"""Shared utilities for Campus2027 GitHub Actions scripts."""
import json
import os
import sys
from pathlib import Path

LISTINGS_FILE = Path(__file__).parent / "listings.json"

CATEGORIES_ORDER = [
    "互联网/AI",
    "游戏",
    "外企（中国）",
    "车企/通信/IC",
    "金融/银行/国企",
    "安全/软件/云",
]

BATCH_ORDER = ["提前批", "正式批", "实习"]

STATUS_DISPLAY = {
    "open":     "✅ 投递中",
    "closed":   "🔒 已截止",
    "expected": "⏳ 未开放",
}


def get_listings() -> list:
    with open(LISTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_listings(listings: list) -> None:
    with open(LISTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=4)


def set_output(name: str, value: str) -> None:
    """Write a GitHub Actions step output."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    else:
        # Fallback for local testing
        print(f"OUTPUT {name}={value}")


def fail(message: str) -> None:
    set_output("error_message", message)
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def format_date(ts: int) -> str:
    """Format a Unix timestamp as YYYY/MM/DD."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y/%m/%d")


def format_locations(locations: list) -> str:
    """Join location list to a short string."""
    if not locations:
        return "全国"
    if len(locations) > 3:
        return "、".join(locations[:3]) + "等"
    return "、".join(locations)
