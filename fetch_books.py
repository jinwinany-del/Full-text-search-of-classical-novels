#!/usr/bin/env python3
"""抓取公版古典小说原文到 data/books/。

数据来源：
- 《三国演义》《水浒传》《红楼梦》等古典小说：NiuTrans/Classical-Modern（MIT 许可）
- 《西游记》：gazhikaba/xiyouji_txt
所收小说本身均为公版作品（作者逝世超过 50 年）。
"""

import concurrent.futures as futures
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "books")

NIU_CONTENTS = "https://api.github.com/repos/NiuTrans/Classical-Modern/contents/"
NIU_RAW_BASE = "https://ghproxy.net/https://raw.githubusercontent.com/NiuTrans/Classical-Modern/main/"
NIU_RAW_FALLBACK = "https://raw.githubusercontent.com/NiuTrans/Classical-Modern/main/"

XYJ_API = "https://api.github.com/repos/gazhikaba/xiyouji_txt/contents/"
XYJ_RAW = "https://ghproxy.net/https://raw.githubusercontent.com/gazhikaba/xiyouji_txt/master/{name}"
XYJ_RAW_FALLBACK = "https://raw.githubusercontent.com/gazhikaba/xiyouji_txt/master/{name}"

NIU_BOOKS = [
    "三国演义", "水浒传", "红楼梦",
    "东周列国志", "隋唐演义", "三侠五义", "杨家将",
    "封神演义", "镜花缘",
    "儒林外史", "官场现形记", "老残游记", "孽海花", "海上花列传",
]

CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
             "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(text):
    total, num = 0, 0
    for ch in text:
        if ch in CN_DIGITS:
            num = CN_DIGITS[ch]
        elif ch in CN_UNITS:
            total += (num or 1) * CN_UNITS[ch]
            num = 0
    return total + num


def fetch(url, retries=4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "book-search/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8-sig")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下载失败：{url}（{last}）")


def fetch_any(urls, retries=2):
    last = None
    for url in urls:
        try:
            return fetch(url, retries=retries)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"全部镜像失败：{last}")


def save(book, no, content):
    folder = os.path.join(DATA, book)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{no:03d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")


def exists(book, no):
    return os.path.isfile(os.path.join(DATA, book, f"{no:03d}.txt"))


def grab_niu(book):
    listing = json.loads(fetch(NIU_CONTENTS + urllib.parse.quote(f"古文原文/{book}")))
    chapters = []
    for item in listing:
        name = item["name"]
        if item["type"] == "dir" and re.fullmatch(r"第[零〇一二三四五六七八九十百]+回", name):
            chapters.append((cn_to_int(name[1:-1]), name))
    chapters.sort()

    def work(entry):
        no, name = entry
        if exists(book, no):
            return no
        try:
            path = urllib.parse.quote(f"古文原文/{book}/{name}/text.txt")
            text = fetch_any([NIU_RAW_BASE + path, NIU_RAW_FALLBACK + path])
            text = html.unescape(text)
            text = text.replace("<疒皇>", "㾮").replace("&", "，")
            text = re.sub(r"<[^>]+>", "", text)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0] if lines else name
            body = "\n".join(lines[1:])
            save(book, no, f"{name} {title}\n\n{body}")
            print(f"  {book} {name} ok", flush=True)
            return no
        except Exception as exc:  # noqa: BLE001
            print(f"  {book} {name} 跳过：{exc}", flush=True)
            return None

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        done = [x for x in pool.map(work, chapters) if x is not None]
    print(f"{book}: {len(done)} 回", flush=True)


def grab_xiyouji():
    listing = json.loads(fetch(XYJ_API))
    files = [item["name"] for item in listing
             if item["name"].endswith(".txt") and item["name"][:3].isdigit()]
    files.sort()

    def work(name):
        no = int(name[:3])
        if exists("西游记", no):
            return no
        try:
            quoted = urllib.parse.quote(name)
            text = fetch_any([XYJ_RAW.format(name=quoted), XYJ_RAW_FALLBACK.format(name=quoted)])
            save("西游记", no, text)
            print(f"  西游记 {name} ok", flush=True)
            return no
        except Exception as exc:  # noqa: BLE001
            print(f"  西游记 {name} 跳过：{exc}", flush=True)
            return None

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        done = [x for x in pool.map(work, files) if x is not None]
    print(f"西游记: {len(done)} 回", flush=True)


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    for name in NIU_BOOKS:
        grab_niu(name)
    grab_xiyouji()
    print("全部完成")
