"""
把 data/videos.json 變成網站 docs/index.html。
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
TW = timezone(timedelta(hours=8))
MAX_VIDEOS = 1500  # 網頁最多放幾支，避免檔案太大


def build():
    src = ROOT / "data" / "videos.json"
    videos = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}

    items = []
    for v in videos.values():
        if not v.get("title"):  # 已下架、私人影片
            continue
        items.append({
            "id": v["id"],
            "title": v["title"],
            "channel": v.get("channel", ""),
            "category": v.get("category", "其他"),
            "score": v.get("score", 0),
            "duration": v.get("duration", 0),
            "last_seen": v.get("last_seen", ""),
            "mentions": [
                {"title": m["title"], "url": m["url"], "nrec": m["nrec"]}
                for m in sorted(v["mentions"], key=lambda m: m["date"])
            ],
        })
    items.sort(key=lambda v: v["score"], reverse=True)
    items = items[:MAX_VIDEOS]

    data = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")  # 避免標題裡的 </script> 弄壞網頁
    updated = datetime.now(TW).strftime("%Y/%m/%d %H:%M")

    html = (ROOT / "template.html").read_text(encoding="utf-8")
    html = html.replace("__DATA__", data).replace("__UPDATED__", updated)

    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("")
    print(f"已產生網站：{out}（{len(items)} 支影片）")


if __name__ == "__main__":
    build()
