# Meta Threads Scraper for AI Sentiment Analysis

Web scraper otomatis berbasis **Python** & **Playwright** untuk mengambil postingan dan komentar dari **Meta Threads** (`threads.net` / `threads.com`). 

Proyek ini dirancang khusus untuk mengumpulkan dataset komentar bersih yang siap digunakan pada model **AI Sentiment Analysis** (seperti IndoBERT, VADER, atau LLM Fine-Tuning).

---

## ✨ Fitur Utama

- ** Pemisahan Dataset Per Keyword**: Setiap kata kunci pencarian akan menghasilkan file `.csv` dan `.jsonl` khusus (misalnya `threads_sentiment_mbg_makanan_bergizi_gratis.csv`), serta tetap memperbarui file akumulasi gabungan `threads_sentiment_all.csv`.
- ** Auto-Discovery Postingan**: Mencari postingan secara otomatis berdasarkan kata kunci pencarian (*search keyword*), daftar akun profil (`target_profiles`), atau direct URL postingan (`target_post_urls`).
- ** Komentar Tidak Terbatas (Unlimited)**: Dapat mengambil seluruh komentar pada postingan hingga selesai dimuat (`"max_comments_per_post": null`).
- ** SQLite Deduplikasi**: Menyimpan riwayat postingan yang telah di-scrape ke dalam database `threads_scraper.db`. Postingan yang sudah ada di database akan **otomatis di-skip** agar tidak di-scrape berulang kali.
- ** Sanitasi Teks Siap Pakai untuk AI**: Teks komentar dibersihkan dari spasi ganda dan newline berlebih tanpa merusak emoji, hashtag, atau tanda baca yang krusial untuk analisis sentimen.
- ** Konfigurasi Mudah (`config.json`)**: Seluruh pengaturan diatur cukup lewat file `config.json` tanpa perlu mengetik parameter panjang di terminal.

---

## 📁 Struktur Proyek

```text
scrapping-tools/
├── config.json          # File konfigurasi utama scraper
├── main.py              # Entry point utama program
├── scraper.py           # Engine Playwright untuk pencarian & ekstraksi komentar
├── database.py          # Pengelola SQLite (deduplikasi & simpan data)
├── utils/
│   ├── cleaner.py       # Pembersihan teks komentar untuk AI Sentiment
│   └── exporter.py      # Ekspor data dari SQLite ke CSV & JSONL per keyword
├── data/                # Folder tempat hasil ekspor dataset (CSV/JSONL)
├── threads_scraper.db   # File database SQLite (otomatis dibuat)
├── requirements.txt     # Dependensi modul Python
├── run.sh               # Skrip pembantu untuk menjalankan scraper
└── README.md            # Dokumentasi proyek
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

2. Buat file `auth_config.json` (tidak ikut di-clone karena berisi kredensial) berisi akun Threads:
   ```json
   {
     "username": "email_atau_username_kamu",
     "password": "password_kamu"
   }
   ```

3. Login sekali untuk menyimpan session:
   ```bash
   python login.py
   ```
   Tanpa login, Threads membatasi jumlah komentar yang bisa dimuat.

4. Sesuaikan `config.json` jika perlu, lalu jalankan scraper:
   ```bash
   ./run.sh
   ```

---

## ⚙️ Panduan Konfigurasi (`config.json`)

Sebelum menjalankan scraper, sesuaikan opsi di file **`config.json`**:

```json
{
  "search_keyword": ["MBG Makanan Bergizi Gratis"],
  "target_profiles": [],
  "target_post_urls": [],
  "max_posts_per_run": 5,
  "max_comments_per_post": null,
  "headless": true,
  "scroll_delay_seconds": 2.0,
  "max_scroll_retries": 5,
  "database_path": "threads_scraper.db",
  "export_formats": ["csv", "jsonl"],
  "output_directory": "./data"
}
```

---

## 📊 Format Output Dataset (`./data/`)

Setiap kali running, scraper akan menghasilkan dua pasang file di folder `./data/`:

1. **File Khusus Keyword**:
   - `threads_sentiment_<nama_keyword>.csv`
   - `threads_sentiment_<nama_keyword>.jsonl`
   *(Hanya berisi dataset komentar dari pencarian kata kunci tersebut)*

2. **File Akumulasi Gabungan**:
   - `threads_sentiment_all.csv`
   - `threads_sentiment_all.jsonl`
   *(Berisi seluruh akumulasi komentar yang pernah di-scrape di database)*
