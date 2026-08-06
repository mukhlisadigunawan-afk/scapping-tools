import json
import os
import sys
from playwright.sync_api import sync_playwright
from rich.console import Console

console = Console()


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        console.print(f"[bold red][ERROR][/bold red] File '{path}' tidak ditemukan!")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    config = load_json("config.json")
    auth_config = load_json("auth_config.json")
    auth_state_path = config.get("auth_state_path", "auth_state.json")

    username = auth_config.get("username", "")
    password = auth_config.get("password", "")

    if not username or not password:
        console.print("[bold red][ERROR][/bold red] Isi 'username' dan 'password' di auth_config.json terlebih dahulu.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto("https://www.threads.com/login", wait_until="domcontentloaded")

        try:
            page.wait_for_selector("input[autocomplete='username']", timeout=15000)
            page.fill("input[autocomplete='username']", username)
            page.fill("input[autocomplete='current-password']", password)
            page.click("button[type='submit']")
        except Exception as e:
            console.print(f"[yellow][NOTICE][/yellow] Form login otomatis tidak ditemukan ({e}).")

        console.print("[bold cyan][ACTION REQUIRED][/bold cyan] Selesaikan proses login di jendela browser yang terbuka (termasuk verifikasi/2FA jika diminta).")
        console.print("Setelah benar-benar masuk ke halaman utama Threads, tekan [bold]Enter[/bold] di sini untuk menyimpan session...")
        input()

        context.storage_state(path=auth_state_path)
        console.print(f"[bold green][SUCCESS][/bold green] Session login disimpan ke: {auth_state_path}")

        browser.close()


if __name__ == "__main__":
    main()
