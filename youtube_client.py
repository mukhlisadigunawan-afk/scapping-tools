import re
from typing import List, Dict, Any, Optional
import requests
from rich.console import Console

from database import DatabaseManager
from utils.cleaner import clean_youtube_comment_text, sanitize_raw_text, generate_comment_id

console = Console()

API_BASE = "https://www.googleapis.com/youtube/v3"
VALID_VIDEO_TYPES = ("all", "shorts_only", "exclude_shorts")
SHORTS_MAX_DURATION_SECONDS = 60  # YouTube API tidak punya flag "isShort" resmi; ini heuristik durasi standar Shorts.


class YouTubeQuotaExceeded(Exception):
    """Dilempar ketika kuota harian YouTube Data API habis."""
    pass


class YouTubeScraper:
    def __init__(self, config: Dict[str, Any], db: DatabaseManager):
        self.config = config
        self.db = db

        search_keyword = config.get("search_keyword", [])
        self.search_keywords = [search_keyword] if isinstance(search_keyword, str) else search_keyword
        self.target_channels = config.get("target_channels", [])
        self.target_video_urls = config.get("target_video_urls", [])
        self.max_posts = config.get("max_posts_per_run", 5)
        max_comments = config.get("max_comments_per_video", config.get("max_comments_per_post", None))
        self.max_comments = max_comments
        self.remove_emojis = config.get("remove_emojis", True)
        self.url_keyword_map: Dict[str, str] = {}
        self.api_key = self._load_api_key(config)

        video_type = config.get("youtube_video_type", "all")
        if video_type not in VALID_VIDEO_TYPES:
            console.print(f"[yellow][WARNING][/yellow] youtube_video_type '{video_type}' tidak dikenali, pakai default 'all'. Pilihan valid: {VALID_VIDEO_TYPES}")
            video_type = "all"
        self.video_type = video_type

    def _load_api_key(self, config: Dict[str, Any]) -> str:
        api_key = (config.get("youtube_api_key") or "").strip()
        if not api_key:
            console.print(
                "[bold red][ERROR][/bold red] Isi field 'youtube_api_key' di config.json terlebih dahulu "
                "(buat API key di Google Cloud Console -> aktifkan YouTube Data API v3)."
            )
            raise SystemExit(1)
        return api_key

    def _api_get(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Panggil endpoint YouTube Data API v3, menangani quota/error umum."""
        params = {**params, "key": self.api_key}
        resp = requests.get(f"{API_BASE}/{endpoint}", params=params, timeout=30)

        if resp.status_code == 200:
            return resp.json()

        try:
            error_info = resp.json().get("error", {})
        except ValueError:
            error_info = {}
        reasons = [e.get("reason", "") for e in error_info.get("errors", [])]

        if resp.status_code == 403 and "quotaExceeded" in reasons:
            raise YouTubeQuotaExceeded("Kuota harian YouTube Data API telah habis.")
        if resp.status_code == 403 and "commentsDisabled" in reasons:
            return None
        if resp.status_code == 404:
            return None

        console.print(f"[red][ERROR][/red] YouTube API {endpoint} gagal ({resp.status_code}): {error_info.get('message', resp.text[:200])}")
        return None

    def _parse_iso8601_duration_seconds(self, duration: str) -> int:
        """Parse durasi ISO 8601 dari YouTube API (mis. 'PT1M30S', 'PT45S') jadi total detik."""
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration or "")
        if not match:
            return 0
        hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    def _filter_by_video_type(self, video_ids: List[str]) -> List[str]:
        """Saring video_id berdasarkan config 'youtube_video_type' (all / shorts_only / exclude_shorts)."""
        if self.video_type == "all" or not video_ids:
            return video_ids

        accepted = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            data = self._api_get("videos", {"part": "contentDetails", "id": ",".join(batch)})
            if not data:
                continue

            duration_by_id = {
                item["id"]: self._parse_iso8601_duration_seconds(item["contentDetails"]["duration"])
                for item in data.get("items", [])
            }
            for video_id in batch:
                duration = duration_by_id.get(video_id)
                if duration is None:
                    continue
                is_short = duration <= SHORTS_MAX_DURATION_SECONDS
                if (self.video_type == "shorts_only" and is_short) or (self.video_type == "exclude_shorts" and not is_short):
                    accepted.append(video_id)

        return accepted

    def extract_video_id(self, url: str) -> Optional[str]:
        """Ekstraksi video_id dari berbagai format URL YouTube."""
        patterns = [
            r'youtu\.be/([A-Za-z0-9_-]{11})',
            r'[?&]v=([A-Za-z0-9_-]{11})',
            r'youtube\.com/embed/([A-Za-z0-9_-]{11})',
            r'youtube\.com/shorts/([A-Za-z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _resolve_uploads_playlist_id(self, channel: str) -> Optional[str]:
        """Cari playlist 'uploads' milik sebuah channel (handle @nama, channel ID UCxxxx, atau nama biasa)."""
        channel = channel.strip()
        params = {"part": "contentDetails"}
        if channel.startswith("UC") and len(channel) == 24:
            params["id"] = channel
        elif channel.startswith("@"):
            params["forHandle"] = channel
        else:
            params["forHandle"] = f"@{channel}"

        data = self._api_get("channels", params)
        items = (data or {}).get("items", [])

        if not items:
            # Fallback: cari via search.list (lebih mahal kuotanya, dipakai hanya jika forHandle gagal)
            search_data = self._api_get("search", {"part": "snippet", "q": channel, "type": "channel", "maxResults": 1})
            search_items = (search_data or {}).get("items", [])
            if not search_items:
                return None
            channel_id = search_items[0]["snippet"]["channelId"]
            data = self._api_get("channels", {"part": "contentDetails", "id": channel_id})
            items = (data or {}).get("items", [])
            if not items:
                return None

        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def discover_videos(self) -> List[str]:
        """Mencari video_id dari direct URL, channel target, atau kata kunci pencarian."""
        discovered: List[str] = []

        # 1. Direct video URLs
        if self.target_video_urls:
            console.print(f"[bold cyan][Discovery][/bold cyan] Menggunakan {len(self.target_video_urls)} direct video URL dari config.")
            for url in self.target_video_urls:
                video_id = self.extract_video_id(url)
                if video_id and not self.db.is_post_scraped(video_id, platform="youtube"):
                    discovered.append(video_id)
                elif video_id:
                    console.print(f"[yellow][SKIP][/yellow] Video ID [bold]{video_id}[/bold] sudah ada di SQLite. Melompati...")

        # 2. Target channels
        if self.target_channels and len(discovered) < self.max_posts:
            for channel in self.target_channels:
                if len(discovered) >= self.max_posts:
                    break
                console.print(f"[bold cyan][Discovery][/bold cyan] Membuka channel: [underline]{channel}[/underline]")
                uploads_playlist_id = self._resolve_uploads_playlist_id(channel)
                if not uploads_playlist_id:
                    console.print(f"[red][ERROR][/red] Channel '{channel}' tidak ditemukan.")
                    continue

                page_token = None
                while len(discovered) < self.max_posts:
                    params = {"part": "snippet", "playlistId": uploads_playlist_id, "maxResults": 50}
                    if page_token:
                        params["pageToken"] = page_token
                    data = self._api_get("playlistItems", params)
                    if not data:
                        break

                    page_candidates = []
                    for item in data.get("items", []):
                        video_id = item["snippet"]["resourceId"]["videoId"]
                        if video_id in discovered or video_id in page_candidates:
                            continue
                        if self.db.is_post_scraped(video_id, platform="youtube"):
                            console.print(f"[yellow][SKIP][/yellow] Video ID [bold]{video_id}[/bold] sudah ada di SQLite.")
                            continue
                        page_candidates.append(video_id)

                    for video_id in self._filter_by_video_type(page_candidates):
                        if len(discovered) >= self.max_posts:
                            break
                        discovered.append(video_id)
                        console.print(f"[green][FOUND][/green] Menemukan video: [bold]{video_id}[/bold]")

                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break

        # 3. Search keyword (paling mahal kuotanya: 100 unit per call)
        if self.search_keywords and len(discovered) < self.max_posts:
            for keyword in self.search_keywords:
                if len(discovered) >= self.max_posts:
                    break

                console.print(f"[bold cyan][Discovery][/bold cyan] Pencarian keyword YouTube: [underline]{keyword}[/underline]")
                page_token = None
                while len(discovered) < self.max_posts:
                    params = {"part": "snippet", "q": keyword, "type": "video", "maxResults": 50}
                    if page_token:
                        params["pageToken"] = page_token
                    data = self._api_get("search", params)
                    if not data:
                        break

                    page_candidates = []
                    for item in data.get("items", []):
                        video_id = item.get("id", {}).get("videoId")
                        if not video_id or video_id in discovered or video_id in page_candidates:
                            continue
                        if self.db.is_post_scraped(video_id, platform="youtube"):
                            console.print(f"[yellow][SKIP][/yellow] Video ID [bold]{video_id}[/bold] sudah ada di SQLite.")
                            continue
                        page_candidates.append(video_id)

                    for video_id in self._filter_by_video_type(page_candidates):
                        if len(discovered) >= self.max_posts:
                            break
                        discovered.append(video_id)
                        self.url_keyword_map[video_id] = keyword
                        console.print(f"[green][FOUND][/green] Menemukan video pencarian ('{keyword}'): [bold]{video_id}[/bold]")

                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break

        console.print(f"[bold green][Discovery Selesai][/bold green] Total [bold]{len(discovered)}[/bold] video siap di-scrape.")
        return discovered

    def _comment_from_snippet(self, video_id: str, snippet: Dict[str, Any], is_reply: bool) -> Dict[str, Any]:
        username = snippet.get("authorDisplayName", "") or "anonymous"
        raw_text = snippet.get("textOriginal", "") or snippet.get("textDisplay", "")
        cleaned_text = clean_youtube_comment_text(raw_text, strip_emojis=self.remove_emojis)
        sanitized_raw = sanitize_raw_text(raw_text)
        comment_id = generate_comment_id(video_id, username, cleaned_text)
        return {
            "comment_id": comment_id,
            "post_id": video_id,
            "username": username,
            "raw_text": sanitized_raw,
            "cleaned_text": cleaned_text,
            "like_count": snippet.get("likeCount", 0),
            "reply_count": 0,
            "is_reply": is_reply,
        }

    def scrape_video_comments(self, video_id: str) -> Optional[List[Dict[str, Any]]]:
        """Mengambil komentar (top-level + replies) dari sebuah video via commentThreads.list."""
        console.print(f"\n[bold blue][Scraping Video][/bold blue] video_id: {video_id}")

        scraped_comments: List[Dict[str, Any]] = []
        seen_comment_ids = set()
        page_token = None

        while True:
            if self.max_comments is not None and self.max_comments > 0:
                if len(scraped_comments) >= self.max_comments:
                    console.print(f"[yellow][LIMIT][/yellow] Mencapai batas maksimum komentar ({self.max_comments}) untuk video ini.")
                    break

            params = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": 100,
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token

            data = self._api_get("commentThreads", params)
            if data is None:
                # commentsDisabled, video tidak ditemukan, atau error non-fatal lain
                break

            for thread in data.get("items", []):
                top_snippet = thread["snippet"]["topLevelComment"]["snippet"]
                top_comment = self._comment_from_snippet(video_id, top_snippet, is_reply=False)
                top_comment["reply_count"] = thread["snippet"].get("totalReplyCount", 0)

                if top_comment["comment_id"] not in seen_comment_ids:
                    seen_comment_ids.add(top_comment["comment_id"])
                    scraped_comments.append(top_comment)
                    if self.max_comments and len(scraped_comments) >= self.max_comments:
                        break

                for reply in thread.get("replies", {}).get("comments", []):
                    if self.max_comments and len(scraped_comments) >= self.max_comments:
                        break
                    reply_comment = self._comment_from_snippet(video_id, reply["snippet"], is_reply=True)
                    if reply_comment["comment_id"] not in seen_comment_ids:
                        seen_comment_ids.add(reply_comment["comment_id"])
                        scraped_comments.append(reply_comment)

            console.print(f"  └─ Total komentar dikumpulkan: [bold green]{len(scraped_comments)}[/bold green]")

            page_token = data.get("nextPageToken")
            if not page_token:
                console.print("[magenta][FINISHED][/magenta] Seluruh komentar video ini selesai diambil.")
                break

        return scraped_comments

    def run(self):
        """Jalankan siklus scraping YouTube lengkap (discovery -> scrape komentar -> simpan ke SQLite)."""
        try:
            video_ids = self.discover_videos()
        except YouTubeQuotaExceeded as e:
            console.print(f"[bold red][QUOTA HABIS][/bold red] {e} Hentikan run YouTube untuk hari ini.")
            return

        if not video_ids:
            console.print("[yellow][NOTICE][/yellow] Tidak ada video baru yang perlu di-scrape.")
            return

        for index, video_id in enumerate(video_ids, 1):
            console.print(f"\n[bold magenta]=== Processing Video [{index}/{len(video_ids)}] ===[/bold magenta]")
            url = f"https://www.youtube.com/watch?v={video_id}"

            try:
                comments = self.scrape_video_comments(video_id)
            except YouTubeQuotaExceeded as e:
                console.print(f"[bold red][QUOTA HABIS][/bold red] {e} Hentikan run YouTube untuk hari ini.")
                break

            if comments is None:
                self.db.save_post(
                    post_id=video_id, url=url, keyword=self.url_keyword_map.get(video_id, ""),
                    comments_count=0, status="FAILED", platform="youtube"
                )
                console.print(f"[red][SKIPPED][/red] Video {video_id} gagal dimuat, lanjut ke video berikutnya.")
                continue

            if comments:
                self.db.save_comments(comments)
            self.db.save_post(
                post_id=video_id, url=url, keyword=self.url_keyword_map.get(video_id, ""),
                comments_count=len(comments), status="COMPLETED", platform="youtube"
            )
            console.print(f"[green][SUCCESS][/green] Tersimpan [bold]{len(comments)}[/bold] komentar dari video {video_id} ke SQLite.")
