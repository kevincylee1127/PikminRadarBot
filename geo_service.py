"""
geo_service.py - Google Maps URL parsing and coordinate extraction

Supported formats:
  1. Full URL with @lat,lon: https://www.google.com/maps/@25.044548,121.559183,17z
  2. Place URL with @lat,lon: https://www.google.com/maps/place/.../@25.044548,121.559183,...
  3. Short URL (redirect):   https://maps.app.goo.gl/XXXXX
"""

import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Regex patterns to extract coordinates from Google Maps URLs / HTML
# Format 1: @lat,lon  (e.g. /maps/@25.044,121.559,17z)
_COORD_AT_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
# Format 2: q=lat,lon (e.g. /maps?q=25.044,121.559)
_COORD_Q_RE = re.compile(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)")
# Format 3: ll=lat,lon (older Google Maps format)
_COORD_LL_RE = re.compile(r"[?&]ll=(-?\d+\.\d+),(-?\d+\.\d+)")
# Format 4: JSON-like "lat":25.044 / "lng":121.559 or "latitude"/"longitude"
_COORD_LAT_RE = re.compile(r'"lat(?:itude)?"\s*:\s*(-?\d+\.\d+)')
_COORD_LNG_RE = re.compile(r'"ln?g(?:itude)?"\s*:\s*(-?\d+\.\d+)')
# Format 5: center=lat,lon
_COORD_CENTER_RE = re.compile(r"center=(-?\d+\.\d+),(-?\d+\.\d+)")

# Detect if a string contains any Google Maps URL
_MAPS_URL_RE = re.compile(
    r"https?://(maps\.app\.goo\.gl|preview\.app\.goo\.gl|goo\.gl/maps|www\.google\.com/maps|google\.com/maps)\S*"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


def extract_url(text: str) -> str | None:
    """Return the first Google Maps URL found in text, or None."""
    m = _MAPS_URL_RE.search(text)
    return m.group(0) if m else None


def _parse_coords(text: str) -> tuple[float, float] | None:
    """Try to extract (lat, lon) from a URL or HTML string using multiple regex patterns."""
    # @lat,lon
    m = _COORD_AT_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    # q=lat,lon
    m = _COORD_Q_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    # ll=lat,lon
    m = _COORD_LL_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    # center=lat,lon
    m = _COORD_CENTER_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    # JSON "lat":..., "lng":... (must find both)
    m_lat = _COORD_LAT_RE.search(text)
    m_lng = _COORD_LNG_RE.search(text)
    if m_lat and m_lng:
        return float(m_lat.group(1)), float(m_lng.group(1))
    return None


async def resolve_coords(url: str) -> tuple[float, float] | None:
    """
    Given a Google Maps URL (full or short), return (lat, lon) or None.

    Strategy:
      1. Try regex on the original URL first (works for full URLs).
      2. If not found, follow redirects (for short URLs like maps.app.goo.gl).
      3. Try regex on the final redirected URL.
    """
    # Step 1: try direct parse
    coords = _parse_coords(url)
    if coords:
        logger.debug("Coords from direct URL: %s", coords)
        return coords

    # Step 2: follow redirects
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            final_url = str(resp.url)
            logger.debug("Redirected to: %s", final_url)

        # Step 3: try regex on final URL
        coords = _parse_coords(final_url)
        if coords:
            logger.debug("Coords from redirected URL: %s", coords)
            return coords

        # Step 4: try regex on response body (some redirects embed coords in HTML)
        coords = _parse_coords(resp.text)
        if coords:
            logger.debug("Coords from response body: %s", coords)
            return coords

    except httpx.RequestError as exc:
        logger.warning("Failed to resolve Google Maps URL %s: %s", url, exc)

    return None
