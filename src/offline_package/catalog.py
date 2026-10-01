"""Local wheel audit, project discovery, and transactional offline admission."""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import tomllib
import venv
import zipfile
from collections import Counter
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import Version

def repository_root() -> Path:
    configured = os.environ.get("OFFLINE_PACKAGE_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve(strict=True)
        if (root / "package311").is_dir():
            return root
        raise ValueError("OFFLINE_PACKAGE_ROOT must contain a package311 directory")

    candidates = [Path(__file__).resolve().parents[2], Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        if (candidate / "package311").is_dir():
            return candidate.resolve()
    return Path(__file__).resolve().parents[2]


ROOT = repository_root()
PACKAGE_DIR = ROOT / "package311"
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "build", "dist"}
TARGET_TAGS = set(cpython_tags((3, 11), platforms=["win_amd64"])) | set(
    compatible_tags((3, 11), interpreter="cp311", platforms=["win_amd64"])
)
ADMISSION_LOCK = threading.Lock()
PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "0bsd", "zlib", "psf-2.0", "cc0-1.0", "unlicense"}

APPLICATION_RULES = (
    ("Data analysis", "Tabular data preparation, statistics and exploratory analysis.", "pandas numpy scipy polars statsmodels ydata-profiling missingno category-encoders phik"),
    ("Machine learning", "Predictive models, feature engineering and model evaluation.", "scikit-learn xgboost lightgbm catboost torch tensorflow keras transformers sentence-transformers"),
    ("Model inference", "Deploy and run trained models on supported hardware.", "openvino onnx onnxruntime torch tensorflow"),
    ("Natural language processing", "Text segmentation, sentiment analysis and semantic search.", "jieba snownlp nltk spacy transformers sentence-transformers tokenizers"),
    ("Computer vision", "Image processing, visual inspection and image similarity.", "opencv-python opencv-contrib-python pillow scikit-image imagehash"),
    ("Visualization", "Charts, analytical reports and interactive dashboards.", "matplotlib seaborn plotly bokeh altair pyecharts dash streamlit wordcloud"),
    ("Web applications", "Web applications, HTTP APIs and service interfaces.", "dash streamlit flask django fastapi starlette uvicorn waitress werkzeug"),
    ("Office automation", "Spreadsheet, document and desktop office workflows.", "openpyxl xlsxwriter xlrd xlwings python-docx python-pptx excel2img pywin32 comtypes jojo-office"),
    ("Browser automation", "Browser-based testing, page interaction and data collection.", "selenium playwright pyppeteer"),
    ("Web data collection", "HTTP clients, HTML parsing and structured web extraction.", "requests httpx aiohttp beautifulsoup4 lxml html5lib scrapy html2text"),
    ("Desktop applications", "Native desktop interfaces and GUI automation.", "pyqt5 pyqt6 pyside2 pyside6 wxpython pyautogui"),
    ("Workflow orchestration", "Scheduled jobs, task queues and data workflows.", "prefect apache-airflow luigi apscheduler celery schedule"),
    ("Databases", "Database connectivity, SQL access and persistence.", "sqlalchemy peewee pymysql psycopg2 psycopg2-binary pyodbc duckdb redis"),
    ("Security", "Cryptographic operations, password hashing and code security checks.", "cryptography pycryptodome bcrypt bandit"),
    ("Developer tools", "Testing, packaging, dependency management and code quality.", "pytest coverage black ruff mypy pip uv poetry setuptools wheel build pyinstaller"),
    ("Scientific computing", "Numerical computing, signal processing and graph analysis.", "numpy scipy sympy networkx pywavelets"),
    ("Media processing", "Audio/video editing, conversion and media analysis.", "moviepy imageio pydub librosa soundfile"),
    ("Documentation", "Documentation sites, notebooks and technical publishing.", "sphinx mkdocs mkdocs-material jupyter notebook jupyterlab nbconvert"),
)
TOPIC_DOMAINS = {
    "Scientific/Engineering :: Artificial Intelligence": "Machine learning",
    "Scientific/Engineering :: Image Processing": "Computer vision",
    "Scientific/Engineering :: Visualization": "Visualization",
    "Scientific/Engineering :: Mathematics": "Scientific computing",
    "Text Processing :: Linguistic": "Natural language processing",
    "Internet :: WWW/HTTP :: Dynamic Content": "Web applications",
    "Office/Business": "Office automation",
    "Database": "Databases",
    "Security :: Cryptography": "Security",
    "Software Development :: Testing": "Developer tools",
    "Software Development :: Build Tools": "Developer tools",
    "Multimedia :: Video": "Media processing",
    "Multimedia :: Sound/Audio": "Media processing",
    "Documentation": "Documentation",
}


