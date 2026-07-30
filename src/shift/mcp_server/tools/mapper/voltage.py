"""Voltage mapping tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def configure_voltage_mapper(
        ctx: Context[AppContext],
        graph_id: str,
        transformer_voltages: list[dict],
    ) -> str:
        """Configure voltage mapping for a distribution graph.

        Maps voltage levels to nodes based on transformer voltage definitions.
        Nodes on the primary side get the primary voltage, nodes on the
        secondary side get the secondary voltage.

        Args:
            graph_id: Graph identifier.
            transformer_voltages: List of transformer voltage dicts, each with:
                - name: Transformer edge name in the graph
                - voltages_kv: List of voltage values in kV (e.g. [12.47, 0.24])

        Returns:
            JSON confirmation with summary.
        """
        try:
            from shift.mapper.transformer_voltage_mapper import TransformerVoltageMapper
            from shift.data_model import TransformerVoltageModel
            from gdm.quantities import Voltage

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)

            voltage_models = []
            for tv in transformer_voltages:
                voltages = [Voltage(v, "kV") for v in tv["voltages_kv"]]
                voltage_models.append(TransformerVoltageModel(name=tv["name"], voltages=voltages))

            voltage_mapper = TransformerVoltageMapper(graph, voltage_models)
            app.voltage_mappers[graph_id] = voltage_mapper

            return json.dumps(
                {
                    "success": True,
                    "graph_id": graph_id,
                    "num_transformers": len(voltage_models),
                    "message": "Voltage mapper configured. Use get_voltage_mapping to view assignments.",
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def get_voltage_mapping(
        ctx: Context[AppContext],
        graph_id: str,
    ) -> str:
        """Get voltage assignments for all nodes in a distribution graph.

        Args:
            graph_id: Graph identifier.

        Returns:
            JSON dict mapping node names to their voltage level in kV.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if graph_id not in app.voltage_mappers:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No voltage mapper configured for graph '{graph_id}'. "
                        "Use configure_voltage_mapper first.",
                    }
                )

            mapper = app.voltage_mappers[graph_id]
            raw = mapper.node_voltage_mapping
            result = {k: float(v.to("kV").magnitude) for k, v in raw.items()}

            return json.dumps(
                {
                    "success": True,
                    "mapping": result,
                    "count": len(result),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
