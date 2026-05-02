"""
analyzer.py - 戰略掃描純度演算法

核心功能：
  實作 Purity Algorithm，找出目標飾品在 1000m 掃描範圍內
  最「純淨」（密度最高）的座標，作為玩家前往的推薦點。

純度公式：
  P = (50m 內目標標籤數量) / (50m 內所有標籤數量)

  P 值越高 = 該點周圍幾乎全是目標設施，獲得目標飾品的機率最高。

使用方式：
  from analyzer import summarize_pikmin_counts, find_best_location

  counts = summarize_pikmin_counts(elements)
  best_lat, best_lon, score = find_best_location(elements, "☕  咖啡廳")
"""

import math
from collections import Counter

from mapping import PIKMIN_RULES, match_pikmin

# ─────────────────────────────────────────────
# 地理距離計算（Haversine）
# ─────────────────────────────────────────────

_EARTH_RADIUS_M = 6_371_000.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    計算兩點間的球面距離（公尺）。

    Args:
        lat1, lon1: 第一點緯度、經度（度）
        lat2, lon2: 第二點緯度、經度（度）

    Returns:
        距離（公尺）
    """
    r = _EARTH_RADIUS_M
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────
# 元素座標提取
# ─────────────────────────────────────────────

def _get_coord(element: dict) -> tuple[float, float] | None:
    """
    從 Overpass 元素取得座標。

    - node: 直接有 lat/lon
    - way/relation: 需使用 out center 取得的 center.lat / center.lon

    Args:
        element: Overpass API 的單一元素 dict

    Returns:
        (lat, lon) 或 None（無座標資訊時）
    """
    if element.get("type") == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)

    center = element.get("center")
    if center:
        lat = center.get("lat")
        lon = center.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)

    return None


# ─────────────────────────────────────────────
# 統計函式（Quick Reply 用）
# ─────────────────────────────────────────────

def summarize_pikmin_counts(elements: list[dict]) -> dict[str, int]:
    """
    統計 1000m 範圍內每種皮克敏飾品的設施數量（含重複）。

    與 match_all_pikmin 不同，此函式保留每個設施的計數，
    用於 Quick Reply 顯示「☕ 咖啡廳 x3」之類的統計資訊。

    Args:
        elements: Overpass API 回傳的 elements 清單

    Returns:
        {飾品名稱: 數量} 的 dict，例如 {"☕  咖啡廳": 3, "🚆  車站": 1}
        依照 PIKMIN_RULES 順序排列
    """
    counter: Counter = Counter()
    for element in elements:
        tags = element.get("tags", {})
        name = match_pikmin(tags)
        if name:
            counter[name] += 1

    # 依照 PIKMIN_RULES 定義順序回傳（保持一致性）
    ordered = {}
    for rule in PIKMIN_RULES:
        n = rule["name"]
        if n in counter:
            ordered[n] = counter[n]

    return ordered


# ─────────────────────────────────────────────
# 純度演算法（Purity Algorithm）
# ─────────────────────────────────────────────

def _purity_score(
    target_lat: float,
    target_lon: float,
    target_pikmin: str,
    all_elements: list[dict],
    radius_m: float = 50.0,
) -> float:
    """
    計算某座標在指定半徑內的純度分數。

    P = (目標飾品元素數) / (所有有對應飾品的元素數)

    Args:
        target_lat, target_lon: 候選點座標
        target_pikmin: 目標皮克敏飾品名稱（如 "☕  咖啡廳"）
        all_elements: 全部 OSM 元素（1000m 掃描結果）
        radius_m: 純度計算半徑（預設 50m）

    Returns:
        P 值（0.0 ~ 1.0）；若 50m 內無任何有意義設施則回傳 0.0
    """
    total_nearby = 0
    target_nearby = 0

    for element in all_elements:
        coord = _get_coord(element)
        if coord is None:
            continue

        dist = haversine(target_lat, target_lon, coord[0], coord[1])
        if dist > radius_m:
            continue

        pikmin = match_pikmin(element.get("tags", {}))
        if pikmin is None:
            continue

        total_nearby += 1
        if pikmin == target_pikmin:
            target_nearby += 1

    if total_nearby == 0:
        return 0.0

    return target_nearby / total_nearby


def find_best_location(
    elements: list[dict],
    target_pikmin: str,
    purity_radius_m: float = 50.0,
) -> tuple[float, float, float] | None:
    """
    在 OSM 元素中找出目標飾品純度最高的推薦座標。

    策略：
      只針對「座標已知且屬於目標飾品種類」的元素作為候選點，
      計算每個候選點在 purity_radius_m 內的 P 值，
      回傳 P 值最高的座標。

    Args:
        elements: Overpass 掃描結果（需含座標，使用 out center 查詢）
        target_pikmin: 目標飾品名稱（如 "☕  咖啡廳"）
        purity_radius_m: 純度計算半徑（預設 50m）

    Returns:
        (lat, lon, purity_score) 或 None（找不到任何候選點時）
    """
    # 過濾出屬於目標飾品且有座標的元素作為候選點
    candidates = []
    for element in elements:
        tags = element.get("tags", {})
        if match_pikmin(tags) != target_pikmin:
            continue
        coord = _get_coord(element)
        if coord is None:
            continue
        candidates.append((coord[0], coord[1]))

    if not candidates:
        return None

    # 計算每個候選點的純度，取最高分
    best: tuple[float, float, float] | None = None
    for lat, lon in candidates:
        score = _purity_score(lat, lon, target_pikmin, elements, purity_radius_m)
        if best is None or score > best[2]:
            best = (lat, lon, score)

    return best


# ─────────────────────────────────────────────
# Google Maps 連結生成
# ─────────────────────────────────────────────

def google_maps_url(lat: float, lon: float) -> str:
    """
    產生可直接開啟 Google Maps 導航的 URL。

    Args:
        lat: 緯度
        lon: 經度

    Returns:
        Google Maps URL 字串
    """
    return "https://www.google.com/maps?q={},{}".format(lat, lon)