def application_info(name: str, metadata=None) -> dict:
    normalized = canonicalize_name(name)
    domains, evidence = set(), []
    for domain, _use_case, names in APPLICATION_RULES:
        if normalized in names.split():
            domains.add(domain)
            evidence.append(f"Local package-name rule: {normalized} -> {domain}")
    topics = [value for value in metadata.get_all("Classifier", []) if value.startswith("Topic :: ")] if metadata is not None else []
    for topic in topics:
        value = topic.removeprefix("Topic :: ")
        for prefix, domain in TOPIC_DOMAINS.items():
            if value == prefix or value.startswith(prefix + " :: "):
                domains.add(domain)
                evidence.append(topic)
    return {
        "domains": sorted(domains) or ["Unclassified"],
        "use_cases": [use_case for domain, use_case, _names in APPLICATION_RULES if domain in domains],
        "summary": str(metadata.get("Summary", "")).strip() if metadata is not None else "",
        "application_evidence": sorted(set(evidence)) or ["No matching offline classification evidence"],
        "topic_classifiers": topics,
    }


def domain_summary(rows: list[dict]) -> list[dict]:
    projects = {}
    for row in rows:
        if row["name"]:
            projects.setdefault(row["name"], set()).update(row.get("domains", ["Unclassified"]))
    counts = Counter(domain for domains in projects.values() for domain in domains)
    return [{"domain": domain, "projects": count, "percent": round(100 * count / len(projects), 2)} for domain, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def license_info(metadata) -> tuple[str, str, str]:
    expression = str(metadata.get("License-Expression", "")).strip()
    declared = str(metadata.get("License", "")).strip()
    classifiers = [value.rsplit(" :: ", 1)[-1] for value in metadata.get_all("Classifier", []) if value.startswith("License ::") and value != "License :: OSI Approved"]
    aliases = {
        "mit license": "MIT", "http://www.opensource.org/licenses/mit-license.php": "MIT",
        "bsd": "BSD (unspecified)", "bsd license": "BSD (unspecified)",
        "apache software license": "Apache-2.0", "apache 2.0": "Apache-2.0",
        "apache 2": "Apache-2.0", "apache license 2.0": "Apache-2.0",
        "apache license, version 2.0": "Apache-2.0", "apache-2.0 license": "Apache-2.0",
        "osi approved :: apache software license": "Apache-2.0",
        "new bsd": "BSD-3-Clause", "new bsd license": "BSD-3-Clause",
        "bsd 3-clause license": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "bsd (3 clause)": "BSD-3-Clause",
        "2-clause bsd": "BSD-2-Clause", "2-clause bsd license": "BSD-2-Clause",
        "python software foundation license": "PSF-2.0", "isc license (iscl)": "ISC",
        "unknown": "Unknown", "": "Unknown",
    }
    value = expression or declared or "; ".join(classifiers) or "Unknown"
    value = aliases.get(value.lower(), value)
    if len(value) > 160 or "\n" in value:
        value = "Custom license text"
    lowered = value.lower()
    if lowered in PERMISSIVE:
        category = "Permissive"
    elif any(token in lowered for token in ("agpl", "gpl", "mpl", "epl", "lgpl")):
        category = "Copyleft / review"
    else:
        category = "Unknown / review"
    evidence = "License-Expression" if expression else "License" if declared else "Classifier" if classifiers else "Missing metadata"
    return value, category, evidence


def read_wheel(path: Path, verify: bool = False) -> dict:
    filename_name, filename_version, _, tags = parse_wheel_filename(path.name)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        if any(name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name for name in names):
            raise ValueError("Unsafe ZIP paths")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Expected exactly one wheel METADATA")
        metadata_name = metadata_names[0]
        if archive.getinfo(metadata_name).file_size > 2_000_000:
            raise ValueError("Wheel METADATA is too large")
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        name, version = metadata.get("Name", ""), metadata.get("Version", "")
        if canonicalize_name(name) != filename_name or Version(version) != filename_version:
            raise ValueError("Wheel filename and METADATA disagree")
        dependencies = metadata.get_all("Requires-Dist", [])
        for dependency in dependencies:
            if Requirement(dependency).url:
                raise ValueError("URL dependencies are prohibited in offline mode")
        license_name, category, evidence = license_info(metadata)
        dist_info = metadata_name.rsplit("/", 1)[0]
        license_files = [name for name in names if name.startswith(dist_info + "/") and any(token in name.rsplit("/", 1)[-1].lower() for token in ("license", "copying", "notice"))]
        modules = set()
        top_level = dist_info + "/top_level.txt"
        if top_level in names and archive.getinfo(top_level).file_size < 100_000:
            modules.update(archive.read(top_level).decode("utf-8").split())
        for member in names:
            first = member.split("/", 1)[0]
            if ".dist-info" in first or ".data" in first:
                continue
            if "/" in member and first.isidentifier():
                modules.add(first)
            elif member.endswith((".py", ".pyd")):
                module = first.split(".", 1)[0]
                if module.isidentifier():
                    modules.add(module)
        if verify:
            record_name = dist_info + "/RECORD"
            if dist_info + "/WHEEL" not in names or record_name not in names:
                raise ValueError("Missing WHEEL or RECORD")
            if archive.getinfo(record_name).file_size > 20_000_000:
                raise ValueError("Wheel RECORD is too large")
            records = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
            recorded = set()
            for row in records:
                if len(row) != 3 or row[0] in recorded:
                    raise ValueError("Invalid or duplicate RECORD row")
                member, encoded_hash, size = row
                recorded.add(member)
                if member not in names:
                    raise ValueError(f"RECORD references absent member: {member}")
                if member == record_name or member.endswith(("/RECORD.jws", "/RECORD.p7s")):
                    continue
                if not encoded_hash or not size:
                    raise ValueError(f"Missing RECORD hash: {member}")
                algorithm, expected = encoded_hash.split("=", 1)
                if algorithm not in {"sha256", "sha384", "sha512"}:
                    raise ValueError(f"Unsupported RECORD hash: {algorithm}")
                digest = hashlib.new(algorithm)
                length = 0
                with archive.open(member) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        length += len(block)
                actual = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
                if actual != expected or length != int(size):
                    raise ValueError(f"RECORD mismatch: {member}")
            unrecorded = set(names) - recorded
            if any(not member.endswith(("/", "/RECORD.jws", "/RECORD.p7s")) for member in unrecorded):
                raise ValueError("Unrecorded wheel content")
        return {
            **application_info(name, metadata),
            "filename": path.name, "name": canonicalize_name(name), "version": version,
            "license": license_name, "category": category, "evidence": evidence,
            "license_files": license_files, "license_declared": str(metadata.get("License", "")),
            "license_classifiers": [value for value in metadata.get_all("Classifier", []) if value.startswith("License ::")],
            "requires": dependencies, "requires_python": metadata.get("Requires-Python", ""),
            "modules": sorted(modules), "compatible": bool(tags & TARGET_TAGS),
            "bytes": path.stat().st_size, "status": "Indexed", "error": "",
        }


def read_sdist(path: Path) -> dict:
    filename_name, filename_version = parse_sdist_filename(path.name)
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        metadata_members = [member for member in members if member.isfile() and member.name.endswith("/PKG-INFO") and len(Path(member.name).parts) == 2]
        if len(metadata_members) != 1 or metadata_members[0].size > 2_000_000:
            raise ValueError("Expected one bounded root PKG-INFO")
        stream = archive.extractfile(metadata_members[0])
        if stream is None:
            raise ValueError("Unreadable PKG-INFO")
        with stream:
            metadata = BytesParser().parsebytes(stream.read())
        name, version = metadata.get("Name", ""), metadata.get("Version", "")
        if canonicalize_name(name) != filename_name or Version(version) != filename_version:
            raise ValueError("Source filename and PKG-INFO disagree")
        license_name, category, evidence = license_info(metadata)
        license_files = [member.name for member in members if member.isfile() and any(token in Path(member.name).name.lower() for token in ("license", "copying", "notice"))]
        return {**application_info(name, metadata), "filename": path.name, "name": canonicalize_name(name), "version": version,
                "license": license_name, "category": category, "evidence": "PKG-INFO / " + evidence,
                "license_files": license_files, "license_declared": str(metadata.get("License", "")),
                "requires": metadata.get_all("Requires-Dist", []), "requires_python": metadata.get("Requires-Python", ""),
                "modules": [], "compatible": False, "bytes": path.stat().st_size,
                "status": "Source only / check", "error": "Build a trusted Windows/Python 3.11 wheel before offline resolution"}


def artifact_evidence(filename: str, package_dir: Path = PACKAGE_DIR) -> dict:
    if Path(filename).name != filename:
        raise ValueError("Invalid artifact filename")
    row = next((item for item in inventory(package_dir) if item["filename"] == filename), None)
    if row is None:
        raise ValueError("Artifact not found")
    texts = {}
    path = package_dir / filename
    if path.is_symlink():
        raise ValueError("Symlink artifacts are not allowed")
    if row["license_files"]:
        if path.suffix.lower() == ".whl":
            with zipfile.ZipFile(path) as archive:
                for member in row["license_files"][:10]:
                    if archive.getinfo(member).file_size <= 200_000:
                        texts[member] = archive.read(member).decode("utf-8", errors="replace")
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                for member in row["license_files"][:10]:
                    info = archive.getmember(member)
                    if info.isfile() and info.size <= 200_000:
                        stream = archive.extractfile(info)
                        if stream:
                            with stream:
                                texts[member] = stream.read().decode("utf-8", errors="replace")
    return dict(row, license_texts=texts, evidence_scope="Up to 10 license/notice files, 200 KB each. Missing or larger files require manual inspection.")


def inventory(package_dir: Path = PACKAGE_DIR) -> list[dict]:
    if not package_dir.is_dir():
        raise ValueError(f"Package directory does not exist: {package_dir}")
    rows = []
    for path in sorted(package_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        try:
            if path.is_symlink():
                raise ValueError("Symlink artifact / manual review")
            if path.name.endswith(".tar.gz"):
                rows.append(read_sdist(path))
                continue
            if path.suffix.lower() != ".whl":
                raise ValueError("Non-wheel artifact / manual review")
            rows.append(read_wheel(path))
        except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError, KeyError, UnicodeError) as error:
            rows.append({**application_info(""), "filename": path.name, "name": "", "version": "", "license": "Unknown", "category": "Unknown / review", "evidence": "Unreadable artifact", "license_files": [], "compatible": False, "bytes": path.stat().st_size, "status": "Check", "error": str(error), "modules": []})
    return rows


def audit_summary(rows: list[dict]) -> dict:
    counts = Counter(row["license"] for row in rows)
    return {
        "artifacts": len(rows), "projects": len({row["name"] for row in rows if row["name"]}),
        "review": sum(row["category"] != "Permissive" or row["status"] != "Indexed" for row in rows),
        "bytes": sum(row["bytes"] for row in rows),
        "licenses": [{"license": name, "count": count, "percent": round(100 * count / len(rows), 2)} for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))],
    }


