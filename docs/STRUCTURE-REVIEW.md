# Project Structure Review

## Assessment

The project had sound **logical boundaries** but mixed full implementations, entrypoints, guides, dependency manifests and binary data at the root. It now uses `src/offline_package/` for the installable core, `config/` for dependency manifests, and separate documentation areas for operations, development and historical references. Root compatibility shims preserve existing commands and import paths.

There is an important constraint: the release builder explicitly requires `autoinstall.bat`, `uv-autoinstall.bat`, `pwistron.txt`, `OFFLINE-RELEASE.md`, and `package311/` at the repository root. Root `offline_catalog.py`, `offline_dashboard.py`, and `offline_mcp.py` now forward to the `src` package so the Dash launcher, MCP configuration, tests, and existing imports keep working.

## Safe Organization Completed

- Active operational Markdown guides remain discoverable at the root while release input paths stay compatible.
- Current architecture, quality, competition and documentation indexes live in `docs/`.
- Historical PDF material is separated under `docs/references/` and labeled as background material, not current operational guidance.
- Core implementations and Dash CSS are grouped in `src/offline_package/`; project build metadata and Ruff settings are in root `pyproject.toml`.
- Actual UI/MCP/development requirements live under `config/`; one-line root requirement includes preserve existing pip commands and VS Code tasks.
- Operator guides are under `docs/operations/`; contributor/setup guides are under `docs/development/`.
- Large wheelhouse, download, backup, release and virtual-environment areas remain in place. They are data/state areas, not application source, and some are fixed by the release workflow.

## Current Layout

```text
repository/
├── README.md
├── autoinstall.bat, uv-autoinstall.bat, pwistron.txt, OFFLINE-RELEASE.md
├── offline_release.py              # Release builder/verifier; root contract
├── offline_catalog.py               # Compatibility import shim
├── offline_dashboard.py             # Compatibility CLI/import shim
├── offline_mcp.py                   # Compatibility stdio CLI/import shim
├── requirements-*.txt               # Compatibility includes -> config/
├── pyproject.toml
├── src/
│   └── offline_package/
│       ├── __init__.py
│       ├── catalog.py
│       ├── dashboard.py
│       ├── mcp_server.py
│       └── assets/
├── config/
│   └── requirements-{ui,mcp,dev}.txt
├── docs/
│   ├── operations/
│   ├── development/
│   ├── references/
│   └── architecture/                # Architecture, review and quality gates
├── tests/
├── .vscode/
├── package311/                      # Fixed local release input
├── download/, bk/, release/         # Local data and generated bundles
└── run_*.bat                        # Root compatibility launchers
```

The three compatibility shims are intentionally small. Implementations and package data are discovered by `pyproject.toml`; imports from the source checkout add `src/` through the shim, while built wheels contain the application-local CSS resource.

## Migration Sequence

1. Keep the fixed release inputs and root compatibility commands while they are referenced by evaluators or other automation.
2. If launchers or manifests move later, keep explicit forwarding files and update every VS Code task, installer, documentation link and test before removing old paths.
3. Remove compatibility wrappers only in a separately reviewed breaking change after confirming downstream consumers.

## Acceptance Criteria

- [x] `offline_release.py` validates the unchanged root package contract.
- [x] Dash and MCP root commands resolve to the `src` implementations.
- [x] UI, MCP, developer dependency manifests and documentation have dedicated locations with compatibility links.
- [x] Build and inspect an actual wheel to confirm package metadata and CSS inclusion.
- [x] Run the full offline unit suite after the source-layout migration.
- [ ] Run the separate installer integration/release gate before publishing a release.
- [x] No wheelhouse, backup or published release contents were moved or overwritten.
