import json
import os
import sys
from rich.console import Console
from rich.panel import Panel

from database import DatabaseManager
from scraper import ThreadsScraper
from youtube_client import YouTubeScraper
from utils.exporter import export_dataset

console = Console()

SUPPORTED_PLATFORMS = ["threads", "youtube"]

def load_config(config_file: str = "config.json") -> dict:
    """Membaca konfigurasi dari file config.json."""
    if not os.path.exists(config_file):
        console.print(f"[bold red][ERROR][/bold red] File konfigurasi '{config_file}' tidak ditemukan!")
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[bold red][ERROR][/bold red] Gagal membaca config.json: {e}")
            sys.exit(1)

def load_platforms(config: dict) -> list:
    """Selector platform: dibaca dari config.json ('platform'), bisa 1 string atau list (multi-platform sekaligus)."""
    raw = config.get("platform", "threads")
    platforms = [raw] if isinstance(raw, str) else list(raw)

    valid_platforms = []
    for platform in platforms:
        if platform not in SUPPORTED_PLATFORMS:
            console.print(f"[bold red][ERROR][/bold red] Platform '{platform}' tidak dikenali. Pilihan valid: {SUPPORTED_PLATFORMS}")
            sys.exit(1)
        if platform not in valid_platforms:
            valid_platforms.append(platform)

    if not valid_platforms:
        console.print("[bold red][ERROR][/bold red] Field 'platform' di config.json kosong. Isi minimal 1: threads dan/atau youtube.")
        sys.exit(1)

    return valid_platforms


def run_platform(platform: str, config: dict, db: DatabaseManager, keywords: list, output_dir: str, export_formats: list):
    """Jalankan scraper + export untuk 1 platform (dipanggil per platform yang dipilih di config.json)."""
    console.print(Panel.fit(f"[bold cyan]Menjalankan platform: {platform.upper()}[/bold cyan]", border_style="cyan"))

    if platform == "threads":
        scraper = ThreadsScraper(config=config, db=db)
    else:  # youtube
        scraper = YouTubeScraper(config=config, db=db)
    scraper.run()

    console.print(f"\n[bold cyan][Exporting Dataset][/bold cyan] Memproses ekspor {platform} dari SQLite ke CSV & JSONL...")
    if keywords:
        for keyword in keywords:
            export_dataset(db=db, output_dir=output_dir, formats=export_formats, keyword=keyword, platform=platform)
    else:
        export_dataset(db=db, output_dir=output_dir, formats=export_formats, keyword=None, platform=platform)


def main():
    console.print(Panel.fit(
        "[bold cyan]Multi-Platform Scraper for AI Sentiment Analysis[/bold cyan]\n"
        "[dim]Threads & YouTube — Auto-Discovery, Unlimited Comments & SQLite Deduplication[/dim]",
        border_style="cyan"
    ))

    # 1. Load Konfigurasi
    config = load_config("config.json")

    platforms = load_platforms(config)
    search_keyword = config.get("search_keyword", [])
    keywords = [search_keyword] if isinstance(search_keyword, str) else search_keyword
    max_posts = config.get("max_posts_per_run", 5)
    max_comments = config.get("max_comments_per_post", None)
    db_path = config.get("database_path", "threads_scraper.db")
    output_dir = config.get("output_directory", "./data")
    export_formats = config.get("export_formats", ["csv", "jsonl"])

    console.print(f"[bold]Konfigurasi Berhasil Dimuat:[/bold]")
    console.print(f" • Platform Aktif   : [bold green]{platforms}[/bold green]")
    console.print(f" • Keyword Pencarian : [bold green]{keywords}[/bold green]")
    console.print(f" • Maksimal Post/Run : [bold green]{max_posts}[/bold green]")
    console.print(f" • Batas Komentar/Post: [bold green]{'Tidak Terbatas (Unlimited)' if max_comments is None or max_comments == 0 else max_comments}[/bold green]")
    console.print(f" • Database SQLite   : [bold green]{db_path}[/bold green]\n")

    # 2. Inisialisasi Database (dipakai bersama semua platform, dibedakan lewat kolom 'platform')
    db = DatabaseManager(db_path=db_path)

    # 3. Jalankan scraper + export untuk tiap platform yang dipilih di config.json
    for platform in platforms:
        run_platform(platform, config, db, keywords, output_dir, export_formats)

    console.print(Panel.fit(
        "[bold green]✔ Selesai! Scraping dan ekspor dataset berhasil dilakukan.[/bold green]\n"
        f"Platform: [bold]{', '.join(platforms)}[/bold]\n"
        f"Dataset tersimpan di folder: [bold underline]{output_dir}[/bold underline]",
        border_style="green"
    ))

if __name__ == "__main__":
    main()
