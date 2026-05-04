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
      1. Try regex on the original URL.
      2. Manually follow each redirect hop (up to 6), checking the Location
         header and destination URL at every step — coordinates often appear
         in an intermediate redirect before Google lands on the preview page.
      3. Try regex on the final response body.
    """
    # Step 1: direct parse
    coords = _parse_coords(url)
    if coords:
        logger.debug("Coords from direct URL: %s", coords)
        return coords

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers=_HEADERS,
            follow_redirects=False,  # manual hop-by-hop
        ) as client:
            current_url = url
            last_resp = None

            for hop in range(6):
                resp = await client.get(current_url)
                last_resp = resp
                logger.debug("Hop %d: %s -> %d", hop, current_url, resp.status_code)

                # Check Location header at this hop
                location = resp.headers.get("location", "")
                if location:
                    coords = _parse_coords(location)
                    if coords:
                        logger.debug("Coords from Location header hop %d: %s", hop, coords)
                        return coords

                # Check current URL itself
                coords = _parse_coords(current_url)
                if coords:
                    logger.debug("Coords from current URL hop %d", hop)
                    return coords

                if resp.is_redirect and location:
                    # Follow next hop
                    if location.startswith("http"):
                        current_url = location
                    else:
                        from urllib.parse import urljoin
                        current_url = urljoin(current_url, location)
                else:
                    break

            # Final attempt: parse response body of last page
            if last_resp is not None:
                try:
                    body = last_resp.text
                    coords = _parse_coords(body)
                    if coords:
                        logger.debug("Coords from response body")
                        return coords
                except Exception:
                    pass

    except httpx.RequestError as exc:
        logger.warning("Failed to resolve Google Maps URL %s: %s", url, exc)

    return None
