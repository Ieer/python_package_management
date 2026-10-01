"""MCP policy tests and real SDK stdio transport integration."""

import asyncio
import json
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextResourceContents
from pydantic import AnyUrl
from test_offline_catalog import make_wheel

from offline_mcp import OfflineService, create_server


class MCPTests(unittest.TestCase):
    def test_root_compatibility_entrypoints_resolve_src_implementations(self):
        from offline_catalog import inventory
        from offline_dashboard import create_app

        self.assertEqual(OfflineService.__module__, "src.offline_package.mcp_server")
        self.assertEqual(inventory.__module__, "src.offline_package.catalog")
        self.assertEqual(create_app.__module__, "src.offline_package.dashboard")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        self.packages = self.repository / "package311"
        self.packages.mkdir(parents=True)
        make_wheel(self.packages, "numpy")
        self.service = OfflineService(self.repository)

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def completed_job(self, started):
        try:
            self.service.jobs[started["job_id"]]["future"].result(timeout=180)
        except ValueError:
            pass
        return self.service.get_job(started["job_id"])

    def test_summary_search_pagination_and_evidence(self):
        make_wheel(self.packages, "numpy", "2.0")
        self.assertEqual(self.service.summary()["audit"]["artifacts"], 2)
        result = self.service.search(domain="Data analysis", limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(self.service.search(review_only=True)["total"], 0)
        self.assertTrue(self.service.details("numpy-1.0-py3-none-any.whl", True)["license_texts"])
        with self.assertRaises(ValueError):
            self.service.search(limit=101)

    def test_path_and_filename_boundaries(self):
        outside = make_wheel(self.root)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.service.preview(str(outside))
        with self.assertRaises(ValueError):
            self.service.preview("\\\\server\\share\\demo.whl")
        with self.assertRaises(ValueError):
            self.service.details("../demo.whl")
        with self.assertRaises(ValueError):
            self.service.receipt("../outside")

    def test_preview_and_admission_default_disabled(self):
        preview = self.service.preview(str(self.packages / "numpy-1.0-py3-none-any.whl"))
        self.assertFalse(preview["installed"])
        self.assertEqual(len(preview["sha256"]), 64)
        self.assertIn("Data analysis", preview["metadata"]["domains"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.service.start_admission(preview["path"], preview["sha256"], True)

    def test_explicit_allowed_root(self):
        source = make_wheel(self.root)
        service = OfflineService(self.repository, [self.root])
        try:
            self.assertEqual(service.preview(str(source))["metadata"]["name"], "demo")
        finally:
            service.close()

    def test_bounded_task_queue(self):
        gate = threading.Event()

        def blocked():
            gate.wait(timeout=10)
            return {"ok": True}

        try:
            jobs = [self.service.submit("fixture", blocked) for _index in range(4)]
            with self.assertRaisesRegex(ValueError, "queue is full"):
                self.service.submit("fixture", blocked)
            self.assertIn(self.service.get_job(jobs[0]["job_id"])["status"], {"running", "queued"})
        finally:
            gate.set()

    def test_real_admission_and_saved_receipt(self):
        self.service.enable_admission = True
        source = make_wheel(self.repository)
        preview = self.service.preview(str(source))
        job = self.completed_job(self.service.start_admission(str(source), preview["sha256"], True))
        self.assertEqual(job["status"], "completed", job)
        self.assertTrue(job["result"]["ok"], job)
        self.assertEqual((self.packages / source.name).read_bytes(), source.read_bytes())
        receipt = self.service.receipt(preview["sha256"])
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["domains"], ["Unclassified"])

    def test_admission_requires_confirmation_and_snapshot_digest(self):
        self.service.enable_admission = True
        source = make_wheel(self.repository)
        preview = self.service.preview(str(source))
        with self.assertRaisesRegex(ValueError, "approval"):
            self.service.start_admission(str(source), preview["sha256"])
        with patch("src.offline_package.mcp_server.admit_wheel") as admitted:
            failure = self.completed_job(self.service.start_admission(str(source), "0" * 64, True))
            self.assertEqual(failure["status"], "failed")
            self.assertIn("SHA-256 mismatch", failure["error"])
            admitted.assert_not_called()
            admitted.return_value = {"ok": True, "log": "fixture"}
            success = self.completed_job(self.service.start_admission(str(source), preview["sha256"], True))
            self.assertTrue(success["result"]["ok"])
            candidate = admitted.call_args.args[0]
            self.assertNotEqual(candidate, source)
            self.assertEqual(candidate.name, source.name)

    def test_changed_candidate_is_not_admitted(self):
        self.service.enable_admission = True
        source = make_wheel(self.repository)
        preview = self.service.preview(str(source))
        source.write_bytes(source.read_bytes() + b"changed")
        with patch("src.offline_package.mcp_server.admit_wheel") as admitted:
            result = self.completed_job(self.service.start_admission(str(source), preview["sha256"], True))
            self.assertEqual(result["status"], "failed")
            admitted.assert_not_called()

    def test_background_requirements_and_validation(self):
        with self.assertRaises(ValueError):
            self.service.start_requirements(["demo @ https://example.org/demo.whl"])
        result = self.completed_job(self.service.start_requirements(["numpy==1.0"]))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["ok"], result)
        self.assertEqual(result["result"]["lock_text"], "numpy==1.0\n")
        with self.assertRaises(ValueError):
            self.service.get_job("missing")

    def test_project_directory_and_manifest(self):
        project = self.repository / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="fixture"\ndependencies=[]\n', encoding="utf-8")
        result = self.completed_job(self.service.start_project(str(project)))
        self.assertTrue(result["result"]["complete"])
        with self.assertRaisesRegex(ValueError, "outside"):
            self.service.start_project(str(self.root))

    def test_stdio_handshake_tools_resources_and_error(self):
        async def exercise():
            parameters = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parents[1] / "offline_mcp.py"), "--repository", str(self.repository)])
            async with stdio_client(parameters) as (reader, writer):  # noqa: SIM117
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=30)) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "Offline Package Repository")
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertEqual(len(names), 8)
                    self.assertNotIn("start_wheel_admission", names)
                    target_tool = next(tool for tool in tools.tools if tool.name == "search_packages")
                    self.assertIsNotNone(target_tool.annotations)
                    assert target_tool.annotations is not None
                    self.assertTrue(target_tool.annotations.readOnlyHint)
                    result = await session.call_tool("search_packages", {"query": "numpy"})
                    self.assertFalse(result.isError)
                    self.assertIsNotNone(result.structuredContent)
                    assert result.structuredContent is not None
                    self.assertEqual(result.structuredContent["total"], 1)
                    bad = await session.call_tool("package_details", {"filename": "../outside.whl"})
                    self.assertTrue(bad.isError)
                    policy = await session.read_resource(AnyUrl("offline://policy"))
                    self.assertIsInstance(policy.contents[0], TextResourceContents)
                    content = policy.contents[0]
                    assert isinstance(content, TextResourceContents)
                    self.assertFalse(json.loads(content.text)["admission_enabled"])
                    resources = await session.list_resources()
                    self.assertEqual(str(resources.resources[0].uri), "offline://policy")

        asyncio.run(exercise())

    def test_write_tool_annotation_when_enabled(self):
        self.service.enable_admission = True
        tools = asyncio.run(create_server(self.service).list_tools())
        admission = next(tool for tool in tools if tool.name == "start_wheel_admission")
        self.assertIsNotNone(admission.annotations)
        assert admission.annotations is not None
        self.assertFalse(admission.annotations.readOnlyHint)
        self.assertTrue(admission.annotations.destructiveHint)


if __name__ == "__main__":
    unittest.main()
