import requests
import feedparser
import json
import os
import hashlib
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
NTFY_TOPIC   = os.environ.get("NTFY_TOPIC", "atharva-news-bot")  # change to your topic
SEEN_FILE    = "seen_ids.json"

SOURCES = {
    "ZeroHedge": {
        "type": "rss",
        "url": "https://feeds.feedburner.com/zerohedge/feed",
    },
    "Unusual Whales": {
        "type": "rss",
        "url": "https://unusualwhales.com/rss.xml",
    },
    "WatcherGuru": {
        "type": "scrape",
        "url": "https://watcher.guru/news/",
    },
}

# ── Seen IDs (dedup) ─────────────────────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    # keep last 500 only
    seen_list = list(seen)[-500:]
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_list, f)

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()

# ── Fetchers ─────────────────────────────────────────────────────────────────
def fetch_rss(url):
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:5]:  # latest 5
            title = entry.get("title", "").strip()
            link  = entry.get("link", "")
            items.append({"title": title, "link": link})
        return items
    except Exception as e:
        print(f"RSS error {url}: {e}")
        return []

def fetch_watcherguru():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://watcher.guru/news/", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for article in soup.select("article")[:5]:
            title_tag = article.select_one("h2, h3")
            link_tag  = article.select_one("a")
            if title_tag and link_tag:
                title = title_tag.get_text(strip=True)
                link  = link_tag.get("href", "")
                if not link.startswith("http"):
                    link = "https://watcher.guru" + link
                items.append({"title": title, "link": link})
        return items
    except Exception as e:
        print(f"WatcherGuru scrape error: {e}")
        return []

# ── AI Analysis via Groq ──────────────────────────────────────────────────────
def analyze(title):
    if not GROQ_API_KEY:
        return "⚠️ No Groq key set."
    try:
        payload = {
            "model": "llama3-8b-8192",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a sharp financial analyst. Given a news headline, "
                        "in 2-3 lines tell: (1) what happened, (2) which asset classes "
                        "are impacted (crypto, equities, gold, forex, bonds), "
                        "(3) likely direction (bullish/bearish/neutral) and why. "
                        "Be concise and direct. No fluff."
                    )
                },
                {"role": "user", "content": f"Headline: {title}"}
            ],
            "max_tokens": 150,
            "temperature": 0.3,
        }
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15
        )
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Analysis error: {e}"

# ── Ntfy Notification ─────────────────────────────────────────────────────────
def notify(source, title, analysis, link):
    try:
        message = f"{analysis}\n\n🔗 {link}"
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": f"[{source}] {title[:80]}",
                "Priority": "default",
                "Tags": "newspaper,chart_with_upwards_trend",
            },
            timeout=10
        )
        print(f"✅ Sent: {title[:60]}")
    except Exception as e:
        print(f"Ntfy error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    new_seen = set()

    all_items = []

    # RSS sources
    for name, cfg in SOURCES.items():
        if cfg["type"] == "rss":
            items = fetch_rss(cfg["url"])
            for item in items:
                all_items.append((name, item))

    # WatcherGuru scrape
    wg_items = fetch_watcherguru()
    for item in wg_items:
        all_items.append(("WatcherGuru", item))

    print(f"Fetched {len(all_items)} total items")

    for source, item in all_items:
        title = item["title"]
        link  = item["link"]
        uid   = make_id(title)

        if uid in seen:
            continue  # already processed

        new_seen.add(uid)
        print(f"\n🔍 [{source}] {title}")

        analysis = analyze(title)
        print(f"📊 {analysis}")

        notify(source, title, analysis, link)

    seen.update(new_seen)
    save_seen(seen)
    print(f"\nDone. {len(new_seen)} new items processed.")

if __name__ == "__main__":
    main()
