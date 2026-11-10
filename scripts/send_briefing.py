#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经 SMTP 发送情报简报（Agent Mail 不可用时的降级通道）。

凭据**只从环境变量读取**，不落盘、不写入命令行历史、不出现在任何输出里。

必需环境变量：
  OSINT_SMTP_HOST     SMTP 服务器，如 smtp.qq.com / smtp.gmail.com / smtp.163.com
  OSINT_SMTP_USER     登录账号（通常是完整邮箱地址）
  OSINT_SMTP_PASS     授权码或应用专用密码（**不是**网页登录密码）

可选：
  OSINT_SMTP_PORT     端口。ssl 默认 465，starttls 默认 587
  OSINT_SMTP_FROM     发件地址，默认取 OSINT_SMTP_USER
  OSINT_SMTP_NAME     发件人显示名，默认 "OSINT Desk"
  OSINT_SMTP_SECURITY ssl | starttls | none，默认按端口自动判断

用法：
  export OSINT_SMTP_HOST=smtp.qq.com
  export OSINT_SMTP_USER=me@qq.com
  export OSINT_SMTP_PASS=xxxxxxxxxxxx
  python send_briefing.py --to a@b.com --subject "[情报简报] ..." --html brief.html --attach report.md

先干跑确认内容与收件人（不实际发送）：
  python send_briefing.py --to a@b.com --subject "..." --html brief.html --dry-run
"""

import argparse
import mimetypes
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path


def env(name, default=""):
    return os.environ.get(name, default).strip()


def build_message(args, allow_placeholder=False):
    sender = env("OSINT_SMTP_FROM") or env("OSINT_SMTP_USER")
    if not sender:
        if not allow_placeholder:
            raise SystemExit("[错误] 未设置 OSINT_SMTP_FROM / OSINT_SMTP_USER。")
        sender = "preview@localhost"
    name = env("OSINT_SMTP_NAME", "OSINT Desk")

    msg = EmailMessage()
    msg["From"] = formataddr((name, sender))
    msg["To"] = ", ".join(args.to)
    msg["Subject"] = args.subject
    msg["Date"] = formatdate(localtime=True)

    text = ""
    if args.text:
        text = Path(args.text).read_text(encoding="utf-8")
    elif args.html:
        text = "本邮件为 HTML 格式。若显示异常，请查看附件中的 Markdown 报告。"
    msg.set_content(text or "（空正文）")

    if args.html:
        html_path = Path(args.html)
        if not html_path.exists():
            raise SystemExit(f"[错误] HTML 文件不存在：{html_path}")
        msg.add_alternative(html_path.read_text(encoding="utf-8"), subtype="html")

    for p in args.attach:
        fp = Path(p)
        if not fp.exists():
            raise SystemExit(f"[错误] 附件不存在：{fp}")
        ctype, _ = mimetypes.guess_type(str(fp))
        if ctype and ctype.startswith("text/"):
            maintype, subtype = ctype.split("/", 1)
            msg.add_attachment(fp.read_bytes(), maintype=maintype, subtype=subtype, filename=fp.name)
        else:
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            msg.add_attachment(fp.read_bytes(), maintype=maintype, subtype=subtype, filename=fp.name)
    return msg, sender


def main():
    ap = argparse.ArgumentParser(description="经 SMTP 发送情报简报")
    ap.add_argument("--to", required=True, help="收件人，多个用逗号分隔")
    ap.add_argument("--subject", required=True, help="主题行")
    ap.add_argument("--html", default="", help="HTML 正文文件")
    ap.add_argument("--text", default="", help="纯文本正文文件（作为备用部分）")
    ap.add_argument("--attach", action="append", default=[], help="附件路径，可重复")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的摘要，不实际发送")
    ap.add_argument("--timeout", type=int, default=30, help="超时秒数")
    args = ap.parse_args()

    args.to = [a.strip() for a in args.to.split(",") if a.strip()]
    if not args.to:
        raise SystemExit("[错误] 收件人为空。")
    if "@" not in args.to[0]:
        raise SystemExit(f"[错误] 收件地址格式可疑：{args.to[0]}。发送前请逐字核对。")

    try:
        msg, sender = build_message(args, allow_placeholder=args.dry_run)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"[错误] 构造邮件失败：{type(e).__name__}: {e}")

    print("── 发送摘要 ──")
    print(f"发件：{sender}")
    print(f"收件：{', '.join(args.to)}")
    print(f"主题：{args.subject}")
    print(f"附件：{', '.join(Path(p).name for p in args.attach) or '无'}")
    print(f"正文：{'HTML' if args.html else '纯文本'}，约 {len(msg.as_string()) // 1024} KB")

    if args.dry_run:
        print("[干跑] 未实际发送。核对无误后去掉 --dry-run 重跑。")
        return 0

    host = env("OSINT_SMTP_HOST")
    user = env("OSINT_SMTP_USER")
    pwd = os.environ.get("OSINT_SMTP_PASS", "")
    if not host or not user or not pwd:
        raise SystemExit(
            "[错误] 缺少 SMTP 凭据。请设置 OSINT_SMTP_HOST / OSINT_SMTP_USER / OSINT_SMTP_PASS。\n"
            "      注意：OSINT_SMTP_PASS 应为授权码或应用专用密码，不是网页登录密码。"
        )

    security = env("OSINT_SMTP_SECURITY").lower()
    port = int(env("OSINT_SMTP_PORT", "0") or 0)
    if not security:
        security = "starttls" if port == 587 else "ssl"
    if not port:
        port = 587 if security == "starttls" else 465

    ctx = ssl.create_default_context()
    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=args.timeout, context=ctx) as s:
                s.login(user, pwd)
                s.send_message(msg)
        elif security == "starttls":
            with smtplib.SMTP(host, port, timeout=args.timeout) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=args.timeout) as s:
                s.login(user, pwd)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        print("[失败] 认证被拒。多数邮箱需使用「授权码/应用专用密码」，且需先在网页端开启 SMTP 服务。", file=sys.stderr)
        return 4
    except (smtplib.SMTPException, OSError) as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        return 5

    print("[完成] 已发送。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
