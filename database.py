import sqlite3
import os
from typing import List, Dict, Any, Optional
import pandas as pd

class DatabaseManager:
    def __init__(self, db_path: str = "threads_scraper.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Inisialisasi tabel SQLite untuk postingan dan komentar."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabel Posts (Menyimpan riwayat postingan yang di-scrape)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    keyword_search TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    comments_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'COMPLETED',
                    platform TEXT NOT NULL DEFAULT 'threads'
                )
            """)

            # Migrasi untuk DB lama yang dibuat sebelum kolom 'platform' ada
            try:
                cursor.execute("ALTER TABLE posts ADD COLUMN platform TEXT NOT NULL DEFAULT 'threads'")
            except sqlite3.OperationalError:
                pass

            # Tabel Comments (Dataset Sentimen)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    comment_id TEXT PRIMARY KEY,
                    post_id TEXT NOT NULL,
                    username TEXT,
                    raw_text TEXT,
                    cleaned_text TEXT,
                    like_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    is_reply BOOLEAN DEFAULT 0,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES posts (post_id)
                )
            """)
            conn.commit()

    def is_post_scraped(self, post_id: str, platform: str = "threads") -> bool:
        """Cek apakah post_id sudah pernah di-scrape di platform tsb (post yang FAILED dianggap belum, agar dicoba ulang)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM posts WHERE post_id = ? AND platform = ? AND status != 'FAILED'",
                (post_id, platform)
            )
            return cursor.fetchone() is not None

    def save_post(self, post_id: str, url: str, keyword: str, comments_count: int, status: str = "COMPLETED", platform: str = "threads"):
        """Menyimpan atau memperbarui data postingan."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO posts (post_id, url, keyword_search, comments_count, status, platform)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    comments_count = excluded.comments_count,
                    scraped_at = CURRENT_TIMESTAMP,
                    status = excluded.status,
                    platform = excluded.platform
            """, (post_id, url, keyword, comments_count, status, platform))
            conn.commit()

    def save_comments(self, comments: List[Dict[str, Any]]):
        """Menyimpan list komentar ke tabel comments."""
        if not comments:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for c in comments:
                cursor.execute("""
                    INSERT OR REPLACE INTO comments 
                    (comment_id, post_id, username, raw_text, cleaned_text, like_count, reply_count, is_reply)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c["comment_id"],
                    c["post_id"],
                    c.get("username", ""),
                    c.get("raw_text", ""),
                    c.get("cleaned_text", ""),
                    c.get("like_count", 0),
                    c.get("reply_count", 0),
                    1 if c.get("is_reply") else 0
                ))
            conn.commit()

    def get_comments_dataframe(self, keyword: Optional[str] = None, platform: Optional[str] = None) -> pd.DataFrame:
        """Mengambil dataset komentar dari database (bisa difilter berdasarkan keyword_search dan/atau platform)."""
        with self._get_connection() as conn:
            query = """
                SELECT
                    c.comment_id,
                    c.post_id,
                    p.url as post_url,
                    p.platform,
                    p.keyword_search,
                    c.username,
                    c.raw_text,
                    c.cleaned_text,
                    c.like_count,
                    c.reply_count,
                    c.is_reply,
                    c.scraped_at
                FROM comments c
                LEFT JOIN posts p ON c.post_id = p.post_id
            """
            conditions = []
            params = []
            if keyword:
                conditions.append("p.keyword_search = ?")
                params.append(keyword)
            if platform:
                conditions.append("p.platform = ?")
                params.append(platform)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY c.scraped_at DESC"
            return pd.read_sql_query(query, conn, params=params)
