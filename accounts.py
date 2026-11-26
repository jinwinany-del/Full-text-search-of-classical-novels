"""账户、会话、书架和书签存储（独立于可重建的 library.db）。"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("USERS_DB_PATH") or os.path.join(ROOT, "data", "users.db")
SESSION_TTL = 30 * 24 * 3600
MAX_SHELF = 500
MAX_BOOKMARKS = 500

USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{2,20}$")
SPECIAL_RE = re.compile(r"[!-/:-@\[-`{-~]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    recovery_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shelf(
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    added_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, title)
);
CREATE TABLE IF NOT EXISTS bookmarks(
    user_id INTEGER NOT NULL,
    id TEXT NOT NULL,
    book TEXT NOT NULL,
    chapter_no INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    paragraph INTEGER NOT NULL,
    excerpt TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
"""


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.executescript(SCHEMA)


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _unb64(text):
    return base64.b64decode(text.encode("ascii"))


def hash_secret(secret):
    salt = os.urandom(16)
    digest = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_secret(secret, stored):
    try:
        algorithm, n, r, p, salt, digest = stored.split("$")
        if algorithm != "scrypt":
            return False
        computed = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(digest)),
        )
        return hmac.compare_digest(computed, _unb64(digest))
    except (ValueError, TypeError):
        return False


def normalize_username(username):
    return (username or "").strip()


def validate_password(password):
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        raise ValueError("密码长度需为 6-128 位")
    if not re.search(r"[A-Za-z]", password) and not SPECIAL_RE.search(password):
        raise ValueError("密码必须包含至少一个英文字母或特殊字符")


def validate_credentials(username, password):
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名需为 2-20 位中文、字母、数字、下划线或短横线")
    validate_password(password)


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def create_user(username, password):
    username = normalize_username(username)
    validate_credentials(username, password)
    recovery_code = secrets.token_urlsafe(12)
    now = int(time.time())
    try:
        with closing(_connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO users(username, password_hash, recovery_hash, created_at) "
                "VALUES(?, ?, ?, ?)",
                (username, hash_secret(password), hash_secret(recovery_code), now),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("用户名已存在") from exc
    return {"id": user_id, "username": username}, recovery_code


def authenticate(username, password):
    username = normalize_username(username)
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not verify_secret(password or "", row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"]}


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES(?, ?, ?)",
            (_token_hash(token), user_id, now + SESSION_TTL),
        )
    return token


def session_user(token):
    if not token:
        return None
    now = int(time.time())
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT u.id, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(token), now),
        ).fetchone()
    return {"id": row["id"], "username": row["username"]} if row else None


def delete_session(token):
    if not token:
        return
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def reset_password(username, recovery_code, new_password):
    username = normalize_username(username)
    validate_password(new_password)
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, recovery_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not verify_secret(recovery_code or "", row["recovery_hash"]):
        raise ValueError("用户名或恢复码不正确")

    new_code = secrets.token_urlsafe(12)
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, recovery_hash = ? WHERE id = ?",
            (hash_secret(new_password), hash_secret(new_code), row["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
    return new_code


def change_password(user_id, old_password, new_password):
    """已登录状态下修改密码，保留现有会话。"""
    validate_password(new_password)
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row or not verify_secret(old_password or "", row["password_hash"]):
        raise ValueError("当前密码不正确")

    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_secret(new_password), user_id),
        )


def delete_user(user_id):
    """注销账户，并删除该用户的全部云端数据。"""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM shelf WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM bookmarks WHERE user_id = ?", (user_id,))
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cursor.rowcount > 0


def get_shelf(user_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT title FROM shelf WHERE user_id = ? ORDER BY added_at",
            (user_id,),
        ).fetchall()
    return [row["title"] for row in rows]


def set_shelf(user_id, titles):
    if not isinstance(titles, list):
        raise ValueError("书架数据格式不正确")
    cleaned = []
    for title in titles:
        if isinstance(title, str) and title and len(title) <= 100 and title not in cleaned:
            cleaned.append(title)
        if len(cleaned) >= MAX_SHELF:
            break
    now = int(time.time())
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM shelf WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO shelf(user_id, title, added_at) VALUES(?, ?, ?)",
            [(user_id, title, now) for title in cleaned],
        )
    return cleaned


def get_bookmarks(user_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, book, chapter_no, chapter_title, paragraph, excerpt, created_at "
            "FROM bookmarks WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_bookmarks(user_id, bookmarks):
    if not isinstance(bookmarks, list):
        raise ValueError("书签数据格式不正确")
    cleaned = []
    seen = set()
    for item in bookmarks:
        if not isinstance(item, dict):
            continue
        bookmark_id = item.get("id")
        book = item.get("book")
        chapter_no = item.get("chapter_no")
        paragraph = item.get("paragraph")
        if not isinstance(bookmark_id, str) or not bookmark_id or len(bookmark_id) > 200:
            continue
        if bookmark_id in seen:
            continue
        if not isinstance(book, str) or not book or len(book) > 100:
            continue
        if not isinstance(chapter_no, int) or chapter_no < 1:
            continue
        if not isinstance(paragraph, int) or paragraph < 1:
            continue
        cleaned.append({
            "id": bookmark_id,
            "book": book,
            "chapter_no": chapter_no,
            "chapter_title": str(item.get("chapter_title") or "")[:200],
            "paragraph": paragraph,
            "excerpt": str(item.get("excerpt") or "")[:200],
            "created_at": _safe_int(item.get("created_at"), int(time.time())),
        })
        seen.add(bookmark_id)
        if len(cleaned) >= MAX_BOOKMARKS:
            break

    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM bookmarks WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO bookmarks(user_id, id, book, chapter_no, chapter_title, paragraph, excerpt, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (user_id, item["id"], item["book"], item["chapter_no"],
                 item["chapter_title"], item["paragraph"], item["excerpt"], item["created_at"])
                for item in cleaned
            ],
        )
    return cleaned


init_db()
