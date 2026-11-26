#!/usr/bin/env python3
"""补充海外公版小说到 data/books/。

文本来自 Project Gutenberg 的公开镜像，均为原作者与英译者逝世超过 50 年、
在中国属于公有领域的作品（英文原版或 19 世纪公版英译本）。脚本会剥离
古腾堡页眉页脚、许可文本与插图标记，按章拆分，并生成 data/overseas_books.json
供 library.py 读取作者、分类与简介。
"""

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "books")
META_PATH = os.path.join(ROOT, "data", "overseas_books.json")
CACHE = os.path.join(tempfile.gettempdir(), "gutenberg-pg-cache")
CATEGORY = "海外名著"

MIRRORS = [
    "http://aleph.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://gutenberg.pglaf.org/cache/epub/{id}/pg{id}.txt",
]

# GITenberg 是古腾堡文本的 GitHub 镜像，走 jsDelivr CDN 下载更快。
GITENBERG = {
    1342: "Pride-and-Prejudice_1342",
    161: "Sense-and-Sensibility_161",
    1260: "Jane-Eyre_1260",
    768: "Wuthering-Heights_768",
    730: "Oliver-Twist_730",
    98: "A-Tale-of-Two-Cities_98",
    1400: "Great-Expectations_1400",
    766: "David-Copperfield_766",
    110: "Tess-of-the-d-Urbervilles--a-Pure-Woman_110",
    1661: "The-Adventures-of-Sherlock-Holmes_1661",
    2852: "The-Hound-of-the-Baskervilles_2852",
    84: "Frankenstein_84",
    345: "Dracula_345",
    11: "Alice-s-Adventures-in-Wonderland_11",
    829: "Gulliver-s-Travels_829",
    521: "The-Life-and-Adventures-of-Robinson-Crusoe_521",
    120: "Treasure-Island_120",
    2701: "Moby-Dick--Or-The-Whale_2701",
    33: "The-Scarlet-Letter_33",
    514: "Little-Women_514",
    55: "The-Wonderful-Wizard-of-Oz_55",
    164: "Twenty-Thousand-Leagues-under-the-Sea_164",
    103: "Around-the-World-in-80-Days_103",
    1184: "The-Count-of-Monte-Cristo_1184",
    2600: "War-and-Peace_2600",
    1399: "Anna-Karenina_1399",
    2554: "Crime-and-Punishment_2554",
    996: "Don-Quixote_996",
}

