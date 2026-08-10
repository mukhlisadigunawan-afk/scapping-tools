# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python multi-platform scraper — Meta Threads (threads.net / threads.com) via Playwright, and YouTube via the official YouTube Data API v3 — that collects posts/videos and comments into a shared deduplicated SQLite database, then exports them to CSV/JSONL for AI sentiment analysis (e.g. IndoBERT, VADER, LLM fine-tuning). Console output and code comments are in Indonesian.

## Commands

```bash
# First-time setup + run (creates venv, installs deps + chromium if missing)
./run.sh

# Manual setup
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium

# One-time login (recommended — see Authentication below; login is manual, no credentials file)
python login.py

# First-time config: copy the template (config.json is gitignored, config.json.example is not)
cp config.json.example config.json   # then strip the // comment lines, config.json must be strict JSON

# One-time YouTube API key setup (only needed if "youtube" is in config.json's "platform")
# fill config.json's "youtube_api_key" field — see Authentication below

# Run after setup
source venv/bin/activate
python main.py
```

There are no lint/test commands or a test suite configured in this repo.

## Configuration

All runtime behavior is driven by `config.json` (not CLI args) — read it before changing scraper behavior. `config.json` itself is gitignored (holds `youtube_api_key`); `config.json.example` is the git-tracked template, annotated with `//` comments explaining valid values (strip those comments when copying it to a real `config.json`, since the app's `json.load()` requires strict JSON). Keep both files' field sets in sync when adding/renaming a config option.

- `platform`: string or array — `"threads"`, `"youtube"`, or `["threads", "youtube"]` to run both in one invocation of `main.py`, sharing the same `search_keyword` list. Validated/normalized by `main.py`'s `load_platforms()`; unknown values exit with an error. Defaults to `"threads"` if omitted, so pre-existing configs keep working unchanged.
- `search_keyword` (array of strings, each searched as a full phrase — not split into words): shared across both platforms. Threads discovery order: `target_post_urls` → `target_profiles` → `search_keywords`. YouTube discovery order: `target_video_urls` → `target_channels` → `search_keywords`.
- `target_profiles` / `target_post_urls`: Threads-only discovery modes.
- `target_channels` / `target_video_urls`: YouTube-only discovery modes (`target_channels` accepts a handle like `@name`, a bare name, or a `UCxxxx` channel ID).
- `youtube_video_type`: `"all"` (default) / `"shorts_only"` / `"exclude_shorts"` — filters videos discovered via `target_channels`/`search_keyword` by duration (YouTube's API has no real "is Short" flag; `<= 60s` is used as the heuristic, see `SHORTS_MAX_DURATION_SECONDS` in youtube_client.py). Does **not** apply to `target_video_urls` — an explicit URL is always scraped regardless of type.
- `max_posts_per_run` (shared), `max_comments_per_post` (Threads), `max_comments_per_video` (YouTube, falls back to `max_comments_per_post` if unset) — `null`/`0` = unlimited on both.
- `remove_emojis`, `headless`, `scroll_delay_seconds`, `max_scroll_retries`: Threads/Playwright-only.
- `database_path`, `export_formats` (`csv`/`jsonl`), `output_directory`: shared across platforms.
- `auth_state_path`: Threads session file. `youtube_api_key`: raw YouTube Data API v3 key, read directly by `YouTubeScraper` — safe to fill in with a real key since `config.json` is gitignored.

`threads_scraper.db` and `data/` are gitignored — they're runtime state/output, not project files.

## Authentication

- **Threads**: caps how many comments load for logged-out visitors. `login.py` opens a headful browser to the Threads login page and waits for you to log in **manually** (including any 2FA) — press Enter in the terminal once you're in, and it saves cookies/localStorage via Playwright's `storage_state` to `auth_state.json`. There is no credentials file for Threads by design — nothing to fill in, nothing to leak. `ThreadsScraper.run()` loads `auth_state.json` into the browser context if present (scraper.py, in `run()`) — scraping without it still works but comment coverage is limited. `auth_state.json` is gitignored.
- **YouTube**: needs a YouTube Data API v3 key (Google Cloud Console → enable the API → create an API key), filled into `config.json`'s `youtube_api_key` field. `YouTubeScraper` (`youtube_client.py`) refuses to start with a clear error if that field is blank. `config.json` is gitignored, so a real key filled in there won't be committed. Free daily quota is 10,000 units; `search.list` (keyword discovery) costs 100 units/call, everything else (`commentThreads.list`, `playlistItems.list`, `channels.list`, `videos.list`) costs 1 unit — keyword-based discovery is the expensive path, so keep `search_keyword`/`max_posts_per_run` modest for YouTube.

## Architecture

Pipeline: `main.py` loads `config.json` → resolves the active platform(s) (`load_platforms()`) → for each, runs the matching scraper (`ThreadsScraper.run()` via Playwright, or `YouTubeScraper.run()` via HTTP calls to the YouTube Data API) → results persist through the shared `DatabaseManager` (database.py) → `export_dataset()` (utils/exporter.py) dumps SQLite to platform-prefixed CSV/JSONL.

- **scraper.py** (`ThreadsScraper`): Owns the Playwright browser lifecycle.
  - `discover_posts()`: builds the list of post URLs to scrape, in priority order: `target_post_urls` → `target_profiles` (visits each profile page, scrolls to collect post links) → `search_keywords` (loops each keyword, searching threads.com for the full phrase). At each step it calls `db.is_post_scraped(post_id, platform="threads")` to skip posts already in SQLite — this is the sole dedup mechanism, applied at discovery time, not at save time. For keyword-discovered posts it also records which keyword found each URL in `self.url_keyword_map`, used later by `run()` so `save_post` stores the correct `keyword_search` per post; the post URL is reconstructed with the poster's username via `extract_username()` (Threads post URLs are `/@username/post/id`, not `/post/id`).
  - `scrape_post_comments()`: opens a post, repeatedly scrolls and re-queries comment DOM nodes (`div[data-pressable-container='true']`), extracting username via `a[href*='/@']` links. Comment identity is a SHA-256 hash of `post_id + username + cleaned_text` (`generate_comment_id`), used both to dedupe within a single scrape pass (`seen_comment_ids`) and as the SQLite primary key. Stops when `max_comments` is hit or scrolling produces no new comments for `max_scroll_retries` consecutive attempts.
  - Selectors here (`div[style*='border-bottom']`, UI-phrase filtering like "Translate"/"Reply") are brittle by nature and are the most likely thing to break if Threads changes its markup. See Authentication above — scraping without a saved session still runs but Threads limits comment visibility for logged-out browsers.
- **youtube_client.py** (`YouTubeScraper`): No browser — plain `requests` calls to `googleapis.com/youtube/v3`, authenticated with `config["youtube_api_key"]` (constructor exits early via `_load_api_key()` if blank). `_api_get()` is the single call site that raises `YouTubeQuotaExceeded` on a 403 `quotaExceeded` response (caught in `run()` to stop the whole platform run early rather than burning remaining calls) and returns `None` on `commentsDisabled`/404 (treated as "no comments", not a fatal error).
  - `discover_videos()`: same three-tier priority pattern as Threads (`target_video_urls` → `target_channels` via `channels.list`/`playlistItems.list` on the channel's uploads playlist → `search_keyword` via `search.list`), deduping with `db.is_post_scraped(video_id, platform="youtube")`. Each page of channel/search results is collected into a candidate list, run through `_filter_by_video_type()` (an extra batched `videos.list` call for duration, skipped entirely when `youtube_video_type` is `"all"`), then appended to `discovered` up to `max_posts`.
  - `scrape_video_comments()`: paginates `commentThreads.list` (`part=snippet,replies`, `textFormat=plainText`) via `nextPageToken`; top-level comments and their inline `replies.comments` both flow through `_comment_from_snippet()`, which reuses `generate_comment_id` with `video_id` as `post_id` — so comment identity/dedup logic is identical to Threads.
- **database.py** (`DatabaseManager`): Two tables — `posts` (dedup ledger + scrape metadata, keyed by `post_id`, with a `platform` column defaulting to `'threads'`) and `comments` (keyed by `comment_id`, FK to `posts`; platform is derived via join, not duplicated onto this table). `save_post`/`is_post_scraped` take a `platform` argument (default `"threads"`) so both scrapers share one ledger without cross-platform ID collisions being load-bearing — `platform` is the actual dedup boundary, not the format of `post_id` itself. `save_comments` uses `INSERT OR REPLACE`. `get_comments_dataframe(keyword=..., platform=...)` is the read path used by the exporter. `_init_db()` runs an `ALTER TABLE posts ADD COLUMN platform ...` guarded by `except sqlite3.OperationalError` so pre-existing `threads_scraper.db` files (created before YouTube support) migrate in place on first run.
- **utils/cleaner.py**: Text pipeline for turning raw scraped text into sentiment-analysis-ready text — two entry points, picked by platform:
  - `clean_comment_text` (Threads): line-by-line strips username echoes, Threads timestamps (`12h`, `4d`, `03/02/26`), UI chrome ("Translate", "Replying to @x"), and bare stat numbers (likes/reply counts like `3.6K`), then optionally strips emojis, then collapses whitespace. This is where scraper false-positives (stray UI text leaking into comments) get patched.
  - `clean_youtube_comment_text` (YouTube): API comments are already plain text with no DOM chrome to strip, so this just normalizes literal/real newlines to spaces, optionally strips emojis, and collapses whitespace.
  - `sanitize_raw_text`: converts embedded newlines in the raw text to literal `\n` so every CSV row stays single-line. Both cleaner functions above know how to un-escape this literal marker back to a real separator when re-deriving `cleaned_text` from an already-sanitized `raw_text` (the exporter's read path).
  - `generate_comment_id`: the dedup key described above — order of inputs (`post_id`, `username`, cleaned text) matters if you need to reproduce IDs elsewhere. Shared verbatim by both scrapers.
- **utils/exporter.py**: Reads from SQLite (not from in-memory scrape results), producing two output pairs per platform per run: a keyword-specific file (`<platform>_sentiment_<slug>.csv/.jsonl`) and a cumulative all-history file (`<platform>_sentiment_all.csv/.jsonl`) — the `threads_`/`youtube_` prefix keeps the two platforms' datasets from mixing in the same `output_directory`. `clean_df_for_csv()` re-derives `cleaned_text` from `raw_text` per row, dispatching to `clean_comment_text` or `clean_youtube_comment_text` based on the row's `platform` column — so changes to either cleaner retroactively affect exported (but not stored) text on the next export run without re-scraping.

## Key invariants to preserve

- Dedup is post-level at discovery (`is_post_scraped(post_id, platform)`) and comment-level at save (`comment_id` hash / `INSERT OR REPLACE`) — there's no update-in-place for changed comment content, only overwrite-by-identical-hash. `platform` is part of the discovery-time dedup check; don't drop it when calling `is_post_scraped`/`save_post`, even though in practice Threads and YouTube ID formats are unlikely to collide.
- CSV rows must remain strictly one physical line; any new text field flowing into CSV export needs to go through `sanitize_raw_text`-style newline collapsing, and any new per-platform cleaner needs to handle un-escaping that same literal `\n` marker (see `clean_youtube_comment_text`) since the exporter re-derives `cleaned_text` from already-sanitized `raw_text`.
- `output_directory` and `data/` are created if missing (`os.makedirs(..., exist_ok=True)`) — don't assume they pre-exist.
- Adding a third platform means: a new scraper module with a `.run()` method, a new entry in `main.py`'s `SUPPORTED_PLATFORMS`/`run_platform()` dispatch, a new `clean_<platform>_comment_text` if the raw text needs different handling, and nothing else in `database.py`/`utils/exporter.py` (both are already platform-parameterized).
