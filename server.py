#!/usr/bin/env python3
"""古典小说全文检索 · 本地预览服务（仅标准库）"""

import ipaddress
import json
import logging
import mimetypes
import os
import sys
import threading
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import accounts
from library import Library, split_terms

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

LIB = Library()

LOG = logging.getLogger("novel-search")

COOKIE_NAME = "novel_session"
_attempts = defaultdict(deque)
_attempts_lock = threading.Lock()

SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
    (
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    ),
]


def is_local_peer(host):
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def allow_attempt(key, limit, window):
    now = time.time()
    with _attempts_lock:
        if len(_attempts) > 5000:
            for stale in [
                k for k, v in _attempts.items() if not v or v[-1] <= now - 3600
            ]:
                del _attempts[stale]
        history = _attempts[key]
        while history and history[0] <= now - window:
            history.popleft()
        if len(history) >= limit:
            return False
        history.append(now)
        return True


def valid_book_titles():
    return {
        book["title"]
        for category in LIB.library_catalog()["categories"]
        for book in category["books"]
    }


def chapter_payload(book, no, query=""):
    ch = LIB.chapter(book, no)
    terms = split_terms(query)
    matches = []
    for index, para in enumerate(ch["paragraphs"], 1):
        ranges = []
        for term in terms:
            start = para.find(term)
            while start != -1:
                ranges.append({"start": start, "length": len(term)})
                start = para.find(term, start + len(term))
        if ranges:
            ranges.sort()
            matches.append({"paragraph": index, "ranges": ranges})
    return {
        "book": book,
        "no": ch["no"],
        "title": ch["title"],
        "paragraphs": ch["paragraphs"],
        "matches": matches,
    }


