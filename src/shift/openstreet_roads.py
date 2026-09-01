from infrasys.quantities import Distance
import networkx as nx
from loguru import logger
import osmnx as ox
from shapely import Polygon

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError
from shift.utils.overpass import fetch_with_overpass_failover

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


def _write_osm_xml(
    output_path: str,
    nodes_data: dict[int, tuple[float, float, dict[str, str]]],
    selected_ways: dict[int, list[int]],
    way_tags: dict[int, dict[str, str]],
) -> None:
    """Write nodes and ways as an OSM XML file (tag values safely escaped)."""
    import re
    from xml.sax.saxutils import escape

    _invalid_xml_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def _xml_attr(value: str) -> str:
        return escape(_invalid_xml_chars.sub("", str(value)), {'"': "&quot;", "'": "&apos;"})

    with open(output_path, "w", encoding="utf-8") as fpointer:
        fpointer.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fpointer.write('<osm version="0.6" generator="pyosmium">\n')
        for node_id, (lon, lat, tags) in sorted(nodes_data.items()):
            fpointer.write(f'<node id="{node_id}" lat="{lat}" lon="{lon}">')
            for key, value in tags.items():
                fpointer.write(f'<tag k="{_xml_attr(key)}" v="{_xml_attr(value)}"/>')
            fpointer.write("</node>\n")
        for way_id, refs in sorted(selected_ways.items()):
            fpointer.write(f'<way id="{way_id}">')
            for key, value in way_tags[way_id].items():
                fpointer.write(f'<tag k="{_xml_attr(key)}" v="{_xml_attr(value)}"/>')
            for ref in refs:
                fpointer.write(f'<nd ref="{ref}"/>')
            fpointer.write("</way>\n")
        fpointer.write("</osm>\n")


def _extract_from_pbf_pyosmium(bbox: tuple[float, float, float, float], output_path: str) -> str:
    """Extract a bbox from the configured PBF using pyosmium (no CLI required).

    Mirrors ``osmium extract --strategy=complete_ways``: keeps every way that
    has at least one node inside the bbox along with all of that way's nodes.
    Falls back to pyosmium when the ``osmium`` command-line tool is unavailable.
    """
    import osmium

    min_lon, min_lat, max_lon, max_lat = bbox

    nodes_in_bbox: set[int] = set()
    way_node_refs: dict[int, list[int]] = {}
    way_tags: dict[int, dict[str, str]] = {}

    class _WayCollector(osmium.SimpleHandler):
        def node(self, node):
            loc = node.location
            if min_lon <= loc.lon <= max_lon and min_lat <= loc.lat <= max_lat:
                nodes_in_bbox.add(node.id)

        def way(self, way):
            way_node_refs[way.id] = [node.ref for node in way.nodes]
            way_tags[way.id] = {tag.k: tag.v for tag in way.tags}

    _WayCollector().apply_file(_LOCAL_PBF_PATH)

    selected_ways = {
        way_id: refs
        for way_id, refs in way_node_refs.items()
        if any(ref in nodes_in_bbox for ref in refs)
    }
    needed_nodes: set[int] = set()
    for refs in selected_ways.values():
        needed_nodes.update(refs)

    nodes_data: dict[int, tuple[float, float, dict[str, str]]] = {}

    class _NodeCollector(osmium.SimpleHandler):
        def node(self, node):
            if node.id in needed_nodes:
                nodes_data[node.id] = (
                    node.location.lon,
                    node.location.lat,
                    {tag.k: tag.v for tag in node.tags},
                )

    _NodeCollector().apply_file(_LOCAL_PBF_PATH)

    _write_osm_xml(output_path, nodes_data, selected_ways, way_tags)
    return output_path


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
    import shutil
    import subprocess
    import tempfile

    if not _LOCAL_PBF_PATH:
        raise ValueError("No local PBF configured. Call set_local_pbf() first.")

    if output_path is None:
        output_path = tempfile.mkstemp(suffix=".osm")[1]

    if shutil.which("osmium") is None:
        logger.debug("osmium CLI not found; using pyosmium extraction.")
        return _extract_from_pbf_pyosmium(bbox, output_path)

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
    # Keep every node and skip simplification: osmnx's default
    # largest-component + simplify collapses small/fragmented extracts (e.g. a
    # tight residential bbox) down to an empty graph.
    graph = ox.graph_from_xml(xml_path, retain_all=True, simplify=False)
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
        if undirected.number_of_nodes() > 0:
            largest = max(nx.connected_components(undirected), key=len)
            undirected = undirected.subgraph(largest).copy()
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


def _try_local_pbf_road_network(location, max_distance, reduce_to_mst) -> nx.Graph | None:
    """Attempt to load a road network from local PBF. Returns None on failure."""
    if not _LOCAL_PBF_PATH:
        return None

    try:
        if isinstance(location, Polygon):
            bounds = location.bounds
        elif isinstance(location, list):
            lons = [pt[0] if isinstance(pt, (tuple, list)) else pt.longitude for pt in location]
            lats = [pt[1] if isinstance(pt, (tuple, list)) else pt.latitude for pt in location]
            bounds = (min(lons), min(lats), max(lons), max(lats))
        elif isinstance(location, GeoLocation):
            d = max_distance.to("m").magnitude / 111139
            bounds = (
                location.longitude - d,
                location.latitude - d,
                location.longitude + d,
                location.latitude + d,
            )
        else:
            return None

        xml_path = extract_from_pbf(bounds)
        try:
            graph = get_road_network_from_xml(xml_path, reduce_to_mst)
            logger.debug(f"Road network loaded from local PBF ({graph.number_of_nodes()} nodes)")
            return graph
        finally:
            import os

            if os.path.exists(xml_path):
                os.unlink(xml_path)
    except Exception as exc:
        logger.debug(f"Local PBF road extraction failed: {exc}, falling back to Overpass")
        return None


def _fetch_road_graph_by_location(location, max_distance):
    """Fetch road graph from OSM based on location type."""
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


def _filter_to_public_roads(graph: nx.Graph) -> nx.Graph:
    """Remove non-public road edges and resulting isolate nodes from graph."""
    edges_to_remove = []
    for u, v, data in graph.edges(data=True):
        highway = data.get("highway", "")
        if isinstance(highway, list):
            if not any(h in _PUBLIC_ROAD_TYPES for h in highway):
                edges_to_remove.append((u, v))
        elif highway not in _PUBLIC_ROAD_TYPES:
            edges_to_remove.append((u, v))

    if edges_to_remove:
        graph.remove_edges_from(edges_to_remove)
        isolates = list(nx.isolates(graph))
        graph.remove_nodes_from(isolates)
        logger.debug(f"Filtered to public roads: removed {len(edges_to_remove)} non-public edges")
    return graph


def get_road_network(
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
    pbf_result = _try_local_pbf_road_network(location, max_distance, reduce_to_mst)
    if pbf_result is not None:
        return pbf_result

    graph, _, _, _ = fetch_with_overpass_failover(
        lambda: _fetch_road_graph_by_location(location, max_distance)
    )

    undirected = graph.to_undirected()
    undirected = _filter_to_public_roads(undirected)

    if reduce_to_mst:
        if undirected.number_of_nodes() > 0:
            largest = max(nx.connected_components(undirected), key=len)
            undirected = undirected.subgraph(largest).copy()
        return nx.minimum_spanning_tree(undirected)
    return undirected
