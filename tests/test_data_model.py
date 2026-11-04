"""Tests for data models."""

from gdm.quantities import Voltage, ApparentPower
from gdm.systems.distribution.components import (
    DistributionLoad,
    DistributionTransformer,
    DistributionBranchBase,
)
from infrasys import Location

from shift.data_model import (
    GeoLocation,
    ParcelModel,
    GroupModel,
    TransformerVoltageModel,
    TransformerTypes,
    TransformerPhaseMapperModel,
    NodeModel,
    EdgeModel,
)


class TestGeoLocation:
    """Test cases for GeoLocation."""

    def test_valid_geolocation(self):
        """Test creating a valid GeoLocation."""
        loc = GeoLocation(longitude=-97.33, latitude=45.56)
        assert loc.longitude == -97.33
        assert loc.latitude == 45.56

    def test_geolocation_bounds(self):
        """Test GeoLocation with boundary values."""
        # Valid boundaries
        loc1 = GeoLocation(longitude=-180, latitude=-90)
        assert loc1.longitude == -180
        assert loc1.latitude == -90

        loc2 = GeoLocation(longitude=180, latitude=90)
        assert loc2.longitude == 180
        assert loc2.latitude == 90


class TestParcelModel:
    """Test cases for ParcelModel."""

    def test_parcel_with_point_geometry(self):
        """Test ParcelModel with point geometry."""
        parcel = ParcelModel(
            name="parcel-1",
            geometry=GeoLocation(-97.33, 45.56),
            building_type="residential",
            city="Test City",
            state="TX",
            postal_address="12345",
        )
        assert parcel.name == "parcel-1"
        assert isinstance(parcel.geometry, GeoLocation)
        assert parcel.building_type == "residential"

    def test_parcel_with_polygon_geometry(self):
        """Test ParcelModel with polygon geometry."""
        parcel = ParcelModel(
            name="parcel-2",
            geometry=[
                GeoLocation(-97.33, 45.56),
                GeoLocation(-97.32, 45.57),
                GeoLocation(-97.31, 45.56),
            ],
            building_type="commercial",
            city="Test City",
            state="TX",
            postal_address="12345",
        )
        assert parcel.name == "parcel-2"
        assert isinstance(parcel.geometry, list)
        assert len(parcel.geometry) == 3


class TestGroupModel:
    """Test cases for GroupModel."""

    def test_group_model(self):
        """Test GroupModel creation."""
        center = GeoLocation(-97.33, 45.56)
        points = [
            GeoLocation(-97.32, 45.55),
            GeoLocation(-97.34, 45.57),
        ]
        group = GroupModel(center=center, points=points)
        assert group.center == center
        assert len(group.points) == 2


class TestTransformerVoltageModel:
    """Test cases for TransformerVoltageModel."""

    def test_transformer_voltage_model(self):
        """Test TransformerVoltageModel creation."""
        voltages = [Voltage(12.47, "kV"), Voltage(0.24, "kV")]
        model = TransformerVoltageModel(name="tx-1", voltages=voltages)
        assert model.name == "tx-1"
        assert len(model.voltages) == 2


class TestTransformerTypes:
    """Test cases for TransformerTypes enum."""

    def test_transformer_types(self):
        """Test TransformerTypes enum values."""
        assert TransformerTypes.THREE_PHASE.value == "THREE_PHASE"
        assert TransformerTypes.SINGLE_PHASE.value == "SINGLE_PHASE"
        assert TransformerTypes.SPLIT_PHASE.value == "SPLIT_PHASE"


class TestTransformerPhaseMapperModel:
    """Test cases for TransformerPhaseMapperModel."""

    def test_phase_mapper_model(self):
        """Test TransformerPhaseMapperModel creation."""
        model = TransformerPhaseMapperModel(
            tr_name="tx-1",
            tr_type=TransformerTypes.THREE_PHASE,
            tr_capacity=ApparentPower(50, "kVA"),
            location=Location(x=-97.33, y=45.56),
        )
        assert model.tr_name == "tx-1"
        assert model.tr_type == TransformerTypes.THREE_PHASE
        assert model.tr_capacity.magnitude == 50


class TestNodeModel:
    """Test cases for NodeModel."""

    def test_node_model_basic(self):
        """Test basic NodeModel creation."""
        node = NodeModel(name="node-1", location=Location(x=-97.33, y=45.56))
        assert node.name == "node-1"
        assert node.location.x == -97.33
        assert node.location.y == 45.56

    def test_node_model_with_assets(self):
        """Test NodeModel with assets."""
        node = NodeModel(
            name="node-2",
            location=Location(x=-97.33, y=45.56),
            assets={DistributionLoad},
        )
        assert node.name == "node-2"
        assert DistributionLoad in node.assets


class TestEdgeModel:
    """Test cases for EdgeModel."""

    def test_edge_model_with_branch(self):
        """Test EdgeModel with branch type."""
        from gdm.quantities import Distance

        edge = EdgeModel(
            name="line-1", edge_type=DistributionBranchBase, length=Distance(100, "m")
        )
        assert edge.name == "line-1"
        assert edge.edge_type == DistributionBranchBase

    def test_edge_model_with_transformer(self):
        """Test EdgeModel with transformer type."""
        edge = EdgeModel(
            name="tx-1",
            edge_type=DistributionTransformer,
        )
        assert edge.name == "tx-1"
        assert edge.edge_type == DistributionTransformer
