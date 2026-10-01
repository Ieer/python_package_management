# Offline Package Audit Workbench

## Run

For agent-driven queries and operations through a local MCP server, see [OFFLINE-MCP.md](OFFLINE-MCP.md). MCP and Dash share the same catalog and admission service; neither requires the other to run.

Use 64-bit CPython 3.11 on Windows, from this repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-ui.txt
.\.venv\Scripts\python.exe .\offline_dashboard.py
```

Open http://127.0.0.1:8050. If occupied, use `--port 8051`. The app binds only to loopback, rejects external Host/Origin headers, loads Dash/Plotly assets locally, and does not require a CDN. Do not expose this administrative tool through a public proxy. It has filesystem access and is not a multi-user authenticated service.

## Workspaces

### License Audit

- Inventory is exclusively the root-level files in `package311`, matching pip's non-recursive wheelhouse discovery. One file is one artifact. Multiple versions count separately; unique projects are also reported.
- Wheels are indexed from METADATA. Source `.tar.gz` distributions are audited from root PKG-INFO without executing setup/build code, but remain `Source only / check` and cannot be resolved or admitted.
- License priority is License-Expression, then License, then license classifiers. Common explicit license aliases are normalized. Original declarations, classifiers, embedded license paths, and dependency metadata are retained in the audit JSON.
- Counts and percentages use all artifact files, including unreadable files and non-package assets in an Unknown group. The chart groups after the first eight declarations as Other; the distribution table and JSON retain every group.
- A review group is conservative: known simple permissive declarations, copyleft/review, or unknown/review. Ambiguous BSD variants, custom text, exceptions, compound expressions, unknown metadata, and non-wheel artifacts require review. An embedded LICENSE does not automatically override a conflicting declaration.
- Select an artifact to inspect and export embedded LICENSE/COPYING/NOTICE evidence. Reading is bounded to ten files of at most 200 KB each; larger/additional files need manual inspection. JSON/CSV exports cover the complete repository, not just filtered rows. CSV fields are guarded against spreadsheet formula injection.

### Application Domains

The audit workspace also shows application-domain counts, a chart, and a domain filter that combines with the license-review filter. Counts deduplicate project names across versions; a project may have multiple domains, so percentages can sum above 100%. Files with no readable project identity are excluded from this domain denominator, but remain in the artifact register as Unclassified.

Classification uses local exact-name rules and the artifact's Topic classifiers, without network requests or executing package code. Domain use cases are indicative, not a guarantee that every version implements every capability. Unknown packages remain Unclassified. The selected-package panel retains the publisher's Summary and classification evidence. JSON/CSV exports include domains and uses. On the admission page, entering a path or uploading a wheel previews these fields before installation; completed admission receipts also preserve them. These labels never override license review or compatibility/test gates.

### Project Dependencies

1. Enter a directory on the server computer and click **Import & check**. Project code is not imported or executed.
2. Direct runtime requirements come from `pyproject.toml` `[project].dependencies`, otherwise `requirements.in`, otherwise `requirements.txt`. Requirements includes and constraints are supported, but cannot escape the project directory. Explicit empty runtime declarations remain empty.
3. If no supported declaration exists, Python AST imports are mapped through wheel top-level modules. Standard-library and local modules are excluded. Unmapped/ambiguous imports, syntax errors, dynamic declarations, and scan limits produce review notes. This is a candidate list, not a guaranteed mathematical minimum. Conditional, dynamic, plugin, optional, notebook, and test imports need manual review. Poetry-only and executable setup.py declarations are not evaluated. Optional dependency groups are not automatically included; add needed extras/requirements in the editor.
4. Edit the direct requirements if necessary, then run **Check edited requirements**. Existing constraints are retained. Only the requested dependency closure is installed by the resolver; the large repository-wide `pwistron.txt` is not used.
5. A pip dry run in Windows x64 CPython 3.11 resolves versions, environment markers, extras, Python requirements, and transitive dependencies against a temporary wheelhouse sourced solely from `package311`. Host-installed packages are ignored. Unsupported/invalid wheels, incompatible tags, URL dependencies and source packages are excluded. Pip always uses `--no-index --no-cache-dir --only-binary=:all:`. URL/path requirements and installer options supplied by projects are rejected, so `--no-index` cannot be bypassed using a direct URL.
6. Missing direct requirements appear as CHECK rows. Missing/conflicting transitive requirements cause a CHECK result with pip's diagnostic in the resolver output. A successful dependency closure does not certify application behavior or a source-level minimum. No project environment is modified.
7. Export exact version pins and the check JSON. The version lock is target-specific and does not contain hashes; archive hashes and release gates remain the responsibility of the existing offline release workflow.

### Package Admission

1. Specify a local wheel file, or upload a wheel of up to 100 MB. For larger files use the local path. If both are present, the path takes priority.
2. Confirm trust in the wheel and all repository dependencies. A venv is environment isolation, not an OS security sandbox. Python startup hooks such as `.pth` may execute during installation/checks. Test unknown publishers in a disposable VM first.
3. The service copies the candidate to staging, validates safe ZIP paths, metadata/filename consistency, target tags, WHEEL/RECORD presence, all recorded SHA-256/384/512 hashes and sizes, and rejects unrecorded content and URL dependencies.
4. It creates a clean temporary venv, installs the candidate and dependency closure with pip strictly offline, then runs `pip check`. This tests installation/dependency consistency, not arbitrary import or application functionality. Additional project-specific smoke tests belong in your release gates.
5. Only successful tests commit a file to `package311`, using a same-directory temporary file and Windows no-overwrite rename. Existing files are never overwritten. Failures leave the repository unchanged. These operations never update `pwistron.txt` or previous release bundles.
6. Completed install tests retain SHA-256, declared license, timestamp and output in `.offline-ui/receipts`. Previous receipts can be inspected, and the current receipt can be downloaded. Structural validation errors are displayed before installation starts. Unused uploads remain in `.offline-ui/uploads` until removed; attempted uploaded candidates are cleaned up automatically. These state files are ignored by Git and are not included in offline releases.

## Review Boundaries

License declarations and hashes do **not** prove publisher identity, absence of malicious code, ownership of bundled assets, or copyright compliance. Before redistribution or commercial use, inspect the actual license and NOTICE texts, third-party/vendored components, dependency licenses, attribution requirements, patent conditions and any source-disclosure obligations. Unknown/custom/dual/copyleft licensing requires responsible human review. This tool is an evidence workbench, not legal advice or automatic approval.

The workbench uses two background worker threads, local task polling, temporary resolver/test environments, and a bounded in-memory job registry. It is intended for one local operator; tasks do not survive process restart. Installation timeout is ten minutes; resolver timeout is five minutes. The original installer scripts and immutable release archives are unchanged.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_offline_*.py" -v
```

Fixtures generate tiny local wheels and a source archive. Coverage includes license proportions/evidence, corrupt RECORD rejection, forbidden URL dependencies, project manifests/imports/includes, missing/version/platform checks, real pip transitive resolution, successful clean-venv admission, failed admission rollback, no overwrite, Dash layout/assets/callbacks, and loopback protections. They do not mutate the actual `package311` repository. The existing full installer integration test is separate and can be run according to OFFLINE-RELEASE.md.
