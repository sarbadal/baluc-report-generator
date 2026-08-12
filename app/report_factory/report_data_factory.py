"""Reusable report factory for discovery, download, and data preparation."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import logging
from time import perf_counter
from typing import Any

import pandas as pd

from app.services import GCSCSVDataLoader
from app.services import GCSCSVDiscoveryRequest
from app.services import GCSCSVDiscoveryService
from app.services import GCSCSVLoadResult
from app.services import GCSStorageClientProvider
from app.services import SupportedCSVFileType


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CombinedReportDataFrames:
    """Combined DataFrames for print, ev, and contract datasets."""

    print_df: pd.DataFrame
    ev_df: pd.DataFrame
    contract_df: pd.DataFrame


@dataclass(slots=True)
class ReportDataFactory:
    """Coordinate report file discovery and CSV loading into one dataset."""

    storage_client_provider: GCSStorageClientProvider
    bucket_prefix: str
    start_date: str
    end_date: str
    read_csv_kwargs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate required factory inputs before running report loading."""
        if self.storage_client_provider is None:
            raise ValueError("storage_client_provider must not be None.")

        if not self.bucket_prefix.strip():
            raise ValueError("bucket_prefix must not be empty.")
        if not self.start_date.strip():
            raise ValueError("start_date must not be empty.")
        if not self.end_date.strip():
            raise ValueError("end_date must not be empty.")

    def build_report_data(self) -> GCSCSVLoadResult:
        """Discover matching Print files and load them into one DataFrame."""
        return self._load_for_file_type(SupportedCSVFileType.PRINT)

    def build_ev_data(self) -> GCSCSVLoadResult:
        """Discover matching EV files and load them into one DataFrame."""
        return self._load_for_file_type(SupportedCSVFileType.EV)

    def build_contract_data(self) -> GCSCSVLoadResult:
        """Discover matching CONTACT files and load them into one DataFrame."""
        return self._load_for_file_type(SupportedCSVFileType.CONTACT)

    def build_combined_dataframes(self) -> CombinedReportDataFrames:
        """Return combined Print, EV, and Contract DataFrames for one date range."""
        started_at = perf_counter()
        logger.info(
            "ReportDataFactory build started: bucket_prefix=%s start_date=%s end_date=%s",
            self.bucket_prefix,
            self.start_date,
            self.end_date,
        )

        print_result = self.build_report_data()
        ev_result = self.build_ev_data()
        contract_result = self.build_contract_data()

        elapsed_seconds = perf_counter() - started_at
        logger.info(
            "ReportDataFactory build completed in %.2fs: print_rows=%d ev_rows=%d contract_rows=%d",
            elapsed_seconds,
            len(print_result.combined_dataframe.index),
            len(ev_result.combined_dataframe.index),
            len(contract_result.combined_dataframe.index),
        )

        return CombinedReportDataFrames(
            print_df=print_result.combined_dataframe,
            ev_df=ev_result.combined_dataframe,
            contract_df=contract_result.combined_dataframe,
        )

    def load_mapping_dataframe(self, gs_path: str, **read_csv_kwargs: Any) -> pd.DataFrame:
        """Load one mapping CSV from a ``gs://`` path and return a DataFrame."""
        path = gs_path.strip()
        if not path:
            raise ValueError("gs_path must not be empty.")

        client = self.storage_client_provider.get_client()
        data_loader = GCSCSVDataLoader(client=client)

        options = dict(self.read_csv_kwargs)
        options.update(read_csv_kwargs)
        return data_loader.load_blob_path(path, **options)

    def _load_for_file_type(self, file_type: SupportedCSVFileType) -> GCSCSVLoadResult:
        """Discover matching files for one file type and load them into a DataFrame."""
        started_at = perf_counter()
        request_payload = GCSCSVDiscoveryRequest(
            bucket_name_prefix=self.bucket_prefix,
            start_date=self.start_date,
            end_date=self.end_date,
            file_type=file_type,
        )

        client = self.storage_client_provider.get_client()
        discovery_service = GCSCSVDiscoveryService(client=client)
        data_loader = GCSCSVDataLoader(client=client)

        discovered_paths = discovery_service.find_matching_blob_paths(request=request_payload)
        logger.info(
            "Discovered %d %s file(s) for date range %s to %s",
            len(discovered_paths),
            file_type.value,
            self.start_date,
            self.end_date,
        )

        load_started_at = perf_counter()
        result = data_loader.load_blob_paths(discovered_paths, **self.read_csv_kwargs)
        load_elapsed_seconds = perf_counter() - load_started_at
        total_elapsed_seconds = perf_counter() - started_at

        logger.info(
            "Loaded %s data in %.2fs (total %.2fs): files=%d rows=%d",
            file_type.value,
            load_elapsed_seconds,
            total_elapsed_seconds,
            len(discovered_paths),
            len(result.combined_dataframe.index),
        )
        return result
