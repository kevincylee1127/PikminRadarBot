"""
config.py — 環境變數管理

使用 pydantic-settings 從 .env 檔案讀取敏感設定。
所有金鑰皆不可 hardcode 於程式碼中。

使用方式：
    from config import settings
    print(settings.line_channel_secret)
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    應用程式設定，對應 .env 檔案中的同名環境變數（不分大小寫）。
    """

    # LINE Messaging API
    line_channel_secret: str
    line_channel_access_token: str

    # Overpass API（可覆寫以切換鏡像站）
    overpass_url: str = "https://overpass-api.de/api/interpreter"

    # 查詢半徑（公尺），預設 100
    search_radius_m: int = 100

    # httpx 逾時設定（秒）
    overpass_timeout_s: float = 10.0

    # 最大重試次數
    overpass_max_retries: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """
    回傳快取的 Settings 實例（整個應用生命週期只建立一次）。
    使用 lru_cache 確保 .env 只被讀取一次。
    """
    return Settings()


# 方便直接 import 使用
settings = get_settings()
