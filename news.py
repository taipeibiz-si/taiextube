"""
台股新聞牆：從 feeds.json 列出的 RSS 抓新聞與部落格標題，產生 docs/news.html。
只保存標題、連結、來源和時間，不轉貼文章內容。

用法：python news.py
"""

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "news.json"
TW = timezone(timedelta(hours=8))
KEEP_DAYS = {"新聞": 3, "部落格": 14}  # 各欄保留最近幾天
EXCLUDE_SOURCES = ["Facebook", "Instagram", "YouTube", "Threads", "TikTok"]  # 不是文章的來源
MAX_ITEMS = 800      # 每一欄最多幾則

try:
    from curl_cffi import requests as http
    session = http.Session(impersonate="chrome")
except ImportError:
    import requests as http
    session = http.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; TaiexTubeNews/1.0)"


def fetch(url):
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            return r.content
        print(f"  HTTP {r.status_code}")
    except Exception as e:  # 連線錯誤
        print(f"  {type(e).__name__}: {str(e)[:120]}")
    return None


def strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def child(el, name):
    for c in el:
        if strip_ns(c.tag) == name:
            return c
    return None


def text_of(el, name):
    c = child(el, name)
    return (c.text or "").strip() if c is not None and c.text else ""


def parse_time(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)  # RSS：Tue, 18 Nov 2026 08:00:00 GMT
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))  # Atom：2026-11-18T08:00:00Z
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TW)


def clean_title(t):
    t = html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()
    return re.sub(r"\s+", " ", t)


BAD_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def sanitize(raw):
    """很多部落格的 RSS 不太標準（夾雜控制字元、&nbsp; 之類的 HTML 符號），先清乾淨。"""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = BAD_CHARS.sub("", text)
    text = BARE_AMP.sub("&amp;", text)
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text)  # 已經轉成文字，拿掉編碼宣告


def parse_feed(raw, feed):
    """支援 RSS 2.0 和 Atom，回傳 [{title, link, source, time}]。"""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(sanitize(raw))
            print("  （格式不標準，已自動修正）")
        except ET.ParseError as e:
            print(f"  格式錯誤：{e}")
            return []
    items = []
    nodes = [n for n in root.iter() if strip_ns(n.tag) in ("item", "entry")]
    for n in nodes:
        title = clean_title(text_of(n, "title"))
        link = text_of(n, "link")
        if not link:  # Atom 的連結放在屬性
            for c in n:
                if strip_ns(c.tag) == "link" and c.get("rel", "alternate") == "alternate":
                    link = c.get("href", "")
                    break
        when = parse_time(text_of(n, "pubDate") or text_of(n, "published")
                          or text_of(n, "updated") or text_of(n, "date"))
        source = feed["name"]
        src_el = child(n, "source")  # Google 新聞會附上原始媒體名稱
        if src_el is not None and (src_el.text or "").strip():
            source = src_el.text.strip()
            if title.endswith(" - " + source):
                title = title[: -len(source) - 3].strip()
        if any(x.lower() in source.lower() for x in EXCLUDE_SOURCES):
            continue
        if title and link and when:
            items.append({"title": title, "link": link, "source": source,
                          "tag": feed.get("tag", ""), "time": when.isoformat()})
    return items


def normalize(title):
    return re.sub(r"[\s\W_]+", "", title).lower()


def collect(kind, feeds, old, exclude_words=()):
    now = datetime.now(TW)
    cutoff = now - timedelta(days=KEEP_DAYS.get(kind, 3))
    merged = {it["link"]: it for it in old}
    for feed in feeds:
        print(f"[{kind}] {feed['name']}")
        raw = fetch(feed["url"])
        if raw is None:
            print("  讀取失敗")
            continue
        got = parse_feed(raw, feed)
        print(f"  取得 {len(got)} 則")
        for it in got:
            merged.setdefault(it["link"], it)
    # 去掉太舊的、時間在未來的、標題重複的（不同媒體轉載同一篇）
    out, seen_titles = [], set()
    for it in sorted(merged.values(), key=lambda x: x["time"], reverse=True):
        t = datetime.fromisoformat(it["time"])
        if t < cutoff or t > now + timedelta(hours=1):
            continue
        if any(w in it["title"] for w in exclude_words):  # 例如選舉新聞
            continue
        key = normalize(it["title"])
        if key in seen_titles:
            continue
        seen_titles.add(key)
        out.append(it)
    return out[:MAX_ITEMS]


def main():
    feeds = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
    old = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    data = {
        "news": collect("新聞", feeds.get("news", []), old.get("news", []),
                        feeds.get("news_exclude", [])),
        "blogs": collect("部落格", feeds.get("blogs", []), old.get("blogs", []),
                         feeds.get("blogs_exclude", [])),
    }
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "news_template.html").read_text(encoding="utf-8")
    page = page.replace("__DATA__", payload).replace(
        "__UPDATED__", datetime.now(TW).strftime("%Y/%m/%d %H:%M"))
    out = ROOT / "docs" / "news.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"已產生 {out}：新聞 {len(data['news'])} 則、部落格 {len(data['blogs'])} 則")


if __name__ == "__main__":
    main()
