#!/usr/bin/env python3
"""users.db 在线备份脚本。

默认从 USERS_DB_PATH（或 data/users.db）读取，写入同目录下的 backups/，
保留最近若干份。使用 SQLite 在线备份接口，服务运行中也可执行。

用法：
    python backup_users_db.py
    python backup_users_db.py --source data/users.db --dest data/backups --keep 14
    python backup_users_db.py --source /app/userdata/users.db --dest /app/userdata/backups
"""

import argparse
import glob
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.environ.get("USERS_DB_PATH") or os.path.join(ROOT, "data", "users.db")


def backup_database(source, dest):
    uri = Path(source).as_uri() + "?mode=ro"
    src = sqlite3.connect(uri, uri=True, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def verify_database(path):
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
        integrity = result[0] if result else "unknown"
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()
    if integrity != "ok":
        raise RuntimeError(f"备份校验失败：{integrity}")
    return users


def prune_backups(dest_dir, keep):
    files = sorted(glob.glob(os.path.join(dest_dir, "users-*.db")))
    if keep <= 0:
        return []
    removed = []
    for path in files[:-keep]:
        os.remove(path)
        removed.append(path)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description="备份 users.db")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="源数据库路径")
    parser.add_argument("--dest", default=None, help="备份目录，默认为源目录下的 backups/")
    parser.add_argument("--keep", type=int, default=14, help="保留最近多少份备份，默认 14")
    args = parser.parse_args(argv)

    source = os.path.abspath(args.source)
    dest_dir = os.path.abspath(args.dest or os.path.join(os.path.dirname(source), "backups"))

    if not os.path.isfile(source):
        print(f"源数据库不存在：{source}", file=sys.stderr)
        return 1

    os.makedirs(dest_dir, exist_ok=True)
    name = f"users-{time.strftime('%Y%m%d-%H%M%S')}.db"
    dest = os.path.join(dest_dir, name)

    try:
        backup_database(source, dest)
        users = verify_database(dest)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        if os.path.exists(dest):
            os.remove(dest)
        print(f"备份失败：{exc}", file=sys.stderr)
        return 1

    removed = prune_backups(dest_dir, args.keep)
    size = os.path.getsize(dest)
    print(f"已备份 {source} -> {dest}（{users} 个用户，{size} 字节）")
    for path in removed:
        print(f"已清理旧备份：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
