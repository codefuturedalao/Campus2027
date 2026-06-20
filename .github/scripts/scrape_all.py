"""
Phase 3 爬虫：关键词探活 + 状态变更检测

策略：
  1. keyword  - requests GET 页面，检测初始 HTML 是否含目标关键词
  2. feishu_api - 直接请求飞书招聘 API，检测是否有符合条件的职位

运行方式：
  python scrape_all.py              # 正常运行，更新 listings.json
  python scrape_all.py --dry-run    # 只打印结果，不写入
"""
import json
import sys
import time
import random
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx   # pip install httpx

import util

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CONFIG_FILE   = Path(__file__).parent / "scraper_config.json"
SCRAPE_STATE  = Path(__file__).parent / "scrape_state.json"  # 上次抓取结果缓存
DRY_RUN       = "--dry-run" in sys.argv

TARGET_YEAR   = "2027"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Load / save scrape state ─────────────────────────────────────────────────

def load_state() -> dict:
    if SCRAPE_STATE.exists():
        with open(SCRAPE_STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(SCRAPE_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── Probe methods ─────────────────────────────────────────────────────────────

def probe_keyword(client: httpx.Client, config: dict) -> dict:
    """GET page HTML and check for keywords in the raw response."""
    url      = config["check_url"]
    keywords = config.get("keywords", [TARGET_YEAR])
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
        text  = r.text.lower()
        found = [kw for kw in keywords if kw.lower() in text]
        # A page that mentions the target year + recruitment terms is likely open
        year_present     = TARGET_YEAR in text
        recruit_present  = any(k in text for k in ["秋招", "提前批", "校园招聘", "campus"])
        is_open          = year_present and recruit_present
        return {
            "reachable": True,
            "status_code": r.status_code,
            "keywords_found": found,
            "is_open": is_open,
            "content_hash": hashlib.md5(r.content).hexdigest(),
            "method": "keyword",
        }
    except Exception as e:
        log.warning(f"[keyword] {url} 请求失败: {e}")
        return {"reachable": False, "is_open": None, "method": "keyword", "error": str(e)}


def probe_feishu(client: httpx.Client, config: dict) -> dict:
    """
    Try to call the Feishu/Lark recruitment API.
    Falls back to keyword method if the API URL is not set.
    """
    api_url = config.get("api_url")
    if not api_url:
        return probe_keyword(client, config)

    try:
        r    = client.get(api_url, timeout=15, follow_redirects=True,
                          headers={**HEADERS, "Accept": "application/json"})
        data = r.json()
        # Feishu API typically returns {"data": {"job_post_list": [...]}, "code": 0}
        jobs = []
        if isinstance(data, dict):
            jobs = (data.get("data") or {}).get("job_post_list", []) or \
                   (data.get("data") or {}).get("list", []) or \
                   data.get("list", [])

        # Check if any job title / description mentions 2027 or campus keywords
        year_hits = [
            j for j in jobs
            if TARGET_YEAR in json.dumps(j, ensure_ascii=False)
        ]
        is_open = len(year_hits) > 0 or (len(jobs) > 0)  # any active jobs = possibly open

        return {
            "reachable": True,
            "status_code": r.status_code,
            "job_count": len(jobs),
            "year_hits": len(year_hits),
            "is_open": is_open,
            "content_hash": hashlib.md5(r.content).hexdigest(),
            "method": "feishu_api",
        }
    except Exception as e:
        log.warning(f"[feishu_api] {api_url} 失败，降级为关键词探活: {e}")
        return probe_keyword(client, config)


PROBERS = {
    "keyword":    probe_keyword,
    "feishu_api": probe_feishu,
}


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        configs = json.load(f)

    listings     = util.get_listings()
    old_state    = load_state()
    new_state    = dict(old_state)
    changes      = []   # list of (company, batch, old_status, new_status)

    with httpx.Client(headers=HEADERS, http2=False) as client:
        for cfg in configs:
            key     = f"{cfg['company_name']}::{cfg['batch_type']}"
            method  = cfg.get("method", "keyword")
            prober  = PROBERS.get(method, probe_keyword)

            log.info(f"探活 [{method}] {cfg['company_name']} {cfg['batch_type']}")
            result  = prober(client, cfg)
            log.info(f"  → reachable={result.get('reachable')} "
                     f"is_open={result.get('is_open')} "
                     f"hash={result.get('content_hash','')[:8]}")

            new_state[key] = {**result, "checked_at": int(datetime.now(timezone.utc).timestamp())}

            # ── Detect status change ──────────────────────────────────────────
            if not result.get("reachable"):
                time.sleep(random.uniform(1.5, 3.0))
                continue

            # Find matching listing
            listing = next(
                (l for l in listings
                 if l["company_name"] == cfg["company_name"]
                 and l["batch_type"] == cfg["batch_type"]),
                None,
            )
            if not listing:
                log.warning(f"  listings.json 中未找到 {key}，跳过")
                time.sleep(random.uniform(1.0, 2.5))
                continue

            old_status = listing.get("status", "expected")

            # ── Determine new status ──────────────────────────────────────────
            if result.get("is_open") is True and old_status == "expected":
                new_status = "open"
            elif result.get("is_open") is False and old_status == "open":
                # Don't auto-close: could be a false negative (SPA didn't load)
                # Only auto-close if method is reliable (feishu_api)
                new_status = "closed" if method == "feishu_api" else old_status
            else:
                new_status = old_status

            if new_status != old_status:
                changes.append({
                    "company":    cfg["company_name"],
                    "batch_type": cfg["batch_type"],
                    "old":        old_status,
                    "new":        new_status,
                })
                if not DRY_RUN:
                    listing["status"]       = new_status
                    listing["date_updated"] = int(datetime.now(timezone.utc).timestamp())
                    if new_status == "open" and not listing.get("open_date"):
                        listing["open_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    log.info(f"  ✅ 状态更新: {old_status} → {new_status}")

            # Random sleep to avoid rate-limiting
            time.sleep(random.uniform(2.0, 5.0))

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info(f"\n{'='*50}")
    log.info(f"探活完成：共检查 {len(configs)} 家，发现 {len(changes)} 处变更")
    for c in changes:
        log.info(f"  [{c['company']} {c['batch_type']}] {c['old']} → {c['new']}")

    if not DRY_RUN:
        util.save_listings(listings)
        save_state(new_state)
        log.info("listings.json 和 scrape_state.json 已保存")
    else:
        log.info("[DRY-RUN] 未写入任何文件")

    # Export changes count for GitHub Actions
    util.set_output("changes_count", str(len(changes)))
    util.set_output("has_changes",   "true" if changes else "false")


if __name__ == "__main__":
    main()
