import re
import hashlib

def remove_emojis(text: str) -> str:
    """Menghapus seluruh karakter emoji dari teks."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        r'[\U00010000-\U0010ffff'
        r'\u2600-\u27ff'
        r'\u2300-\u23ff'
        r'\u2b00-\u2bff'
        r'\u3030\u303d\u3297\u3299]'
        r'|[\u200d\ufe0f]',
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)

def clean_comment_text(raw_text: str, username: str = "", strip_emojis: bool = True) -> str:
    """
    Ekstraksi murni isi komentar dari blok teks Threads untuk AI Sentiment Analysis:
    - Mengeliminasi username, tanggal/timestamp (misal: 10/15/25, 12h, 4d), 'Author', 'Translate'
    - Mengeliminasi angka statistik UI (likes/replies count di footer)
    - Mengeliminasi emoji jika strip_emojis=True
    - Menghasilkan teks murni komentar dalam 1 baris bersih
    """
    if not raw_text:
        return ""

    # Pisahkan per baris untuk membuang elemen UI Threads
    raw_lines = [line.strip() for line in str(raw_text).replace('\\n', '\n').split('\n') if line.strip()]
    cleaned_lines = []

    for line in raw_lines:
        # 1. Abaikan jika baris sama dengan username
        if username and line.lower() == str(username).lower():
            continue

        # 2. Abaikan timestamp & tanggal Threads (03/02/26, 12h, 4d)
        if re.match(r'^\d{2}/\d{2}/\d{2}$', line) or re.match(r'^\d+[hdms]$', line):
            continue

        # 3. Abaikan kata UI bawaan Threads
        if line.lower() in ['author', 'translate', 'replying to', 'thread', 'views', '·']:
            continue
        if re.match(r'^replying to @\w+$', line, flags=re.IGNORECASE):
            continue

        # 4. Abaikan angka/metrik statistik di footer (misal: "273", "21", "3.6K", "19.1K")
        if re.match(r'^\d+(\.\d+)?[KMk]?$', line):
            continue

        cleaned_lines.append(line)

    body_text = " ".join(cleaned_lines)
    
    # 5. Hapus emoji jika diaktifkan
    if strip_emojis:
        body_text = remove_emojis(body_text)

    # 6. Pembersihan sekunder untuk sisa-sisa metadata
    body_text = re.sub(r'\b\d{2}/\d{2}/\d{2}\b', ' ', body_text)
    body_text = re.sub(r'\b\d+[hd]\b', ' ', body_text)
    body_text = re.sub(r'[\r\n\t]+', ' ', body_text)
    body_text = re.sub(r'\s+', ' ', body_text)

    return body_text.strip()

def sanitize_raw_text(raw_text: str) -> str:
    """
    Mengubah newline fisik (\\n) pada raw_text menjadi spasi / string '\\n' visual
    agar setiap baris pada file CSV strictly 1 baris tanpa merusak format delimiter.
    """
    if not raw_text:
        return ""
    text = str(raw_text).replace('\r\n', ' \\n ').replace('\n', ' \\n ')
    return re.sub(r'\s+', ' ', text).strip()

def generate_comment_id(post_id: str, username: str, raw_text: str) -> str:
    """Membuat ID unik berbasis hash sha256 untuk setiap komentar."""
    content = f"{post_id}_{username}_{raw_text}".encode('utf-8')
    return hashlib.sha256(content).hexdigest()[:16]
