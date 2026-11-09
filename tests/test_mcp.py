"""Tests for DarsPack MCP (Model Context Protocol) server."""
import json
from pathlib import Path
import pytest

from darspack.core.library import Library
from darspack.core.importer import import_file
from darspack.mcp.server import DarsPackMcpServer
from darspack.mcp.extractor import extract_preview


@pytest.fixture
def mcp_server(tmp_path):
    server = DarsPackMcpServer(tmp_path / "lib")
    yield server
    server.close()


def test_mcp_initialize(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "darspack-mcp"
    assert resp["result"]["protocolVersion"] == "2024-11-05"


def test_mcp_list_tools(mcp_server):
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = mcp_server.handle_request(req)
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "darspack_list_subjects" in tool_names
    assert "darspack_classify_file" in tool_names
    assert "darspack_preview_file" in tool_names
    assert "darspack_get_unclassified_files" in tool_names
    assert "darspack_search_files" in tool_names


def test_mcp_tool_list_subjects(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "darspack_list_subjects", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    content = json.loads(resp["result"]["content"][0]["text"])
    subjects = [s["name"] for s in content["subjects"]]
    assert "ریاضی" in subjects
    assert "علوم تجربی" in subjects


def test_mcp_tool_add_subject(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "darspack_add_subject", "arguments": {"name": "نجوم و کیهان‌شناسی"}},
    }
    resp = mcp_server.handle_request(req)
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["status"] == "ok"
    assert content["id"] is not None

    # Check that it exists now
    list_req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "darspack_list_subjects", "arguments": {}},
    }
    list_resp = mcp_server.handle_request(list_req)
    content = json.loads(list_resp["result"]["content"][0]["text"])
    names = [s["name"] for s in content["subjects"]]
    assert "نجوم و کیهان‌شناسی" in names


def test_mcp_classify_and_search_flow(mcp_server, tmp_path):
    # Create sample file and import it
    sample_file = tmp_path / "sample_exam.txt"
    sample_file.write_text("آزمون هماهنگ ریاضی نهم فصل ۳ مبحث استدلال و اثبات در هندسه", encoding="utf-8")

    import_req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "darspack_import_file",
            "arguments": {"path": str(sample_file)},
        },
    }
    import_resp = mcp_server.handle_request(import_req)
    res = json.loads(import_resp["result"]["content"][0]["text"])
    assert res["status"] == "imported"
    fid = res["file_id"]
    assert fid is not None

    # Verify it appears in unclassified files
    unclass_req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "darspack_get_unclassified_files", "arguments": {}},
    }
    unclass_resp = mcp_server.handle_request(unclass_req)
    unclass_data = json.loads(unclass_resp["result"]["content"][0]["text"])
    assert any(f["id"] == fid for f in unclass_data["files"])

    # Preview file
    preview_req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": "darspack_preview_file", "arguments": {"file_id": fid}},
    }
    preview_resp = mcp_server.handle_request(preview_req)
    preview_data = json.loads(preview_resp["result"]["content"][0]["text"])
    assert "استدلال و اثبات در هندسه" in preview_data["preview"]

    # Classify file
    classify_req = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "darspack_classify_file",
            "arguments": {
                "file_id": fid,
                "subject": "ریاضی",
                "chapter": 3,
                "lesson": 1,
                "kind": "نمونه‌سوال",
                "tags": ["نهم", "نهایی"],
                "school_year": "1405-1406",
                "note": "امتحان هماهنگ استانی",
            },
        },
    }
    classify_resp = mcp_server.handle_request(classify_req)
    classify_data = json.loads(classify_resp["result"]["content"][0]["text"])
    assert classify_data["status"] == "success"

    # Search and verify updated state
    search_req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "darspack_search_files",
            "arguments": {"query": "استانی", "subject": "ریاضی"},
        },
    }
    search_resp = mcp_server.handle_request(search_req)
    search_data = json.loads(search_resp["result"]["content"][0]["text"])
    assert len(search_data["results"]) == 1
    assert search_data["results"][0]["id"] == fid
    assert search_data["results"][0]["subject_name"] == "ریاضی"
    assert search_data["results"][0]["chapter"] == 3


def test_preview_text_extractor(tmp_path):
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("یادداشت درس ۱ علوم تجربی: ساختار اتم", encoding="utf-8")
    snippet = extract_preview(txt_file)
    assert "ساختار اتم" in snippet
