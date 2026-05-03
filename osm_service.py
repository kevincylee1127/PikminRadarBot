"""
osm_service.py - Overpass API async query service

Features:
  - Query OSM elements by lat/lon and radius
  - httpx AsyncClient with User-Agent, mirror fallback, retry
  - Instant mode: query_nearby_pikmin (returns set of pikmin names)
  - Scan mode: query_scan_elements (returns raw elements with coordinates)
"""

import asyncio
import logging
from typing import Any

import httpx

from config import settings
from mapping import match_all_pikmin, match_pikmin

logger = logging.getLogger(__name__)

# ── Connection settings ────────────────────────────────────────────────────────

_OVERPASS_HEADERS = {
    "User-Agent": "PikminBloomRadar/1.0 (LINE Bot)",
    "Accept": "application/json",
}

_OVERPASS_MIRRORS = [
    None,  # uses settings.overpass_url
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


# ── Query builder (instant mode) ───────────────────────────────────────────────

def build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    center = "{},{}".format(lat, lon)
    r = radius_m
    filters = _tag_filters(center, r)
    return "[out:json][timeout:25];\n(\n  {}\n);\nout tags;".format(
        "\n  ".join(filters)
    )


# ── Query builder (scan mode, returns coordinates) ─────────────────────────────

def _build_scan_query(lat: float, lon: float, radius_m: int) -> str:
    center = "{},{}".format(lat, lon)
    r = radius_m
    filters = _tag_filters(center, r)
    # out center tags: returns center lat/lon for ways/relations + tags for all
    return "[out:json][timeout:40];\n(\n  {}\n);\nout center tags;".format(
        "\n  ".join(filters)
    )


def _tag_filters(center: str, r: int) -> list:
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
        ("amenity", "pharmacy"),
        ("amenity", "arts_centre"),
        ("shop",    "convenience"),
        ("shop",    "supermarket"),
        ("shop",    "bakery"),
        ("amenity", "library"),
        ("amenity", "hospital"),
        ("tourism", "hotel"),
        ("tourism", "motel"),
        ("leisure", "stadium"),
        ("leisure", "park"),
        ("shop",    "hairdresser"),
        ("natural", "beach"),
        ("tourism", "museum"),
    ]
    filters = []
    for key, val in pairs:
        tag = '["{}"="{}"]'.format(key, val)
        filters.append('node{}(around:{},{});'.format(tag, r, center))
        filters.append('way{}(around:{},{});'.format(tag, r, center))
        # relation for area-type tags
        if key in ("tourism", "natural", "landuse", "aeroway", "leisure"):
            filters.append('relation{}(around:{},{});'.format(tag, r, center))
    return filters


# ── HTTP fetch with retry and mirror fallback ──────────────────────────────────

async def _fetch_overpass(query: str) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.overpass_timeout_s)
    max_retries = settings.overpass_max_retries
    last_exc: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout, headers=_OVERPASS_HEADERS) as client:
        for attempt in range(1, max_retries + 1):
            mirror = _OVERPASS_MIRRORS[(attempt - 1) % len(_OVERPASS_MIRRORS)]
            url = mirror if mirror else settings.overpass_url

            try:
                logger.debug("Overpass attempt %d/%d -> %s", attempt, max_retries, url)
                response = await client.get(url, params={"data": query})
                response.raise_for_status()
                return response.json()

            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                wait = 2 ** (attempt - 1)
                logger.warning(
                    "Overpass failed attempt %d/%d url=%s: %s, retry in %.0fs",
                    attempt, max_retries, url, exc, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

            except httpx.RequestError as exc:
                logger.error("Overpass network error: %s", exc)
                raise

    raise last_exc  # type: ignore[misc]


# ── Public API ─────────────────────────────────────────────────────────────────

async def query_nearby_pikmin(
    lat: float,
    lon: float,
    radius_m: int | None = None,
) -> set[str]:
    """
    Instant mode: query OSM elements within radius and return deduplicated
    set of pikmin decor names.
    """
    if radius_m is None:
        radius_m = settings.search_radius_m

    query = build_overpass_query(lat, lon, radius_m)

    try:
        data = await _fetch_overpass(query)
    except Exception as exc:
        logger.error("Overpass query failed: %s", exc)
        return set()

    elements: list[dict] = data.get("elements", [])
    logger.info("Instant query (%.6f, %.6f) r=%dm: %d elements", lat, lon, radius_m, len(elements))
    return match_all_pikmin(elements)


async def query_nearest_pikmin(
    lat: float,
    lon: float,
    radius_m: int | None = None,
) -> tuple[str, float] | None:
    """
    Nearest POI mode: query OSM elements with coordinates, find the closest
    one that matches a pikmin rule, and return (pikmin_name, distance_m).
    Returns None if nothing found.

    Note: search radius is fixed at 300m to ensure large buildings (cinemas,
    museums, etc.) whose OSM center may be offset from the user are still found.
    The result is still only the single nearest POI.
    """
    # Always search 300m to catch large buildings with offset centers,
    # but still return only the nearest single result
    search_radius = 300

    # Use scan query to get element coordinates
    query = _build_scan_query(lat, lon, search_radius)

    try:
        data = await _fetch_overpass(query)
    except Exception as exc:
        logger.error("Overpass nearest query failed: %s", exc)
        return None

    elements: list[dict] = data.get("elements", [])
    logger.info("Nearest query (%.6f, %.6f) r=%dm: %d elements", lat, lon, radius_m, len(elements))

    if not elements:
        return None

    # Find closest element that matches a pikmin rule
    best_name: str | None = None
    best_dist: float = float("inf")

    for el in elements:
        # Get coordinates
        if el.get("type") == "node":
            elat, elon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center", {})
            elat, elon = center.get("lat"), center.get("lon")

        if elat is None or elon is None:
            continue

        # Check if it matches a pikmin rule
        tags = el.get("tags", {})
        name = match_pikmin(tags)
        if name is None:
            continue

        # Calculate distance using Haversine
        from math import radians, sin, cos, sqrt, atan2
        R = 6371000
        phi1, phi2 = radians(lat), radians(elat)
        dphi = radians(elat - lat)
        dlam = radians(elon - lon)
        a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
        dist = R * 2 * atan2(sqrt(a), sqrt(1 - a))

        if dist < best_dist:
            best_dist = dist
            best_name = name

    if best_name is None:
        return None

    logger.info("Nearest pikmin: %s at %.1fm", best_name, best_dist)
    return best_name, best_dist


async def query_scan_elements(
    lat: float,
    lon: float,
    radius_m: int = 1000,
) -> list[dict]:
    """
    Scan mode: query OSM elements with coordinate info (out center tags).
    Returns raw element list for purity algorithm.
    """
    query = _build_scan_query(lat, lon, radius_m)

    try:
        data = await _fetch_overpass(query)
    except Exception as exc:
        logger.error("Overpass scan failed: %s", exc)
        return []

    elements: list[dict] = data.get("elements", [])
    logger.info("Scan query (%.6f, %.6f) r=%dm: %d elements", lat, lon, radius_m, len(elements))
    return elements
