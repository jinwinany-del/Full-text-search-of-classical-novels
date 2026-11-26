#!/usr/bin/env python3
"""补充公版古典小说到 data/books/，目标总数 100 本。

新增文本来自 ibyli/chinese-novel（MIT 许可）：
- https://github.com/ibyli/chinese-novel
- https://gitee.com/chobits81/chinese-novel

只收录作者已逝世超过 50 年的公版章回小说，并跳过现代前言、序跋和校点说明。
脚本会生成 data/extra_books.json，供 library.py 读取作者、分类与简介。
"""

import html as html_lib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "books")
META_PATH = os.path.join(ROOT, "data", "extra_books.json")
LICENSE_SRC = "licenses/chinese-novel-LICENSE.txt"

SOURCE_URLS = [
    "https://gitee.com/chobits81/chinese-novel/repository/archive/master.zip",
    "https://codeload.github.com/luoxuhai/chinese-novel/zip/refs/heads/master",
]

# (源分类, 书名, 本站分类)
SELECTION = [
    ("历史演义", "东汉演义", "历史演义"),
    ("历史演义", "西汉演义", "历史演义"),
    ("历史演义", "五代残唐", "历史演义"),
    ("历史演义", "续三国演义", "历史演义"),
    ("历史演义", "隋唐两朝志传", "历史演义"),
    ("历史演义", "北史演义", "历史演义"),
    ("历史演义", "南史演义", "历史演义"),
    ("历史演义", "东西晋演义", "历史演义"),
    ("历史演义", "大宋中兴通俗演义", "历史演义"),
    ("历史演义", "飞龙全传", "历史演义"),
    ("历史演义", "说唐", "历史演义"),
    ("历史演义", "樵史通俗演义", "历史演义"),
    ("历史演义", "二十四史通俗演义", "历史演义"),
    ("历史演义", "夏商野史", "历史演义"),
    ("历史演义", "开辟演义", "历史演义"),
    ("历史演义", "周朝秘史", "历史演义"),
    ("历史演义", "狄青演义", "历史演义"),
    ("英雄传奇", "儿女英雄传", "英雄传奇"),
    ("英雄传奇", "说岳全传", "英雄传奇"),
    ("英雄传奇", "水浒后传", "英雄传奇"),
    ("英雄传奇", "小五义", "英雄传奇"),
    ("英雄传奇", "续小五义", "英雄传奇"),
    ("英雄传奇", "七剑十三侠", "英雄传奇"),
    ("英雄传奇", "仙侠五花剑", "英雄传奇"),
    ("英雄传奇", "薛刚反唐", "英雄传奇"),
    ("英雄传奇", "万花楼", "英雄传奇"),
    ("英雄传奇", "粉妆楼", "英雄传奇"),
    ("英雄传奇", "呼家将", "英雄传奇"),
    ("英雄传奇", "木兰奇女传", "英雄传奇"),
    ("英雄传奇", "金台全传", "英雄传奇"),
    ("英雄传奇", "银瓶梅", "英雄传奇"),
    ("英雄传奇", "笏山记", "英雄传奇"),
    ("英雄传奇", "章台柳", "英雄传奇"),
    ("其他", "绿牡丹", "英雄传奇"),
    ("鬼怪神魔", "东游记", "神魔小说"),
    ("鬼怪神魔", "南游记", "神魔小说"),
    ("鬼怪神魔", "北游记", "神魔小说"),
    ("鬼怪神魔", "后西游记", "神魔小说"),
    ("鬼怪神魔", "续西游记", "神魔小说"),
    ("鬼怪神魔", "西游补", "神魔小说"),
    ("鬼怪神魔", "三遂平妖传", "神魔小说"),
    ("鬼怪神魔", "女仙外史", "神魔小说"),
    ("鬼怪神魔", "绿野仙踪", "神魔小说"),
    ("鬼怪神魔", "济公全传", "神魔小说"),
    ("鬼怪神魔", "续济公传", "神魔小说"),
    ("鬼怪神魔", "东度记", "神魔小说"),
    ("鬼怪神魔", "南海观音菩萨出身修行传", "神魔小说"),
    ("鬼怪神魔", "唐钟馗平鬼传", "神魔小说"),
    ("鬼怪神魔", "斩鬼传", "神魔小说"),
    ("鬼怪神魔", "绣云阁", "神魔小说"),
    ("鬼怪神魔", "锋剑春秋", "神魔小说"),
    ("鬼怪神魔", "雷峰塔奇传", "神魔小说"),
    ("鬼怪神魔", "续镜花缘", "神魔小说"),
    ("世态人情", "醒世姻缘传", "世情小说"),
    ("世态人情", "林兰香", "世情小说"),
    ("世态人情", "好逑传", "世情小说"),
    ("世态人情", "平山冷燕", "世情小说"),
    ("世态人情", "玉娇梨", "世情小说"),
    ("世态人情", "花月痕", "世情小说"),
    ("世态人情", "青楼梦", "世情小说"),
    ("世态人情", "风月梦", "世情小说"),
    ("世态人情", "蜃楼志", "世情小说"),
    ("世态人情", "金云翘传", "世情小说"),
    ("世态人情", "赛花铃", "世情小说"),
    ("其他", "雪月梅", "世情小说"),
    ("其他", "绘芳录", "世情小说"),
    ("谴责公案", "二十年目睹之怪现状", "讽刺谴责"),
    ("谴责公案", "九命奇冤", "讽刺谴责"),
    ("谴责公案", "冷眼观", "讽刺谴责"),
    ("谴责公案", "刘公案", "讽刺谴责"),
    ("谴责公案", "彭公案", "讽刺谴责"),
    ("谴责公案", "施公案", "讽刺谴责"),
    ("谴责公案", "狄公案", "讽刺谴责"),
    ("谴责公案", "龙图公案", "讽刺谴责"),
    ("谴责公案", "海公大红袍全传", "讽刺谴责"),
    ("谴责公案", "海公小红袍全传", "讽刺谴责"),
    ("谴责公案", "包公传", "讽刺谴责"),
    ("谴责公案", "蓝公案", "讽刺谴责"),
    ("谴责公案", "林公案", "讽刺谴责"),
    ("谴责公案", "于公案", "讽刺谴责"),
    ("谴责公案", "李公案", "讽刺谴责"),
    ("谴责公案", "春阿氏谋夫案", "讽刺谴责"),
    ("谴责公案", "杨乃武与小白菜", "讽刺谴责"),
    ("谴责公案", "梼杌萃编", "讽刺谴责"),
    ("世态人情", "文明小史", "讽刺谴责"),
]

