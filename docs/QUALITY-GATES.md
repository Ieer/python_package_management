# Quality Gates

| Gate | Command | Proves | Does not prove |
| --- | --- | --- | --- |
| Static analysis | `run_lint.bat` | Configured Ruff correctness checks pass for tracked source/test scope | Runtime correctness, security certification or legal compliance |
| Fast functional suite | `run_tests.bat` | Offline catalog, UI and MCP fixtures pass; MCP stdio and temporary admission paths work | Behavior of every package in the full wheelhouse |
| Installer integration | `python tests/test_uv_autoinstall.py` | The real uv installer installs the declared manifest in a clean Windows x64 Python 3.11 environment, checks dependencies and extracts the browser archive | Application-specific smoke tests or release archive integrity |
| Archive build/verify | `python offline_release.py build <new-id>` then `python offline_release.py verify <archive>` | Fixed release inputs, archive contents and SHA-256 manifests pass | Publisher identity; sidecar transport authenticity |
| Human license review | Inspect exported license/notice and dependency evidence | Reviewers have package-level evidence to assess obligations | Automated legal approval; metadata may be incomplete or wrong |

Fast unit tests use synthetic wheelhouses and must not add test artifacts to the actual `package311/`. Keep installer integration and archive verification separate from quick feedback because they exercise larger, environment-specific release paths.
