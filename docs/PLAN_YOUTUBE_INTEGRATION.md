# Plan: Integrasi YouTube (via YouTube Data API v3)

Status: **sudah diimplementasikan**, dengan 2 penyesuaian dari plan awal ini (lihat `CLAUDE.md`/`README.md` untuk kondisi final):

- API key YouTube disimpan langsung di field `youtube_api_key` pada `config.json` (bukan file terpisah `youtube_config.json`). Konsekuensinya: `config.json` git-tracked, jadi jangan commit file itu saat `youtube_api_key` terisi key asli.
- Login Threads (`login.py`) tidak lagi pakai `auth_config.json`/auto-fill kredensial — sekarang selalu login manual di jendela browser yang terbuka.

Sisa dokumen di bawah ini adalah plan **awal** (referensi historis) dan tidak sepenuhnya mencerminkan kode final untuk 2 poin di atas.

## 1. Keputusan dasar

- **Tidak scraping DOM/Playwright untuk YouTube.** Pakai **YouTube Data API v3** resmi (gratis, kuota harian 10.000 unit). Ini lebih stabil daripada scraping dan sudah cukup untuk kebutuhan: cari video by keyword, ambil komentar video.
- **Akses cukup pakai API key** (tidak perlu OAuth) karena kita cuma baca data publik (`search.list`, `videos.list`, `commentThreads.list`, `comments.list`, `playlistItems.list`).
- **Estimasi kuota** (unit per call):
  - `search.list` (cari video by keyword) = **100 unit**
  - `commentThreads.list` (ambil komentar top-level, max 100/request) = **1 unit**
  - `comments.list` (ambil balasan/replies) = **1 unit**
  - `videos.list`, `channels.list`, `playlistItems.list` = **1 unit**
  - Dengan kuota 10.000/hari: ± 100x pencarian keyword, atau ribuan kali fetch komentar. `search.list` adalah operasi termahal → batasi jumlah keyword & video per run.
- **Reuse arsitektur existing:** `DatabaseManager` dan `export_dataset()` dipakai ulang dengan penambahan kolom `platform`. Pipeline scraping YouTube jadi modul baru (`youtube_client.py`), paralel dengan `scraper.py`, bukan menggantikannya.

## 2. Kredensial

- Buat API key baru di Google Cloud Console → aktifkan **YouTube Data API v3** → generate API key (restrict ke YouTube Data API v3 saja untuk keamanan).
- Simpan di file baru **`youtube_config.json`** (pola sama seperti `auth_config.json` untuk Threads) — **gitignored**, tidak pernah masuk `config.json` yang git-tracked.
  ```json
  { "api_key": "AIzaSy..." }
  ```
- Tambahkan `youtube_config.json` ke `.gitignore`.

## 3. Perubahan skema database (`database.py`)

- Tambah kolom `platform TEXT DEFAULT 'threads'` ke tabel `posts` (lewat `ALTER TABLE ... ADD COLUMN` dibungkus try/except untuk DB lama yang belum punya kolom ini — kompatibel dengan `threads_scraper.db` yang sudah ada).
- `post_id` untuk YouTube pakai **video ID asli dari API** (unik secara global di YouTube), disimpan apa adanya — tidak perlu prefix, karena `posts.post_id` sudah cukup sebagai primary key selama tidak bentrok. Video ID YouTube (11 karakter base64url) dan post ID Threads (string base64-like beda pola) praktis tidak akan bentrok, tapi untuk aman kolom `platform` dipakai sebagai pembeda saat query/filter, bukan mengandalkan keunikan format ID.
- `save_post()` dan `is_post_scraped()` dapat parameter `platform: str = "threads"` (default menjaga backward-compat pemanggilan lama dari `scraper.py`).
- `get_comments_dataframe()` dapat parameter opsional `platform: Optional[str] = None` untuk filter, ditambahkan ke `SELECT`.
- Tabel `comments` **tidak berubah** — platform bisa didapat lewat JOIN ke `posts.platform`.

## 4. Modul baru: `youtube_client.py`

Class `YouTubeScraper` (nama disamakan gaya dengan `ThreadsScraper`, tapi berbasis HTTP request ke API, bukan Playwright):

