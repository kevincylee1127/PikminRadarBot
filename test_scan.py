"""
test_scan.py - 戰略掃描本地測試腳本

模擬完整的兩階段 Strategic Scan 流程，不需要 LINE SDK 或 .env。

依賴：
  pip install httpx

執行方式：
  # 互動模式
  python test_scan.py

  # 直接帶座標
  python test_scan.py 25.0339 121.5619

  # 指定半徑
  python test_scan.py 25.0339 121.5619 --radius 1000
"""

import argparse
import asyncio
import sys

import httpx

# 直接 import 正式模組（不需要 config.py / LINE SDK）
from analyzer import find_best_location, google_maps_url, summarize_pikmin_counts
from mapping import PIKMIN_RULES

# ── Overpass 設定 ──────────────────────────────────────────────────────────────

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

HEADERS = {
    "User-Agent": "PikminBloomRadar/1.0 (local-scan-test)",
    "Accept": "application/json",
}


# ── Overpass QL（scan 模式，含座標）──────────────────────────────────────────────

def build_scan_query(lat, lon, radius):
    c = "{},{}".format(lat, lon)
    r = radius
    pairs = [
        ("amenity", "restaurant"),
        ("amenity", "cafe"),
        ("shop",    "pastry"),
        ("shop",    "confectionery"),
        ("amenity", "cinema"),
        ("shop",    "chemist"),
        ("shop",    "drugstore"),
        ("tourism", "zoo"),
        ("natural", "wood"),
        ("landuse", "forest"),
        ("natural", "water"),
        ("natural", "coastline"),
        ("amenity", "post_office"),
        ("tourism", "gallery"),
        ("aeroway", "terminal"),
        ("aeroway", "aerodrome"),
        ("railway", "station"),
    ]
    lines = []
    for key, val in pairs:
        tag = '["{}"="{}"]'.format(key, val)
        lines.append('node{}(around:{},{});'.format(tag, r, c))
        lines.append('way{}(around:{},{});'.format(tag, r, c))
        if key in ("tourism", "natural", "landuse", "aeroway"):
            lines.append('relation{}(around:{},{});'.format(tag, r, c))

    return "[out:json][timeout:40];\n(\n  {}\n);\nout center tags;".format(
        "\n  ".join(lines)
    )


# ── HTTP 查詢 ──────────────────────────────────────────────────────────────────

async def fetch_scan_elements(lat, lon, radius):
    query = build_scan_query(lat, lon, radius)
    print("  正在查詢 Overpass API（半徑 {}m，含座標）...".format(radius), flush=True)

    last_err = None
    async with httpx.AsyncClient(timeout=40.0, headers=HEADERS) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                resp = await client.get(endpoint, params={"data": query})
                resp.raise_for_status()
                data = resp.json()
                if endpoint != OVERPASS_ENDPOINTS[0]:
                    print("  (備用鏡像: {})".format(endpoint))
                return data.get("elements", [])
            except httpx.HTTPStatusError as e:
                print("  ⚠️  {} 回傳 {}，切換備用...".format(endpoint, e.response.status_code))
                last_err = e
            except httpx.TimeoutException:
                print("  ⚠️  {} 逾時，切換備用...".format(endpoint))
                last_err = Exception("timeout")

    raise last_err or Exception("all endpoints failed")


# ── 主流程 ─────────────────────────────────────────────────────────────────────

