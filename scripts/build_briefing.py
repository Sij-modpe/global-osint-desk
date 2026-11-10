#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Markdown 简报转成邮件可用的 HTML（仅标准库，不依赖第三方 markdown 包）。

支持：标题、粗体/斜体/行内代码/链接/删除线、无序与有序列表、引用块、
      表格、水平线、围栏代码块、段落。样式全部内联，兼容主流邮箱客户端。

用法：
  python build_briefing.py brief.md                      # -> brief.html
  python build_briefing.py brief.md -o out.html --title "情报简报 · 主题"
  python build_briefing.py brief.md --fragment           # 只出正文片段，不套完整文档
"""

import argparse
import html
import re
import sys

BODY_STYLE = (
    "margin:0;padding:24px;background:#f6f7f9;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif;"
    "font-size:15px;line-height:1.75;color:#1f2328;"
)
WRAP_STYLE = "max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #e3e6ea;border-radius:10px;padding:28px 30px;"


def inline(text):
    """行内格式化。先抽出 code span 避免其内部被再次解析。"""
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00CODE{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2" style="color:#0b62d6;text-decoration:none;border-bottom:1px solid #cfe0f7;">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r'<strong style="font-weight:600;">\1</strong>', text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", text)

    for i, c in enumerate(codes):
        text = text.replace(f"\x00CODE{i}\x00", f'<code style="background:#f1f3f5;padding:1px 5px;border-radius:4px;font-size:13px;font-family:ui-monospace,Consolas,monospace;">{html.escape(c)}</code>')
    return text


def is_table_sep(line):
    s = line.strip()
    return bool(re.fullmatch(r"\|?[\s:\-|]+\|?", s)) and "-" in s and re.search(r"\|", s)


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def convert(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)

    while i < n:
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        # 围栏代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(
                '<pre style="background:#f6f8fa;border:1px solid #e3e6ea;border-radius:8px;'
                'padding:12px 14px;overflow-x:auto;font-size:12.5px;line-height:1.6;'
                'font-family:ui-monospace,Consolas,monospace;"><code>'
                + html.escape("\n".join(buf))
                + "</code></pre>"
            )
            continue

        # 水平线
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append('<hr style="border:none;border-top:1px solid #e3e6ea;margin:24px 0;">')
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            sizes = {1: ("22px", "600", "0 0 14px"), 2: ("18px", "600", "26px 0 10px"),
                     3: ("16px", "600", "20px 0 8px"), 4: ("15px", "600", "16px 0 6px")}
            fs, fw, mg = sizes.get(lvl, ("14px", "600", "12px 0 6px"))
            border = "border-left:3px solid #0b62d6;padding-left:10px;" if lvl == 2 else ""
            out.append(
                f'<h{lvl} style="font-size:{fs};font-weight:{fw};margin:{mg};color:#11161c;'
                f'line-height:1.4;{border}">{inline(m.group(2))}</h{lvl}>'
            )
            i += 1
            continue

        # 表格
        if "|" in s and i + 1 < n and is_table_sep(lines[i + 1]):
            header = split_row(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            th = "".join(
                f'<th style="background:#f2f5f8;border:1px solid #dde2e8;padding:8px 10px;'
                f'text-align:left;font-size:13px;font-weight:600;color:#2b3138;">{inline(c)}</th>'
                for c in header
            )
            trs = []
            for r in rows:
                tds = "".join(
                    f'<td style="border:1px solid #dde2e8;padding:8px 10px;font-size:13px;'
                    f'vertical-align:top;">{inline(c)}</td>'
                    for c in r
                )
                trs.append(f"<tr>{tds}</tr>")
            out.append(
                '<div style="overflow-x:auto;margin:12px 0;"><table style="border-collapse:collapse;'
                'width:100%;font-size:13px;">'
                f"<thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
            )
            continue

        # 引用块
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(
                '<blockquote style="margin:12px 0;padding:10px 14px;background:#f7f9fb;'
                'border-left:3px solid #b9c6d4;color:#3a424b;font-size:14px;">'
                + inline(" ".join(x.strip() for x in buf if x.strip()))
                + "</blockquote>"
            )
            continue

        # 列表
        if re.match(r"^([-*+]|\d+\.)\s+", s):
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < n:
                cur = lines[i]
                cs = cur.strip()
                if re.match(r"^([-*+]|\d+\.)\s+", cs):
                    items.append(re.sub(r"^([-*+]|\d+\.)\s+", "", cs))
                    i += 1
                elif not cs:
                    # 允许列表项之间夹空行而不打断列表（Markdown 常规写法）
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    nxt = lines[j].strip() if j < n else ""
                    if nxt and re.match(r"^([-*+]|\d+\.)\s+", nxt) and bool(re.match(r"^\d+\.", nxt)) == ordered:
                        i = j
                        continue
                    break
                elif cs and cur.startswith(("  ", "\t")) and items:
                    items[-1] += "\x01BR\x01" + cs  # 缩进续行归属上一条
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            pad = "padding-left:22px;margin:10px 0;"
            lis_parts = []
            for x in items:
                box = ""
                m2 = re.match(r"^\[([ xX])\]\s*", x)
                if m2:
                    box = "☑ " if m2.group(1).lower() == "x" else "☐ "
                    x = x[m2.end():]
                lis_parts.append(f'<li style="margin:5px 0;">{box}{inline(x).replace(chr(1) + "BR" + chr(1), "<br>")}</li>')
            out.append(f'<{tag} style="{pad}">{"".join(lis_parts)}</{tag}>')
            continue

        # 段落：合并连续非空行
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|>|```|[-*+]\s|\d+\.\s)", lines[i].strip()) \
                and not re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", lines[i].strip()) \
                and "|" not in lines[i].strip():
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append(f'<p style="margin:10px 0;">{inline(" ".join(buf))}</p>')
        else:
            i += 1
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Markdown 简报 → 邮件 HTML")
    ap.add_argument("source", help="Markdown 文件路径")
    ap.add_argument("-o", "--out", default="", help="输出 HTML 路径（默认同名 .html）")
    ap.add_argument("--title", default="", help="HTML <title>")
    ap.add_argument("--footer", default="", help="页脚文字（如保密声明）")
    ap.add_argument("--fragment", action="store_true", help="只输出正文片段，不套完整 HTML 文档")
    args = ap.parse_args()

    try:
        with open(args.source, encoding="utf-8") as f:
            md = f.read()
    except OSError as e:
        print(f"[错误] 无法读取 {args.source}：{e}", file=sys.stderr)
        return 2

    body = convert(md)
    if args.fragment:
        result = body
    else:
        title = html.escape(args.title or args.source)
        footer = (
            f'<div style="margin-top:26px;padding-top:14px;border-top:1px solid #e3e6ea;'
            f'font-size:12px;color:#7b848f;line-height:1.6;">{inline(args.footer)}</div>'
            if args.footer else ""
        )
        result = (
            '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title></head>"
            f'<body style="{BODY_STYLE}"><div style="{WRAP_STYLE}">{body}{footer}</div></body></html>'
        )

    out_path = args.out or re.sub(r"\.(md|markdown)$", "", args.source) + ".html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"[完成] 已写入 {out_path}（{len(result)} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
