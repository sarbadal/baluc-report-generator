from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import zipfile

import pandas as pd
import pytest
from flask import Flask

from app.blueprints.auth import auth_blueprint
from app.blueprints.home import home_blueprint
from app.blueprints.home import _build_report_set_filenames
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
    name = (
        "brand_enquiry" if report_key == "brand-wise-enquery"
        else f"caption_{label.removeprefix('By Caption: ').lower()}"
    ) + "_20260701_20260702.csv"
    assert f"filename={name}" in download.headers["Content-Disposition"]
    assert name in view_body
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
        assert set(archive.namelist()) == {
            "brand_enquiry_20260701_20260702.csv",
            "caption_altroz_20260701_20260702.csv",
            "caption_curvv_20260701_20260702.csv",
            "caption_nexon_20260701_20260702.csv",
        }
        for report_key, (label, _) in reports.items():
            download = client.get(f"/reports/r1/reportset/download?report={report_key}")
            name = (
                "brand_enquiry" if report_key == "brand-wise-enquery"
                else f"caption_{label.removeprefix('By Caption: ').lower()}"
            ) + "_20260701_20260702.csv"
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
        assert archive.read("brand_enquiry_20260701_20260702.csv") == download.data


def test_report_set_filenames_are_short_safe_unique_and_stable() -> None:
    captions = ["A/B", "A B", "a_b", "a_b_2", "", "(blank)", "日本語", "../", "X" * 200, "X" * 201]
    reports = get_report_set_reports(pd.DataFrame({"caption": captions}))
    labels = {key: label for key, (label, _) in reports.items()}
    filenames = _build_report_set_filenames(
        "ev_20260701_20260702_long_internal_report_id.csv", labels
    )
    assert filenames == _build_report_set_filenames(
        "ev_20260701_20260702_long_internal_report_id.csv",
        dict(reversed(list(labels.items()))),
    )
    names = list(filenames.values())
    assert len({name.casefold() for name in names}) == len(reports)
    assert "caption_日本語_20260701_20260702.csv" in names
    assert "caption_blank_20260701_20260702.csv" in names
    for name in names:
        assert len(name) <= 72
        assert name.endswith("_20260701_20260702.csv")
        assert not any(character in name for character in ("/", "\\", ".."))
        assert "formatted" not in name


def test_report_set_filenames_without_date_range_do_not_invent_dates() -> None:
    assert _build_report_set_filenames(
        "empty.csv", {"brand-wise-enquery": "Brand wise Enquery"}
    ) == {"brand-wise-enquery": "brand_enquiry.csv"}


def test_report_set_zip_handles_colliding_and_unicode_captions(monkeypatch) -> None:
    base_df = pd.DataFrame({
        "bu": ["PV"] * 5,
        "caption": ["A/B", "A B", "", "日本語", "X" * 200],
    })
    monkeypatch.setattr(
        _FakeReportJobManager,
        "get_download_file",
        lambda self, report_id: (
            "ev_20260701_20260702_r1.csv", base_df.to_csv(index=False).encode("utf-8")
        ),
    )
    client = _make_client()
    reports = get_report_set_reports(base_df)
    filenames = _build_report_set_filenames(
        "ev_20260701_20260702_r1.csv",
        {key: label for key, (label, _) in reports.items()},
    )
    response = client.get("/reports/r1/reportset/download-all")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert len(set(archive.namelist())) == len(reports)
        for report_key, name in filenames.items():
            download = client.get(f"/reports/r1/reportset/download?report={report_key}")
            assert download.status_code == 200
            assert archive.read(name) == download.data
            if name.isascii():
                assert f"filename={name}" in download.headers["Content-Disposition"]
            else:
                from urllib.parse import quote
                assert f"filename*=UTF-8''{quote(name)}" in download.headers["Content-Disposition"]


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


def test_all_caption_is_excluded_from_report_set_surfaces(monkeypatch) -> None:
    csv_content = BASE_CSV + b"All,All,Kerala,Ajit,AJIT,2026-07-01,13\n"
    base_df = load_base_report_dataframe(csv_content)
    original_df = base_df.copy(deep=True)
    reports = get_report_set_reports(base_df)
    assert len(reports) == 4
    assert all(label != "By Caption: All" for label, _ in reports.values())
    pd.testing.assert_frame_equal(base_df, original_df)
    monkeypatch.setattr(
        _FakeReportJobManager,
        "get_download_file",
        lambda self, report_id: ("ev_20260701_20260702_r1.csv", csv_content),
    )
    client = _make_client()
    page = client.get("/reports/r1/reportset").get_data(as_text=True)
    assert "4 reports from 5 base rows" in page
    assert "By Caption: All" not in page
    assert "By Caption: Altroz" in page
    all_key = f"by-caption-{sha256(b'All').hexdigest()}"
    for action in ("view", "download"):
        assert client.get(f"/reports/r1/reportset/{action}?report={all_key}").status_code == 404
    response = client.get("/reports/r1/reportset/download-all")
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert len(archive.namelist()) == 4
        assert "caption_all_20260701_20260702.csv" not in archive.namelist()
        assert "brand_enquiry_20260701_20260702.csv" in archive.namelist()
    assert client.get("/reports/r1/download").data == csv_content


def test_missing_caption_column_is_an_explicit_error() -> None:
    with pytest.raises(ValueError, match="caption"):
        get_report_set_reports(pd.DataFrame({"bu": ["PV"]}))


def test_brand_wise_enquery_keeps_existing_custom_filter() -> None:
    base_df = pd.DataFrame({"bu": ["--", "PV"], "caption": ["A", "B"]})
    _, builder = REPORT_SET_REPORTS["brand-wise-enquery"]
    pd.testing.assert_frame_equal(builder(base_df), base_df.loc[[0]])
