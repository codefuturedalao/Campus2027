"""
Parse an approved GitHub Issue and update listings.json.

Usage:
    python contribution.py $GITHUB_EVENT_PATH
"""
import json
import re
import sys
import uuid
from datetime import datetime, timezone

import util

# ── Chinese labels used in Issue Form templates ──────────────────────────────
FIELD_LABELS = {
    "company_name":   "公司名称",
    "career_url":     "投递链接",
    "batch_type":     "批次类型",
    "category":       "行业分类",
    "status":         "招聘状态",
    "open_date":      "开放日期",
    "expected_date":  "预计开放日期",
    "locations":      "工作地点",
    "notes":          "备注",
    "email":          "联系邮箱",
}

CLOSE_FIELD_LABELS = {
    "company_name": "公司名称",
    "batch_type":   "批次类型",
    "career_url":   "投递链接（可选）",
}

STATUS_MAP = {
    "已开放": "open",
    "投递中": "open",
    "已截止": "closed",
    "已关闭": "closed",
    "未开放": "expected",
    "预计开放": "expected",
}


def parse_issue_body(body: str) -> dict:
    """Parse GitHub Issue Form body (### Label\\n\\nValue) into a dict."""
    fields: dict = {}
    # Split on section headers
    sections = re.split(r"(?:^|\n)### ", body.strip())
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Label is the first line; value is everything after the blank line
        if "\n\n" in section:
            label, _, raw_value = section.partition("\n\n")
        elif "\n" in section:
            label, _, raw_value = section.partition("\n")
        else:
            continue
        label = label.strip()
        value = raw_value.strip()
        if value.lower() not in ("_no response_", ""):
            fields[label] = value
    return fields


def field(parsed: dict, key: str) -> str:
    label = FIELD_LABELS.get(key, key)
    return parsed.get(label, "").strip()


def parse_status(s: str) -> str:
    for keyword, code in STATUS_MAP.items():
        if keyword in s:
            return code
    return "expected"


def parse_locations(s: str) -> list:
    if not s:
        return ["全国"]
    parts = re.split(r"[,，、|/\s]+", s)
    return [p.strip() for p in parts if p.strip()] or ["全国"]


def ensure_https(url: str) -> str:
    if url and not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        util.fail("Usage: contribution.py <event_path>")

    with open(sys.argv[1], encoding="utf-8") as f:
        event = json.load(f)

    issue   = event["issue"]
    body    = issue.get("body") or ""
    user    = issue["user"]["login"]
    labels  = {lbl["name"] for lbl in issue.get("labels", [])}

    is_new    = "new_job"    in labels
    is_update = "update_job" in labels
    is_close  = "close_job"  in labels

    if not any([is_new, is_update, is_close]):
        util.fail("Issue 必须带有 new_job / update_job / close_job 标签之一")

    parsed   = parse_issue_body(body)
    listings = util.get_listings()
    ts       = now_ts()

    # ── Close ────────────────────────────────────────────────────────────────
    if is_close:
        company_name  = parsed.get(CLOSE_FIELD_LABELS["company_name"], "").strip()
        batch_type    = parsed.get(CLOSE_FIELD_LABELS["batch_type"],   "").strip()
        career_url    = ensure_https(parsed.get(CLOSE_FIELD_LABELS["career_url"], "").strip())

        if not company_name or not batch_type:
            util.fail("关闭表单必须填写公司名称和批次类型")

        candidates = [
            l for l in listings
            if l["company_name"] == company_name and l["batch_type"] == batch_type
        ]
        if career_url:
            url_match = [l for l in candidates if l.get("career_url") == career_url]
            if url_match:
                candidates = url_match

        if not candidates:
            util.fail(f"未找到 {company_name} {batch_type} 的记录")

        for listing in candidates:
            listing["status"]       = "closed"
            listing["date_updated"] = ts

        util.set_output("commit_message", f"close: {company_name} {batch_type}")
        util.set_output("commit_email",    "action@github.com")
        util.set_output("commit_username", "Campus2027 Bot")

    # ── New / Update ─────────────────────────────────────────────────────────
    else:
        company_name = field(parsed, "company_name")
        career_url   = ensure_https(field(parsed, "career_url"))
        batch_type   = field(parsed, "batch_type")
        category     = field(parsed, "category")

        if not company_name or not career_url or not batch_type:
            util.fail("公司名称、投递链接和批次类型为必填项")

        data = {
            "company_name":      company_name,
            "career_url":        career_url,
            "batch_type":        batch_type,
            "category":          category,
            "status":            parse_status(field(parsed, "status")),
            "open_date":         field(parsed, "open_date") or None,
            "expected_date":     field(parsed, "expected_date") or None,
            "locations":         parse_locations(field(parsed, "locations")),
            "notes":             field(parsed, "notes"),
            "date_updated":      ts,
            "is_visible":        True,
            "source":            user,
            "wechat_article_url": None,
        }

        existing = next(
            (l for l in listings
             if l["company_name"] == company_name and l["batch_type"] == batch_type),
            None,
        )

        if is_update:
            if not existing:
                util.fail(f"未找到 {company_name} {batch_type} 的记录，请使用新增表单")
            existing.update(data)
            util.set_output("commit_message", f"update: {company_name} {batch_type}")
        else:  # new
            if existing:
                util.fail(f"{company_name} {batch_type} 已存在，请使用更新表单")
            data["id"]          = str(uuid.uuid4())
            data["date_posted"] = ts
            listings.append(data)
            util.set_output("commit_message", f"add: {company_name} {batch_type}")

        # Commit attribution
        email = field(parsed, "email")
        if email and "@" in email:
            util.set_output("commit_email",    email)
            util.set_output("commit_username", user)
        else:
            util.set_output("commit_email",    "action@github.com")
            util.set_output("commit_username", "Campus2027 Bot")

    util.save_listings(listings)
    print("listings.json 已更新")


if __name__ == "__main__":
    main()
