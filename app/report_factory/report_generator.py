"""Class-based report generation module for multiple report types."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Callable

import pandas as pd


@dataclass(slots=True)
class ReportGenerator:
    """Generate report DataFrames through a single extensible interface."""

    dataframe: pd.DataFrame
    report_type: str
    start_date: str
    end_date: str

    _handlers: dict[str, Callable[[], pd.DataFrame]] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate inputs and build report-type to handler mapping."""
        if self.dataframe is None:
            raise ValueError("dataframe must not be None.")
        if not self.report_type.strip():
            raise ValueError("report_type must not be empty.")
        if not self.start_date.strip():
            raise ValueError("start_date must not be empty.")
        if not self.end_date.strip():
            raise ValueError("end_date must not be empty.")

        self._handlers = {
            "PRINT": self.generate_print_report,
            "EV": self.generate_ev_report,
            "CONTACT": self.generate_contact_report,
        }

    def generate_report(self) -> pd.DataFrame:
        """Route report generation to the correct handler by report type."""
        normalized_type = self.report_type.strip().upper()

        handler = self._handlers.get(normalized_type)
        if handler is None:
            supported = ", ".join(sorted(self._handlers.keys()))
            raise ValueError(
                f"Unsupported report_type '{self.report_type}'. Supported: {supported}"
            )

        return handler()

    def generate_print_report(self) -> pd.DataFrame:
        """Generate grouped PRINT report output for the requested date window."""
        filtered = self._apply_date_range_if_possible(
            dataframe=self.dataframe.copy(),
            start_date=self.start_date,
            end_date=self.end_date,
        )
        columns_to_include = [
            "pub_name",
            "client",
            "est_no",
            "pr_name",
            "schedule_dt",
            "RO_AMT",
        ]
        renamed_columns = {
            "pub_name": "Publication Name",
            "client": "Client",
            "est_no": "Estimate Number",
            "pr_name": "PR Name",
            "schedule_dt": "Schedule Date",
            "RO_AMT": "RO Amount",
        }

        available_columns = [
            column for column in columns_to_include if column in filtered.columns
        ]
        if not available_columns:
            return filtered.head(15)

        grouped_df = filtered.groupby(available_columns).size().reset_index(name="count")
        return grouped_df.rename(columns=renamed_columns)

    def generate_ev_report(self) -> pd.DataFrame:
        """Generate EV/EB report output for the requested date window."""
        source = self.dataframe.copy()
        filtered = self._apply_date_range_if_possible(
            dataframe=source,
            start_date=self.start_date,
            end_date=self.end_date,
        )

        # EV files are already date-scoped during discovery; if row-level date
        # filtering removes everything due to incompatible column formats,
        # prefer returning discovered data over an empty report.
        if filtered.empty and not source.empty:
            return source

        return filtered

    def generate_contact_report(self) -> pd.DataFrame:
        """Generate CONTACT report output for the requested date window."""
        filtered = self._apply_date_range_if_possible(
            dataframe=self.dataframe.copy(),
            start_date=self.start_date,
            end_date=self.end_date,
        )
        preferred_group_cols = [
            column
            for column in ["pub_name", "client", "pr_name", "schedule_dt"]
            if column in filtered.columns
        ]
        if not preferred_group_cols:
            return filtered

        return filtered.groupby(preferred_group_cols).size().reset_index(name="count")

    @staticmethod
    def _apply_date_range_if_possible(dataframe: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        """Apply date filtering when a known date column exists in the DataFrame."""
        if dataframe.empty:
            return dataframe

        start = datetime.strptime(start_date.strip(), "%Y-%m-%d")
        end = datetime.strptime(end_date.strip(), "%Y-%m-%d")
        if start > end:
            raise ValueError("start_date must be on or before end_date.")

        date_columns = ["schedule_dt", "schedule_date", "date", "report_date"]
        target_column = next(
            (column for column in date_columns if column in dataframe.columns),
            None,
        )
        if target_column is None:
            return dataframe

        parsed = pd.to_datetime(dataframe[target_column], errors="coerce")
        mask = parsed.between(start, end, inclusive="both")
        return dataframe.loc[mask].copy()