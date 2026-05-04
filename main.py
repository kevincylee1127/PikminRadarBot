"""
main.py - FastAPI 入口（v2.0，含戰略掃描模式）
"""

import hashlib
import hmac
import logging
import urllib.parse
from base64 import b64encode
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    LocationMessageContent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

import cache_service as cache
from analyzer import find_best_location, google_maps_url, summarize_pikmin_counts
from config import settings
from geo_service import extract_plain_coords, extract_url, resolve_coords
from mapping import PIKMIN_RULES
from osm_service import query_nearby_pikmin, query_nearest_pikmin, query_scan_elements

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_line_config = Configuration(access_token=settings.line_channel_access_token)
_parser = WebhookParser(settings.line_channel_secret)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pikmin Bloom Radar Bot v2.0 啟動中...")
    yield
    logger.info("Pikmin Bloom Radar Bot 已關閉")


app = FastAPI(
    title="Pikmin Bloom Radar Bot",
    description="LINE Bot v2.0：即時單點模式 + 戰略掃描模式",
    version="2.0.0",
    lifespan=lifespan,
)


# ── 簽章驗證 ──────────────────────────────────

def _verify_signature(body: bytes, signature: str) -> None:
    digest = hmac.new(
        settings.line_channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = b64encode(digest).decode("utf-8")
    if not hmac.compare_digest(expected, signature):
        logger.warning("LINE 簽章驗證失敗")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )


# ── 即時模式回覆 ──────────────────────────────

def _build_instant_reply(title: str, results: list) -> str:
    if not results:
        return "📍 座標：{}\n附近僅有路邊皮克敏 🌿".format(title)
    items = "\n".join(
        "- {} （距離約 {:.0f}m）".format(name, dist) for name, dist in results
    )
    return "📍 座標：{}\n附近最近的飾品設施：\n{}".format(title, items)


# ── 掃描模式 Quick Reply ──────────────────────

_MAX_QUICK_REPLY = 13


def _build_scan_quick_reply(user_id: str, title: str, pikmin_counts: dict):
    sorted_items = sorted(pikmin_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_items = sorted_items[:_MAX_QUICK_REPLY]

    reply_text = (
        "📡 戰略掃描完成：{}\n"
        "500m 範圍內找到 {} 種飾品設施\n\n"
        "請點選你想前往的飾品種類，我會找出純度最高的位置："
    ).format(title, len(sorted_items))

    items = []
    for name, count in sorted_items:
        label = "{} x{}".format(name, count)
        postback_data = urllib.parse.urlencode({
            "action": "target",
            "uid": user_id,
            "pikmin": name,
        })
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=label[:20],
                    data=postback_data,
                    display_text=label,
                )
            )
        )

    return reply_text, QuickReply(items=items)


# ── 事件處理器 ────────────────────────────────

async def _handle_text(event, api, user_id: str) -> None:
    text = event.message.text.strip()
    text_lower = text.lower()

    # ── 純座標文字偵測（如 "25.044548 121.559183"）──
    plain_coords = extract_plain_coords(text)
    if plain_coords:
        lat, lon = plain_coords
        title = "{:.5f}, {:.5f}".format(lat, lon)
        logger.info("使用者 %s 輸入純座標: %s", user_id, title)
        if cache.is_awaiting_location(user_id):
            await _run_scan_mode(event, api, user_id, lat, lon, title)
        else:
            results = await query_nearest_pikmin(lat, lon)
            reply_text = _build_instant_reply(title, results)
            await api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
        return

    # ── Google Maps 完整 URL 偵測 ─────────────────
    maps_url = extract_url(text)
    if maps_url:
        await _handle_maps_url(event, api, user_id, maps_url)
        return

    if text_lower == "scan":
        cache.set_state(user_id, {"mode": "awaiting_location"})
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text=(
                        "📡 戰略掃描模式已啟動！\n"
                        "請分享你的位置或貼上 Google Maps 連結\n"
                        "我將掃描 500m 範圍內的設施\n\n"
                        "（輸入 cancel 可取消）"
                    ),
                )],
            )
        )
        logger.info("使用者 %s 啟動戰略掃描模式", user_id)

    elif text_lower == "cancel":
        cache.clear_state(user_id)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="已取消掃描。直接分享位置或貼上 Google Maps 連結可使用即時模式 📍")],
            )
        )

    else:
        hint = (
            "🌱 Pikmin Bloom Radar\n\n"
            "📍 即時模式：\n"
            "  • 分享 LINE 位置\n"
            "  • 貼座標，如：25.0445 121.5592\n\n"
            "📡 戰略掃描：\n"
            "  • 輸入 scan 再分享位置或貼座標\n\n"
            "💡 如何取得座標：\n"
            "  Google Maps → 長按地點 → 複製上方數字"
        )
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=hint)],
            )
        )


