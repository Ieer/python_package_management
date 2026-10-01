#!/usr/bin/env python3
"""Build and verify immutable Python 3.11 offline release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Iterable

REQUIRED_FILES = (
    "autoinstall.bat",
    "uv-autoinstall.bat",
    "pwistron.txt",
    "OFFLINE-RELEASE.md",
)
REQUIRED_ARCHIVE_FILES = (
    *REQUIRED_FILES,
    "package311/ms-playwright.zip",
    "RELEASE-METADATA.json",
    "SHA256SUMS.txt",
)
RELEASE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
UV_VERSION_PATTERN = re.compile(r'^set\s+"UV_VERSION=([^"\r\n]+)"\s*$', re.MULTILINE | re.IGNORECASE)
MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")


class ReleaseError(Exception):
    """Raised when release inputs or archive integrity checks fail."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def package_files(package_dir: Path) -> list[tuple[Path, str]]:
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise ReleaseError(f"Package directory is missing or is a symlink: {package_dir}")

    files: list[tuple[Path, str]] = []
    for current, directories, filenames in os.walk(package_dir, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            candidate = current_path / directory
            if candidate.is_symlink():
                raise ReleaseError(f"Symlinks are not allowed in package311: {candidate}")
        for filename in filenames:
            source = current_path / filename
            if source.is_symlink() or not source.is_file():
                raise ReleaseError(f"Only regular files are allowed in package311: {source}")
            relative = source.relative_to(package_dir).as_posix()
            files.append((source, f"package311/{relative}"))

    return sorted(files, key=lambda item: item[1].casefold())


def validate_inputs(root: Path) -> tuple[str, list[tuple[Path, str]], int]:
    for name in REQUIRED_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ReleaseError(f"Required release file is missing: {path}")

    package_dir = root / "package311"
    files = package_files(package_dir)
    archive_names = {archive_name for _, archive_name in files}
    if "package311/ms-playwright.zip" not in archive_names:
        raise ReleaseError("package311/ms-playwright.zip is required by the installers.")

    installer_text = (root / "uv-autoinstall.bat").read_text(encoding="utf-8-sig")
    uv_match = UV_VERSION_PATTERN.search(installer_text)
    if not uv_match:
        raise ReleaseError('Could not read UV_VERSION from uv-autoinstall.bat.')
    uv_version = uv_match.group(1)
    uv_wheel = f"package311/uv-{uv_version}-py3-none-win_amd64.whl"
    if uv_wheel not in archive_names:
        raise ReleaseError(f"The uv wheel required by the installer is missing: {uv_wheel}")

    requirements_text = (root / "pwistron.txt").read_text(encoding="utf-8-sig")
    uv_pins = {
        line.strip().split("==", 1)[1]
        for line in requirements_text.splitlines()
        if line.strip().startswith("uv==") and "==" in line.strip()
    }
    if uv_pins != {uv_version}:
        raise ReleaseError(
            f"pwistron.txt must pin uv=={uv_version} exactly once to match uv-autoinstall.bat."
        )

    files.extend((root / name, name) for name in REQUIRED_FILES)
    names = [archive_name for _, archive_name in files]
    if len(names) != len(set(names)):
        raise ReleaseError("Duplicate archive paths were found in release inputs.")
    package_bytes = sum(path.stat().st_size for path, name in files if name.startswith("package311/"))
    return uv_version, sorted(files, key=lambda item: item[1].casefold()), package_bytes


def make_manifest(files: Iterable[tuple[Path, str]], metadata_bytes: bytes) -> bytes:
    lines = [f"{sha256_file(path)}  {name}" for path, name in files]
    lines.append(f"{hashlib.sha256(metadata_bytes).hexdigest()}  RELEASE-METADATA.json")
    return ("\n".join(lines) + "\n").encode("utf-8")


def verify_archive(archive_path: Path) -> dict[str, object]:
    archive_path = archive_path.resolve(strict=True)
    sidecar = archive_path.with_name(archive_path.name + ".sha256")
    if not sidecar.is_file():
        raise ReleaseError(f"Archive SHA-256 sidecar is missing: {sidecar}")
    sidecar_text = sidecar.read_text(encoding="utf-8-sig").strip()
    sidecar_match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", sidecar_text)
    if not sidecar_match or sidecar_match.group(2) != archive_path.name:
        raise ReleaseError(f"Invalid archive checksum sidecar: {sidecar}")
    archive_hash = sha256_file(archive_path)
    if archive_hash != sidecar_match.group(1).lower():
        raise ReleaseError("Archive SHA-256 does not match its sidecar.")

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            entries = archive.infolist()
            files = [entry for entry in entries if not entry.is_dir()]
            by_name: dict[str, zipfile.ZipInfo] = {}
            for entry in files:
                if entry.filename in by_name:
                    raise ReleaseError(f"Duplicate archive entry: {entry.filename}")
                if entry.compress_type != zipfile.ZIP_STORED:
                    raise ReleaseError(f"Archive entry is unexpectedly compressed: {entry.filename}")
                by_name[entry.filename] = entry

            missing = set(REQUIRED_ARCHIVE_FILES).difference(by_name)
            if missing:
                raise ReleaseError(f"Required files are missing from archive: {', '.join(sorted(missing))}")

            try:
                manifest_text = archive.read("SHA256SUMS.txt").decode("utf-8-sig")
            except (KeyError, UnicodeDecodeError) as error:
                raise ReleaseError("Archive SHA256SUMS.txt is missing or invalid UTF-8.") from error

            manifest_paths: set[str] = set()
            checked = 0
            for line in manifest_text.splitlines():
                match = MANIFEST_LINE.fullmatch(line)
                if not match:
                    raise ReleaseError(f"Invalid SHA-256 manifest line: {line}")
                expected_hash, name = match.groups()
                if name in manifest_paths:
                    raise ReleaseError(f"Duplicate manifest path: {name}")
                entry = by_name.get(name)
                if entry is None:
                    raise ReleaseError(f"Manifest entry is missing from archive: {name}")
                with archive.open(entry, "r") as stream:
                    actual_hash = sha256_stream(stream)
                if actual_hash != expected_hash:
                    raise ReleaseError(f"SHA-256 mismatch: {name}")
                manifest_paths.add(name)
                checked += 1

            untracked = set(by_name).difference(manifest_paths, {"SHA256SUMS.txt"})
            if untracked:
                raise ReleaseError(f"Untracked files in archive: {', '.join(sorted(untracked))}")
            if "SHA256SUMS.txt" in manifest_paths:
                raise ReleaseError("SHA256SUMS.txt must not hash itself.")

            try:
                metadata = json.loads(archive.read("RELEASE-METADATA.json"))
            except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ReleaseError("Release metadata is missing or invalid JSON.") from error
            if metadata.get("schema_version") != 1:
                raise ReleaseError(f"Unsupported release metadata schema: {metadata.get('schema_version')}")
            release_id = metadata.get("release_id")
            if not isinstance(release_id, str) or not RELEASE_NAME.fullmatch(release_id):
                raise ReleaseError("Release metadata contains an invalid release_id.")
            if archive_path.name != f"python311-offline-{release_id}.zip":
                raise ReleaseError("Archive filename does not match the release ID in metadata.")
            if metadata.get("package_file_count") != sum(
                name.startswith("package311/") for name in manifest_paths
            ):
                raise ReleaseError("Package file count does not match release metadata.")

    except zipfile.BadZipFile as error:
        raise ReleaseError(f"Invalid ZIP archive: {archive_path}") from error

    return {
        "archive": archive_path,
        "release_id": release_id,
        "files_hashed": checked,
        "archive_bytes": archive_path.stat().st_size,
        "sha256": archive_hash,
    }


def build_release(root: Path, release_id: str) -> dict[str, object]:
    if not RELEASE_NAME.fullmatch(release_id):
        raise ReleaseError("Release ID may contain only letters, numbers, dots, underscores, and hyphens.")
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise ReleaseError("Build releases with 64-bit CPython 3.11 on Windows.")

    release_root = root / "release"
    release_dir = release_root / release_id
    if release_dir.exists():
        raise ReleaseError(f"Release directories are immutable; destination already exists: {release_dir}")

    uv_version, files, package_bytes = validate_inputs(root)
    release_root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{release_id}-", dir=release_root))
    archive_name = f"python311-offline-{release_id}.zip"
    staged_archive = stage_dir / archive_name
    created_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    requirements = [
        line.strip()
        for line in (root / "pwistron.txt").read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    metadata = {
        "schema_version": 1,
        "release_id": release_id,
        "created_utc": created_utc,
        "python": "CPython 3.11, Windows x64",
        "installer": "uv-autoinstall.bat",
        "uv_version": uv_version,
        "requirements_file": "pwistron.txt",
        "requirement_count": len(requirements),
        "package_file_count": sum(name.startswith("package311/") for _, name in files),
        "package_bytes": package_bytes,
        "archive_compression": "none (payloads are already compressed)",
    }
    metadata_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_bytes = make_manifest(files, metadata_bytes)

    try:
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for source, archive_name_in_zip in files:
                archive.write(source, archive_name_in_zip, compress_type=zipfile.ZIP_STORED)
            archive.writestr("RELEASE-METADATA.json", metadata_bytes, compress_type=zipfile.ZIP_STORED)
            archive.writestr("SHA256SUMS.txt", manifest_bytes, compress_type=zipfile.ZIP_STORED)

        archive_hash = sha256_file(staged_archive)
        (stage_dir / f"{archive_name}.sha256").write_text(
            f"{archive_hash}  {archive_name}\n", encoding="utf-8", newline="\n"
        )
        (stage_dir / "SHA256SUMS.txt").write_bytes(manifest_bytes)
        verify_archive(staged_archive)

        if release_dir.exists():
            raise ReleaseError(f"Release destination appeared during build; refusing to overwrite: {release_dir}")
        stage_dir.rename(release_dir)
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    return verify_archive(release_dir / archive_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build", help="build a dated, immutable offline release")
    build_parser.add_argument("release_id", nargs="?", default=datetime.now().strftime("%Y%m%d"))
    verify_parser = subparsers.add_parser("verify", help="verify an archive and its SHA-256 sidecar")
    verify_parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "build":
            result = build_release(Path(__file__).resolve().parent, args.release_id)
        else:
            result = verify_archive(args.archive)
    except (OSError, ReleaseError, zipfile.BadZipFile) as error:
        print(f"Release error: {error}", file=sys.stderr)
        return 1

    print(f"Verified archive: {result['archive']}")
    print(f"Release ID: {result['release_id']}")
    print(f"Files hashed: {result['files_hashed']}")
    print(f"Archive size bytes: {result['archive_bytes']}")
    print(f"SHA256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
