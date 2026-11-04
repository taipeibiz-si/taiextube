"""
台股 Tube 爬蟲：抓 PTT 股票板（Stock）文章與推文裡的 YouTube 連結，
計算每支影片被推薦的熱門度，存成 data/videos.json。

用法：
    python scraper.py              # 預設抓最新 40 頁（約 800 篇文章）
    python scraper.py --pages 10   # 只抓 10 頁
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BOARD = "Stock"
BASE = "https://www.ptt.cc"
DATA_DIR = Path(__file__).parent / "data"
VIDEOS_FILE = DATA_DIR / "videos.json"
SEEN_FILE = DATA_DIR / "seen_articles.json"
TW = timezone(timedelta(hours=8))

# 每次請求之間等待幾秒，對 PTT 客氣一點
DELAY = float(os.environ.get("PTT_DELAY", "0.8"))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

YT_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?(?:[^\s\"'<>]*&)?v=|shorts/|live/|embed/)"
    r"|youtube-nocookie\.com/embed/"
    r"|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (compatible; StockTubeBot/1.0)"
session.cookies.set("over18", "1", domain="www.ptt.cc")


# ---------- 工具 ----------

def get(url, **kwargs):
    """帶重試的 GET。"""
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20, **kwargs)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def extract_video_ids(text):
    """從一段文字或 HTML 抓出所有 YouTube 影片 ID（去重、保留順序）。"""
    seen, out = set(), []
    for vid in YT_PATTERN.findall(text or ""):
        if vid not in seen:
            seen.add(vid)
            out.append(vid)
    return out


def parse_nrec(text):
    """PTT 推文數：'爆' 視為 100，'X1'~'XX' 為負數，空白為 0。"""
    text = (text or "").strip()
    if not text:
        return 0
    if text == "爆":
        return 100
    if text.startswith("X"):
        return -10 if text == "XX" else -int(text[1:] or 1) * 10
    try:
        return int(text)
    except ValueError:
        return 0


def parse_category(title):
    m = re.match(r"\s*(?:Re:\s*|Fw:\s*)?\[([^\]]+)\]", title or "")
    return m.group(1).strip() if m else "其他"


def article_time(article_id):
    """文章 ID 形如 M.1730000000.A.123，中間就是發文時間戳。"""
    m = re.match(r"M\.(\d+)\.", article_id)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)), TW)


# ---------- 解析 PTT 頁面 ----------

def parse_index(html):
    """解析看板列表頁，回傳 (文章列表, 上一頁網址)。"""
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    for ent in soup.select("div.r-ent"):
        a = ent.select_one("div.title a")
        if not a:  # 已刪除的文章
            continue
        href = a.get("href", "")
        aid = href.rsplit("/", 1)[-1].replace(".html", "")
        nrec_el = ent.select_one("div.nrec span")
        articles.append({
            "id": aid,
            "url": BASE + href,
            "title": a.get_text(strip=True),
            "nrec": parse_nrec(nrec_el.get_text() if nrec_el else ""),
        })
    prev = None
    for btn in soup.select("div.btn-group-paging a.btn"):
        if "上頁" in btn.get_text() and btn.get("href"):
            prev = BASE + btn["href"]
    return articles, prev


def parse_article(html):
    """解析文章頁，回傳 {'body_ids': [...], 'push_ids': [...]}。"""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#main-content")
    if not main:
        return {"body_ids": [], "push_ids": []}

    push_ids = []
    for push in main.select("div.push"):
        content = push.select_one("span.push-content")
        raw = str(content) if content else ""
        push_ids.extend(extract_video_ids(raw))
        push.decompose()  # 從本文移除，避免重複計算

    body_ids = extract_video_ids(str(main))
    push_ids = [v for v in dict.fromkeys(push_ids) if v not in body_ids]
    return {"body_ids": body_ids, "push_ids": push_ids}


# ---------- 影片資訊 ----------

def fetch_oembed(vid):
    """不需要金鑰的 YouTube oEmbed，可取得標題、頻道。"""
    r = get("https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
    if not r:
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    return {"title": d.get("title", ""), "channel": d.get("author_name", "")}


ISO_DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def fetch_api_details(ids):
    """有設定 YOUTUBE_API_KEY 時，額外取得片長與觀看數。"""
    out = {}
    if not YOUTUBE_API_KEY:
        return out
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = get("https://www.googleapis.com/youtube/v3/videos", params={
            "part": "contentDetails,statistics,snippet",
            "id": ",".join(chunk), "key": YOUTUBE_API_KEY,
        })
        if not r:
            continue
        for item in r.json().get("items", []):
            m = ISO_DUR.match(item["contentDetails"].get("duration", ""))
            secs = 0
            if m:
                h, mi, s = (int(x or 0) for x in m.groups())
                secs = h * 3600 + mi * 60 + s
            out[item["id"]] = {
                "duration": secs,
                "views": int(item.get("statistics", {}).get("viewCount", 0)),
                "published": item["snippet"].get("publishedAt", "")[:10],
            }
    return out


# ---------- 熱門度 ----------

def score(video, now):
    """
    熱門度 = 被多少篇文章提到（本文 3 分、推文 2 分）
           + 文章推文數加權
           + 最近被提到的加分（30 天內逐漸遞減）
    """
    s = 0.0
    for m in video["mentions"]:
        s += 3 if m["where"] == "body" else 2
        s += max(m["nrec"], 0) ** 0.5 / 2
    last = datetime.fromisoformat(video["last_seen"])
    days = max((now - last).total_seconds() / 86400, 0)
    s *= 1 + max(0, 30 - days) / 30
    return round(s, 2)


# ---------- 主流程 ----------

def crawl(pages):
    videos = load_json(VIDEOS_FILE, {})
    seen = set(load_json(SEEN_FILE, []))
    now = datetime.now(TW)

    url = f"{BASE}/bbs/{BOARD}/index.html"
    new_articles = 0
    for page in range(pages):
        r = get(url)
        if not r:
            print(f"列表頁讀取失敗：{url}")
            break
        articles, prev = parse_index(r.text)
        print(f"[{page + 1}/{pages}] {url}：{len(articles)} 篇")
        for art in articles:
            if art["id"] in seen:
                continue
            time.sleep(DELAY)
            ar = get(art["url"])
            if not ar:
                continue
            seen.add(art["id"])
            new_articles += 1
            parsed = parse_article(ar.text)
            posted = article_time(art["id"]) or now
            for where, ids in (("body", parsed["body_ids"]), ("push", parsed["push_ids"])):
                for vid in ids:
                    v = videos.setdefault(vid, {
                        "id": vid, "mentions": [],
                        "first_seen": posted.isoformat(),
                        "last_seen": posted.isoformat(),
                    })
                    if any(m["article"] == art["id"] for m in v["mentions"]):
                        continue
                    v["mentions"].append({
                        "article": art["id"], "url": art["url"],
                        "title": art["title"], "category": parse_category(art["title"]),
                        "nrec": art["nrec"], "where": where,
                        "date": posted.isoformat(),
                    })
                    if posted.isoformat() > v["last_seen"]:
                        v["last_seen"] = posted.isoformat()
                    if posted.isoformat() < v["first_seen"]:
                        v["first_seen"] = posted.isoformat()
        if not prev:
            break
        url = prev
        time.sleep(DELAY)

    print(f"新讀取 {new_articles} 篇文章，累計 {len(videos)} 支影片")

    # 補影片資訊
    missing = [vid for vid, v in videos.items() if "title" not in v]
    for vid in missing:
        info = fetch_oembed(vid)
        time.sleep(0.2)
        if info:
            videos[vid].update(info)
        else:
            videos[vid]["title"] = None  # 影片已下架或私人
    details = fetch_api_details([v for v in videos if videos[v].get("title")])
    for vid, d in details.items():
        videos[vid].update(d)

    for v in videos.values():
        v["score"] = score(v, now)
        cats = [m["category"] for m in v["mentions"]]
        v["category"] = max(set(cats), key=cats.count) if cats else "其他"

    save_json(VIDEOS_FILE, videos)
    save_json(SEEN_FILE, sorted(seen)[-20000:])
    return videos


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=int(os.environ.get("PTT_PAGES", "40")))
    args = p.parse_args()
    crawl(args.pages)
