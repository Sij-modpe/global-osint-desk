#!/usr/bin/env python3
"""Build a qq-mail inline attachment payload from local files.

qq-mail's SendMessage `attachments` field requires base64 content plus
filename / content_type / size / sha1 for every item. Doing this by hand is
error-prone, so this script prints ready-to-use JSON.

Usage:
    python attach_payload.py report.md [brief.html ...]

Output (stdout): a JSON array, paste it into the `attachments` argument.
Limits enforced here before you hit the server:
    single file <= 1 MiB, total <= 3 MiB, at most 3 files.
"""
import base64
import hashlib
import json
import mimetypes
import os
import sys

SINGLE_MAX = 1024 * 1024          # 1 MiB per file
TOTAL_MAX = 3 * 1024 * 1024       # 3 MiB total
COUNT_MAX = 3


def payload(path):
    with open(path, "rb") as f:
        raw = f.read()
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if name.lower().endswith((".md", ".markdown")):
        ctype = "text/markdown; charset=utf-8"
    elif name.lower().endswith(".html"):
        ctype = "text/html; charset=utf-8"
    return {
        "filename": name,
        "content_type": ctype,
        "content": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
        "sha1": hashlib.sha1(raw).hexdigest(),
    }


def main(argv):
    if not argv:
        print("用法: python attach_payload.py <file1> [file2] [file3]", file=sys.stderr)
        return 2
    if len(argv) > COUNT_MAX:
        print(f"[错误] 最多 {COUNT_MAX} 个附件，收到 {len(argv)} 个。", file=sys.stderr)
        return 3

    items, total = [], 0
    for p in argv:
        if not os.path.isfile(p):
            print(f"[错误] 文件不存在: {p}", file=sys.stderr)
            return 4
        it = payload(p)
        if it["size"] > SINGLE_MAX:
            print(
                f"[错误] {it['filename']} 为 {it['size']} 字节，超过单件 1 MiB 上限。"
                "\n[建议] 精简报告，或只发简报正文、报告改为本地交付。",
                file=sys.stderr,
            )
            return 5
        total += it["size"]
        items.append(it)

    if total > TOTAL_MAX:
        print(f"[错误] 附件总量 {total} 字节，超过 3 MiB 上限。", file=sys.stderr)
        return 6

    print(json.dumps(items, ensure_ascii=False))
    print(
        f"[ok] {len(items)} 件，合计 {total} 字节",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
