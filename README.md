# 🌱 Pikmin Bloom Radar — LINE Bot

查詢你附近可能出現哪些**皮克敏飾品（Decor Pikmin）**的 LINE Bot。  
傳送位置給 Bot，它會即時查詢 OpenStreetMap 數據，回傳 500 公尺內的設施類型。

---

## 功能

### 📍 即時模式（預設）
直接在 LINE 分享位置，Bot 立即回傳附近可能出現的飾品種類：

```
📍 座標：台北 101
附近可能發現的飾品：
- ☕ 咖啡廳
- 🍽️ 餐廳
- 🚆 車站
```

### 📡 戰略掃描模式
輸入 `scan` 再分享位置，Bot 掃描 1000 公尺範圍並統計各設施數量。  
選擇目標飾品後，Bot 執行純度演算法，推薦最高機率的精確座標並附上 Google Maps 導航連結。

---

## 支援的飾品種類

| 飾品 | OSM 標籤 |
|------|----------|
| 🍽️ 餐廳 | `amenity=restaurant` |
| ☕ 咖啡廳 | `amenity=cafe` |
| 🍰 甜點店 | `shop=pastry` / `shop=confectionery` |
| 🎬 電影院 | `amenity=cinema` |
| 💊 藥妝店 | `shop=chemist` / `shop=drugstore` |
| 🦁 動物園 | `tourism=zoo` |
| 🌳 森林 | `natural=wood` / `landuse=forest` |
| 💧 水邊 | `natural=water` / `natural=coastline` |
| 📮 郵局 | `amenity=post_office` |
| 🖼️ 美術館 | `tourism=gallery` |
| ✈️ 機場 | `aeroway=terminal` / `aeroway=aerodrome` |
| 🚆 車站 | `railway=station` |

---

## 技術架構

- **Backend:** Python 3.10+ / FastAPI（非同步）
- **LINE SDK:** `line-bot-sdk` v3
- **地圖資料:** OpenStreetMap via Overpass API
- **部署:** Docker + Nginx 反向代理
- **狀態管理:** TTLCache（5 分鐘 TTL）

---

## 本地測試

不需要 LINE 憑證，只需 `httpx`：

```bash
pip install httpx

# 即時模式測試
python test_query.py 25.0330 121.5654

# 戰略掃描測試（互動式選單）
python test_scan.py 25.0330 121.5654 --title "台北 101"
```

---

## 部署

詳細步驟請參考 [DEPLOY.md](DEPLOY.md)。

簡要流程（DigitalOcean Droplet）：

```bash
# 1. Clone 專案
git clone https://github.com/kevincylee1127/ShitakeCo.git /opt/pikmin
cd /opt/pikmin

# 2. 建立 .env
cp .env.example .env
nano .env  # 填入 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN

# 3. 啟動 Docker
docker build -t pikmin-bot .
docker run -d --name pikmin-bot --restart unless-stopped \
  --env-file .env -p 127.0.0.1:8000:8000 pikmin-bot
```

Nginx Webhook 路徑：`https://你的網域/pikmin/callback`

---

## 環境變數

複製 `.env.example` 並填入真實值：

```env
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
OVERPASS_URL=https://overpass-api.de/api/interpreter
SEARCH_RADIUS_M=500
```

---

## 檔案結構

```
├── main.py           # FastAPI Webhook 入口
├── osm_service.py    # Overpass API 查詢服務
├── analyzer.py       # 戰略掃描純度演算法
├── mapping.py        # OSM Tags ↔ 皮克敏飾品對照表
├── cache_service.py  # 使用者狀態暫存
├── config.py         # 環境變數設定
├── Dockerfile
├── requirements.txt
├── .env.example
├── test_query.py     # 本地即時模式測試
├── test_scan.py      # 本地戰略掃描測試
└── DEPLOY.md         # 完整部署指南
```