# 只覆盖较有名的书目，其余使用“朝代 + 作者”的通用简介。
BLURBS = {
    "西汉演义": "楚汉相争到西汉覆亡，帝王将相轮番登场。",
    "东汉演义": "东汉一朝兴衰，光武中兴与宦官外戚之争。",
    "五代残唐": "唐末黄巢起义至五代十国，乱世英雄辈出。",
    "续三国演义": "三国归晋之后，两晋南北朝的纷争与兴亡。",
    "隋唐两朝志传": "隋末群雄并起，李唐开国与开元天宝旧事。",
    "东西晋演义": "西晋统一到东晋偏安，门阀与胡汉纷争。",
    "大宋中兴通俗演义": "靖康之变后宋室南渡，岳飞等抗金故事。",
    "飞龙全传": "赵匡胤发迹与陈桥兵变，宋初开国传奇。",
    "说唐": "隋末十八路反王，秦琼、程咬金等英雄聚义。",
    "儿女英雄传": "安骥与何玉凤、张金凤的侠义姻缘。",
    "说岳全传": "岳飞抗金，十二道金牌与风波亭冤案。",
    "水浒后传": "梁山好汉后裔与幸存者再度聚义抗金。",
    "小五义": "三侠五义后辈小五义行侠仗义。",
    "续小五义": "小五义群侠继续除暴安良、平定叛乱。",
    "七剑十三侠": "明代七剑十三侠协助王守仁平定宁王。",
    "薛刚反唐": "薛丁山之子薛刚反唐，薛家将故事。",
    "呼家将": "呼延赞家族抗辽保宋的忠勇传奇。",
    "东游记": "八仙得道成仙的传说。",
    "南游记": "华光天王降妖伏魔、皈依佛道。",
    "北游记": "真武大帝降世修行、收服妖魔。",
    "后西游记": "花果山新石猴随唐半偈西行取经。",
    "西游补": "孙悟空坠入情梦，穿梭古今的奇幻续书。",
    "三遂平妖传": "胡永儿与王则起事，诸葛遂智等平妖。",
    "女仙外史": "月殿嫦娥转世唐赛儿，起兵靖难的故事。",
    "绿野仙踪": "冷于冰求仙问道、度化世人的神魔小说。",
    "济公全传": "济公疯癫济世、惩恶扬善的民间传奇。",
    "东度记": "达摩东渡传法，度化众生的故事。",
    "雷峰塔奇传": "白蛇与许仙的爱情传说。",
    "醒世姻缘传": "晁源与狄希陈两世姻缘的世情小说。",
    "林兰香": "耿朗一家的盛衰与妻妾命运。",
    "好逑传": "铁中玉与水冰心的侠义姻缘。",
    "平山冷燕": "平如衡、山黛、冷绛雪、燕白颔的才子佳人故事。",
    "玉娇梨": "苏友白与白红玉、卢梦梨的姻缘。",
    "花月痕": "韦痴珠、韩荷生与名妓的悲欢。",
    "金云翘传": "王翠翘坎坷飘零的一生。",
    "二十年目睹之怪现状": "以“九死一生”的见闻揭露晚清社会怪状。",
    "九命奇冤": "广东梁、凌两家命案与冤狱平反。",
    "刘公案": "刘墉断案、惩办贪官恶霸的公案小说。",
    "彭公案": "彭朋断案与群侠除暴安良。",
    "施公案": "施仕伦断案，黄天霸等侠士相助。",
    "狄公案": "狄仁杰断案如神的公案故事。",
    "龙图公案": "包拯断案、伸张正义的公案集。",
    "海公大红袍全传": "海瑞刚直不阿、断案除奸的故事。",
    "杨乃武与小白菜": "晚清杨乃武与小白菜的著名冤案。",
    "梼杌萃编": "晚清官场与士林的讽刺小说。",
    "文明小史": "晚清社会变革中的新旧冲突。",
}

