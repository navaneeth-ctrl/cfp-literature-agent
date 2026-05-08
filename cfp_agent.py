#!/usr/bin/env python3
"""
CFP Literature Agent
--------------------
Monitors call-for-papers.sas.upenn.edu for new literature CFPs and
emails a daily digest. Runs on GitHub Actions.

Strategy (most resilient first):
  1. RSS feed per category  → fast, lightweight XML
  2. HTML scrape of /category/all  → fallback with keyword filter

Environment variables (set as GitHub Secrets):
  RECIPIENT_EMAIL  – where you want to receive notifications
  SENDER_EMAIL     – Gmail address used to send
  SENDER_PASSWORD  – Gmail App Password (16 chars, NOT your real password)
"""

import os
import json
import datetime
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Literature categories (all have RSS feeds on the CFP site) ─────────────────
LITERATURE_CATEGORIES = [
    "african-american",
    "american",
    "childrens-literature",
    "classical-studies",
    "cultural-studies-and-historical-approaches",
    "ecocriticism-and-environmental-studies",
    "eighteenth-century",
    "ethnicity-and-national-identity",
    "film-and-television",
    "gender-studies-and-sexuality",
    "interdisciplinary",
    "international-conferences",
    "journals-and-collections-of-essays",
    "medieval",
    "modernist-studies",
    "online-conferences",
    "poetry",
    "popular-culture",
    "postcolonial",
    "renaissance",
    "romantic",
    "science-and-culture",
    "theory",
    "translation-studies",
    "travel-writing",
    "twentieth-century-and-beyond",
    "victorian",
    "world-literatures-and-indigenous-studies",
]

# Keywords used for catch-all HTML pass
LITERATURE_KEYWORDS = [
    "literature", "literary", "novel", "fiction", "poetry", "poem", "poet",
    "narrative", "text", "textual", "reading", "reader", "writing", "writer",
    "author", "book", "genre", "rhetoric", "composition", "humanities",
    "philology", "comparative", "translation", "postcolonial", "modernist",
    "victorian", "romantic", "renaissance", "medieval", "classical",
    "ecocriticism", "cultural studies", "film", "theatre", "performance",
    "language", "linguistic", "discourse", "canon", "pedagogy",
    "eighteenth century", "twentieth century", "world literature",
]

BASE_URL  = "https://call-for-papers.sas.upenn.edu"
SEEN_FILE = Path("seen_cfps.json")

# Browser-like headers to avoid bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "DNT":             "1",
}



# ── Persistence ────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        data = json.loads(SEEN_FILE.read_text())
        return set(data.get("seen", []))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps({"seen": sorted(seen)}, indent=2))


# ── HTTP helper ────────────────────────────────────────────────────────────────