async def run(lat, lon, radius, title):
    print()
    print("=" * 50)
    print("📡 戰略掃描模式")
    print("=" * 50)
    print("地點：{}".format(title))
    print("座標：{}, {}　掃描半徑：{}m".format(lat, lon, radius))
    print("-" * 50)

    # ── 第一階段：取得元素 ──
    try:
        elements = await fetch_scan_elements(lat, lon, radius)
    except Exception as e:
        print("❌ 掃描失敗：{}".format(e))
        return

    print("  ✅ 取得 {} 個 OSM 元素".format(len(elements)))

    # 統計各飾品種類數量（含重複）
    pikmin_counts = summarize_pikmin_counts(elements)

    if not pikmin_counts:
        print("\n掃描完成，{}m 內未找到特殊設施 🌿".format(radius))
        return

    # ── 顯示掃描結果（模擬 Quick Reply）──
    print()
    print("📊 掃描結果（{}m 內飾品統計）：".format(radius))
    print("-" * 50)

    # 依數量降序排列
    sorted_items = sorted(pikmin_counts.items(), key=lambda x: x[1], reverse=True)
    for idx, (name, count) in enumerate(sorted_items, start=1):
        bar = "█" * min(count, 20)
        print("  [{:2d}] {} x{}  {}".format(idx, name, count, bar))

    print()

    # ── 選擇飾品種類 ──
    print("請輸入編號選擇想前往的飾品種類（q 退出）：", end=" ")
    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n結束")
        return

    if choice.lower() == "q":
        print("結束")
        return

    try:
        idx = int(choice)
        if not (1 <= idx <= len(sorted_items)):
            print("❌ 無效編號")
            return
        target_pikmin, target_count = sorted_items[idx - 1]
    except ValueError:
        print("❌ 請輸入數字")
        return

    print()
    print("🔍 正在對「{}」執行純度演算法...".format(target_pikmin))

    # ── 第二階段：純度演算法 ──
    result = find_best_location(elements, target_pikmin, purity_radius_m=50.0)

    print()
    print("=" * 50)

    if result is None:
        print("⚠️  找不到含座標的候選點（元素可能為 way/relation 且無 center 資料）")
        print("   建議：縮小範圍後重新掃描，或直接前往附近區域")
        return

    best_lat, best_lon, purity = result
    maps_url = google_maps_url(best_lat, best_lon)

    print("🎯 最佳獲取點")
    print("-" * 50)
    print("目標飾品：{}（共 {} 個設施）".format(target_pikmin, target_count))
    print("最佳座標：{:.6f}, {:.6f}".format(best_lat, best_lon))
    print("純度分數：{:.1%}".format(purity))
    print()

    # 純度說明
    if purity >= 0.8:
        hint = "🌟 極高純度，幾乎確定能獲得目標飾品！"
    elif purity >= 0.5:
        hint = "✅ 高純度，推薦前往"
    elif purity >= 0.3:
        hint = "⚠️  中等純度，附近有其他種類混雜"
    else:
        hint = "❗ 低純度，目標飾品設施較分散"

    print(hint)
    print()
    print("📍 Google Maps 導航：")
    print("   {}".format(maps_url))
    print("=" * 50)


# ── 入口 ───────────────────────────────────────────────────────────────────────

def interactive_mode():
    print("🌱 Pikmin Bloom Radar - 戰略掃描測試模式")
    print("   （直接按 Enter 使用預設值：台北 101 附近）")
    print()

    title_raw = input("地點名稱（選填）：").strip()
    title = title_raw if title_raw else "台北 101"

    lat_raw   = input("緯度（預設 25.0339）：").strip()
    lon_raw   = input("經度（預設 121.5619）：").strip()
    radius_raw = input("掃描半徑 m（預設 1000）：").strip()

    lat    = float(lat_raw)    if lat_raw    else 25.0339
    lon    = float(lon_raw)    if lon_raw    else 121.5619
    radius = int(radius_raw)   if radius_raw else 1000

    return lat, lon, radius, title


def main():
    parser = argparse.ArgumentParser(description="Pikmin Bloom Radar 戰略掃描本地測試")
    parser.add_argument("lat",     nargs="?", type=float, help="緯度")
    parser.add_argument("lon",     nargs="?", type=float, help="經度")
    parser.add_argument("--radius", type=int, default=1000, help="掃描半徑（預設 1000m）")
    parser.add_argument("--title",  type=str, default="",   help="地點名稱")
    args = parser.parse_args()

    if args.lat is not None and args.lon is not None:
        lat    = args.lat
        lon    = args.lon
        radius = args.radius
        title  = args.title if args.title else "{}, {}".format(lat, lon)
    else:
        try:
            lat, lon, radius, title = interactive_mode()
        except (ValueError, KeyboardInterrupt):
            print("\n結束")
            sys.exit(0)

    asyncio.run(run(lat, lon, radius, title))


if __name__ == "__main__":
    main()