CHAPTER_RE = re.compile(r"第\s*[零〇○一二三四五六七八九十百千0-9]+\s*[回卷则章篇节]")
PREFACE_RE = re.compile(
    r"(序|前言|说明|小引|引子|楔子|附录|后记|跋|题记|凡例|简介|导读|"
    r"校点|整理|出版|再版|重印|原序|小序|丛语|目录|弁言|叙言|叙|读法)"
)
NAV_RE = re.compile(
    r"(上一章|下一章|返回目录|加入书签|请记住本站|手机阅读|章节错误|举报|"
    r"www\.|https?://|mingqingxiaoshuo|笔趣阁|顶点小说|本章未完)"
)
CN_DIGITS = {"零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "两": 2, "三": 3,
             "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_number(text):
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(ch in text for ch in CN_UNITS):
        total, num = 0, 0
        for ch in text:
            if ch in CN_DIGITS:
                num = CN_DIGITS[ch]
            elif ch in CN_UNITS:
                total += (num or 1) * CN_UNITS[ch]
                num = 0
        return total + num
    digits = "".join(str(CN_DIGITS[ch]) for ch in text if ch in CN_DIGITS)
    return int(digits) if digits else None


def chapter_number(title):
    match = re.search(r"第\s*([零〇○一二三四五六七八九十百千0-9]+)\s*[回卷则章篇节]", title)
    return cn_number(match.group(1)) if match else None


def ensure_source():
    cache = os.path.join(tempfile.gettempdir(), "chinese-novel-src")
    root = os.path.join(cache, "chinese-novel-master", "resources")
    if os.path.isdir(root):
        return root

    os.makedirs(cache, exist_ok=True)
    archive = os.path.join(cache, "chinese-novel.zip")
    last_error = None
    for url in SOURCE_URLS:
        try:
            print(f"下载语料：{url}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "novel-search/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as out:
                shutil.copyfileobj(resp, out)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"  下载失败：{exc}", flush=True)
    else:
        raise RuntimeError(f"无法下载语料：{last_error}")

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(cache)
    if not os.path.isdir(root):
        raise RuntimeError(f"语料目录不存在：{root}")
    return root


def clean_html(raw):
    raw = re.sub(r"(?is)\?a\s+class=\"__cf_email__\".*?(?=<script|<)", "", raw)
    raw = re.sub(r"(?is)<a[^>]*__cf_email__[^>]*>.*?</a>", "", raw)
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", raw)
    raw = re.sub(r"\[email\s*(?:&nbsp;)?protected\]", "", raw)
    raw = re.sub(r"(?is)<!--.*?-->", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p\s*>", "\n\n", raw)
    raw = re.sub(r"(?i)<p[^>]*>", "\n\n", raw)
    raw = re.sub(r"(?i)</div\s*>", "\n\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", "", raw)
    raw = html_lib.unescape(raw)
    raw = raw.replace("\xa0", " ").replace("\u3000", " ").replace("\u200b", "")
    raw = raw.replace("&", "□")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    lines = []
    for line in raw.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if NAV_RE.search(line):
            continue
        if re.fullmatch(r"第?\s*\d+\s*页", line):
            continue
        lines.append(line)
    return lines


def chapter_entries(info, book_name):
    entries = []
    for index, raw in enumerate(info.get("catalogues") or []):
        title = re.sub(r"\s+", " ", (raw or "").strip())
        if not title or title == book_name:
            continue
        if CHAPTER_RE.search(title):
            entries.append((index, title))
        elif PREFACE_RE.search(title):
            continue
        else:
            entries.append((index, title))

    numbers = [chapter_number(title) for _, title in entries]
    if any(n is not None for n in numbers):
        known = [(i, t, n) for (i, t), n in zip(entries, numbers) if n is not None]
        if known and known[0][2] > known[-1][2]:
            entries = [(i, t) for i, t, _ in sorted(known, key=lambda row: row[2])]
    if book_name == "醒世姻缘传":
        intro = [entry for entry in entries if "引起" in entry[1]]
        entries = intro + [entry for entry in entries if "引起" not in entry[1]]
    return entries


def save_book(book_dir, title, entries, meta, category, author, dynasty):
    folder = os.path.join(DATA, title)
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.endswith(".txt"):
            os.remove(os.path.join(folder, old))

    saved = 0
    for original_index, chapter_title in entries:
        path = os.path.join(book_dir, f"{original_index}.html")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            paragraphs = clean_html(f.read())
        if title == "续三国演义":
            paragraphs = [
                p.replace("慕?", "慕□").replace("攻?", "攻□").replace("延?", "延□")
                for p in paragraphs
            ]
        if not paragraphs:
            continue
        saved += 1
        with open(os.path.join(folder, f"{saved:03d}.txt"), "w", encoding="utf-8") as f:
            f.write(chapter_title + "\n\n" + "\n".join(paragraphs) + "\n")

    if saved == 0:
        raise RuntimeError(f"{title} 没有生成任何章节")

    meta.append({
        "title": title,
        "category": category,
        "author": author,
        "dynasty": dynasty,
        "blurb": BLURBS.get(title) or default_blurb(author, dynasty),
        "chapters": saved,
    })
    return saved


def default_blurb(author, dynasty):
    era = f"{dynasty}代" if dynasty else "古代"
    if author and author not in ("佚名", "不题撰人", "无名氏", "不署撰人"):
        return f"{era}章回小说，{author}著。"
    return f"{era}章回小说。"


def main():
    source_root = ensure_source()
    repo_root = os.path.dirname(source_root)
    license_src = os.path.join(repo_root, "LICENSE")
    if os.path.isfile(license_src):
        license_dst = os.path.join(ROOT, LICENSE_SRC)
        os.makedirs(os.path.dirname(license_dst), exist_ok=True)
        shutil.copyfile(license_src, license_dst)

    os.makedirs(DATA, exist_ok=True)
    books = []
    for source_cat, title, target_cat in SELECTION:
        book_dir = os.path.join(source_root, source_cat, title)
        info_path = os.path.join(book_dir, "info.json")
        if not os.path.isfile(info_path):
            raise RuntimeError(f"缺少源书目：{source_cat}/{title}")
        with open(info_path, encoding="utf-8") as f:
            info = json.load(f)
        author_info = info.get("author") or {}
        author = author_info.get("name") or "佚名"
        dynasty = author_info.get("dynasty") or ""
        if dynasty in ("未知", "不详"):
            dynasty = ""
        entries = chapter_entries(info, title)
        saved = save_book(book_dir, title, entries, books, target_cat, author, dynasty)
        print(f"{title}: {saved} 章", flush=True)

    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "source": {
                "name": "ibyli/chinese-novel",
                "url": "https://github.com/ibyli/chinese-novel",
                "license": "MIT",
            },
            "books": books,
        }, f, ensure_ascii=False, indent=2)
    print(f"完成：{len(books)} 本，元数据 {META_PATH}", flush=True)


if __name__ == "__main__":
    main()
