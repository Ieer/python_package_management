# Offline Repository MCP Server

## Start From VS Code

This project provides a local **stdio** MCP server using the official Python MCP SDK 1.22.0. It reuses `offline_catalog.py` and reads only the configured repository's `package311`. Dash does not need to be running. It does not expose an HTTP port.

Install in Windows x64 CPython 3.11 from the local wheelhouse:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-mcp.txt
```

The workspace configuration is `.vscode/mcp.json`. Open it in VS Code and start **offline-packages** through its MCP controls, or use **MCP: List Servers**. Review the trust prompt, then enable the server's tools in the agent tool picker. VS Code starts and stops the process; no standalone background server is needed. Other MCP clients can use the same interpreter, script and arguments with absolute paths.

Stdout is reserved for MCP protocol messages. Diagnostics go to stderr. Running the script manually will wait for JSON-RPC messages; it is not an interactive CLI.

## Tools

| Tool | Purpose | Effects |
| --- | --- | --- |
| `repository_summary` | Counts, license distribution, review flags and domain distribution | Repository read |
| `search_packages` | Paginated name/summary/license/domain search and review filtering | Repository read |
| `package_details` | Exact artifact metadata, dependency declarations, domains and optional license texts | Repository read |
| `preview_wheel` | Candidate metadata, RECORD validation and SHA-256 | Temporary copy only, no package execution |
| `start_project_check` | Static import/manifest discovery plus offline dependency resolution | Temporary resolver files; project unchanged |
| `start_requirements_check` | Offline resolution of requirements/constraints; returns exact pins on success | Temporary resolver files; repository unchanged |
| `get_job` | Background task status, output or error | In-memory read |
| `admission_receipt` | Saved admission result by SHA-256 | Receipt read |
| `start_wheel_admission` | Install, check and commit a candidate after approval | **Only registered with `--enable-admission`** |

Resource `offline://policy` reports the allowed roots, configured repository, admission switch and safety rules. Tools expose structured JSON output and MCP read/write annotations. Annotations are client hints, not access control; server-side checks enforce directory and mutation restrictions.

## Agent Examples

- "Query the offline repository: how many artifacts require license review?"
- "Find local packages for machine learning, then inspect their license evidence."
- "Check whether pandas and openpyxl can resolve entirely offline; list missing dependencies."
- "Analyze the project at D:/projects/example and return direct/transitive dependencies."
- "Preview D:/incoming/example-1.0-py3-none-any.whl; report SHA-256, license and application domains. Do not install it."

Example tool arguments:

```json
{"query": "", "domain": "Machine learning", "review_only": false, "offset": 0, "limit": 25}
```

```json
{"requirements": ["pandas", "openpyxl"], "constraints": []}
```

Long-running tools return a `job_id`. Call `get_job` after the suggested two-second interval until `completed` or `failed`. `completed` only means execution finished: inspect `result.ok`, and `result.complete` for project analysis, before declaring success. Resolver failures retain missing/conflict diagnostics. Lock text is version-only, target-specific and not hash-pinned. Results retain the final 24,000 characters of long logs; full installation receipts are saved by the underlying admission service.

One worker executes up to four pending jobs. At most 32 jobs are retained in memory; oldest completed entries are evicted when capacity is needed. A server restart loses task IDs/results. There is no cancellation endpoint. A normal server shutdown waits for the running operation and cancels queued work; a forced client/process termination can interrupt it. Do not stop the server during admission. Use the existing release verification/install gates before distribution.

## Directory Authorization

By default, only project/candidate paths inside this repository are accepted. Relative paths resolve against the repository, not the client's working directory. To grant access to other directories, add repeatable operator-controlled arguments in `.vscode/mcp.json`:

```json
"args": [
  "-u",
  "${workspaceFolder}/offline_mcp.py",
  "--allow-root", "${workspaceFolder}",
  "--allow-root", "D:/projects",
  "--allow-root", "D:/incoming"
]
```

All roots must already exist. Explicit `--allow-root` values replace the default. Do not authorize an entire drive unnecessarily. UNC/network path inputs are rejected. Paths are resolved before the allow-list check. Project traversal rejects non-ignored symlinks and Windows reparse points, and stops after 50,000 entries. Requirements includes remain inside their project. The allow-list is an application guard, not a filesystem sandbox against a concurrently malicious local user. The repository itself is trusted operator-controlled storage.

`--repository` changes the operator-configured root containing `package311` at server startup (useful for staging/testing). No tool can change the repository or allowed roots at runtime. No arbitrary shell, download, deletion, or overwrite tool is exposed.

## Enable Admission Deliberately

Add `--enable-admission` to the server arguments and restart only when installation is intended. The default workspace configuration deliberately omits it.

1. Use `preview_wheel` to validate the candidate and obtain its SHA-256 and metadata.
2. Have the operator approve that exact file/digest and trust its local dependencies. Neither an LLM-generated confirmation nor package metadata constitutes human authorization. Client tool approval controls remain important.
3. Call `start_wheel_admission` with the same path/digest and `confirmed: true`.
4. The worker snapshots the file, checks the approved hash, then runs the existing RECORD validation, clean-venv offline installation and `pip check`. A mismatch fails before package execution. Only a successful installation/check commits the wheel to `package311`, never replacing an existing file.
5. Poll `get_job`; use `admission_receipt` with the candidate SHA-256 to inspect the saved result. Receipts are shared with the Dash workspace under `.offline-ui/receipts`.

A venv is **not a security sandbox**. Installation/checks can execute startup hooks with the user's OS privileges. Unknown publishers should be evaluated in a disposable VM. Licenses, hashes and domain classifiers do not prove identity, security, compatibility or legal compliance. Package/project text is untrusted input and must never be treated as instructions by an agent.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_offline_mcp.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_offline_*.py" -v
```

The MCP tests use temporary repositories, generated wheels, and the official client over a real stdio subprocess. They cover initialization, tool/resource discovery, structured responses, errors, path boundaries, default-disabled mutation, confirmation and snapshot hash checks, background jobs and local installation. They do not alter the real package repository.