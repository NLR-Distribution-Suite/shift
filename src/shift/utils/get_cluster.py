from __future__ import annotations

from sklearn.cluster import KMeans
import numpy as np
from pyproj import Geod

from shift.data_model import GeoLocation, GroupModel

_GEOD = Geod(ellps="WGS84")


def get_kmeans_clusters(num_cluster: int, points: list[GeoLocation]) -> list[GroupModel]:
    """Cluster geographic points using K-means algorithm.

    This function groups a set of geographic locations into clusters using the
    K-means clustering algorithm. Each cluster contains a center point and all
    points assigned to that cluster.

    The algorithm minimizes the sum of squared distances between points and their
    assigned cluster centers. This is useful for grouping nearby loads or parcels
    in distribution system modeling.

    Parameters
    ----------
    num_cluster : int
        Number of clusters to create. Must be less than or equal to the number
        of input points.
    points : list[GeoLocation]
        List of geographic locations to cluster. Each point should be a GeoLocation
        namedtuple with longitude and latitude.

    Returns
    -------
    list[GroupModel]
        List of cluster models, where each model contains:
        - center: GeoLocation of the cluster centroid
        - points: List of GeoLocation objects assigned to this cluster

    Notes
    -----
    - Uses scikit-learn's KMeans implementation with random_state=0 for reproducibility
    - Points are treated as Euclidean coordinates; consider projection for large areas
    - Empty clusters are possible if num_cluster is too large relative to point distribution

    Examples
    --------
    >>> from shift import get_kmeans_clusters, GeoLocation
    >>> points = [
    ...     GeoLocation(-97.33, 32.75),
    ...     GeoLocation(-97.32, 32.76),
    ...     GeoLocation(-97.35, 32.77),
    ... ]
    >>> clusters = get_kmeans_clusters(2, points)
    >>> len(clusters)
    2

    """

    clusters = KMeans(n_clusters=num_cluster, random_state=0).fit(points)

    return [
        GroupModel(
            center=GeoLocation(*center),
            points=[GeoLocation(*el) for el in np.array(points)[clusters.labels_ == idx]],
        )
        for idx, center in enumerate(clusters.cluster_centers_)
    ]


def estimate_load_kva(area_m2: float, building_type: str | None) -> float:
    """Estimate a parcel's connected load in kVA from its footprint and type.

    Uses a coarse power-density (kVA per square metre) that varies with the
    building's usage. A small floor keeps tiny or point-only parcels from
    collapsing to a near-zero weight.

    Parameters
    ----------
    area_m2 : float
        Parcel footprint area in square metres (0 for point geometries).
    building_type : str | None
        OpenStreetMap-style building tag (e.g. ``"residential"``, ``"retail"``).

    Returns
    -------
    float
        Estimated load in kVA (minimum 5.0).
    """
    btype = (building_type or "").lower()
    kva_per_m2 = 0.02

    if any(tag in btype for tag in ["industrial", "factory", "warehouse"]):
        kva_per_m2 = 0.05
    elif any(tag in btype for tag in ["commercial", "retail", "office", "school"]):
        kva_per_m2 = 0.035
    elif any(tag in btype for tag in ["hospital", "data", "critical"]):
        kva_per_m2 = 0.06
    elif any(tag in btype for tag in ["house", "residential", "apartments", "dorm"]):
        kva_per_m2 = 0.02

    return max(5.0, area_m2 * kva_per_m2)


def _point_lonlat(point) -> tuple[float, float]:
    """Read ``(longitude, latitude)`` from a dict or an object with those attrs."""
    if isinstance(point, dict):
        return float(point["longitude"]), float(point["latitude"])
    return float(point.longitude), float(point.latitude)


