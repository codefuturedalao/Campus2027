#!/usr/bin/env python3
"""
微信公众号招聘监控 —— 基于 WeWe RSS
--------------------------------------
依赖一个自托管的 WeWe RSS 实例 (https://github.com/cooderl/wewe-rss)
WeWe RSS 通过微信读书 API 稳定拉取公众号文章，并暴露标准 RSS/Atom 端点。

环境变量（GitHub Secrets）：
  WEWE_RSS_BASE   WeWe RSS 实例根 URL，例如 https://wewe-rss.railway.app
  WEWE_RSS_TOKEN  可选，WeWe RSS 的 AUTH_CODE

工作流程：
  1. 拉取 /feeds/all.atom，用 title_include 过滤招聘关键词
  2. 解析每条文章标题，匹配 wechat_accounts.json 中的公司
  3. 检测到"开启/启动"→ 更新 listings.json 对应条目状态为 open
"""

import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import URLError, HTTPError

SCRIPT_DIR    = Path(__file__).parent
LISTINGS_PATH = SCRIPT_DIR / "listings.json"
ACCOUNTS_PATH = SCRIPT_DIR / "wechat_accounts.json"
STATE_PATH    = SCRIPT_DIR / "wechat_state.json"

# ── 关键词 ──────────────────────────────────────────────────────
OPEN_KEYWORDS    = ["开启", "启动", "开放", "正式开始", "投递通道", "开门", "上线", "火热招募"]
CLOSE_KEYWORDS   = ["截止", "结束", "关闭", "停止接收", "暂停投递"]
YEAR_KEYWORDS    = ["2027", "27届"]
RECRUIT_KEYWORDS = ["校招", "秋招", "提前批", "校园招聘", "实习"]

# WeWe RSS 拉取时用的标题过滤（OR 逻辑，"|"分隔）
TITLE_INCLUDE = quote("2027|27届|校招|秋招|提前批")


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def set_gha_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT", "")
    if out:
        with open(out, "a") as f:
            f.write(f"{name}={value}\n")


# ── RSS 拉取 ────────────────────────────────────────────────────

def fetch_feed(base_url: str, token: str | None) -> list[dict]:
    """
    拉取 WeWe RSS 的聚合 Atom feed，返回文章列表。
    每条文章：{title, summary, published, feed_id}
    """
    params = {"title_include": TITLE_INCLUDE}
    url = f"{base_url.rstrip('/')}/feeds/all.atom?{urlencode(params)}"

    headers = {"User-Agent": "Campus2027-Bot/1.0", "Accept": "application/atom+xml"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except HTTPError as e:
        print(f"[ERROR] fetch_feed HTTP {e.code}: {url}", file=sys.stderr)
        return []
    except URLError as e:
        print(f"[ERROR] fetch_feed URLError: {e.reason}", file=sys.stderr)
        return []

    # 解析 Atom XML
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[ERROR] XML parse: {e}", file=sys.stderr)
        return []

    articles = []
    for entry in root.findall("atom:entry", ns):
        title_el   = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        pub_el     = entry.find("atom:published", ns)
        src_el     = entry.find("atom:source/atom:id", ns)

        articles.append({
            "title":     title_el.text.strip()   if title_el   is not None else "",
            "summary":   summary_el.text.strip()  if summary_el is not None else "",
            "published": pub_el.text.strip()      if pub_el     is not None else "",
            "feed_id":   src_el.text.strip()      if src_el     is not None else "",
        })

    return articles


# ── 文章分析 ────────────────────────────────────────────────────

def classify_article(title: str, summary: str) -> str:
    """
    返回 'open' | 'close' | 'irrelevant'
    必须同时包含年份关键词 + 招聘关键词 + 动作关键词。
    """
    combined = title + " " + summary
    has_year    = any(k in combined for k in YEAR_KEYWORDS)
    has_recruit = any(k in combined for k in RECRUIT_KEYWORDS)

    if not (has_year and has_recruit):
        return "irrelevant"

    if any(k in combined for k in OPEN_KEYWORDS):
        return "open"
    if any(k in combined for k in CLOSE_KEYWORDS):
        return "close"
    return "irrelevant"


def match_company(title: str, summary: str, company_name: str, wechat_name: str) -> bool:
    """
    文章是否属于该公司的招聘账号。
    匹配逻辑：公司名（前2字）出现在标题/摘要中，或公众号名匹配。
    """
    combined = title + " " + summary
    short    = company_name[:2]
    return (company_name in combined or short in combined or wechat_name in combined)


# ── 主流程 ──────────────────────────────────────────────────────

def main() -> None:
    # 配置
    base_url = os.environ.get("WEWE_RSS_BASE", "").rstrip("/")
    token    = os.environ.get("WEWE_RSS_TOKEN", "") or None
    dry_run  = os.environ.get("DRY_RUN", "false").lower() == "true"

    if not base_url:
        print("[ERROR] WEWE_RSS_BASE 未设置，请在 GitHub Secrets 中配置", file=sys.stderr)
        print("[INFO]  若尚未部署 WeWe RSS，参考 README 的《部署指南》章节")
        set_gha_output("changed", "false")
        sys.exit(0)   # 不阻断 CI，降级退出

    if dry_run:
        print("[DRY RUN] 不写入任何文件")

    accounts = load_json(ACCOUNTS_PATH)
    listings = load_json(LISTINGS_PATH)
    state    = load_json(STATE_PATH) if STATE_PATH.exists() else {}

    # listings 快速查找：(company_name, batch_type) → entry（优先 expected）
    listing_map: dict[tuple, dict] = {}
    for entry in listings:
        key = (entry["company_name"], entry["batch_type"])
        if key not in listing_map or entry["status"] == "expected":
            listing_map[key] = entry

    # ── 拉取 RSS ──
    print(f"[INFO] 拉取 {base_url}/feeds/all.atom ...")
    articles = fetch_feed(base_url, token)
    print(f"[INFO] 获取到 {len(articles)} 篇相关文章")

    if not articles:
        print("[WARN] 未获取到文章，请检查 WeWe RSS 实例和公众号订阅状态")
        set_gha_output("changed", "false")
        return

    ts_now  = now_ts()
    changed = False

    # ── 逐篇文章匹配 ──
    for art in articles:
        action = classify_article(art["title"], art["summary"])
        if action == "irrelevant":
            continue

        for acc in accounts:
            company = acc["company_name"]
            batch   = acc["batch_type"]
            wechat  = acc["wechat_name"]

            if not match_company(art["title"], art["summary"], company, wechat):
                continue

            entry = listing_map.get((company, batch))
            if entry is None:
                continue
            if entry["status"] != "expected":
                continue

            state_key = f"{company}__{batch}"
            print(
                f"  {'🔓' if action == 'open' else '🔒'} "
                f"{company}/{batch} | {art['title'][:50]}"
            )

            if action == "open" and not dry_run:
                entry["status"]       = "open"
                entry["open_date"]    = today_str()
                entry["date_updated"] = ts_now
                entry["notes"]        = (
                    f"微信公众号「{wechat}」检测到开启公告：{art['title']}"
                )
                state[state_key] = {
                    "last_updated": ts_now,
                    "matched_title": art["title"],
                    "published": art["published"],
                }
                changed = True

    # ── 持久化 ──
    if not dry_run:
        save_json(STATE_PATH, state)
        if changed:
            save_json(LISTINGS_PATH, listings)
            print(f"\n✅ listings.json 已更新")
        else:
            print(f"\nℹ️  无状态变更")

    set_gha_output("changed", "true" if changed else "false")


if __name__ == "__main__":
    main()
