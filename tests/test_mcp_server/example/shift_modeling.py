from datetime import datetime, timedelta

from shapely.geometry import Polygon, Point
from shapely import distance

from infrasys.quantities import ActivePower, Resistance, Angle
from infrasys import System, SingleTimeSeries
from functools import cached_property

from shift import ParcelModel, GeoLocation, get_kmeans_clusters, PRSG
from shift import PlotManager, add_parcels_to_plot
from shift import add_distribution_graph_to_plot
from shift import parcels_from_location

from shift import EdgeEquipmentMapper, DistributionGraph, BaseVoltageMapper, BasePhaseMapper

import networkx as nx

from gdm.systems.distribution import DistributionSystem
from gdm.systems.distribution.common import VoltageLimitSet
from gdm.systems.distribution.components import (
    DistributionVoltageSource,
    DistributionTransformer,
    MatrixImpedanceBranch,
    DistributionLoad,
    DistributionBus,
)
from gdm.systems.distribution.distribution_graph import build_graph_from_system
from gdm.systems.distribution.equipment import (
    PhaseVoltageSourceEquipment,
    VoltageSourceEquipment,
    PhaseLoadEquipment,
    LoadEquipment,
)
from gdm.systems.distribution.enums import (
    ConnectionType,
    VoltageTypes,
    LimitType,
)
from gdm.quantities import Voltage, ReactivePower, Reactance

from resstock_comstock_interface import (
    RestockBuildingTypes,
    StockProfile,
    StockProfiler,
    mapped_building_type,
)


def get_parcels_in_polygon(coordinates: list[list[float, float]]):
    polygon = Polygon(coordinates)
    polygon_center = GeoLocation(polygon.centroid.x, polygon.centroid.y)
    parcels = parcels_from_location(coordinates)
    plot_manager = PlotManager(center=polygon_center)
    add_parcels_to_plot(parcels, plot_manager)
    return plot_manager, parcels, polygon_center


def _get_parcel_points(parcels: list[ParcelModel]) -> list[GeoLocation]:
    building_locations = []
    for parcel in parcels:
        if isinstance(parcel.geometry, list):
            points = [(point.longitude, point.latitude) for point in parcel.geometry]
            polygon = Polygon(points)
            location = GeoLocation(longitude=polygon.centroid.x, latitude=polygon.centroid.y)
            building_locations.append(location)
        else:
            building_locations.append(parcel.geometry)
    return building_locations


def plot_graph(graph, graph_center):
    plot_manager = PlotManager(center=graph_center)
    add_distribution_graph_to_plot(graph, plot_manager)
    return plot_manager


def build_graph_from_parcels(parcels, parcels_per_cluster, source_location):
    num_clusters = int(len(parcels) / parcels_per_cluster)
    clusters = get_kmeans_clusters(max([num_clusters, 1]), _get_parcel_points(parcels))
    builder = PRSG(
        groups=clusters,
        source_location=source_location,
    )
    graph = builder.get_distribution_graph()
    return graph