def centroid_and_area_m2(geometry) -> tuple[GeoLocation, float]:
    """Return the ``(centroid, geodesic area in m^2)`` for a parcel geometry.

    ``geometry`` may be a polygon (a list of vertices) or a single point.
    Vertices may be dicts with ``longitude``/``latitude`` keys or objects
    exposing those attributes. Point geometries yield an area of ``0.0``.
    """
    # GeoLocation is a NamedTuple, so it must be detected as a point before the
    # generic tuple branch (which would otherwise iterate over its floats).
    if hasattr(geometry, "longitude") and hasattr(geometry, "latitude"):
        return GeoLocation(float(geometry.longitude), float(geometry.latitude)), 0.0
    if isinstance(geometry, (list, tuple)):
        lons = [_point_lonlat(p)[0] for p in geometry]
        lats = [_point_lonlat(p)[1] for p in geometry]
        if len(lons) < 3:
            return GeoLocation(lons[0], lats[0]), 0.0

        # Close the polygon ring for the geodesic area if not already closed.
        if lons[0] != lons[-1] or lats[0] != lats[-1]:
            lons = [*lons, lons[0]]
            lats = [*lats, lats[0]]

        area_m2, _ = _GEOD.polygon_area_perimeter(lons, lats)
        centroid = GeoLocation(float(np.mean(lons[:-1])), float(np.mean(lats[:-1])))
        return centroid, abs(float(area_m2))

    lon, lat = _point_lonlat(geometry)
    return GeoLocation(lon, lat), 0.0


def _distance_m(a: GeoLocation, b: GeoLocation) -> float:
    _, _, dist_m = _GEOD.inv(a.longitude, a.latitude, b.longitude, b.latitude)
    return float(abs(dist_m))


def _parcel_attr(parcel, name: str):
    """Read a field from a parcel that may be a dict or an object."""
    if isinstance(parcel, dict):
        return parcel.get(name)
    return getattr(parcel, name, None)


def get_capacity_distance_clusters(  # noqa: C901
    parcels,
    *,
    target_kva_per_transformer: float = 75.0,
    dedicated_transformer_area_m2: float = 2000.0,
    dedicated_transformer_load_kva: float = 150.0,
    max_secondary_length_m: float = 120.0,
    min_clusters: int = 1,
    max_clusters: int | None = None,
) -> list[GroupModel]:
    """Cluster parcels by transformer capacity and secondary-line distance.

    Unlike plain K-means (which only balances geographic proximity for a fixed
    cluster count), this strategy sizes transformer service groups from the
    estimated electrical load of each parcel and a maximum secondary-line reach:

    1. Parcels whose footprint area or estimated load exceeds the "dedicated"
       thresholds each receive their own transformer.
    2. The number of shared transformers is derived from the total remaining
       load divided by ``target_kva_per_transformer`` (bounded by
       ``min_clusters``/``max_clusters``).
    3. Load-weighted K-means seeds transformer centres, then parcels are
       assigned heaviest-first to the nearest centre that still has spare
       capacity and is within ``max_secondary_length_m``. Parcels that cannot be
       placed under those constraints spawn a new dedicated group.

    Parameters
    ----------
    parcels : Sequence
        Parcels as dicts or objects exposing ``geometry`` and ``building_type``.
    target_kva_per_transformer : float
        Target connected load per shared transformer (kVA).
    dedicated_transformer_area_m2 : float
        Footprint area at/above which a parcel gets its own transformer.
    dedicated_transformer_load_kva : float
        Estimated load at/above which a parcel gets its own transformer.
    max_secondary_length_m : float
        Maximum allowed distance from a parcel to its transformer (metres).
    min_clusters, max_clusters : int | None
        Bounds on the number of shared transformers.

    Returns
    -------
    list[GroupModel]
        One group per transformer, each with a ``center`` and member ``points``.
    """
    if not parcels:
        raise ValueError("Capacity-distance clustering requires parcels.")

    dedicated: list[GroupModel] = []
    shared_entries: list[dict] = []
    for parcel in parcels:
        center, area_m2 = centroid_and_area_m2(_parcel_attr(parcel, "geometry"))
        load_kva = estimate_load_kva(area_m2, _parcel_attr(parcel, "building_type"))

        if area_m2 >= dedicated_transformer_area_m2 or load_kva >= dedicated_transformer_load_kva:
            dedicated.append(GroupModel(center=center, points=[center]))
        else:
            shared_entries.append({"point": center, "load_kva": load_kva})

    if not shared_entries:
        return dedicated

    total_load = float(sum(e["load_kva"] for e in shared_entries))
    est_clusters = max(1, int(round(total_load / target_kva_per_transformer)))
    est_clusters = max(min_clusters, est_clusters)
    est_clusters = min(est_clusters, len(shared_entries))
    if max_clusters is not None:
        est_clusters = min(est_clusters, max_clusters)

    coords = np.array([(e["point"].longitude, e["point"].latitude) for e in shared_entries])
    weights = np.array([e["load_kva"] for e in shared_entries])
    model = KMeans(n_clusters=est_clusters, random_state=0)
    model.fit(coords, sample_weight=weights)

    centers: list[GeoLocation] = [
        GeoLocation(float(c[0]), float(c[1])) for c in model.cluster_centers_
    ]
    assignments: list[list[GeoLocation]] = [[] for _ in centers]
    remaining_capacity: list[float] = [target_kva_per_transformer for _ in centers]

    # Assign heaviest parcels first so capacity constraints are respected better.
    ordered = sorted(shared_entries, key=lambda e: e["load_kva"], reverse=True)
    for entry in ordered:
        point = entry["point"]
        load_kva = float(entry["load_kva"])

        ranked = sorted(range(len(centers)), key=lambda i: _distance_m(point, centers[i]))

        placed = False
        for i in ranked:
            if _distance_m(point, centers[i]) > max_secondary_length_m:
                continue
            if remaining_capacity[i] < load_kva:
                continue
            assignments[i].append(point)
            remaining_capacity[i] -= load_kva
            placed = True
            break

        if not placed:
            # Constraint-violating parcels spawn their own dedicated group.
            centers.append(point)
            assignments.append([point])
            remaining_capacity.append(max(target_kva_per_transformer, load_kva) - load_kva)

    grouped: list[GroupModel] = []
    for i, points in enumerate(assignments):
        if not points:
            continue
        grouped.append(GroupModel(center=centers[i], points=points))

    return [*dedicated, *grouped]


