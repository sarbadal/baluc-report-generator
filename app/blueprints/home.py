"""Home and report generator blueprint for report operations workflow."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from datetime import date
from io import BytesIO
from io import StringIO
import os
from typing import TypedDict
from zoneinfo import ZoneInfo

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import send_file
from flask import url_for

home_blueprint = Blueprint("home", __name__)
RECENT_REPORTS_LIMIT = 10
IST_TZ = ZoneInfo("Asia/Kolkata")
EV_ENQUIRY_COLUMNS = [
    "ev_enquery_count_date_m2",
    "ev_enquery_count_date_m1",
    "ev_enquery_count_date_t",
    "ev_enquery_count_date_p1",
    "ev_enquery_count_date_p2",
]
EV_PERFORMANCE_COLUMNS = [
    "ev_perf_enquery_count_date_m2_m1_avg",
    "ev_perf_enquery_count_date_t_avg",
    "ev_perf_enquery_count_date_p2_p1_avg",
]
EV_GROWTH_COLUMNS = [
    "ev_growth_enquery_count_date_t_vs_m2_avg",
    "ev_growth_enquery_count_date_p2_vs_t_avg",
]
PV_ENQUIRY_COLUMNS = [
    "pv_enquery_count_date_m2",
    "pv_enquery_count_date_m1",
    "pv_enquery_count_date_t",
    "pv_enquery_count_date_p1",
    "pv_enquery_count_date_p2",
]
PV_PERFORMANCE_COLUMNS = [
    "pv_perf_enquery_count_date_m2_m1_avg",
    "pv_perf_enquery_count_date_t_avg",
    "pv_perf_enquery_count_date_p2_p1_avg",
]
PV_GROWTH_COLUMNS = [
    "pv_growth_enquery_count_date_t_vs_m2_avg",
    "pv_growth_enquery_count_date_p2_vs_t_avg",
]
PERCENTAGE_FORMAT_COLUMNS = set(EV_GROWTH_COLUMNS + PV_GROWTH_COLUMNS)
GROWTH_EMPTY_CONDITIONS: dict[str, tuple[str, str]] = {
    "ev_growth_enquery_count_date_t_vs_m2_avg": (
        "ev_perf_enquery_count_date_m2_m1_avg",
        "ev_perf_enquery_count_date_t_avg",
    ),
    "ev_growth_enquery_count_date_p2_vs_t_avg": (
        "ev_perf_enquery_count_date_t_avg",
        "ev_perf_enquery_count_date_p2_p1_avg",
    ),
    "pv_growth_enquery_count_date_t_vs_m2_avg": (
        "pv_perf_enquery_count_date_m2_m1_avg",
        "pv_perf_enquery_count_date_t_avg",
    ),
    "pv_growth_enquery_count_date_p2_vs_t_avg": (
        "pv_perf_enquery_count_date_t_avg",
        "pv_perf_enquery_count_date_p2_p1_avg",
    ),
}


class TopHeader(TypedDict, total=False):
    label: str
    rowspan: int
    colspan: int
    column_index: int
    end_column_index: int
    separator_before: bool


class MiddleHeader(TypedDict):
    label: str
    colspan: int
    end_column_index: int
    separator_before: bool
    subgroup_separator_before: bool


class DetailHeader(TypedDict):
    full: str
    short: str
    narrow: bool
    column_index: int


@dataclass(slots=True)
class GroupedHeadersBuildResult:
    top_headers: list[TopHeader]
    middle_headers: list[MiddleHeader]
    detail_headers: list[DetailHeader]
    metric_column_indexes: list[int]
    narrow_metric_column_indexes: list[int]
    pv_separator_index: int | None
    subgroup_separator_indexes: list[int]


@home_blueprint.route("/", methods=["GET"])
def home():
    """Render application landing page with a snapshot of recent report activity."""
    report_job_manager = _get_report_job_manager()
    recent_reports = report_job_manager.list_recent_jobs(limit=RECENT_REPORTS_LIMIT)
    completed_count = sum(1 for report in recent_reports if report.get("status") == "Completed")
    failed_count = sum(1 for report in recent_reports if report.get("status") == "Failed")
    generating_count = sum(
        1
        for report in recent_reports
        if report.get("status") in {"Generating", "Processing"}
    )

    return render_template(
        "home.html",
        recent_reports=recent_reports,
        completed_count=completed_count,
        failed_count=failed_count,
        generating_count=generating_count,
    )


@home_blueprint.route("/report-generator", methods=["GET", "POST"])
def report_generator_page():
    """Render report generator workflow with asynchronous status tracking."""
    today_ist = datetime.now(IST_TZ).date().isoformat()
    form_data = {
        "start_date": request.form.get("start_date", today_ist),
        "end_date": request.form.get("end_date", today_ist),
    }
    report_job_manager = _get_report_job_manager()

    context = {
        "form_data": form_data,
        "recent_reports": report_job_manager.list_recent_jobs(limit=RECENT_REPORTS_LIMIT),
        "recent_reports_limit": RECENT_REPORTS_LIMIT,
        "status_poll_seconds": int(current_app.config.get("REPORT_STATUS_POLL_SECONDS", 5)),
        "submitted_report_id": None,
        "error": None,
    }

    if request.method == "POST":
        try:
            start_date = _parse_iso_date(form_data["start_date"], field_name="start_date")
            end_date = _parse_iso_date(form_data["end_date"], field_name="end_date")
            if end_date < start_date:
                raise ValueError("end_date must be greater than or equal to start_date.")

            bucket_prefix = (
                current_app.config.get("REPORT_GCS_BUCKET_PREFIX")
                or current_app.config.get("REPORT_STORAGE_BUCKET_NAME")
                or os.getenv("TEST_GCS_BUCKET_NAME", "")
            ).strip()
            if not bucket_prefix:
                raise ValueError("REPORT_GCS_BUCKET_PREFIX is not configured.")

            report_id = report_job_manager.submit_job(
                bucket_prefix=bucket_prefix,
                start_date=form_data["start_date"],
                end_date=form_data["end_date"],
            )
            context["submitted_report_id"] = report_id
            context["recent_reports"] = report_job_manager.list_recent_jobs(limit=RECENT_REPORTS_LIMIT)
        except Exception as exc:
            context["error"] = str(exc)

    return render_template("report_generator.html", **context)


@home_blueprint.route("/reports/<report_id>/download", methods=["GET"])
def download_report(report_id: str):
    """Download generated CSV for a completed report job."""
    report_job_manager = _get_report_job_manager()
    download_file = report_job_manager.get_download_file(report_id)
    if download_file is None:
        abort(404)

    filename, csv_content = download_file

    return send_file(
        BytesIO(csv_content),
        as_attachment=True,
        download_name=filename,
        mimetype="text/csv",
    )


@home_blueprint.route("/reports/<report_id>/download-formatted", methods=["GET"])
def download_formatted_report(report_id: str):
    """Download CSV as shown in preview table, including display header formatting."""
    report_job_manager = _get_report_job_manager()
    download_file = report_job_manager.get_download_file(report_id)
    if download_file is None:
        abort(404)

    filename, csv_content = download_file
    headers, rows = _parse_csv_content(csv_content)
    grouped_headers_result = _build_grouped_headers(headers)
    formatted_csv = _build_preview_csv_content(
        headers,
        rows,
        grouped_headers_result.top_headers,
        grouped_headers_result.middle_headers,
        grouped_headers_result.detail_headers,
    )
    formatted_filename = _build_formatted_filename(filename)

    return send_file(
        BytesIO(formatted_csv),
        as_attachment=True,
        download_name=formatted_filename,
        mimetype="text/csv",
    )


@home_blueprint.route("/reports/<report_id>/view", methods=["GET"])
def view_report_table(report_id: str):
    """Render a generated CSV as an HTML table for quick inspection."""
    report_job_manager = _get_report_job_manager()
    download_file = report_job_manager.get_download_file(report_id)
    if download_file is None:
        abort(404)

    filename, csv_content = download_file
    headers, rows = _parse_csv_content(csv_content)
    date_separator_index = headers.index("date") if "date" in headers else None
    pv_growth_end_separator_index = (
        headers.index("pv_growth_enquery_count_date_p2_vs_t_avg")
        if "pv_growth_enquery_count_date_p2_vs_t_avg" in headers
        else None
    )
    grouped_headers_result = _build_grouped_headers(headers)
    return render_template(
        "report_preview.html",
        report_id=report_id,
        filename=filename,
        headers=headers,
        top_headers=grouped_headers_result.top_headers,
        middle_headers=grouped_headers_result.middle_headers,
        detail_headers=grouped_headers_result.detail_headers,
        metric_column_indexes=grouped_headers_result.metric_column_indexes,
        narrow_metric_column_indexes=grouped_headers_result.narrow_metric_column_indexes,
        date_separator_index=date_separator_index,
        pv_separator_index=grouped_headers_result.pv_separator_index,
        subgroup_separator_indexes=grouped_headers_result.subgroup_separator_indexes,
        pv_growth_end_separator_index=pv_growth_end_separator_index,
        rows=rows,
        row_count=len(rows),
    )


@home_blueprint.route("/reports/refresh", methods=["GET"])
def refresh_report_history():
    """Simple redirect endpoint to refresh current report status list."""
    return redirect(url_for("home.report_generator_page"))


@home_blueprint.route("/reports/status", methods=["GET"])
def report_status():
    """Return recent report statuses in JSON format for polling clients."""
    report_job_manager = _get_report_job_manager()

    limit_raw = request.args.get("limit", str(RECENT_REPORTS_LIMIT)).strip()
    try:
        limit = max(1, min(50, int(limit_raw)))
    except ValueError:
        limit = RECENT_REPORTS_LIMIT

    reports = report_job_manager.list_recent_jobs(limit=limit)
    payload: list[dict[str, str | None]] = []
    for report in reports:
        row = dict(report)
        report_id = row.get("report_id")
        status = row.get("status")
        if isinstance(report_id, str) and status == "Completed":
            row["download_url"] = url_for("home.download_report", report_id=report_id)
            row["view_url"] = url_for("home.view_report_table", report_id=report_id)
        else:
            row["download_url"] = None
            row["view_url"] = None
        payload.append(row)

    return jsonify({"reports": payload})


def _get_report_job_manager():
    """Return shared report job manager from Flask app extensions."""
    manager = current_app.extensions.get("report_job_manager")
    if manager is None:
        raise RuntimeError("report_job_manager is not initialized.")
    return manager


def _parse_csv_content(csv_content: bytes) -> tuple[list[str], list[list[str]]]:
    """Decode CSV bytes and split into table headers and rows for template rendering."""
    decoded_csv = csv_content.decode("utf-8-sig", errors="replace")
    parsed_rows = list(csv.reader(StringIO(decoded_csv)))
    if not parsed_rows:
        return [], []

    raw_headers = [str(column).strip() for column in parsed_rows[0]]
    normalized_headers = [_normalize_column_name(column) for column in raw_headers]
    headers = [_display_header_label(column) for column in normalized_headers]
    column_count = len(headers)
    table_rows: list[list[str]] = []
    for row in parsed_rows[1:]:
        normalized = [str(cell) for cell in row]
        if len(normalized) < column_count:
            normalized.extend([""] * (column_count - len(normalized)))

        row_values_by_header = {
            normalized_headers[index]: normalized[index]
            for index in range(column_count)
        }
        forced_empty_growth_headers = _growth_headers_to_blank(row_values_by_header)

        formatted_row = [
            "" if normalized_headers[index] in forced_empty_growth_headers
            else _format_table_cell(normalized_headers[index], normalized[index])
            for index in range(column_count)
        ]
        table_rows.append(formatted_row)
    return headers, table_rows


def _growth_headers_to_blank(row_values_by_header: dict[str, str]) -> set[str]:
    """Return growth headers that should render as empty based on dependent zero values."""
    blank_headers: set[str] = set()
    for growth_header, dependency_headers in GROWTH_EMPTY_CONDITIONS.items():
        first_dependency = row_values_by_header.get(dependency_headers[0], "")
        second_dependency = row_values_by_header.get(dependency_headers[1], "")
        if _is_zero_like(first_dependency) and _is_zero_like(second_dependency):
            blank_headers.add(growth_header)
    return blank_headers


def _is_zero_like(value: str) -> bool:
    """Return True when the value is a parseable numeric zero (optionally with % suffix)."""
    normalized = value.strip()
    if not normalized:
        return True

    numeric_text = normalized[:-1] if normalized.endswith("%") else normalized
    try:
        numeric_value = float(numeric_text)
    except ValueError:
        return False
    return abs(numeric_value) < 1e-12


def _format_table_cell(header_name: str, value: str) -> str:
    """Apply display formatting rules for preview table cells by column name."""
    if header_name not in PERCENTAGE_FORMAT_COLUMNS:
        return value

    normalized = value.strip()
    if not normalized:
        return value

    numeric_text = normalized[:-1] if normalized.endswith("%") else normalized
    try:
        numeric_value = float(numeric_text)
    except ValueError:
        return value

    return f"{numeric_value:.2f}%"


def _normalize_column_name(header: str) -> str:
    """Normalize prefixed aliases like EVC/PVC to the EV/PV naming conventions used in report previews."""
    normalized = header.strip()
    return normalized.replace("evc_", "ev_").replace("pvc_", "pv_")


def _display_header_label(header: str) -> str:
    """Map internal CSV headers to user-friendly display labels for preview table."""
    normalized = _normalize_column_name(header)
    if normalized in {"pub_name", "publication_original"}:
        return "publication original"
    return normalized


def _display_group_family_label(family_label: str, existing_top_headers: list[TopHeader]) -> str:
    """Return report-friendly top header labels for EV/PV family sections."""
    has_ev = any((header.get("label") or "").startswith("EV") for header in existing_top_headers)
    has_pv = any((header.get("label") or "").startswith("PV") for header in existing_top_headers)

    if family_label == "EV":
        if has_ev and has_pv:
            return "EV/PV"
        return "EV(All Captions)"
    if family_label == "PV":
        return "PV(All Captions)"
    return family_label


def _build_grouped_headers(headers: list[str]) -> GroupedHeadersBuildResult:
    """Build three-level header model: EV/PV -> subgroup -> detailed metric labels."""
    normalized_headers = [_normalize_column_name(header) for header in headers]
    column_groups: dict[str, tuple[str, str, bool]] = {
        **{column: ("EV", "Enquiry", True) for column in EV_ENQUIRY_COLUMNS},
        **{column: ("EV", "Performance", False) for column in EV_PERFORMANCE_COLUMNS},
        **{column: ("EV", "Growth", False) for column in EV_GROWTH_COLUMNS},
        **{column: ("PV", "Enquiry", True) for column in PV_ENQUIRY_COLUMNS},
        **{column: ("PV", "Performance", False) for column in PV_PERFORMANCE_COLUMNS},
        **{column: ("PV", "Growth", False) for column in PV_GROWTH_COLUMNS},
    }

    top_headers: list[TopHeader] = []
    middle_headers: list[MiddleHeader] = []
    detail_headers: list[DetailHeader] = []
    metric_column_indexes: list[int] = []
    narrow_metric_column_indexes: list[int] = []
    pv_separator_index: int | None = None
    subgroup_separator_indexes: list[int] = []

    index = 0
    while index < len(normalized_headers):
        header = normalized_headers[index]
        group_info = column_groups.get(header)

        if group_info is None:
            top_headers.append(
                {
                    "label": header,
                    "rowspan": 3,
                    "column_index": index,
                    "end_column_index": index,
                }
            )
            index += 1
            continue

        family_label = group_info[0]
        family_start = index
        if family_label == "PV" and pv_separator_index is None:
            pv_separator_index = family_start
        while index < len(normalized_headers):
            current_info = column_groups.get(normalized_headers[index])
            if current_info is None or current_info[0] != family_label:
                break

            subgroup_label = current_info[1]
            subgroup_start = index

            while index < len(normalized_headers):
                subgroup_info = column_groups.get(normalized_headers[index])
                if (
                    subgroup_info is None
                    or subgroup_info[0] != family_label
                    or subgroup_info[1] != subgroup_label
                ):
                    break

                column_name = normalized_headers[index]
                is_narrow = bool(subgroup_info[2])
                detail_headers.append(
                    {
                        "full": column_name,
                        "short": _compact_group_label(column_name),
                        "narrow": is_narrow,
                        "column_index": index,
                    }
                )
                metric_column_indexes.append(index)
                if is_narrow:
                    narrow_metric_column_indexes.append(index)
                index += 1

            middle_headers.append(
                {
                    "label": subgroup_label,
                    "colspan": index - subgroup_start,
                    "end_column_index": index - 1,
                    "separator_before": bool(family_label == "PV" and subgroup_start == family_start),
                    "subgroup_separator_before": bool(subgroup_start != family_start),
                }
            )

            if subgroup_start != family_start:
                subgroup_separator_indexes.append(subgroup_start)

        top_headers.append(
            {
                "label": _display_group_family_label(family_label, top_headers),
                "colspan": index - family_start,
                "end_column_index": index - 1,
                "separator_before": bool(family_label == "PV"),
            }
        )

    return GroupedHeadersBuildResult(
        top_headers=top_headers,
        middle_headers=middle_headers,
        detail_headers=detail_headers,
        metric_column_indexes=metric_column_indexes,
        narrow_metric_column_indexes=narrow_metric_column_indexes,
        pv_separator_index=pv_separator_index,
        subgroup_separator_indexes=subgroup_separator_indexes,
    )


def _compact_group_label(column_name: str) -> str:
    """Return short display labels for grouped date-offset columns."""
    normalized_column_name = _normalize_column_name(column_name)
    explicit_labels = {
        "ev_perf_enquery_count_date_m2_m1_avg": "Avg T-2, T-1",
        "ev_perf_enquery_count_date_t_avg": "T",
        "ev_perf_enquery_count_date_p2_p1_avg": "Avg T+1, T+2",
        "ev_growth_enquery_count_date_t_vs_m2_avg": "Avg T-1,T-2 vs T",
        "ev_growth_enquery_count_date_p2_vs_t_avg": "Avg T+1, T+2 vs T",
        "pv_perf_enquery_count_date_m2_m1_avg": "Avg T-2, T-1",
        "pv_perf_enquery_count_date_t_avg": "T",
        "pv_perf_enquery_count_date_p2_p1_avg": "Avg T+1, T+2",
        "pv_growth_enquery_count_date_t_vs_m2_avg": "Avg T-1,T-2 vs T",
        "pv_growth_enquery_count_date_p2_vs_t_avg": "Avg T+1, T+2 vs T",
    }
    if normalized_column_name in explicit_labels:
        return explicit_labels[normalized_column_name]

    suffix = normalized_column_name.rsplit("_", maxsplit=1)[-1].lower()
    if suffix == "m2":
        return "T-2"
    if suffix == "m1":
        return "T-1"
    if suffix == "t":
        return "T"
    if suffix == "p1":
        return "T+1"
    if suffix == "p2":
        return "T+2"
    return column_name


def _build_preview_csv_content(
    headers: list[str],
    rows: list[list[str]],
    top_headers: list[TopHeader],
    middle_headers: list[MiddleHeader],
    detail_headers: list[DetailHeader],
) -> bytes:
    """Build CSV bytes that mirror the currently rendered preview table."""
    buffer = StringIO()
    writer = csv.writer(buffer)

    if detail_headers:
        first_row: list[str] = []
        second_row: list[str] = []
        third_row: list[str] = []
        middle_index = 0
        detail_index = 0

        for top_header in top_headers:
            label = str(top_header.get("label", ""))
            if "rowspan" in top_header:
                first_row.append(label)
                second_row.append("")
                third_row.append("")
                continue

            colspan = int(top_header.get("colspan", 1))
            first_row.append(label)
            first_row.extend([""] * max(0, colspan - 1))
            remaining = colspan
            while remaining > 0:
                if middle_index < len(middle_headers):
                    middle_header = middle_headers[middle_index]
                    middle_label = str(middle_header.get("label", ""))
                    middle_colspan = int(middle_header.get("colspan", 1))
                else:
                    middle_label = ""
                    middle_colspan = 1

                second_row.append(middle_label)
                second_row.extend([""] * max(0, middle_colspan - 1))

                for _ in range(middle_colspan):
                    if detail_index < len(detail_headers):
                        third_row.append(str(detail_headers[detail_index].get("short", "")))
                    else:
                        third_row.append("")
                    detail_index += 1

                middle_index += 1
                remaining -= middle_colspan

        writer.writerow(first_row)
        writer.writerow(second_row)
        writer.writerow(third_row)
    else:
        writer.writerow(headers)

    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _build_formatted_filename(filename: str) -> str:
    """Return a user-friendly filename for formatted preview CSV exports."""
    stripped = filename.strip() or "report.csv"
    if stripped.lower().endswith(".csv"):
        return f"{stripped[:-4]}_formatted.csv"
    return f"{stripped}_formatted.csv"


def _parse_iso_date(value: str, *, field_name: str) -> date:
    """Parse YYYY-MM-DD date input and raise a clear error for invalid values."""
    normalized = value.strip()
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid date in YYYY-MM-DD format.") from exc
