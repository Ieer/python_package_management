"""Dash layout, local-only access, and audit callback smoke tests."""

import tempfile
import unittest
from email.message import Message
from pathlib import Path

from offline_catalog import application_info, domain_summary
from offline_dashboard import create_app
from test_offline_catalog import make_wheel


class DashboardTests(unittest.TestCase):
    def test_application_domains_and_unknown_package(self):
        self.assertEqual(application_info("NumPy")["domains"], ["Data analysis", "Scientific computing"])
        self.assertEqual(application_info("not-a-known-package")["domains"], ["Unclassified"])
        self.assertEqual(application_info("not-a-known-package")["use_cases"], [])

    def test_application_metadata_and_distinct_project_counts(self):
        metadata = Message()
        metadata["Summary"] = "Image helpers"
        metadata["Classifier"] = "Topic :: Scientific/Engineering :: Image Processing"
        info = application_info("custom-image-tools", metadata)
        self.assertEqual(info["domains"], ["Computer vision"])
        self.assertEqual(info["summary"], "Image helpers")
        self.assertIn(metadata["Classifier"], info["application_evidence"])
        rows = [{"name": "numpy", **application_info("numpy")}] * 2 + [{"name": "custom", **info}, {"name": "", **application_info("")}]
        result = domain_summary(rows)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(row["projects"] == 1 and row["percent"] == 50 for row in result))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.packages = self.root / "package311"
        self.packages.mkdir()
        make_wheel(self.packages)
        self.app = create_app(self.packages, self.root / "state")
        self.client = self.app.server.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_layout_and_local_assets(self):
        response = self.client.get("/_dash-layout", base_url="http://127.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Project dependencies", response.data)
        with self.client.get("/assets/offline-dashboard.css", base_url="http://127.0.0.1") as asset:
            self.assertEqual(asset.status_code, 200)
        with self.client.get("/", base_url="http://127.0.0.1") as index:
            self.assertIn(b'content="width=device-width, initial-scale=1"', index.data)

    def test_external_host_and_origin_rejected(self):
        self.assertEqual(self.client.get("/", base_url="http://untrusted.example").status_code, 403)
        self.assertEqual(self.client.get("/", base_url="http://127.0.0.1", headers={"Origin": "https://untrusted.example"}).status_code, 403)

    def test_audit_callback_counts(self):
        callback = next(value["callback"].__wrapped__ for key, value in self.app.callback_map.items() if "artifact-count.children" in key)
        result = callback(0, "all", None)
        self.assertEqual(result[:3], (1, 1, 0))
        self.assertEqual(result[6][0]["license"], "MIT")
        reviewed = callback(0, "review", None)
        self.assertEqual(reviewed[6], [])

    def test_domain_filter_and_classification_in_register(self):
        make_wheel(self.packages, "numpy")
        make_wheel(self.packages, "numpy", version="2.0")
        callback = next(value["callback"].__wrapped__ for key, value in self.app.callback_map.items() if "artifact-count.children" in key)
        result = callback(0, "all", None, "Scientific computing")
        self.assertEqual(len(result[6]), 2)
        self.assertTrue(all("Scientific computing" in row["domains"] for row in result[6]))
        domain = next(row for row in result[9] if row["domain"] == "Scientific computing")
        self.assertEqual(domain["projects"], 1)
        self.assertEqual(domain["percent"], 50)
        self.assertEqual(callback(0, "review", None, "Scientific computing")[6], [])
        self.assertEqual(callback(0, "all", None, "Unclassified")[6][0]["name"], "demo")

    def test_admission_metadata_preview_without_installation(self):
        source = make_wheel(self.root, "numpy")
        callback = self.app.callback_map["wheel-application.children"]["callback"].__wrapped__
        self.assertIn("Scientific computing", str(callback(str(source), None)))
        self.assertEqual(len(list(self.packages.iterdir())), 1)
        self.assertIsNone(callback(None, None))
        self.assertIn("CHECK", callback(str(self.root / "missing.whl"), None))

    def test_selected_license_text_displayed(self):
        callback = self.app.callback_map["artifact-detail.children"]["callback"].__wrapped__
        evidence = callback([0], [{"filename": "demo-1.0-py3-none-any.whl"}])
        self.assertIn("Fixture license evidence", evidence)

    def test_exports_only_enabled_for_current_results(self):
        callback = next(value["callback"].__wrapped__ for key, value in self.app.callback_map.items() if "export-lock.disabled" in key)
        self.assertEqual(callback(None, None), (True, True, True))
        self.assertEqual(callback({"ok": False}, {"ok": False}), (True, False, False))
        self.assertEqual(callback({"ok": True}, {"ok": True}), (False, False, False))


if __name__ == "__main__":
    unittest.main()