def get_area_aware_clusters(
    parcels,
    *,
    target_area_per_transformer_m2: float = 5000.0,
    dedicated_transformer_area_m2: float = 2000.0,
    min_clusters: int = 1,
    max_clusters: int | None = None,
) -> list[GroupModel]:
    """Cluster parcels by footprint area with dedicated transformers for large parcels.

    Parcels whose geodesic footprint area exceeds ``dedicated_transformer_area_m2``
    each receive their own transformer group. Remaining parcels are clustered
    using area-weighted K-means where the number of clusters is derived from
    the ratio of total shared area to ``target_area_per_transformer_m2``.

    Parameters
    ----------
    parcels : Sequence
        Parcels as dicts or objects exposing ``geometry`` (list of vertices or
        single point).
    target_area_per_transformer_m2 : float
        Target total parcel area served by each shared transformer.
    dedicated_transformer_area_m2 : float
        Footprint area at/above which a parcel gets its own transformer.
    min_clusters : int
        Minimum number of shared transformer clusters.
    max_clusters : int | None
        Maximum number of shared transformer clusters.

    Returns
    -------
    list[GroupModel]
        One group per transformer, dedicated first then shared.
    """
    if not parcels:
        raise ValueError("Area-aware clustering requires parcels.")

    dedicated: list[GroupModel] = []
    shared_points: list[GeoLocation] = []
    shared_weights: list[float] = []

    for parcel in parcels:
        geometry = _parcel_attr(parcel, "geometry")
        center, area_m2 = centroid_and_area_m2(geometry)
        if area_m2 >= dedicated_transformer_area_m2:
            dedicated.append(GroupModel(center=center, points=[center]))
        else:
            shared_points.append(center)
            shared_weights.append(max(area_m2, 1.0))

    grouped: list[GroupModel] = []
    if shared_points:
        total_area = float(sum(shared_weights))
        est_clusters = max(
            1,
            int(np.ceil(total_area / max(target_area_per_transformer_m2, 1.0))),
        )
        est_clusters = max(min_clusters, est_clusters)
        est_clusters = min(est_clusters, len(shared_points))
        if max_clusters is not None:
            est_clusters = min(est_clusters, max_clusters)

        coords = np.array([(p.longitude, p.latitude) for p in shared_points])
        model = KMeans(n_clusters=est_clusters, random_state=0)
        model.fit(coords, sample_weight=np.array(shared_weights))

        for idx, center in enumerate(model.cluster_centers_):
            points = [
                shared_points[i] for i, label in enumerate(model.labels_) if int(label) == idx
            ]
            grouped.append(
                GroupModel(
                    center=GeoLocation(float(center[0]), float(center[1])),
                    points=points,
                )
            )

    return [*dedicated, *grouped]


