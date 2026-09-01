"""Tests for the parallel feeder-model pipeline."""

from unittest import mock

import geopandas as gpd
import numpy as np
import pytest
from gdm.distribution import CatalogSystem, DistributionSystem
from gdm.distribution.components import (
    DistributionBus,
    DistributionLoad,
    DistributionTransformer,
    MatrixImpedanceBranch,
)
from gdm.distribution.equipment import (
    BareConductorEquipment,
    DistributionTransformerEquipment,
    LoadEquipment,
    MatrixImpedanceBranchEquipment,
    PhaseLoadEquipment,
    WindingEquipment,
)
from gdm.distribution.enums import ConnectionType, VoltageTypes
from gdm.quantities import (
    ActivePower,
    ApparentPower,
    Current,
    Distance,
    ReactivePower,
    ResistancePULength,
    Voltage,
)
from shapely import Point, Polygon

from shift.data_model import GeoLocation
from shift.feeder_models import (
    CatalogConfig,
    ClusteringConfig,
    ExportConfig,
    FeederConfig,
    FeederModelConfig,
    GisParcelSource,
    PRSGConfig,
    ParcelSourceConfig,
    _iter_feeder_tasks,
    augment_catalog_with_matrix_branches,
    build_feeder_model,
    build_feeder_models,
    load_catalog,
)
from shift.substation import substation_voltage_kv

SERVICE_POLYGON = Polygon([[0, 0], [0, 0.1], [0.1, 0.1], [0.1, 0]])


def _transformer_equipment(name="catalog_xfmr"):
    """Split-phase center-tapped transformer, 7.2/0.12 kV."""
    return DistributionTransformerEquipment(
        name=name,
        windings=[
            WindingEquipment(
                num_phases=1,
                rated_power=ApparentPower(25, "kilovolt_ampere"),
                rated_voltage=Voltage(7.2, "kilovolt"),
                voltage_type=VoltageTypes.LINE_TO_GROUND,
                connection_type=ConnectionType.STAR,
                resistance=0.6,
                is_grounded=True,
                tap_positions=[1.0],
            ),
            WindingEquipment(
                num_phases=1,
                rated_power=ApparentPower(25, "kilovolt_ampere"),
                rated_voltage=Voltage(120, "volt"),
                voltage_type=VoltageTypes.LINE_TO_GROUND,
                connection_type=ConnectionType.STAR,
                resistance=0.012,
                is_grounded=True,
                tap_positions=[1.0],
            ),
            WindingEquipment(
                num_phases=1,
                rated_power=ApparentPower(25, "kilovolt_ampere"),
                rated_voltage=Voltage(120, "volt"),
                voltage_type=VoltageTypes.LINE_TO_GROUND,
                connection_type=ConnectionType.STAR,
                resistance=0.012,
                is_grounded=True,
                tap_positions=[1.0],
            ),
        ],
        is_center_tapped=True,
        pct_no_load_loss=0.1,
        pct_full_load_loss=1.0,
        coupling_sequences=[[0, 1], [0, 2], [1, 2]],
        winding_reactances=[0.02, 0.02, 0.01],
    )


def _branch_equipment(name, size, ampacity):
    r_matrix = np.full((size, size), 0.4)
    x_matrix = np.full((size, size), 0.28)
    np.fill_diagonal(r_matrix, 0.45)
    np.fill_diagonal(x_matrix, 0.32)
    return MatrixImpedanceBranchEquipment(
        name=name,
        r_matrix=r_matrix,
        x_matrix=x_matrix,
        c_matrix=np.zeros((size, size)),
        ampacity=Current(ampacity, "ampere"),
    )


def _load_equipment(name="catalog_load"):
    return LoadEquipment(
        name=name,
        phase_loads=[
            PhaseLoadEquipment(
                name=f"{name}_phase",
                real_power=ActivePower(10, "kilowatt"),
                reactive_power=ReactivePower(3, "kilovar"),
                z_real=0,
                z_imag=0,
                i_real=0,
                i_imag=0,
                p_real=1,
                p_imag=1,
            )
        ],
    )


@pytest.fixture(scope="session")
def catalog():
    """A minimal CatalogSystem with transformer, branch, and load equipment."""
    system = CatalogSystem(name="catalog", auto_add_composed_components=True)
    system.add_component(_transformer_equipment())
    system.add_component(_branch_equipment("branch_1ph", 1, 100))
    system.add_component(_branch_equipment("branch_2ph", 2, 200))
    system.add_component(_branch_equipment("branch_3ph", 3, 300))
    system.add_component(_load_equipment())
    return system


