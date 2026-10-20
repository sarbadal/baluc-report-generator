from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pandas as pd
import pytest
from flask import Flask

from app.blueprints.auth import auth_blueprint
from app.blueprints.home import home_blueprint
from app.report_factory.report_set import REPORT_SET_REPORTS
from app.report_factory.report_set import by_caption
from app.report_factory.report_set import get_report_set_reports
from app.report_factory.report_set import load_base_report_dataframe

BASE_CSV = (
    "bu,caption,state,publication,pub_name,date,ev_enquery_count_date_t\n"
    "PV,Altroz,Kerala,Ajit,AJIT,2026-07-01,3\n"
    "PV,Nexon,Kerala,Ajit,AJIT,2026-07-02,4\n"
    "EV,Curvv,Tamil Nadu,Dainik Bhaskar,DAINIK BHASKAR,2026-07-01,5\n"
    "EV,Curvv,,Dainik Bhaskar,DAINIK BHASKAR,2026-07-01,1\n"
).encode("utf-8")


class _FakeReportJobManager:
    def get_download_file(self, report_id: str) -> tuple[str, bytes] | None:
        if report_id == "r1":
            return "ev_20260701_20260702_r1.csv", BASE_CSV
        return None

    def list_recent_jobs(self, limit: int = 5) -> list[dict[str, str | None]]:
        return [
            {
                "report_id": "r1",
                "report_type": "EV",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "requested_at": "now",
                "status": "Completed",
                "error": None,
            }
        ]


def _make_client():
    template_folder = Path(__file__).resolve().parents[1] / "app" / "templates"
    app = Flask(__name__, template_folder=str(template_folder))
    app.config.update(SECRET_KEY="test-secret", TESTING=True)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(home_blueprint)
    app.extensions["report_job_manager"] = _FakeReportJobManager()

    @app.context_processor
    def template_globals() -> dict[str, object]:
        return {
            "app_password_enabled": False,
            "current_year": 2026,
            "static_asset": lambda filename: f"/static/{filename}",
        }

    return app.test_client()


def test_report_set_page_lists_predefined_reports() -> None:
    response = _make_client().get("/reports/r1/reportset")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "4 reports from 4 base rows" in body
    assert "Brand wise Enquery" in body
    assert "By Caption: Altroz" in body
    assert "By Caption: Nexon" in body
    assert "By Caption: Curvv" in body
    assert "By Brand" not in body
    assert "Split by:" not in body
    assert "/reports/r1/reportset/download-all" in body
    assert "report=brand-wise-enquery" in body
    assert "report=by-caption-" in body


def test_base_dataframe_retains_raw_headers_numbers_and_blank_values() -> None:
    base_df = load_base_report_dataframe(BASE_CSV)

    assert list(base_df.columns) == BASE_CSV.decode().splitlines()[0].split(",")
    assert base_df["ev_enquery_count_date_t"].sum() == 13
    assert base_df.loc[3, "state"] == ""
    frame = load_base_report_dataframe(
        b"\xef\xbb\xbfpub_name,growth\nNA,12.345\n,0\n"
    )
    assert frame.loc[0, "pub_name"] == "NA"
    assert frame.loc[0, "growth"] == 12.345


def test_caption_builder_returns_independent_filtered_dataframe() -> None:
    base_df = load_base_report_dataframe(BASE_CSV)
    report_df = by_caption(base_df, caption="Curvv")
    pd.testing.assert_frame_equal(report_df, base_df.loc[[2, 3]])
    report_df.loc[2, "caption"] = "Changed"
    assert base_df.loc[0, "caption"] == "Altroz"
    assert base_df.loc[2, "caption"] == "Curvv"


@pytest.mark.parametrize("report_key,label", [
    (key, label) for key, (label, _) in get_report_set_reports(
        load_base_report_dataframe(BASE_CSV)
    ).items()
])
def test_report_set_item_view_and_download_use_builder_data(report_key: str, label: str) -> None:
    client = _make_client()
    base_df = load_base_report_dataframe(BASE_CSV)
    _, builder = get_report_set_reports(base_df)[report_key]
    expected_df = builder(base_df)

    view = client.get(f"/reports/r1/reportset/view?report={report_key}")
    assert view.status_code == 200
    view_body = view.get_data(as_text=True)
    assert label in view_body
    assert f"{len(expected_df)} data rows" in view_body
    assert "Back to Report Set" in view_body

    download = client.get(f"/reports/r1/reportset/download?report={report_key}")
    assert download.status_code == 200
    assert f"_{report_key.replace('-', '_')}_formatted.csv" in download.headers["Content-Disposition"]
    from app.blueprints.home import _build_formatted_csv, _dataframe_preview_table
    assert download.data == _build_formatted_csv(*_dataframe_preview_table(expected_df))
    assert client.get("/reports/r1/download").data == BASE_CSV


