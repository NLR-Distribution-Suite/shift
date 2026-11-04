"""Test for building a complete GDM Distribution model from a start location.

This test demonstrates the complete workflow from creating a graph to building
a distribution system, as described in the documentation's complete example.
"""

import numpy as np

from gdm.systems.distribution import DistributionSystem
from gdm.systems.distribution.components import (
    DistributionVoltageSource,
    DistributionTransformer,
    DistributionBus,
    MatrixImpedanceBranch,
    DistributionLoad,
)
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
from gdm.quantities import Distance, Voltage, ApparentPower, Current, ReactivePower
from infrasys import Location
from infrasys.quantities import ActivePower, Angle

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


class _MockEquipmentMapper(BaseEquipmentMapper):
    """Equipment mapper that creates equipment programmatically for testing."""

    def __init__(self, graph, phase_mapper, voltage_mapper):
        super().__init__(graph)

        edge_equipment = {}
        for from_node, to_node, edge in graph.get_edges():
            if edge.edge_type == DistributionTransformer:
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

        node_asset_equipment = {}
        for node in graph.get_nodes():
            node_asset_equipment[node.name] = {}
            if node.assets:
                for asset_type in node.assets:
                    if asset_type == DistributionLoad:
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


def test_build_complete_distribution_model_from_location():
    """Test building a complete GDM Distribution model starting from a location.

    This test demonstrates the full workflow:
    1. Create a distribution graph with nodes and edges
    2. Configure phase mapper (balanced allocation)
    3. Configure voltage mapper (transformer voltages)
    4. Configure equipment mapper (select equipment)
    5. Build the distribution system
    6. Verify the system is correctly constructed
    """
    # Step 1: Create a distribution graph
    # Simulates what PRSG would create from a real location
    graph = DistributionGraph()

    # Create source node (like a substation)
    start_location = Location(x=-97.33, y=32.75)  # Fort Worth, TX coordinates

    source_node = NodeModel(
        name="substation",
        location=start_location,
        assets={DistributionVoltageSource},
    )

    # Create secondary node (after transformer)
    secondary_node = NodeModel(
        name="secondary_1",
        location=Location(x=-97.329, y=32.749),
        assets=set(),
    )

    # Create load nodes
    load_node_1 = NodeModel(
        name="load_1",
        location=Location(x=-97.328, y=32.748),
        assets={DistributionLoad},
    )

    load_node_2 = NodeModel(
        name="load_2",
        location=Location(x=-97.327, y=32.747),
        assets={DistributionLoad},
    )

    # Add nodes to graph
    graph.add_nodes([source_node, secondary_node, load_node_1, load_node_2])

    # Create transformer edge
    transformer_edge = EdgeModel(
        name="xfmr_1",
        edge_type=DistributionTransformer,
        length=None,
    )

    # Create branch edges (update type to match catalog)
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

    # the graph represents the distribution network topology
    assert len(list(graph.get_nodes())) == 4
    assert len(list(graph.get_edges())) == 3

    # Step 2: Configure phase mapper
    transformer_phase_models = [
        TransformerPhaseMapperModel(
            tr_name="xfmr_1",
            tr_type=TransformerTypes.SPLIT_PHASE,
            tr_capacity=ApparentPower(25, "kilovolt_ampere"),
            location=start_location,
        )
    ]

    phase_mapper = BalancedPhaseMapper(
        graph,
        method="greedy",
        mapper=transformer_phase_models,
    )

    # Verify phase mapper created node mappings
    assert "substation" in phase_mapper.node_phase_mapping
    assert "secondary_1" in phase_mapper.node_phase_mapping

    # Step 3: Configure voltage mapper
    voltage_mapper = TransformerVoltageMapper(
        graph,
        xfmr_voltage=[
            TransformerVoltageModel(
                name="xfmr_1",
                voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
            )
        ],
    )

    # Verify voltage mapper created node mappings
    assert "substation" in voltage_mapper.node_voltage_mapping
    assert "secondary_1" in voltage_mapper.node_voltage_mapping

    # Step 4: Configure equipment mapper
    equipment_mapper = _MockEquipmentMapper(
        graph,
        phase_mapper,
        voltage_mapper,
    )

    # Verify equipment mapper created mappings
    assert "xfmr_1" in equipment_mapper.edge_equipment_mapping
    assert "line_1" in equipment_mapper.edge_equipment_mapping

    # Step 5: Build the distribution system
    system_builder = DistributionSystemBuilder(
        name="test_distribution_from_location",
        dist_graph=graph,
        phase_mapper=phase_mapper,
        voltage_mapper=voltage_mapper,
        equipment_mapper=equipment_mapper,
    )

    system = system_builder.get_system()

    # Step 6: Verify the complete system
    assert system is not None
    assert system.name == "test_distribution_from_location"

    # Verify buses
    buses = list(system.get_components(DistributionBus))
    assert len(buses) == 4  # source, secondary, 2 loads
    bus_names = [bus.name for bus in buses]
    assert "substation" in bus_names
    assert "secondary_1" in bus_names
    assert "load_1" in bus_names
    assert "load_2" in bus_names

    # Verify voltage source
    vsources = list(system.get_components(DistributionVoltageSource))
    assert len(vsources) == 1
    assert vsources[0].bus.name == "substation"

    # Verify transformer
    transformers = list(system.get_components(DistributionTransformer))
    assert len(transformers) == 1
    assert transformers[0].name == "xfmr_1"

    # Verify branches
    branches = list(system.get_components(MatrixImpedanceBranch))
    assert len(branches) == 2
    branch_names = [b.name for b in branches]
    assert "line_1" in branch_names
    assert "line_2" in branch_names

    # Verify loads
    loads = list(system.get_components(DistributionLoad))
    assert len(loads) == 2
    load_bus_names = [load.bus.name for load in loads]
    assert "load_1" in load_bus_names
    assert "load_2" in load_bus_names

    # Verify connectivity
    # substation_bus = system.get_component(DistributionBus, "substation")
    # secondary_bus = system.get_component(DistributionBus, "secondary_1")

    # Transformer should connect substation to secondary
    transformer_buses = [bus.name for bus in transformers[0].buses]
    assert "substation" in transformer_buses
    assert "secondary_1" in transformer_buses

    # Branches should connect secondary to loads
    for branch in branches:
        branch_bus_names = [bus.name for bus in branch.buses]
        assert "secondary_1" in branch_bus_names
        assert any(load_name in branch_bus_names for load_name in ["load_1", "load_2"])

    print("✓ Successfully built complete GDM Distribution model from start location")
    print(f"  - System: {system.name}")
    print(f"  - Buses: {len(buses)}")
    print(f"  - Transformers: {len(transformers)}")
    print(f"  - Branches: {len(branches)}")
    print(f"  - Loads: {len(loads)}")


