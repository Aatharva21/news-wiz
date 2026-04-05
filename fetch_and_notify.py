import requests
import feedparser
import json
import os
import hashlib
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
NTFY_TOPIC   = os.environ.get("NTFY_TOPIC", "news-wiz")
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
    return set()  # temporary: always treat everything as new

def save_seen(seen):
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
        for entry in feed.entries[:5]:
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
        return "No Groq key set."
    try:
        payload = {
            "model": "llama3-8b-8192",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a sharp financial analyst. Given a news headline, write 2-3 sentences analyzing "
                        "the real market impact. Think naturally about what this news actually moves — don't force "
                        "every asset class. Always include your view on Crypto/BTC, Gold, and Oil somewhere in the "
                        "analysis even if briefly. Be intelligent, specific, and direct. No bullet points, no fluff."
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
        print(f"Groq raw error: {e}")
        return "Analysis unavailable."

# ── Ntfy Notification ─────────────────────────────────────────────────────────
def notify(source, title, analysis):
    try:
        message = f"{title}\n\n{analysis}"
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": source,
                "Priority": "default",
            },
            timeout=10
        )
        print(f"Sent: {title[:60]}")
    except Exception as e:
        print(f"Ntfy error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    new_seen = set()
    all_items = []

    for name, cfg in SOURCES.items():
        if cfg["type"] == "rss":
            items = fetch_rss(cfg["url"])
            for item in items:
                all_items.append((name, item))

    wg_items = fetch_watcherguru()
    for item in wg_items:
        all_items.append(("WatcherGuru", item))

    print(f"Fetched {len(all_items)} total items")

    for source, item in all_items:
        title = item["title"]
        uid   = make_id(title)

        if uid in seen:
            continue

        new_seen.add(uid)
        print(f"\n[{source}] {title}")

        analysis = analyze(title)
        print(f"Analysis: {analysis}")

        notify(source, title, analysis)

    seen.update(new_seen)
    save_seen(seen)
    print(f"\nDone. {len(new_seen)} new items processed.")

if __name__ == "__main__":
    main()