def test_report_set_download_all_returns_zip_of_items() -> None:
    client = _make_client()
    response = client.get("/reports/r1/reportset/download-all")

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        reports = get_report_set_reports(load_base_report_dataframe(BASE_CSV))
        assert len(archive.namelist()) == 4
        for report_key in reports:
            download = client.get(f"/reports/r1/reportset/download?report={report_key}")
            name = f"ev_20260701_20260702_r1_{report_key.replace('-', '_')}_formatted.csv"
            assert archive.read(name) == download.data


def test_report_set_returns_404_for_unknown_or_missing_report() -> None:
    client = _make_client()

    assert client.get("/reports/missing/reportset").status_code == 404
    for action in ("view", "download"):
        assert client.get(f"/reports/r1/reportset/{action}?report=unknown").status_code == 404
        assert client.get(f"/reports/r1/reportset/{action}").status_code == 404
        assert client.get(
            f"/reports/missing/reportset/{action}?report=brand-wise-enquery"
        ).status_code == 404
        assert client.get(f"/reports/r1/reportset/{action}?report=by-brand").status_code == 404
    assert client.get("/reports/missing/reportset/download-all").status_code == 404


def test_custom_dataframe_is_used_by_page_preview_download_and_zip(monkeypatch) -> None:
    def custom_report(base_df: pd.DataFrame) -> pd.DataFrame:
        return base_df.loc[base_df["caption"] == "Altroz", ["caption", "state"]].copy()

    monkeypatch.setitem(REPORT_SET_REPORTS, "brand-wise-enquery", ("Brand wise Enquery", custom_report))
    client = _make_client()
    body = client.get("/reports/r1/reportset").get_data(as_text=True)
    assert "<td>Brand wise Enquery</td>\n            <td>1</td>" in body
    preview = client.get("/reports/r1/reportset/view?report=brand-wise-enquery").get_data(as_text=True)
    assert "1 data rows" in preview
    assert "Nexon" not in preview
    download = client.get("/reports/r1/reportset/download?report=brand-wise-enquery")
    assert download.data == b"caption,state\r\nAltroz,Kerala\r\n"
    archive_response = client.get("/reports/r1/reportset/download-all")
    with zipfile.ZipFile(BytesIO(archive_response.data)) as archive:
        assert archive.read("ev_20260701_20260702_r1_brand_wise_enquery_formatted.csv") == download.data


def test_empty_base_report_keeps_predefined_reports_available(monkeypatch) -> None:
    monkeypatch.setattr(
        _FakeReportJobManager,
        "get_download_file",
        lambda self, report_id: ("empty.csv", b"bu,caption,state\n"),
    )
    client = _make_client()
    body = client.get("/reports/r1/reportset").get_data(as_text=True)
    assert "1 reports from 0 base rows" in body
    assert "Brand wise Enquery" in body and "By Caption:" not in body
    assert client.get("/reports/r1/reportset/download?report=brand-wise-enquery").data == b"bu,caption,state\r\n"
    assert load_base_report_dataframe(b"").empty


def test_queue_and_status_expose_report_set_link() -> None:
    client = _make_client()

    payload = client.get("/reports/status").get_json()
    assert payload["reports"][0]["reportset_url"] == "/reports/r1/reportset"
    assert "/reports/r1/reportset" in client.get("/").get_data(as_text=True)


def test_caption_registry_preserves_exact_values_and_stable_unique_keys() -> None:
    base_df = pd.DataFrame({
        "bu": ["PV"] * 7,
        "caption": ["A/B", "A B", "", "日本語", "001", "A/B", " Altroz "],
    })
    reports = get_report_set_reports(base_df)
    assert len(reports) == 7
    reordered = get_report_set_reports(base_df.iloc[::-1])
    assert list(reports) == list(reordered)
    collected = []
    for key, (label, builder) in reports.items():
        if not key.startswith("by-caption-"):
            continue
        frame = builder(base_df)
        assert frame["caption"].nunique(dropna=False) == 1
        assert "/" not in key
        collected.extend(frame.index)
    assert sorted(collected) == list(base_df.index)
    assert any(label == "By Caption: (blank)" for label, _ in reports.values())
    numeric_caption = load_base_report_dataframe(b"bu,caption\nPV,001\n")
    assert numeric_caption.loc[0, "caption"] == "001"


def test_missing_caption_column_is_an_explicit_error() -> None:
    with pytest.raises(ValueError, match="caption"):
        get_report_set_reports(pd.DataFrame({"bu": ["PV"]}))


def test_brand_wise_enquery_keeps_existing_custom_filter() -> None:
    base_df = pd.DataFrame({"bu": ["--", "PV"], "caption": ["A", "B"]})
    _, builder = REPORT_SET_REPORTS["brand-wise-enquery"]
    pd.testing.assert_frame_equal(builder(base_df), base_df.loc[[0]])
