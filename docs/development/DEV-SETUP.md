# Development Setup

## Prerequisites

- Windows x64
- CPython 3.11
- A project virtual environment at `.venv` (or activate a separate environment)
- The local `package311/` wheelhouse

## Install Offline

Install only the tool groups needed for your task. For the UI and MCP services:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-ui.txt -r .\requirements-mcp.txt
```

For source checks, install Ruff from the locally mirrored Windows wheel:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-dev.txt
```

The root `pyproject.toml` configures the `src/offline_package` build and Ruff. Actual dependency manifests live in `config/`: `pwistron.txt` describes the deployment set; `requirements-ui.txt` and `requirements-mcp.txt` describe the workbench adapters; `requirements-dev.txt` contains local quality tools. Root `requirements-*.txt` files are compatibility includes. Do not merge developer tools into the production offline manifest without release review.

When running an installed wheel outside the repository working directory, set `OFFLINE_PACKAGE_ROOT` to the local repository directory containing `package311/`. From the repository itself, the package discovers the root automatically.

## Repeatable Checks

```powershell
.\run_lint.bat
.\run_tests.bat
```

`run_lint.bat` runs the configured Ruff rules across source and tests. `run_tests.bat` runs the fast offline catalog, UI and MCP suite using temporary fixtures. For a release candidate, additionally run `tests\test_uv_autoinstall.py`, then build and verify a new immutable release ID as described in `OFFLINE-RELEASE.md`.

## VS Code

Open the repository root as a workspace. `.vscode/settings.json` selects the local interpreter and excludes binary-heavy data directories from file watching/search. `.vscode/tasks.json` exposes Dash, unit-test and offline dependency-install tasks. `.vscode/extensions.json` recommends Python, Pylance and Ruff; recommendations do not automatically install extensions.
