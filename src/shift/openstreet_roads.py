from infrasys.quantities import Distance
import socket
import networkx as nx
from loguru import logger
import osmnx as ox
from shapely import Polygon

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError

DIST_TYPE = "bbox"
NETWORK_TYPE = "drive"

# Highway types considered "public roads" for distribution line routing.
# Excludes service roads, alleys, driveways, footpaths, cycleways, tracks.
_PUBLIC_ROAD_TYPES = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "unclassified",
    "living_street",
}

# Public Overpass mirrors for automatic failover.
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def _get_default_overpass_url() -> str | None:
    """Return the currently configured OSMnx Overpass endpoint."""
    if hasattr(ox.settings, "overpass_url"):
        return getattr(ox.settings, "overpass_url")
    if hasattr(ox.settings, "overpass_endpoint"):
        return getattr(ox.settings, "overpass_endpoint")
    return None


def _set_overpass_url(url: str) -> None:
    """Set the OSMnx Overpass endpoint."""
    if hasattr(ox.settings, "overpass_url"):
        setattr(ox.settings, "overpass_url", url)
    elif hasattr(ox.settings, "overpass_endpoint"):
        setattr(ox.settings, "overpass_endpoint", url)


def _fetch_graph_with_failover(fetch_fn):
    """Try fetch_fn across Overpass mirrors, returning first success."""
    original_url = _get_default_overpass_url()

    # Build endpoint list: current default + mirrors (deduplicated).
    endpoints = [original_url] if original_url else []
    for mirror in _OVERPASS_MIRRORS:
        if mirror not in endpoints:
            endpoints.append(mirror)

    # Save original settings.
    old_timeout = getattr(ox.settings, "timeout", None)
    old_http_timeout = getattr(ox.settings, "requests_timeout", None)

    # Set short timeouts so unreachable mirrors fail fast.
    if old_timeout is not None:
        ox.settings.timeout = 5
    if hasattr(ox.settings, "requests_timeout"):
        ox.settings.requests_timeout = 5

    # Hard Python socket timeout as backstop (5s).
    old_socket_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)

    last_exc = None
    for endpoint in endpoints:
        _set_overpass_url(endpoint)
        try:
            logger.debug(f"Trying Overpass endpoint: {endpoint}")
            result = fetch_fn()
            logger.debug(f"Success via {endpoint}")
            socket.setdefaulttimeout(old_socket_timeout)
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.debug(f"Overpass endpoint {endpoint} failed: {exc!s:.120}")

    # Restore original settings before raising.
    socket.setdefaulttimeout(old_socket_timeout)
    if original_url:
        _set_overpass_url(original_url)
    if old_timeout is not None:
        ox.settings.timeout = old_timeout
    if old_http_timeout is not None and hasattr(ox.settings, "requests_timeout"):
        ox.settings.requests_timeout = old_http_timeout
    raise last_exc  # type: ignore[misc]


# Path to local PBF file (set via environment or config)
_LOCAL_PBF_PATH: str | None = None


def set_local_pbf(path: str | None) -> None:
    """Configure a local PBF file for offline road/building extraction."""
    global _LOCAL_PBF_PATH  # noqa: PLW0603
    _LOCAL_PBF_PATH = path
    if path:
        logger.info(f"Local PBF configured: {path}")


def get_local_pbf() -> str | None:
    """Return the configured local PBF path."""
    return _LOCAL_PBF_PATH


