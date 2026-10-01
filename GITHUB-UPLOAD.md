# GitHub Upload Package

The companion `Python311_package-github-source-20261001.zip` is a **source-code package** for GitHub review or a GitHub Release asset. It contains the application, tests, configuration, current documentation, VS Code settings and the small historical source reference. Historical PDFs under `docs/references/` are excluded.

It intentionally excludes `.venv/`, `package311/`, `download/`, `bk/`, generated `release/` bundles, caches and temporary admission state. Therefore it is not a self-contained offline deployment. To run the offline installers on another computer, transfer the required `package311/` wheelhouse separately and place it beside the root installer scripts. Do not commit the wheelhouse, backups or generated releases to the source repository; `.gitignore` excludes them.

## Upload as a GitHub Release Asset

Upload the ZIP and its adjacent `.sha256` file to a GitHub Release. Publish the expected SHA-256 through a trusted channel if recipients need integrity verification.

## Create a GitHub Source Repository

Extract the ZIP on the destination computer, then run from the extracted project directory:

```powershell
git init -b main
git add .
git status --short
git commit -m "Organize offline Python package workbench"
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Replace `OWNER/REPOSITORY` with the destination repository. Review `git status` before committing; ignored local data is intentionally absent from the upload. If a GitHub repository already contains commits, follow its import/push guidance rather than overwriting its history.

For offline runtime setup after extracting the source, see [development setup](docs/development/DEV-SETUP.md) and [offline release requirements](OFFLINE-RELEASE.md).
