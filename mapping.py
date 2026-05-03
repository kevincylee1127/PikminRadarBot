"""
mapping.py — OSM Tags 與皮克敏飾品名稱對應字典

結構設計說明：
  PIKMIN_RULES 是一個有序清單，每一條規則代表一種皮克敏飾品。
  每條規則包含：
    - name: 顯示給使用者的名稱（含 emoji）
    - conditions: 一個或多個 OSM tag 條件（key/value），符合其中一個即觸發

  查詢時，對每個 OSM 元素逐一比對 conditions；
  整批結果再去重，最終以 set 輸出已匹配的飾品名稱。

未來擴充方式：
  - 新增皮克敏種類：在 PIKMIN_RULES 末尾 append 新規則 dict 即可
  - 新增判斷條件：在對應規則的 conditions 清單中新增 {"key": ..., "value": ...}
"""

from typing import TypedDict

# ─────────────────────────────────────────────
# 型別定義
# ─────────────────────────────────────────────

class OsmCondition(TypedDict):
    key: str
    value: str


class PikminRule(TypedDict):
    name: str          # 顯示名稱，含 emoji
    conditions: list[OsmCondition]


# ─────────────────────────────────────────────
# 主要對照規則
# ─────────────────────────────────────────────

PIKMIN_RULES: list[PikminRule] = [
    {
        "name": "🍽️ 餐廳",
        "conditions": [
            {"key": "amenity", "value": "restaurant"},
        ],
    },
    {
        "name": "☕ 咖啡廳",
        "conditions": [
            {"key": "amenity", "value": "cafe"},
        ],
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
        "conditions": [
            {"key": "amenity", "value": "cinema"},
        ],
    },
    {
        "name": "💊 藥妝店",
        "conditions": [
            {"key": "amenity", "value": "pharmacy"},
            {"key": "shop", "value": "chemist"},
            {"key": "shop", "value": "drugstore"},
        ],
    },
    {
        "name": "🦁 動物園",
        "conditions": [
            {"key": "tourism", "value": "zoo"},
        ],
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
        "conditions": [
            {"key": "amenity", "value": "post_office"},
        ],
    },
    {
        "name": "🖼️ 美術館",
        "conditions": [
            {"key": "tourism", "value": "gallery"},
            {"key": "amenity", "value": "arts_centre"},
        ],
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
        "conditions": [
            {"key": "railway", "value": "station"},
        ],
    },
    {
        "name": "🏪 便利商店",
        "conditions": [
            {"key": "shop", "value": "convenience"},
        ],
    },
    {
        "name": "🛒 超市",
        "conditions": [
            {"key": "shop", "value": "supermarket"},
        ],
    },
    {
        "name": "🍞 麵包店",
        "conditions": [
            {"key": "shop", "value": "bakery"},
        ],
    },
    {
        "name": "📚 圖書館",
        "conditions": [
            {"key": "amenity", "value": "library"},
        ],
    },
    {
        "name": "🏥 醫院",
        "conditions": [
            {"key": "amenity", "value": "hospital"},
        ],
    },
    {
        "name": "🏨 飯店",
        "conditions": [
            {"key": "tourism", "value": "hotel"},
            {"key": "tourism", "value": "motel"},
        ],
    },
    {
        "name": "🏟️ 體育場",
        "conditions": [
            {"key": "leisure", "value": "stadium"},
        ],
    },
    {
        "name": "💇 美髮沙龍",
        "conditions": [
            {"key": "shop", "value": "hairdresser"},
        ],
    },
    {
        "name": "🏖️ 海灘",
        "conditions": [
            {"key": "natural", "value": "beach"},
        ],
    },
    {
        "name": "🌸 公園",
        "conditions": [
            {"key": "leisure", "value": "park"},
        ],
    },
    {
        "name": "🏛️ 博物館",
        "conditions": [
            {"key": "tourism", "value": "museum"},
        ],
    },
]


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def match_pikmin(tags: dict[str, str]) -> str | None:
    """
    給定單一 OSM 元素的 tags dict，回傳第一個符合的皮克敏飾品名稱；
    若無符合則回傳 None。

    Args:
        tags: OSM 元素的標籤，如 {"amenity": "cafe", "name": "星巴克"}

    Returns:
        符合的飾品名稱字串，例如 "☕ 咖啡廳"；無符合則為 None
    """
    for rule in PIKMIN_RULES:
        for condition in rule["conditions"]:
            if tags.get(condition["key"]) == condition["value"]:
                return rule["name"]
    return None


def match_all_pikmin(elements: list[dict]) -> set[str]:
    """
    對一批 OSM 元素（Overpass API 回傳的 elements 陣列）進行全量比對，
    回傳已去重的皮克敏飾品名稱集合。

    Args:
        elements: Overpass API 回傳的 elements 清單，每個元素需含 "tags" dict

    Returns:
        去重後的飾品名稱 set，例如 {"☕ 咖啡廳", "🚆 車站"}
    """
    found: set[str] = set()
    for element in elements:
        tags = element.get("tags", {})
        name = match_pikmin(tags)
        if name:
            found.add(name)
    return found
