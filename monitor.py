"""
Philly Godfather members-area pick monitor.

- Logs into the members area
- Parses the picks table (date / author / picks-text rows)
- Stores raw rows exactly as posted (source of truth for future grading)
- Best-effort splits rows on "/" into individual picks; anything that
  doesn't cleanly split (space-separated bundles, teasers, ticket-number
  rows) is kept whole and flagged `needs_manual_split` rather than guessed at
- Tracks which rows have already been seen using a private GitHub Gist
- Emails a summary when new rows appear
- Skips entirely during quiet hours (no site load at all in that window)
"""

import hashlib
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SITE_URL = "https://www.thephillygodfather.com/members-area/"
LOGIN_URL = "https://www.thephillygodfather.com/members-area/"

TIMEZONE = "America/Chicago"
QUIET_HOURS_START = 0   # 12am
QUIET_HOURS_END = 6     # 6am (exclusive)

GIST_API = "https://api.github.com/gists/{gist_id}"
STATE_FILENAME = "last_seen.json"
MAX_HISTORY = 500  # bound how many fingerprints we keep around

USER_AGENT = "Mozilla/5.0 (compatible; PicksMonitor/1.0; +personal use)"


def in_quiet_hours() -> bool:
    now = datetime.now(ZoneInfo(TIMEZONE))
    return QUIET_HOURS_START <= now.hour < QUIET_HOURS_END


# ---------------------------------------------------------------------------
# State storage (private Gist — keeps history off the public repo entirely)
# ---------------------------------------------------------------------------

def load_state(gist_id: str, token: str) -> list[dict]:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    resp = requests.get(GIST_API.format(gist_id=gist_id), headers=headers, timeout=30)
    resp.raise_for_status()
    files = resp.json().get("files", {})
    if STATE_FILENAME not in files:
        return []
    content = files[STATE_FILENAME]["content"]
    return json.loads(content) if content.strip() else []


def save_state(gist_id: str, token: str, rows: list[dict]) -> None:
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    payload = {"files": {STATE_FILENAME: {"content": json.dumps(rows, indent=2)}}}
    resp = requests.patch(GIST_API.format(gist_id=gist_id), headers=headers, json=payload, timeout=30)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Site interaction
# ---------------------------------------------------------------------------

def login(session: requests.Session, username: str, password: str) -> requests.Response:
    resp = session.post(
        LOGIN_URL,
        data={
            "form_username": username,
            "form_password": password,
            "form_remember": "true",
            "form_btn": "Submit",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp


def fingerprint(date_text: str, full_text: str) -> str:
    return hashlib.sha256(f"{date_text}|{full_text}".encode("utf-8")).hexdigest()


def split_picks(full_text: str) -> tuple[list[str], bool]:
    """
    Best-effort split of a row's text into individual picks.
    Returns (picks, needs_manual_split).
    Only splits on "/" — anything without that delimiter is kept whole
    rather than guessed at, since space-separated bundles and teasers
    aren't reliably separable with plain text rules.
    """
    if "/" in full_text:
        parts = [p.strip(" /") for p in full_text.split("/")]
        parts = [p for p in parts if p]
        if len(parts) > 1:
            return parts, False
    return [full_text], True


def fetch_picks(session: requests.Session) -> list[dict]:
    resp = session.get(SITE_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue
        date_text = cells[0].get_text(strip=True)
        author_text = cells[1].get_text(strip=True)
        full_text = cells[2].get_text(" ", strip=True)
        if not date_text or not full_text:
            continue

        picks, needs_manual_split = split_picks(full_text)
        rows.append({
            "fingerprint": fingerprint(date_text, full_text),
            "date": date_text,
            "author": author_text,
            "raw_text": full_text,
            "picks": picks,
            "needs_manual_split": needs_manual_split,
        })
    return rows


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(new_rows: list[dict], smtp_user: str, smtp_pass: str, to_addr: str) -> None:
    lines = []
    for row in new_rows:
        lines.append(f"{row['date']} — {row['raw_text']}")
        if row["needs_manual_split"]:
            lines.append("   (bundled picks — not auto-split)")
        elif len(row["picks"]) > 1:
            for p in row["picks"]:
                lines.append(f"   - {p}")
        lines.append("")

    body = "New picks posted:\n\n" + "\n".join(lines)
    msg = MIMEText(body)
    msg["Subject"] = f"{len(new_rows)} new Philly Godfather pick post(s)"
    msg["From"] = smtp_user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if in_quiet_hours():
        print("Within quiet hours (12am-6am Central) — skipping check entirely.")
        return

    username = os.environ["SITE_USERNAME"]
    password = os.environ["SITE_PASSWORD"]
    gist_id = os.environ["GIST_ID"]
    gist_token = os.environ["GIST_TOKEN"]
    smtp_user = os.environ["GMAIL_USER"]
    smtp_pass = os.environ["GMAIL_APP_PASSWORD"]
    alert_to = os.environ.get("ALERT_TO", smtp_user)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    login(session, username, password)
    rows = fetch_picks(session)

    if not rows:
        print("No rows parsed — page structure may have changed, or login failed.", file=sys.stderr)
        sys.exit(1)

    seen_fingerprints = {r["fingerprint"] for r in load_state(gist_id, gist_token)}
    new_rows = [r for r in rows if r["fingerprint"] not in seen_fingerprints]

    if new_rows:
        print(f"Found {len(new_rows)} new row(s). Sending email.")
        send_email(new_rows, smtp_user, smtp_pass, alert_to)
    else:
        print("No new rows.")

    # Merge: keep everything currently on the page, plus older history, bounded.
    current_fps = {r["fingerprint"] for r in rows}
    merged = {r["fingerprint"]: r for r in rows}
    for old in load_state(gist_id, gist_token):
        merged.setdefault(old["fingerprint"], old)

    all_rows = list(merged.values())
    if len(all_rows) > MAX_HISTORY:
        # Prioritize rows currently visible on the page, then fill with recent history.
        current = [r for r in all_rows if r["fingerprint"] in current_fps]
        rest = [r for r in all_rows if r["fingerprint"] not in current_fps]
        all_rows = current + rest[: MAX_HISTORY - len(current)]

    save_state(gist_id, gist_token, all_rows)


if __name__ == "__main__":
    main()