def safe_requirement(text: str) -> str:
    requirement = Requirement(text)
    if requirement.url:
        raise ValueError(f"URL or path requirement is not allowed: {text}")
    return str(requirement)


def project_files(project: Path) -> list[Path]:
    files = []
    for current, directories, filenames in os.walk(project, followlinks=False):
        directories[:] = [name for name in directories if name not in SKIP_DIRS and not name.startswith(".") and not (Path(current) / name).is_symlink() and not (Path(current) / name / "pyvenv.cfg").exists()]
        for filename in filenames:
            candidate = Path(current) / filename
            if filename.endswith(".py") and not candidate.is_symlink():
                files.append(candidate)
                if len(files) > 10_000:
                    raise ValueError("Project exceeds the 10,000 Python file scan limit")
    return files


def discover_project(project: Path, rows: list[dict]) -> dict:
    project = project.expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Select a project directory")
    requirements, constraints, warnings = [], [], []
    source = "Source imports (candidate dependencies)"
    manifest = project / "pyproject.toml"
    if manifest.is_file():
        data = tomllib.loads(manifest.read_text(encoding="utf-8-sig"))
        if "dependencies" in data.get("project", {}):
            requirements = [safe_requirement(item) for item in data["project"]["dependencies"]]
            source = "pyproject.toml / project.dependencies"
        if data.get("project", {}).get("dynamic") or data.get("tool", {}).get("poetry"):
            warnings.append("Dynamic / Poetry declarations need manual review; project code is never executed.")
    if source.startswith("Source"):
        manifest = next((project / name for name in ("requirements.in", "requirements.txt") if (project / name).is_file()), None)
        if manifest:
            source = manifest.name
            visited = set()

            def read_requirements(path: Path, constraint: bool = False) -> None:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(project):
                    raise ValueError("Requirements includes must stay inside the project")
                key = (resolved, constraint)
                if key in visited:
                    return
                visited.add(key)
                if len(visited) > 100:
                    raise ValueError("Too many requirements include files")
                for raw in resolved.read_text(encoding="utf-8-sig").splitlines():
                    text = raw.split(" #", 1)[0].strip()
                    if not text or text.startswith("#"):
                        continue
                    if text.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
                        flag, target = text.split(maxsplit=1)
                        read_requirements(resolved.parent / target, constraint or flag in {"-c", "--constraint"})
                    elif text.startswith("-"):
                        raise ValueError(f"Unsupported requirements option: {text}")
                    else:
                        (constraints if constraint else requirements).append(safe_requirement(text))

            read_requirements(manifest)
    python_files = project_files(project)
    local = {path.stem for path in python_files}
    local.update(path.parent.name for path in python_files if path.name == "__init__.py")
    for base in (project, project / "src"):
        if base.is_dir():
            local.update(path.name for path in base.iterdir() if path.is_dir() and not path.name.startswith("."))
    module_map = {}
    for row in rows:
        if row["status"] == "Indexed":
            for module in row["modules"]:
                module_map.setdefault(module, set()).add(row["name"])
    imports = set()
    for path in python_files:
        if path.stat().st_size > 2_000_000:
            warnings.append(f"Skipped oversized source: {path.relative_to(project)}")
            continue
        try:
            with path.open("rb") as stream:
                tree = ast.parse(stream.read(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
        except (SyntaxError, UnicodeError, OSError) as error:
            warnings.append(f"Source scan failed: {path.relative_to(project)}: {error}")
    unresolved, candidates = [], []
    for module in sorted(imports - local - sys.stdlib_module_names - {"__future__"}):
        matches = sorted(module_map.get(module, []))
        candidates.append({"module": module, "distributions": ", ".join(matches) or "CHECK", "status": "Mapped" if len(matches) == 1 else "Check"})
        if len(matches) != 1:
            unresolved.append(module)
        elif source.startswith("Source"):
            requirements.append(matches[0])
    if source.startswith("Source"):
        warnings.append("AST imports are candidates, not a proven minimum; dynamic imports, optional and test imports require review.")
    return {"project": str(project), "source": source, "requirements": sorted(set(requirements)), "constraints": sorted(set(constraints)), "imports": candidates, "unresolved": unresolved, "warnings": warnings}


def run_command(arguments: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PIP_REQUIREMENT", "PIP_CONSTRAINT", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        environment.pop(key, None)
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["PIP_NO_INPUT"] = "1"
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=environment, check=False)


def populate_wheelhouse(destination: Path, package_dir: Path, extra: Path | None = None) -> None:
    for row in inventory(package_dir):
        if row["status"] != "Indexed" or not row["compatible"]:
            continue
        source = package_dir / row["filename"]
        if extra and source.name == extra.name:
            continue
        target = destination / source.name
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
    if extra:
        shutil.copyfile(extra, destination / extra.name)


def resolve_dependencies(requirements: list[str], package_dir: Path = PACKAGE_DIR, constraints: list[str] | None = None) -> dict:
    requirements = [safe_requirement(item) for item in requirements]
    constraints = [safe_requirement(item) for item in constraints or []]
    if not requirements:
        return {"ok": True, "packages": [], "log": "No declared runtime dependencies.", "requirements": []}
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise ValueError("Dependency checks require Windows x64 CPython 3.11")
    with tempfile.TemporaryDirectory(prefix="offline-resolve-") as directory:
        work = Path(directory)
        wheels = work / "wheels"
        wheels.mkdir()
        populate_wheelhouse(wheels, package_dir)
        requirement_file = work / "requirements.txt"
        requirement_file.write_text("\n".join(requirements), encoding="utf-8")
        constraint_file = work / "constraints.txt"
        constraint_file.write_text("\n".join(constraints), encoding="utf-8")
        report = work / "report.json"
        command = [sys.executable, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--dry-run", "--ignore-installed", "--no-index", "--no-cache-dir", "--only-binary=:all:", "--find-links", str(wheels), "--report", str(report), "-r", str(requirement_file), "-c", str(constraint_file)]
        completed = run_command(command)
        log = completed.stdout + completed.stderr
        if completed.returncode:
            return {"ok": False, "packages": [], "log": log, "requirements": requirements}
        result = json.loads(report.read_text(encoding="utf-8"))
        packages = [{"name": canonicalize_name(item["metadata"]["name"]), "version": item["metadata"]["version"], "kind": "Direct" if item.get("requested") else "Transitive", "status": "Available"} for item in result["install"]]
        return {"ok": True, "packages": packages, "log": log, "requirements": requirements}


def check_roots(requirements: list[str], rows: list[dict]) -> list[dict]:
    checked = []
    for text in requirements:
        requirement = Requirement(safe_requirement(text))
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            status = "Not applicable"
        else:
            matches = [row for row in rows if row["name"] == canonicalize_name(requirement.name)]
            available = [row for row in matches if row["status"] == "Indexed" and row["compatible"] and requirement.specifier.contains(row["version"], prereleases=None) and SpecifierSet(row.get("requires_python", "")).contains(sys.version.split()[0])]
            status = "Available" if available else "CHECK: source only / invalid wheel" if matches and not any(row["status"] == "Indexed" for row in matches) else "CHECK: version / Python / platform" if matches else "CHECK: missing"
        checked.append({"requirement": text, "status": status})
    return checked


def analyze_project(project: Path, package_dir: Path = PACKAGE_DIR) -> dict:
    rows = inventory(package_dir)
    discovered = discover_project(project, rows)
    result = resolve_dependencies(discovered["requirements"], package_dir, discovered["constraints"])
    result["roots"] = check_roots(discovered["requirements"], rows)
    result["discovery"] = discovered
    result["complete"] = result["ok"] and not discovered["unresolved"] and not discovered["warnings"]
    return result


def admit_wheel(source: Path, package_dir: Path = PACKAGE_DIR, history_dir: Path | None = None) -> dict:
    source = source.expanduser().resolve(strict=True)
    if source.suffix.lower() != ".whl" or not source.is_file():
        raise ValueError("Only local .whl files can be admitted")
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise ValueError("Admission tests require Windows x64 CPython 3.11")
    with ADMISSION_LOCK, tempfile.TemporaryDirectory(prefix="offline-admission-") as directory:
        work = Path(directory)
        candidate = work / source.name
        shutil.copyfile(source, candidate)
        metadata = read_wheel(candidate, verify=True)
        if not metadata["compatible"]:
            raise ValueError("Wheel is not compatible with Windows x64 CPython 3.11")
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        checksum = digest.hexdigest()
        target = package_dir / source.name
        if target.exists():
            raise ValueError("Destination already exists; existing artifacts are never overwritten")
        wheels = work / "wheels"
        wheels.mkdir()
        populate_wheelhouse(wheels, package_dir, candidate)
        environment_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_dir)
        python = environment_dir / "Scripts" / "python.exe"
        install = run_command([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--no-index", "--no-cache-dir", "--only-binary=:all:", "--find-links", str(wheels), str(wheels / candidate.name)], timeout=600)
        log = install.stdout + install.stderr
        success = install.returncode == 0
        if success:
            checked = run_command([str(python), "-I", "-m", "pip", "--isolated", "check"])
            log += "\n" + checked.stdout + checked.stderr
            success = checked.returncode == 0
        receipt = {"ok": success, "filename": source.name, "sha256": checksum, "license": metadata["license"], "category": metadata["category"], "log": log, **{key: metadata[key] for key in ("domains", "summary", "use_cases", "application_evidence", "topic_classifiers")}}
        if success:
            package_dir.mkdir(parents=True, exist_ok=True)
            staged = None
            try:
                with tempfile.NamedTemporaryFile(dir=package_dir, suffix=".partial", delete=False) as output, candidate.open("rb") as input_stream:
                    staged = Path(output.name)
                    shutil.copyfileobj(input_stream, output)
                os.rename(staged, target)
            finally:
                if staged and staged.exists():
                    staged.unlink()
        if history_dir:
            from datetime import datetime, timezone

            history_dir.mkdir(parents=True, exist_ok=True)
            receipt["tested_at"] = datetime.now(timezone.utc).isoformat()
            (history_dir / f"{checksum}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return receipt
