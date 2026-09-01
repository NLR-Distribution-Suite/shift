"""Parcel attribute mapping and additional data sources.

Decouples *which source columns* populate the four :class:`ParcelModel` fields
from *how* geometries are built, so OSM, API, and public GIS/FeatureServer
layers all flow through the same :func:`shift.parcel.parcels_from_geodataframe`
conversion.

Sources
-------
``parcels_from_gis``
    Fetch building/parcel features from a public ArcGIS FeatureServer layer via
    its REST ``query`` endpoint (no Esri login required).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any, Mapping
from urllib.parse import urlencode

import geopandas as gpd
from loguru import logger
import requests
from shapely.geometry import shape as shapely_shape

from shift.data_model import ParcelModel
from shift.exceptions import InvalidInputError

# The four fields every source must populate on a ParcelModel.
PARCEL_FIELDS: tuple[str, ...] = ("building_type", "city", "state", "postal_address")


class ParcelFieldMapper(ABC):
    """Map source GeoDataFrame columns onto the four ``ParcelModel`` fields.

    Subclasses declare default column names for their data type; callers can
    override any subset by passing a ``column_map`` to the constructor.
    """

    def __init__(self, column_map: Mapping[str, str] | None = None) -> None:
        self._column_map = dict(column_map) if column_map else {}
        unknown = set(self._column_map) - set(PARCEL_FIELDS)
        if unknown:
            raise InvalidInputError(
                f"Unknown parcel field(s) {sorted(unknown)}; expected one of {list(PARCEL_FIELDS)}."
            )

    @abstractmethod
    def default_columns(self) -> dict[str, str]:
        """Default ``{ParcelModel_field: source_column}``` for this data type."""

    @property
    def columns(self) -> dict[str, str]:
        """Effective column map (defaults overlaid with any overrides)."""
        return {**self.default_columns(), **self._column_map}

    @staticmethod
    def _clean(value: Any) -> str:
        """Normalize a raw attribute value to a trimmed string."""
        if value is None:
            return ""
        if isinstance(value, float) and math.isnan(value):
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def map_record(self, record: Mapping[str, Any]) -> dict[str, str]:
        """Return the four parcel attributes for a single source ``record``."""
        return {field: self._clean(record.get(self.columns[field])) for field in PARCEL_FIELDS}


class OSMParcelFieldMapper(ParcelFieldMapper):
    """Default mapper matching historical OSM/Overpass column names."""

    def default_columns(self) -> dict[str, str]:
        return {
            "building_type": "building",
            "city": "addr:city",
            "state": "addr:state",
            "postal_address": "addr:postcode",
        }


class GISParcelFieldMapper(ParcelFieldMapper):
    """Generic mapper for public GIS/FeatureServer parcel layers.

    Column names vary by layer; override them via ``column_map`` to match the
    service's schema (e.g. ``{"city": "CITY", "postal_address": "ZIP"}``).
    """

    def default_columns(self) -> dict[str, str]:
        return {
            "building_type": "Building",
            "city": "City",
            "state": "State",
            "postal_address": "Address",
        }


def _build_query_url(
    base_url: str, layer: int | str | None, where: str, out_fields: str, out_crs: str
) -> str:
    """Build a FeatureServer ``query`` URL returning JSON geometry in ``out_crs``."""
    url = base_url.rstrip("/")
    if "/FeatureServer/" not in url:
        layer_id = layer if layer is not None else 0
        url = f"{url}/FeatureServer/{layer_id}"
    params = {
        "where": where,
        "outFields": out_fields,
        "f": "json",
        "returnGeometry": "true",
        "outSR": out_crs.split(":")[-1],
    }
    return f"{url}/query?{urlencode(params)}"


def _fetch_features(query_url: str, timeout: float) -> list[dict]:
    """GET a FeatureServer query endpoint and return its ``features`` list."""
    response = requests.get(query_url, timeout=timeout)
    if response.status_code != 200:
        raise InvalidInputError(
            f"FeatureServer request failed with status {response.status_code}: {query_url}"
        )
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        error = data["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise InvalidInputError(f"ArcGIS FeatureServer error: {message}")
    return data.get("features", [])


def _features_to_geodataframe(features: list[dict], out_crs: str) -> gpd.GeoDataFrame:
    """Turn ArcGIS ``features`` into a GeoDataFrame in ``out_crs``.

    ArcGIS FeatureServer geometries use ``rings``/``paths`` (and ``x``/``y`` for
    points) rather than GeoJSON ``coordinates``, so they are normalized first.
    """
    geometries: list = []
    attributes: list[dict] = []
    for feature in features:
        geometry_dict = feature.get("geometry")
        if not geometry_dict:
            continue
        geometries.append(shapely_shape(_normalize_geometry(geometry_dict)))
        attributes.append(feature.get("attributes") or {})
    return gpd.GeoDataFrame(attributes, geometry=geometries, crs=out_crs)


def _normalize_geometry(geometry_dict: dict) -> dict:
    """Convert an ArcGIS geometry dict to GeoJSON ``shape()``-compatible form."""
    geom_type = (geometry_dict.get("type") or "").lower()
    if geom_type == "polygon":
        return {"type": "Polygon", "coordinates": geometry_dict["rings"]}
    if geom_type == "multipolygon":
        return {"type": "MultiPolygon", "coordinates": geometry_dict["paths"]}
    if geom_type == "point":
        return {"type": "Point", "coordinates": [geometry_dict.get("x"), geometry_dict.get("y")]}
    if geom_type in ("linestring", "multilinestring"):
        key = "paths" if "paths" in geometry_dict else "coordinates"
        return {"type": geometry_dict["type"], "coordinates": geometry_dict[key]}
    # ArcGIS points omit the "type" key and use {x, y, spatialReference}.
    if "x" in geometry_dict and "y" in geometry_dict:
        return {"type": "Point", "coordinates": [geometry_dict["x"], geometry_dict["y"]]}
    return geometry_dict


def parcels_from_gis(
    url: str,
    *,
    layer: int | str | None = None,
    mapper: ParcelFieldMapper | None = None,
    out_crs: str = "EPSG:4326",
    where: str = "1=1",
    out_fields: str = "*",
    id_field: str | None = None,
    request_timeout: float = 60.0,
) -> list[ParcelModel]:
    """Fetch building/parcel features from a public ArcGIS FeatureServer layer.

    The REST ``query`` endpoint is used (no Esri login required). Geometry is
    requested in ``out_crs`` (default WGS84); because :class:`ParcelModel`
    coordinates are longitude/latitude, use EPSG:4326.

        Parameters
        ----------
        url
            FeatureServer URL, e.g.
            ``https://gis.colorado.gov/public/rest/services/.../FeatureServer/0``.
            A service root without a layer defaults to feature layer 0.
        layer
            Feature layer index/name when ``url`` points at the service root.
        mapper
            Column-to-field mapper; defaults to :class:`GISParcelFieldMapper`.
        out_crs
            Spatial reference requested from the service for returned geometry.
            Must be EPSG:4326 (WGS84) since :class:`ParcelModel` uses lon/lat.
        where
            SQL-style filter (default selects all rows).
        out_fields
            Comma-separated output fields, or ``"*"`` for all.
        id_field
            Attribute column to use as the parcel name when present; otherwise
            parcels are named ``parcel_{index}``.
        request_timeout
            Per-request timeout in seconds.

        Returns
        -------
        list[ParcelModel]
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidInputError("url must be a non-empty FeatureServer URL.")

    from shift.parcel import parcels_from_geodataframe

    query_url = _build_query_url(url, layer, where, out_fields, out_crs)
    features = _fetch_features(query_url, request_timeout)
    if not features:
        logger.info(f"No features returned from {query_url}")
        return []

    # ParcelModel coordinates are longitude/latitude, so geometry must be WGS84.
    gdf = _features_to_geodataframe(features, out_crs)

    return parcels_from_geodataframe(
        gdf, mapper=mapper or GISParcelFieldMapper(), name_column=id_field
    )