# 只收原作者与英译者均已逝世超过 50 年的作品；书名用中文，避免与馆内已有书名冲突。
SELECTION = [
    {"title": "傲慢与偏见", "original": "Pride and Prejudice", "id": 1342,
     "author": "简·奥斯汀", "country": "英",
     "blurb": "伊丽莎白与达西的偏见与误会，十九世纪英国乡绅阶层的婚姻群像。"},
    {"title": "理智与情感", "original": "Sense and Sensibility", "id": 161,
     "author": "简·奥斯汀", "country": "英",
     "blurb": "达什伍德姐妹在拮据生活中面对情感与理智的抉择。"},
    {"title": "简·爱", "original": "Jane Eyre", "id": 1260,
     "author": "夏洛蒂·勃朗特", "country": "英",
     "blurb": "孤女简·爱历经磨难，追求独立人格与平等爱情。"},
    {"title": "呼啸山庄", "original": "Wuthering Heights", "id": 768,
     "author": "艾米莉·勃朗特", "country": "英",
     "blurb": "希斯克利夫与凯瑟琳的爱恨纠缠，荒原上的复仇与毁灭。"},
    {"title": "雾都孤儿", "original": "Oliver Twist", "id": 730,
     "author": "查尔斯·狄更斯", "country": "英",
     "blurb": "孤儿奥利弗逃出济贫院，在伦敦底层卷入贼窝。"},
    {"title": "双城记", "original": "A Tale of Two Cities", "id": 98,
     "author": "查尔斯·狄更斯", "country": "英",
     "blurb": "伦敦与巴黎双城之间，革命风暴中的爱与牺牲。"},
    {"title": "远大前程", "original": "Great Expectations", "id": 1400,
     "author": "查尔斯·狄更斯", "country": "英",
     "blurb": "孤儿匹普意外获得遗产，在阶层跃迁中经历幻灭。"},
    {"title": "大卫·科波菲尔", "original": "David Copperfield", "id": 766,
     "author": "查尔斯·狄更斯", "country": "英",
     "blurb": "大卫·科波菲尔从苦难童年到成熟作家的成长史。"},
    {"title": "德伯家的苔丝", "original": "Tess of the d'Urbervilles", "id": 110,
     "author": "托马斯·哈代", "country": "英",
     "blurb": "乡村少女苔丝在命运、礼法与爱情间的悲剧。"},
    {"title": "福尔摩斯探案集", "original": "The Adventures of Sherlock Holmes", "id": 1661,
     "author": "阿瑟·柯南·道尔", "country": "英",
     "blurb": "十二则福尔摩斯短篇探案，贝克街的推理传奇。"},
    {"title": "巴斯克维尔的猎犬", "original": "The Hound of the Baskervilles", "id": 2852,
     "author": "阿瑟·柯南·道尔", "country": "英",
     "blurb": "荒原猎犬传说笼罩下的庄园谋杀案。"},
    {"title": "弗兰肯斯坦", "original": "Frankenstein", "id": 84,
     "author": "玛丽·雪莱", "country": "英",
     "blurb": "科学家造出生命，却在恐惧中走向毁灭。"},
    {"title": "德拉库拉", "original": "Dracula", "id": 345,
     "author": "布拉姆·斯托克", "country": "英",
     "blurb": "特兰西瓦尼亚伯爵闯入伦敦，吸血鬼传说由此定型。"},
    {"title": "爱丽丝漫游奇境", "original": "Alice's Adventures in Wonderland", "id": 11,
     "author": "刘易斯·卡罗尔", "country": "英",
     "blurb": "爱丽丝坠入兔子洞，在荒诞奇境中漫游。"},
    {"title": "格列佛游记", "original": "Gulliver's Travels", "id": 829,
     "author": "乔纳森·斯威夫特", "country": "英",
     "blurb": "小人国、大人国、飞岛与慧骃国的四次航海见闻。"},
    {"title": "鲁滨逊漂流记", "original": "Robinson Crusoe", "id": 521,
     "author": "丹尼尔·笛福", "country": "英",
     "blurb": "海难余生，荒岛二十八年的生存与重建。"},
    {"title": "金银岛", "original": "Treasure Island", "id": 120,
     "author": "罗伯特·路易斯·史蒂文森", "country": "英",
     "blurb": "少年吉姆与海盗争夺藏宝图的冒险。"},
    {"title": "化身博士", "original": "Dr. Jekyll and Mr. Hyde", "id": 43,
     "author": "罗伯特·路易斯·史蒂文森", "country": "英",
     "blurb": "一剂药水分裂出善与恶的双重人格。"},
    {"title": "白鲸", "original": "Moby-Dick", "id": 2701,
     "author": "赫尔曼·梅尔维尔", "country": "美",
     "blurb": "亚哈船长执意追捕白鲸，走向毁灭的航程。"},
    {"title": "红字", "original": "The Scarlet Letter", "id": 33,
     "author": "纳撒尼尔·霍桑", "country": "美",
     "blurb": "清教小镇的通奸审判与一生赎罪。"},
    {"title": "小妇人", "original": "Little Women", "id": 514,
     "author": "路易莎·梅·奥尔科特", "country": "美",
     "blurb": "马奇家四姐妹在战争年代的成长与家庭生活。"},
    {"title": "奥兹国历险记", "original": "The Wonderful Wizard of Oz", "id": 55,
     "author": "莱曼·弗兰克·鲍姆", "country": "美",
     "blurb": "多萝西与稻草人、铁皮人、狮子同赴翡翠城。"},
    {"title": "海底两万里", "original": "Twenty Thousand Leagues under the Sea", "id": 164,
     "author": "儒勒·凡尔纳", "country": "法",
     "blurb": "尼摩船长驾驶鹦鹉螺号，展开海底航行。"},
    {"title": "八十天环游地球", "original": "Around the World in Eighty Days", "id": 103,
     "author": "儒勒·凡尔纳", "country": "法",
     "blurb": "福格为一场赌约，八十天环游世界。"},
    {"title": "基督山伯爵", "original": "The Count of Monte Cristo", "id": 1184,
     "author": "大仲马", "country": "法",
     "blurb": "爱德蒙·唐泰斯越狱寻宝，向仇人展开复仇。"},
    {"title": "悲惨世界", "original": "Les Misérables", "id": 135,
     "author": "维克多·雨果", "country": "法",
     "blurb": "冉阿让的救赎、芳汀的苦难与巴黎起义。"},
    {"title": "战争与和平", "original": "War and Peace", "id": 2600,
     "author": "列夫·托尔斯泰", "country": "俄",
     "blurb": "拿破仑战争中的贵族群像与历史沉思。"},
    {"title": "安娜·卡列尼娜", "original": "Anna Karenina", "id": 1399,
     "author": "列夫·托尔斯泰", "country": "俄",
     "blurb": "安娜的婚外情与列文的乡村生活双线交织。"},
    {"title": "罪与罚", "original": "Crime and Punishment", "id": 2554,
     "author": "费奥多尔·陀思妥耶夫斯基", "country": "俄",
     "blurb": "大学生拉斯柯尔尼科夫杀人后的良心审判。"},
    {"title": "堂吉诃德", "original": "Don Quixote", "id": 996,
     "author": "米格尔·德·塞万提斯", "country": "西",
     "blurb": "堂吉诃德与侍从桑丘的骑士冒险，笑中带泪。"},
]

