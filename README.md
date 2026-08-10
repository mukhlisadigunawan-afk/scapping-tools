# Multi-Platform Scraper for AI Sentiment Analysis

Scraper otomatis berbasis **Python** untuk mengambil postingan/video dan komentar dari **Meta Threads** (`threads.net` / `threads.com`, via Playwright) dan **YouTube** (via **YouTube Data API v3** resmi).

Proyek ini dirancang khusus untuk mengumpulkan dataset komentar bersih yang siap digunakan pada model **AI Sentiment Analysis** (seperti IndoBERT, VADER, atau LLM Fine-Tuning).

---

## ✨ Fitur Utama

- ** Multi-Platform Sekaligus**: Pilih `"platform": ["threads", "youtube"]` di `config.json` untuk scraping 1 keyword yang sama di dua platform dalam satu kali run, atau salah satu saja.
- ** Pemisahan Dataset Per Keyword & Per Platform**: Setiap kata kunci pencarian menghasilkan file `.csv`/`.jsonl` khusus dengan prefix platform (misalnya `threads_sentiment_mbg_makanan_bergizi_gratis.csv`, `youtube_sentiment_mbg_makanan_bergizi_gratis.csv`), serta tetap memperbarui file akumulasi gabungan per platform (`threads_sentiment_all.csv`, `youtube_sentiment_all.csv`).
- ** Auto-Discovery**: Threads dicari berdasarkan kata kunci, daftar akun profil (`target_profiles`), atau direct URL postingan (`target_post_urls`). YouTube dicari berdasarkan kata kunci yang sama, daftar channel (`target_channels`), atau direct URL video (`target_video_urls`).
- ** Komentar Tidak Terbatas (Unlimited)**: Dapat mengambil seluruh komentar hingga selesai dimuat (`"max_comments_per_post": null` untuk Threads, `"max_comments_per_video": null` untuk YouTube).
- ** SQLite Deduplikasi Lintas Platform**: Satu database (`threads_scraper.db`) menyimpan riwayat semua platform, dibedakan lewat kolom `platform`. Postingan/video yang sudah ada akan **otomatis di-skip** agar tidak di-scrape berulang kali.
- ** Sanitasi Teks Siap Pakai untuk AI**: Teks komentar dibersihkan dari spasi ganda dan newline berlebih tanpa merusak emoji, hashtag, atau tanda baca yang krusial untuk analisis sentimen — dengan cleaner yang disesuaikan per platform.
- ** Konfigurasi Mudah (`config.json`)**: Seluruh pengaturan diatur cukup lewat file `config.json` tanpa perlu mengetik parameter panjang di terminal.

---

## 📁 Struktur Proyek

```text
scrapping-tools/
├── config.json.example     # Template konfigurasi berkomentar (ikut di-commit)
├── config.json             # File konfigurasi lokal kamu (gitignored, copy dari .example)
├── main.py                 # Entry point utama program (platform selector)
├── scraper.py              # Engine Playwright untuk Threads (pencarian & ekstraksi komentar)
├── youtube_client.py       # Client YouTube Data API v3 (pencarian video & komentar)
├── database.py             # Pengelola SQLite (deduplikasi & simpan data, multi-platform)
├── utils/
│   ├── cleaner.py          # Pembersihan teks komentar untuk AI Sentiment (per platform)
│   └── exporter.py         # Ekspor data dari SQLite ke CSV & JSONL per keyword & platform
├── data/                   # Folder tempat hasil ekspor dataset (CSV/JSONL)
├── threads_scraper.db      # File database SQLite (otomatis dibuat, dipakai bersama semua platform)
├── auth_state.json         # Session login Threads tersimpan (gitignored, dibuat oleh login.py)
├── requirements.txt        # Dependensi modul Python
├── run.sh                  # Skrip pembantu untuk menjalankan scraper
└── README.md               # Dokumentasi proyek
```

---

## 🛠️ Instalasi & Setup

### Persyaratan
- Python 3.9 atau lebih baru.

### Langkah Instalasi

1. Clone repo dan install dependency (buat `venv`, install package, install browser Chromium):
   ```bash
   git clone https://github.com/mukhlisadigunawan-afk/scapping-tools.git
   cd scapping-tools
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ./venv/bin/playwright install chromium
   source venv/bin/activate
   ```

