"""Tests for building complete distribution systems."""

import pytest

from gdm.systems.distribution import DistributionSystem
from gdm.systems.distribution.components import (
    DistributionVoltageSource,
    DistributionTransformer,
    DistributionLoad,
    DistributionBus,
    MatrixImpedanceBranch,
)
from gdm.quantities import Distance, Voltage, ApparentPower, Current, ReactivePower
from infrasys import Location

from shift import (
    DistributionGraph,
    DistributionSystemBuilder,
    BalancedPhaseMapper,
    TransformerVoltageMapper,
    BaseEquipmentMapper,
    NodeModel,
    EdgeModel,
    TransformerPhaseMapperModel,
    TransformerVoltageModel,
    TransformerTypes,
)


class MockEquipmentMapper(BaseEquipmentMapper):
    """Mock equipment mapper that creates minimal equipment for testing."""

    def __init__(self, graph, phase_mapper, voltage_mapper):
        """Initialize with equipment dictionaries."""
        from gdm.systems.distribution.equipment import (
            DistributionTransformerEquipment,
            MatrixImpedanceBranchEquipment,
            LoadEquipment,
            VoltageSourceEquipment,
            PhaseVoltageSourceEquipment,
            WindingEquipment,
        )
        from gdm.systems.distribution.equipment.load_equipment import PhaseLoadEquipment
        from gdm.systems.distribution.enums import VoltageTypes, ConnectionType
        from infrasys.quantities import ActivePower, Angle
        import numpy as np

        super().__init__(graph)

        # Create equipment for edges
        edge_equipment = {}
        for from_node, to_node, edge in graph.get_edges():
            if edge.edge_type == DistributionTransformer:
                # Create 3-winding center-tapped split-phase transformer equipment
                # Primary (7.2 kV) + two secondary windings (120V each)
                edge_equipment[edge.name] = DistributionTransformerEquipment(
                    name=f"eq_{edge.name}",
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
            elif edge.edge_type == MatrixImpedanceBranch:
                # Create branch equipment
                r_matrix = np.array([[0.4013, 0.0953], [0.0953, 0.4013]])
                x_matrix = np.array([[0.2809, 0.0667], [0.0667, 0.2809]])
                c_matrix = np.array([[0.0, 0.0], [0.0, 0.0]])
                edge_equipment[edge.name] = MatrixImpedanceBranchEquipment(
                    name=f"eq_{edge.name}",
                    r_matrix=r_matrix,
                    x_matrix=x_matrix,
                    c_matrix=c_matrix,
                    ampacity=Current(200, "ampere"),
                )

        self._edge_equipment_mapping = edge_equipment

        # Create equipment for node assets
        node_asset_equipment = {}
        for node in graph.get_nodes():
            node_asset_equipment[node.name] = {}
            if node.assets:
                for asset_type in node.assets:
                    if asset_type == DistributionLoad:
                        # Create load equipment
                        node_asset_equipment[node.name][asset_type] = LoadEquipment(
                            name=f"load_eq_{node.name}",
                            phase_loads=[
                                PhaseLoadEquipment(
                                    name=f"phase_load_{node.name}_s1",
                                    p_real=1.0,
                                    i_real=0.0,
                                    z_real=0.0,
                                    p_imag=1.0,
                                    i_imag=0.0,
                                    z_imag=0.0,
                                    real_power=ActivePower(2.5, "kilowatt"),
                                    reactive_power=ReactivePower(0.5, "kilovar"),
                                ),
                                PhaseLoadEquipment(
                                    name=f"phase_load_{node.name}_s2",
                                    p_real=1.0,
                                    i_real=0.0,
                                    z_real=0.0,
                                    p_imag=1.0,
                                    i_imag=0.0,
                                    z_imag=0.0,
                                    real_power=ActivePower(2.5, "kilowatt"),
                                    reactive_power=ReactivePower(0.5, "kilovar"),
                                ),
                            ],
                        )
                    elif asset_type == DistributionVoltageSource:
                        # Create voltage source equipment
                        pvs = PhaseVoltageSourceEquipment(
                            name=f"phase_vsource_{node.name}",
                            voltage=Voltage(7.2, "kilovolt"),
                            angle=Angle(0, "degree"),
                            voltage_type=VoltageTypes.LINE_TO_GROUND,
                            r0=0.0,
                            r1=0.0,
                            x0=0.0001,
                            x1=0.0001,
                        )
                        node_asset_equipment[node.name][asset_type] = VoltageSourceEquipment(
                            name=f"vsource_eq_{node.name}",
                            sources=[pvs],
                        )

        self._node_asset_equipment_mapping = node_asset_equipment

    @property
    def edge_equipment_mapping(self):
        return self._edge_equipment_mapping

    @property
    def node_asset_equipment_mapping(self):
        return self._node_asset_equipment_mapping


@pytest.fixture
def simple_distribution_graph():
    """Create a simple distribution graph for testing.

    Graph structure:
    - Source node with voltage source
    - Transformer connecting source to secondary
    - Secondary node
    - Two load branches from secondary
    """
    graph = DistributionGraph()

    # Create nodes
    source_node = NodeModel(
        name="source_bus",
        location=Location(x=-97.33, y=32.75),
        assets={DistributionVoltageSource},
    )

    secondary_node = NodeModel(
        name="secondary_bus",
        location=Location(x=-97.329, y=32.749),
        assets=set(),
    )

    load_node_1 = NodeModel(
        name="load_bus_1",
        location=Location(x=-97.328, y=32.748),
        assets={DistributionLoad},
    )

    load_node_2 = NodeModel(
        name="load_bus_2",
        location=Location(x=-97.327, y=32.747),
        assets={DistributionLoad},
    )

    # Add nodes to graph
    graph.add_nodes([source_node, secondary_node, load_node_1, load_node_2])

    # Create edges
    transformer_edge = EdgeModel(
        name="xfmr_1",
        edge_type=DistributionTransformer,
        length=None,
    )

    branch_edge_1 = EdgeModel(
        name="line_1",
        edge_type=MatrixImpedanceBranch,
        length=Distance(50, "m"),
    )

    branch_edge_2 = EdgeModel(
        name="line_2",
        edge_type=MatrixImpedanceBranch,
        length=Distance(75, "m"),
    )

    # Add edges to graph
    graph.add_edge(source_node.name, secondary_node.name, edge_data=transformer_edge)
    graph.add_edge(secondary_node.name, load_node_1.name, edge_data=branch_edge_1)
    graph.add_edge(secondary_node.name, load_node_2.name, edge_data=branch_edge_2)

    return graph


@pytest.fixture
def complete_distribution_graph():
    """Create a more complete distribution graph with multiple transformers and branches.

    Graph structure:
    - Source node with voltage source
    - Three transformers
    - Three secondary buses (one per transformer)
    - Multiple load nodes per secondary
    """
    graph = DistributionGraph()

    # Create source node
    source_node = NodeModel(
        name="substation",
        location=Location(x=-97.33, y=32.75),
        assets={DistributionVoltageSource},
    )
    graph.add_node(source_node)

    # Create 3 transformer-secondary pairs
    for i in range(1, 4):
        # Secondary node for each transformer
        secondary_node = NodeModel(
            name=f"secondary_{i}",
            location=Location(x=-97.33 + i * 0.001, y=32.75 - i * 0.001),
            assets=set(),
        )
        graph.add_node(secondary_node)

        # Transformer edge
        transformer_edge = EdgeModel(
            name=f"xfmr_{i}",
            edge_type=DistributionTransformer,
            length=None,
        )
        graph.add_edge(source_node.name, secondary_node.name, edge_data=transformer_edge)

        # Create 2-3 load nodes per secondary
        for j in range(1, 3):
            load_node = NodeModel(
                name=f"load_{i}_{j}",
                location=Location(
                    x=-97.33 + i * 0.001 + j * 0.0005,
                    y=32.75 - i * 0.001 - j * 0.0005,
                ),
                assets={DistributionLoad},
            )
            graph.add_node(load_node)

            # Branch edge
            branch_edge = EdgeModel(
                name=f"line_{i}_{j}",
                edge_type=MatrixImpedanceBranch,
                length=Distance(30 + j * 20, "m"),
            )
            graph.add_edge(secondary_node.name, load_node.name, edge_data=branch_edge)

    return graph


class TestSystemBuilder:
    """Test cases for DistributionSystemBuilder."""

    def test_build_simple_distribution_system(self, simple_distribution_graph):
        """Test building a simple distribution system from scratch."""
        # Configure phase mapper
        transformer_phase_models = [
            TransformerPhaseMapperModel(
                tr_name="xfmr_1",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=simple_distribution_graph.get_node("source_bus").location,
            )
        ]

        phase_mapper = BalancedPhaseMapper(
            simple_distribution_graph,
            method="greedy",
            mapper=transformer_phase_models,
        )

        # Configure voltage mapper
        voltage_mapper = TransformerVoltageMapper(
            simple_distribution_graph,
            xfmr_voltage=[
                TransformerVoltageModel(
                    name="xfmr_1",
                    voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
                )
            ],
        )

        # Configure equipment mapper
        equipment_mapper = MockEquipmentMapper(
            simple_distribution_graph,
            phase_mapper,
            voltage_mapper,
        )

        # Build the system
        system_builder = DistributionSystemBuilder(
            name="test_simple_system",
            dist_graph=simple_distribution_graph,
            phase_mapper=phase_mapper,
            voltage_mapper=voltage_mapper,
            equipment_mapper=equipment_mapper,
        )

        system = system_builder.get_system()

        # Verify system
        assert system is not None
        assert system.name == "test_simple_system"

        # Verify buses
        buses = list(system.get_components(DistributionBus))
        assert len(buses) == 4  # source, secondary, 2 loads

        # Verify voltage source
        vsources = list(system.get_components(DistributionVoltageSource))
        assert len(vsources) == 1

        # Verify transformer
        transformers = list(system.get_components(DistributionTransformer))
        assert len(transformers) == 1
        assert transformers[0].name == "xfmr_1"

        # Verify branches
        branches = list(system.get_components(MatrixImpedanceBranch))
        assert len(branches) == 2

        # Verify loads
        loads = list(system.get_components(DistributionLoad))
        assert len(loads) == 2

    def test_build_complete_distribution_system(self, complete_distribution_graph):
        """Test building a complete distribution system with multiple transformers and loads."""
        # Configure phase mapper
        transformer_phase_models = [
            TransformerPhaseMapperModel(
                tr_name=f"xfmr_{i}",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=complete_distribution_graph.get_node("substation").location,
            )
            for i in range(1, 4)
        ]

        phase_mapper = BalancedPhaseMapper(
            complete_distribution_graph,
            method="greedy",
            mapper=transformer_phase_models,
        )

        # Configure voltage mapper
        voltage_mapper = TransformerVoltageMapper(
            complete_distribution_graph,
            xfmr_voltage=[
                TransformerVoltageModel(
                    name=f"xfmr_{i}",
                    voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
                )
                for i in range(1, 4)
            ],
        )

        # Configure equipment mapper
        equipment_mapper = MockEquipmentMapper(
            complete_distribution_graph,
            phase_mapper,
            voltage_mapper,
        )

        # Build the system
        system_builder = DistributionSystemBuilder(
            name="test_complete_system",
            dist_graph=complete_distribution_graph,
            phase_mapper=phase_mapper,
            voltage_mapper=voltage_mapper,
            equipment_mapper=equipment_mapper,
        )

        system = system_builder.get_system()

        # Verify system
        assert system is not None
        assert system.name == "test_complete_system"

        # Verify buses (1 source + 3 secondaries + 6 loads = 10)
        buses = list(system.get_components(DistributionBus))
        assert len(buses) == 10

        # Verify voltage source
        vsources = list(system.get_components(DistributionVoltageSource))
        assert len(vsources) == 1

        # Verify transformers
        transformers = list(system.get_components(DistributionTransformer))
        assert len(transformers) == 3

        # Verify branches
        branches = list(system.get_components(MatrixImpedanceBranch))
        assert len(branches) == 6

        # Verify loads
        loads = list(system.get_components(DistributionLoad))
        assert len(loads) == 6

    def test_system_builder_without_auto_build(self, simple_distribution_graph):
        """Test building system with auto_build=False."""
        # Configure mappers
        transformer_phase_models = [
            TransformerPhaseMapperModel(
                tr_name="xfmr_1",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=simple_distribution_graph.get_node("source_bus").location,
            )
        ]

        phase_mapper = BalancedPhaseMapper(
            simple_distribution_graph,
            method="greedy",
            mapper=transformer_phase_models,
        )

        voltage_mapper = TransformerVoltageMapper(
            simple_distribution_graph,
            xfmr_voltage=[
                TransformerVoltageModel(
                    name="xfmr_1",
                    voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
                )
            ],
        )

        equipment_mapper = MockEquipmentMapper(
            simple_distribution_graph,
            phase_mapper,
            voltage_mapper,
        )

        # Build the system with auto_build=False
        system_builder = DistributionSystemBuilder(
            name="test_manual_build",
            dist_graph=simple_distribution_graph,
            phase_mapper=phase_mapper,
            voltage_mapper=voltage_mapper,
            equipment_mapper=equipment_mapper,
            auto_build=False,
        )

        # System should not be built yet
        assert system_builder._system is None

        # Manually build the system
        system = system_builder.build()
        assert system is not None
        assert system.name == "test_manual_build"

        # Get system again should return same instance
        system2 = system_builder.get_system()
        assert system2 is system

    def test_system_export_to_json(self, simple_distribution_graph, tmp_path):
        """Test building and exporting a distribution system to JSON."""
        # Configure mappers
        transformer_phase_models = [
            TransformerPhaseMapperModel(
                tr_name="xfmr_1",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=simple_distribution_graph.get_node("source_bus").location,
            )
        ]

        phase_mapper = BalancedPhaseMapper(
            simple_distribution_graph,
            method="greedy",
            mapper=transformer_phase_models,
        )

        voltage_mapper = TransformerVoltageMapper(
            simple_distribution_graph,
            xfmr_voltage=[
                TransformerVoltageModel(
                    name="xfmr_1",
                    voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
                )
            ],
        )

        equipment_mapper = MockEquipmentMapper(
            simple_distribution_graph,
            phase_mapper,
            voltage_mapper,
        )

        # Build the system
        system_builder = DistributionSystemBuilder(
            name="test_export_system",
            dist_graph=simple_distribution_graph,
            phase_mapper=phase_mapper,
            voltage_mapper=voltage_mapper,
            equipment_mapper=equipment_mapper,
        )

        system = system_builder.get_system()

        # Export to JSON
        output_file = tmp_path / "test_system.json"
        system.to_json(output_file)

        # Verify file exists
        assert output_file.exists()

        # Load back and verify
        loaded_system = DistributionSystem.from_json(output_file)
        assert loaded_system.name == "test_export_system"
        assert len(list(loaded_system.get_components(DistributionBus))) == 4
        assert len(list(loaded_system.get_components(DistributionTransformer))) == 1
        assert len(list(loaded_system.get_components(MatrixImpedanceBranch))) == 2

    def test_system_components_connectivity(self, simple_distribution_graph):
        """Test that all system components are properly connected."""
        # Configure mappers
        transformer_phase_models = [
            TransformerPhaseMapperModel(
                tr_name="xfmr_1",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=simple_distribution_graph.get_node("source_bus").location,
            )
        ]

        phase_mapper = BalancedPhaseMapper(
            simple_distribution_graph,
            method="greedy",
            mapper=transformer_phase_models,
        )

        voltage_mapper = TransformerVoltageMapper(
            simple_distribution_graph,
            xfmr_voltage=[
                TransformerVoltageModel(
                    name="xfmr_1",
                    voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
                )
            ],
        )

        equipment_mapper = MockEquipmentMapper(
            simple_distribution_graph,
            phase_mapper,
            voltage_mapper,
        )

        # Build the system
        system_builder = DistributionSystemBuilder(
            name="test_connectivity",
            dist_graph=simple_distribution_graph,
            phase_mapper=phase_mapper,
            voltage_mapper=voltage_mapper,
            equipment_mapper=equipment_mapper,
        )

        system = system_builder.get_system()

        # Get buses
        source_bus = system.get_component(DistributionBus, "source_bus")
        secondary_bus = system.get_component(DistributionBus, "secondary_bus")
        load_bus_1 = system.get_component(DistributionBus, "load_bus_1")
        load_bus_2 = system.get_component(DistributionBus, "load_bus_2")

        # Verify buses exist
        assert source_bus is not None
        assert secondary_bus is not None
        assert load_bus_1 is not None
        assert load_bus_2 is not None

        # Verify transformer connects source to secondary
        transformer = system.get_component(DistributionTransformer, "xfmr_1")
        assert transformer is not None
        transformer_buses = transformer.buses
        assert source_bus in transformer_buses
        assert secondary_bus in transformer_buses

        # Verify branches connect secondary to loads
        line_1 = system.get_component(MatrixImpedanceBranch, "line_1")
        assert line_1 is not None
        assert secondary_bus in line_1.buses
        assert load_bus_1 in line_1.buses

        line_2 = system.get_component(MatrixImpedanceBranch, "line_2")
        assert line_2 is not None
        assert secondary_bus in line_2.buses
        assert load_bus_2 in line_2.buses

        # Verify voltage source is at source bus
        vsource = list(system.get_components(DistributionVoltageSource))[0]
        assert vsource.bus == source_bus

        # Verify loads are at load buses
        loads = list(system.get_components(DistributionLoad))
        load_buses = [load.bus for load in loads]
        assert load_bus_1 in load_buses
        assert load_bus_2 in load_buses
