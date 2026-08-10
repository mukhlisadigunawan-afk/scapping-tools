import os
import re
import csv
import pandas as pd
from typing import List, Dict, Any, Optional
from database import DatabaseManager
from utils.cleaner import sanitize_raw_text, clean_comment_text, clean_youtube_comment_text

def slugify(text: str) -> str:
    """Mengubah teks/keyword menjadi format nama file slug yang bersih."""
    text = re.sub(r'[^a-zA-Z0-9_-]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text.lower() if text else "all"

def clean_df_for_csv(df: pd.DataFrame, strip_emojis: bool = True) -> pd.DataFrame:
    """Memastikan semua kolom teks di DataFrame bebas dari line-break fisik (\\n) dan emoji agar CSV 100% bersih.

    cleaned_text di-derive ulang dari raw_text per baris, dengan cleaner yang berbeda per platform:
    Threads (DOM innerText, perlu strip UI chrome) vs YouTube (plain text dari API, cukup rapikan whitespace).
    """
    if df.empty:
        return df

    df = df.copy()
    if 'raw_text' in df.columns:
        df['raw_text'] = df['raw_text'].astype(str).apply(sanitize_raw_text)

    # Ekstraksi murni isi komentar untuk cleaned_text
    if 'raw_text' in df.columns and 'username' in df.columns:
        def _clean_row(row):
            if row.get('platform') == 'youtube':
                return clean_youtube_comment_text(row['raw_text'], strip_emojis=strip_emojis)
            return clean_comment_text(row['raw_text'], username=row['username'], strip_emojis=strip_emojis)

        df['cleaned_text'] = df.apply(_clean_row, axis=1)

    return df

def export_dataset(db: DatabaseManager, output_dir: str = "./data", formats: Optional[List[str]] = None, keyword: Optional[str] = None, platform: str = "threads"):
    """
    Mengekspor dataset komentar dari SQLite ke CSV dan/atau JSONL.
    - Setiap baris pada CSV dipastikan persis 1 baris (single line per record) tanpa newline terpisah
    - Terpisah berdasarkan keyword dan juga file akumulasi gabungan
    - File diberi prefix nama platform (mis. threads_sentiment_*, youtube_sentiment_*) agar dataset antar
      platform tidak bercampur di folder output yang sama
    """
    if formats is None:
        formats = ["csv", "jsonl"]

    os.makedirs(output_dir, exist_ok=True)

    # 1. Ekspor Khusus Keyword (jika keyword diisi)
    if keyword and keyword.strip():
        kw_slug = slugify(keyword)
        df_kw = db.get_comments_dataframe(keyword=keyword, platform=platform)
        df_kw = clean_df_for_csv(df_kw)

        if not df_kw.empty:
            if "csv" in formats:
                kw_csv = os.path.join(output_dir, f"{platform}_sentiment_{kw_slug}.csv")
                df_kw.to_csv(kw_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
                print(f"[exporter] Dataset Khusus Keyword '{keyword}' ({platform}) disimpan ke: {kw_csv} ({len(df_kw)} baris)")

            if "jsonl" in formats:
                kw_jsonl = os.path.join(output_dir, f"{platform}_sentiment_{kw_slug}.jsonl")
                df_kw.to_json(kw_jsonl, orient="records", lines=True, force_ascii=False)
                print(f"[exporter] Dataset Khusus Keyword '{keyword}' ({platform}) disimpan ke: {kw_jsonl} ({len(df_kw)} baris)")

    # 2. Ekspor Seluruh Dataset Gabungan per platform (<platform>_sentiment_all)
    df_all = db.get_comments_dataframe(platform=platform)
    df_all = clean_df_for_csv(df_all)

    if df_all.empty:
        print(f"[exporter] Belum ada data komentar ({platform}) di database untuk diekspor.")
        return

    if "csv" in formats:
        all_csv = os.path.join(output_dir, f"{platform}_sentiment_all.csv")
        df_all.to_csv(all_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
        print(f"[exporter] Total Dataset Gabungan ({platform}) disimpan ke: {all_csv} ({len(df_all)} baris)")

    if "jsonl" in formats:
        all_jsonl = os.path.join(output_dir, f"{platform}_sentiment_all.jsonl")
        df_all.to_json(all_jsonl, orient="records", lines=True, force_ascii=False)
        print(f"[exporter] Total Dataset Gabungan ({platform}) disimpan ke: {all_jsonl} ({len(df_all)} baris)")
