from __future__ import annotations

import argparse
import csv
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from infrasys.quantities import Distance
import networkx as nx

from shift import (
    DelaunayStrategy,
    FullRoadGraphStrategy,
    GeoLocation,
    HubLineStrategy,
    MeshSteinerStrategy,
    MinimumSpanningTreeStrategy,
    OpenStreetSecondaryStrategy,
    PRSG,
    PlotManager,
    RadialStrategy,
    ShortestPathTreeStrategy,
    SteinerTreeStrategy,
    WeightedSteinerTreeStrategy,
    add_distribution_graph_to_plot,
    add_parcels_to_plot,
    get_kmeans_clusters,
    parcels_from_location,
)


class SafeSteinerTreeStrategy(SteinerTreeStrategy):
    def route(self, graph, terminal_nodes):
        return super().route(nx.Graph(graph), terminal_nodes)


class SafeWeightedSteinerTreeStrategy(WeightedSteinerTreeStrategy):
    def route(self, graph, terminal_nodes):
        return super().route(nx.Graph(graph), terminal_nodes)


class SafeShortestPathTreeStrategy(ShortestPathTreeStrategy):
    def route(self, graph, terminal_nodes):
        return super().route(nx.Graph(graph), terminal_nodes)


class SafeMinimumSpanningTreeStrategy(MinimumSpanningTreeStrategy):
    def route(self, graph, terminal_nodes):
        return super().route(nx.Graph(graph), terminal_nodes)


class SafeOpenStreetSecondaryStrategy(OpenStreetSecondaryStrategy):
    def build(self, group):
        graph = super().build(group)
        mapping = {node: f"{node}_{uuid.uuid4().hex[:8]}" for node in graph.nodes}
        return nx.relabel_nodes(graph, mapping)


@dataclass
class RunResult:
    category: str
    routing_strategy: str
    secondary_strategy: str
    status: str
    error: str
    node_count: int
    edge_count: int
    total_length_m: float
    plot_path: str


def _parse_polygon(value: str) -> list[GeoLocation]:
    points = []
    for item in value.split(";"):
        lon_str, lat_str = item.split(",")
        points.append(GeoLocation(float(lon_str.strip()), float(lat_str.strip())))
    if len(points) < 3:
        raise ValueError("Polygon requires at least 3 lon,lat points.")
    return points


def _parcel_points(parcels) -> list[GeoLocation]:
    points: list[GeoLocation] = []
    for parcel in parcels:
        if isinstance(parcel.geometry, list):
            lons = [g.longitude for g in parcel.geometry]
            lats = [g.latitude for g in parcel.geometry]
            points.append(GeoLocation(sum(lons) / len(lons), sum(lats) / len(lats)))
        else:
            points.append(parcel.geometry)
    return points


def _save_plot(graph, parcels, center: GeoLocation, output_path: Path):
    plot_manager = PlotManager(center=center)
    add_parcels_to_plot(parcels, plot_manager, name="Parcels")
    add_distribution_graph_to_plot(graph, plot_manager, name="Network")
    plot_manager._figure.update_maps(
        center={"lon": center.longitude, "lat": center.latitude},
        style="carto-positron",
        zoom=14,
    )
    plot_manager._figure.write_html(str(output_path))


def _graph_metrics(graph) -> tuple[int, int, float]:
    edge_length = 0.0
    for _, _, edge in graph.get_edges():
        if edge.length is not None:
            edge_length += float(edge.length.to("m").magnitude)
    return len(list(graph.get_nodes())), len(list(graph.get_edges())), edge_length


def _run_case(
    *,
    category: str,
    routing_name: str,
    routing_factory: Callable[[], object],
    secondary_name: str,
    secondary_factory: Callable[[], object],
    groups,
    source: GeoLocation,
    parcels,
    output_dir: Path,
) -> RunResult:
    slug = f"{routing_name}__{secondary_name}".replace(" ", "_")
    plot_path = output_dir / f"{category}_{slug}.html"

    try:
        builder = PRSG(
            groups=groups,
            source_location=source,
            routing_strategy=routing_factory(),
            secondary_strategy=secondary_factory(),
        )
        graph = builder.get_distribution_graph()
        node_count, edge_count, total_length_m = _graph_metrics(graph)
        _save_plot(graph, parcels, source, plot_path)
        return RunResult(
            category=category,
            routing_strategy=routing_name,
            secondary_strategy=secondary_name,
            status="ok",
            error="",
            node_count=node_count,
            edge_count=edge_count,
            total_length_m=round(total_length_m, 2),
            plot_path=str(plot_path),
        )
    except Exception as exc:  # noqa: BLE001
        return RunResult(
            category=category,
            routing_strategy=routing_name,
            secondary_strategy=secondary_name,
            status="failed",
            error=str(exc),
            node_count=0,
            edge_count=0,
            total_length_m=0.0,
            plot_path="",
        )


