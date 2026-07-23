"""System building tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from shift.mcp_server.state import AppContext


def _get_missing_mappers(app: AppContext, graph_id: str) -> list[str]:
    """Return list of missing mapper descriptions for a graph."""
    missing = []
    if graph_id not in app.phase_mappers:
        missing.append("phase_mapper (use configure_phase_mapper)")
    if graph_id not in app.voltage_mappers:
        missing.append("voltage_mapper (use configure_voltage_mapper)")
    if graph_id not in app.equipment_mappers:
        missing.append("equipment_mapper (use configure_equipment_mapper)")
    return missing


def _count_components(system, component_type) -> int:
    """Safely count components of a given type in a system."""
    try:
        return len(list(system.get_components(component_type)))
    except Exception:
        return 0


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def build_system(
        ctx: Context[ServerSession, AppContext],
        system_name: str,
        graph_id: str,
    ) -> str:
        """Build a complete distribution system from a configured graph.

        Requires that phase, voltage, and equipment mappers have all been
        configured for the given graph. Produces a GDM DistributionSystem
        with buses, transformers, branches, loads, and voltage source.

        Args:
            system_name: Name for the distribution system.
            graph_id: Graph identifier with configured mappers.

        Returns:
            JSON summary of the built system (component counts).
        """
        try:
            from shift.system_builder import DistributionSystemBuilder

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)

            missing = _get_missing_mappers(app, graph_id)
            if missing:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Missing mappers for graph '{graph_id}': {', '.join(missing)}",
                    }
                )

            builder = DistributionSystemBuilder(
                name=system_name,
                dist_graph=graph,
                phase_mapper=app.phase_mappers[graph_id],
                voltage_mapper=app.voltage_mappers[graph_id],
                equipment_mapper=app.equipment_mappers[graph_id],
            )
            system = builder.get_system()
            app.systems[system_name] = system

            return json.dumps(
                {
                    "success": True,
                    "system_name": system_name,
                    "graph_id": graph_id,
                    "message": "System built successfully. Use get_system_summary for details.",
                }
            )

        except Exception as exc:
            import traceback

            return json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )

    @mcp.tool()
    def get_system_summary(
        ctx: Context[ServerSession, AppContext],
        system_name: str,
    ) -> str:
        """Get a summary of a built distribution system.

        Args:
            system_name: Name of the system (from build_system).

        Returns:
            JSON with component counts (buses, branches, transformers,
            loads, solar, capacitors, voltage sources).
        """
        try:
            from gdm.distribution.components import (
                DistributionBus,
                DistributionBranchBase,
                DistributionTransformer,
                DistributionLoad,
                DistributionSolar,
                DistributionCapacitor,
                DistributionVoltageSource,
            )

            app: AppContext = ctx.request_context.lifespan_context
            if system_name not in app.systems:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No system found with name '{system_name}'. "
                        f"Available: {list(app.systems.keys())}",
                    }
                )

            system = app.systems[system_name]
            summary = {
                "success": True,
                "system_name": system_name,
                "buses": _count_components(system, DistributionBus),
                "branches": _count_components(system, DistributionBranchBase),
                "transformers": _count_components(system, DistributionTransformer),
                "loads": _count_components(system, DistributionLoad),
                "solar": _count_components(system, DistributionSolar),
                "capacitors": _count_components(system, DistributionCapacitor),
                "voltage_sources": _count_components(system, DistributionVoltageSource),
            }
            return json.dumps(summary)

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def list_systems(
        ctx: Context[ServerSession, AppContext],
    ) -> str:
        """List all built distribution systems in the current session.

        Returns:
            JSON array of system names.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            names = list(app.systems.keys())
            return json.dumps({"success": True, "systems": names, "count": len(names)})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
