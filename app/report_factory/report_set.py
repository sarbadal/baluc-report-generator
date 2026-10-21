"""Predefined reports built from the unformatted base report DataFrame."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from hashlib import sha256
from io import BytesIO

import pandas as pd

from app.report_factory.dedup import Deduplicator, DedupParameters


ENQUIRY_PERIODS = ("m2", "m1", "t", "p1", "p2")
METRIC_PREFIXES = ("ev", "pv", "evc")
METRIC_COLUMNS = {
    prefix: tuple(f"{prefix}_enquery_count_date_{period}" for period in ENQUIRY_PERIODS)
    for prefix in METRIC_PREFIXES
}
PERFORMANCE_PERIODS = {
    "m2_m1": ("m2", "m1"),
    "t": ("t", "t"),
    "p2_p1": ("p2", "p1"),
}
GROWTH_COMPARISONS = {"t_vs_m2": ("t", "m2_m1"), "p2_vs_t": ("p2_p1", "t")}
WINDOW_OFFSETS = {
    "tm2": {"m2": -1, "t": -2, "p1": -3, "p2": -4},
    "tm1": {"t": -1, "p1": -2},
    "tp1": {"t": 1},
    "tp2": {"m1": 3, "t": 2, "p1": 1},
}
IDENTITY_COLUMNS = ("bu", "caption", "ppl", "state", "pub_name", "date")

COLUMNS = [
    *IDENTITY_COLUMNS,
    *METRIC_COLUMNS["ev"],
    "ev_perf_enquery_count_date_m2_m1_avg",
    "ev_perf_enquery_count_date_t_avg",
    "ev_perf_enquery_count_date_p2_p1_avg",
    "ev_growth_enquery_count_date_t_vs_m2_avg",
    "ev_growth_enquery_count_date_p2_vs_t_avg",
    *METRIC_COLUMNS["pv"],
    "pv_perf_enquery_count_date_m2_m1_avg",
    "pv_perf_enquery_count_date_t_avg",
    "pv_perf_enquery_count_date_p2_p1_avg",
    "pv_growth_enquery_count_date_t_vs_m2_avg",
    "pv_growth_enquery_count_date_p2_vs_t_avg",
    *METRIC_COLUMNS["evc"],
    "evc_perf_enquery_count_date_m2_m1_avg",
    "evc_perf_enquery_count_date_t_avg",
    "evc_perf_enquery_count_date_p2_p1_avg",
    "evc_growth_enquery_count_date_t_vs_m2_avg",
    "evc_growth_enquery_count_date_p2_vs_t_avg",
]


def _calculate_window_sum(df: pd.DataFrame, parameters: DedupParameters, window_offsets: dict[str, int], *, include_caption: bool = False, include_ppl: bool = False) -> int:
    total = 0
    for column, offset in window_offsets.items():
        mask = (df["date"] == parameters.date + pd.Timedelta(days=offset)) & (
            df["state"] == parameters.state
        )
        if include_caption:
            mask &= df["caption"] == parameters.caption
        if include_ppl:
            mask &= df["ppl"] == parameters.ppl
        total += df.loc[mask, column].sum()
    return total


def calculate_window_date_state_sum(df: pd.DataFrame, parameters: DedupParameters, window_offsets: dict[str, int]) -> int:
    """Sum metrics on matching dates and state."""
    return _calculate_window_sum(df, parameters, window_offsets)


def calculate_window_date_state_caption_sum(df: pd.DataFrame, parameters: DedupParameters, window_offsets: dict[str, int]) -> int:
    """Sum metrics on matching dates, state, and caption."""
    return _calculate_window_sum(df, parameters, window_offsets, include_caption=True)


def calculate_window_date_state_ppl_sum(df: pd.DataFrame, parameters: DedupParameters, window_offsets: dict[str, int]) -> int:
    """Sum metrics on matching dates, state, and ppl."""
    return _calculate_window_sum(df, parameters, window_offsets, include_ppl=True)


def _add_performance_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add performance averages and growth percentages for each metric family."""
    for prefix in METRIC_PREFIXES:
        averages: dict[str, pd.Series] = {}
        for period_name, periods in PERFORMANCE_PERIODS.items():
            average_column = f"{prefix}_perf_enquery_count_date_{period_name}_avg"
            source_columns = [f"{prefix}_enquery_count_date_{period}" for period in periods]
            df[average_column] = df[source_columns].mean(axis=1)
            averages[period_name] = df[average_column]

        for comparison, (numerator, denominator) in GROWTH_COMPARISONS.items():
            growth_column = f"{prefix}_growth_enquery_count_date_{comparison}_avg"
            df[growth_column] = (averages[numerator] / averages[denominator] - 1) * 100
    return df


