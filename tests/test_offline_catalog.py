"""Focused tests using small synthetic wheels, without network access."""

import base64
import csv
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from offline_catalog import admit_wheel, artifact_evidence, audit_summary, check_roots, discover_project, inventory, read_wheel, repository_root, resolve_dependencies, safe_requirement


def make_wheel(directory, name="demo", version="1.0", requires=(), license_name="MIT", corrupt=False):
    path = directory / f"{name}-{version}-py3-none-any.whl"
    info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    if license_name:
        metadata += f"License: {license_name}\n"
    metadata += "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)
    entries = {f"{info}/METADATA": metadata.encode(), f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n", f"{name}/__init__.py": b"", f"{info}/licenses/LICENSE": b"Fixture license evidence"}
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for member, content in entries.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow([member, "sha256=" + digest, str(len(content))])
    writer.writerow([f"{info}/RECORD", "", ""])
    entries[f"{info}/RECORD"] = stream.getvalue().encode()
    if corrupt:
        entries[f"{name}/__init__.py"] = b"tampered"
    with zipfile.ZipFile(path, "w") as archive:
        for member, content in entries.items():
            archive.writestr(member, content)
    return path


class CatalogTests(unittest.TestCase):
    def test_explicit_repository_root_must_contain_wheelhouse(self):
        repository = self.root / "repository"
        (repository / "package311").mkdir(parents=True)
        invalid_root = self.root / "without-wheelhouse"
        invalid_root.mkdir()
        with patch.dict(os.environ, {"OFFLINE_PACKAGE_ROOT": str(repository)}):
            self.assertEqual(repository_root(), repository.resolve())
        with patch.dict(os.environ, {"OFFLINE_PACKAGE_ROOT": str(invalid_root)}):
            with self.assertRaisesRegex(ValueError, "package311"):
                repository_root()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.packages = self.root / "package311"
        self.packages.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_license_evidence_and_denominator(self):
        make_wheel(self.packages)
        make_wheel(self.packages, "unknown", license_name="")
        (self.packages / "browser.zip").write_bytes(b"not a wheel")
        rows = inventory(self.packages)
        summary = audit_summary(rows)
        self.assertEqual(summary["artifacts"], 3)
        self.assertEqual(summary["projects"], 2)
        self.assertEqual(summary["review"], 2)
        self.assertEqual(summary["licenses"][0]["percent"], 66.67)
        self.assertTrue(next(row for row in rows if row["name"] == "demo")["license_files"])

    def test_record_integrity(self):
        path = make_wheel(self.packages, corrupt=True)
        with self.assertRaisesRegex(ValueError, "RECORD mismatch"):
            read_wheel(path, verify=True)

    def test_alias_normalization_and_embedded_license(self):
        path = make_wheel(self.packages, license_name="Apache License, Version 2.0")
        self.assertEqual(read_wheel(path)["license"], "Apache-2.0")
        self.assertIn("Fixture license evidence", list(artifact_evidence(path.name, self.packages)["license_texts"].values()))

    def test_source_metadata_audited_without_building(self):
        path = self.packages / "source_demo-1.0.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            content = b"Metadata-Version: 2.1\nName: source-demo\nVersion: 1.0\nLicense: MIT\n"
            member = tarfile.TarInfo("source_demo-1.0/PKG-INFO")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        rows = inventory(self.packages)
        self.assertEqual(rows[0]["license"], "MIT")
        self.assertEqual(rows[0]["status"], "Source only / check")
        self.assertEqual(check_roots(["source-demo"], rows)[0]["status"], "CHECK: source only / invalid wheel")

    def test_reject_url_dependencies(self):
        with self.assertRaises(ValueError):
            safe_requirement("demo @ https://example.org/demo.whl")
        make_wheel(self.packages, requires=["evil @ https://example.org/evil.whl"])
        self.assertEqual(inventory(self.packages)[0]["status"], "Check")

    def test_declared_dependencies_do_not_include_test_imports(self):
        make_wheel(self.packages)
        project = self.root / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="example"\ndependencies=["demo>=1"]\n')
        (project / "app.py").write_text("import demo\nimport unavailable\nimport os\n")
        result = discover_project(project, inventory(self.packages))
        self.assertEqual(result["requirements"], ["demo>=1"])
        self.assertEqual(result["unresolved"], ["unavailable"])

    def test_import_fallback_and_local_modules(self):
        make_wheel(self.packages)
        project = self.root / "project"
        project.mkdir()
        (project / "local.py").write_text("")
        (project / "app.py").write_text("import demo\nimport local\nimport pathlib\n")
        result = discover_project(project, inventory(self.packages))
        self.assertEqual(result["requirements"], ["demo"])
        self.assertTrue(result["warnings"])

    def test_include_escape_rejected(self):
        project = self.root / "project"
        project.mkdir()
        (self.root / "external.txt").write_text("demo\n")
        (project / "requirements.txt").write_text("-r ../external.txt\n")
        with self.assertRaisesRegex(ValueError, "inside the project"):
            discover_project(project, [])

    def test_explicit_empty_dependencies_not_replaced_by_imports(self):
        project = self.root / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="example"\ndependencies=[]\n')
        (project / "app.py").write_text("import unknown\n")
        self.assertEqual(discover_project(project, [])["requirements"], [])

    def test_root_checks_missing_versions_and_markers(self):
        make_wheel(self.packages)
        checked = check_roots(["demo>=2", "absent", 'linuxonly; sys_platform == "linux"'], inventory(self.packages))
        self.assertIn("version", checked[0]["status"])
        self.assertEqual(checked[1]["status"], "CHECK: missing")
        self.assertEqual(checked[2]["status"], "Not applicable")

    @unittest.skipUnless(sys.platform == "win32", "Windows admission")
    def test_admission_install_check_receipt_and_no_overwrite(self):
        source_dir = self.root / "incoming"
        source_dir.mkdir()
        source = make_wheel(source_dir)
        result = admit_wheel(source, self.packages, self.root / "history")
        self.assertTrue(result["ok"], result["log"])
        self.assertEqual((self.packages / source.name).read_bytes(), source.read_bytes())
        self.assertTrue((self.root / "history" / (result["sha256"] + ".json")).is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            admit_wheel(source, self.packages)

    @unittest.skipUnless(sys.platform == "win32", "Windows admission")
    def test_failed_admission_keeps_repository_unchanged(self):
        source_dir = self.root / "incoming"
        source_dir.mkdir()
        source = make_wheel(source_dir, requires=["missing_child==1.0"])
        result = admit_wheel(source, self.packages)
        self.assertFalse(result["ok"])
        self.assertEqual(list(self.packages.iterdir()), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows target resolver")
    def test_offline_transitive_resolution_and_missing(self):
        make_wheel(self.packages, requires=["child==1.0"])
        make_wheel(self.packages, "child")
        result = resolve_dependencies(["demo==1.0"], self.packages)
        self.assertTrue(result["ok"], result["log"])
        self.assertEqual({item["name"] for item in result["packages"]}, {"demo", "child"})
        self.assertEqual(next(item for item in result["packages"] if item["name"] == "child")["kind"], "Transitive")
        (self.packages / "child-1.0-py3-none-any.whl").unlink()
        result = resolve_dependencies(["demo==1.0"], self.packages)
        self.assertFalse(result["ok"])
        self.assertIn("child", result["log"])


if __name__ == "__main__":
    unittest.main()
