"""Report generation orchestration and transformer inputs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import ClassVar

import pandas as pd

from app.services import GCSCSVDataLoader


logger = logging.getLogger(__name__)


@dataclass
class ReportAggregationTransformer:
    """Receive report dataframes and configuration for future transformation."""

    MAPPING_BLOB_PATHS: ClassVar[dict[str, str]] = {
        "ppl_caption_bu": "gs://inventory-baluc/mapping/ppl-caption-bu.csv",
        "publication": "gs://inventory-baluc/mapping/publications.csv"
    }
    PRINT_GROUP_KEYS: ClassVar[list[str]] = ["bu", "caption", "ppl", "state", "publication", "pub_name", "finalschdt"]
    OPPORTUNITY_GROUP_KEYS: ClassVar[list[str]] = ["bu", "caption", "state", "zone", "event_date"]
    REPORT_JOIN_KEYS: ClassVar[list[str]] = ["bu", "caption", "state"]
    OPPORTUNITY_AGG_COLUMN: ClassVar[str] = "gf_opportunity_created"
    REPORT_BASE_OUTPUT_COLUMNS: ClassVar[list[str]] = [
        "bu",
        "caption",
        "state",
        "publication",
        "pub_name",
        "date",
    ]
    INTERMEDIATE_REPORT_COLUMNS: ClassVar[list[str]] = [
        "bu",
        "caption",
        "state",
        "publication",
        "pub_name",
        "finalschdt",
    ]

    WINDOW_MAPPER: ClassVar[dict[str, pd.DateOffset]] = {
        "date_m2": pd.DateOffset(days=-2),
        "date_m1": pd.DateOffset(days=-1),
        "date_t": pd.DateOffset(days=0),
        "date_p1": pd.DateOffset(days=1),
        "date_p2": pd.DateOffset(days=2),
    }
    FILTER_VALUES_BY_COLUMN: ClassVar[dict[str, list[str]]] = {
        "source": ["Natural"],
    }
 
    start_date: str
    end_date: str
    key_column: str | list[str]
    date_column: str
    mapping_loader: GCSCSVDataLoader | None = None
    
    def load_mapping_data(self, mapping_blob_path: str, **read_csv_kwargs: object) -> pd.DataFrame:
        """Load one mapping CSV from a gs:// path and return it as a DataFrame."""
        path = mapping_blob_path.strip()
        if not path:
            raise ValueError("mapping_blob_path must not be empty.")
        if self.mapping_loader is None:
            raise ValueError("mapping_loader must be provided to load mapping data.")

        mapping_df = self.mapping_loader.load_blob_path(path, **read_csv_kwargs)
        return mapping_df

    def transform(self, print_df: pd.DataFrame, ev_df: pd.DataFrame, contract_df: pd.DataFrame) -> pd.DataFrame:
        """Pass through the combined DataFrames without transformation logic."""
        self._validate_input_frames(print_df, ev_df, contract_df)

        mapping_dfs = self._load_mapping_dataframes()
        mapping_ppl_caption_bu_df = self._require_mapping(mapping_dfs, "ppl_caption_bu")
        mapping_publication_df = self._require_mapping(mapping_dfs, "publication")
        ev_filtered_df = self._filter_df_by(ev_df, "source")
        pv_filtered_df = self._filter_df_by(contract_df, "source")

        print_grouped_bu = self._build_print_grouped(print_df, mapping_ppl_caption_bu_df, mapping_publication_df)
        ev = self._build_opportunity_aggregate(ev_filtered_df, mapping_ppl_caption_bu_df)
        pv = self._build_opportunity_aggregate(pv_filtered_df, mapping_ppl_caption_bu_df)

        report = self._build_report(print_grouped_bu, ev, pv)
        self._display("report first 15", report, n=15)

        return report.copy()

    def _filter_df_by(self, df: pd.DataFrame, column_name: str) -> pd.DataFrame:
        """Filter a DataFrame by a specific column value, returning a copy of the filtered DataFrame."""
        if df is None:
            raise ValueError("df must not be None.")
        if column_name not in df.columns:
            raise ValueError(f"Column '{column_name}' not found in DataFrame columns.")
        if column_name not in self.FILTER_VALUES_BY_COLUMN:
            raise ValueError(f"No filter values configured for column '{column_name}'.")

        normalized_allowed_values = {
            str(value).strip().casefold() for value in self.FILTER_VALUES_BY_COLUMN[column_name]
        }
        filtered_df = df[
            df[column_name]
            .astype("string")
            .str.strip()
            .str.casefold()
            .isin(normalized_allowed_values)
        ]
        return filtered_df.copy()

    def _validate_input_frames(self, print_df: pd.DataFrame, ev_df: pd.DataFrame, contract_df: pd.DataFrame) -> None:
        """Validate required source DataFrames before transformation."""
        if print_df is None:
            raise ValueError("print_df must not be None.")
        if ev_df is None:
            raise ValueError("ev_df must not be None.")
        if contract_df is None:
            raise ValueError("contract_df must not be None.")

    def _load_mapping_dataframes(self) -> dict[str, pd.DataFrame]:
        """Load all configured mapping CSVs and return them keyed by logical name."""
        mapping_dfs: dict[str, pd.DataFrame] = {}
        for mapping_name, blob_path in self.MAPPING_BLOB_PATHS.items():
            mapping_dfs[mapping_name] = self.load_mapping_data(blob_path)
        return mapping_dfs

    def _require_mapping(self, mapping_dfs: dict[str, pd.DataFrame], mapping_name: str) -> pd.DataFrame:
        """Return a mapping DataFrame by name with a clear error when missing."""
        mapping_df = mapping_dfs.get(mapping_name)
        if mapping_df is None:
            raise ValueError(f"Mapping '{mapping_name}' not found. Available mappings: {sorted(mapping_dfs.keys())}")
        return mapping_df

    def _build_print_grouped(self, print_df: pd.DataFrame, mapping_ppl_caption_bu_df: pd.DataFrame, mapping_publication_df: pd.DataFrame) -> pd.DataFrame:
        """Group print data by report keys and attach BU mapping."""
        enriched_print_df = self._merge_with_mapping(
            print_df,
            mapping_ppl_caption_bu_df,
            key_columns={"caption": "caption"},
        )
        enriched_print_df = self._merge_with_mapping(
            enriched_print_df,
            mapping_publication_df,
            key_columns={"pub_name": "pub_name"},
        )
        print_grouped = self._group_by_key(
            enriched_print_df,
            key_columns=self.PRINT_GROUP_KEYS,
        )
        print_grouped = self._normalize_datetime_column(print_grouped, "finalschdt")

        for new_col, offset in self.WINDOW_MAPPER.items():
            print_grouped[new_col] = print_grouped["finalschdt"] + offset

        self._display("print_grouped first 15", print_grouped, n=15)
        return print_grouped.copy()

    def _build_opportunity_aggregate(self, df: pd.DataFrame, mapping_ppl_caption_bu_df: pd.DataFrame) -> pd.DataFrame:
        """Map PPL to caption and aggregate opportunities by reporting keys."""
        enriched_df = self._merge_with_mapping(
            df,
            mapping_ppl_caption_bu_df,
            key_columns={"ppl": "ppl"},
        )
        grouped_df = self._aggregate_by_key(
            enriched_df,
            key_columns=self.OPPORTUNITY_GROUP_KEYS,
            agg_column=self.OPPORTUNITY_AGG_COLUMN,
        )
        grouped_df = grouped_df.rename(columns={"event_date": "finalschdt"})
        return self._normalize_datetime_column(grouped_df, "finalschdt")

    def _build_report(self, print_grouped_bu: pd.DataFrame, ev: pd.DataFrame, pv: pd.DataFrame) -> pd.DataFrame:
        """Join print, EV, and PV aggregates into final report shape."""
        report = print_grouped_bu.copy()
        window_cols: list[str] = [
            f"ev_enquery_count_{dt_col}" for dt_col in self.WINDOW_MAPPER.keys()
        ] + [
            f"pv_enquery_count_{dt_col}" for dt_col in self.WINDOW_MAPPER.keys()
        ]

        for dt_col in self.WINDOW_MAPPER:
            ev_enquery_col = f"ev_enquery_count_{dt_col}"
            pv_enquery_col = f"pv_enquery_count_{dt_col}"

            ev_slice = ev[self.REPORT_JOIN_KEYS + ["finalschdt", "total_gf_opportunity_created"]].rename(
                columns={
                    "finalschdt": dt_col,
                    "total_gf_opportunity_created": ev_enquery_col,
                }
            )
            pv_slice = pv[self.REPORT_JOIN_KEYS + ["finalschdt", "total_gf_opportunity_created"]].rename(
                columns={
                    "finalschdt": dt_col,
                    "total_gf_opportunity_created": pv_enquery_col,
                }
            )

            report = pd.merge(
                report,
                ev_slice,
                how="left",
                on=self.REPORT_JOIN_KEYS + [dt_col],
            )

            report = pd.merge(
                report,
                pv_slice,
                how="left",
                on=self.REPORT_JOIN_KEYS + [dt_col],
            )

        report = report[self.INTERMEDIATE_REPORT_COLUMNS + window_cols]
        report = report.rename(columns={"finalschdt": "date", "pub_name": "publication original"})
        return report[self.REPORT_BASE_OUTPUT_COLUMNS + window_cols]

    def _group_by_key(self, df: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
        """Return grouped DataFrame with one row per key combination and row count."""
        if df is None:
            raise ValueError("df must not be None.")
        not_present_keys = [col for col in key_columns if col not in df.columns]
        if not_present_keys:
            raise ValueError(f"Key column(s) {not_present_keys} not found in DataFrame columns.")

        return (
            df.groupby(key_columns, as_index=False)
            .size()
            .rename(columns={"size": "row_count"})
        )

    def _aggregate_by_key(self, df: pd.DataFrame, key_columns: list[str], agg_column: str) -> pd.DataFrame:
        """Return aggregated DataFrame with sum of agg_column for each key combination."""
        if df is None:
            raise ValueError("df must not be None.")
        if not key_columns:
            raise ValueError("key_columns must not be empty.")
        if agg_column not in df.columns:
            raise ValueError(f"agg_column '{agg_column}' not found in DataFrame columns.")

        return (
            df.groupby(key_columns, as_index=False)
            .agg({agg_column: "sum"})
            .rename(columns={agg_column: f"total_{agg_column}"})
        )

    def _merge_with_mapping(self, df: pd.DataFrame, mapping_df: pd.DataFrame, key_columns: dict[str, str]) -> pd.DataFrame:
        """Merge the DataFrame with mapping DataFrame on key columns."""
        if df is None:
            raise ValueError("df must not be None.")
        if mapping_df is None:
            raise ValueError("mapping_df must not be None.")
        if not key_columns:
            raise ValueError("key_columns must not be empty.")

        return df.merge(
            mapping_df, 
            left_on=list(key_columns.keys()),
            right_on=list(key_columns.values()),
            how="left"
        )

    def _normalize_datetime_column(self, df: pd.DataFrame, column_name: str) -> pd.DataFrame:
        """Ensure the provided column is datetime for safe date arithmetic and joins."""
        if column_name not in df.columns:
            raise ValueError(f"Column '{column_name}' not found in DataFrame columns.")

        normalized_df = df.copy()
        normalized_df[column_name] = pd.to_datetime(normalized_df[column_name], errors="coerce")
        return normalized_df

    def _display(self, name: str, df: pd.DataFrame, n: int = 5) -> None:
        """Log a preview of the DataFrame with its name."""
        options = ( "display.max_columns", None, "display.width", None, "display.max_colwidth", None)
        with pd.option_context(*options):
            logger.info("DataFrame preview (%s):\n%s", name, df.head(n).to_string(index=False))



@dataclass(slots=True)
class ReportGenerator:
    """Orchestrate report generation by passing combined datasets to transformer."""

    print_df: pd.DataFrame
    ev_df: pd.DataFrame
    contract_df: pd.DataFrame
    start_date: str
    end_date: str
    mapping_loader: GCSCSVDataLoader | None = None
    key_column: str | list[str] = "pub_name"
    date_column: str = "finalschdt"

    def __post_init__(self) -> None:
        """Validate inputs for report generation."""
        if self.print_df is None:
            raise ValueError("print_df must not be None.")
        if self.ev_df is None:
            raise ValueError("ev_df must not be None.")
        if self.contract_df is None:
            raise ValueError("contract_df must not be None.")
        if not self.start_date.strip():
            raise ValueError("start_date must not be empty.")
        if not self.end_date.strip():
            raise ValueError("end_date must not be empty.")

    def generate_report(self) -> pd.DataFrame:
        """Generate output by passing combined dataframes to the transformer."""
        transformer = ReportAggregationTransformer(
            start_date=self.start_date,
            end_date=self.end_date,
            key_column=self.key_column,
            date_column=self.date_column,
            mapping_loader=self.mapping_loader,
        )
        return transformer.transform(
            print_df=self.print_df,
            ev_df=self.ev_df,
            contract_df=self.contract_df,
        )