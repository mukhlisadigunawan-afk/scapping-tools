import json
import os
import sys
from rich.console import Console
from rich.panel import Panel

from database import DatabaseManager
from scraper import ThreadsScraper
from utils.exporter import export_dataset

console = Console()

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

def main():
    console.print(Panel.fit(
        "[bold cyan]Meta Threads Scraper for AI Sentiment Analysis[/bold cyan]\n"
        "[dim]Auto-Discovery, Unlimited Comments & SQLite Deduplication[/dim]",
        border_style="cyan"
    ))

    # 1. Load Konfigurasi
    config = load_config("config.json")
    
    search_keyword = config.get("search_keyword", [])
    keywords = [search_keyword] if isinstance(search_keyword, str) else search_keyword
    max_posts = config.get("max_posts_per_run", 5)
    max_comments = config.get("max_comments_per_post", None)
    db_path = config.get("database_path", "threads_scraper.db")
    output_dir = config.get("output_directory", "./data")
    export_formats = config.get("export_formats", ["csv", "jsonl"])

    console.print(f"[bold]Konfigurasi Berhasil Dimuat:[/bold]")
    console.print(f" • Keyword Pencarian : [bold green]{keywords}[/bold green]")
    console.print(f" • Maksimal Post/Run : [bold green]{max_posts}[/bold green]")
    console.print(f" • Batas Komentar/Post: [bold green]{'Tidak Terbatas (Unlimited)' if max_comments is None or max_comments == 0 else max_comments}[/bold green]")
    console.print(f" • Database SQLite   : [bold green]{db_path}[/bold green]\n")

    # 2. Inisialisasi Database
    db = DatabaseManager(db_path=db_path)

    # 3. Jalankan Scraper
    scraper = ThreadsScraper(config=config, db=db)
    scraper.run()

    # 4. Ekspor Dataset untuk AI Sentiment Analysis
    console.print("\n[bold cyan][Exporting Dataset][/bold cyan] Memproses ekspor dari SQLite ke CSV & JSONL...")
    if keywords:
        for keyword in keywords:
            export_dataset(db=db, output_dir=output_dir, formats=export_formats, keyword=keyword)
    else:
        export_dataset(db=db, output_dir=output_dir, formats=export_formats, keyword=None)

    console.print(Panel.fit(
        "[bold green]✔ Selesai! Scraping dan ekspor dataset berhasil dilakukan.[/bold green]\n"
        f"Dataset tersimpan di folder: [bold underline]{output_dir}[/bold underline]",
        border_style="green"
    ))

if __name__ == "__main__":
    main()
