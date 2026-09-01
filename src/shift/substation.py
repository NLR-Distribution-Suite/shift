import hashlib
import math
import time
from pathlib import Path

import requests
import geopandas as gpd
from loguru import logger
from shapely.geometry import Polygon

from shift.utils.overpass import OVERPASS_MIRRORS

# Primary mirror's interpreter endpoint (raw Overpass query, not via OSMnx).
OVERPASS_URL = f"{OVERPASS_MIRRORS[0]}/interpreter"

# Cache directory for fetched substations (mirrors `.dump` gitignore convention).
_SUBSTATIONS_CACHE_DIR: Path | None = None


def set_substations_cache_dir(path: str | Path | None) -> None:
    """Set the folder used to cache fetched substations between runs."""
    global _SUBSTATIONS_CACHE_DIR  # noqa: PLW0603
    _SUBSTATIONS_CACHE_DIR = Path(path) if path else None


def _substations_cache_path(polygon: Polygon) -> Path | None:
    """Return the cache file for ``polygon`` when a cache dir is configured."""
    if _SUBSTATIONS_CACHE_DIR is None:
        return None
    key = hashlib.sha256(polygon.wkt.encode("utf-8")).hexdigest()[:16]
    return _SUBSTATIONS_CACHE_DIR / f"substations_{key}.geojson"


def _normalize_voltage_part(part: str) -> tuple[float, bool] | None:
    """Normalize a single OSM voltage part to ``(value, explicit_kv)``.

    Recognizes unit suffixes (``kV``/``k``/``V``); bare numbers are assumed to be
    volts. Returns None when the part is not numeric.
    """
    lower = part.strip().lower()
    if not lower:
        return None
    unit_kv = False
    if lower.endswith("kv"):
        lower, unit_kv = lower[:-2], True
    elif lower.endswith("k"):
        lower, unit_kv = lower[:-1], True
    elif lower.endswith("v"):
        lower = lower[:-1]
    try:
        return float(lower), unit_kv
    except ValueError:
        return None


def substation_voltage_kv(voltage_tag: object) -> float | None:
    """Parse an OSM/OpenInfraMap substation ``voltage`` tag to the distribution-side kV.

    OSM stores substation voltage levels in volts, semicolon-separated, e.g.
    ``"110000;20000"``. The lowest level is treated as the distribution-side
    (primary) voltage. Parts carrying an explicit unit suffix (``kV``/``k``/``V``)
    are honored; bare numbers are assumed to be volts when they look like volts
    (``>= 1000``) and kV otherwise.

    Returns ``None`` when the tag is missing or cannot be parsed.
    """
    if voltage_tag is None:
        return None
    if isinstance(voltage_tag, float) and math.isnan(voltage_tag):
        return None

    values: list[float] = []
    explicit_kv = False
    for part in str(voltage_tag).replace(",", ";").split(";"):
        normalized = _normalize_voltage_part(part)
        if normalized is None:
            continue
        value, unit_kv = normalized
        values.append(value)
        explicit_kv = explicit_kv or unit_kv

    if not values:
        return None
    minimum = min(values)
    if explicit_kv or max(values) <= 1000.0:
        return float(minimum)
    return float(minimum / 1000.0)


def get_substations(polygon: Polygon) -> gpd.GeoDataFrame:
    """
    Get all OSM/OpenInfraMap substations intersecting a polygon.

    Parameters
    ----------
    polygon:
        Shapely Polygon in WGS84 (EPSG:4326).

    Returns
    -------
    GeoDataFrame
        Substations as point/polygon geometries with OSM tags.
    """
    cache_path = _substations_cache_path(polygon)
    if cache_path is not None and cache_path.exists():
        logger.info("Loading cached substations from {}", cache_path)
        return gpd.read_file(cache_path)

    # Overpass expects: lat lon
    coords = list(polygon.exterior.coords)
    poly_string = " ".join(f"{lat} {lon}" for lon, lat in coords)

    query = f"""
    [out:json][timeout:300];

    (
        nwr["power"="substation"](poly:"{poly_string}");
    );

    out geom;
    """

    response = None
    last_error: Exception | None = None
    for mirror in OVERPASS_MIRRORS:
        url = f"{mirror}/interpreter"
        try:
            logger.info("Querying Overpass for substations via {}", mirror)
            response = requests.post(
                url,
                data={"data": query},
                headers={
                    "User-Agent": "shift/0.7.0",
                    "Accept": "*/*",
                },
                timeout=360,
            )
            response.raise_for_status()
            last_error = None
            break
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Overpass mirror {} failed: {}", mirror, exc)
            time.sleep(2)

    if response is None or last_error is not None:
        raise (
            last_error if last_error is not None else RuntimeError("No Overpass mirror available.")
        )

    data = response.json()

    features = []

    for element in data["elements"]:
        tags = element.get("tags", {})

        if element["type"] == "node":
            geometry = {
                "type": "Point",
                "coordinates": [
                    element["lon"],
                    element["lat"],
                ],
            }

        elif element["type"] == "way":
            coordinates = [[p["lon"], p["lat"]] for p in element.get("geometry", [])]

            geometry = {
                "type": "Polygon",
                "coordinates": [coordinates],
            }

        else:
            # Relations are more complicated because their
            # geometry is assembled from members.
            continue

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "osm_type": element["type"],
                    "osm_id": element["id"],
                    **tags,
                },
                "geometry": geometry,
            }
        )

    result = gpd.GeoDataFrame.from_features(
        features,
        crs="EPSG:4326",
    )

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_file(cache_path, driver="GeoJSON")
        logger.info("Cached {} substation(s) to {}", len(result), cache_path)

    return result
