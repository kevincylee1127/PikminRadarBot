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
    # Group values by key and use regex matching to keep the query compact.
    # This prevents 403 errors on mirrors that reject overly long URLs.
    groups = [
        ("amenity", ["restaurant", "cafe", "cinema", "post_office",
                     "pharmacy", "arts_centre", "library", "hospital"]),
        ("shop",    ["pastry", "confectionery", "chemist", "drugstore",
                     "convenience", "supermarket", "bakery", "hairdresser"]),
        ("tourism", ["zoo", "gallery", "hotel", "motel", "museum"]),
        ("natural", ["wood", "water", "coastline", "beach"]),
        ("landuse", ["forest"]),
        ("aeroway", ["terminal", "aerodrome"]),
        ("railway", ["station"]),
        ("leisure", ["stadium", "park"]),
    ]
    # Keys whose elements can be relations (area-type features)
    area_keys = {"tourism", "natural", "landuse", "aeroway", "leisure"}

    filters = []
    for key, values in groups:
        regex = "|".join(values)
        tag = '["{}"~"{}"]'.format(key, regex)
        filters.append('node{}(around:{},{});'.format(tag, r, center))
        filters.append('way{}(around:{},{});'.format(tag, r, center))
        if key in area_keys:
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
    Nearest POI mode: use the stable 'out tags' query (same as instant mode),
    then find the closest matching element.

    Nodes have lat/lon in 'out tags' output directly.
    Ways/relations have no coordinates in 'out tags', so they are treated as
    distance=0 (they matched 'around:N' so they are definitely nearby).
    This keeps the query simple and reliable across all mirrors.
    """
    from math import atan2, cos, radians, sin, sqrt

    search_radius = 300
    query = build_overpass_query(lat, lon, search_radius)

    try:
        data = await _fetch_overpass(query)
    except Exception as exc:
        logger.error("Overpass nearest query failed: %s", exc)
        return None

    elements: list[dict] = data.get("elements", [])
    logger.info("Nearest query (%.6f, %.6f) r=%dm: %d elements", lat, lon, search_radius, len(elements))

    if not elements:
        return None

    best_name: str | None = None
    best_dist: float = float("inf")

    R = 6371000
    for el in elements:
        tags = el.get("tags", {})
        name = match_pikmin(tags)
        if name is None:
            continue

        if el.get("type") == "node":
            elat = el.get("lat")
            elon = el.get("lon")
            if elat is not None and elon is not None:
                phi1, phi2 = radians(lat), radians(elat)
                dphi = radians(elat - lat)
                dlam = radians(elon - lon)
                a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
                dist = R * 2 * atan2(sqrt(a), sqrt(1 - a))
            else:
                dist = 0.0
        else:
            # way/relation: no coords in out tags, treat as present at location
            dist = 0.0

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
