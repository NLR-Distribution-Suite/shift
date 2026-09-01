"""Build GDM feeder models for Trinidad, CO entirely from local data.

Inputs
------
Parcels : /Users/alatif/Downloads/Master_Address_Public.gdb
          (Colorado master address points; "LasAnimas" layer, zip 81082 = Trinidad)
Roads   : .dump/colorado-260720.osm.pbf via shift.openstreet_roads.set_local_pbf
          (osmium bbox extracts per feeder cell; no Overpass/internet needed)

Settings: the UI quick-build defaults (THREE_PHASE 500 kVA, 12.47/0.48 kV,
Delaunay secondary strategy, area-aware clustering, p1rhs7_1247 catalog). The
clustering target is re-expressed for address-point parcels: point parcels have
zero footprint, so ``target_area_per_transformer_m2`` acts as "address points
per transformer" (25 ~= the ~20-50 buildings per 5016 m^2 quick-build target).

Substations are not looked up online; when Overpass is unreachable the whole
service polygon is tiled as a single substation cell (see feeder_models).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely import Polygon, box as sbox
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[1]
GDB_PATH = Path("/Users/alatif/Downloads/Master_Address_Public.gdb")
PBF_PATH = REPO / ".dump" / "colorado-260720.osm.pbf"
OUT_DIR = REPO / ".dump" / "trinidad_co"
CATALOG_PATH = REPO / "tests" / "models" / "p1rhs7_1247.json"

# Quick-build (UI) settings
SQFT_TO_M2 = 0.09290304
QUICK_TARGET_AREA_M2 = 54000 * SQFT_TO_M2  # ~5016.76 m^2 per transformer (building footprints)
QUICK_DEDICATED_AREA_M2 = 22000 * SQFT_TO_M2  # ~2043.87 m^2
POINTS_PER_TRANSFORMER = 25.0  # re-expressed target for zero-area address points


def trinidad_service_polygon(points: gpd.GeoDataFrame) -> Polygon:
    """Compact urban service polygon from the densest connected block of address cells.

    Grids the points into ~1 km cells, keeps cells with >=20 addresses, and takes
    the 8-connected component containing the densest cell (the town core), then
    buffers it slightly so boundary streets are included.
    """
    xs = points.geometry.x.values
    ys = points.geometry.y.values
    cell = 0.01
    gx = np.floor(xs / cell).astype(int)
    gy = np.floor(ys / cell).astype(int)

    counts: dict[tuple[int, int], int] = defaultdict(int)
    for a, b in zip(gx, gy):
        counts[(a, b)] += 1

    dense = {k for k, v in counts.items() if v >= 20}
    seed = max(counts, key=counts.get)
    component: set[tuple[int, int]] = {seed}
    queue = deque([seed])
    while queue:
        a, b = queue.popleft()
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                nxt = (a + da, b + db)
                if nxt in dense and nxt not in component:
                    component.add(nxt)
                    queue.append(nxt)

    union = unary_union(
        [sbox(a * cell, b * cell, (a + 1) * cell, (b + 1) * cell) for a, b in component]
    ).buffer(0.002)  # ~200 m
    if not isinstance(union, Polygon):
        union = max(union.geoms, key=lambda g: g.area)
    return union


def main() -> None:
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
    from gdm.distribution import DistributionSystem

    if not GDB_PATH.exists():
        raise FileNotFoundError(f"Address geodatabase not found: {GDB_PATH}")
    if not PBF_PATH.exists():
        raise FileNotFoundError(f"Local road extract not found: {PBF_PATH}")
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Equipment catalog not found: {CATALOG_PATH}")

    df = gpd.read_file(GDB_PATH, layer="LasAnimas")
    tri = df[df["Zipcode"].astype(str) == "81082"]  # Trinidad postal area
    print(f"Trinidad (zip 81082) address points: {len(tri)}")
    if tri.empty:
        raise ValueError("No Trinidad address points found for ZIP code 81082")

    polygon = trinidad_service_polygon(tri)
    lat = float(np.median(tri.geometry.y.values))
    km_per_deg = 111.32 * math.cos(math.radians(lat))
    area_km2 = polygon.area * 111.32 * km_per_deg
    print(
        f"Service polygon: {area_km2:.1f} km^2, bounds={tuple(round(v, 4) for v in polygon.bounds)}"
    )

    set_local_pbf(str(PBF_PATH))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parcel_path = OUT_DIR / "trinidad_address_points.geojson"
    tri.to_file(parcel_path, driver="GeoJSON")
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
    ok = [r for r in results if r.get("output_path")]
    for r in results:
        print(f"substation_{r['osm_id']}/feeder_{r['feeder_index']}: OK -> {r['output_path']}")
    print(f"\n{len(ok)}/{len(results)} feeder models built under {OUT_DIR}")


if __name__ == "__main__":
    main()
