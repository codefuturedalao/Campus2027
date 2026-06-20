"""
Regenerate README.md from listings.json.

Usage:
    python update_readme.py
"""
from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path

import util

README_FILE = Path(__file__).parent.parent.parent / "README.md"

# Ordered section titles displayed in README
BATCH_TITLES = {
    "提前批": "校招提前批",
    "正式批": "校招正式批",
    "实习":   "实习",
}

TABLE_HEADER = (
    "| 公司 | 状态 & 投递链接 | 地点 | 更新日期 | 备注 |\n"
    "| ---- | -------------- | ---- | -------- | ---- |"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def status_cell(listing: dict) -> str:
    status  = listing.get("status", "expected")
    url     = listing.get("career_url", "")
    label   = util.STATUS_DISPLAY.get(status, "⏳ 未开放")

    date_hint = ""
    if status == "open" and listing.get("open_date"):
        date_hint = f"（{listing['open_date']}）"
    elif status == "expected" and listing.get("expected_date"):
        date_hint = f"（预计 {listing['expected_date']}）"

    display = f"{label}{date_hint}"
    return f"[{display}]({url})" if url else display


def make_table(listings: list) -> str:
    rows = [TABLE_HEADER]
    for l in sorted(listings, key=lambda x: x["company_name"]):
        company  = l.get("company_name", "")
        status   = status_cell(l)
        locs     = util.format_locations(l.get("locations", []))
        updated  = util.format_date(l.get("date_updated", 0))
        notes    = l.get("notes", "").replace("\n", " ").strip()
        rows.append(f"| {company} | {status} | {locs} | {updated} | {notes} |")
    return "\n".join(rows)


def make_section(batch_type: str, listings_in_batch: list) -> str:
    title = BATCH_TITLES.get(batch_type, batch_type)
    lines = [f"## {title}\n"]

    by_category = defaultdict(list)
    for l in listings_in_batch:
        by_category[l.get("category", "其他")].append(l)

    for cat in util.CATEGORIES_ORDER:
        if cat not in by_category:
            continue
        lines.append(f"### {cat}\n")
        lines.append(make_table(by_category[cat]))
        lines.append("")

    # Append any categories not in the predefined order
    for cat, items in by_category.items():
        if cat not in util.CATEGORIES_ORDER:
            lines.append(f"### {cat}\n")
            lines.append(make_table(items))
            lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def get_repo_slug() -> str:
    """Return 'owner/repo' from GITHUB_REPOSITORY env var, or a placeholder."""
    return os.environ.get("GITHUB_REPOSITORY", "your-username/Campus2027")


def build_readme(listings: list) -> str:
    visible = [l for l in listings if l.get("is_visible", True)]

    total    = len(visible)
    open_cnt = sum(1 for l in visible if l.get("status") == "open")
    exp_cnt  = sum(1 for l in visible if l.get("status") == "expected")

    now_str  = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    repo     = get_repo_slug()

    # Group by batch_type
    by_batch = defaultdict(list)
    for l in visible:
        by_batch[l.get("batch_type", "正式批")].append(l)

    sections = []
    for batch in util.BATCH_ORDER:
        if batch in by_batch:
            sections.append(make_section(batch, by_batch[batch]))

    readme = f"""\
# Campus 2027 | 2027届互联网秋招信息汇总

[![自动更新](https://github.com/{repo}/actions/workflows/contribution.yml/badge.svg)](https://github.com/{repo}/actions)

> **2027届计算机学生秋招信息追踪** · 每日更新 · 欢迎共创
>
> 数据来源：各大厂官方校招官网 + 社区贡献
> 最后更新：`{now_str}`

**📊 当前统计：** 共收录 **{total}** 条 · 已开放 **{open_cnt}** 条 · 待开放 **{exp_cnt}** 条

---

## 说明

| 图标 | 含义 |
| ---- | ---- |
| ✅ 投递中 | 当前可投递 |
| ⏳ 未开放 | 尚未开放，括号内为预计开放日期 |
| 🔒 已截止 | 投递已截止 |

> **提交新信息 / 更新 / 纠错** → 点击 [Issue → 新建](../../issues/new/choose) 选择对应模板  
> **贡献指南** → 查看 [CONTRIBUTING.md](./CONTRIBUTING.md)

---

{chr(10).join(sections)}
---

## 相关资源

- [牛客网校招日历](https://www.nowcoder.com/school/schedule)
- [LeetCode Hot 100](https://leetcode.cn/studyplan/top-100-liked/)
- [2026届参考（Campus2026）](https://github.com/namewyf/Campus2026)

---

> **免责声明：** 本项目数据来源于官方网站及社区贡献，仅供参考，请以各公司官方通知为准。
"""
    return readme


def main() -> None:
    listings = util.get_listings()
    readme   = build_readme(listings)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme)

    print(f"README.md 已更新（共 {len(listings)} 条记录）")


if __name__ == "__main__":
    main()
