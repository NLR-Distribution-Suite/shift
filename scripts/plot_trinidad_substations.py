#!/usr/bin/env python
"""Plot all Trinidad, Colorado substations and feeders as one interactive HTML map.

The feeder JSON files are discovered recursively beneath ``--folder``. Each file
is loaded as a GDM ``DistributionSystem`` and rendered with its ``to_gdf``
helper through the shared Plotly implementation in ``plot_feeders``.

Examples
--------
python scripts/plot_trinidad_substations.py
python scripts/plot_trinidad_substations.py --show
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from plot_feeders import build_figure, discover_feeder_files

DEFAULT_FOLDER = Path(__file__).resolve().parents[1] / "outputs" / "trinidad_co"
DEFAULT_OUTPUT = DEFAULT_FOLDER / "trinidad_substations.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder",
        type=Path,
        default=DEFAULT_FOLDER,
        help="Folder containing substation folders with feeder JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
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
        help="Open the plot in a web browser after saving it.",
    )
    args = parser.parse_args()

    if not args.folder.is_dir():
        logger.error("Folder {} does not exist.", args.folder)
        return 1

    systems = discover_feeder_files(args.folder)
    if not systems:
        logger.error("No DistributionSystem JSON files found under {}.", args.folder)
        return 1

    figure = build_figure(systems, root=args.folder, map_type=args.map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(args.output), include_plotlyjs="cdn", full_html=True)
    logger.info(
        "Wrote {} feeder models across {} substations to {}.",
        len(systems),
        len({path.parent for path, _ in systems}),
        args.output,
    )

    if args.show:
        figure.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