def get(url: str, retries: int = 3, delay: float = 4.0):
    """GET with retry + back-off."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            if resp.status_code == 200:
                return resp
            print(f"  [HTTP {resp.status_code}] {url} (attempt {attempt+1})")
        except requests.RequestException as e:
            print(f"  [ERR] {url}: {e} (attempt {attempt+1})")
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    return None


# ── RSS scraping ───────────────────────────────────────────────────────────────

def parse_rss(resp) -> list:
    """Extract CFP items from an RSS feed using BeautifulSoup (tolerates malformed XML)."""
    cfps = []
    try:
        soup  = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")
    except Exception as e:
        print(f"  [RSS parse error] {e}")
        return cfps

    for item in items:
        def txt(tag):
            el = item.find(tag)
            return el.get_text(strip=True) if el else ""

        title    = txt("title")
        url      = txt("link") or txt("guid")
        desc     = txt("description") or txt("summary") or txt("content")
        pub_date = txt("pubDate") or txt("published")

        if not title or not url:
            continue

        snippet  = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)[:300]

        deadline = ""
        lower    = snippet.lower()
        idx      = lower.find("deadline for submissions:")
        if idx != -1:
            deadline = snippet[idx + len("deadline for submissions:"):idx + 60].strip()

        cfps.append({
            "title":    title,
            "url":      url,
            "deadline": deadline,
            "snippet":  snippet,
            "pub_date": pub_date,
            "category": "",
        })

    return cfps


def scrape_rss_category(category: str) -> list:
    """Fetch and parse the RSS feed for one category."""
    url  = f"{BASE_URL}/category/{category}/feed"
    resp = get(url)
    if resp is None:
        return []
    cfps = parse_rss(resp)
    for c in cfps:
        c["category"] = category
    return cfps


# ── HTML fallback scraping ─────────────────────────────────────────────────────

def is_literature_related(title: str, snippet: str) -> bool:
    combined = (title + " " + snippet).lower()
    return any(kw in combined for kw in LITERATURE_KEYWORDS)


def scrape_html_all(max_pages: int = 5) -> list:
    """
    Keyword-filtered scrape of /category/all HTML pages.
    Used as a catch-all for posts not assigned to a specific category.
    """
    cfps = []
    for page in range(max_pages):
        params = {"page": page} if page > 0 else {}
        url    = f"{BASE_URL}/category/all"
        resp   = requests.get(url, headers=HEADERS, params=params, timeout=25)
        if resp is None or resp.status_code != 200:
            break

        soup    = BeautifulSoup(resp.text, "html.parser")
        entries = soup.select("h2 a")
        if not entries:
            break

        for tag in entries:
            href  = tag.get("href", "")
            title = tag.get_text(strip=True)
            if not href or not title:
                continue

            full_url = href if href.startswith("http") else BASE_URL + href
            parent   = tag.find_parent(["div", "li", "article"]) or tag.parent
            snippet  = parent.get_text(" ", strip=True)[:400] if parent else ""

            if not is_literature_related(title, snippet):
                continue

            deadline = ""
            lower    = snippet.lower()
            idx      = lower.find("deadline for submissions:")
            if idx != -1:
                deadline = snippet[idx + len("deadline for submissions:"):idx + 60].strip()

            cfps.append({
                "title":    title,
                "url":      full_url,
                "deadline": deadline,
                "snippet":  snippet[:300],
                "pub_date": "",
                "category": "all",
            })

        if not soup.select_one("a[title='Go to next page']"):
            break
        time.sleep(1)   # polite crawling

    return cfps


# ── Main collection ────────────────────────────────────────────────────────────

def collect_new_cfps(seen: set) -> list:
    new_cfps     = []
    visited_urls = set()
    rss_success  = 0

    print(f"Scanning {len(LITERATURE_CATEGORIES)} categories via RSS …")
    for cat in LITERATURE_CATEGORIES:
        posts = scrape_rss_category(cat)
        if posts:
            rss_success += 1
        for post in posts:
            url = post["url"]
            if url not in seen and url not in visited_urls:
                visited_urls.add(url)
                new_cfps.append(post)
        time.sleep(0.5)   # polite rate limit

    print(f"  RSS succeeded for {rss_success}/{len(LITERATURE_CATEGORIES)} categories")

    # HTML catch-all pass
    print("Running HTML catch-all pass on /category/all …")
    for post in scrape_html_all():
        url = post["url"]
        if url not in seen and url not in visited_urls:
            visited_urls.add(url)
            new_cfps.append(post)

    print(f"Found {len(new_cfps)} new literature CFP(s).")
    return new_cfps


# ── Email ──────────────────────────────────────────────────────────────────────

def build_html_email(cfps: list) -> str:
    today = datetime.date.today().strftime("%B %d, %Y")

    rows = ""
    for c in cfps:
        cat_label = c["category"].replace("-", " ").title() if c["category"] else "General"
        deadline_html = (
            f'&nbsp;·&nbsp; ⏰ <b>Deadline:</b> {c["deadline"]}'
            if c["deadline"] else ""
        )
        rows += f"""
        <tr>
          <td style="padding:16px 28px; border-bottom:1px solid #e5e7eb; vertical-align:top;">
            <a href="{c['url']}"
               style="color:#1d4ed8; font-size:16px; font-weight:700;
                      text-decoration:none; line-height:1.4; display:block; margin-bottom:5px;">
              {c['title']}
            </a>
            <span style="color:#6b7280; font-size:12px;">
              📂 {cat_label}{deadline_html}
            </span><br>
            <span style="color:#374151; font-size:13px; margin-top:5px; display:block;">
              {c['snippet'][:240]}…
            </span>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="680" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:10px;border:1px solid #d1d5db;overflow:hidden;
                    max-width:680px;">
        <tr>
          <td style="background:#1e3a5f;padding:28px 32px;">
            <h1 style="margin:0;color:#fff;font-size:24px;font-family:Georgia,serif;">
              📚 Literature CFP Digest
            </h1>
            <p style="margin:6px 0 0;color:#93c5fd;font-size:14px;">
              {today} &nbsp;·&nbsp;
              {len(cfps)} new call{"s" if len(cfps) != 1 else ""} for papers
            </p>
          </td>
        </tr>
        <tr><td>
          <table width="100%" cellpadding="0" cellspacing="0">
            {rows}
          </table>
        </td></tr>
        <tr>
          <td style="background:#f9fafb;padding:18px 32px;font-size:12px;
                     color:#6b7280;text-align:center;border-top:1px solid #e5e7eb;">
            Source:
            <a href="https://call-for-papers.sas.upenn.edu" style="color:#1d4ed8;">
              call-for-papers.sas.upenn.edu
            </a>
            — University of Pennsylvania, Dept. of English<br>
            Automated by <b>CFP Literature Agent</b> running on GitHub Actions
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_plain_email(cfps: list) -> str:
    today = datetime.date.today().strftime("%B %d, %Y")
    lines = [f"Literature CFP Digest — {today}", "=" * 52, ""]
    for i, c in enumerate(cfps, 1):
        lines.append(f"{i}. {c['title']}")
        lines.append(f"   URL:      {c['url']}")
        if c["deadline"]:
            lines.append(f"   Deadline: {c['deadline']}")
        if c["category"]:
            lines.append(f"   Category: {c['category'].replace('-',' ').title()}")
        lines.append("")
    lines.append("Source: https://call-for-papers.sas.upenn.edu")
    return "\n".join(lines)


def send_email(cfps: list) -> None:
    sender    = os.environ["SENDER_EMAIL"]
    password  = os.environ["SENDER_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    today     = datetime.date.today().strftime("%B %d, %Y")
    count     = len(cfps)

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 {count} New Literature CFP{'s' if count != 1 else ''} — {today}"
    msg["From"]    = f"CFP Literature Agent <{sender}>"
    msg["To"]      = recipient

    msg.attach(MIMEText(build_plain_email(cfps), "plain"))
    msg.attach(MIMEText(build_html_email(cfps),  "html"))

    print(f"Sending digest to {recipient} …")
    with smtplib.SMTP("smtp-relay.brevo.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print("Email sent ✓")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("── CFP Literature Agent ──────────────────────────────────")
    print(f"Run time (UTC): {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')}")

    seen     = load_seen()
    print(f"Previously seen CFPs: {len(seen)}")

    new_cfps = collect_new_cfps(seen)

    if not new_cfps:
        print("No new CFPs found — skipping email.")
    else:
        send_email(new_cfps)
        for c in new_cfps:
            seen.add(c["url"])

    save_seen(seen)
    print("── Done ──────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
