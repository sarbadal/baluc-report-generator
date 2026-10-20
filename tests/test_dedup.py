import pandas as pd
import pytest

from app.report_factory.dedup import Deduplicator


def _frame(dates) -> pd.DataFrame:
    return pd.DataFrame({
        "date": dates,
        "caption": ["Altroz"] * len(dates),
        "ppl": ["Altroz"] * len(dates),
        "state": ["Kerala"] * len(dates),
        "pub_name": ["AJIT"] * len(dates),
        "T": list(range(1, len(dates) + 1)),
    })


@pytest.mark.parametrize("timestamps", [False, True])
def test_window_sums_accept_csv_dates_and_timestamps_without_mutating_input(timestamps) -> None:
    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    frame = _frame(pd.to_datetime(dates) if timestamps else dates)
    original = frame.copy(deep=True)
    dedup = Deduplicator(
        frame, tm2_offset={"T": -2}, tm1_offset={"T": -1},
        tp1_offset={"T": 1}, tp2_offset={"T": 2},
    ).add_all_columns()

    assert dedup.df["_Tm2"].tolist() == [0, 0, 1]
    assert dedup.df["_Tm1"].tolist() == [0, 1, 2]
    assert dedup.df["_Tp1"].tolist() == [2, 3, 0]
    assert dedup.df["_Tp2"].tolist() == [3, 0, 0]
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("date", ["not-a-date", "", None])
def test_invalid_or_missing_dates_raise_explicit_errors(date) -> None:
    with pytest.raises(ValueError):
        Deduplicator(_frame([date]), {}, {}, {}, {})


def test_window_sums_convert_numeric_strings_and_ignore_blanks() -> None:
    frame = _frame(["2026-07-01"] * 6 + ["2026-07-02"])
    frame["T"] = ["2", "3.5", "", "  ", None, "0", "7"]
    original = frame.copy(deep=True)
    dedup = Deduplicator(frame, {"T": -1}, {}, {}, {}).add_tm2_column()

    assert dedup.df["_Tm2"].tolist() == [0, 0, 0, 0, 0, 0, 5.5]
    assert pd.api.types.is_numeric_dtype(dedup.df["T"])
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("window", range(4))
def test_each_window_converts_its_metric_columns(window) -> None:
    frame = _frame(["2026-07-01", "2026-07-02"])
    frame["enquiry"] = ["4", "5"]
    offsets = [{}, {}, {}, {}]
    offsets[window] = {"enquiry": -1}
    dedup = Deduplicator(frame, *offsets).add_all_columns()
    assert dedup.df[["_Tm2", "_Tm1", "_Tp1", "_Tp2"][window]].tolist() == [0, 4]


def test_nonnumeric_metric_raises_instead_of_silently_becoming_zero() -> None:
    frame = _frame(["2026-07-01"])
    frame["T"] = ["invalid"]
    with pytest.raises(ValueError, match="invalid"):
        Deduplicator(frame, {"T": -1}, {}, {}, {})
