"""Phase mapping tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from shift.mcp_server.state import AppContext


def _find_transformer_location(graph, tr_name):
    """Find the location of a transformer edge's downstream node."""
    from infrasys import Location

    for from_n, to_n, edge_data in graph.get_edges():
        if edge_data.name == tr_name:
            return graph.get_node(to_n).location

    try:
        return graph.get_node(tr_name).location
    except Exception:
        return Location(x=0, y=0)


def _build_mapper_models(graph, transformer_configs):
    """Build TransformerPhaseMapperModel list from config dicts."""
    from shift.data_model import TransformerPhaseMapperModel, TransformerTypes
    from gdm.quantities import ApparentPower

    models = []
    for tc in transformer_configs:
        models.append(
            TransformerPhaseMapperModel(
                tr_name=tc["tr_name"],
                tr_type=TransformerTypes(tc["tr_type"]),
                tr_capacity=ApparentPower(tc["tr_capacity_kva"], "kVA"),
                location=_find_transformer_location(graph, tc["tr_name"]),
            )
        )
    return models


def _format_phase_mapping(mapper, mapping_type):
    """Extract and serialise phase mapping by type. Returns (result, error)."""
    if mapping_type == "nodes":
        raw = mapper.node_phase_mapping
        return {k: [str(p) for p in v] for k, v in raw.items()}, None
    if mapping_type == "assets":
        raw = mapper.asset_phase_mapping
        result = {}
        for node_name, asset_dict in raw.items():
            result[node_name] = {
                asset_type.__name__: [str(p) for p in phases]
                for asset_type, phases in asset_dict.items()
            }
        return result, None
    if mapping_type == "transformers":
        raw = mapper.transformer_phase_mapping
        return {k: [str(p) for p in v] for k, v in raw.items()}, None
    return None, f"Unknown mapping_type '{mapping_type}'. Valid: nodes, assets, transformers"


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def configure_phase_mapper(
        ctx: Context[ServerSession, AppContext],
        graph_id: str,
        transformer_configs: list[dict],
        method: str = "agglomerative",
    ) -> str:
        """Configure balanced phase mapping for a distribution graph.

        Assigns phases (A, B, C) to nodes, assets, and transformers using
        a balanced allocation algorithm.

        Args:
            graph_id: Graph identifier.
            transformer_configs: List of transformer configuration dicts, each with:
                - tr_name: Transformer edge name in the graph
                - tr_type: Transformer type — one of "THREE_PHASE",
                  "SINGLE_PHASE", "SPLIT_PHASE",
                  "SINGLE_PHASE_PRIMARY_DELTA", "SPLIT_PHASE_PRIMARY_DELTA"
                - tr_capacity_kva: Transformer capacity in kVA
            method: Allocation method — "agglomerative" (default), "kmean", or "greedy".

        Returns:
            JSON confirmation with summary of phase assignments.
        """
        try:
            from shift.mapper.balanced_phase_mapper import BalancedPhaseMapper

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            mapper_models = _build_mapper_models(graph, transformer_configs)

            phase_mapper = BalancedPhaseMapper(graph, mapper_models, method=method)
            app.phase_mappers[graph_id] = phase_mapper

            return json.dumps(
                {
                    "success": True,
                    "graph_id": graph_id,
                    "method": method,
                    "num_transformers": len(mapper_models),
                    "message": "Phase mapper configured. Use get_phase_mapping to view assignments.",
                }
            )

        except Exception as exc:
            import traceback

            return json.dumps(
                {"success": False, "error": str(exc), "traceback": traceback.format_exc()}
            )

    @mcp.tool()
    def get_phase_mapping(
        ctx: Context[ServerSession, AppContext],
        graph_id: str,
        mapping_type: str = "nodes",
    ) -> str:
        """Get phase assignments for a distribution graph.

        Args:
            graph_id: Graph identifier.
            mapping_type: Type of mapping to retrieve:
                - "nodes": Phase assignment per node
                - "assets": Phase assignment per asset at each node
                - "transformers": Phase assignment per transformer

        Returns:
            JSON dict of phase assignments.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if graph_id not in app.phase_mappers:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No phase mapper configured for graph '{graph_id}'. "
                        "Use configure_phase_mapper first.",
                    }
                )

            result, error = _format_phase_mapping(app.phase_mappers[graph_id], mapping_type)
            if error:
                return json.dumps({"success": False, "error": error})

            return json.dumps(
                {
                    "success": True,
                    "mapping_type": mapping_type,
                    "mapping": result,
                    "count": len(result),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
