"""Concrete equipment mapper that supplies default node asset equipment.

:class:`EdgeEquipmentMapper` implements ``edge_equipment_mapping`` (selecting
conductors and transformers for each edge) but leaves
``node_asset_equipment_mapping`` abstract so callers can inject their own load
and voltage-source equipment. This class provides a sensible default: each load
node gets phase-matched :class:`LoadEquipment` (taken from the catalog when
available, otherwise a generic 10 kW / 3 kVAR load) and each voltage-source node
gets a balanced three-phase :class:`VoltageSourceEquipment` at the primary
voltage.
"""

from __future__ import annotations

from functools import cached_property

from gdm.distribution.components import (
    DistributionLoad,
    DistributionVoltageSource,
)
from gdm.distribution.equipment import (
    LoadEquipment,
    PhaseLoadEquipment,
    PhaseVoltageSourceEquipment,
    VoltageSourceEquipment,
)
from gdm.distribution.enums import VoltageTypes
from gdm.quantities import ActivePower, Reactance, ReactivePower, Voltage
from infrasys.quantities import Angle, Resistance

from shift.mapper.edge_equipment_mapper import EdgeEquipmentMapper


class DefaultLoadEquipmentMapper(EdgeEquipmentMapper):
    """Edge equipment mapper with default load and voltage-source equipment.

    Parameters
    ----------
    graph, catalog_sys, voltage_mapper, phase_mapper
        Same as :class:`EdgeEquipmentMapper`.
    source_voltage_kv: float
        Line-to-line voltage (kV) used for the default voltage source.
    """

    def __init__(
        self,
        graph,
        catalog_sys,
        voltage_mapper,
        phase_mapper,
        source_voltage_kv: float,
    ):
        self._source_voltage_kv = float(source_voltage_kv)
        super().__init__(graph, catalog_sys, voltage_mapper, phase_mapper)

    @staticmethod
    def _build_phase_matched_load(
        template: LoadEquipment, node_name: str, phase_count: int
    ) -> LoadEquipment:
        """Create load equipment whose phase_loads length matches the node phases."""
        count = max(1, phase_count)
        src_phase_loads = list(template.phase_loads) if template.phase_loads else []
        if not src_phase_loads:
            src_phase_loads = [
                PhaseLoadEquipment(
                    name=f"{node_name}_phase_load_template",
                    real_power=ActivePower(10, "kilowatt"),
                    reactive_power=ReactivePower(3, "kilovar"),
                    z_real=0,
                    z_imag=0,
                    i_real=0,
                    i_imag=0,
                    p_real=1,
                    p_imag=1,
                )
            ]

        total_p_kw = sum(pl.real_power.to("kilowatt").magnitude for pl in src_phase_loads)
        total_q_kvar = sum(pl.reactive_power.to("kilovar").magnitude for pl in src_phase_loads)

        base = src_phase_loads[0]
        per_phase_p_kw = total_p_kw / count if count else total_p_kw
        per_phase_q_kvar = total_q_kvar / count if count else total_q_kvar

        phase_loads = [
            PhaseLoadEquipment(
                name=f"{node_name}_phase_load_{idx + 1}",
                real_power=ActivePower(per_phase_p_kw, "kilowatt"),
                reactive_power=ReactivePower(per_phase_q_kvar, "kilovar"),
                z_real=base.z_real,
                z_imag=base.z_imag,
                i_real=base.i_real,
                i_imag=base.i_imag,
                p_real=base.p_real,
                p_imag=base.p_imag,
            )
            for idx in range(count)
        ]

        return LoadEquipment(name=f"{node_name}_load_equipment", phase_loads=phase_loads)

    @cached_property
    def node_asset_equipment_mapping(self) -> dict:
        mapping: dict = {}

        load_equips = (
            list(self.catalog_sys.get_components(LoadEquipment)) if self.catalog_sys else []
        )
        if load_equips:
            default_load = load_equips[0]
        else:
            default_load = LoadEquipment(
                name="default_load",
                phase_loads=[
                    PhaseLoadEquipment(
                        name="default_phase_load",
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

        vsrc = VoltageSourceEquipment(
            name="default_vsource",
            sources=[
                PhaseVoltageSourceEquipment(
                    name=f"vsrc_{i}",
                    r0=Resistance(0.001, "ohm"),
                    r1=Resistance(0.001, "ohm"),
                    x0=Reactance(0.001, "ohm"),
                    x1=Reactance(0.001, "ohm"),
                    voltage=Voltage(self._source_voltage_kv, "kV"),
                    voltage_type=VoltageTypes.LINE_TO_LINE,
                    angle=Angle(i * 120, "degree"),
                )
                for i in range(3)
            ],
        )

        for node in self.graph.get_nodes():
            if not node.assets:
                continue
            nm: dict = {}
            if DistributionLoad in node.assets:
                phases = self.phase_mapper.asset_phase_mapping[node.name][DistributionLoad]
                # The builder assigns this exact phase list (which may include the
                # neutral for split-phase loads) to the DistributionLoad, and gdm
                # validates that the number of phase_loads equals the number of
                # phases. Match the full length to satisfy that invariant.
                load_phase_count = len(phases)
                nm[DistributionLoad] = self._build_phase_matched_load(
                    default_load, node.name, load_phase_count
                )
            if DistributionVoltageSource in node.assets:
                nm[DistributionVoltageSource] = vsrc
            if nm:
                mapping[node.name] = nm
        return mapping