def _has_report_columns(df: pd.DataFrame, *, include_metrics: bool = True) -> bool:
    required_columns = set(IDENTITY_COLUMNS)
    if include_metrics:
        required_columns.update(
            column for columns in METRIC_COLUMNS.values() for column in columns
        )
    return required_columns.issubset(df.columns)


def load_base_report_dataframe(csv_content: bytes) -> pd.DataFrame:
    """Load base CSV columns and values before preview formatting is applied."""
    if not csv_content.decode("utf-8-sig").strip():
        return pd.DataFrame()
    return pd.read_csv(
        BytesIO(csv_content), encoding="utf-8-sig", keep_default_na=False,
        dtype={"caption": str},
    )


def brand_wise_enquery(base_df: pd.DataFrame) -> pd.DataFrame:
    """Build the brand-wise report from base rows."""
    report_df = base_df.copy(deep=True)
    if not set(IDENTITY_COLUMNS).issubset(report_df.columns):
        return report_df.loc[report_df["bu"] == "--"].copy()

    # Older or reduced base reports may omit metrics; preserve the output schema.
    for columns in METRIC_COLUMNS.values():
        for column in columns:
            if column not in report_df:
                report_df[column] = 0

    left = report_df.loc[report_df["bu"] == "--"].copy()
    left["ppl"] = "All"
    left = left.loc[:, ["bu", "caption", "state", "date", "pub_name", "ppl"]]
    left = left.sort_values(by=["bu", "caption", "state", "pub_name", "date"]).drop_duplicates()

    all_bu = report_df.loc[report_df["bu"] == "All"].copy()
    ev_pv_columns = [*METRIC_COLUMNS["ev"], *METRIC_COLUMNS["pv"]]
    all_bu = _coerce_and_group_metrics(all_bu, ev_pv_columns)
    result = left.merge(all_bu, on=["state", "date"], how="left")

    evc_rows = report_df.loc[report_df["bu"] == "--"].copy()
    evc_rows = _coerce_and_group_metrics(evc_rows, METRIC_COLUMNS["evc"])
    result = result.merge(evc_rows, on=["caption", "state", "date"], how="left")

    for prefix in METRIC_PREFIXES:
        result = _deduplicate_metric_family(
            result,
            prefix,
            window_sum_calculator=(
                calculate_window_date_state_caption_sum
                if prefix == "evc"
                else calculate_window_date_state_sum
            ),
        )

    result = _add_performance_metrics(result)

    for column in COLUMNS:
        if column not in result:
            result[column] = pd.NA

    return result.loc[:, COLUMNS].copy()


def _coerce_and_group_metrics(df: pd.DataFrame, columns: tuple[str, ...] | list[str]) -> pd.DataFrame:
    """Coerce metric values and sum them by caption, state, and date."""
    for column in columns:
        df[column] = (
            pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
        )
    return df.groupby(["caption", "state", "date"])[list(columns)].sum()


def _coerce_and_group_metrics_ppl(df: pd.DataFrame, columns: tuple[str, ...] | list[str]) -> pd.DataFrame:
    """Coerce metric values and sum them by caption, state, pub_name, ppl, and date."""
    for column in columns:
        df[column] = (
            pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
        )
    return df.groupby(["caption", "state", "pub_name", "ppl", "date"])[list(columns)].sum()