def _parcel_geodataframe(tmp_path):
    rows = []
    for i in range(16):
        x = 0.03 + 0.015 * (i % 4)
        y = 0.03 + 0.015 * (i // 4)
        rows.append(
            {
                "name": f"parcel_{i}",
                "building": "residential",
                "addr:city": "Testville",
                "addr:state": "TS",
                "addr:postcode": "12345",
                "geometry": Polygon(
                    [[x, y], [x + 0.005, y], [x + 0.005, y + 0.005], [x, y + 0.005]]
                ),
            }
        )
    parcels = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    path = tmp_path / "parcels.geojson"
    parcels.to_file(path, driver="GeoJSON")
    return path


def _substations_gdf():
    return gpd.GeoDataFrame(
        {
            "osm_type": ["node"],
            "osm_id": [12345],
            "substation_point": [Point(0.05, 0.05)],
            "geometry": [SERVICE_POLYGON],
        },
        crs="EPSG:4326",
    )


def _substations_gdf_with_voltage():
    gdf = _substations_gdf()
    gdf["voltage"] = ["110000;20000"]
    return gdf


def _config(tmp_path, parcel_path, **overrides):
    return FeederModelConfig(
        export=ExportConfig(folder=tmp_path),
        feeders=FeederConfig(
            min_feeders=3,
            max_feeders=8,
            max_workers=2,
            phase_method="greedy",
        ),
        parcels=ParcelSourceConfig(source="geodataframe", path=str(parcel_path)),
        prsg=PRSGConfig(offline=True, snap_to_roads=False, secondary_strategy="RadialStrategy"),
        clustering=ClusteringConfig(strategy="kmeans_count", parcels_per_cluster=2),
        **overrides,
    )


def test_config_from_toml(tmp_path):
    """FeederModelConfig parses a TOML file."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
[export]
folder = "./models"

[feeders]
min_feeders = 2
max_feeders = 5
max_workers = 4

[catalog]
dataset = "gdm_catalog"

[parcels]
source = "geodataframe"
path = "./data/parcels.geojson"

[clustering]
strategy = "capacity_distance"

[prsg]
offline = true
secondary_strategy = "RadialStrategy"
"""
    )
    config = FeederModelConfig.from_toml(toml_path)
    from pathlib import Path

    assert config.export_folder == Path("./models")
    assert config.feeders.min_feeders == 2
    assert config.feeders.max_workers == 4
    assert config.parcels.source == "geodataframe"
    assert config.parcels.path == Path("./data/parcels.geojson")
    assert config.clustering.strategy == "capacity_distance"
    assert config.prsg.offline is True
    assert config.prsg.secondary_strategy == "RadialStrategy"


def test_config_geodataframe_requires_path():
    """geodataframe parcel source without a path is rejected."""
    with pytest.raises(Exception):
        ParcelSourceConfig(source="geodataframe")


def test_load_catalog(monkeypatch):
    """load_catalog delegates to gdmloader's SystemLoader."""
    captured = {}

    class FakeLoader:
        def __init__(self, cached_dir=None):
            self.cached_dir = cached_dir

        def add_source(self, source):
            captured["source"] = source

        def load_dataset(self, **kwargs):
            captured["kwargs"] = kwargs
            return CatalogSystem(name="fake_catalog")

    monkeypatch.setattr("gdmloader.source.SystemLoader", FakeLoader)
    load_catalog(CatalogConfig(dataset="my_catalog", cache_dir="cache"))
    assert captured["source"].name == "gdm_data"
    assert captured["kwargs"]["system_type"].__name__ == "CatalogSystem"
    assert captured["kwargs"]["dataset_name"] == "my_catalog"


def test_build_single_feeder_model(catalog, tmp_path):
    """A single feeder DistributionSystem builds from parcels and a catalog."""
    parcel_path = _parcel_geodataframe(tmp_path)
    config = _config(tmp_path, parcel_path)

    system = build_feeder_model(
        SERVICE_POLYGON,
        GeoLocation(0.05, 0.05),
        catalog,
        config,
        name="test_feeder",
    )

    assert system.name == "test_feeder"
    assert len(list(system.get_components(DistributionBus))) > 0
    assert len(list(system.get_components(DistributionTransformer))) > 0
    assert len(list(system.get_components(MatrixImpedanceBranch))) > 0
    assert len(list(system.get_components(DistributionLoad))) > 0


@mock.patch("shift.feeder_models.substation_boundaries", return_value=_substations_gdf())
def test_build_feeder_models_exports_in_parallel(mock_boundaries, catalog, tmp_path):
    """build_feeder_models exports substation/feeder JSON files concurrently."""
    parcel_path = _parcel_geodataframe(tmp_path)
    config = _config(tmp_path, parcel_path)

    manifest = build_feeder_models(SERVICE_POLYGON, config, catalog=catalog)

    assert len(manifest) == 3  # 1 substation, min_feeders=3
    assert all(entry["osm_id"] == 12345 for entry in manifest)

    for entry in manifest:
        output = tmp_path / f"substation_12345/feeder_{entry['feeder_index']}.json"
        assert output.exists()
        assert entry["output_path"] == str(output)
        reloaded = DistributionSystem.from_json(output)
        assert reloaded.name == f"substation_12345_feeder_{entry['feeder_index']}"

    assert [entry["feeder_index"] for entry in manifest] == [1, 2, 3]


