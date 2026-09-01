from functools import cached_property
import math
from typing import Type
from uuid import uuid4
from loguru import logger


from infrasys.component import Component
from gdm.dataset.dataset_system import DatasetSystem
from gdm.quantities import ApparentPower, Current, Voltage
from gdm.distribution.components import (
    DistributionTransformer,
    DistributionBranchBase,
    DistributionLoad,
)
from gdm.distribution.equipment import (
    DistributionTransformerEquipment,
    SequenceImpedanceBranchEquipment,
    MatrixImpedanceBranchEquipment,
    GeometryBranchEquipment,
    LoadEquipment,
)
from gdm.distribution.enums import Phase, VoltageTypes

import networkx as nx

from shift.exceptions import (
    EquipmentNotFoundError,
    UnsupportedBranchEquipmentType,
    WrongEquipmentAssigned,
)
from shift.graph.distribution_graph import DistributionGraph
from shift.mapper.base_equipment_mapper import BaseEquipmentMapper
from shift.mapper.base_phase_mapper import BasePhaseMapper
from shift.mapper.base_voltage_mapper import BaseVoltageMapper
from shift.mapper.catalog_utils import phase_voltage_kv
from shift.constants import EQUIPMENT_TO_CLASS_TYPE


class EdgeEquipmentMapper(BaseEquipmentMapper):
    """Class interface for selecting edge equipment
    based on load equipment.

    Parameters
    ----------
    graph: DistributionGraph
        Instance of the distribution graph.
    catalog_sys: DatasetSystem
        Instance of Dataset system containing catalogs.
    voltage_mapper: BaseVoltageMapper
        Instance of the voltage mapper.
    phase_mapper: BasePhaseMapper
        Instance of the base phase mapper.

    """

    def __init__(
        self,
        graph: DistributionGraph,
        catalog_sys: DatasetSystem,
        voltage_mapper: BaseVoltageMapper,
        phase_mapper: BasePhaseMapper,
    ):
        self.catalog_sys = catalog_sys
        self.voltage_mapper = voltage_mapper
        self.phase_mapper = phase_mapper
        super().__init__(graph)

    def _get_load_power(self, load_equipment: LoadEquipment) -> ApparentPower:
        """Internal method to return total load power."""

        return ApparentPower(
            sum(
                [
                    math.sqrt(
                        (el.z_real + el.i_real + el.p_real)
                        * el.real_power.to("kilowatt").magnitude ** 2
                        + (el.z_imag + el.i_imag + el.p_imag)
                        * el.reactive_power.to("kilovar").magnitude ** 2
                    )
                    for el in load_equipment.phase_loads
                ]
            ),
            "kilova",
        )

    def _get_served_load(self, from_node: str, to_node: str) -> ApparentPower:
        """Internal method to get load served downward from this edge."""
        dfs_graph = self.graph.get_dfs_tree()
        parent_node = from_node if dfs_graph.has_edge(from_node, to_node) else to_node
        if parent_node not in dfs_graph:
            # Edge outside the source-connected tree (shouldn't happen after
            # connectivity enforcement); treat as serving no load.
            return ApparentPower(0, "kilova")
        descendants = list(nx.descendants(dfs_graph, parent_node))
        load_nodes = list(
            self.graph.get_nodes(
                filter_func=lambda x: (
                    x.name in descendants and x.assets is not None and DistributionLoad in x.assets
                )
            )
        )
        served_load = ApparentPower(0, "kilova")
        for node in load_nodes:
            equipment = self.node_asset_equipment_mapping[node.name][DistributionLoad]
            if not isinstance(equipment, LoadEquipment):
                msg = f"Wrong {equipment=} used for {node=}"
                raise WrongEquipmentAssigned(msg)
            served_load += self._get_load_power(equipment)
        return served_load

    @staticmethod
    def _is_phase_compatible(x: DistributionTransformerEquipment, num_phase: int) -> bool:
        if num_phase == 3 and x.windings[0].num_phases != 3:
            return False
        if num_phase < 3 and x.windings[0].num_phases != min(num_phase, 1):
            return False
        return True

    @staticmethod
    def _is_voltage_compatible(
        x: DistributionTransformerEquipment, num_phase: int, voltages: list
    ) -> bool:
        if not EdgeEquipmentMapper._is_phase_compatible(x, num_phase):
            return False
        wdg_voltages = sorted(
            (phase_voltage_kv(wdg.rated_voltage, wdg.voltage_type) for wdg in x.windings),
            reverse=True,
        )
        req_voltages = sorted((v.to("kilovolt").magnitude for v in voltages), reverse=True)
        for v1, v2 in zip(req_voltages, wdg_voltages[: len(req_voltages)]):
            if v2 < 0.85 * v1 or v2 >= 1.15 * v1:
                return False
        return True

    def _get_closest_transformer_equipment(
        self,
        capacity: ApparentPower,
        num_phase: int,
        voltages: list[Voltage],
        is_split_phase: bool = False,
    ) -> Component:
        """Internal method to return transformer equipment by capacity."""

        def filter_func(x: DistributionTransformerEquipment):
            min_capacity = min([wdg.rated_power.to("kva") for wdg in x.windings])
            if min_capacity < capacity:
                return False
            if is_split_phase and (not x.is_center_tapped or len(x.windings) != 3):
                return False
            if not self._is_phase_compatible(x, num_phase):
                return False
            wdg_voltages = sorted(
                (phase_voltage_kv(wdg.rated_voltage, wdg.voltage_type) for wdg in x.windings),
                reverse=True,
            )
            req_voltages = sorted((v.to("kilovolt").magnitude for v in voltages), reverse=True)
            for v1, v2 in zip(req_voltages, wdg_voltages[: len(req_voltages)]):
                if v2 < 0.85 * v1 or v2 >= 1.15 * v1:
                    logger.debug(f"Failed V1 {v1}, V2 {v2}, winding voltages {wdg_voltages}.")
                    return False
            return True

        trs: list[DistributionTransformerEquipment] = list(
            self.catalog_sys.get_components(
                DistributionTransformerEquipment, filter_func=filter_func
            )
        )
        if trs:
            return sorted(trs, key=lambda x: x.windings[0].rated_power)[0]

        return self._synthesize_transformer(
            capacity,
            num_phase,
            voltages,
            is_split_phase=is_split_phase,
        )

    def _synthesize_transformer(
        self,
        capacity: ApparentPower,
        num_phase: int,
        voltages: list[Voltage],
        is_split_phase: bool = False,
    ) -> Component:
        """Synthesize a transformer when no exact catalog match exists."""
        requested_voltages = [round(v.to("kilovolt").magnitude, 6) for v in voltages]
        available_transformers = list(
            self.catalog_sys.get_components(DistributionTransformerEquipment)
        )

        # The gdm_catalog stores only two-winding transformers, so split-phase
        # (120/240 V center-tapped) units must always be synthesized.
        if is_split_phase:
            return self._synthesize_split_phase(
                available_transformers,
                capacity,
                num_phase,
                voltages,
                requested_voltages,
            )

        voltage_compatible_candidates = [
            x
            for x in available_transformers
            if isinstance(x, DistributionTransformerEquipment)
            and self._is_voltage_compatible(x, num_phase, voltages)
        ]

        if voltage_compatible_candidates:
            return self._synthesize_capacity_override(
                voltage_compatible_candidates, capacity, num_phase, requested_voltages
            )

        return self._synthesize_full_override(
            available_transformers,
            capacity,
            num_phase,
            voltages,
            requested_voltages,
        )

    def _synthesize_split_phase(
        self, available_transformers, capacity, num_phase, voltages, requested_voltages
    ) -> Component:
        """Synthesize a center-tapped 120/240 V split-phase transformer."""
        templates = [x for x in available_transformers if self._is_phase_compatible(x, num_phase)]
        if not templates:
            msg = f"Equipment of type {DistributionTransformerEquipment} not found in catalog system."
            raise EquipmentNotFoundError(msg)

        base = sorted(
            templates,
            key=lambda x: min(w.rated_power.to("kva").magnitude for w in x.windings),
        )[-1]
        required_kva = capacity.to("kva").magnitude
        target_kva = round(required_kva * 1.05, 6)
        sorted_req_kv = sorted((v.to("kilovolt").magnitude for v in voltages), reverse=True)
        primary_kv, secondary_kv = sorted_req_kv[0], sorted_req_kv[-1]

        primary_template = base.windings[0]
        secondary_template = base.windings[-1]
        new_windings = []
        for idx in range(3):
            template = primary_template if idx == 0 else secondary_template
            new_windings.append(
                template.model_copy(
                    update={
                        "uuid": uuid4(),
                        "name": template.name or f"wdg_{idx + 1}",
                        "rated_power": ApparentPower(target_kva, "kva"),
                        "rated_voltage": Voltage(
                            primary_kv if idx == 0 else secondary_kv, "kilovolt"
                        ),
                        "voltage_type": VoltageTypes.LINE_TO_GROUND,
                    }
                )
            )

        new_uuid = uuid4()
        from gdm.distribution.common.sequence_pair import SequencePair

        synthesized = base.model_copy(
            update={
                "uuid": new_uuid,
                "name": f"{base.name}_split_synth_{str(new_uuid)[:8]}",
                "windings": new_windings,
                "is_center_tapped": True,
                "coupling_sequences": [
                    SequencePair(0, 1),
                    SequencePair(0, 2),
                    SequencePair(1, 2),
                ],
                "winding_reactances": [0.02, 0.02, 0.01],
            }
        )
        logger.warning(
            "Synthesized split-phase transformer {} from template {} "
            "(primary_kv={} secondary_kv={} capacity_kva={}).",
            synthesized.name,
            base.name,
            round(primary_kv, 6),
            round(secondary_kv, 6),
            round(required_kva, 6),
        )
        return synthesized

    def _synthesize_capacity_override(
        self, candidates, capacity, num_phase, requested_voltages
    ) -> Component:
        """Synthesize by overriding capacity on a voltage-compatible template."""
        base = sorted(
            candidates,
            key=lambda x: min(w.rated_power.to("kva").magnitude for w in x.windings),
        )[-1]
        required_kva = capacity.to("kva").magnitude
        target_kva = round(required_kva * 1.05, 6)

        new_uuid = uuid4()
        new_windings = [
            winding.model_copy(
                update={
                    "uuid": uuid4(),
                    "name": winding.name or f"wdg_{idx + 1}",
                    "rated_power": ApparentPower(target_kva, "kva"),
                }
            )
            for idx, winding in enumerate(base.windings)
        ]
        synthesized = base.model_copy(
            update={
                "uuid": new_uuid,
                "name": f"{base.name}_synth_{str(new_uuid)[:8]}",
                "windings": new_windings,
            }
        )
        logger.warning(
            "Synthesized transformer equipment {} from template {} for requested_capacity_kva={} requested_voltages_kv={} num_phase={}.",
            synthesized.name,
            base.name,
            round(required_kva, 6),
            requested_voltages,
            num_phase,
        )
        return synthesized

    def _synthesize_full_override(
        self,
        available_transformers,
        capacity,
        num_phase,
        voltages,
        requested_voltages,
    ) -> Component:
        """Synthesize by overriding both voltage and capacity on any template."""
        templates = [x for x in available_transformers if self._is_phase_compatible(x, num_phase)]
        if not templates:
            templates = available_transformers
        if not templates:
            logger.error(
                "No transformer equipment available to synthesize from. "
                "requested_capacity_kva={} requested_voltages_kv={} num_phase={}",
                round(capacity.to("kva").magnitude, 6),
                requested_voltages,
                num_phase,
            )
            msg = f"Equipment of type {DistributionTransformerEquipment} not found in catalog system."
            raise EquipmentNotFoundError(msg)

        base = sorted(
            templates,
            key=lambda x: min(w.rated_power.to("kva").magnitude for w in x.windings),
        )[-1]
        required_kva = capacity.to("kva").magnitude
        target_kva = round(required_kva * 1.05, 6)
        sorted_req_kv = sorted((v.to("kilovolt").magnitude for v in voltages), reverse=True)
        primary_kv, secondary_kv = sorted_req_kv[0], sorted_req_kv[-1]
        highest_winding = max(
            base.windings, key=lambda w: w.rated_voltage.to("kilovolt").magnitude
        )

        new_uuid = uuid4()
        new_windings = [
            winding.model_copy(
                update={
                    "uuid": uuid4(),
                    "name": winding.name or f"wdg_{idx + 1}",
                    "rated_power": ApparentPower(target_kva, "kva"),
                    "rated_voltage": Voltage(
                        primary_kv if winding is highest_winding else secondary_kv, "kilovolt"
                    ),
                    "voltage_type": VoltageTypes.LINE_TO_GROUND,
                }
            )
            for idx, winding in enumerate(base.windings)
        ]
        synthesized = base.model_copy(
            update={
                "uuid": new_uuid,
                "name": f"{base.name}_synth_{str(new_uuid)[:8]}",
                "windings": new_windings,
            }
        )
        logger.warning(
            "Synthesized transformer equipment {} from template {} with overridden "
            "primary_kv={} secondary_kv={} (requested_voltages_kv={}, num_phase={}, "
            "capacity_kva={}).",
            synthesized.name,
            base.name,
            round(primary_kv, 6),
            round(secondary_kv, 6),
            requested_voltages,
            num_phase,
            round(required_kva, 6),
        )
        return synthesized

    def _get_closest_branch_equipment(  # noqa: C901
        self, type_: Type[Component], current: Current, num_phase: int
    ) -> Component:
        """Internal method to return closest conductor equipment."""
        phase_only_filter = None

        if issubclass(type_, MatrixImpedanceBranchEquipment):

            def filter_func(x: MatrixImpedanceBranchEquipment):
                n_row, n_col = x.r_matrix.shape
                return x.ampacity > current and n_row == num_phase and n_col == num_phase

            def phase_only_filter(x: MatrixImpedanceBranchEquipment):
                n_row, n_col = x.r_matrix.shape
                return n_row == num_phase and n_col == num_phase

        elif issubclass(type_, SequenceImpedanceBranchEquipment):

            def filter_func(x: SequenceImpedanceBranchEquipment):
                return x.ampacity > current and num_phase >= 3

            def phase_only_filter(x: SequenceImpedanceBranchEquipment):
                return num_phase >= 3

        elif issubclass(type_, GeometryBranchEquipment):

            def filter_func(x: GeometryBranchEquipment):
                return max([c.ampacity for c in x.conductors]) > current and num_phase <= len(
                    x.conductors
                )

            def phase_only_filter(x: GeometryBranchEquipment):
                return num_phase <= len(x.conductors)

        else:
            msg = f"Not supported {type_=} passed to find branch equipment."
            raise UnsupportedBranchEquipmentType(msg)

        branches = list(self.catalog_sys.get_components(type_, filter_func=filter_func))

        branches = [el for el in branches if type(el) is type_]

        if not branches:
            phase_compatible = []
            if phase_only_filter is not None:
                phase_compatible = [
                    el
                    for el in self.catalog_sys.get_components(type_, filter_func=phase_only_filter)
                    if type(el) is type_
                ]

            if not phase_compatible:
                msg = f"Equipment of type {type_} not found in catalog system."
                raise EquipmentNotFoundError(msg)

            selected = sorted(phase_compatible, key=lambda x: x.ampacity)[-1]
            logger.warning(
                "No {} meets required current {} for num_phase={}. Falling back to highest-ampacity compatible equipment {} (ampacity={}).",
                type_.__name__,
                current,
                num_phase,
                selected.name,
                selected.ampacity,
            )
            return selected

        return sorted(branches, key=lambda x: x.ampacity)[0]

    @cached_property
    def edge_equipment_mapping(self) -> dict[str, Component]:
        edge_equipment_mapper = {}
        for from_node, to_node, edge in self.graph.get_edges():
            served_load = self._get_served_load(from_node, to_node)
            from_phases = self.phase_mapper.node_phase_mapping[from_node] - set(Phase.N)
            to_phases = self.phase_mapper.node_phase_mapping[to_node] - set(Phase.N)
            num_phase = min(len(from_phases), len(to_phases))
            if issubclass(edge.edge_type, DistributionTransformer):
                requested_voltages = [
                    self.voltage_mapper.node_voltage_mapping[from_node],
                    self.voltage_mapper.node_voltage_mapping[to_node],
                ]
                is_split_phase = bool({Phase.S1, Phase.S2} & (from_phases | to_phases))
                try:
                    edge_equipment_mapper[edge.name] = self._get_closest_transformer_equipment(
                        served_load,
                        num_phase,
                        requested_voltages,
                        is_split_phase=is_split_phase,
                    )
                except EquipmentNotFoundError:
                    logger.error(
                        "Transformer equipment selection failed for edge={} from_node={} to_node={} served_load_kva={} from_phases={} to_phases={} requested_voltages_kv={}",
                        edge.name,
                        from_node,
                        to_node,
                        round(served_load.to("kva").magnitude, 6),
                        sorted(str(ph) for ph in from_phases),
                        sorted(str(ph) for ph in to_phases),
                        [round(v.to("kilovolt").magnitude, 6) for v in requested_voltages],
                    )
                    raise
            elif issubclass(edge.edge_type, DistributionBranchBase):
                kv = self.voltage_mapper.node_voltage_mapping[from_node].to("kilovolt").magnitude
                kva = served_load.to("kilova").magnitude
                is_split_phase = Phase.S1 in from_phases or Phase.S2 in from_phases
                current = (
                    kva / kv
                    if num_phase == 1
                    else kva / (2 * kv)
                    if is_split_phase
                    else kva / (math.sqrt(3) * kv)
                )

                edge_equipment_mapper[edge.name] = self._get_closest_branch_equipment(
                    EQUIPMENT_TO_CLASS_TYPE[edge.edge_type],
                    Current(current, "ampere"),
                    num_phase,
                )
        return edge_equipment_mapper
