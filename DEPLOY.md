# Pikmin Bloom Radar Bot — 部署指南

> **環境：** DigitalOcean WordPress Marketplace Droplet（Ubuntu 22.04 + Nginx）  
> **目標：** 在不影響 WordPress 的前提下，以 Docker 運行 LINE Bot

---

## 前置確認清單

在開始之前，請先備好以下資訊：

- [ ] Droplet 的 IP 位址（DigitalOcean 控制台 → 你的 Droplet → 上方的數字）
- [ ] 你的網域名稱（例如 `example.com`）
- [ ] GitHub Repo URL（例如 `https://github.com/你的帳號/pikmin-bloom-radar.git`）
- [ ] LINE Channel Secret（LINE Developers Console → 你的 Channel → Basic settings）
- [ ] LINE Channel Access Token（同上頁面 → Messaging API → Issue）

---

## Step 1：SSH 連線到 Droplet

在你的電腦（Mac / Windows PowerShell）開啟終端機：

```bash
ssh root@你的Droplet_IP
# 例如：ssh root@123.45.67.89
```

第一次連線會問是否信任，輸入 `yes`。

> **DigitalOcean Web Console 用戶：** 直接在瀏覽器控制台操作即可，不需要本地終端機。

---

## Step 2：安裝 Docker 與 Git

登入後，在 Droplet 上執行：

```bash
# 更新套件清單
apt update

# 安裝 Git（通常已預裝，確認一下）
git --version

# 安裝 Docker（一行指令）
curl -fsSL https://get.docker.com | sh

# 驗證安裝成功
docker --version
# 應看到：Docker version 24.x.x ...
```

---

## Step 3：Clone 專案到 Droplet

```bash
# Clone 你的 GitHub Repo
git clone https://github.com/你的帳號/pikmin-bloom-radar.git /opt/pikmin

# 進入專案目錄
cd /opt/pikmin

# 確認檔案都在
ls
# 應看到：main.py  mapping.py  osm_service.py  Dockerfile ...
```

> **注意：** 如果你的 Repo 是 **Private**，git clone 時會要求輸入 GitHub 帳號密碼。  
> 建議使用 **Personal Access Token**（PAT）代替密碼：  
> GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token（勾選 `repo` 權限）

---

## Step 4：建立 .env 檔案

`.env` 不會在 GitHub 上，需要在 Droplet 手動建立：

```bash
cd /opt/pikmin

# 複製範本並編輯
cp .env.example .env
nano .env
```

在編輯器中，將以下兩行改成你的真實金鑰：

```
LINE_CHANNEL_SECRET=貼上你的_Channel_Secret
LINE_CHANNEL_ACCESS_TOKEN=貼上你的_Access_Token
```

儲存：按 `Ctrl+X` → `Y` → `Enter`

---

## Step 5：建立並啟動 Docker Container

```bash
cd /opt/pikmin

# 建立 Docker Image（約需 1-2 分鐘）
docker build -t pikmin-bot .

# 啟動 Container（背景執行，自動重啟）
docker run -d \
  --name pikmin-bot \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  pikmin-bot

# 驗證 Container 正在運行
docker ps
# 應看到 pikmin-bot 狀態為 Up

# 查看啟動日誌
docker logs pikmin-bot
# 應看到：Pikmin Bloom Radar Bot v2.0 啟動中...
```

> **注意：** `-p 127.0.0.1:8000:8000` 讓 Port 8000 只對本機開放，
> 外部流量統一走 Nginx（更安全）。

---

## Step 6：設定 Nginx 反向代理

找到你的 Nginx WordPress 設定檔：

```bash
# DigitalOcean WordPress 通常在這個位置
ls /etc/nginx/sites-enabled/
```

編輯設定檔：

```bash
nano /etc/nginx/sites-enabled/wordpress
```

在 `server { ... }` 區塊內，找到類似 `location / { ... }` 的段落，
在它**之前**（同層級）新增以下內容：

```nginx
location /pikmin/ {
    proxy_pass         http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
    proxy_buffering    off;
}
```

測試設定是否正確並重新載入：

```bash
nginx -t
# 應看到：syntax is ok / test is successful

systemctl reload nginx
```

---

## Step 7：測試 Bot 是否正常運行

```bash
# 測試健康檢查端點
curl https://你的網域/pikmin/health

# 應回傳：{"status":"healthy","service":"pikmin-bloom-radar","version":"2.0.0"}
```

---

## Step 8：設定 LINE Webhook

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. 選擇你的 Provider → 你的 Channel → **Messaging API**
3. 找到 **Webhook URL**，填入：
   ```
   https://你的網域/pikmin/callback
   ```
4. 開啟 **Use webhook**
5. 點選 **Verify** — 應顯示 Success

---

## 日常維護指令

```bash
# 查看 Bot 即時日誌
docker logs -f pikmin-bot

# 重啟 Bot
docker restart pikmin-bot

# 從 GitHub 拉取最新程式碼並重新部署
cd /opt/pikmin
git pull
docker stop pikmin-bot && docker rm pikmin-bot
docker build -t pikmin-bot .
docker run -d --name pikmin-bot --restart unless-stopped --env-file .env -p 127.0.0.1:8000:8000 pikmin-bot

# 停止 Bot
docker stop pikmin-bot
```

---

## 常見問題

**Q：`docker logs` 看到 `LINE 簽章驗證失敗`**  
A：確認 .env 中的 `LINE_CHANNEL_SECRET` 正確，且 Nginx 有轉發 `X-Line-Signature` header。

**Q：Nginx `nginx -t` 失敗**  
A：確認 location block 縮排正確，且在 `server { }` 內部。

**Q：`curl health` 回傳 502 Bad Gateway**  
A：Bot Container 可能未啟動，執行 `docker ps` 確認，並用 `docker logs pikmin-bot` 查看錯誤。

**Q：LINE Verify 顯示失敗**  
A：確認 Webhook URL 使用 https，且網域 SSL 憑證有效。

**Q：git clone 私有 Repo 要求輸入密碼**  
A：GitHub 已停用帳號密碼驗證，請改用 Personal Access Token（PAT）作為密碼。
