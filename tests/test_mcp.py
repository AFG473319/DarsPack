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


def test_mcp_trash_and_restore(mcp_server, tmp_path):
    # Import a file
    f = tmp_path / "to_delete.txt"
    f.write_text("محتوای تستی برای سطل زباله", encoding="utf-8")
    imp_req = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "darspack_import_file", "arguments": {"path": str(f)}},
    }
    imp_res = json.loads(mcp_server.handle_request(imp_req)["result"]["content"][0]["text"])
    fid = imp_res["file_id"]

    # Move to trash
    trash_req = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "darspack_trash_file", "arguments": {"file_id": fid}},
    }
    trash_res = json.loads(mcp_server.handle_request(trash_req)["result"]["content"][0]["text"])
    assert trash_res["status"] == "success"
    trash_name = trash_res["trash_name"]

    # List trash
    list_trash_req = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "darspack_list_trash", "arguments": {}},
    }
    list_res = json.loads(mcp_server.handle_request(list_trash_req)["result"]["content"][0]["text"])
    assert list_res["count"] == 1
    assert list_res["items"][0]["trash_name"] == trash_name

    # Restore from trash
    restore_req = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "darspack_restore_trash_file", "arguments": {"trash_name": trash_name}},
    }
    restore_res = json.loads(mcp_server.handle_request(restore_req)["result"]["content"][0]["text"])
    assert restore_res["status"] == "success"
    assert restore_res["file_id"] is not None

    # Trash is empty now
    list_res_after = json.loads(mcp_server.handle_request(list_trash_req)["result"]["content"][0]["text"])
    assert list_res_after["count"] == 0


def test_mcp_package_export_verify_and_stats(mcp_server, tmp_path):
    # Import 2 files
    f1 = tmp_path / "sample1.txt"
    f1.write_text("درس یک", encoding="utf-8")
    f2 = tmp_path / "sample2.txt"
    f2.write_text("درس دو", encoding="utf-8")

    r1 = json.loads(mcp_server.handle_request({
        "jsonrpc": "2.0", "id": 30, "method": "tools/call",
        "params": {"name": "darspack_import_file", "arguments": {"path": str(f1)}}
    })["result"]["content"][0]["text"])
    r2 = json.loads(mcp_server.handle_request({
        "jsonrpc": "2.0", "id": 31, "method": "tools/call",
        "params": {"name": "darspack_import_file", "arguments": {"path": str(f2)}}
    })["result"]["content"][0]["text"])

    # Classify them
    mcp_server.handle_request({
        "jsonrpc": "2.0", "id": 32, "method": "tools/call",
        "params": {"name": "darspack_classify_file", "arguments": {"file_id": r1["file_id"], "subject": "علوم تجربی", "kind": "جزوه"}}
    })
    mcp_server.handle_request({
        "jsonrpc": "2.0", "id": 33, "method": "tools/call",
        "params": {"name": "darspack_classify_file", "arguments": {"file_id": r2["file_id"], "subject": "علوم تجربی", "kind": "کاربرگ"}}
    })

    # Stats
    stats_req = {"jsonrpc": "2.0", "id": 34, "method": "tools/call", "params": {"name": "darspack_get_stats", "arguments": {}}}
    stats_res = json.loads(mcp_server.handle_request(stats_req)["result"]["content"][0]["text"])
    assert stats_res["file_count"] == 2
    assert any(s["subject"] == "علوم تجربی" and s["count"] == 2 for s in stats_res["per_subject"])

    # Export package
    zip_out = tmp_path / "science_pack.zip"
    export_req = {
        "jsonrpc": "2.0", "id": 35, "method": "tools/call",
        "params": {"name": "darspack_export_package", "arguments": {"file_ids": [r1["file_id"], r2["file_id"]], "output_path": str(zip_out)}}
    }
    export_res = json.loads(mcp_server.handle_request(export_req)["result"]["content"][0]["text"])
    assert export_res["status"] == "success"
    assert export_res["count"] == 2
    assert zip_out.is_file()

    # Verify package
    verify_req = {
        "jsonrpc": "2.0", "id": 36, "method": "tools/call",
        "params": {"name": "darspack_verify_package", "arguments": {"package_path": str(zip_out)}}
    }
    verify_res = json.loads(mcp_server.handle_request(verify_req)["result"]["content"][0]["text"])
    assert verify_res["ok"] is True
    assert verify_res["problems"] == []

    # Check duplicates tool
    dup_req = {"jsonrpc": "2.0", "id": 37, "method": "tools/call", "params": {"name": "darspack_check_duplicates", "arguments": {}}}
    dup_res = json.loads(mcp_server.handle_request(dup_req)["result"]["content"][0]["text"])
    assert "exact_duplicates" in dup_res
    assert "version_conflicts" in dup_res