def get_balanced_kmeans_clusters(points: list[GeoLocation], num_clusters: int) -> list[GroupModel]:
    """Cluster points using balanced K-means with size-constrained assignment.

    Unlike standard K-means (which can produce very uneven cluster sizes), this
    variant assigns points to the nearest cluster that hasn't reached its maximum
    size, producing roughly equal-sized groups.

    Parameters
    ----------
    points : list[GeoLocation]
        Geographic locations to cluster.
    num_clusters : int
        Number of clusters to produce. Must be <= len(points).

    Returns
    -------
    list[GroupModel]
        Balanced clusters with approximately equal point counts.

    Raises
    ------
    ValueError
        If num_clusters exceeds the number of points.
    """
    if len(points) < num_clusters:
        raise ValueError("num_clusters must be <= number of points")

    coords = np.array([(p.longitude, p.latitude) for p in points])
    model = KMeans(n_clusters=num_clusters, random_state=0)
    model.fit(coords)
    centers = [GeoLocation(float(c[0]), float(c[1])) for c in model.cluster_centers_]

    distances = np.linalg.norm(coords[:, None, :] - model.cluster_centers_[None, :, :], axis=2)
    order = np.argsort(np.min(distances, axis=1))

    max_size = int(np.ceil(len(points) / num_clusters))
    assignments: list[list[GeoLocation]] = [[] for _ in range(num_clusters)]
    counts = [0 for _ in range(num_clusters)]

    for idx in order:
        ranked = np.argsort(distances[idx])
        for cluster_idx in ranked:
            cluster_idx = int(cluster_idx)
            if counts[cluster_idx] < max_size:
                assignments[cluster_idx].append(points[int(idx)])
                counts[cluster_idx] += 1
                break

    groups = []
    for cluster_idx, cluster_points in enumerate(assignments):
        if not cluster_points:
            continue
        groups.append(GroupModel(center=centers[cluster_idx], points=cluster_points))

    return groups


def estimate_feeder_count(
    *,
    parcel_count: int,
    region_area_km2: float,
    target_parcels_per_feeder: int = 200,
    high_density_threshold_per_km2: float = 1000.0,
    large_region_threshold_km2: float = 5.0,
    min_feeders: int = 1,
    max_feeders: int = 10,
) -> int:
    """Estimate the number of feeders needed for a region.

    Uses parcel count and regional density heuristics to determine an
    appropriate feeder count.

    Parameters
    ----------
    parcel_count : int
        Total number of parcels/loads in the region.
    region_area_km2 : float
        Area of the service region in square kilometres.
    target_parcels_per_feeder : int
        Desired number of parcels per feeder.
    high_density_threshold_per_km2 : float
        Density above which an extra feeder is added.
    large_region_threshold_km2 : float
        Region size above which an extra feeder is added.
    min_feeders : int
        Minimum feeder count.
    max_feeders : int
        Maximum feeder count.

    Returns
    -------
    int
        Estimated number of feeders, clamped to [min_feeders, max_feeders].
    """
    base = max(1, int(np.ceil(parcel_count / max(1, target_parcels_per_feeder))))
    density = parcel_count / max(region_area_km2, 0.01)

    if density > high_density_threshold_per_km2:
        base += 1
    if region_area_km2 > large_region_threshold_km2:
        base += 1

    return max(min_feeders, min(max_feeders, base))
