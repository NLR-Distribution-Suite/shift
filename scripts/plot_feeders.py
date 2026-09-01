#!/usr/bin/env python
"""Plot every feeder DistributionSystem under a folder as one interactive HTML map.

Each ``*.json`` found recursively under ``--folder`` is loaded as a GDM
``DistributionSystem`` and rendered onto a single Plotly map using
``DistributionSystem.to_gdf()`` for node/edge geometry. Feeders are color-coded
with a legend entry and a dropdown that isolates a single feeder. The map is
saved to ``--output`` as a self-contained interactive HTML file.

Examples
--------
python scripts/plot_feeders.py                              # plot ./.dump -> feeders_plot.html
python scripts/plot_feeders.py --folder models --output all.html
python scripts/plot_feeders.py --map scattergeo --show
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import plotly.graph_objects as go
from loguru import logger

from gdm.distribution import DistributionSystem
from gdm.distribution.components import DistributionLoad
from shift.plot_manager import COLORS

SECONDARY_COLOR = "#9aa0a6"
LOAD_COLOR = "#e11d48"


def discover_feeder_files(folder: Path) -> list[tuple[Path, DistributionSystem]]:
    """Load every DistributionSystem JSON found under ``folder``."""
    systems: list[tuple[Path, DistributionSystem]] = []
    for path in sorted(folder.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            system = DistributionSystem.from_json(path)
        except Exception:
            logger.warning("Skipping {} (not a DistributionSystem JSON).", path)
            continue
        systems.append((path, system))
    return systems


def _line_coords(geometry) -> tuple[list, list]:
    """Return ``(lon, lat)`` arrays for a LineString, with None separators."""
    geoms = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    lon: list = []
    lat: list = []
    for line in geoms:
        for x, y in line.coords:
            lon.append(x)
            lat.append(y)
        lon.append(None)
        lat.append(None)
    return lon, lat


def _point_coords(geometry) -> tuple[list, list]:
    """Return ``(lon, lat)`` arrays for Point/MultiPoint geometries."""
    geoms = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    lon: list = []
    lat: list = []
    for point in geoms:
        lon.append(point.x)
        lat.append(point.y)
    return lon, lat


def _is_secondary_phases(phases) -> bool:
    """True when the branch phases indicate a low-voltage secondary (split-phase)."""
    if phases is None:
        return False
    return "S1" in str(phases) or "S2" in str(phases)


def add_feeder_traces(fig: go.Figure, system: DistributionSystem, label: str, color: str) -> None:
    """Add primary/secondary line traces and load/bus marker traces for one feeder."""
    load_buses = {load.bus.name for load in system.get_components(DistributionLoad)}

    gdf = system.to_gdf()
    lines = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    buses = gdf[gdf.geometry.geom_type.isin(["Point", "MultiPoint"])]

    primary_lon, primary_lat = [], []
    secondary_lon, secondary_lat = [], []
    for _, row in lines.iterrows():
        lons, lats = _line_coords(row.geometry)
        target = secondary_lon if _is_secondary_phases(row.get("Phases")) else primary_lon
        target.extend(lons)
        (secondary_lat if _is_secondary_phases(row.get("Phases")) else primary_lat).extend(lats)

    if primary_lon:
        fig.add_trace(
            go.Scattermap(
                lon=primary_lon,
                lat=primary_lat,
                mode="lines",
                line=dict(color=color, width=2.5),
                name=f"{label} (primary)",
                legendgroup=label,
            )
        )
    if secondary_lon:
        fig.add_trace(
            go.Scattermap(
                lon=secondary_lon,
                lat=secondary_lat,
                mode="lines",
                line=dict(color=SECONDARY_COLOR, width=1.5),
                name=f"{label} (secondary)",
                legendgroup=label,
            )
        )

    if len(buses):
        load_lon, load_lat, bus_lon, bus_lat = [], [], [], []
        for _, row in buses.iterrows():
            lons, lats = _point_coords(row.geometry)
            is_load = str(row.get("Name")) in load_buses
            (load_lon if is_load else bus_lon).extend(lons)
            (load_lat if is_load else bus_lat).extend(lats)

        if load_lon:
            fig.add_trace(
                go.Scattermap(
                    lon=load_lon,
                    lat=load_lat,
                    mode="markers",
                    marker=dict(color=LOAD_COLOR, size=6, opacity=0.9),
                    name=f"{label} (loads)",
                    legendgroup=label,
                )
            )
        if bus_lon:
            fig.add_trace(
                go.Scattermap(
                    lon=bus_lon,
                    lat=bus_lat,
                    mode="markers",
                    marker=dict(color=color, size=3, opacity=0.7),
                    name=f"{label} (buses)",
                    legendgroup=label,
                )
            )


def build_figure(
    systems: list[tuple[Path, DistributionSystem]],
    root: Path,
    map_type: str = "scattermap",
) -> go.Figure:
    """Build an interactive map figure with all feeders overlaid."""
    fig = go.Figure()

    all_lon: list[float] = []
    all_lat: list[float] = []
    for index, (path, system) in enumerate(systems):
        label = str(path.relative_to(root))
        color = COLORS[index % len(COLORS)]
        add_feeder_traces(fig, system, label, color)
        gdf = system.to_gdf()
        all_lon.extend([g.x for g in gdf.geometry[gdf.geometry.geom_type == "Point"]])
        all_lat.extend([g.y for g in gdf.geometry[gdf.geometry.geom_type == "Point"]])

    center_lon = sum(all_lon) / len(all_lon) if all_lon else 0.0
    center_lat = sum(all_lat) / len(all_lat) if all_lat else 0.0

    fig.update_layout(
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
        title=f"Feeders ({len(systems)})",
        legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.7)"),
    )

    if map_type == "scattermap":
        fig.update_maps(
            {
                "style": "carto-positron",
                "center": {"lon": center_lon, "lat": center_lat},
                "zoom": 12,
            }
        )
    else:
        fig.update_layout(
            geo=dict(
                center=dict(lat=center_lat, lon=center_lon),
                projection_scale=12,
                showland=True,
                landcolor="lightgray",
            )
        )

    _add_feeders_dropdown(fig, systems, root)
    return fig


def _add_feeders_dropdown(
    fig: go.Figure, systems: list[tuple[Path, DistributionSystem]], root: Path
) -> None:
    """Add a dropdown menu that isolates a single feeder (or shows all)."""
    if not systems:
        return
    buttons: list[dict] = [
        dict(label="All feeders", method="update", args=[{"visible": True}, {}])
    ]
    for index, (path, system) in enumerate(systems):
        label = str(path.relative_to(root))
        trace_indices = [i for i, trace in enumerate(fig.data) if trace.legendgroup == label]
        visible = [False] * len(fig.data)
        for i in trace_indices:
            visible[i] = True
        buttons.append(
            dict(
                label=f"Feeder {index + 1}: {system.name or path.name}",
                method="update",
                args=[{"visible": visible}, {}],
            )
        )
    fig.update_layout(
        updatemenus=[
            dict(
                buttons=buttons,
                direction="down",
                showactive=True,
                x=0.0,
                xanchor="left",
                y=1.15,
                yanchor="top",
            )
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder",
        type=Path,
        default=Path(".dump"),
        help="Folder containing feeder DistributionSystem JSON files (recursive). "
        "Defaults to ./.dump.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feeders_plot.html"),
        help="Output interactive HTML file.",
    )
    parser.add_argument(
        "--map",
        choices=["scattermap", "scattergeo"],
        default="scattermap",
        help="Map type: scattermap (MapLibre tiles) or scattergeo (built-in geo).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open the plot in a web browser in addition to saving it.",
    )
    args = parser.parse_args()

    if not args.folder.exists() or not args.folder.is_dir():
        logger.error("Folder {} does not exist.", args.folder)
        return 1

    systems = discover_feeder_files(args.folder)
    if not systems:
        logger.error("No DistributionSystem JSON files found under {}.", args.folder)
        return 1

    logger.info("Loaded {} feeder model(s) from {}.", len(systems), args.folder)
    fig = build_figure(systems, root=args.folder, map_type=args.map)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(args.output), include_plotlyjs="cdn", full_html=True)
    logger.info("Wrote interactive plot to {}.", args.output)

    if args.show:
        fig.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
