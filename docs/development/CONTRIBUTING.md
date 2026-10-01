# Contribution Guide

This repository targets Windows x64 and CPython 3.11. Keep the offline guarantee, package provenance, audit caveats, and immutable release workflow intact when proposing changes.

## Local Setup

Activate the project virtual environment and install only from the checked-in wheelhouse:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-ui.txt -r .\requirements-mcp.txt
```

Never add an online index or download fallback to an installer, resolver, or admission path. `package311/`, `download/`, `bk/`, `release/`, virtual environments, caches, and admission state are local/generated data, not source-control inputs.

## Before Submitting

Run the lint gate and focused test suite:

```powershell
.\.venv\Scripts\ruff.exe check .
.\run_tests.bat
```

`run_tests.bat` covers `test_offline_*.py`. The installer integration test is a separate, longer Windows x64 CPython 3.11 gate:

```powershell
.\.venv\Scripts\python.exe .\tests\test_uv_autoinstall.py
```

Use temporary wheelhouses and generated fixtures for unit tests. Tests must not mutate the real `package311/`, published release bundles, or the active user Python environment. Admission tests must prove both successful commit and failed-test rollback, and verify that existing wheels are not overwritten.

## Engineering Rules

- Keep the existing release-required inputs at the repository root: `autoinstall.bat`, `uv-autoinstall.bat`, `pwistron.txt`, `OFFLINE-RELEASE.md`, and `package311/`. `offline_release.py` validates these locations.
- Put shared package/audit behavior in `src/offline_package/catalog.py`; keep Dash and MCP in their package modules as transport/presentation layers. Preserve root compatibility shims unless a separately reviewed breaking change removes them.
- Keep external operations explicit and bounded. Resolver/install commands must be offline, use binary distributions, cap time, and avoid inherited pip index/config environment variables.
- Treat wheel metadata, license texts, project source, and MCP arguments as untrusted input. Do not execute projects to discover dependencies. A Python virtual environment is not an operating-system security sandbox.
- Never enable package admission by default. Preview the exact candidate, obtain human approval of its SHA-256, reject hash changes, validate RECORD, test offline, and commit atomically without overwriting.
- Report license declarations as evidence for human review, not legal clearance. Keep unknown/ambiguous applications unclassified rather than inventing certainty.
- Avoid hard-coded inventory totals, credentials, machine-specific paths, and claims of security or compatibility unsupported by tests.
- Keep changes scoped, preserve public interfaces unless required, and document user-facing or release-process changes.

## Review Checklist

- [ ] No network dependency or index fallback was introduced.
- [ ] Input paths, archive entries, file sizes, timeouts, and output sizes have bounded validation.
- [ ] Tests cover the success path and a meaningful rejection/failure path.
- [ ] Local data and immutable release artifacts remain unchanged.
- [ ] Documentation states target platform, operation effects, and residual limitations.
- [ ] The offline unit suite and relevant release gate pass.