2. Buat `config.json` dari template `config.json.example` (`config.json` gitignored — tidak ikut ke-commit, jadi aman diisi kredensial asli):
   ```bash
   cp config.json.example config.json
   ```
   `config.json.example` berisi komentar (`//...`) yang menjelaskan tiap field — hapus baris-baris komentar itu setelah kamu selesai menyesuaikan nilainya, karena JSON asli tidak mendukung komentar.

3. Login sekali untuk menyimpan session Threads:
   ```bash
   python login.py
   ```
   Jendela browser akan terbuka ke halaman login Threads — **login manual** di situ (isi email/password & 2FA langsung di browser, tidak lewat file config), lalu tekan Enter di terminal setelah berhasil masuk untuk menyimpan session ke `auth_state.json`. Tanpa login, Threads membatasi jumlah komentar yang bisa dimuat.

4. **Khusus jika ingin scraping YouTube**: buat API key gratis di [Google Cloud Console](https://console.cloud.google.com/) → aktifkan **YouTube Data API v3** → buat API key, lalu isi field `youtube_api_key` di `config.json`. Kuota gratis 10.000 unit/hari — cukup untuk ratusan pencarian keyword atau ribuan pengambilan komentar per hari.

5. Sesuaikan `config.json` jika perlu (termasuk field `platform`), lalu jalankan scraper:
   ```bash
   ./run.sh
   ```

---

## ⚙️ Panduan Konfigurasi (`config.json`)

Sebelum menjalankan scraper, sesuaikan opsi di file **`config.json`**:

```json
{
  "platform": ["threads", "youtube"],
  "search_keyword": ["MBG Makanan Bergizi Gratis"],
  "target_profiles": [],
  "target_post_urls": [],
  "target_channels": [],
  "target_video_urls": [],
  "youtube_video_type": "all",
  "max_posts_per_run": 5,
  "max_comments_per_post": null,
  "max_comments_per_video": null,
  "headless": true,
  "scroll_delay_seconds": 2.0,
  "max_scroll_retries": 5,
  "database_path": "threads_scraper.db",
  "auth_state_path": "auth_state.json",
  "youtube_api_key": "",
  "export_formats": ["csv", "jsonl"],
  "output_directory": "./data"
}
```

Field penting:

- `platform`: `"threads"`, `"youtube"`, atau array keduanya `["threads", "youtube"]` untuk menjalankan 1 keyword yang sama di dua platform sekaligus dalam satu kali `python main.py`.
- `search_keyword` dipakai bersama oleh kedua platform. `target_profiles`/`target_post_urls` khusus Threads; `target_channels`/`target_video_urls` khusus YouTube.
- `max_comments_per_video` khusus YouTube (kalau tidak diisi, ikut nilai `max_comments_per_post`).
- `youtube_api_key` khusus YouTube — aman diisi key asli karena `config.json` gitignored (tidak ikut ke-commit).
- `youtube_video_type` khusus YouTube: `"all"` (default, ambil semua), `"shorts_only"` (cuma YouTube Shorts, heuristik durasi ≤60 detik), `"exclude_shorts"` (skip Shorts, cuma video biasa). Hanya berlaku untuk video hasil `target_channels`/`search_keyword` — kalau kamu isi `target_video_urls` langsung, video itu tetap diambil apa adanya.

---

## 📊 Format Output Dataset (`./data/`)

Setiap kali running, scraper akan menghasilkan dua pasang file **per platform** yang aktif di folder `./data/` (prefix `threads_` atau `youtube_`):

1. **File Khusus Keyword**:
   - `threads_sentiment_<nama_keyword>.csv` / `.jsonl`
   - `youtube_sentiment_<nama_keyword>.csv` / `.jsonl`
   *(Hanya berisi dataset komentar dari pencarian kata kunci tersebut, untuk platform tsb)*

2. **File Akumulasi Gabungan**:
   - `threads_sentiment_all.csv` / `.jsonl`
   - `youtube_sentiment_all.csv` / `.jsonl`
   *(Berisi seluruh akumulasi komentar yang pernah di-scrape di database, per platform)*
