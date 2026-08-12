"""Home and report generator blueprint for report operations workflow."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import os

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
RECENT_REPORTS_LIMIT = 20


@home_blueprint.route("/", methods=["GET"])
def home():
    """Render application landing page with a snapshot of recent report activity."""
    report_job_manager = _get_report_job_manager()
    recent_reports = report_job_manager.list_recent_jobs(limit=RECENT_REPORTS_LIMIT)
    completed_count = sum(1 for report in recent_reports if report.get("status") == "Completed")
    failed_count = sum(1 for report in recent_reports if report.get("status") == "Failed")
    generating_count = sum(1 for report in recent_reports if report.get("status") == "Generating")

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
    form_data = {
        "start_date": request.form.get("start_date", date.today().isoformat()),
        "end_date": request.form.get("end_date", date.today().isoformat()),
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
        else:
            row["download_url"] = None
        payload.append(row)

    return jsonify({"reports": payload})


def _get_report_job_manager():
    """Return shared report job manager from Flask app extensions."""
    manager = current_app.extensions.get("report_job_manager")
    if manager is None:
        raise RuntimeError("report_job_manager is not initialized.")
    return manager
