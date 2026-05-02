"""
test_query.py - 本地測試腳本（不需 LINE SDK 或 .env）

用途：
  在部署前，直接用命令列測試「輸入座標 → 查詢 OSM → 顯示皮克敏飾品」的核心流程。

安裝依賴（只需一個套件）：
  pip install httpx

執行方式：
  # 互動模式（輸入地址名稱+座標）
  python test_query.py

  # 直接帶參數（緯度 經度）
  python test_query.py 25.0330 121.5654

  # 自訂半徑（公尺）
  python test_query.py 25.0330 121.5654 --radius 300
"""

import argparse
import asyncio
import sys

import httpx

# ──────────────────────────────────────────────
# mapping 邏輯（直接內嵌，不 import config.py）
# ──────────────────────────────────────────────

PIKMIN_RULES = [
    {
        "name": "🍽️ 餐廳",
        "conditions": [{"key": "amenity", "value": "restaurant"}],
    },
    {
        "name": "☕ 咖啡廳",
        "conditions": [{"key": "amenity", "value": "cafe"}],
    },
    {
        "name": "🍰 甜點店",
        "conditions": [
            {"key": "shop", "value": "pastry"},
            {"key": "shop", "value": "confectionery"},
        ],
    },
    {
        "name": "🎬 電影院",
        "conditions": [{"key": "amenity", "value": "cinema"}],
    },
    {
        "name": "💊 藥妝店",
        "conditions": [
            {"key": "shop", "value": "chemist"},
            {"key": "shop", "value": "drugstore"},
        ],
    },
    {
        "name": "🦁 動物園",
        "conditions": [{"key": "tourism", "value": "zoo"}],
    },
    {
        "name": "🌳 森林",
        "conditions": [
            {"key": "natural", "value": "wood"},
            {"key": "landuse", "value": "forest"},
        ],
    },
    {
        "name": "💧 水邊",
        "conditions": [
            {"key": "natural", "value": "water"},
            {"key": "natural", "value": "coastline"},
        ],
    },
    {
        "name": "📮 郵局",
        "conditions": [{"key": "amenity", "value": "post_office"}],
    },
    {
        "name": "🖼️ 美術館",
        "conditions": [{"key": "tourism", "value": "gallery"}],
    },
    {
        "name": "✈️ 機場",
        "conditions": [
            {"key": "aeroway", "value": "terminal"},
            {"key": "aeroway", "value": "aerodrome"},
        ],
    },
    {
        "name": "🚆 車站",
        "conditions": [{"key": "railway", "value": "station"}],
    },
]


def match_all_pikmin(elements):
    found = set()
    for element in elements:
        tags = element.get("tags", {})
        for rule in PIKMIN_RULES:
            for cond in rule["conditions"]:
                if tags.get(cond["key"]) == cond["value"]:
                    found.add(rule["name"])
                    break
    return found


# ──────────────────────────────────────────────
# Overpass 設定
# ──────────────────────────────────────────────

# 多個端點，自動切換以避免 406 / timeout
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

HEADERS = {
    "User-Agent": "PikminBloomRadar/1.0 (local-test)",
    "Accept": "application/json",
}


# ──────────────────────────────────────────────
# Overpass QL 查詢建構
# ──────────────────────────────────────────────

def build_query(lat, lon, radius):
    c = "{},{}".format(lat, lon)
    r = radius
    return (
        "[out:json][timeout:30];\n"
        "(\n"
        '  node["amenity"="restaurant"](around:{r},{c});\n'
        '  way["amenity"="restaurant"](around:{r},{c});\n'
        '  node["amenity"="cafe"](around:{r},{c});\n'
        '  way["amenity"="cafe"](around:{r},{c});\n'
        '  node["shop"="pastry"](around:{r},{c});\n'
        '  way["shop"="pastry"](around:{r},{c});\n'
        '  node["shop"="confectionery"](around:{r},{c});\n'
        '  way["shop"="confectionery"](around:{r},{c});\n'
        '  node["amenity"="cinema"](around:{r},{c});\n'
        '  way["amenity"="cinema"](around:{r},{c});\n'
        '  node["shop"="chemist"](around:{r},{c});\n'
        '  way["shop"="chemist"](around:{r},{c});\n'
        '  node["shop"="drugstore"](around:{r},{c});\n'
        '  way["shop"="drugstore"](around:{r},{c});\n'
        '  node["tourism"="zoo"](around:{r},{c});\n'
        '  way["tourism"="zoo"](around:{r},{c});\n'
        '  way["natural"="wood"](around:{r},{c});\n'
        '  relation["natural"="wood"](around:{r},{c});\n'
        '  way["landuse"="forest"](around:{r},{c});\n'
        '  relation["landuse"="forest"](around:{r},{c});\n'
        '  node["natural"="water"](around:{r},{c});\n'
        '  way["natural"="water"](around:{r},{c});\n'
        '  relation["natural"="water"](around:{r},{c});\n'
        '  way["natural"="coastline"](around:{r},{c});\n'
        '  node["amenity"="post_office"](around:{r},{c});\n'
        '  way["amenity"="post_office"](around:{r},{c});\n'
        '  node["tourism"="gallery"](around:{r},{c});\n'
        '  way["tourism"="gallery"](around:{r},{c});\n'
        '  node["aeroway"="terminal"](around:{r},{c});\n'
        '  way["aeroway"="terminal"](around:{r},{c});\n'
        '  node["aeroway"="aerodrome"](around:{r},{c});\n'
        '  way["aeroway"="aerodrome"](around:{r},{c});\n'
        '  node["railway"="station"](around:{r},{c});\n'
        '  way["railway"="station"](around:{r},{c});\n'
        ");\n"
        "out tags;"
    ).format(r=r, c=c)


# ──────────────────────────────────────────────
# 非同步查詢（含自動切換鏡像）
# ──────────────────────────────────────────────

async def query_osm(lat, lon, radius):
    query = build_query(lat, lon, radius)
    print("  Overpass API ({} m) ...".format(radius), flush=True)

    last_err = None

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:
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
            except httpx.TimeoutException as e:
                print("  ⚠️  {} 逾時，切換備用...".format(endpoint))
                last_err = e

    raise last_err


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

async def run(lat, lon, radius, title):
    print()
    print("📍 查詢地點：{}".format(title))
    print("   座標：{}, {}　半徑：{}m".format(lat, lon, radius))
    print("-" * 40)

    try:
        elements = await query_osm(lat, lon, radius)
    except httpx.TimeoutException:
        print("❌ 查詢逾時，請稍後再試或縮小半徑")
        return
    except httpx.HTTPStatusError as e:
        print("❌ Overpass API 全部端點失敗（最後錯誤：{}）".format(e.response.status_code))
        return
    except Exception as e:
        print("❌ 查詢失敗：{}".format(e))