@mock.patch(
    "shift.feeder_models.substation_boundaries",
    return_value=gpd.GeoDataFrame(
        {"osm_type": [], "osm_id": [], "substation_point": [], "geometry": []},
        crs="EPSG:4326",
    ),
)
def test_build_feeder_models_empty_area(mock_boundaries, catalog, tmp_path):
    """No substations yields an empty manifest and no export folder contents."""
    parcel_path = _parcel_geodataframe(tmp_path)
    config = _config(tmp_path, parcel_path)
    manifest = build_feeder_models(SERVICE_POLYGON, config, catalog=catalog)
    assert manifest == []


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("110000;20000", 20.0),
        ("132000;33000", 33.0),
        ("50000", 50.0),
        ("20", 20.0),
        ("20kV", 20.0),
        ("110000 ; 20000", 20.0),
        (None, None),
        (float("nan"), None),
        ("unknown", None),
    ],
)
def test_substation_voltage_kv(tag, expected):
    """The OSM voltage tag parses to the distribution-side kV."""
    assert (
        substation_voltage_kv(tag) is expected
        if expected is None
        else substation_voltage_kv(tag) == pytest.approx(expected)
    )


@mock.patch(
    "shift.feeder_models.substation_boundaries", return_value=_substations_gdf_with_voltage()
)
def test_substation_voltage_feeds_primary(mock_boundaries, tmp_path):
    """The substation voltage tag overrides the configured primary voltage."""
    parcel_path = _parcel_geodataframe(tmp_path)
    config = _config(tmp_path, parcel_path)

    tasks = _iter_feeder_tasks(SERVICE_POLYGON, config, parcel_source=None)
    assert tasks
    assert all(task.primary_voltage_kv == pytest.approx(20.0) for task in tasks)


@mock.patch(
    "shift.feeder_models.substation_boundaries", return_value=_substations_gdf_with_voltage()
)
def test_substation_voltage_can_be_disabled(mock_boundaries, tmp_path):
    """use_substation_voltage=False keeps the configured primary voltage."""
    parcel_path = _parcel_geodataframe(tmp_path)
    config = _config(tmp_path, parcel_path)
    config.voltages.use_substation_voltage = False
    config.voltages.primary_voltage_kv = 12.47

    tasks = _iter_feeder_tasks(SERVICE_POLYGON, config, parcel_source=None)
    assert tasks
    assert all(task.primary_voltage_kv == pytest.approx(12.47) for task in tasks)


def test_augment_catalog_with_matrix_branches():
    """Catalog conductors convert to 1/2/3-phase matrix branch equipment."""
    catalog = CatalogSystem(name="catalog", auto_add_composed_components=True)
    catalog.add_component(
        BareConductorEquipment(
            name="oh_cond",
            conductor_diameter=Distance(0.0201, "in"),
            conductor_gmr=Distance(0.00065, "ft"),
            ampacity=Current(200, "ampere"),
            ac_resistance=ResistancePULength(0.1, "ohm/km"),
            dc_resistance=ResistancePULength(0.1, "ohm/km"),
            emergency_ampacity=Current(220, "ampere"),
        )
    )
    assert len(list(catalog.get_components(MatrixImpedanceBranchEquipment))) == 0

    augment_catalog_with_matrix_branches(catalog)

    branches = list(catalog.get_components(MatrixImpedanceBranchEquipment))
    assert len(branches) == 3  # 1, 2, and 3-phase assemblies
    assert sorted({b.r_matrix.shape[0] for b in branches}) == [1, 2, 3]
    assert all(isinstance(b.ampacity, Current) for b in branches)

    # Idempotent on a second pass.
    augment_catalog_with_matrix_branches(catalog)
    assert len(list(catalog.get_components(MatrixImpedanceBranchEquipment))) == 3


def test_gis_parcel_source(monkeypatch):
    """GisParcelSource fetches ArcGIS point features within the polygon."""
    payload = {
        "features": [
            {
                "attributes": {
                    "AddrFull": "100 MAIN ST",
                    "PlaceName": "Trinidad",
                    "County": "LAS ANIMAS",
                    "Building": None,
                },
                "geometry": {"x": -104.5, "y": 37.17},
            }
        ],
        "exceededTransferLimit": False,
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr("shift.feeder_models.requests.get", lambda *a, **k: FakeResponse())

    config = ParcelSourceConfig(
        source="gis",
        url="https://host/FeatureServer/0",
        field_mapper="gis",
        column_map={"postal_address": "AddrFull", "city": "PlaceName"},
    )
    source = GisParcelSource(config)
    polygon = Polygon([[-104.51, 37.16], [-104.51, 37.18], [-104.49, 37.18], [-104.49, 37.16]])
    parcels = source.get_parcels(polygon)
    assert len(parcels) == 1
    assert parcels[0].postal_address == "100 MAIN ST"
    assert parcels[0].city == "Trinidad"