class CustomLoadMapper(EdgeEquipmentMapper):
    def __init__(
        self,
        graph: DistributionGraph,
        parcels: list[ParcelModel],
        catalog_sys: System,
        voltage_mapper: BaseVoltageMapper,
        phase_mapper: BasePhaseMapper,
        zip_code=None,
    ):
        self.voltage_mapper = voltage_mapper
        self.phase_mapper = phase_mapper
        self.catalog_sys = catalog_sys
        self.graph = graph
        self.parcels = parcels
        self.distribution_buses = {}
        if zip_code is None:
            self.zip_code = str(parcels[0].postal_address)
        else:
            self.zip_code = zip_code
        self.resstock = StockProfiler(StockProfile.RESSTOCK, self.zip_code)
        self.comstock = StockProfiler(StockProfile.COMSTOCK, self.zip_code)

    @cached_property
    def line_catalog(self):
        branch_catalog = self.catalog_sys.get_components(MatrixImpedanceBranch)
        catalog = {}
        for branch in branch_catalog:
            phases = tuple(branch.phases)

            if phases not in catalog:
                catalog[phases] = {}

            if branch.equipment.ampacity.magnitude not in catalog[phases]:
                catalog[phases][branch.equipment.ampacity.magnitude] = branch
        return catalog

    @cached_property
    def xfmr_catalog(self):
        transformer_catalog = self.catalog_sys.get_components(DistributionTransformer)
        catalog = {}
        for xfmr in transformer_catalog:
            catalog_phases = tuple([phase for bus in xfmr.buses for phase in bus.phases])

            if catalog_phases not in catalog:
                catalog[catalog_phases] = {}

            rated_power = xfmr.equipment.windings[0].rated_power.magnitude
            if rated_power not in catalog[catalog_phases]:
                catalog[catalog_phases][rated_power] = xfmr
        return catalog

    @cached_property
    def node_asset_equipment_mapping(self) -> dict[str, object]:
        directed_graph = nx.dfs_tree(self.graph._graph, source=self.graph.vsource_node)
        node_equipment_dict = {}

        distribution_systems = DistributionSystem(auto_add_composed_components=True)

        for node in self.graph.get_nodes():
            node_equipment_dict[node.name] = {}
            distribution_bus = self._build_node(node)
            distribution_systems.add_component(distribution_bus)
            self.distribution_buses[node.name] = distribution_bus

            if DistributionVoltageSource in node.assets:
                source = self._build_source(node)
                distribution_systems.add_component(source)

            if DistributionLoad in node.assets:
                load, active_power, profile = self._build_load(node)
                distribution_systems.add_component(load)

                start = datetime(year=2018, month=1, day=1)
                resolution = timedelta(hours=1)
                ts = SingleTimeSeries.from_array(
                    data=profile,
                    variable_name="real_power",
                    initial_time=start,
                    resolution=resolution,
                )
                distribution_systems.add_time_series(ts, load, scenario="base", model_year="2018")

            else:
                active_power = 0

            nx.set_node_attributes(directed_graph, {node.name: {"load": active_power}})

        max_load = []
        all_secondary_nodes = set()

        for e in nx.edges(directed_graph):
            ds_load = 0
            node_voltage = self.voltage_mapper.node_voltage_mapping[e[1]]
            secondary_nodes = nx.descendants(directed_graph, e[0])
            all_secondary_nodes = all_secondary_nodes | secondary_nodes

            for n in secondary_nodes:
                ds_load += directed_graph.nodes[n]["load"]

            nx.set_edge_attributes(
                directed_graph, {e: {"ds_load": ds_load, "voltage": node_voltage.magnitude}}
            )
            model_type = self.graph._graph.edges[e]["edge_data"]
            max_load.append(ds_load)

            if model_type.edge_type == DistributionTransformer:
                transformer = self._build_transformer(model_type, ds_load, e)
                distribution_systems.add_component(transformer)

                secondary_graph = directed_graph.subgraph(secondary_nodes)
                secondary_lines = self._build_branches(ds_load, secondary_graph)
                distribution_systems.add_components(*secondary_lines)

        primary_nodes = [
            n
            for n, v in self.voltage_mapper.node_voltage_mapping.items()
            if v.to("kilovolt").magnitude > 1.0
        ]
        primary_graph = directed_graph.subgraph(primary_nodes)
        primaries_lines = self._build_branches(max(max_load), primary_graph)
        distribution_systems.add_components(*primaries_lines)

        distribution_systems.info()
        gdm_graph = build_graph_from_system(distribution_systems)

        for edge in list(self.graph._graph.edges()):
            if not gdm_graph.has_edge(*edge):
                print(self.graph.get_edge(*edge))
        print(self.graph._graph)
        print(gdm_graph)
        distribution_systems.to_json("model.json", overwrite=True)
        return node_equipment_dict

    def _build_branches(self, max_load, graph):
        wires = []

        for edge in graph.edges():
            print(edge)
            buses = [self.distribution_buses[node] for node in edge]
            phases = buses[1].phases
            voltages = [bus.nominal_voltage for bus in buses]
            kva = max_load / 0.9
            current_req_amp = kva / voltages[0].to("kilovolt").magnitude

            selected_conductor = None
            for catalog_phases, info in self.line_catalog.items():
                if set(catalog_phases) == set(phases):
                    ampacities = list(self.line_catalog[catalog_phases].keys())
                    ampacities = [amp for amp in ampacities if amp > current_req_amp]
                    ampacities.sort()
                    if ampacities:
                        selected_conductor = info[ampacities[0]]
                    else:
                        ampacities = list(self.line_catalog[catalog_phases].keys())
                        ampacities.sort()
                        selected_conductor = info[ampacities[-1]]
                    break

            edge_model = self.graph._graph.edges[edge]["edge_data"]
            length = edge_model.length

            from uuid import uuid4

            wires.append(
                MatrixImpedanceBranch(
                    buses=buses,
                    length=length,
                    phases=selected_conductor.phases,
                    name=str(uuid4()),
                    equipment=selected_conductor.equipment,
                )
            )
        return wires

    def _build_transformer(self, model_type, ds_load, edge):
        worst_case_pf = 0.9
        xfmr_loading = ds_load / worst_case_pf * 0.2
        buses = [self.distribution_buses[node] for node in edge]
        phases = [phase for bus in buses for phase in bus.phases]
        selected_xfmr = None
        for phases_catalog, info in self.xfmr_catalog.items():
            if set(phases).issubset(phases_catalog):
                acceptable_ratings = [
                    xfmr_rating for xfmr_rating in list(info.keys()) if xfmr_rating > xfmr_loading
                ]

                acceptable_ratings.sort()
                if acceptable_ratings:
                    selected_xfmr = info[acceptable_ratings[0]]
                else:
                    acceptable_ratings = [xfmr_rating for xfmr_rating in list(info.keys())]
                    acceptable_ratings.sort()
                    selected_xfmr = info[acceptable_ratings[-1]]
                break

        if selected_xfmr.equipment.is_center_tapped:
            x_buses = [buses[0], buses[1], buses[1]]
        else:
            x_buses = buses

        for bus in buses:
            bus.pprint()
        selected_xfmr.equipment.pprint()

        return DistributionTransformer(
            name=f"{model_type.name}",
            buses=x_buses,
            winding_phases=selected_xfmr.winding_phases,
            equipment=selected_xfmr.equipment,
        )

    def _build_node(self, node):
        node_voltage = self.voltage_mapper.node_voltage_mapping[node.name]
        phases = self.phase_mapper.node_phase_mapping[node.name]
        return DistributionBus(
            voltage_type=VoltageTypes.LINE_TO_LINE,
            phases=phases,
            rated_voltage=node_voltage,
            name=node.name,
            voltagelimits=[
                VoltageLimitSet(
                    limit_type=LimitType.MIN, value=Voltage(node_voltage.magnitude * 0.9, "volt")
                ),
                VoltageLimitSet(
                    limit_type=LimitType.MAX, value=Voltage(node_voltage.magnitude * 1.1, "volt")
                ),
            ],
            coordinate=node.location,
        )

    def _build_source(self, node):
        phases = self.phase_mapper.asset_phase_mapping[node.name][DistributionVoltageSource]
        node_voltage = self.voltage_mapper.node_voltage_mapping[node.name]
        return DistributionVoltageSource(
            name=f"vsource_{node.name}",
            bus=self.distribution_buses[node.name],
            phases=phases,
            equipment=VoltageSourceEquipment(
                name=f"vsource_eqiup_{node.name}",
                sources=[
                    PhaseVoltageSourceEquipment(
                        name=f"vsource_phase_eqiup_{i}_{node.name}",
                        r0=Resistance(0.001, "ohm"),
                        r1=Resistance(0.001, "ohm"),
                        x0=Reactance(0.001, "ohm"),
                        x1=Reactance(0.001, "ohm"),
                        voltage=node_voltage,
                        angle=Angle(i * 120, "degree"),
                    )
                    for i in range(len(phases))
                ],
            ),
        )

    def _get_closest_parcel(self, node) -> ParcelModel | None:
        for parcel in self.parcels:
            if isinstance(parcel.geometry, list):
                points = [(point.longitude, point.latitude) for point in parcel.geometry]
                polygon = Polygon(points)
                in_polygon = polygon.contains(Point(node.location.x, node.location.y))
                if in_polygon:
                    return parcel
        min_distance = 1e20
        my_parcel = None
        for parcel in self.parcels:
            if isinstance(parcel.geometry, list):
                points = [(point.longitude, point.latitude) for point in parcel.geometry]
                polygon = Polygon(points)
                new_distance = distance(polygon, Point(node.location.x, node.location.y))
                if new_distance < min_distance:
                    min_distance = new_distance
                    my_parcel = parcel
        return my_parcel

    def _build_load(self, node):
        load_phases = self.phase_mapper.asset_phase_mapping[node.name][DistributionLoad]
        n_phases = len(load_phases)
        parcel = self._get_closest_parcel(node)
        supported_building_type = mapped_building_type[parcel.building_type]
        if supported_building_type in RestockBuildingTypes:
            profile = self.resstock.create_load_profiles(node, parcel)
        else:
            profile = self.comstock.create_load_profiles(node, parcel)
        active_power = max(profile)
        load_model = DistributionLoad(
            name=f"load_{node.name}",
            bus=self.distribution_buses[node.name],
            phases=load_phases,
            equipment=LoadEquipment(
                name=f"load_eqp_{node.name}",
                phase_loads=[
                    PhaseLoadEquipment(
                        real_power=ActivePower(active_power / n_phases, "kilowatt"),
                        reactive_power=ReactivePower(0, "kilovar"),
                        z_real=1.0,
                        z_imag=1.0,
                        i_real=0.0,
                        i_imag=0.0,
                        p_real=0.0,
                        p_imag=0.0,
                        name=f"load_eqp_{phs}_{node.name}",
                    )
                    for phs in range(n_phases)
                ],
                connection_type=ConnectionType.STAR,
            ),
        )

        return load_model, active_power, profile
