"""
cache_service.py - 使用者狀態暫存服務

功能：
  管理「戰略掃描」兩階段互動的使用者狀態。
  以 user_id 為 key，TTL 5 分鐘後自動清除（避免殘留舊狀態）。

狀態機：
  (無狀態)
    → 收到 "scan" 文字 → mode="awaiting_location"
    → 收到位置訊息 → mode="awaiting_selection"（含 OSM 元素快取）
    → 收到 Postback → 執行純度演算法 → 清除狀態

設計原則：
  - 使用 cachetools.TTLCache，無需外部 Redis 依賴
  - 若未來需要水平擴展，可將此模組替換為 Redis 實作，介面保持不變

UserState 結構：
  {
    "mode": "awaiting_location" | "awaiting_selection",
    "elements": list[dict],    # Overpass 元素（含座標），mode=awaiting_selection 時存在
    "lat": float,              # 掃描中心緯度
    "lon": float,              # 掃描中心經度
    "title": str,              # 地點名稱（顯示用）
    "pikmin_counts": dict,     # 飾品種類 → 數量
  }
"""

import threading
from typing import TypedDict

from cachetools import TTLCache

# ─────────────────────────────────────────────
# 型別定義
# ─────────────────────────────────────────────

class UserState(TypedDict, total=False):
    mode: str               # "awaiting_location" | "awaiting_selection"
    elements: list          # Overpass 元素（含座標）
    lat: float
    lon: float
    title: str
    pikmin_counts: dict     # {"☕  咖啡廳": 3, "🚆  車站": 1}


# ─────────────────────────────────────────────
# Cache 實例（Thread-safe）
# ─────────────────────────────────────────────

_TTL_SECONDS = 300   # 5 分鐘
_MAX_USERS   = 1000  # 同時最多暫存 1000 位使用者

_cache: TTLCache = TTLCache(maxsize=_MAX_USERS, ttl=_TTL_SECONDS)
_lock = threading.Lock()


# ─────────────────────────────────────────────
# 公開介面
# ─────────────────────────────────────────────

def get_state(user_id: str) -> UserState | None:
    """
    取得使用者目前的掃描狀態。

    Args:
        user_id: LINE 使用者 ID（格式如 Uxxxxxxxx）

    Returns:
        UserState dict；若無狀態或已過期，回傳 None
    """
    with _lock:
        return _cache.get(user_id)


def set_state(user_id: str, state: UserState) -> None:
    """
    設定或更新使用者狀態（覆寫並重置 TTL）。

    Args:
        user_id: LINE 使用者 ID
        state: 新的 UserState dict
    """
    with _lock:
        _cache[user_id] = state


def clear_state(user_id: str) -> None:
    """
    清除使用者狀態（掃描完成或使用者取消時呼叫）。

    Args:
        user_id: LINE 使用者 ID
    """
    with _lock:
        _cache.pop(user_id, None)


def is_awaiting_location(user_id: str) -> bool:
    """使用者是否處於「等待位置」狀態（輸入 scan 後尚未分享位置）"""
    state = get_state(user_id)
    return state is not None and state.get("mode") == "awaiting_location"


def is_awaiting_selection(user_id: str) -> bool:
    """使用者是否處於「等待選擇飾品種類」狀態（Quick Reply 已顯示）"""
    state = get_state(user_id)
    return state is not None and state.get("mode") == "awaiting_selection"