def main() -> None:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Compare routing and secondary algorithms for the same region and dump plots."
    )
    parser.add_argument("--location", default="Fort Worth, TX")
    parser.add_argument(
        "--polygon",
        default="",
        help="Optional polygon as 'lon,lat;lon,lat;lon,lat'. Overrides --location.",
    )
    parser.add_argument("--distance-m", type=float, default=500.0)
    parser.add_argument("--parcels-per-cluster", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        default=".dump/algorithm_comparison",
        help="Directory where plots and summary files are written.",
    )
    parser.add_argument(
        "--full-matrix",
        action="store_true",
        help="Run all routing x secondary combinations.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.polygon:
        region = _parse_polygon(args.polygon)
    else:
        region = args.location

    parcels = parcels_from_location(region, Distance(args.distance_m, "m")) or []
    if not parcels:
        raise RuntimeError("No parcels found for the selected region.")

    points = _parcel_points(parcels)
    clusters = max(1, len(points) // max(1, args.parcels_per_cluster))
    groups = get_kmeans_clusters(clusters, points)

    source = GeoLocation(
        sum([p.longitude for p in points]) / len(points),
        sum([p.latitude for p in points]) / len(points),
    )

    routing_factories: dict[str, Callable[[], object]] = {
        "SteinerTreeStrategy": SafeSteinerTreeStrategy,
        "WeightedSteinerTreeStrategy": SafeWeightedSteinerTreeStrategy,
        "ShortestPathTreeStrategy": SafeShortestPathTreeStrategy,
        "MinimumSpanningTreeStrategy": SafeMinimumSpanningTreeStrategy,
        "FullRoadGraphStrategy": FullRoadGraphStrategy,
    }

    secondary_factories: dict[str, Callable[[], object]] = {
        "MeshSteinerStrategy": MeshSteinerStrategy,
        "RadialStrategy": RadialStrategy,
        "DelaunayStrategy": DelaunayStrategy,
        "OpenStreetSecondaryStrategy": lambda: SafeOpenStreetSecondaryStrategy(
            routing_strategy=SafeWeightedSteinerTreeStrategy()
        ),
        "HubLineStrategy": HubLineStrategy,
    }

    results: list[RunResult] = []

    # Sweep routing algorithms with a fixed secondary strategy.
    for routing_name, routing_factory in routing_factories.items():
        results.append(
            _run_case(
                category="routing_sweep",
                routing_name=routing_name,
                routing_factory=routing_factory,
                secondary_name="OpenStreetSecondaryStrategy",
                secondary_factory=lambda: SafeOpenStreetSecondaryStrategy(
                    routing_strategy=SafeWeightedSteinerTreeStrategy()
                ),
                groups=groups,
                source=source,
                parcels=parcels,
                output_dir=output_dir,
            )
        )

    # Sweep secondary algorithms with a fixed routing strategy.
    for secondary_name, secondary_factory in secondary_factories.items():
        results.append(
            _run_case(
                category="secondary_sweep",
                routing_name="WeightedSteinerTreeStrategy",
                routing_factory=SafeWeightedSteinerTreeStrategy,
                secondary_name=secondary_name,
                secondary_factory=secondary_factory,
                groups=groups,
                source=source,
                parcels=parcels,
                output_dir=output_dir,
            )
        )

    if args.full_matrix:
        for routing_name, routing_factory in routing_factories.items():
            for secondary_name, secondary_factory in secondary_factories.items():
                results.append(
                    _run_case(
                        category="full_matrix",
                        routing_name=routing_name,
                        routing_factory=routing_factory,
                        secondary_name=secondary_name,
                        secondary_factory=secondary_factory,
                        groups=groups,
                        source=source,
                        parcels=parcels,
                        output_dir=output_dir,
                    )
                )

    summary_json = output_dir / "summary.json"
    summary_csv = output_dir / "summary.csv"

    summary_json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")

    with summary_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

    ok_runs = [r for r in results if r.status == "ok"]
    failed_runs = [r for r in results if r.status != "ok"]
    print(f"Wrote {len(ok_runs)} plot(s) to {output_dir}")
    print(f"Summary: {summary_json}")
    if failed_runs:
        print(f"Failed runs: {len(failed_runs)}")
        for item in failed_runs:
            print(
                f"  - [{item.category}] {item.routing_strategy} + {item.secondary_strategy}: {item.error}"
            )


if __name__ == "__main__":
    main()