def extract_from_pbf(
    bbox: tuple[float, float, float, float], output_path: str | None = None
) -> str:
    """Extract a bbox from the configured PBF file using osmium.

    Parameters
    ----------
    bbox : tuple[float, float, float, float]
        (min_lon, min_lat, max_lon, max_lat)
    output_path : str | None
        Output OSM XML path. Auto-generated if None.

    Returns
    -------
    str
        Path to the extracted OSM XML file.
    """
    import subprocess
    import tempfile

    if not _LOCAL_PBF_PATH:
        raise ValueError("No local PBF configured. Call set_local_pbf() first.")

    if output_path is None:
        output_path = tempfile.mkstemp(suffix=".osm")[1]

    min_lon, min_lat, max_lon, max_lat = bbox
    bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    result = subprocess.run(
        [
            "osmium",
            "extract",
            f"--bbox={bbox_str}",
            "--strategy=complete_ways",
            _LOCAL_PBF_PATH,
            "-o",
            output_path,
            "--overwrite",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osmium extract failed: {result.stderr}")
    logger.debug(f"Extracted bbox {bbox_str} → {output_path}")
    return output_path


def get_road_network_from_xml(xml_path: str, reduce_to_mst: bool = True) -> nx.Graph:
    """Load road network from a local OSM XML file, filtered to public roads only."""
    graph = ox.graph_from_xml(xml_path)
    undirected = graph.to_undirected()

    # Filter to public road types (PBF/XML loads everything)
    edges_to_remove = []
    for u, v, data in undirected.edges(data=True):
        highway = data.get("highway", "")
        # highway can be a list if multiple tags
        if isinstance(highway, list):
            if not any(h in _PUBLIC_ROAD_TYPES for h in highway):
                edges_to_remove.append((u, v))
        elif highway not in _PUBLIC_ROAD_TYPES:
            edges_to_remove.append((u, v))

    if edges_to_remove:
        undirected.remove_edges_from(edges_to_remove)
        # Remove isolated nodes
        isolates = list(nx.isolates(undirected))
        undirected.remove_nodes_from(isolates)
        logger.debug(
            f"Filtered to public roads: removed {len(edges_to_remove)} non-public edges, {len(isolates)} isolated nodes"
        )

    if reduce_to_mst:
        return nx.minimum_spanning_tree(undirected)
    return undirected


def _filter_graph_by_polygon(graph: nx.Graph, polygon) -> nx.Graph:
    """Remove road nodes outside the polygon, keep largest connected component."""
    from shapely.geometry import Point as _SPoint

    nodes_to_remove = []
    for node, data in graph.nodes(data=True):
        if "x" in data and "y" in data:
            if not polygon.contains(_SPoint(data["x"], data["y"])):
                nodes_to_remove.append(node)

    if nodes_to_remove:
        graph = graph.copy()
        graph.remove_nodes_from(nodes_to_remove)

    # Keep only the largest connected component
    if graph.number_of_nodes() > 0:
        components = list(nx.connected_components(graph))
        if components:
            largest = max(components, key=len)
            graph = graph.subgraph(largest).copy()

    return graph


def get_road_network(  # noqa: C901
    location: str | GeoLocation | list[GeoLocation] | Polygon,
    max_distance: Distance = Distance(500, "m"),
    reduce_to_mst: bool = True,
) -> nx.Graph:
    """Function to return networkx graph representation for a road network.

    Note max_distance is not used if location type is Polygon.
    For a location of type str and GeoLocation, a polygon
    is created by forming a sqaure bounding box using max distance.
    We use osmnx package to fetch road network

    Parameters
    ----------
        location : str | GeoLocation | Polygon
            Location for which openstreet parcels
            are to be fetched.
        max_distance : Distance
            Maximum distance to form a bounding box
            within which buildings are fetched.
        reduce_to_mst : bool, optional
            Whether to reduce the graph to its minimum spanning tree.
            Defaults to True (original behavior). Set to False to get
            the full road network graph (useful for FullRoadGraphStrategy).

    Returns
    -------
        nx.Graph
            Instance of nx.Graph.

    Examples
    --------
    >>> get_road_network("Fort Worth, Texas", Distance(100, "m"))
    """
    logger.debug(f"Attempting to fecth road network for {location}")

    # Try local PBF first if configured
    if _LOCAL_PBF_PATH:
        try:
            if isinstance(location, Polygon):
                bounds = location.bounds  # (minx, miny, maxx, maxy)
            elif isinstance(location, list):
                lons = [
                    pt[0] if isinstance(pt, (tuple, list)) else pt.longitude for pt in location
                ]
                lats = [pt[1] if isinstance(pt, (tuple, list)) else pt.latitude for pt in location]
                bounds = (min(lons), min(lats), max(lons), max(lats))
            elif isinstance(location, GeoLocation):
                d = max_distance.to("m").magnitude / 111139  # rough deg
                bounds = (
                    location.longitude - d,
                    location.latitude - d,
                    location.longitude + d,
                    location.latitude + d,
                )
            else:
                bounds = None

            if bounds:
                xml_path = extract_from_pbf(bounds)
                try:
                    graph = get_road_network_from_xml(xml_path, reduce_to_mst)
                    logger.debug(
                        f"Road network loaded from local PBF ({graph.number_of_nodes()} nodes)"
                    )
                    return graph
                finally:
                    import os

                    os.unlink(xml_path) if os.path.exists(xml_path) else None
        except Exception as exc:
            logger.debug(f"Local PBF road extraction failed: {exc}, falling back to Overpass")

    def _fetch():
        if isinstance(location, str):
            return ox.graph_from_address(
                location, dist=max_distance.to("m"), dist_type=DIST_TYPE, network_type=NETWORK_TYPE
            )
        elif isinstance(location, GeoLocation):
            return ox.graph_from_point(
                list(reversed(location)),
                dist=max_distance.to("m").magnitude,
                dist_type=DIST_TYPE,
                network_type=NETWORK_TYPE,
            )
        elif isinstance(location, list):
            return ox.graph_from_polygon(Polygon(location), network_type=NETWORK_TYPE)
        elif isinstance(location, Polygon):
            return ox.graph_from_polygon(location, network_type=NETWORK_TYPE)
        else:
            msg = f"Invalid {location=} passed."
            raise InvalidInputError(msg)

    graph = _fetch_graph_with_failover(_fetch)

    undirected = graph.to_undirected()

    # Filter to public road types only
    edges_to_remove = []
    for u, v, data in undirected.edges(data=True):
        highway = data.get("highway", "")
        if isinstance(highway, list):
            if not any(h in _PUBLIC_ROAD_TYPES for h in highway):
                edges_to_remove.append((u, v))
        elif highway not in _PUBLIC_ROAD_TYPES:
            edges_to_remove.append((u, v))

    if edges_to_remove:
        undirected.remove_edges_from(edges_to_remove)
        isolates = list(nx.isolates(undirected))
        undirected.remove_nodes_from(isolates)
        logger.debug(f"Filtered to public roads: removed {len(edges_to_remove)} non-public edges")

    if reduce_to_mst:
        return nx.minimum_spanning_tree(undirected)
    return undirected