- Dependency baru: `requests` (ringan, cukup untuk REST call ke `https://www.googleapis.com/youtube/v3/...`; **hindari** `google-api-python-client` karena berat dan tidak dibutuhkan untuk read-only + API key).
- Constructor: baca `config.json` (keyword/channel/video target, max results) + `youtube_config.json` (api_key).
- `discover_videos()` — prioritas sama seperti Threads (direct URL → channel → keyword):
  1. `target_video_urls` — ekstrak video ID langsung dari URL (`youtu.be/<id>`, `watch?v=<id>`).
  2. `target_channels` — resolve channel → `channels.list` (ambil `uploads` playlist ID) → `playlistItems.list` untuk daftar video terbaru.
  3. `search_keyword` (reuse key config yang sama dengan Threads, looping semua keyword) — `search.list(q=keyword, type=video, order=relevance, maxResults=50)`, paginasi via `pageToken` sampai `max_posts_per_run` tercapai.
  - Setiap kandidat video_id dicek `db.is_post_scraped(video_id, platform="youtube")` sebelum ditambahkan — dedup sama seperti Threads.
- `scrape_video_comments(video_id)` — `commentThreads.list(videoId=..., part=snippet,replies, textFormat=plainText, maxResults=100)`, paginasi via `nextPageToken` sampai `max_comments_per_post` tercapai atau habis. Ambil top-level comment + replies (dari field `replies.comments` kalau `totalReplyCount` kecil, atau `comments.list(parentId=...)` kalau replies terpotong).
- Tangani `commentsDisabled` (video yang mematikan kolom komentar → skip, tandai status `COMPLETED` dengan 0 komentar, bukan `FAILED`) dan `quotaExceeded` (403 → hentikan run lebih awal dengan pesan jelas, jangan retry-loop yang menghabiskan kuota sisa).
- `run()` — orkestrasi: discover → loop scrape per video → `db.save_comments()` + `db.save_post(..., platform="youtube")`, mirror struktur `ThreadsScraper.run()`.

## 5. Perubahan `utils/cleaner.py`

- Komentar dari YouTube API sudah berupa teks bersih (`textFormat=plainText`, tanpa "chrome" UI seperti timestamp/like-count yang menempel di `innerText` DOM Threads) — jadi **tidak perlu** logic baris-per-baris `clean_comment_text` yang spesifik ke Threads (deteksi `12h`, `4d`, "Translate", dll).
- Tambah fungsi baru `clean_youtube_comment_text(raw_text, strip_emojis=True)`: cukup `remove_emojis()` (reuse) + collapse whitespace + `sanitize_raw_text()` (reuse, karena YouTube comment bisa multi-baris).
- `generate_comment_id(post_id, username, text)` — reuse langsung, tidak perlu diubah.

## 6. Perubahan `config.json` (skema baru, backward-compatible)

```json
{
  "platform": "threads",        // BARU — "threads" | "youtube". Default "threads" agar config lama tetap jalan.
  "search_keyword": ["kepala bgn", "MBG", "bahlil", "pajak"],
  "target_profiles": [],
  "target_post_urls": [],

  "target_channels": [],        // BARU — khusus platform youtube
  "target_video_urls": [],      // BARU — khusus platform youtube
  "max_comments_per_video": 0,  // BARU — analog max_comments_per_post

  "max_posts_per_run": 100,
  "max_comments_per_post": 0,
  ...
}
```

- `search_keyword` dipakai ulang apa adanya untuk kedua platform supaya tidak duplikasi config.
- Field `target_channels`/`target_video_urls`/`max_comments_per_video` diabaikan sepenuhnya kalau `platform: "threads"`.

## 7. Perubahan `main.py`

- Baca `config.get("platform", "threads")`.
- Dispatch: `platform == "youtube"` → import & jalankan `YouTubeScraper`; selain itu → `ThreadsScraper` (existing, default, tidak berubah perilakunya).
- `export_dataset()` dapat parameter `platform=platform` supaya nama file output beda prefix (`youtube_sentiment_<slug>.csv` vs `threads_sentiment_<slug>.csv`) — hindari file YouTube menimpa/bercampur file Threads di folder `data/` yang sama.

