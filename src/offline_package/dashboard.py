"""Loopback-only Dash workbench for the Python 3.11 offline repository."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from flask import abort, request

from .catalog import (
    PACKAGE_DIR, ROOT, admit_wheel, analyze_project, artifact_evidence, audit_summary, check_roots,
    domain_summary, inventory, read_wheel, resolve_dependencies, safe_requirement,
)

COLORS = ["#147d70", "#e36b54", "#477ca5", "#b59336", "#73996d", "#a6727c", "#667b86", "#b5c5c9"]


def application_panel(row: dict):
    return html.Div([
        html.H3(row["name"] + " " + row["version"]),
        html.Dl([
            html.Dt("Application domains"), html.Dd(" / ".join(row["domains"])),
            html.Dt("Package summary"), html.Dd(row["summary"] or "Not declared in package metadata"),
            html.Dt("Typical use cases"), html.Dd(html.Ul([html.Li(value) for value in row["use_cases"]]) if row["use_cases"] else "Unclassified / manual review"),
            html.Dt("Classification evidence"), html.Dd(html.Ul([html.Li(value) for value in row["application_evidence"]])),
        ]),
        html.Small("Indicative use cases, not a suitability, compatibility or license approval.", className="subtle"),
    ], className="application-detail")


def domain_chart(rows: list[dict]):
    visible = list(reversed(rows))
    figure = go.Figure(go.Bar(x=[row["projects"] for row in visible], y=[row["domain"] for row in visible], orientation="h", marker_color=[COLORS[index % len(COLORS)] for index in range(len(visible))], hovertemplate="%{y}: %{x} projects<extra></extra>"))
    figure.update_layout(height=max(260, 25 * len(visible) + 60), margin={"l": 12, "r": 20, "t": 12, "b": 35}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family": "Segoe UI", "color": "#193c39"}, xaxis={"title": "Unique projects", "rangemode": "tozero", "dtick": 1 if len(rows) < 4 else None}, yaxis={"automargin": True})
    return figure


def table(identifier: str, columns: list[tuple[str, str]], page_size: int = 12, selectable: bool = False):
    options = {"row_selectable": "single", "selected_rows": []} if selectable else {}
    return dash_table.DataTable(
        id=identifier, columns=[{"name": label, "id": key} for key, label in columns],
        data=[], page_size=page_size, sort_action="native", filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Segoe UI, sans-serif", "fontSize": 13, "textAlign": "left", "padding": "12px", "minWidth": "100px", "maxWidth": "340px", "whiteSpace": "normal", "overflowWrap": "anywhere", "border": "none", "borderBottom": "1px solid #e5eaeb"},
        style_header={"fontWeight": 600, "backgroundColor": "#f1f5f4", "color": "#425657"},
        style_data_conditional=[
            {"if": {"filter_query": '{category} != "Permissive"', "column_id": "category"}, "color": "#a84430"},
            {"if": {"filter_query": '{status} contains "CHECK"', "column_id": "status"}, "color": "#a84430", "fontWeight": 600},
        ], **options,
    )


def license_chart(summary: dict):
    licenses = summary["licenses"]
    visible = licenses[:8]
    labels = [item["license"] for item in visible]
    values = [item["count"] for item in visible]
    if len(licenses) > 8:
        labels.append("Other licenses")
        values.append(sum(item["count"] for item in licenses[8:]))
    figure = go.Figure(go.Pie(labels=labels, values=values, hole=0.72, sort=False, textinfo="none", marker={"colors": COLORS}, hovertemplate="%{label}<br>%{value} files / %{percent}<extra></extra>"))
    figure.update_layout(height=300, margin={"l": 12, "r": 12, "t": 10, "b": 10}, showlegend=False, paper_bgcolor="rgba(0,0,0,0)", font={"family": "Segoe UI", "color": "#183b39"}, annotations=[{"text": f"<b>{summary['artifacts']}</b><br>artifacts", "x": 0.5, "y": 0.5, "showarrow": False, "font": {"size": 22}}])
    return figure


def create_app(package_dir: Path = PACKAGE_DIR, state_dir: Path | None = None) -> Dash:
    package_dir = package_dir.resolve()
    state_dir = state_dir or ROOT / ".offline-ui"
    app = Dash(__name__, title="Offline package audit", assets_folder=str(Path(__file__).resolve().parent / "assets"), update_title=None, meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
    app.server.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="offline-ui")
    jobs, uploads = {}, {}
    job_lock = threading.Lock()

    @app.server.before_request
    def loopback_requests_only():
        if request.host.split(":", 1)[0] not in {"127.0.0.1", "localhost"}:
            abort(403)
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403)

    def submit(function, *arguments):
        with job_lock:
            if len(jobs) >= 32:
                for key in list(jobs):
                    if jobs[key].done():
                        del jobs[key]
                if len(jobs) >= 32:
                    raise ValueError("Task queue is full")
            identifier = uuid.uuid4().hex
            jobs[identifier] = executor.submit(function, *arguments)
            return identifier

    def read_job(identifier):
        future = jobs.get(identifier)
        if future is None:
            raise ValueError("Task expired; run the check again")
        if not future.done():
            return None
        return future.result()

    app.layout = html.Div([
        dcc.Store(id="project-job"), dcc.Store(id="project-result"),
        dcc.Store(id="admission-job"), dcc.Store(id="admission-result"), dcc.Store(id="upload-token"),
        dcc.Interval(id="project-poll", interval=1200, disabled=True),
        dcc.Interval(id="admission-poll", interval=1200, disabled=True),
        dcc.Download(id="download"),
        html.Header([
            html.Div([html.Span("P311", className="brand-mark"), html.Div([html.H1("Offline package audit"), html.Div("Windows x64 / Python 3.11", className="subtle")])], className="brand"),
            html.Div([html.Span(className="connection-dot"), html.Span("LOCAL REPOSITORY"), html.Code("package311")], className="repo-label"),
        ], className="topbar"),
        dcc.Tabs(id="workspace", value="audit", children=[
            dcc.Tab(label="01  License audit", value="audit", children=[
                html.Section([
                    html.Div([html.Div([html.H2("Repository overview"), html.P("License declarations are evidence for review, not legal clearance.", className="subtle")]), html.Div([html.Button("Refresh", id="refresh", n_clicks=0), html.Button("Export audit JSON", id="export-audit"), html.Button("Export CSV", id="export-csv")], className="actions")], className="section-heading"),
                    html.Div(id="audit-status", className="status", role="status"),
                    html.Div([html.Div([html.Span(label), html.Strong("...", id=identifier)], className="metric") for label, identifier in [("Artifacts", "artifact-count"), ("Unique projects", "project-count"), ("Needs review", "review-count"), ("Repository size", "repository-size")]], className="metrics"),
                    html.Div([dcc.Graph(id="license-chart", config={"displayModeBar": False, "responsive": True}), html.Div([html.H3("License distribution"), html.P("Share of all root-level artifact files; versions counted separately.", className="subtle"), table("license-table", [("license", "Declared license"), ("count", "Files"), ("percent", "Share (%)")], 7)])], className="distribution"),
                    html.Details([html.Summary("Application domains"), html.P("Unique identified projects; multi-domain shares may exceed 100%. Unreadable artifacts are excluded.", className="subtle"), html.Div([dcc.Graph(id="domain-chart", config={"displayModeBar": False, "responsive": True}), table("domain-table", [("domain", "Application domain"), ("projects", "Projects"), ("percent", "Share (%)")], 8)], className="domain-distribution")], open=True),
                    html.Div([html.H3("Artifact register"), html.Div([dcc.Dropdown(id="domain-filter", options=[{"label": "All domains", "value": "all"}], value="all", clearable=False), dcc.Dropdown(id="risk-filter", options=[{"label": "All artifacts", "value": "all"}, {"label": "Needs review", "value": "review"}, {"label": "Permissive declarations", "value": "permissive"}], value="all", clearable=False)], className="register-filters")], className="register-heading"),
                    table("artifact-table", [("filename", "Artifact"), ("name", "Project"), ("version", "Version"), ("domains", "Application domains"), ("purpose", "Summary / typical uses"), ("license", "Declared license"), ("category", "Review group"), ("evidence", "Evidence"), ("platform", "Win / 3.11"), ("status", "Index")], selectable=True),
                    html.Div(id="artifact-application"),
                    html.Details([html.Summary("Selected artifact evidence"), html.Button("Export selected license evidence", id="export-evidence"), html.Pre(id="artifact-detail", children="No artifact selected.")], open=True),
                ], className="workspace-section"),
            ]),
            dcc.Tab(label="02  Project dependencies", value="project", children=[
                html.Section([
                    html.Div([html.H2("Project dependency check"), html.Span("SOURCE: package311", className="source-label")], className="section-heading"),
                    html.Label("Project directory on this computer", htmlFor="project-path"),
                    html.Div([dcc.Input(id="project-path", type="text", placeholder="D:\\projects\\my-project", debounce=True), html.Button("Import & check", id="scan-project", className="primary")], className="input-row"),
                    html.Div(id="project-status", className="status", role="status"),
                    html.Div([
                        html.Div([html.H3("Direct requirements"), dcc.Textarea(id="requirements-editor", placeholder="No project imported yet.", spellCheck=False), html.Div([html.Button("Check edited requirements", id="resolve-project"), html.Button("Export locked dependencies", id="export-lock", disabled=True), html.Button("Export check report", id="export-project", disabled=True)], className="actions")]),
                        html.Div([html.H3("Availability check"), table("roots-table", [("requirement", "Requirement"), ("status", "Offline availability")], 7)]),
                    ], className="project-grid"),
                    html.H3("Resolved dependency closure"), table("resolved-table", [("name", "Project"), ("version", "Locked version"), ("kind", "Dependency"), ("status", "Availability")]),
                    html.Details([html.Summary("Source import mapping"), table("imports-table", [("module", "Import"), ("distributions", "Wheel project"), ("status", "Check")], 8)]),
                    html.Details([html.Summary("Resolver output & review notes"), html.Pre(id="project-log", children="No check run.")], open=True),
                ], className="workspace-section"),
            ]),
            dcc.Tab(label="03  Package admission", value="admission", children=[
                html.Section([
                    html.Div([html.H2("Test a new offline wheel"), html.Span("DESTINATION: package311", className="source-label")], className="section-heading"),
                    html.Label("Local wheel file", htmlFor="wheel-path"),
                    dcc.Input(id="wheel-path", type="text", placeholder="D:\\downloads\\package-1.0-py3-none-any.whl", debounce=True),
                    dcc.Upload(id="wheel-upload", children=html.Button("Choose wheel file (up to 100 MB)"), multiple=False, accept=".whl"),
                    html.Div(id="upload-status", className="subtle", role="status"),
                    html.Div(id="wheel-application", role="status"),
                    dcc.Checklist(id="test-consent", options=[{"label": "I trust this wheel and its local dependencies. A virtual environment is not a security sandbox; installation checks may execute package startup code.", "value": "trusted"}], value=[]),
                    html.Div([html.Button("Validate, test & add", id="test-wheel", className="primary"), html.Button("Export test receipt", id="export-receipt", disabled=True)], className="actions"),
                    html.Div(id="admission-status", className="status", role="status"),
                    html.Pre(id="admission-log", children="No wheel tested."),
                    html.H3("Saved admission receipts"),
                    html.Div([dcc.Dropdown(id="receipt-history", options=[], placeholder="Select a previous test"), html.Button("Refresh history", id="refresh-history")], className="input-row"),
                    html.Pre(id="history-detail", children="No receipt selected."),
                ], className="workspace-section"),
            ]),
        ], className="workspaces"),
        html.Footer([html.Span("OFFLINE OPERATIONS"), html.Span(str(package_dir))]),
    ], className="app-shell")

    @app.callback(
        Output("artifact-count", "children"), Output("project-count", "children"), Output("review-count", "children"),
        Output("repository-size", "children"), Output("license-chart", "figure"), Output("license-table", "data"),
        Output("artifact-table", "data"), Output("audit-status", "children"),
        Output("domain-chart", "figure"), Output("domain-table", "data"), Output("domain-filter", "options"),
        Input("refresh", "n_clicks"), Input("risk-filter", "value"), Input("admission-result", "data"), Input("domain-filter", "value"),
    )
    def refresh_audit(_clicks, risk, _admission, domain="all"):
        try:
            rows = inventory(package_dir)
            summary = audit_summary(rows)
            selected = [dict(row, platform="Compatible" if row["compatible"] else "CHECK") for row in rows if risk == "all" or (risk == "review" and (row["category"] != "Permissive" or row["status"] != "Indexed")) or (risk == "permissive" and row["category"] == "Permissive" and row["status"] == "Indexed")]
            display_rows = []
            for row in selected:
                if domain != "all" and domain not in row["domains"]:
                    continue
                display = {key: row.get(key, "") for key in ("filename", "name", "version", "license", "category", "evidence", "platform", "status")}
                display.update(domains=" / ".join(row["domains"]), purpose=row["summary"] or " ".join(row["use_cases"]) or "Unclassified / manual review")
                display_rows.append(display)
            domains = domain_summary(rows)
            options = [{"label": "All domains", "value": "all"}] + [{"label": value, "value": value} for value in sorted({value for row in rows for value in row["domains"]})]
            return summary["artifacts"], summary["projects"], summary["review"], f"{summary['bytes'] / 1024**3:.2f} GB", license_chart(summary), summary["licenses"], display_rows, f"Updated {datetime.now().strftime('%H:%M:%S')} / {len(display_rows)} artifacts shown", domain_chart(domains), domains, options
        except Exception as error:
            return "-", "-", "-", "-", go.Figure(), [], [], f"CHECK: {error}", go.Figure(), [], [{"label": "All domains", "value": "all"}]

    @app.callback(Output("artifact-application", "children"), Input("artifact-table", "derived_virtual_selected_rows"), Input("artifact-table", "derived_virtual_data"))
    def selected_application(selected, visible):
        if not selected or not visible or selected[0] >= len(visible):
            return None
        try:
            row = next(row for row in inventory(package_dir) if row["filename"] == visible[selected[0]]["filename"])
            return application_panel(row)
        except Exception as error:
            return f"CHECK: {error}"

    @app.callback(Output("wheel-application", "children"), Input("wheel-path", "value"), Input("upload-token", "data"))
    def preview_application(path, token):
        source = Path(path).expanduser() if path else uploads.get(token)
        if source is None:
            return None
        try:
            return application_panel(read_wheel(source))
        except Exception as error:
            return f"CHECK: Cannot preview package metadata: {error}"

    @app.callback(Output("artifact-detail", "children"), Input("artifact-table", "derived_virtual_selected_rows"), Input("artifact-table", "derived_virtual_data"))
    def artifact_detail(selected, visible):
        if not selected or not visible or selected[0] >= len(visible):
            return "No artifact selected."
        filename = visible[selected[0]]["filename"]
        try:
            return json.dumps(artifact_evidence(filename, package_dir), indent=2, ensure_ascii=False)
        except Exception as error:
            return f"CHECK: {error}"

    def edited_check(text, previous):
        requirements = [safe_requirement(line.strip()) for line in (text or "").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        discovery = (previous or {}).get("discovery", {})
        result = resolve_dependencies(requirements, package_dir, discovery.get("constraints", []))
        result["roots"] = check_roots(requirements, inventory(package_dir))
        result["discovery"] = discovery
        result["complete"] = result["ok"] and not discovery.get("unresolved") and not discovery.get("warnings")
        return result

    @app.callback(
        Output("project-job", "data"), Output("project-result", "data"), Output("project-status", "children"),
        Output("roots-table", "data"), Output("resolved-table", "data"), Output("imports-table", "data"),
        Output("requirements-editor", "value"), Output("project-log", "children"),
        Output("scan-project", "disabled"), Output("resolve-project", "disabled"), Output("project-poll", "disabled"),
        Input("scan-project", "n_clicks"), Input("resolve-project", "n_clicks"), Input("project-poll", "n_intervals"),
        State("project-path", "value"), State("requirements-editor", "value"), State("project-job", "data"), State("project-result", "data"),
        prevent_initial_call=True,
    )
    def project_task(_scan, _resolve, _poll, path, text, job, previous):
        try:
            if ctx.triggered_id in {"scan-project", "resolve-project"}:
                if job and jobs.get(job) and not jobs[job].done():
                    return (no_update,) * 11
                if ctx.triggered_id == "scan-project":
                    if not path:
                        raise ValueError("Enter a local project directory")
                    job = submit(analyze_project, Path(path), package_dir)
                else:
                    job = submit(edited_check, text, previous)
                return job, None, "Running offline dependency check...", no_update, no_update, no_update, no_update, no_update, True, True, False
            result = read_job(job)
            if result is None:
                return (no_update,) * 11
            discovery = result.get("discovery", {})
            status = "PASS: dependency closure available" if result.get("complete") else "CHECK: review import candidates / notes" if result["ok"] else "CHECK: missing or conflicting offline dependencies"
            notes = [f"Source: {discovery.get('source', 'Edited requirements')}", *discovery.get("warnings", [])]
            if discovery.get("unresolved"):
                notes.append("Unmapped / ambiguous imports: " + ", ".join(discovery["unresolved"]))
            log = "\n".join(notes) + "\n\n" + result["log"]
            return None, result, status, result["roots"], result["packages"], discovery.get("imports", []), "\n".join(result["requirements"]), log, False, False, True
        except Exception as error:
            return None, None, f"CHECK: {error}", [], [], [], no_update, str(error), False, False, True

    @app.callback(Output("upload-token", "data"), Output("upload-status", "children"), Input("wheel-upload", "contents"), State("wheel-upload", "filename"), prevent_initial_call=True)
    def upload_wheel(contents, filename):
        try:
            if not contents or not filename or Path(filename).name != filename or not filename.lower().endswith(".whl"):
                raise ValueError("Select a wheel with a plain filename")
            if len(contents) > 140 * 1024 * 1024:
                raise ValueError("Upload exceeds 100 MB; use a local path instead")
            data = base64.b64decode(contents.split(",", 1)[1], validate=True)
            if len(data) > 100 * 1024 * 1024:
                raise ValueError("Upload exceeds 100 MB; use a local path instead")
            token = uuid.uuid4().hex
            destination = state_dir / "uploads" / token
            destination.mkdir(parents=True)
            wheel = destination / filename
            wheel.write_bytes(data)
            uploads[token] = wheel
            return token, f"Staged: {filename}. Clear the local path to use this upload."
        except Exception as error:
            return None, f"CHECK: {error}"

    def admission(source, token):
        try:
            return admit_wheel(source, package_dir, state_dir / "receipts")
        finally:
            if token in uploads:
                shutil.rmtree(uploads.pop(token).parent, ignore_errors=True)

    @app.callback(
        Output("admission-job", "data"), Output("admission-result", "data"), Output("admission-status", "children"),
        Output("admission-log", "children"), Output("test-wheel", "disabled"), Output("admission-poll", "disabled"),
        Input("test-wheel", "n_clicks"), Input("admission-poll", "n_intervals"),
        State("wheel-path", "value"), State("upload-token", "data"), State("test-consent", "value"), State("admission-job", "data"),
        prevent_initial_call=True,
    )
    def admission_task(_test, _poll, path, token, consent, job):
        try:
            if ctx.triggered_id == "test-wheel":
                if job and jobs.get(job) and not jobs[job].done():
                    return (no_update,) * 6
                if "trusted" not in (consent or []):
                    raise ValueError("Confirm trust before running installation tests")
                source = Path(path) if path else uploads.get(token)
                if source is None:
                    raise ValueError("Enter a wheel path or select a wheel file")
                used_token = None if path else token
                job = submit(admission, source, used_token)
                return job, None, "Running RECORD checks, isolated offline installation, and pip check...", "Test running...", True, False
            result = read_job(job)
            if result is None:
                return (no_update,) * 6
            status = "PASS: tested and added to package311" if result["ok"] else "CHECK: test failed; repository unchanged"
            return None, result, status, json.dumps({key: value for key, value in result.items() if key != "log"}, indent=2) + "\n\n" + result["log"], False, True
        except Exception as error:
            return None, None, f"CHECK: {error}; repository unchanged", str(error), False, True

    @app.callback(Output("receipt-history", "options"), Input("refresh-history", "n_clicks"), Input("admission-result", "data"))
    def receipt_options(_clicks, _result):
        receipts = sorted((state_dir / "receipts").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        options = []
        for path in receipts[:30]:
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
                options.append({"label": f"{'PASS' if receipt['ok'] else 'CHECK'} / {receipt['filename']} / {receipt.get('tested_at', '')}", "value": path.stem})
            except (OSError, ValueError, KeyError):
                continue
        return options

    @app.callback(Output("export-lock", "disabled"), Output("export-project", "disabled"), Output("export-receipt", "disabled"), Input("project-result", "data"), Input("admission-result", "data"))
    def export_availability(project_result, admission_result):
        return not bool(project_result and project_result.get("ok")), not bool(project_result), not bool(admission_result)

    @app.callback(Output("history-detail", "children"), Input("receipt-history", "value"))
    def receipt_detail(identifier):
        if not identifier or len(identifier) != 64 or any(character not in "0123456789abcdef" for character in identifier):
            return "No receipt selected."
        try:
            return (state_dir / "receipts" / f"{identifier}.json").read_text(encoding="utf-8")
        except OSError as error:
            return f"CHECK: {error}"

    @app.callback(Output("download", "data"), Input("export-audit", "n_clicks"), Input("export-csv", "n_clicks"), Input("export-lock", "n_clicks"), Input("export-project", "n_clicks"), Input("export-receipt", "n_clicks"), Input("export-evidence", "n_clicks"), State("project-result", "data"), State("admission-result", "data"), State("artifact-table", "derived_virtual_selected_rows"), State("artifact-table", "derived_virtual_data"), prevent_initial_call=True)
    def export(_audit, _csv, _lock, _project, _receipt, _evidence, project_result, admission_result, selected, visible):
        triggered = ctx.triggered_id
        if triggered == "export-evidence":
            if not selected or not visible or selected[0] >= len(visible):
                return no_update
            result = artifact_evidence(visible[selected[0]]["filename"], package_dir)
            return dcc.send_string(json.dumps(result, indent=2, ensure_ascii=False), "artifact-license-evidence.json")
        if triggered in {"export-audit", "export-csv"}:
            rows = inventory(package_dir)
            if triggered == "export-csv":
                stream = io.StringIO()
                writer = csv.DictWriter(stream, fieldnames=["filename", "name", "version", "domains", "summary", "use_cases", "application_evidence", "license", "category", "evidence", "status", "error"])
                writer.writeheader()
                for row in rows:
                    record = {key: row.get(key, "") for key in writer.fieldnames}
                    record = {key: "; ".join(value) if isinstance(value, list) else value for key, value in record.items()}
                    record = {key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value for key, value in record.items()}
                    writer.writerow(record)
                return dcc.send_string(stream.getvalue(), "offline-audit.csv")
            result = {"generated_at": datetime.now(timezone.utc).isoformat(), "source": str(package_dir), "target": "Windows x64 CPython 3.11", "scope": "Root-level artifact files; each version counted separately", "notice": "Metadata declarations do not prove copyright compliance or publisher identity. Review license texts, notices, dependency licenses, and usage obligations.", "domain_scope": "Unique identified projects; multiple domains per project; indicative classification, not suitability approval", "domains": domain_summary(rows), "summary": audit_summary(rows), "artifacts": rows}
            return dcc.send_string(json.dumps(result, indent=2, ensure_ascii=False), "offline-audit.json")
        if triggered == "export-lock":
            if not project_result or not project_result.get("ok"):
                return no_update
            pins = sorted(f"{row['name']}=={row['version']}" for row in project_result["packages"])
            return dcc.send_string("# Windows x64 CPython 3.11; package311 only\n# Installation resolution, not proof of a source-level minimum\n" + "\n".join(pins) + "\n", "requirements-offline.lock.txt")
        result = project_result if triggered == "export-project" else admission_result
        if not result:
            return no_update
        return dcc.send_string(json.dumps(result, indent=2, ensure_ascii=False), "project-check.json" if triggered == "export-project" else "admission-receipt.json")

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()