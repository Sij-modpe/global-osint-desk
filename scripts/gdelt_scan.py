#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GDELT DOC 2.0 多语种事件扫描器。

用途：在阶段 2 快速建立"当日全景"与线索池。
注意：GDELT 编码的是**报道强度**，不是事态强度。输出仅可用于发现线索，
      任何一条都必须在阶段 3 回溯原始出处并做双轴评级，不得直接引用。

用法示例：
  python gdelt_scan.py "semiconductor export controls" --timespan 3d --max 40
  python gdelt_scan.py "港口 OR 罢工" --lang chinese --timespan 24h
  python gdelt_scan.py "Red Sea shipping" --mode timeline --timespan 14d
  python gdelt_scan.py "Taiwan strait" --format json --out scan.json

GDELT 查询语法（原样透传给 API，可自由组合）：
  "phrase"              精确短语
  a OR b                或
  domain:reuters.com    限定域名
  sourcelang:spanish    限定语种（--lang 会自动追加）
  theme:TAX_ETHNICITY   主题编码
  -term                 排除
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = "Mozilla/5.0 (compatible; OSINT-Desk/1.0)"
CST = timezone(timedelta(hours=8))


def build_url(args):
    params = {
        "query": args.query,
        "mode": "TimelineVol" if args.mode == "timeline" else "ArtList",
        "format": "json",
        "timespan": args.timespan,
        "sort": "DateDesc",
    }
    if args.mode != "timeline":
        params["maxrecords"] = str(max(1, min(args.max, 250)))
    if args.lang:
        params["query"] = f"({args.query}) sourcelang:{args.lang}"
    return API + "?" + urllib.parse.urlencode(params)


def fetch(url, timeout, retries=3, backoff=6):
    """GDELT 对高频请求会返回 429，退避重试；仍失败则交回上层报错。"""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore"), resp.status
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
    raise last


def parse_seendate(s):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def render_articles(payload, top_n):
    arts = payload.get("articles") or []
    if not arts:
        return "_无结果。可能原因：查询过于狭窄、时间窗过短、或 GDELT 未索引该语种内容。_"
    rows = ["| 时间(UTC+8) | 语种 | 来源国 | 域名 | 标题 | 链接 |", "|---|---|---|---|---|---|"]
    for a in arts[:top_n]:
        dt = parse_seendate(a.get("seendate", ""))
        ts = dt.astimezone(CST).strftime("%m-%d %H:%M") if dt else "?"
        title = (a.get("title") or "").replace("|", "／").strip()
        if len(title) > 90:
            title = title[:90] + "…"
        rows.append(
            "| {} | {} | {} | {} | {} | [原文]({}) |".format(
                ts,
                a.get("language", "?"),
                a.get("sourcecountry", "?"),
                a.get("domain", "?"),
                title,
                a.get("url", ""),
            )
        )
    return "\n".join(rows)


def render_timeline(payload):
    tl = payload.get("timeline") or []
    if not tl:
        return "_无时间线数据。_"
    series = tl[0]
    data = series.get("data") or []
    if not data:
        return "_时间线为空。_"
    rows = ["| 日期 | 相对报道强度（0–1，已归一化） |", "|---|---|"]
    for p in data:
        rows.append("| {} | {} |".format(p.get("date", "")[:8], p.get("value", 0)))
    head = f"**时间线**：{series.get('series', '')}\n\n"
    return head + "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(
        description="GDELT DOC 2.0 扫描器（线索层，非证据层）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("query", help="GDELT 查询串，支持其原生语法")
    ap.add_argument("--timespan", default="24h", help="时间窗，如 24h / 3d / 2w / 1m（默认 24h）")
    ap.add_argument("--lang", default="", help="限定语种，如 english/chinese/spanish/russian/arabic")
    ap.add_argument("--max", type=int, default=40, help="最多返回条数（≤250，默认 40）")
    ap.add_argument("--mode", choices=["artlist", "timeline"], default="artlist", help="文章列表或报道量时间线")
    ap.add_argument("--format", choices=["md", "json"], default="md", help="输出格式")
    ap.add_argument("--out", default="", help="输出文件路径；缺省打印到标准输出")
    ap.add_argument("--timeout", type=int, default=30, help="请求超时秒数")
    args = ap.parse_args()

    url = build_url(args)
    try:
        raw, status = fetch(url, args.timeout)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[错误] GDELT 限流（HTTP 429）。已退避重试 3 次仍失败。", file=sys.stderr)
            print("[建议] 降低调用频率、加长 --timespan、放宽 --max，或改走 WebSearch。", file=sys.stderr)
        else:
            print(f"[错误] GDELT 返回 HTTP {e.code}：{e.reason}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[错误] 请求 GDELT 失败：{type(e).__name__}: {e}", file=sys.stderr)
        print("[提示] 网络不可用或接口不可达。退回 WebSearch 手工采集，评级标准不变。", file=sys.stderr)
        return 2

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        snippet = raw.strip()[:300]
        print(f"[错误] 返回非 JSON（HTTP {status}）。原始响应片段：\n{snippet}", file=sys.stderr)
        print("[提示] 常见原因：查询语法不合法、关键词过窄、或含未编码的特殊字符。", file=sys.stderr)
        return 3

    if args.format == "json":
        out = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
        header = (
            f"### GDELT 扫描 · `{args.query}`\n\n"
            f"- 扫描时间：{now} (UTC+8) ｜ 窗口：{args.timespan} ｜ 语种：{args.lang or '全部'}\n"
            f"- **性质：线索层。条数反映报道强度，不代表事态强度。每一条须回溯原始出处并评级后方可引用。**\n"
            f"- **判读提示：同一标题在多个域名重复出现（如地方电台转播网、多语种同稿）属转载体，不构成多源印证。**\n"
        )
        body = render_timeline(payload) if args.mode == "timeline" else render_articles(payload, args.max)
        out = header + "\n" + body + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[完成] 已写入 {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
