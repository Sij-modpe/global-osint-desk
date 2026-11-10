#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量 RSS/Atom 扫描器（仅标准库）。

用途：在阶段 2 用一组订阅源快速铺开采集面，按关键词过滤、去重、按时间排序。
注意：RSS 仅给标题与摘要，**不是原文**。命中项必须打开原文再评级。

用法：
  python rss_scan.py --keywords 半导体,出口管制,chip
  python rss_scan.py --feeds https://example.com/rss.xml --keywords 港口
  python rss_scan.py --feeds-file feeds.txt --hours 48 --out scan.md

默认源可用 --no-default 关闭。单个源失败不影响其余源，失败清单会在末尾汇总。
"""

import argparse
import difflib
import gzip
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; OSINT-Desk/1.0)"
CST = timezone(timedelta(hours=8))

DEFAULT_FEEDS = [
    ("France 24", "https://www.france24.com/en/rss"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    ("Yonhap", "https://en.yna.co.kr/RSS/news.xml"),
    ("Moscow Times", "https://www.themoscowtimes.com/rss/news"),
    ("ReliefWeb", "https://reliefweb.int/updates/rss.xml"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("The Guardian World", "https://www.theguardian.com/world/rss"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
]

NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}


def txt(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            continue
    return None


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def norm_title(t):
    """归一化标题：去通讯社前缀括号、去标点、小写。"""
    t = (t or "").strip()
    t = re.sub(r"^(\([^)]{1,20}\)\s*)+", "", t)  # (LEAD) (2ND LD) (URGENT) 等
    return re.sub(r"[^\w\u4e00-\u9fff]", "", t.lower())[:60]


def kw_hit(blob, kws):
    """ASCII 关键词按词边界匹配（避免 port 命中 supports），CJK 按子串匹配。"""
    for k in kws:
        if re.search(r"[\u4e00-\u9fff]", k):
            if k in blob:
                return True
        elif re.search(r"\b" + re.escape(k) + r"\b", blob):
            return True
    return False


def fetch_feed(url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def parse_feed(data):
    items = []
    root = ET.fromstring(data)
    # RSS 2.0 / RDF
    for it in root.iter("item"):
        items.append(
            {
                "title": txt(it.find("title")),
                "link": txt(it.find("link")),
                "summary": strip_tags(txt(it.find("description"))),
                "date": parse_date(txt(it.find("pubDate")) or txt(it.find("date"))),
            }
        )
    # Atom
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link_el = it.find("atom:link", NS)
        href = link_el.get("href") if link_el is not None else ""
        items.append(
            {
                "title": txt(it.find("atom:title", NS)),
                "link": href,
                "summary": strip_tags(txt(it.find("atom:summary", NS)) or txt(it.find("atom:content", NS))),
                "date": parse_date(txt(it.find("atom:updated", NS)) or txt(it.find("atom:published", NS))),
            }
        )
    return items


def main():
    ap = argparse.ArgumentParser(description="批量 RSS/Atom 扫描器")
    ap.add_argument("--feeds", default="", help="逗号分隔的 feed URL 列表")
    ap.add_argument("--feeds-file", default="", help="每行一个 feed URL 的文件")
    ap.add_argument("--no-default", action="store_true", help="不使用内置默认源")
    ap.add_argument("--keywords", default="", help="逗号分隔的关键词，任一命中即保留；留空则全部保留")
    ap.add_argument("--hours", type=int, default=72, help="仅保留最近 N 小时内的条目（默认 72；0 表示不过滤）")
    ap.add_argument("--limit", type=int, default=0, help="每个源最多取几条（0 不限）")
    ap.add_argument("--out", default="", help="输出 Markdown 文件路径")
    ap.add_argument("--timeout", type=int, default=20, help="单源超时秒数")
    args = ap.parse_args()

    feeds = []
    if not args.no_default:
        feeds.extend(DEFAULT_FEEDS)
    if args.feeds:
        feeds.extend([(u.split("//")[-1].split("/")[0], u.strip()) for u in args.feeds.split(",") if u.strip()])
    if args.feeds_file:
        try:
            with open(args.feeds_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        feeds.append((line.split("//")[-1].split("/")[0], line))
        except OSError as e:
            print(f"[错误] 无法读取 feed 文件：{e}", file=sys.stderr)
            return 2

    if not feeds:
        print("[错误] 没有可用的 feed。用 --feeds 或 --feeds-file 指定。", file=sys.stderr)
        return 2

    kws = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours) if args.hours else None

    collected, failed, seen, by_source = [], [], set(), {}

    for name, url in feeds:
        try:
            data = fetch_feed(url, args.timeout)
            items = parse_feed(data)
        except Exception as e:
            failed.append(f"{name} ({url}) -> {type(e).__name__}")
            continue
        kept = 0
        for it in items:
            if args.limit and kept >= args.limit:
                break
            if cutoff and it["date"] and it["date"] < cutoff:
                continue
            if kws:
                blob = (it["title"] + " " + it["summary"]).lower()
                if not kw_hit(blob, kws):
                    continue
            key = norm_title(it["title"])
            if not key or key in seen:
                continue
            # 同源近似标题去重（通讯社改稿常导致同题重复）
            if any(difflib.SequenceMatcher(None, key, prev).ratio() >= 0.88 for prev in by_source.get(name, [])):
                continue
            seen.add(key)
            by_source.setdefault(name, []).append(key)
            it["source"] = name
            collected.append(it)
            kept += 1

    collected.sort(key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    lines = [
        "### RSS 扫描结果",
        "",
        f"- 扫描时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')} (UTC+8) ｜ 窗口：{args.hours}h ｜ 关键词：{args.keywords or '（无，全量）'}",
        f"- 源数 {len(feeds)}，成功 {len(feeds) - len(failed)}，失败 {len(failed)}；去重后条目 {len(collected)}",
        "- **性质：线索层。RSS 只给标题与摘要，须打开原文后评级。**",
        "",
    ]
    if not collected:
        lines.append("_无命中条目。可放宽关键词或时间窗，或改用 GDELT 扫描。_")
    else:
        lines.append("| 时间(UTC+8) | 来源 | 标题 | 链接 |")
        lines.append("|---|---|---|---|")
        for it in collected:
            ts = it["date"].astimezone(CST).strftime("%m-%d %H:%M") if it["date"] else "?"
            title = (it["title"] or "").replace("|", "／").strip()
            lines.append(f"| {ts} | {it['source']} | {title} | [原文]({it['link']}) |")

    if failed:
        lines.extend(["", "**抓取失败的源**（不影响其余结果；如需补齐请手工访问）：", ""])
        for f in failed:
            lines.append(f"- {f}")

    out = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[完成] 已写入 {args.out}（{len(collected)} 条）")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
