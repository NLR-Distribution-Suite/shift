"""Equipment mapping tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from shift.mcp_server.state import AppContext


def _snap_voltage_mapper_to_catalog(graph, catalog, voltage_mapper, phase_mapper):
    """Align transformer-edge voltages with equipment available in the catalog.

    The equipment mapper selects transformer equipment from the catalog by
    matching the requested per-edge voltages within a +/-15% band. When the
    requested voltages (e.g. 12.47/0.24 kV line-to-line) have no catalog match
    (catalogs commonly store the line-to-ground / center-tapped equivalents such
    as 7.2/0.12 kV), building the system fails. This mirrors the SHIFT UI
    workaround: for each transformer edge, snap the requested primary/secondary
    to the nearest phase-compatible catalog transformer's voltages and rebuild
    the voltage mapper accordingly.

    Returns the (possibly rebuilt) voltage mapper.
    """
    from gdm.distribution.components import DistributionTransformer
    from gdm.distribution.equipment import DistributionTransformerEquipment
    from gdm.distribution.enums import Phase
    from gdm.quantities import Voltage
    from shift.data_model import TransformerVoltageModel
    from shift.mapper.transformer_voltage_mapper import TransformerVoltageMapper

    options: set[tuple[float, float, int, bool]] = set()
    for equipment in catalog.get_components(DistributionTransformerEquipment):
        winding_kv = sorted(
            (w.rated_voltage.to("kilovolt").magnitude for w in equipment.windings),
            reverse=True,
        )
        primary_kv = winding_kv[0]
        secondary_kv = winding_kv[-1]
        num_phases = max(int(getattr(w, "num_phases", 1) or 1) for w in equipment.windings)
        center_tapped = bool(getattr(equipment, "is_center_tapped", False))
        options.add((round(primary_kv, 6), round(secondary_kv, 6), num_phases, center_tapped))

    if not options:
        return voltage_mapper

    node_voltages = voltage_mapper.node_voltage_mapping
    node_phases = phase_mapper.node_phase_mapping

    models: list[TransformerVoltageModel] = []
    for from_node, to_node, edge in graph.get_edges():
        if not issubclass(edge.edge_type, DistributionTransformer):
            continue
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


def register(mcp: FastMCP) -> None:  # noqa: C901
    @mcp.tool()
    def configure_equipment_mapper(
        ctx: Context[ServerSession, AppContext],
        graph_id: str,
        catalog_path: str,
    ) -> str:
        """Configure equipment mapping using an equipment catalog.

        Maps edges to specific equipment models (conductors, transformers)
        from a catalog file. Requires phase and voltage mappers to be
        configured first.

        Args:
            graph_id: Graph identifier.
            catalog_path: Path to equipment catalog JSON file (DatasetSystem format).

        Returns:
            JSON confirmation.
        """
        try:
            from pathlib import Path
            from shift.mapper.default_load_equipment_mapper import (
                DefaultLoadEquipmentMapper,
            )
            from gdm.distribution import DistributionSystem as DatasetSystem
            from gdm.distribution.upgrade_handler.upgrade_handler import UpgradeHandler

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)

            if graph_id not in app.voltage_mappers:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Voltage mapper must be configured first. "
                        "Use configure_voltage_mapper.",
                    }
                )
            if graph_id not in app.phase_mappers:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Phase mapper must be configured first. "
                        "Use configure_phase_mapper.",
                    }
                )

            catalog_file = Path(catalog_path)
            if not catalog_file.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Catalog file not found: {catalog_path}",
                    }
                )

            catalog = DatasetSystem.from_json(
                catalog_file,
                upgrade_handler=UpgradeHandler().upgrade,
            )
            voltage_mapper = app.voltage_mappers[graph_id]
            phase_mapper = app.phase_mappers[graph_id]
            # Snap transformer-edge voltages to catalog-available equipment so the
            # equipment mapper can find matching transformers (mirrors SHIFT UI).
            voltage_mapper = _snap_voltage_mapper_to_catalog(
                graph, catalog, voltage_mapper, phase_mapper
            )
            app.voltage_mappers[graph_id] = voltage_mapper
            node_voltages = getattr(voltage_mapper, "node_voltage_mapping", {}) or {}
            source_voltage_kv = 12.47
            if node_voltages:
                source_voltage_kv = max(v.to("kilovolt").magnitude for v in node_voltages.values())
            equipment_mapper = DefaultLoadEquipmentMapper(
                graph,
                catalog,
                voltage_mapper,
                phase_mapper,
                source_voltage_kv=source_voltage_kv,
            )
            app.equipment_mappers[graph_id] = equipment_mapper

            return json.dumps(
                {
                    "success": True,
                    "graph_id": graph_id,
                    "catalog_path": str(catalog_path),
                    "message": "Equipment mapper configured. Use get_equipment_mapping to view assignments.",
                }
            )

        except Exception as exc:
            import traceback

            return json.dumps(
                {"success": False, "error": str(exc), "traceback": traceback.format_exc()}
            )

    @mcp.tool()
    def get_equipment_mapping(
        ctx: Context[ServerSession, AppContext],
        graph_id: str,
    ) -> str:
        """Get equipment assignments for all edges in a distribution graph.

        Args:
            graph_id: Graph identifier.

        Returns:
            JSON dict mapping edge names to equipment details.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if graph_id not in app.equipment_mappers:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No equipment mapper configured for graph '{graph_id}'. "
                        "Use configure_equipment_mapper first.",
                    }
                )

            mapper = app.equipment_mappers[graph_id]
            raw = mapper.edge_equipment_mapping
            result = {}
            for edge_name, component in raw.items():
                result[edge_name] = {
                    "type": type(component).__name__,
                    "name": getattr(component, "name", str(component)),
                }

            return json.dumps(
                {
                    "success": True,
                    "mapping": result,
                    "count": len(result),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
