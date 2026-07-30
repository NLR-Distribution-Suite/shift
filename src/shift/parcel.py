from infrasys.quantities import Distance
from shapely.geometry import Polygon
from geopandas import GeoDataFrame
from loguru import logger
import osmnx as ox
import shapely

from shift.data_model import ParcelModel, GeoLocation
from shift.exceptions import InvalidInputError
from shift.openstreet_roads import _fetch_graph_with_failover

from pathlib import Path

import pandas as pd
from shapely import wkt


def parcels_from_geodataframe(geo_df: GeoDataFrame) -> list[ParcelModel]:
    """Function to convert geopandas dataframe to list of parcel models.

    Args:
        geo_df (GeoDataFrame): Geo dataframe.

    Returns:
        list[ParcelModel]
    """
    logger.info(f"Length of geodataframe: {len(geo_df)}, CRS: {geo_df.crs}")
    parcels: list[ParcelModel] = []
    for idx, geometry in enumerate(geo_df.to_dict(orient="records")):
        name = f"parcel_{idx}"
        geometry_obj = geometry["geometry"]
        match geometry_obj.geom_type:
            case "Point":
                parcels.append(
                    ParcelModel(
                        name=name,
                        geometry=GeoLocation(*list(geometry_obj.coords)[0]),
                        building_type=geometry["building"]
                        if "building" in geometry and isinstance(geometry["building"], str)
                        else "",
                        city=geometry["addr:city"]
                        if "addr:city" in geometry and isinstance(geometry["addr:city"], str)
                        else "",
                        state=geometry["addr:state"]
                        if "addr:state" in geometry and isinstance(geometry["addr:state"], str)
                        else "",
                        postal_address=geometry["addr:postcode"]
                        if "addr:postcode" in geometry
                        and isinstance(geometry["addr:postcode"], str)
                        else "",
                    )
                )
            case "Polygon":
                parcels.append(
                    ParcelModel(
                        name=name,
                        geometry=[GeoLocation(*coord) for coord in geometry_obj.exterior.coords],
                        building_type=geometry["building"]
                        if "building" in geometry and isinstance(geometry["building"], str)
                        else "",
                        city=geometry["addr:city"]
                        if "addr:city" in geometry and isinstance(geometry["addr:city"], str)
                        else "",
                        state=geometry["addr:state"]
                        if "addr:state" in geometry and isinstance(geometry["addr:state"], str)
                        else "",
                        postal_address=geometry["addr:postcode"]
                        if "addr:postcode" in geometry
                        and isinstance(geometry["addr:postcode"], str)
                        else "",
                    )
                )
            case "MultiPolygon":
                parcels.append(
                    ParcelModel(
                        name=name,
                        geometry=[
                            GeoLocation(*coord)
                            for coord in geometry_obj.convex_hull.exterior.coords
                        ],
                        building_type=geometry["building"]
                        if "building" in geometry and isinstance(geometry["building"], str)
                        else "",
                        city=geometry["addr:city"]
                        if "addr:city" in geometry and isinstance(geometry["addr:city"], str)
                        else "",
                        state=geometry["addr:state"]
                        if "addr:state" in geometry and isinstance(geometry["addr:state"], str)
                        else "",
                        postal_address=geometry["addr:postcode"]
                        if "addr:postcode" in geometry
                        and isinstance(geometry["addr:postcode"], str)
                        else "",
                    )
                )
            case _:
                logger.warning(f"{geometry_obj.geom_type} is not supported.")
    logger.info(f"Number of parcels: {len(parcels)}")
    return parcels


def parcels_from_csv(file_path: Path):
    """Function to load parcels from csv.

    Note, this function uses geopandas to construct geo dataframe
    which requires that you have at least a column named `geometry` in your file.

    Parameters
    ----------
    file_path: Path to csv file with geometries.
    """

    df = pd.read_csv(file_path)
    if "geometry" not in df.columns:
        msg = f"geometry column missing csv file {file_path=}"
        raise InvalidInputError(msg)
    df["geometry"] = df["geometry"].apply(wkt.loads)
    return parcels_from_geodataframe(GeoDataFrame(df))


