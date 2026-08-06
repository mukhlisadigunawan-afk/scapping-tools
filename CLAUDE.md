# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python + Playwright scraper for Meta Threads (threads.net / threads.com) that collects posts and comments into a deduplicated SQLite database, then exports them to CSV/JSONL for AI sentiment analysis (e.g. IndoBERT, VADER, LLM fine-tuning). Console output and code comments are in Indonesian.

## Commands

```bash
# First-time setup + run (creates venv, installs deps + chromium if missing)
./run.sh

# Manual setup
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium

# One-time login (recommended — see Authentication below)
python login.py

# Run after setup
source venv/bin/activate
python main.py
```

There are no lint/test commands or a test suite configured in this repo.

## Configuration

All runtime behavior is driven by `config.json` (not CLI args) — read it before changing scraper behavior:

- `search_keyword` (array of strings, each searched as a full phrase — not split into words) / `target_profiles` / `target_post_urls`: three post-discovery modes, checked in that priority order (direct URLs → profiles → keyword search, looping over all keywords).
- `max_posts_per_run`, `max_comments_per_post` (`null`/`0` = unlimited), `remove_emojis`, `headless`, `scroll_delay_seconds`, `max_scroll_retries`.
- `database_path`, `export_formats` (`csv`/`jsonl`), `output_directory`, `auth_state_path` (session file used to scrape while logged in).

`threads_scraper.db` and `data/` are gitignored — they're runtime state/output, not project files.

## Authentication

Threads caps how many comments load for logged-out visitors. `login.py` opens a headful browser, logs in with credentials from `auth_config.json` (falls back to manual login in the same window if the auto-fill selectors don't match), then saves cookies/localStorage via Playwright's `storage_state` to `auth_state.json`. `ThreadsScraper.run()` loads that file into the browser context if present (scraper.py, in `run()`) — scraping without it still works but comment coverage is limited. `auth_config.json` and `auth_state.json` are gitignored; never put credentials in `config.json` (it's git-tracked).

## Architecture

Pipeline: `main.py` loads `config.json` → `ThreadsScraper.run()` (scraper.py) drives Playwright → results persist through `DatabaseManager` (database.py) → `export_dataset()` (utils/exporter.py) dumps SQLite to CSV/JSONL.

- **scraper.py** (`ThreadsScraper`): Owns the Playwright browser lifecycle.
  - `discover_posts()`: builds the list of post URLs to scrape, in priority order: `target_post_urls` → `target_profiles` (visits each profile page, scrolls to collect post links) → `search_keywords` (loops each keyword, searching threads.com for the full phrase). At each step it calls `db.is_post_scraped(post_id)` to skip posts already in SQLite — this is the sole dedup mechanism, applied at discovery time, not at save time. For keyword-discovered posts it also records which keyword found each URL in `self.url_keyword_map`, used later by `run()` so `save_post` stores the correct `keyword_search` per post; the post URL is reconstructed with the poster's username via `extract_username()` (Threads post URLs are `/@username/post/id`, not `/post/id`).
  - `scrape_post_comments()`: opens a post, repeatedly scrolls and re-queries comment DOM nodes (`div[data-pressable-container='true']`), extracting username via `a[href*='/@']` links. Comment identity is a SHA-256 hash of `post_id + username + cleaned_text` (`generate_comment_id`), used both to dedupe within a single scrape pass (`seen_comment_ids`) and as the SQLite primary key. Stops when `max_comments` is hit or scrolling produces no new comments for `max_scroll_retries` consecutive attempts.
  - Selectors here (`div[style*='border-bottom']`, UI-phrase filtering like "Translate"/"Reply") are brittle by nature and are the most likely thing to break if Threads changes its markup. See Authentication above — scraping without a saved session still runs but Threads limits comment visibility for logged-out browsers.
- **database.py** (`DatabaseManager`): Two tables — `posts` (dedup ledger + scrape metadata, keyed by `post_id`) and `comments` (keyed by `comment_id`, FK to `posts`). `save_post` upserts via `ON CONFLICT`; `save_comments` uses `INSERT OR REPLACE`. `get_comments_dataframe(keyword=...)` is the read path used by the exporter, joining comments to posts to filter by `keyword_search`.
- **utils/cleaner.py**: Text pipeline for turning raw DOM `innerText` blocks into sentiment-analysis-ready text.
  - `clean_comment_text`: line-by-line strips username echoes, Threads timestamps (`12h`, `4d`, `03/02/26`), UI chrome ("Translate", "Replying to @x"), and bare stat numbers (likes/reply counts like `3.6K`), then optionally strips emojis, then collapses whitespace. This is where scraper false-positives (stray UI text leaking into comments) get patched.
  - `sanitize_raw_text`: converts embedded newlines in the raw text to literal `\n` so every CSV row stays single-line.
  - `generate_comment_id`: the dedup key described above — order of inputs (`post_id`, `username`, cleaned text) matters if you need to reproduce IDs elsewhere.
- **utils/exporter.py**: Reads from SQLite (not from in-memory scrape results), producing two output pairs per run: a keyword-specific file (`threads_sentiment_<slug>.csv/.jsonl`) and a cumulative all-history file (`threads_sentiment_all.csv/.jsonl`). Since it re-derives `cleaned_text` from `raw_text` again on export (`clean_df_for_csv`), changes to `clean_comment_text` retroactively affect exported (but not stored) text on the next export run without re-scraping.

## Key invariants to preserve

- Dedup is post-level at discovery (`is_post_scraped`) and comment-level at save (`comment_id` hash / `INSERT OR REPLACE`) — there's no update-in-place for changed comment content, only overwrite-by-identical-hash.
- CSV rows must remain strictly one physical line; any new text field flowing into CSV export needs to go through `sanitize_raw_text`-style newline collapsing.
- `output_directory` and `data/` are created if missing (`os.makedirs(..., exist_ok=True)`) — don't assume they pre-exist.