NUMBER_WORDS = (
    "ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|"
    "THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY|"
    "THIRTY|FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY|"
    "FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH"
)
NUMBER = rf"(?:\d+|[IVXLCDM]+|{NUMBER_WORDS})"

HEADING_RE = re.compile(
    rf"^\s*(CHAPTER|BOOK|PART|LETTER|ADVENTURE|PROLOGUE|EPILOGUE|PHASE)\s+"
    rf"(?:THE\s+)?{NUMBER}\b[.:]?\s*(.*)$",
    re.I,
)
ROMAN_TITLE_RE = re.compile(r"^\s*([IVXLCDM]+)\.\s+(\S.*)$")
ROMAN_ALONE_RE = re.compile(r"^\s*[IVXLCDM]+\.?\s*$")
NUM_TITLE_RE = re.compile(r"^\s*(\d+)\.\s+(\S.*)$")
NUM_ALONE_RE = re.compile(r"^\s*(\d{1,3})\s*$")
START_RE = re.compile(
    r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.I
)
END_RE = re.compile(
    r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.I
)
JUNK_PARA_RE = re.compile(
    r"(?i)^(?:the\s+)?project gutenberg\b|^produced by\b|^transcribed from\b|"
    r"^release date\b|^character set\b|^encoding:\s|^contents\.?$|"
    r"^illustrations?\.?$|^\*\*\*|^the end\.?$|"
    r"^end of (?:the )?project gutenberg\b"
)
TOC_RE = re.compile(
    r"(?i)^(chapter|book|part|letter|adventure)\b.{0,90}\s\d{1,4}\s*$"
    r"|^.{1,70}(?:\.{3,}|…{2,})\s*\d{1,4}\s*$"
)
DECORATION_RE = re.compile(r"^[\s*\-—–_~·.]+$")
FRONT_TITLE_RE = re.compile(
    r"(?i)\b(preface|foreword|introduction|contents|illustrations?|dedication|"
    r"epilogue|appendix|notes|index)\b"
)
CHAPTER_WORD_RE = re.compile(r"(?i)\b(chapter|letter|part|book)\b")


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def download(book):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"pg{book['id']}.txt")
    if os.path.isfile(path) and os.path.getsize(path) > 20000:
        if END_RE.search(read_text(path)):
            return path

    urls = []
    slug = GITENBERG.get(book["id"])
    if slug:
        urls.append(
            f"https://cdn.jsdelivr.net/gh/GITenberg/{slug}@master/{book['id']}.txt"
        )
    urls.extend(pattern.format(id=book["id"]) for pattern in MIRRORS)

    last_error = None
    for url in urls:
        try:
            print(f"下载：{book['title']} <- {url}", flush=True)
            req = urllib.request.Request(
                url, headers={"User-Agent": "novel-search/1.0 (public-domain texts)"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp, open(path, "wb") as out:
                shutil.copyfileobj(resp, out)
            text = read_text(path)
            if not START_RE.search(text) or not END_RE.search(text):
                raise RuntimeError("文本不完整")
            return path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"  失败：{exc}", flush=True)
    raise RuntimeError(f"{book['title']} 下载失败：{last_error}")


def extract_body(raw):
    start = START_RE.search(raw)
    end = END_RE.search(raw)
    if not start:
        raise RuntimeError("缺少古腾堡开始标记")
    if end and end.start() > start.end():
        return raw[start.end():end.start()]
    return raw[start.end():]


def clean_lines(body):
    """去掉插图块、行内标记，保留章节标题行。"""
    lines = []
    in_illustration = False
    for raw_line in body.split("\n"):
        line = raw_line.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
        line = re.sub(r"[ \t]+", " ", line).strip()

        if in_illustration:
            if HEADING_RE.match(line):
                lines.append(line)
            if line.endswith("]"):
                in_illustration = False
            continue

        if line.startswith("[Illustration"):
            if "]" not in line:
                in_illustration = True
            continue

        line = re.sub(r"\[Illustration[^\]]*\]", "", line).strip()
        lines.append(line)
    return lines


def next_nonempty(lines, start):
    for index in range(start, len(lines)):
        if lines[index]:
            return index
    return None


def is_title_line(line):
    if not line or len(line) > 48 or len(line.split()) > 8:
        return False
    if re.fullmatch(
        r"(?i)(chapter|book|part|letter|epilogue|prologue|contents|preface|"
        r"introduction|appendix|notes|index)[.:]?",
        line,
    ):
        return False
    if HEADING_RE.match(line) or ROMAN_TITLE_RE.match(line) or ROMAN_ALONE_RE.match(line):
        return False
    if line[0] in "\"'“‘—–-":
        return False
    if re.search(r"[.!?;:,]$", line):
        return False
    return line[0].isupper()


def strip_front_toc(lines, headings):
    """丢掉目录页生成的标题；多卷本可能有多处目录。"""
    markers = [
        index for index, line in enumerate(lines)
        if re.fullmatch(r"(?i)(table of )?contents\.?", line.strip())
    ]
    for marker in markers:
        prose = None
        for index in range(marker + 1, len(lines)):
            line = lines[index]
            if (len(line) >= 60
                    and not line.isupper()
                    and not TOC_RE.search(line)
                    and not HEADING_RE.match(line)):
                prose = index
                break
        if prose is None:
            continue

        before = [
            heading for heading in headings
            if marker < heading["index"] < prose
        ]
        if not before:
            continue
        cut = before[-1]["index"]
        if len(before) >= 2:
            previous = before[-2]
            between = lines[previous["index"] + 1:cut]
            if previous.get("section_only") and all(not text for text in between):
                cut = previous["index"]
        headings = [
            heading for heading in headings
            if not (marker < heading["index"] < cut)
        ]
    return headings


def collect_headings(lines):
    headings = []
    for index, line in enumerate(lines):
        if not line:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        title = line
        consumed = set()
        rest = match.group(2).strip(" .:;,]")
        if not rest:
            follow = next_nonempty(lines, index + 1)
            if follow is not None and is_title_line(lines[follow]):
                title = f"{line} {lines[follow]}".strip()
                consumed.add(follow)
        headings.append({
            "index": index,
            "title": title,
            "kind": match.group(1).upper(),
            "consumed": consumed,
        })

    roman_alone = [
        index for index, line in enumerate(lines) if ROMAN_ALONE_RE.match(line)
    ]
    number_alone = [
        index for index, line in enumerate(lines) if NUM_ALONE_RE.match(line)
    ]
    chapter_kinds = {"CHAPTER", "LETTER", "ADVENTURE", "PROLOGUE", "EPILOGUE", "PHASE"}
    only_sections = headings and not any(
        heading["kind"] in chapter_kinds for heading in headings
    )

    if len(number_alone) >= 8 and only_sections:
        # 《金银岛》一类：PART 作卷，正文用单独的数字行加标题。
        for heading in headings:
            heading["section_only"] = True
        for index in number_alone:
            follow = next_nonempty(lines, index + 1)
            if follow is None:
                continue
            follow_line = lines[follow]
            if (HEADING_RE.match(follow_line)
                    or NUM_ALONE_RE.match(follow_line)
                    or len(follow_line) > 100):
                continue
            headings.append({
                "index": index,
                "title": f"{lines[index]}. {lines[follow]}",
                "kind": "NUMBER",
                "consumed": {follow},
                "section_only": False,
            })
        headings.sort(key=lambda heading: heading["index"])
        return strip_front_toc(lines, headings), "standard"

    if len(roman_alone) >= 8 and any(
        heading["kind"] == "PHASE" for heading in headings
    ):
        for heading in headings:
            heading["section_only"] = True
        for index in roman_alone:
            headings.append({
                "index": index,
                "title": lines[index],
                "kind": "ROMAN",
                "consumed": set(),
                "section_only": False,
            })
        headings.sort(key=lambda heading: heading["index"])
        return strip_front_toc(lines, headings), "standard"

    if len(headings) >= 2:
        has_chapters = bool({heading["kind"] for heading in headings} & chapter_kinds)
        for heading in headings:
            heading["section_only"] = has_chapters and heading["kind"] in ("BOOK", "PART")

        # 有些版本后半部改用“VII. THE ADVENTURE…”这类不带 ADVENTURE 前缀的标题。
        seen = {heading["index"] for heading in headings}
        extra_roman = []
        for index, line in enumerate(lines):
            match = ROMAN_TITLE_RE.match(line)
            if not match or index in seen:
                continue
            title = match.group(2)
            if any(ch.isalpha() for ch in title) and title.isupper():
                extra_roman.append({
                    "index": index,
                    "title": line,
                    "kind": "ROMAN",
                    "consumed": set(),
                    "section_only": False,
                })
        for index, line in enumerate(lines):
            if index not in seen and re.fullmatch(r"(?i)(prologue|epilogue)\.?", line):
                extra_roman.append({
                    "index": index,
                    "title": line,
                    "kind": "EPILOGUE",
                    "consumed": set(),
                    "section_only": False,
                })
                seen.add(index)

        if len(roman_alone) >= 8:
            for index in roman_alone:
                if index in seen:
                    continue
                title = lines[index]
                consumed = set()
                follow = next_nonempty(lines, index + 1)
                if follow is not None and is_title_line(lines[follow]):
                    title = f"{lines[index]} {lines[follow]}".strip()
                    consumed.add(follow)
                extra_roman.append({
                    "index": index,
                    "title": title,
                    "kind": "ROMAN",
                    "consumed": consumed,
                    "section_only": False,
                })
        if extra_roman:
            headings.extend(extra_roman)
            headings.sort(key=lambda heading: heading["index"])
        return strip_front_toc(lines, headings), "standard"

    number_titles = [
        (index, line) for index, line in enumerate(lines)
        if NUM_TITLE_RE.match(line)
    ]
    if len(number_titles) >= 6:
        headings = [
            {"index": index, "title": line, "kind": "NUMBER",
             "consumed": set(), "section_only": False}
            for index, line in number_titles
        ]
        return strip_front_toc(lines, headings), "number"

    roman = [
        index for index, line in enumerate(lines) if ROMAN_TITLE_RE.match(line)
    ]
    if len(roman) >= 3:
        headings = [
            {"index": index, "title": lines[index], "kind": "ROMAN",
             "consumed": set(), "section_only": False}
            for index in roman
        ]
        return strip_front_toc(lines, headings), "roman"

    if not headings:
        # 《化身博士》一类：章节标题本身就是全大写短语，且目录与正文各出现一次。
        caps = []
        counts = {}
        for index, line in enumerate(lines):
            if (line.isupper() and len(line) <= 80
                    and any(ch.isalpha() for ch in line)
                    and not re.match(r"(?i)^(contents|preface|introduction|index|notes)\b", line)):
                key = re.sub(r"\s+", " ", line.strip().lower())
                counts[key] = counts.get(key, 0) + 1
                caps.append((index, key))
        caps = [index for index, key in caps if counts[key] >= 2]
        if len(caps) >= 12:
            headings = [
                {"index": index, "title": lines[index], "kind": "TITLE",
                 "consumed": set(), "section_only": False}
                for index in caps
            ]
            return strip_front_toc(lines, headings), "title"

    if headings:
        for heading in headings:
            heading["section_only"] = False
        return strip_front_toc(lines, headings), "standard"
    raise RuntimeError("无法识别章节")


def clean_title(title):
    title = re.sub(r"\s+", " ", title).strip()
    title = title.rstrip("]").strip()
    return title or "无题"


def clean_paragraph(text):
    text = re.sub(r"_([^_]{1,300})_", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_junk(text):
    return bool(
        not text
        or JUNK_PARA_RE.search(text)
        or TOC_RE.search(text)
        or DECORATION_RE.fullmatch(text)
        or re.fullmatch(r"\d{1,4}", text)
    )


ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
WORD_NUMBERS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
}


def roman_to_int(text):
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        value = ROMAN_VALUES.get(char)
        if value is None:
            return None
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total


def chapter_number(title):
    match = re.search(
        r"(?i)\b(?:chapter|letter)\s+([IVXLCDM]+|\d+|[A-Za-z]+)\b", title
    )
    if match:
        token = match.group(1)
        if token.isdigit():
            return int(token)
        return roman_to_int(token) or WORD_NUMBERS.get(token.upper())
    match = re.match(r"^\s*([IVXLCDM]+)\.\s+\S", title)
    if match:
        return roman_to_int(match.group(1))
    match = re.match(r"^\s*(\d+)\.\s+\S", title)
    if match:
        return int(match.group(1))
    match = re.match(r"^\s*([IVXLCDM]+)\.?\s*$", title)
    if match:
        return roman_to_int(match.group(1))
    match = re.search(r"·\s*([IVXLCDM]+)\s*$", title)
    if match:
        return roman_to_int(match.group(1))
    return None


def trim_leading_chapters(chapters):
    """目录残页可能排在最前，丢到正文第一章为止。"""
    if len(chapters) < 3:
        return chapters
    first = chapter_number(chapters[0][0])
    if first is None or first <= 1:
        return chapters
    for index in range(1, len(chapters)):
        if chapter_number(chapters[index][0]) == 1:
            return chapters[index:]
    return chapters


def split_chapters(lines):
    headings, _ = collect_headings(lines)
    chapters = []
    part_title = ""

    for position, heading in enumerate(headings):
        if heading.get("section_only"):
            part_title = clean_title(heading["title"])
            continue
        start = heading["index"] + 1
        end = headings[position + 1]["index"] if position + 1 < len(headings) else len(lines)
        paragraphs = []
        block = []

        for index in range(start, end):
            if index in heading["consumed"]:
                continue
            line = lines[index]
            if not line:
                if block:
                    paragraphs.append(" ".join(block))
                    block = []
                continue
            if ROMAN_ALONE_RE.match(line):
                continue
            if HEADING_RE.match(line):
                continue
            block.append(line)
        if block:
            paragraphs.append(" ".join(block))

        paragraphs = [clean_paragraph(paragraph) for paragraph in paragraphs]
        paragraphs = [paragraph for paragraph in paragraphs if not is_junk(paragraph)]
        if not paragraphs:
            continue
        title = clean_title(heading["title"])
        if part_title:
            title = f"{part_title} · {title}"
        chapters.append((title, paragraphs))

    chapters = trim_leading_chapters(chapters)
    while chapters:
        title, paragraphs = chapters[0]
        first = paragraphs[0] if paragraphs else ""
        front_title = (
            FRONT_TITLE_RE.search(title)
            and not CHAPTER_WORD_RE.search(title)
        )
        front_text = re.match(
            r"(?i)^(?:(?:translator|author|editor)[’']?s?\s+)?"
            r"(?:preface|foreword|introduction|contents|dedication|note|"
            r"epilogue|prologue|appendix)\b",
            first,
        )
        if not front_title and not front_text:
            break
        chapters.pop(0)

    if not chapters:
        raise RuntimeError("没有解析出任何章节")
    return chapters


def save_book(book, chapters):
    folder = os.path.join(DATA, book["title"])
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith(".txt"):
            os.remove(os.path.join(folder, name))

    for number, (title, paragraphs) in enumerate(chapters, 1):
        path = os.path.join(folder, f"{number:03d}.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(title + "\n\n" + "\n\n".join(paragraphs) + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    os.makedirs(DATA, exist_ok=True)
    results = {}
    failures = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download, book): book for book in SELECTION}
        for future in as_completed(futures):
            book = futures[future]
            try:
                path = future.result()
                raw = extract_body(read_text(path))
                chapters = split_chapters(clean_lines(raw))
                save_book(book, chapters)
                results[book["title"]] = {
                    "title": book["title"],
                    "category": CATEGORY,
                    "author": book["author"],
                    "dynasty": book["country"],
                    "blurb": book["blurb"],
                    "chapters": len(chapters),
                    "original": book["original"],
                    "gutenberg_id": book["id"],
                }
                chars = sum(len(paragraph) for _, paragraphs in chapters for paragraph in paragraphs)
                print(f"{book['title']}: {len(chapters)} 章 / {chars:,} 字", flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append((book["title"], str(exc)))
                print(f"{book['title']} 失败：{exc}", flush=True)

    books = [results[book["title"]] for book in SELECTION if book["title"] in results]
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "source": {
                "name": "Project Gutenberg",
                "url": "https://www.gutenberg.org/",
                "mirror": "https://gutenberg.pglaf.org/",
                "license": "Public domain",
            },
            "books": books,
        }, f, ensure_ascii=False, indent=2)

    print(f"完成：{len(books)} / {len(SELECTION)} 本，元数据 {META_PATH}", flush=True)
    if failures:
        print("失败书目：", flush=True)
        for title, error in failures:
            print(f"  {title}: {error}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
