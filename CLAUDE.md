# CLAUDE.md — Pikmin Bloom Radar LINE Bot

## 專案背景與目標

在已運行 WordPress 的 DigitalOcean Droplet 上，部署一個基於 Python 的 LINE Bot。  
當使用者在 LINE 發送「位置分享」時，Bot 會查詢 OpenStreetMap (OSM) 數據，回傳周邊 500 公尺內可能出現的皮克敏飾品（Decor Pikmin）種類。
**v2.0 新增功能：** Strategic Scan (戰略掃描)，透過兩階段互動協助使用者精確定位高機率獲取點。

---

## 技術架構

- **Backend:** Python 3.10+，使用 FastAPI（高併發非同步處理）
- **Deployment:** Docker 容器化，與主機 WordPress 環境隔離
- **Networking:**
  - 外部流量經由主機 Nginx（Port 443）反向代理至 Container（Port 8000）
  - Webhook URL 路徑：`/pikmin/callback`
- **Data Source:** Overpass API（OpenStreetMap）
- **State Management:** 使用 Redis (或 Python 內建 TTLCache) 暫存戰略掃描結果。

---

## 程式檔案結構

| 檔案 | 功能說明 |
|---|---|
| `main.py` | FastAPI 入口，處理 LINE Webhook 簽章驗證、訊息解析與 Postback 事件 |
| `osm_service.py` | 封裝 Overpass API 請求邏輯，包含錯誤處理（Timeout/Retry），支援動態半徑設定與錯誤處理 |
| `analyzer.py` | **(新增)** 實作「戰略掃描」的標籤純度演算法 |
| `cache_service.py` | **(新增)** 管理暫存數據，優化兩階段查詢效能 |
| `mapping.py` | 獨立字典檔，定義 OSM Tags 與皮克敏飾品名稱的對應 |
| `config.py` | 使用 `pydantic-settings` 讀取 `.env` |
| `Dockerfile` | 使用 `python:3.10-slim` 作為基底 |
| `nginx_proxy.conf` | 提供給使用者參考的 Nginx Location 設定範例 |

---

## 核心功能需求

### 模式一：即時單點模式 (Instant Mode - 預設)
- **觸發機制：** 使用者直接發送 LINE 「位置訊息」。
- **行為：** 提取 `latitude`、`longitude`，查詢周邊 **500m** 內設施，去重後回傳文字清單。

### 模式二：戰略掃描模式 (Strategic Scan - 高級功能)
- **第一階段：區域摘要 (Area Summary)**
  - 使用者輸入 `Scan` 並發送位置後，查詢周邊 **1000m** 數據。
  - 使用 LINE **Quick Reply** 顯示飾品種類統計（如：🎨 美術館 x3, 🍣 壽司店 x1）。
- **第二階段：精確定位 (Targeting)**
  - 使用者點選特定種類後，執行 **純度演算法 (Purity Algorithm)**：
    $$P = \frac{\text{目標標籤數量}}{\text{50m 內總標籤數}}$$
  - 推薦 $P$ 值最高（最純淨）的座標，並回傳 Google Maps 導航連結。

---

## 開發與部署規範

- **非同步處理：** 使用 `httpx` 進行 Overpass API 請求，避免阻塞。
- **錯誤處理：** 需處理 API Timeout 與 LINE 簽章驗證失敗。
- **回覆格式：** 
  - 單點模式使用 `TextMessage`。
  - 掃描模式使用 `Quick Reply` 或 `Flex Message` 以利互動。
- **環境變數：** `LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN` 透過 `.env` 讀取。
- **Nginx 配置：** 確保轉發 `X-Line-Signature` 標頭以供驗證。

---

## 部署環境說明

- 主機已有 WordPress 運行，Bot 以 Docker 獨立運作避免衝突
- Nginx 負責 SSL 終止與反向代理（Port 443 → Container Port 8000）
- LINE Webhook 需設定為 `https://<your-domain>/pikmin/callback`
