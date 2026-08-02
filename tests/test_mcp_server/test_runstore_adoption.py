"""Tests for the best-effort dist-stack runstore mirror in shift MCP tools.

Additive/best-effort contract (doc 11 §1.5, shift row):
- With ``DIST_STACK_RUNSTORE_DB`` set, successful graph/system builds record
  ``graph_``/``feeder_`` runs and ``export_system_json`` attaches an artifact.
- With it unset, the same calls behave exactly as before (no raises).

The PRSG and DistributionSystemBuilder internals are monkeypatched so the
tests exercise the tool + runstore wiring without network or heavy mappers.
"""

from __future__ import annotations

import pytest
from mcp.server import MCPServer

from dist_stack import RunstoreUnavailableError, list_artifacts, list_runs

from shift.mcp_server.state import AppContext, GraphMeta
from shift.mcp_server.tools.graph import builder as graph_builder
from shift.mcp_server.tools.system import builder as sys_builder, export

from tests.test_mcp_server.conftest import MockContext, parse


_mcp = MCPServer("test-runstore")
graph_builder.register(_mcp)
sys_builder.register(_mcp)
export.register(_mcp)

_GROUPS = [
    {
        "center": {"longitude": -105.2, "latitude": 39.75},
        "points": [{"longitude": -105.2, "latitude": 39.75}],
    }
]


def _build_graph_system_and_export(app_context, sample_graph, monkeypatch, export_path):
    """Run build_graph_from_groups → build_system → export_system_json.

    Heavy internals are replaced with fakes; returns (ctx, gid, results).
    """
    gid = "g1"
    app_context.graphs[gid] = sample_graph
    app_context.graph_meta[gid] = GraphMeta(
        name="g1", created_at="2026-01-01T00:00:00+00:00", node_count=3, edge_count=2
    )
    app_context.phase_mappers[gid] = "dummy"
    app_context.voltage_mappers[gid] = "dummy"
    app_context.equipment_mappers[gid] = "dummy"
    ctx = MockContext(app_context)

    class _FakePRSG:
        """Stand-in for the PRSG pipeline: returns a canned graph, no network."""

        def __init__(self, **kwargs):
            pass

        def get_distribution_graph(self):
            return sample_graph

    monkeypatch.setattr("shift.graph.prsgb.PRSG", _FakePRSG)

    class _FakeSystemBuilder:
        """Stand-in for DistributionSystemBuilder: builds an empty real system."""

        def __init__(self, **kwargs):
            self._name = kwargs["name"]

        def get_system(self):
            from gdm.distribution.distribution_system import DistributionSystem

            return DistributionSystem(name=self._name, auto_add_composed_components=True)

    monkeypatch.setattr("shift.system_builder.DistributionSystemBuilder", _FakeSystemBuilder)

    build_graph = _mcp._tool_manager._tools["build_graph_from_groups"].fn
    graph_result = parse(
        build_graph(
            ctx=ctx,
            groups=_GROUPS,
            source_longitude=-105.2,
            source_latitude=39.75,
        )
    )

    build_system = _mcp._tool_manager._tools["build_system"].fn
    sys_result = parse(build_system(ctx=ctx, system_name="s1", graph_id=gid))

    export_fn = _mcp._tool_manager._tools["export_system_json"].fn
    exp_result = parse(export_fn(ctx=ctx, system_name="s1", output_path=str(export_path)))

    return ctx, gid, graph_result, sys_result, exp_result


class TestSessionId:
    def test_app_context_has_session_id(self):
        app = AppContext()
        assert isinstance(app.session_id, str)
        assert len(app.session_id) == 12

    def test_session_id_is_stable_per_context(self):
        app = AppContext()
        assert app.session_id == app.session_id


class TestRunstoreAdoption:
    def test_records_runs_and_artifact(self, app_context, sample_graph, tmp_path, monkeypatch):
        """Env set: graph_/feeder_ runs recorded; export attaches an artifact."""
        db_path = tmp_path / "runstore.db"
        monkeypatch.setenv("DIST_STACK_RUNSTORE_DB", str(db_path))
        export_path = tmp_path / "s1.json"

        ctx, gid, graph_result, sys_result, exp_result = _build_graph_system_and_export(
            app_context, sample_graph, monkeypatch, export_path
        )
        assert graph_result["success"] is True
        assert sys_result["success"] is True
        assert exp_result["success"] is True

        runs = list_runs(runstore_db=str(db_path))

        graph_runs = [r for r in runs if r.run_id.startswith("graph_")]
        assert len(graph_runs) == 1
        gr = graph_runs[0]
        assert gr.tool == "build_graph_from_groups"
        assert gr.run_type == "shift_graph"
        assert gr.status == "succeeded"
        assert gr.session_id == app_context.session_id
        assert (gr.payload or {}).get("graph_id") == graph_result["graph_id"]
        assert (gr.payload or {}).get("node_count") == 3
        assert (gr.payload or {}).get("edge_count") == 2

        feeder_runs = [r for r in runs if r.run_id.startswith("feeder_")]
        assert len(feeder_runs) == 1
        fr = feeder_runs[0]
        assert fr.tool == "build_system"
        assert fr.run_type == "shift_feeder"
        assert fr.status == "succeeded"
        assert fr.session_id == app_context.session_id
        assert (fr.payload or {}).get("graph_id") == gid

        artifacts = list_artifacts(fr.run_id, runstore_db=str(db_path))
        assert len(artifacts) == 1
        assert artifacts[0].artifact_path == str(export_path)

    def test_env_unset_is_noop(self, app_context, sample_graph, tmp_path, monkeypatch):
        """Env unset: identical behavior — no raise from the same calls."""
        monkeypatch.delenv("DIST_STACK_RUNSTORE_DB", raising=False)
        export_path = tmp_path / "s1.json"

        _, _, graph_result, sys_result, exp_result = _build_graph_system_and_export(
            app_context, sample_graph, monkeypatch, export_path
        )
        assert graph_result["success"] is True
        assert sys_result["success"] is True
        assert exp_result["success"] is True
        assert export_path.is_file()

        # Precondition sanity: the runstore genuinely is unavailable.
        with pytest.raises(RunstoreUnavailableError):
            list_runs()
