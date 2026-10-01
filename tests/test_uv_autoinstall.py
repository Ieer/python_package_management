#!/usr/bin/env python3
"""Run uv-autoinstall.bat in an isolated temporary Python environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from pathlib import Path


def require_supported_host() -> None:
    if os.name != "nt":
        raise RuntimeError("This integration test must run on Windows.")
    if sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise RuntimeError("Run this test with 64-bit CPython 3.11.")


def run_test(keep_temp: bool) -> int:
    require_supported_host()
    project_root = Path(__file__).resolve().parents[1]
    installer = project_root / "uv-autoinstall.bat"
    requirements = project_root / "pwistron.txt"
    browser_archive = project_root / "package311" / "ms-playwright.zip"
    for path in (installer, requirements, browser_archive):
        if not path.is_file():
            raise FileNotFoundError(f"Required test input is missing: {path}")

    temporary = tempfile.TemporaryDirectory(prefix="uv-autoinstall-test-", dir=project_root)
    temporary_root = Path(temporary.name)
    environment_dir = temporary_root / "venv"
    local_app_data = temporary_root / "local-app-data"
    local_app_data.mkdir()

    try:
        print(f"Creating isolated environment: {environment_dir}", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment_dir)
        python_exe = environment_dir / "Scripts" / "python.exe"
        if not python_exe.is_file():
            raise RuntimeError(f"Virtual environment Python was not created: {python_exe}")

        child_env = os.environ.copy()
        child_env["VIRTUAL_ENV"] = str(environment_dir)
        child_env["LOCALAPPDATA"] = str(local_app_data)
        child_env["PATH"] = str(environment_dir / "Scripts") + os.pathsep + child_env.get("PATH", "")
        child_env.pop("PYTHONHOME", None)

        print("Running uv-autoinstall.bat (offline package install, dependency check, browser extraction)...", flush=True)
        started = time.perf_counter()
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", installer.name],
            cwd=project_root,
            env=child_env,
            check=False,
            timeout=3600,
        )
        elapsed = time.perf_counter() - started
        print(f"Installer exit code: {completed.returncode}; elapsed: {elapsed:.2f} seconds")
        if completed.returncode != 0:
            raise RuntimeError(f"uv-autoinstall.bat failed with exit code {completed.returncode}.")

        uv_exe = environment_dir / "Scripts" / "uv.exe"
        if not uv_exe.is_file():
            raise RuntimeError(f"uv.exe was not installed into the test environment: {uv_exe}")
        subprocess.run([str(uv_exe), "--version"], check=True)

        print("Running an independent pip dependency check...", flush=True)
        subprocess.run([str(python_exe), "-m", "pip", "check"], check=True)

        with zipfile.ZipFile(browser_archive) as archive:
            chromium_members = [
                name
                for name in archive.namelist()
                if name.lower().endswith("/chrome-win/chrome.exe")
            ]
        if not chromium_members:
            raise RuntimeError("The browser archive contains no Chromium chrome.exe entry.")
        for member in chromium_members:
            extracted_browser = local_app_data / Path(member.replace("/", os.sep))
            if not extracted_browser.is_file():
                raise RuntimeError(f"Chromium browser file was not extracted: {extracted_browser}")

        print(f"Playwright browser extraction verified under: {local_app_data}")
        print("uv-autoinstall integration test passed.")
        return 0
    finally:
        if keep_temp:
            print(f"Keeping test environment for inspection: {temporary_root}")
            temporary._finalizer.detach() # type: ignore
        else:
            temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="keep the temporary virtual environment and isolated browser files for debugging",
    )
    args = parser.parse_args()

    try:
        return run_test(args.keep_temp)
    except (OSError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"TEST FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