def _deduplicate_metric_family(
    df: pd.DataFrame, 
    prefix: str, 
    *, 
    tm1_target: str = "m1", 
    window_sum_calculator: Callable[[pd.DataFrame, DedupParameters, dict[str, int]], int] = calculate_window_date_state_sum
) -> pd.DataFrame:
    """Apply the shared four-window deduplication rules to one metric family."""
    target_columns = {
        "tm2": f"{prefix}_enquery_count_date_m2",
        "tm1": f"{prefix}_enquery_count_date_{tm1_target}",
        "tp1": f"{prefix}_enquery_count_date_p1",
        "tp2": f"{prefix}_enquery_count_date_p2",
    }
    offsets = {
        window: {
            f"{prefix}_enquery_count_date_{period}": offset
            for period, offset in period_offsets.items()
        }
        for window, period_offsets in WINDOW_OFFSETS.items()
    }
    return (
        Deduplicator(
            df,
            **{f"{window}_offset": window_offsets for window, window_offsets in offsets.items()},
            **target_columns,
            window_sum_calculator=window_sum_calculator,
        )
        .deduplicate_all()
        .drop_auxiliary_columns()
        .df
    )


def caption_report(base_df: pd.DataFrame) -> pd.DataFrame:
    """Generate a caption-specific report."""
    if not _has_report_columns(base_df):
        return base_df.copy(deep=True)

    report_df = base_df.copy(deep=True)

    for prefix in METRIC_PREFIXES:
        report_df = _deduplicate_metric_family(
            report_df,
            prefix,
            window_sum_calculator=calculate_window_date_state_ppl_sum,
        )

    result = _add_performance_metrics(report_df)

    for column in COLUMNS:
        if column not in result:
            result[column] = pd.NA

    return result.loc[:, COLUMNS].copy()


def by_caption(base_df: pd.DataFrame, *, caption: str) -> pd.DataFrame:
    """Customize one caption's report without modifying the base DataFrame."""
    report_df = base_df.loc[base_df["caption"] == caption].copy(deep=True)
    if not _has_report_columns(base_df) or "bu" not in base_df:
        return report_df

    left = report_df.loc[report_df["bu"] == "--"].copy()
    left = left.loc[:, ["bu", "caption", "ppl", "state", "pub_name", "date" ]]
    left = left.sort_values(by=["bu", "caption", "ppl", "state", "pub_name", "date"]).drop_duplicates()

    all_bu = base_df.loc[base_df["bu"] == "All"].copy()
    ev_pv_columns = [*METRIC_COLUMNS["ev"], *METRIC_COLUMNS["pv"]]
    all_bu = _coerce_and_group_metrics(all_bu, ev_pv_columns)
    result = left.merge(all_bu, on=["state", "date"], how="left")

    evc_rows = report_df.loc[report_df["bu"] == "--"].copy()
    evc_rows = _coerce_and_group_metrics_ppl(evc_rows, METRIC_COLUMNS["evc"])
    result = result.merge(evc_rows, on=["caption", "ppl", "state", "pub_name", "date"], how="left")

    return caption_report(result)


REPORT_SET_REPORTS: dict[str, tuple[str, Callable[[pd.DataFrame], pd.DataFrame]]] = {
    "brand-wise-enquery": ("Brand wise Enquery", brand_wise_enquery),
}


def get_report_set_reports(base_df: pd.DataFrame) -> dict[str, tuple[str, Callable[[pd.DataFrame], pd.DataFrame]]]:
    """Combine fixed reports with one dynamically registered report per caption."""
    reports = REPORT_SET_REPORTS.copy()
    if base_df.empty:
        return reports
    if "caption" not in base_df.columns:
        raise ValueError("The base report must contain a 'caption' column.")
    for caption in sorted(base_df["caption"].unique(), key=lambda value: (value.casefold(), value)):
        caption_key = sha256(caption.encode("utf-8")).hexdigest()
        reports[f"by-caption-{caption_key}"] = (
            f"By Caption: {caption or '(blank)'}",
            partial(by_caption, caption=caption),
        )
    return reports
