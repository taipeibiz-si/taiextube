# 台股Tube

PTT 股票板鄉民一直互相推薦的 YouTube 影片，自動整理成一個網站。

- 每天自動抓 PTT 股票板（Stock）**文章和推文**裡分享的 YouTube 連結
- 依照「被幾篇文章提到、文章推文數、最近有沒有人提」計算熱門度
- 網站有：熱門／最新／長片排行、分類（心得、標的、新聞…）、搜尋、稍後觀看、已看過、內嵌播放，還能直接點進去看「鄉民怎麼說」
- 全部用 GitHub 免費服務架設，**不用租伺服器、不用花錢**

> 本站只整理鄉民分享的影片，不構成任何投資建議。

---

## 架設步驟（約 10 分鐘，不需要會寫程式）

### 1. 建立 GitHub 帳號與儲存庫
1. 到 <https://github.com> 註冊帳號（已有就登入）
2. 右上角「＋」→ **New repository**
3. Repository name 填 `stocktube`（或你喜歡的名字），選 **Public**，按 **Create repository**

### 2. 上傳檔案
1. 在新儲存庫頁面點 **uploading an existing file**
2. 把壓縮檔解開後的**所有檔案和資料夾**拖進去（包含 `.github` 資料夾）
   - 如果看不到 `.github` 資料夾，是因為它是隱藏資料夾：Mac 在 Finder 按 `Command + Shift + .` 就會顯示
3. 按 **Commit changes**

> 小提醒：網頁上傳有時候會漏掉 `.github` 資料夾。上傳後確認儲存庫裡有 `.github/workflows/update.yml`，沒有的話，點 **Add file → Create new file**，檔名打 `.github/workflows/update.yml`，把檔案內容貼進去存檔。

### 3. 允許自動更新寫入
**Settings → Actions → General**，拉到最下面 **Workflow permissions**，選 **Read and write permissions**，按 **Save**。

### 4. 開啟網站
**Settings → Pages**：
- Source 選 **Deploy from a branch**
- Branch 選 **main**，資料夾選 **/docs**，按 **Save**

### 5. 第一次更新
1. 點上方 **Actions** 分頁（如果有提示，按 **I understand my workflows, go ahead and enable them**）
2. 左邊點 **更新台股Tube** → 右邊 **Run workflow** → **Run workflow**
3. 等它變成綠色勾勾（第一次大約 10～20 分鐘）
4. 打開網站：`https://你的帳號.github.io/stocktube/`

之後每天台灣時間 **07:17、13:17、19:17** 會自動更新，不用再管它。

---

## 進階設定（可以不做）

### 顯示片長、開啟「長片」分頁
沒設定時，網站從 YouTube 免費取得標題和頻道，但拿不到片長。想要片長：
1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案，啟用 **YouTube Data API v3**，建立一組 **API 金鑰**
2. GitHub 儲存庫 **Settings → Secrets and variables → Actions → New repository secret**
3. Name 填 `YOUTUBE_API_KEY`，Secret 貼上金鑰，存檔

下次更新後，影片會顯示片長，也會出現「⏳ 長片」分頁（20 分鐘以上的影片）。

### 調整抓取範圍與頻率
編輯 `.github/workflows/update.yml`：
- `PTT_PAGES: "40"`：每次往回看幾頁（一頁約 20 篇）。已經讀過的文章不會重抓，所以 40 頁就夠了
- `cron`：更新時間，用的是 UTC 時間（台灣時間減 8 小時）

### 換成別的看板
把 `scraper.py` 裡的 `BOARD = "Stock"` 改成其他看板名稱，例如 `"Fund"`、`"Option"`。

---

## 檔案說明
| 檔案 | 用途 |
|---|---|
| `scraper.py` | 抓 PTT 文章與推文，整理影片，存到 `data/videos.json` |
| `build_site.py` | 把資料變成網站 `docs/index.html` |
| `template.html` | 網站的版面 |
| `.github/workflows/update.yml` | 自動更新的排程 |
| `tests/test_scraper.py` | 用模擬的 PTT 頁面測試爬蟲 |

## 在自己電腦上跑（選擇性）
```bash
pip install -r requirements.txt
python scraper.py --pages 5
python build_site.py
# 用瀏覽器打開 docs/index.html
```

## 常見問題
- **Actions 出現紅色叉叉？** 點進去看錯誤訊息。最常見是第 3 步沒設定成 Read and write。
- **網站打不開？** 確認第 4 步選的是 `/docs` 資料夾，而且 Actions 至少成功跑過一次。
- **熱門度怎麼算？** 每篇提到的文章：本文 3 分、推文 2 分，再加上文章推文數的加權；最近 30 天內被提到的會加分，越新越多。
- **對 PTT 會不會造成負擔？** 每次請求間隔 0.8 秒，而且讀過的文章不會重抓，一天只更新三次，負擔很小。