## 8. Perubahan `utils/exporter.py`

- `export_dataset()` dapat parameter `platform: str = "threads"`.
- Prefix nama file jadi dinamis: `f"{platform}_sentiment_{slug}.csv"` dan `f"{platform}_sentiment_all.csv"` (menggantikan hardcode `"threads_sentiment_"`).
- `db.get_comments_dataframe(keyword=..., platform=platform)` — teruskan filter platform supaya file `youtube_sentiment_all.csv` tidak ikut memuat baris komentar Threads.

## 9. Error handling & rate limit khusus YouTube

- Hormati kemungkinan **403 `quotaExceeded`**: begitu terjadi, log jelas ke console (Bahasa Indonesia, konsisten gaya existing) dan hentikan run dengan graceful — jangan retry loop yang sia-sia menghabiskan kuota besok.
- Hormati **429/backoff**: kalau kena rate limit sesaat, retry dengan exponential backoff (2-3x max), bukan infinite retry.
- Video privat/dihapus/`commentsDisabled` → tangani sebagai kasus normal (bukan exception fatal), tandai `status` di tabel `posts` sesuai kondisi.

## 10. Testing / validasi manual

1. Buat API key, isi `youtube_config.json`.
2. Set `config.json`: `platform: "youtube"`, 1 keyword, `max_posts_per_run: 3`, `max_comments_per_video: 20` — run kecil dulu untuk validasi kuota & parsing sebelum scale up.
3. Cek `threads_scraper.db` (atau rename jadi `scraper.db` generik — lihat poin 11) — pastikan baris baru di `posts` punya `platform='youtube'` dan tidak bentrok dengan data Threads lama.
4. Cek file export `data/youtube_sentiment_<slug>.csv` — pastikan `cleaned_text` bersih dan CSV tetap 1 baris per record (tidak pecah karena newline di komentar YouTube yang sering multi-paragraf).
5. Jalankan ulang run yang sama → pastikan video yang sudah di-scrape ke-skip (dedup jalan).

## 11. Hal yang perlu didiskusikan/diputuskan sebelum eksekusi

- **Nama database file**: `threads_scraper.db` saat ini platform-specific di namanya. Opsi: (a) tetap satu file itu untuk semua platform (kolom `platform` sebagai pembeda) — lebih simpel, direkomendasikan; atau (b) file DB terpisah per platform (`youtube_scraper.db`) — lebih terisolasi tapi menduplikasi kode dedup lintas file. **Rekomendasi: opsi (a)**, cukup ubah default `database_path` jadi lebih generik di `config.json` kalau user mau, tanpa migrasi paksa (kode lama tetap jalan apa adanya).
- **Replies (balasan komentar)**: apakah replies dihitung sebagai row terpisah dengan `is_reply=1` (sudah ada kolomnya di skema `comments`, tinggal dipakai) — asumsi plan ini: ya, disertakan.
- **Update `CLAUDE.md` & `README.md`**: setelah implementasi selesai, kedua file ini perlu diperbarui untuk mendokumentasikan arsitektur multi-platform (di luar scope plan ini, dilakukan saat implementasi).

## 12. Ringkasan file yang disentuh

| File | Perubahan |
|---|---|
| `youtube_config.json` | **Baru** (gitignored) — API key |
| `.gitignore` | Tambah `youtube_config.json` |
| `requirements.txt` | Tambah `requests` |
| `database.py` | Kolom `platform` di tabel `posts`; param `platform` di `save_post`, `is_post_scraped`, `get_comments_dataframe` |
| `youtube_client.py` | **Baru** — `YouTubeScraper` (discovery + scrape comments via API) |
| `utils/cleaner.py` | Tambah `clean_youtube_comment_text()` |
| `utils/exporter.py` | Param `platform` untuk penamaan file & filter query |
| `config.json` | Tambah `platform`, `target_channels`, `target_video_urls`, `max_comments_per_video` |
| `main.py` | Dispatch `ThreadsScraper` vs `YouTubeScraper` berdasarkan `config["platform"]` |