def parcels_from_location(
    location: str | GeoLocation | list[GeoLocation], max_distance: Distance = Distance(500, "m")
) -> list[ParcelModel] | None:
    """Function to return parcels for a given location.

    Note max_distance is not used if location type is Polygon.
    For a location of type str and GeoLocation, a polygon
    is created by forming a sqaure bounding box using max distance.
    We use osmnx package to fetch these buildings.

    Parameters
    ----------
        location : str | GeoLocation | Polygon
            Location for which openstreet parcels
            are to be fetched.
        max_distance : Distance
            Maximum distance to form a bounding box
            within which buildings are fetched.

    Returns
    -------
        list[ParcelModel]
            List of `ParcelModel`.

    Examples
    --------
    >>> from shift.parcel.openstreet import get_parcels
    >>> from infrasys.quantities import Distance
    >>> get_parcels("Fort Worth, Texas", Distance(100, "m"))
    """
    logger.info(f"Attempting to fetch parcels for {location}")
    tags = {"building": True}
    if isinstance(location, str):
        return parcels_from_geodataframe(
            _fetch_graph_with_failover(
                lambda: ox.features_from_address(
                    location, tags, dist=max_distance.to("m").magnitude
                )
            )
        )
    elif isinstance(location, GeoLocation):
        return parcels_from_geodataframe(
            _fetch_graph_with_failover(
                lambda: ox.features_from_point(
                    list(reversed(location)), tags, dist=max_distance.to("m").magnitude
                )
            )
        )
    elif isinstance(location, list):
        return parcels_from_geodataframe(
            _fetch_graph_with_failover(
                lambda: ox.features_from_polygon(shapely.Polygon(location), tags)
            )
        )


def get_parcels_in_polygon(coordinates: list[list[float, float]] | Polygon) -> list[ParcelModel]:
    if isinstance(coordinates, Polygon):
        coordinates = [list(reversed(coord)) for coord in coordinates.exterior.coords]
    return parcels_from_location(coordinates)


def parcels_from_pbf(  # noqa: C901
    polygon: list[GeoLocation] | list[list[float]] | Polygon,
) -> list[ParcelModel]:
    """Extract building parcels from the configured local PBF within a polygon.

    Uses ``osmium`` to cut the polygon's bounding box out of the configured
    local ``.pbf`` file, then parses building ways from the resulting OSM XML
    and keeps those whose centroid falls inside the polygon. This mirrors the
    SHIFT web UI's ``/api/parcels/fetch-local`` offline path and requires a PBF
    configured via :func:`shift.openstreet_roads.set_local_pbf`.
    """

    from shapely.geometry import Point as _SPoint, Polygon as _SPolygon

    from shift.openstreet_roads import extract_from_pbf, get_local_pbf

    if not get_local_pbf():
        raise ValueError("No local PBF configured. Call set_local_pbf() first.")

    if isinstance(polygon, Polygon):
        raw_pts = [(x, y) for x, y in polygon.exterior.coords]
    else:
        raw_pts = []
        for point in polygon:
            if isinstance(point, GeoLocation):
                raw_pts.append((point.longitude, point.latitude))
            elif isinstance(point, (list, tuple)):
                raw_pts.append((float(point[0]), float(point[1])))
            else:
                raw_pts.append((point.longitude, point.latitude))

    if len(raw_pts) < 3:
        raise InvalidInputError("Polygon needs at least 3 points.")

    lons = [lon for lon, _ in raw_pts]
    lats = [lat for _, lat in raw_pts]
    bbox = (min(lons), min(lats), max(lons), max(lats))

    xml_path = extract_from_pbf(bbox)
    try:
        import defusedxml.ElementTree as _SafeET

        root = _SafeET.parse(xml_path).getroot()

        nodes_map: dict[str, tuple[float, float]] = {}
        for node_el in root.findall("node"):
            nid = node_el.get("id")
            nodes_map[nid] = (float(node_el.get("lon")), float(node_el.get("lat")))

        user_polygon = _SPolygon(raw_pts)
        parcels: list[ParcelModel] = []
        for way_el in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way_el.findall("tag")}
            if "building" not in tags:
                continue
            coords = [
                nodes_map[nd.get("ref")]
                for nd in way_el.findall("nd")
                if nd.get("ref") in nodes_map
            ]
            if len(coords) < 3:
                continue
            avg_lon = sum(c[0] for c in coords) / len(coords)
            avg_lat = sum(c[1] for c in coords) / len(coords)
            if not user_polygon.contains(_SPoint(avg_lon, avg_lat)):
                continue

            building_type = tags.get("building", "yes")
            parcels.append(
                ParcelModel(
                    name=f"parcel_{len(parcels)}",
                    geometry=[GeoLocation(lon, lat) for lon, lat in coords],
                    building_type=building_type if isinstance(building_type, str) else "yes",
                    city=tags.get("addr:city", "") or "",
                    state=tags.get("addr:state", "") or "",
                    postal_address=tags.get("addr:street", "") or "",
                )
            )
        logger.info(f"Extracted {len(parcels)} parcels from local PBF for polygon bbox {bbox}")
        return parcels
    finally:
        Path(xml_path).unlink(missing_ok=True)
