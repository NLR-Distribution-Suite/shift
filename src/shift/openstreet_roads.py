from infrasys.quantities import Distance
import networkx as nx
from loguru import logger
import osmnx as ox
from shapely import Polygon

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError

DIST_TYPE = "bbox"
NETWORK_TYPE = "drive"


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

    if isinstance(location, str):
        graph = ox.graph_from_address(
            location, dist=max_distance.to("m"), dist_type=DIST_TYPE, network_type=NETWORK_TYPE
        )

    elif isinstance(location, GeoLocation):
        graph = ox.graph_from_point(
            list(reversed(location)),
            dist=max_distance.to("m").magnitude,
            dist_type=DIST_TYPE,
            network_type=NETWORK_TYPE,
        )
    elif isinstance(location, list):
        graph = ox.graph_from_polygon(Polygon(location), network_type=NETWORK_TYPE)
    elif isinstance(location, Polygon):
        graph = ox.graph_from_polygon(location, network_type=NETWORK_TYPE)

    else:
        msg = f"Invalid {location=} passed."
        raise InvalidInputError(msg)

    undirected = graph.to_undirected()
    if reduce_to_mst:
        return nx.minimum_spanning_tree(undirected)
    return undirected
