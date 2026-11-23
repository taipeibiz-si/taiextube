"""
美股Tube：
  1. 從 us_channels.json 列出的 YouTube 頻道 RSS 抓最新影片（免費、不用金鑰）
  2. 再加上 PTT 海外投資板（Foreign_Inv）鄉民推薦的影片（來自 scraper.py 的 data/videos.json）
產生 docs/us.html。

用法：python us.py
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
CONFIG = ROOT / "us_channels.json"
DATA_FILE = ROOT / "data" / "us.json"
CACHE_FILE = ROOT / "data" / "us_channel_ids.json"   # @帳號 → 頻道 ID 的對照，查一次就記起來
PTT_FILE = ROOT / "data" / "videos.json"
TW = timezone(timedelta(hours=8))
KEEP_DAYS = 10          # 頻道影片保留幾天
PER_CHANNEL = 40        # 每個頻道最多保留幾支（Bloomberg 一天上傳上百支，要限制）
PTT_DAYS = 60           # 鄉民推薦保留最近幾天被提到的
CH_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")

try:
    from curl_cffi import requests as http
    session = http.Session(impersonate="chrome")
except ImportError:
    import requests as http
    session = http.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
session.headers["Accept-Language"] = "zh-TW,zh;q=0.9,en;q=0.8"
# 歐洲機房會先跳「同意 Cookie」頁，先帶上同意
session.cookies.set("SOCS", "CAI", domain=".youtube.com")

# 簡體標題轉台灣繁體（有裝 opencc 才會轉，沒裝就維持原文）
try:
    from opencc import OpenCC
    _cc = OpenCC("s2twp")
    FIX = {"英偉達": "輝達", "臺積電": "台積電", "臺灣": "台灣", "美聯儲": "聯準會"}

    def to_tw(s):
        s = _cc.convert(s)
        for a, b in FIX.items():
            s = s.replace(a, b)
        return s
except Exception:  # 沒裝或載入失敗
    to_tw = lambda s: s


def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            msg = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return None
        except Exception as e:  # 連線錯誤
            msg = f"{type(e).__name__}: {str(e)[:100]}"
        print(f"  第 {i + 1} 次失敗：{msg}")
        time.sleep(2 + i * 3)
    return None


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def resolve(ch, cache):
    """
    設定檔三種寫法擇一：
      id：UC 開頭的頻道 ID（最準）
      handle：頻道網址 youtube.com/@ 後面那段
      search：頻道名稱，用 YouTube 搜尋找第一個頻道
    查到的 ID 會記在 data/us_channel_ids.json，下次不用再查。
    """
    if ch.get("id"):
        return ch["id"]
    handle = ch.get("handle", "").strip()
    query = ch.get("search", "").strip()
    key = ("@" + handle.lstrip("@")) if handle else ("search:" + query if query else "")
    if not key:
        return None
    if key in cache:
        return cache[key]
    if handle:
        page = fetch(f"https://www.youtube.com/{key}", tries=2)
        pats = (r'"externalId":"(UC[A-Za-z0-9_-]{22})"',
                r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"',
                r'"channelId":"(UC[A-Za-z0-9_-]{22})"')
    else:
        # sp=EgIQAg%3D%3D：只搜尋「頻道」
        page = fetch("https://www.youtube.com/results?sp=EgIQAg%3D%3D&search_query="
                     + quote(query), tries=2)
        pats = (r'"channelRenderer":\{"channelId":"(UC[A-Za-z0-9_-]{22})"',
                r'"channelId":"(UC[A-Za-z0-9_-]{22})"')
    if page:
        for pat in pats:
            m = re.search(pat, page)
            if m:
                cache[key] = m.group(1)
                print(f"  {key} → {m.group(1)}")
                return m.group(1)
    print(f"  找不到「{handle or query}」的頻道，請到 us_channels.json 檢查，或直接填 id")
    return None


def ns(tag):
    return tag.rsplit("}", 1)[-1]


def find(el, name):
    for c in el.iter():
        if ns(c.tag) == name:
            return c
    return None


def parse_feed(xml_text):
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as e:
        print(f"  RSS 格式錯誤：{e}")
        return []
    out = []
    for entry in root:
        if ns(entry.tag) != "entry":
            continue
        vid = find(entry, "videoId")
        link = find(entry, "link")
        title = find(entry, "title")
        pub = find(entry, "published")
        stats = find(entry, "statistics")
        if vid is None or not vid.text:
            continue
        href = link.get("href", "") if link is not None else ""
        if "/shorts/" in href:          # 跳過 Shorts 短影音
            continue
        out.append({
            "id": vid.text.strip(),
            "title": (title.text or "").strip() if title is not None else "",
            "published": (pub.text or "").strip() if pub is not None else "",
            "views": int(stats.get("views", 0)) if stats is not None else 0,
        })
    return out


def main():
    cfg = load(CONFIG, {"channels": []})
    cache = load(CACHE_FILE, {})
    old = {v["id"]: v for v in load(DATA_FILE, [])}
    now = datetime.now(TW)
    cutoff = now - timedelta(days=KEEP_DAYS)

    videos = {}
    ok = 0
    for ch in cfg["channels"]:
        name, lang = ch.get("name", ""), ch.get("lang", "中文")
        print(f"[{lang}] {name}")
        cid = resolve(ch, cache)
        if not cid:
            continue
        xml_text = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        if not xml_text:
            print("  讀取失敗（先保留上次的影片）")
            continue
        items = parse_feed(xml_text)
        ok += 1
        m = re.search(r"<author>\s*<name>([^<]*)</name>", xml_text)
        print(f"  {len(items)} 支（YouTube 上的頻道名稱：{m.group(1) if m else '?'}）")
        for it in items:
            try:
                pub = datetime.fromisoformat(it["published"].replace("Z", "+00:00")).astimezone(TW)
            except ValueError:
                continue
            if pub < cutoff:
                continue
            title = to_tw(it["title"]) if lang == "中文" else it["title"]
            videos[it["id"]] = {
                "id": it["id"], "title": title, "channel": name, "lang": lang,
                "published": pub.isoformat(timespec="minutes"), "views": it["views"],
                "ptt": [],
            }

    # 這次沒抓到的頻道，沿用上次的資料，避免 YouTube 偶爾出錯就整個不見
    for vid, v in old.items():
        if vid in videos or v.get("lang") == "鄉民":
            continue
        try:
            if datetime.fromisoformat(v["published"]) >= cutoff:
                videos[vid] = {**v, "ptt": []}
        except (KeyError, ValueError):
            pass

    # 每個頻道只留最新的幾支
    by_ch = {}
    for v in sorted(videos.values(), key=lambda v: v["published"], reverse=True):
        by_ch.setdefault(v["channel"], []).append(v)
    videos = {v["id"]: v for lst in by_ch.values() for v in lst[:PER_CHANNEL]}

    # PTT 海外投資板鄉民推薦
    ptt_cut = (now - timedelta(days=PTT_DAYS)).isoformat()
    ptt_count = 0
    for vid, pv in load(PTT_FILE, {}).items():
        if not pv.get("title"):
            continue
        ms = [m for m in pv.get("mentions", []) if m.get("board") == "Foreign_Inv"]
        if not ms:
            continue
        last = max(m["date"] for m in ms)
        if last < ptt_cut:
            continue
        ptt_count += 1
        mentions = [{"title": m["title"], "url": m["url"], "nrec": m["nrec"]}
                    for m in sorted(ms, key=lambda m: m["date"])]
        if vid in videos:
            videos[vid]["ptt"] = mentions
        else:
            videos[vid] = {
                "id": vid, "title": pv["title"], "channel": pv.get("channel", ""),
                "lang": "鄉民",
                "published": datetime.fromisoformat(last).astimezone(TW).isoformat(timespec="minutes"), "views": 0, "ptt": mentions,
            }

    items = sorted(videos.values(), key=lambda v: v["published"], reverse=True)
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    data = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "us_template.html").read_text(encoding="utf-8")
    page = page.replace("__DATA__", data).replace("__UPDATED__", now.strftime("%Y/%m/%d %H:%M"))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "us.html").write_text(page, encoding="utf-8")
    print(f"成功讀取 {ok}/{len(cfg['channels'])} 個頻道，共 {len(items)} 支影片"
          f"（其中鄉民推薦 {ptt_count} 支），已產生 docs/us.html")


if __name__ == "__main__":
    main()