def int_param(query, name, default):
    try:
        return int((query.get(name) or [str(default)])[0])
    except ValueError:
        return default


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type, extra_headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, status=200, extra_headers=None):
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False),
            "application/json; charset=utf-8",
            extra_headers,
        )

    def _body_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("请求长度不正确") from exc
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求内容为空或过大")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 格式不正确") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON 格式不正确")
        return data

    def _cookie_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001
            return ""
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else ""

    def _session_cookie(self, token=None):
        if token:
            value = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={accounts.SESSION_TTL}"
        else:
            value = f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        if self.headers.get("X-Forwarded-Proto") == "https":
            value += "; Secure"
        return value

    def _current_user(self):
        token = self._cookie_token()
        return token, accounts.session_user(token)

    def _client_ip(self):
        peer = self.client_address[0]
        forwarded = (self.headers.get("X-Real-IP") or "").strip()
        if forwarded and is_local_peer(peer):
            try:
                ipaddress.ip_address(forwarded)
            except ValueError:
                return peer
            return forwarded
        return peer

    def _session_payload(self, user):
        return {
            "user": user,
            "shelf": accounts.get_shelf(user["id"]),
            "bookmarks": accounts.get_bookmarks(user["id"]),
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path.startswith("/api/"):
            ip = self._client_ip()
            if parsed.path == "/api/search":
                limited = not allow_attempt(("search", ip), 60, 60)
            else:
                limited = not allow_attempt(("read", ip), 240, 60)
            if limited:
                return self._json(
                    {"error": "请求太频繁，请稍后再试"},
                    429,
                    [("Retry-After", "60")],
                )

        if parsed.path == "/api/library":
            return self._json(LIB.library_catalog())

        if parsed.path == "/api/me":
            token, user = self._current_user()
            if not user:
                return self._json({
                    "user": None,
                    "shelf": [],
                    "bookmarks": [],
                    "expired": bool(token),
                })
            return self._json(self._session_payload(user))

        if parsed.path == "/api/book":
            title = (query.get("title") or [""])[0]
            try:
                return self._json(LIB.book_chapters(title))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 404)

        if parsed.path == "/api/stats":
            return self._json(LIB.stats())

        if parsed.path == "/api/search":
            text = (query.get("q") or [""])[0]
            book = (query.get("book") or [""])[0] or None
            page = int_param(query, "page", 1)
            per_page = max(5, min(int_param(query, "per_page", 20), 50))
            started = time.perf_counter()
            try:
                payload = LIB.search(text, book=book, page=page, per_page=per_page)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            elapsed = time.perf_counter() - started
            if elapsed > 0.5:
                LOG.warning(
                    "慢检索 %.0fms q=%r book=%r page=%s",
                    elapsed * 1000, text[:60], book or "", page,
                )
            return self._json(payload)

        if parsed.path == "/api/chapter":
            book = (query.get("book") or [""])[0]
            no = int_param(query, "no", 0)
            try:
                return self._json(chapter_payload(book, no, (query.get("q") or [""])[0]))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 404)

        rel = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        path = os.path.normpath(os.path.join(STATIC, rel))
        if path != STATIC and not path.startswith(STATIC + os.sep):
            return self._send(403, "forbidden", "text/plain; charset=utf-8")
        if not os.path.isfile(path):
            return self._send(404, "not found", "text/plain; charset=utf-8")

        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/register":
                if not allow_attempt(("register", self._client_ip()), 5, 3600):
                    return self._json({"error": "注册太频繁，请稍后再试"}, 429)
                data = self._body_json()
                user, recovery_code = accounts.create_user(
                    data.get("username", ""), data.get("password", "")
                )
                token = accounts.create_session(user["id"])
                payload = self._session_payload(user)
                payload["recovery_code"] = recovery_code
                return self._json(payload, 201, [("Set-Cookie", self._session_cookie(token))])

            if parsed.path == "/api/login":
                data = self._body_json()
                username = (data.get("username") or "").strip()
                if not allow_attempt(("login", self._client_ip(), username), 10, 300):
                    return self._json({"error": "登录尝试太频繁，请稍后再试"}, 429)
                user = accounts.authenticate(username, data.get("password", ""))
                if not user:
                    return self._json({"error": "用户名或密码错误"}, 401)
                token = accounts.create_session(user["id"])
                return self._json(
                    self._session_payload(user), 200,
                    [("Set-Cookie", self._session_cookie(token))],
                )

            if parsed.path == "/api/logout":
                token, _ = self._current_user()
                accounts.delete_session(token)
                return self._json({"ok": True}, 200, [("Set-Cookie", self._session_cookie())])

            if parsed.path == "/api/account/reset":
                data = self._body_json()
                username = (data.get("username") or "").strip()
                if not allow_attempt(("reset", self._client_ip(), username), 10, 3600):
                    return self._json({"error": "操作太频繁，请稍后再试"}, 429)
                new_code = accounts.reset_password(
                    username,
                    data.get("recovery_code", ""),
                    data.get("new_password", ""),
                )
                return self._json({"ok": True, "recovery_code": new_code})

            return self._json({"error": "not found"}, 404)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception:  # noqa: BLE001
            LOG.exception("POST %s 失败", parsed.path)
            return self._json({"error": "服务器内部错误"}, 500)

    def do_PUT(self):
        parsed = urlparse(self.path)
        try:
            _, user = self._current_user()
            if not user:
                return self._json({"error": "请先登录"}, 401)

            if parsed.path == "/api/me/shelf":
                data = self._body_json()
                titles = data.get("titles", [])
                if not isinstance(titles, list):
                    raise ValueError("书架数据格式不正确")
                allowed = valid_book_titles()
                cleaned = [title for title in titles if isinstance(title, str) and title in allowed]
                saved = accounts.set_shelf(user["id"], cleaned)
                return self._json({"ok": True, "shelf": saved})

            if parsed.path == "/api/me/bookmarks":
                data = self._body_json()
                bookmarks = data.get("bookmarks", [])
                if not isinstance(bookmarks, list):
                    raise ValueError("书签数据格式不正确")
                allowed = valid_book_titles()
                cleaned = [
                    item for item in bookmarks
                    if isinstance(item, dict) and item.get("book") in allowed
                ]
                saved = accounts.set_bookmarks(user["id"], cleaned)
                return self._json({"ok": True, "bookmarks": saved})

            if parsed.path == "/api/me/password":
                if not allow_attempt(
                    ("password", self._client_ip(), user["id"]), 10, 3600
                ):
                    return self._json(
                        {"error": "操作太频繁，请稍后再试"},
                        429,
                        [("Retry-After", "3600")],
                    )
                data = self._body_json()
                accounts.change_password(
                    user["id"],
                    data.get("old_password", ""),
                    data.get("new_password", ""),
                )
                return self._json({"ok": True})

            return self._json({"error": "not found"}, 404)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception:  # noqa: BLE001
            LOG.exception("PUT %s 失败", parsed.path)
            return self._json({"error": "服务器内部错误"}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        try:
            _, user = self._current_user()
            if not user:
                return self._json({"error": "请先登录"}, 401)
            if parsed.path != "/api/account":
                return self._json({"error": "not found"}, 404)
            accounts.delete_user(user["id"])
            LOG.info("账户已注销 user_id=%s", user["id"])
            return self._json(
                {"ok": True}, 200, [("Set-Cookie", self._session_cookie())]
            )
        except Exception:  # noqa: BLE001
            LOG.exception("DELETE %s 失败", parsed.path)
            return self._json({"error": "服务器内部错误"}, 500)

    def log_message(self, fmt, *args):
        LOG.info("%s %s", self._client_ip(), fmt % args)

    def log_error(self, fmt, *args):
        LOG.warning("%s %s", self._client_ip(), fmt % args)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    stats = LIB.stats()
    LOG.info("已加载 %s 本书、%s 回、%s 字", stats["books"], stats["chapters"], stats["chars"])
    LOG.info("服务已启动：http://localhost:%s", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
