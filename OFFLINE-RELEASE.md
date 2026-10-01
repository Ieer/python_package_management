# Python 3.11 Offline Release

## Contents

Each dated release contains `package311/`, `pwistron.txt`, `autoinstall.bat`, `uv-autoinstall.bat`, this guide, `RELEASE-METADATA.json`, and `SHA256SUMS.txt`.

The ZIP uses no compression for payload files. Wheels, browser archives, and source archives are already compressed; avoiding recompression cuts CPU time while retaining a standard ZIP archive.

## Build

From the project root, run with 64-bit CPython 3.11 on Windows:

```powershell
python .\offline_release.py build
```

The default release ID is the current date (`yyyyMMdd`). A specific ID can be supplied as the second argument, for example `python .\offline_release.py build 20260930`. A release is written to `release/<release-id>/python311-offline-<release-id>.zip`. Existing release directories are never overwritten. Use a new release ID for every changed package set or installer.

Before building, the script verifies the required installers, manifest, `package311/ms-playwright.zip`, and the uv wheel/version pin. The complete `package311/` tree, including the browser archive, is included without recompression. It hashes every packaged file, writes release metadata and a manifest into the archive, writes the manifest beside the archive, and creates an external archive SHA-256 sidecar. The archive is built in a temporary sibling directory, verified, then moved into its immutable release directory.

## Verify

```powershell
python .\offline_release.py verify .\release\20260930\python311-offline-20260930.zip
```

The verifier requires and checks the external archive hash, required archive paths, every per-file SHA-256, release metadata, duplicate entries, and untracked files. Verify the sidecar after transferring the ZIP, before extracting or installing it.

## Test the installer

Run the uv installer integration test from the project root:

```powershell
python .\tests\test_uv_autoinstall.py
```

The test creates an isolated Python 3.11 virtual environment and temporary `%LOCALAPPDATA%`, runs the offline installer, checks dependencies and Chromium extraction, then removes the temporary files. Add `--keep-temp` to retain the environment for debugging.

## Install

- Use 64-bit CPython 3.11 on Windows.
- For the uv route, activate the target virtual environment and run `uv-autoinstall.bat`. The script installs only from `package311`, runs `uv pip check`, then extracts `package311\ms-playwright.zip` under `%LOCALAPPDATA%`.
- For the pip route, activate the target environment and run `autoinstall.bat`. It also extracts `package311\ms-playwright.zip` under the local application data directory and requires 7-Zip at the configured path in that script.
- Keep release directories immutable. Update `pwistron.txt`, collect matching Windows/Python 3.11 artifacts, run the installer in a clean environment, run the verifier, then publish a new release ID.

## Release control

For local license evidence, project dependency checks, and tested wheel admission, see [the Dash workbench guide](docs/operations/OFFLINE-UI.md). The Dash workbench does not replace the clean-environment release gate or modify existing release archives.

- Treat `pwistron.txt` as the source of direct version pins; do not silently substitute a higher local version.
- A successful resolver is not a release gate by itself. Require a clean-environment offline installation and a successful dependency check before building.
- Retain the ZIP, external `.sha256`, and `SHA256SUMS.txt` together. Record the release ID in the deployment/change record.
- The hashes detect accidental corruption or untracked changes; they do not establish publisher identity. Distribute the expected outer SHA-256 through a separate trusted channel.

## Git publishing

- Track installer scripts, `pwistron.txt`, `offline_release.py`, this guide, and the Git configuration files in source control.
- Keep `package311/`, local download/backup directories, and generated `release/` archives out of Git. They contain large binary artifacts and are ignored by the root `.gitignore`.
- After the clean-environment install gate passes, build and verify the archive, then publish the ZIP, its `.sha256` sidecar, and `SHA256SUMS.txt` as release assets. Tag the exact source commit with the same release ID.