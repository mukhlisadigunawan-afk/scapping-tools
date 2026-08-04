import time
import re
import urllib.parse
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext
from rich.console import Console

from database import DatabaseManager
from utils.cleaner import clean_comment_text, sanitize_raw_text, generate_comment_id

console = Console()

class ThreadsScraper:
    def __init__(self, config: Dict[str, Any], db: DatabaseManager):
        self.config = config
        self.db = db
        self.search_keyword = config.get("search_keyword", "")
        self.target_profiles = config.get("target_profiles", [])
        self.target_post_urls = config.get("target_post_urls", [])
        self.max_posts = config.get("max_posts_per_run", 5)
        self.max_comments = config.get("max_comments_per_post", None)
        self.headless = config.get("headless", False)
        self.remove_emojis = config.get("remove_emojis", True)
        self.scroll_delay = config.get("scroll_delay_seconds", 2.0)
        self.max_retries = config.get("max_scroll_retries", 5)

    def extract_post_id(self, url: str) -> Optional[str]:
        """Ekstraksi post_id unik dari URL Threads."""
        match = re.search(r'/post/([A-Za-z0-9_-]+)', url)
        if match:
            return match.group(1)
        return None

    def discover_posts(self, page: Page) -> List[str]:
        """Mencari postingan Threads dari direct URL, profil target, atau kata kunci pencarian."""
        discovered_urls = []

        # 1. Dari Direct Post URLs di config
        if self.target_post_urls:
            console.print(f"[bold cyan][Discovery][/bold cyan] Menggunakan {len(self.target_post_urls)} direct post URL dari config.")
            for url in self.target_post_urls:
                post_id = self.extract_post_id(url)
                if post_id and not self.db.is_post_scraped(post_id):
                    discovered_urls.append(url)
                elif post_id:
                    console.print(f"[yellow][SKIP][/yellow] Post ID [bold]{post_id}[/bold] sudah ada di SQLite. Melompati...")

        # 2. Dari Profil Target jika diisi di config
        if self.target_profiles and len(discovered_urls) < self.max_posts:
            for profile in self.target_profiles:
                if len(discovered_urls) >= self.max_posts:
                    break
                
                clean_profile = profile.strip().lstrip('@')
                profile_url = f"https://www.threads.com/@{clean_profile}"
                console.print(f"[bold cyan][Discovery][/bold cyan] Membuka profil: [underline]{profile_url}[/underline]")
                
                try:
                    page.goto(profile_url, wait_until="domcontentloaded")
                    time.sleep(3.0)

                    # Scroll untuk memuat lebih banyak postingan profil
                    for _ in range(3):
                        links = page.eval_on_selector_all("a[href*='/post/']", "elements => elements.map(e => e.href)")
                        for link in links:
                            post_id = self.extract_post_id(link)
                            if post_id:
                                clean_url = f"https://www.threads.com/@{clean_profile}/post/{post_id}"
                                if clean_url not in discovered_urls:
                                    if self.db.is_post_scraped(post_id):
                                        console.print(f"[yellow][SKIP][/yellow] Post ID [bold]{post_id}[/bold] sudah ada di SQLite.")
                                    else:
                                        discovered_urls.append(clean_url)
                                        console.print(f"[green][FOUND][/green] Menemukan postingan: [bold]{clean_url}[/bold]")
                                        if len(discovered_urls) >= self.max_posts:
                                            break
                        page.evaluate("window.scrollBy(0, 800)")
                        time.sleep(1.5)
                except Exception as e:
                    console.print(f"[red][ERROR][/red] Gagal mengakses profil {profile}: {e}")

        # 3. Dari Kata Kunci Pencarian (jika discovered_urls masih kurang dari max_posts)
        if self.search_keyword and len(discovered_urls) < self.max_posts:
            # Siapkan variasi query jika kata kunci berisi beberapa istilah/hashtag
            query_terms = [self.search_keyword]
            terms_split = [t.strip() for t in self.search_keyword.split() if len(t.strip()) > 1]
            if len(terms_split) > 1:
                query_terms.extend(terms_split)

            for term in query_terms:
                if len(discovered_urls) >= self.max_posts:
                    break

                encoded_keyword = urllib.parse.quote(term)
                search_url = f"https://www.threads.com/search?q={encoded_keyword}"
                console.print(f"[bold cyan][Discovery][/bold cyan] Membuka pencarian keyword: [underline]{search_url}[/underline]")
                
                try:
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(3.0)

                    retries = 0
                    while len(discovered_urls) < self.max_posts and retries < self.max_retries:
                        links = page.eval_on_selector_all("a[href*='/post/']", "elements => elements.map(e => e.href)")
                        new_found = 0

                        for link in links:
                            post_id = self.extract_post_id(link)
                            if post_id:
                                clean_url = f"https://www.threads.com/post/{post_id}"
                                if clean_url not in discovered_urls:
                                    if self.db.is_post_scraped(post_id):
                                        console.print(f"[yellow][SKIP][/yellow] Post ID [bold]{post_id}[/bold] sudah ada di SQLite.")
                                    else:
                                        discovered_urls.append(clean_url)
                                        new_found += 1
                                        console.print(f"[green][FOUND][/green] Menemukan postingan pencarian ('{term}'): [bold]{clean_url}[/bold]")
                                        if len(discovered_urls) >= self.max_posts:
                                            break

                        if new_found == 0:
                            retries += 1
                        else:
                            retries = 0

                        page.evaluate("window.scrollBy(0, 1000)")
                        time.sleep(self.scroll_delay)

                except Exception as e:
                    console.print(f"[red][ERROR][/red] Gagal pencarian keyword '{term}': {e}")

        console.print(f"[bold green][Discovery Selesai][/bold green] Total [bold]{len(discovered_urls)}[/bold] postingan siap di-scrape.")
        return discovered_urls

    def scrape_post_comments(self, page: Page, post_url: str) -> List[Dict[str, Any]]:
        """Mengambil seluruh/sebagian komentar dari postingan tertentu."""
        post_id = self.extract_post_id(post_url)
        if not post_id:
            return []

        console.print(f"\n[bold blue][Scraping Post][/bold blue] Membuka URL: {post_url}")
        page.goto(post_url, wait_until="domcontentloaded")
        time.sleep(3.0)

        scraped_comments = []
        seen_comment_ids = set()
        retries_without_new = 0

        while True:
            if self.max_comments is not None and self.max_comments > 0:
                if len(scraped_comments) >= self.max_comments:
                    console.print(f"[yellow][LIMIT][/yellow] Mencapai batas maksimum komentar ({self.max_comments}) untuk post ini.")
                    break

            # Ambil elemen komentar / baris teks dari DOM Threads
            comment_blocks = page.query_selector_all("div[data-pressable-container='true'], div[style*='border-bottom']")
            initial_count = len(scraped_comments)

            for block in comment_blocks:
                try:
                    text_content = block.inner_text().strip()
                    if not text_content or len(text_content) < 3:
                        continue

                    # Cari username pengirim komentar (link berformat /@username)
                    user_elem = block.query_selector("a[href*='/@']")
                    username = ""
                    if user_elem:
                        href = user_elem.get_attribute("href") or ""
                        match = re.search(r'/@([A-Za-z0-9_.-]+)', href)
                        if match:
                            username = match.group(1)

                    cleaned_text = clean_comment_text(text_content, strip_emojis=self.remove_emojis)
                    
                    # Bersihkan jika username terbaca ulang di dalam teks
                    if username and cleaned_text.startswith(username):
                        cleaned_text = clean_comment_text(cleaned_text[len(username):])

                    # Filter frasa UI standar Threads yang bukan komentar asli
                    ignore_phrases = ["Translate", "Log in", "Reply", "View replies", "Terms of Use", "Privacy Policy"]
                    if any(cleaned_text == phrase for phrase in ignore_phrases) or len(cleaned_text) < 2:
                        continue

                    sanitized_raw = sanitize_raw_text(text_content)
                    c_id = generate_comment_id(post_id, username, cleaned_text)
                    if c_id not in seen_comment_ids:
                        seen_comment_ids.add(c_id)
                        
                        comment_data = {
                            "comment_id": c_id,
                            "post_id": post_id,
                            "username": username or "anonymous",
                            "raw_text": sanitized_raw,
                            "cleaned_text": cleaned_text,
                            "like_count": 0,
                            "reply_count": 0,
                            "is_reply": False
                        }
                        scraped_comments.append(comment_data)

                        if self.max_comments is not None and self.max_comments > 0:
                            if len(scraped_comments) >= self.max_comments:
                                break

                except Exception as e:
                    continue

            new_added = len(scraped_comments) - initial_count
            if new_added > 0:
                retries_without_new = 0
                console.print(f"  └─ Total komentar dikumpulkan: [bold green]{len(scraped_comments)}[/bold green]")
            else:
                retries_without_new += 1

            if retries_without_new >= self.max_retries:
                console.print(f"[magenta][FINISHED][/magenta] Seluruh komentar selesai dimuat atau tidak ada komentar baru setelah {self.max_retries}x scroll.")
                break

            page.evaluate("window.scrollBy(0, 1000)")
            time.sleep(self.scroll_delay)

        return scraped_comments

    def run(self):
        """Jalankan siklus scraping lengkap."""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900}
            )
            page = context.new_page()

            try:
                target_urls = self.discover_posts(page)

                if not target_urls:
                    console.print("[yellow][NOTICE][/yellow] Tidak ada postingan baru yang perlu di-scrape.")
                    return

                for index, url in enumerate(target_urls, 1):
                    post_id = self.extract_post_id(url)
                    console.print(f"\n[bold magenta]=== Processing Post [{index}/{len(target_urls)}] ===[/bold magenta]")
                    
                    comments = self.scrape_post_comments(page, url)
                    
                    if comments:
                        self.db.save_comments(comments)
                    self.db.save_post(
                        post_id=post_id,
                        url=url,
                        keyword=self.search_keyword,
                        comments_count=len(comments),
                        status="COMPLETED"
                    )
                    console.print(f"[green][SUCCESS][/green] Tersimpan [bold]{len(comments)}[/bold] komentar dari post {post_id} ke SQLite.")

            finally:
                browser.close()
