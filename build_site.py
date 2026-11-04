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

    template = (ROOT / "template.html").read_text(encoding="utf-8")
    pages = {
        # 全部影片：docs/index.html
        "index.html": {"__TITLE__": "台股Tube", "__BADGE__": "", "__FIN_ONLY__": "false",
                       "__SWITCH_URL__": "./finance.html", "__SWITCH_LABEL__": "💹 財經版"},
        # 只看財經：docs/finance.html
        "finance.html": {"__TITLE__": "台股Tube 財經版", "__BADGE__": "<small>財經版</small>",
                         "__FIN_ONLY__": "true",
                         "__SWITCH_URL__": "./", "__SWITCH_LABEL__": "🎬 看全部影片"},
    }
    (ROOT / "docs").mkdir(exist_ok=True)
    for name, values in pages.items():
        html = template.replace("__DATA__", data).replace("__UPDATED__", updated)
        for k, v in values.items():
            html = html.replace(k, v)
        (ROOT / "docs" / name).write_text(html, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("")
    print(f"已產生網站：index.html、finance.html（共 {len(items)} 支影片）")


if __name__ == "__main__":
    build()
