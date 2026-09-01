"""Build GDM feeder models for Trinidad, CO entirely from prepared local data.

Inputs
------
Parcels : /Users/alatif/Downloads/Master_Address_Public.gdb
          (Colorado master address points; "LasAnimas" layer, zip 81082 = Trinidad)
Roads   : data/trinidad/colorado.osm.pbf via shift.openstreet_roads.set_local_pbf
          (osmium bbox extracts per feeder cell; no Overpass/internet needed)

Settings: the UI quick-build defaults (THREE_PHASE 500 kVA, 12.47/0.48 kV,
Delaunay secondary strategy, area-aware clustering, p1rhs7_1247 catalog).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely import Polygon, box as sbox
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[2]
GDB_PATH = Path("/Users/alatif/Downloads/Master_Address_Public.gdb")
PBF_PATH = REPO / "data" / "trinidad" / "colorado.osm.pbf"
OUT_DIR = REPO / "outputs" / "trinidad_co"
CATALOG_PATH = REPO / "tests" / "models" / "p1rhs7_1247.json"

SQFT_TO_M2 = 0.09290304
QUICK_DEDICATED_AREA_M2 = 22000 * SQFT_TO_M2
POINTS_PER_TRANSFORMER = 25.0


def trinidad_service_polygon(points: gpd.GeoDataFrame) -> Polygon:
    """Return a compact service polygon around the densest address cells."""
    xs = points.geometry.x.values
    ys = points.geometry.y.values
    cell = 0.01
    gx = np.floor(xs / cell).astype(int)
    gy = np.floor(ys / cell).astype(int)

    counts: dict[tuple[int, int], int] = defaultdict(int)
    for x_cell, y_cell in zip(gx, gy):
        counts[(x_cell, y_cell)] += 1

    dense = {key for key, value in counts.items() if value >= 20}
    seed = max(counts, key=counts.get)
    component: set[tuple[int, int]] = {seed}
    queue = deque([seed])
    while queue:
        x_cell, y_cell = queue.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbor = (x_cell + dx, y_cell + dy)
                if neighbor in dense and neighbor not in component:
                    component.add(neighbor)
                    queue.append(neighbor)

    union = unary_union(
        [sbox(x * cell, y * cell, (x + 1) * cell, (y + 1) * cell) for x, y in component]
    ).buffer(0.002)
    if not isinstance(union, Polygon):
        union = max(union.geoms, key=lambda geometry: geometry.area)
    return union


def main() -> None:
    from gdm.distribution import DistributionSystem
    from shift.feeder_models import (
        ClusteringConfig,
        ExportConfig,
        FeederConfig,
        FeederModelConfig,
        ParcelSourceConfig,
        PRSGConfig,
        TransformerConfig,
        VoltageConfig,
        build_feeder_models,
    )
    from shift.openstreet_roads import set_local_pbf

    if not GDB_PATH.exists():
        raise FileNotFoundError(f"Address geodatabase not found: {GDB_PATH}")
    if not PBF_PATH.exists():
        raise FileNotFoundError(f"Local road extract not found: {PBF_PATH}")
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Equipment catalog not found: {CATALOG_PATH}")

    addresses = gpd.read_file(GDB_PATH, layer="LasAnimas")
    trinidad = addresses[addresses["Zipcode"].astype(str) == "81082"]
    print(f"Trinidad (zip 81082) address points: {len(trinidad)}")
    if trinidad.empty:
        raise ValueError("No Trinidad address points found for ZIP code 81082")

    polygon = trinidad_service_polygon(trinidad)
    latitude = float(np.median(trinidad.geometry.y.values))
    km_per_degree = 111.32 * math.cos(math.radians(latitude))
    area_km2 = polygon.area * 111.32 * km_per_degree
    print(
        f"Service polygon: {area_km2:.1f} km^2, "
        f"bounds={tuple(round(value, 4) for value in polygon.bounds)}"
    )

    set_local_pbf(str(PBF_PATH))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parcel_path = OUT_DIR / "trinidad_address_points.geojson"
    trinidad.to_file(parcel_path, driver="GeoJSON")
    catalog = DistributionSystem.from_json(CATALOG_PATH)

    config = FeederModelConfig(
        export=ExportConfig(folder=OUT_DIR),
        feeders=FeederConfig(phase_method="greedy"),
        parcels=ParcelSourceConfig(
            source="geodataframe",
            path=parcel_path,
            name_column="AddrFull",
            field_mapper="gis",
            column_map={"city": "PlaceName", "postal_address": "Zipcode"},
            local_pbf_path=PBF_PATH,
        ),
        clustering=ClusteringConfig(
            strategy="area_aware",
            target_area_per_transformer_m2=POINTS_PER_TRANSFORMER,
            dedicated_transformer_area_m2=QUICK_DEDICATED_AREA_M2,
        ),
        prsg=PRSGConfig(
            offline=False,
            routing_strategy="SteinerTreeStrategy",
            secondary_strategy="DelaunayStrategy",
        ),
        transformers=TransformerConfig(type="THREE_PHASE", capacity_kva=500.0),
        voltages=VoltageConfig(
            primary_voltage_kv=12.47,
            secondary_voltage_kv=0.48,
            use_substation_voltage=False,
        ),
    )
    results = build_feeder_models(polygon, config, catalog=catalog)

    print("\n=== Results ===")
    successful = [result for result in results if result.get("output_path")]
    for result in results:
        print(
            f"substation_{result['osm_id']}/feeder_{result['feeder_index']}: "
            f"OK -> {result['output_path']}"
        )
    print(f"\n{len(successful)}/{len(results)} feeder models built under {OUT_DIR}")


if __name__ == "__main__":
    main()
