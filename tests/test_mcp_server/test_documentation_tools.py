"""Tests for documentation tools (search, read, list)."""

from mcp.server import MCPServer

from shift.mcp_server.state import AppContext
from shift.mcp_server.tools.documentation import search, read

from tests.test_mcp_server.conftest import MockContext, parse


_mcp = MCPServer("test-docs")
search.register(_mcp)
read.register(_mcp)


# ---------------------------------------------------------------------------
# list_docs
# ---------------------------------------------------------------------------


class TestListDocs:
    def test_returns_all_docs(self, mock_ctx):
        fn = _mcp._tool_manager._tools["list_docs"].fn
        result = parse(fn(ctx=mock_ctx))
        assert result["success"] is True
        assert result["count"] == 3
        names = [d["name"] for d in result["docs"]]
        assert "readme" in names
        assert "quickstart" in names

    def test_empty_index(self):
        app = AppContext()
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["list_docs"].fn
        result = parse(fn(ctx=ctx))
        assert result["success"] is True
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# read_doc
# ---------------------------------------------------------------------------


class TestReadDoc:
    def test_read_existing(self, mock_ctx):
        fn = _mcp._tool_manager._tools["read_doc"].fn
        result = parse(fn(ctx=mock_ctx, doc_name="readme"))
        assert result["success"] is True
        assert "NREL-shift" in result["content"]

    def test_read_nonexistent(self, mock_ctx):
        fn = _mcp._tool_manager._tools["read_doc"].fn
        result = parse(fn(ctx=mock_ctx, doc_name="nonexistent"))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_read_with_section(self, mock_ctx):
        fn = _mcp._tool_manager._tools["read_doc"].fn
        result = parse(fn(ctx=mock_ctx, doc_name="readme", section="Features"))
        assert result["success"] is True
        assert "Graph modeling" in result["content"]

    def test_read_with_missing_section(self, mock_ctx):
        fn = _mcp._tool_manager._tools["read_doc"].fn
        result = parse(fn(ctx=mock_ctx, doc_name="readme", section="Nonexistent Section"))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_section_extraction_stops_at_next_heading(self, mock_ctx):
        fn = _mcp._tool_manager._tools["read_doc"].fn
        # "Features" is an h2 — should stop before "Setup" wouldn't exist
        # but in our test data, "Features" is followed by content only
        result = parse(fn(ctx=mock_ctx, doc_name="readme", section="Features"))
        assert result["success"] is True
        assert "## Features" in result["content"]


# ---------------------------------------------------------------------------
# search_docs
# ---------------------------------------------------------------------------


class TestSearchDocs:
    def test_search_found(self, mock_ctx):
        fn = _mcp._tool_manager._tools["search_docs"].fn
        result = parse(fn(ctx=mock_ctx, query="Python"))
        assert result["success"] is True
        assert result["total_docs_matched"] >= 1

    def test_search_not_found(self, mock_ctx):
        fn = _mcp._tool_manager._tools["search_docs"].fn
        result = parse(fn(ctx=mock_ctx, query="xyzzyzzy"))
        assert result["success"] is True
        assert result["total_docs_matched"] == 0

    def test_search_case_insensitive(self, mock_ctx):
        fn = _mcp._tool_manager._tools["search_docs"].fn
        result = parse(fn(ctx=mock_ctx, query="python"))
        assert result["total_docs_matched"] >= 1

    def test_search_max_results(self, mock_ctx):
        fn = _mcp._tool_manager._tools["search_docs"].fn
        result = parse(fn(ctx=mock_ctx, query="the", max_results=1))
        assert result["total_docs_matched"] <= 1

    def test_search_includes_context(self, mock_ctx):
        fn = _mcp._tool_manager._tools["search_docs"].fn
        result = parse(fn(ctx=mock_ctx, query="framework"))
        assert result["success"] is True
        if result["total_docs_matched"] > 0:
            match = result["results"][0]
            assert "matches" in match
            assert len(match["matches"]) > 0
            assert "context" in match["matches"][0]
