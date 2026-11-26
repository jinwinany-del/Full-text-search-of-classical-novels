"""古典小说检索内核（SQLite FTS5 版）。

文本存放在 data/books/<书名>/<001>.txt，启动时若索引缺失或文本有更新，
会自动把正文写入 data/library.db 并建立全文索引。
"""

import json
import math
import os
import re
import sqlite3
import sys
from collections import OrderedDict
from contextlib import closing

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "books")
DB_PATH = os.path.join(ROOT, "data", "library.db")
EXTRA_META_PATH = os.path.join(ROOT, "data", "extra_books.json")
OVERSEAS_META_PATH = os.path.join(ROOT, "data", "overseas_books.json")
COVERS_PATH = os.path.join(ROOT, "data", "covers.json")

PER_PAGE = 20
SNIPPET_MAX = 110
SENTENCE_MARKS = "。！？；….!?"
QUERY_SPLIT_RE = re.compile(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+")

CATEGORIES = [
    {"name": "历史演义", "desc": "以历史为骨，演一代兴亡。",
     "books": ["三国演义", "东周列国志", "隋唐演义"]},
    {"name": "英雄传奇", "desc": "草莽聚义，快意恩仇。",
     "books": ["水浒传", "三侠五义", "杨家将"]},
    {"name": "神魔小说", "desc": "神魔变幻，寄托世情。",
     "books": ["西游记", "封神演义", "镜花缘"]},
    {"name": "世情小说", "desc": "一府兴衰，众生悲欢。",
     "books": ["红楼梦", "海上花列传"]},
    {"name": "讽刺谴责", "desc": "以笔为镜，照见世相。",
     "books": ["儒林外史", "官场现形记", "老残游记", "孽海花"]},
    {"name": "海外名著", "desc": "泰西经典，英文原文。", "books": []},
]

BLURBS = {
    "三国演义": "东汉末年群雄并起，魏蜀吴三分天下，终归于晋。",
    "水浒传": "一百零八位好汉聚义梁山，替天行道，终归招安。",
    "西游记": "唐僧师徒四人西行取经，历经八十一难。",
    "红楼梦": "贾府由盛而衰，宝黛爱情与一干人物的命运浮沉。",
    "东周列国志": "自西周覆亡至秦统一，五百年诸侯争霸与列国兴亡。",
    "隋唐演义": "隋末群雄并起，李唐开国，英雄儿女与宫廷风云。",
    "三侠五义": "包公断案，五鼠闹东京，群侠除暴安良。",
    "杨家将": "杨门世代忠勇，抗辽保宋，一门英烈。",
    "封神演义": "商周更替，阐截二教斗法，封神榜上定功过。",
    "镜花缘": "唐敖海外游历，百位才女应试，奇国异俗寄讽喻。",
    "海上花列传": "沪上花场众生相，以吴语对白写尽世态人情。",
    "儒林外史": "科举士林百态，功名富贵场中的众生相。",
    "官场现形记": "晚清官场群像，钻营倾轧，穷形尽相。",
    "老残游记": "走方郎中老残游历山东，见吏治之酷与世道之艰。",
    "孽海花": "状元名妓的浮沉，映照晚清士大夫与时代变局。",
}

AUTHORS = {
    "三国演义": "明 · 罗贯中",
    "水浒传": "明 · 施耐庵",
    "西游记": "明 · 吴承恩",
    "红楼梦": "清 · 曹雪芹",
    "东周列国志": "明 · 冯梦龙 编",
    "隋唐演义": "清 · 褚人获",
    "三侠五义": "清 · 石玉昆",
    "杨家将": "明 · 熊大木",
    "封神演义": "明 · 许仲琳",
    "镜花缘": "清 · 李汝珍",
    "儒林外史": "清 · 吴敬梓",
    "官场现形记": "清 · 李宝嘉",
    "老残游记": "清 · 刘鹗",
    "孽海花": "清 · 曾朴",
    "海上花列传": "清 · 韩邦庆",
}


def load_extra_metadata(path=EXTRA_META_PATH):
    """把补充书目的作者、分类和简介并入静态目录。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return

    categories = {category["name"]: category for category in CATEGORIES}
    for book in data.get("books", []):
        title = (book.get("title") or "").strip()
        category_name = (book.get("category") or "").strip()
        if not title or category_name not in categories:
            continue
        books = categories[category_name]["books"]
        if title not in books:
            books.append(title)
        if book.get("blurb"):
            BLURBS[title] = book["blurb"]
        author = (book.get("author") or "").strip()
        dynasty = (book.get("dynasty") or "").strip()
        if author:
            AUTHORS[title] = f"{dynasty} · {author}" if dynasty else author


load_extra_metadata()
load_extra_metadata(OVERSEAS_META_PATH)

COVERS = {}


def load_covers(path=COVERS_PATH):
    """读取本地生成的封面清单。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    for title, cover in (data.get("covers") or {}).items():
        if isinstance(cover, str) and cover:
            COVERS[title] = cover


load_covers()

SCHEMA = """
CREATE TABLE books(
    id INTEGER PRIMARY KEY,
    title TEXT UNIQUE NOT NULL,
    chars INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE chapters(
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    no INTEGER NOT NULL,
    title TEXT NOT NULL,
    UNIQUE(book_id, no)
);
CREATE TABLE paragraphs(
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    chapter_no INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    para_no INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
    tokens,
    content=''
);
CREATE INDEX idx_paragraphs_chapter ON paragraphs(book_id, chapter_no, para_no);
CREATE INDEX idx_chapters_book ON chapters(book_id, no);
"""


def tokenize(text):
    """把中文拆成单字、英文拆成单词，交给 FTS5 做短语匹配。"""
    tokens = []
    word = []
    for ch in text:
        if ch.isascii() and ch.isalnum():
            word.append(ch.lower())
        elif ch.isalnum():
            if word:
                tokens.append("".join(word))
                word = []
            tokens.append(ch.lower())
        elif word:
            tokens.append("".join(word))
            word = []
    if word:
        tokens.append("".join(word))
    return " ".join(tokens)


def split_terms(query):
    """按空格和中文/英文标点切分查询词。"""
    return [term for term in QUERY_SPLIT_RE.split(query.strip()) if term]


def snippet(paragraph, anchor, ranges):
    """截取命中位置所在的一到两句话。"""
    start = 0
    for i in range(anchor - 1, -1, -1):
        if paragraph[i] in SENTENCE_MARKS:
            start = i + 1
            break

    end = len(paragraph)
    for i in range(anchor, len(paragraph)):
        if paragraph[i] in SENTENCE_MARKS:
            end = i + 1
            break

    if end - start < 36 and end < len(paragraph):
        for i in range(end, len(paragraph)):
            if paragraph[i] in SENTENCE_MARKS:
                end = i + 1
                break
        else:
            end = len(paragraph)

    if end - start > SNIPPET_MAX:
        start = max(start, anchor - SNIPPET_MAX // 3)
        end = min(len(paragraph), start + SNIPPET_MAX)

    raw = paragraph[start:end]
    text = raw.strip()
    offset = start + (len(raw) - len(raw.lstrip()))

    return (
        text,
        [
            {"start": r["start"] - offset, "length": r["length"]}
            for r in ranges
            if offset <= r["start"] < end
        ],
        start > 0,
        end < len(paragraph),
    )


def build_database(data_dir=DATA_DIR, db_path=DB_PATH):
    if not os.path.isdir(data_dir):
        raise RuntimeError("未找到 data/books，请先运行 python3 fetch_books.py")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        with conn:
            for name in sorted(os.listdir(data_dir)):
                folder = os.path.join(data_dir, name)
                if not os.path.isdir(folder):
                    continue

                chapters = []
                for fname in sorted(os.listdir(folder)):
                    if not fname.endswith(".txt"):
                        continue
                    with open(os.path.join(folder, fname), encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                    if len(lines) >= 2:
                        chapters.append((int(fname[:3]), lines[0], lines[1:]))

                if not chapters:
                    continue

                cursor = conn.execute("INSERT INTO books(title) VALUES(?)", (name,))
                book_id = cursor.lastrowid
                chars = 0

                for no, chapter_title, paragraphs in chapters:
                    conn.execute(
                        "INSERT INTO chapters(book_id, no, title) VALUES(?, ?, ?)",
                        (book_id, no, chapter_title),
                    )
                    for index, text in enumerate(paragraphs, 1):
                        chars += len(text)
                        cursor = conn.execute(
                            "INSERT INTO paragraphs(book_id, chapter_no, chapter_title, para_no, text) "
                            "VALUES(?, ?, ?, ?, ?)",
                            (book_id, no, chapter_title, index, text),
                        )
                        conn.execute(
                            "INSERT INTO paragraphs_fts(rowid, tokens) VALUES(?, ?)",
                            (cursor.lastrowid, tokenize(text)),
                        )

                conn.execute("UPDATE books SET chars = ? WHERE id = ?", (chars, book_id))

        with conn:
            conn.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('optimize')")
    finally:
        conn.close()


def needs_rebuild(data_dir=DATA_DIR, db_path=DB_PATH):
    if not os.path.isfile(db_path):
        return True
    db_time = os.path.getmtime(db_path)
    if not os.path.isdir(data_dir):
        return False
    for root, _, files in os.walk(data_dir):
        for name in files:
            if name.endswith(".txt") and os.path.getmtime(os.path.join(root, name)) > db_time:
                return True
    return False


class Library:
    def __init__(self, db_path=DB_PATH, data_dir=DATA_DIR):
        if needs_rebuild(data_dir, db_path):
            build_database(data_dir, db_path)
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA mmap_size = 268435456")
        return conn

    def stats(self):
        with closing(self._connect()) as conn:
            books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            chapters = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
            chars = conn.execute("SELECT COALESCE(SUM(chars), 0) FROM books").fetchone()[0]
        return {"books": books, "chapters": chapters, "chars": chars}

    def _book_id(self, conn, title):
        row = conn.execute("SELECT id FROM books WHERE title = ?", (title,)).fetchone()
        if not row:
            raise ValueError("没有这本书")
        return row["id"]

    def library_catalog(self):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT b.title, b.chars, COUNT(c.id) AS chapters "
                "FROM books b LEFT JOIN chapters c ON c.book_id = b.id GROUP BY b.id"
            ).fetchall()
        meta = {row["title"]: row for row in rows}

        catalog = []
        for category in CATEGORIES:
            items = []
            for title in category["books"]:
                row = meta.get(title)
                if not row:
                    continue
                items.append({
                    "title": title,
                    "author": AUTHORS.get(title, ""),
                    "cover": COVERS.get(title, ""),
                    "chapters": row["chapters"],
                    "chars": row["chars"],
                    "blurb": BLURBS.get(title, ""),
                })
            if items:
                catalog.append({
                    "name": category["name"],
                    "desc": category["desc"],
                    "books": items,
                })
        return {"categories": catalog}

    def book_chapters(self, title):
        with closing(self._connect()) as conn:
            book_id = self._book_id(conn, title)
            rows = conn.execute(
                "SELECT no, title FROM chapters WHERE book_id = ? ORDER BY no", (book_id,)
            ).fetchall()
        return {"title": title, "chapters": [{"no": r["no"], "title": r["title"]} for r in rows]}

    def chapter(self, book_title, no):
        with closing(self._connect()) as conn:
            book_id = self._book_id(conn, book_title)
            rows = conn.execute(
                "SELECT chapter_title, para_no, text FROM paragraphs "
                "WHERE book_id = ? AND chapter_no = ? ORDER BY para_no",
                (book_id, no),
            ).fetchall()
        if not rows:
            raise ValueError("找不到这一回")
        return {
            "no": no,
            "title": rows[0]["chapter_title"],
            "paragraphs": [r["text"] for r in rows],
        }

    def search(self, query, book=None, page=1, per_page=PER_PAGE):
        terms = split_terms(query)
        if not terms:
            raise ValueError("请输入要查找的字词")
        if len(query) > 120:
            raise ValueError("查询太长了")

        phrases = []
        for term in terms:
            tokens = tokenize(term)
            if tokens:
                phrases.append('"' + tokens + '"')
        if not phrases:
            raise ValueError("请输入文字或字母")
        fts_query = " AND ".join(phrases)

        filter_sql = ""
        filter_params = []
        with closing(self._connect()) as conn:
            if book:
                filter_sql = " AND p.book_id = ?"
                filter_params = [self._book_id(conn, book)]

            counts_rows = conn.execute(
                "SELECT p.book_id, COUNT(*) AS c FROM paragraphs_fts "
                "JOIN paragraphs p ON p.id = paragraphs_fts.rowid "
                "WHERE paragraphs_fts MATCH ?" + filter_sql + " GROUP BY p.book_id",
                [fts_query, *filter_params],
            ).fetchall()
            counts = {r["book_id"]: r["c"] for r in counts_rows}
            total = sum(counts.values())
            pages = max(1, math.ceil(total / per_page))
            page = max(1, min(int(page), pages))

            titles = {
                r["id"]: r["title"]
                for r in conn.execute("SELECT id, title FROM books").fetchall()
            }

            rows = conn.execute(
                "WITH matched AS ("
                "  SELECT p.id, p.book_id, p.chapter_no, p.para_no "
                "  FROM paragraphs_fts JOIN paragraphs p ON p.id = paragraphs_fts.rowid "
                "  WHERE paragraphs_fts MATCH ?" + filter_sql +
                "), book_counts AS ("
                "  SELECT book_id, COUNT(*) AS c FROM matched GROUP BY book_id"
                ") "
                "SELECT p.id, p.book_id, p.chapter_no, p.chapter_title, p.para_no, p.text "
                "FROM matched m "
                "JOIN book_counts bc ON bc.book_id = m.book_id "
                "JOIN paragraphs p ON p.id = m.id "
                "ORDER BY bc.c DESC, p.book_id, m.chapter_no, m.para_no "
                "LIMIT ? OFFSET ?",
                [fts_query, *filter_params, per_page, (page - 1) * per_page],
            ).fetchall()

        groups = OrderedDict()
        for row in rows:
            text = row["text"]
            haystack = text.lower()
            ranges = []
            for term in terms:
                needle = term.lower()
                pos = haystack.find(needle)
                while pos != -1:
                    ranges.append({"start": pos, "length": len(needle)})
                    pos = haystack.find(needle, pos + len(needle))
            ranges.sort(key=lambda r: (r["start"], r["length"]))

            anchor = ranges[0]["start"] if ranges else 0
            snippet_text, rel_ranges, cut_before, cut_after = snippet(text, anchor, ranges)
            title = titles[row["book_id"]]

            group = groups.setdefault(title, {
                "title": title,
                "count": counts[row["book_id"]],
                "hits": [],
            })
            group["hits"].append({
                "book": title,
                "chapter_no": row["chapter_no"],
                "chapter_title": row["chapter_title"],
                "paragraph": row["para_no"],
                "offset": anchor + 1,
                "context": snippet_text,
                "ranges": rel_ranges,
                "cut_before": cut_before,
                "cut_after": cut_after,
            })

        return {
            "query": " ".join(terms),
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": per_page,
            "counts": {titles[bid]: c for bid, c in counts.items()},
            "groups": list(groups.values()),
        }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_database()
        size = os.path.getsize(DB_PATH) / 1024 / 1024
        print(f"索引已重建：{DB_PATH}（{size:.1f} MB）")
    else:
        print("用法：python3 library.py build")