def test_system_export_to_json(tmp_path):
    """Test building and exporting a complete system to JSON."""
    # Create a minimal graph
    graph = DistributionGraph()

    source_node = NodeModel(
        name="source",
        location=Location(x=-97.33, y=32.75),
        assets={DistributionVoltageSource},
    )

    secondary_node = NodeModel(
        name="secondary",
        location=Location(x=-97.329, y=32.749),
        assets=set(),
    )

    load_node = NodeModel(
        name="load",
        location=Location(x=-97.328, y=32.748),
        assets={DistributionLoad},
    )

    graph.add_nodes([source_node, secondary_node, load_node])

    transformer_edge = EdgeModel(
        name="xfmr",
        edge_type=DistributionTransformer,
        length=None,
    )

    branch_edge = EdgeModel(
        name="line",
        edge_type=MatrixImpedanceBranch,
        length=Distance(50, "m"),
    )

    graph.add_edge(source_node.name, secondary_node.name, edge_data=transformer_edge)
    graph.add_edge(secondary_node.name, load_node.name, edge_data=branch_edge)

    # Configure mappers
    phase_mapper = BalancedPhaseMapper(
        graph,
        method="greedy",
        mapper=[
            TransformerPhaseMapperModel(
                tr_name="xfmr",
                tr_type=TransformerTypes.SPLIT_PHASE,
                tr_capacity=ApparentPower(25, "kilovolt_ampere"),
                location=source_node.location,
            )
        ],
    )

    voltage_mapper = TransformerVoltageMapper(
        graph,
        xfmr_voltage=[
            TransformerVoltageModel(
                name="xfmr",
                voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
            )
        ],
    )

    equipment_mapper = _MockEquipmentMapper(
        graph,
        phase_mapper,
        voltage_mapper,
    )

    # Build system
    system_builder = DistributionSystemBuilder(
        name="export_test_system",
        dist_graph=graph,
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
    assert output_file.stat().st_size > 0

    # Load back and verify
    loaded_system = DistributionSystem.from_json(output_file)
    assert loaded_system.name == "export_test_system"
    assert len(list(loaded_system.get_components(DistributionBus))) == 3

    print(f"✓ Successfully exported system to {output_file}")
