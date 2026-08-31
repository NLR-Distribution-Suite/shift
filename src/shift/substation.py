import requests
import geopandas as gpd
from shapely.geometry import Polygon

from shift.utils.overpass import OVERPASS_MIRRORS

# Primary mirror's interpreter endpoint (raw Overpass query, not via OSMnx).
OVERPASS_URL = f"{OVERPASS_MIRRORS[0]}/interpreter"


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

    response = requests.post(
        OVERPASS_URL,
        data=query,
        timeout=360,
    )
    response.raise_for_status()

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
                "osm_type": element["type"],
                "osm_id": element["id"],
                **tags,
                "geometry": geometry,
            }
        )

    return gpd.GeoDataFrame.from_features(
        features,
        crs="EPSG:4326",
    )
