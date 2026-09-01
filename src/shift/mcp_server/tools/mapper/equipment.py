"""Equipment mapping tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext


def _snap_voltage_mapper_to_catalog(graph, catalog, voltage_mapper, phase_mapper):
    """Align transformer-edge voltages with equipment available in the catalog.

    This is the shared :func:`shift.mapper.catalog_utils.snap_voltage_mapper_to_catalog`.
    It is re-exported here so MCP server tools keep a stable private name.
    """
    from shift.mapper.catalog_utils import snap_voltage_mapper_to_catalog

    return snap_voltage_mapper_to_catalog(graph, catalog, voltage_mapper, phase_mapper)


def register(mcp: MCPServer) -> None:  # noqa: C901
    @mcp.tool()
    def configure_equipment_mapper(
        ctx: Context[AppContext],
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
            from shift.mapper.catalog_utils import source_voltage_kv

            equipment_mapper = DefaultLoadEquipmentMapper(
                graph,
                catalog,
                voltage_mapper,
                phase_mapper,
                source_voltage_kv=source_voltage_kv(voltage_mapper),
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
        ctx: Context[AppContext],
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