async def _handle_maps_url(event, api, user_id: str, url: str) -> None:
    """處理 Google Maps 連結，解析座標後走即時模式或掃描模式。"""
    logger.info("使用者 %s 傳送 Google Maps URL: %s", user_id, url)

    await api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="🔍 正在解析 Google Maps 連結...")],
        )
    )

    coords = await resolve_coords(url)
    if coords is None:
        # reply_token 已使用，改用 push（需要 user_id）
        logger.warning("無法從 URL 解析座標: %s", url)
        return

    lat, lon = coords
    title = "Google Maps 分享位置 ({:.5f}, {:.5f})".format(lat, lon)
    logger.info("Google Maps 解析成功：(%.6f, %.6f)", lat, lon)

    if cache.is_awaiting_location(user_id):
        # 建立一個假的 event-like 物件傳給 scan mode
        # 直接呼叫核心邏輯，reply_token 已被使用，用 push message
        from linebot.v3.messaging import PushMessageRequest
        async with AsyncApiClient(_line_config) as push_client:
            push_api = AsyncMessagingApi(push_client)
            elements = await query_scan_elements(lat, lon, radius_m=500)
            if not elements:
                cache.clear_state(user_id)
                await push_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text="掃描完成，500m 內未找到特殊設施 🌿")],
                    )
                )
                return

            from analyzer import summarize_pikmin_counts
            pikmin_counts = summarize_pikmin_counts(elements)
            if not pikmin_counts:
                cache.clear_state(user_id)
                await push_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text="掃描完成，500m 內未找到特殊設施 🌿")],
                    )
                )
                return

            cache.set_state(user_id, {
                "mode": "awaiting_selection",
                "elements": elements,
                "lat": lat,
                "lon": lon,
                "title": title,
                "pikmin_counts": pikmin_counts,
            })

            reply_text, quick_reply = _build_scan_quick_reply(user_id, title, pikmin_counts)
            await push_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=reply_text, quick_reply=quick_reply)],
                )
            )
    else:
        # 即時模式
        from linebot.v3.messaging import PushMessageRequest
        results = await query_nearest_pikmin(lat, lon)
        reply_text = _build_instant_reply(title, results)
        async with AsyncApiClient(_line_config) as push_client:
            push_api = AsyncMessagingApi(push_client)
            await push_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=reply_text)],
                )
            )


async def _handle_location(event, api, user_id: str) -> None:
    loc = event.message
    lat = loc.latitude
    lon = loc.longitude
    title = loc.title or "{:.5f}, {:.5f}".format(lat, lon)

    if cache.is_awaiting_location(user_id):
        await _run_scan_mode(event, api, user_id, lat, lon, title)
    else:
        await _run_instant_mode(event, api, lat, lon, title)


async def _run_instant_mode(event, api, lat: float, lon: float, title: str) -> None:
    logger.info("即時模式：%s (%.6f, %.6f)", title, lat, lon)
    results = await query_nearest_pikmin(lat, lon)
    reply_text = _build_instant_reply(title, results)
    await api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)],
        )
    )


async def _run_scan_mode(
    event, api, user_id: str, lat: float, lon: float, title: str
) -> None:
    logger.info("掃描模式第一階段：%s (%.6f, %.6f)", title, lat, lon)
    elements = await query_scan_elements(lat, lon, radius_m=500)

    if not elements:
        cache.clear_state(user_id)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="掃描完成，500m 內未找到特殊設施 🌿")],
            )
        )
        return

    pikmin_counts = summarize_pikmin_counts(elements)

    if not pikmin_counts:
        cache.clear_state(user_id)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="掃描完成，500m 內未找到特殊設施 🌿")],
            )
        )
        return

    cache.set_state(user_id, {
        "mode": "awaiting_selection",
        "elements": elements,
        "lat": lat,
        "lon": lon,
        "title": title,
        "pikmin_counts": pikmin_counts,
    })

    reply_text, quick_reply = _build_scan_quick_reply(user_id, title, pikmin_counts)
    await api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text, quick_reply=quick_reply)],
        )
    )


async def _handle_postback(event, api, user_id: str) -> None:
    params = urllib.parse.parse_qs(event.postback.data)
    action = params.get("action", [""])[0]
    target_pikmin = params.get("pikmin", [""])[0]
    postback_uid = params.get("uid", [""])[0]

    if action != "target" or not target_pikmin or postback_uid != user_id:
        logger.warning("非法 postback：uid=%s data=%s", user_id, event.postback.data)
        return

    state = cache.get_state(user_id)
    if not state or state.get("mode") != "awaiting_selection":
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="掃描已過期，請重新輸入 scan 開始新的掃描。")],
            )
        )
        return

    elements = state.get("elements", [])
    scan_title = state.get("title", "")
    logger.info("掃描模式第二階段：使用者 %s 選擇 %s", user_id, target_pikmin)

    result = find_best_location(elements, target_pikmin)
    cache.clear_state(user_id)

    if result is None:
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(
                    text="找不到 {} 的精確座標資料，請嘗試其他種類。".format(target_pikmin)
                )],
            )
        )
        return

    best_lat, best_lon, purity = result
    maps_url = google_maps_url(best_lat, best_lon)

    reply_text = (
        "🎯 最佳獲取點：{}\n"
        "目標飾品：{}\n"
        "純度分數：{:.0%}\n\n"
        "📍 導航連結：\n{}"
    ).format(scan_title, target_pikmin, purity, maps_url)

    await api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)],
        )
    )


# ── Webhook 端點 ──────────────────────────────

@app.post("/pikmin/callback", status_code=status.HTTP_200_OK)
async def callback(
    request: Request,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
) -> dict:
    body = await request.body()
    _verify_signature(body, x_line_signature)

    try:
        events = _parser.parse(body.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    async with AsyncApiClient(_line_config) as api_client:
        api = AsyncMessagingApi(api_client)

        for event in events:
            source = event.source
            user_id = getattr(source, "user_id", None) or ""

            if isinstance(event, MessageEvent):
                if isinstance(event.message, TextMessageContent):
                    await _handle_text(event, api, user_id)
                elif isinstance(event.message, LocationMessageContent):
                    await _handle_location(event, api, user_id)

            elif isinstance(event, PostbackEvent):
                await _handle_postback(event, api, user_id)

    return {"status": "ok"}


# ── 健康檢查 ──────────────────────────────────

@app.get("/pikmin/health")
async def health() -> dict:
    return {"status": "healthy", "service": "pikmin-bloom-radar", "version": "2.0.0"}
