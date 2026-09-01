"""Utilities for aligning mappers with an equipment catalog.

The equipment mapper selects transformer equipment from a catalog by matching
the requested per-edge voltages within a +/-15% band. Catalogs store winding
voltages as either line-to-ground (e.g. 7.2 kV) or line-to-line (e.g. 12.47 kV);
GDM validates transformer windings against bus ratings using phase (line-to-ground)
voltage, so all comparisons here normalize to phase voltage. When the requested
voltages (e.g. 12.47/0.24 kV line-to-line) have no catalog match (catalogs
commonly store the line-to-ground / center-tapped equivalents such as
7.2/0.12 kV), building the system fails. These helpers snap a voltage mapper's
transformer voltages onto catalog-available equipment and derive a voltage
source rating from the mapped buses.
"""

from __future__ import annotations

import math

from gdm.distribution.enums import VoltageTypes

from shift.graph.distribution_graph import DistributionGraph


def phase_voltage_kv(voltage, voltage_type: VoltageTypes) -> float:
    """Return a voltage's line-to-ground (phase) magnitude in kV.

    Line-to-line values are divided by ``sqrt(3)``; line-to-ground values are
    returned unchanged.
    """
    magnitude = voltage.to("kilovolt").magnitude
    return magnitude / math.sqrt(3) if voltage_type == VoltageTypes.LINE_TO_LINE else magnitude


def catalog_transformer_voltage_options(catalog) -> set[tuple[float, float, int, bool]]:
    """Collect ``(primary_phase_kv, secondary_phase_kv, num_phases, is_center_tapped)``
    tuples from every transformer equipment in ``catalog`` (phase-normalized)."""
    from gdm.distribution.equipment import DistributionTransformerEquipment

    options: set[tuple[float, float, int, bool]] = set()
    for equipment in catalog.get_components(DistributionTransformerEquipment):
        winding_kv = sorted(
            (phase_voltage_kv(w.rated_voltage, w.voltage_type) for w in equipment.windings),
        )
        primary_kv = winding_kv[-1]
        secondary_kv = winding_kv[0]
        num_phases = max(int(getattr(w, "num_phases", 1) or 1) for w in equipment.windings)
        center_tapped = bool(getattr(equipment, "is_center_tapped", False))
        options.add((round(primary_kv, 6), round(secondary_kv, 6), num_phases, center_tapped))
    return options


def snap_voltage_mapper_to_catalog(
    graph: DistributionGraph, catalog, voltage_mapper, phase_mapper
):
    """Rebuild a voltage mapper whose transformer voltages match catalog equipment.

    For each transformer edge, snap the requested primary/secondary voltage to
    the nearest phase-compatible catalog transformer's phase voltages and rebuild
    the voltage mapper accordingly. Returns the (possibly rebuilt) voltage mapper.
    """
    from gdm.distribution.components import DistributionTransformer
    from gdm.distribution.enums import Phase
    from gdm.quantities import Voltage
    from shift.data_model import TransformerVoltageModel
    from shift.mapper.transformer_voltage_mapper import TransformerVoltageMapper

    options = catalog_transformer_voltage_options(catalog)
    if not options:
        return voltage_mapper

    node_voltages = voltage_mapper.node_voltage_mapping
    node_phases = phase_mapper.node_phase_mapping

    models: list[TransformerVoltageModel] = []
    for from_node, to_node, edge in graph.get_edges():
        if not issubclass(edge.edge_type, DistributionTransformer):
            continue
        # Bus voltages are line-to-ground, so they already are phase voltages.
        requested = sorted(
            [
                node_voltages[from_node].to("kilovolt").magnitude,
                node_voltages[to_node].to("kilovolt").magnitude,
            ],
            reverse=True,
        )
        req_primary, req_secondary = requested[0], requested[-1]

        from_phases = {ph for ph in node_phases[from_node] if ph != Phase.N}
        to_phases = {ph for ph in node_phases[to_node] if ph != Phase.N}
        num_phase = min(len(from_phases), len(to_phases)) or 1

        if num_phase >= 3:
            candidates = [opt for opt in options if opt[2] == 3]
        else:
            candidates = [opt for opt in options if opt[2] < 3 or opt[3]]
        if not candidates:
            candidates = list(options)

        best = min(
            candidates,
            key=lambda opt: abs(opt[0] - req_primary) + abs(opt[1] - req_secondary),
        )
        models.append(
            TransformerVoltageModel(
                name=edge.name,
                voltages=[Voltage(best[0], "kV"), Voltage(best[1], "kV")],
            )
        )

    if not models:
        return voltage_mapper

    return TransformerVoltageMapper(graph, models)


def source_voltage_kv(voltage_mapper, default: float = 12.47) -> float:
    """Return a source (substation) line-to-line voltage from the mapped buses."""
    node_voltages = getattr(voltage_mapper, "node_voltage_mapping", {}) or {}
    if not node_voltages:
        return default
    max_phase_kv = max(v.to("kilovolt").magnitude for v in node_voltages.values())
    return max_phase_kv * math.sqrt(3)
