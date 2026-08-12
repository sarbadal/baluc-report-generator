"""Service for loading multiple CSV files from GCS into one DataFrame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import logging
import re
from time import perf_counter
from typing import Any

import pandas as pd
from google.cloud import storage


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GCSCSVLoadResult:
    """Outcome of loading one or more CSV files from GCS."""

    discovered_files: list[str]
    loaded_files: list[str]
    failed_files: list[str]
    combined_dataframe: pd.DataFrame


@dataclass(slots=True)
class GCSCSVDataLoader:
    """Download CSV files from GCS and concatenate into one DataFrame."""

    client: storage.Client

    def __post_init__(self) -> None:
        """Validate the injected storage client."""
        if self.client is None:
            raise ValueError("client must not be None.")

    def load_blob_paths(self, blob_paths: list[str], **read_csv_kwargs: Any) -> GCSCSVLoadResult:
        """Load discovered ``gs://`` CSV paths and return a combined DataFrame."""
        run_started_at = perf_counter()
        dataframes: list[pd.DataFrame] = []
        loaded_files: list[str] = []
        failed_files: list[str] = []
        total_download_seconds = 0.0
        total_parse_seconds = 0.0

        for blob_path in blob_paths:
            try:
                bucket_name, blob_name = self._parse_gs_path(blob_path)
                blob = self.client.bucket(bucket_name).blob(blob_name)

                download_started_at_wall = datetime.now().astimezone().isoformat(timespec="seconds")
                download_started_at = perf_counter()
                csv_bytes = blob.download_as_bytes()
                download_ended_at = perf_counter()
                download_ended_at_wall = datetime.now().astimezone().isoformat(timespec="seconds")
                download_duration_seconds = download_ended_at - download_started_at
                total_download_seconds += download_duration_seconds

                parse_started_at = perf_counter()
                dataframe = pd.read_csv(BytesIO(csv_bytes), **read_csv_kwargs)
                parse_duration_seconds = perf_counter() - parse_started_at
                total_parse_seconds += parse_duration_seconds

                dataframes.append(dataframe)
                loaded_files.append(blob_path)
                logger.info(
                    "GCS CSV load succeeded: path=%s object=%s size_bytes=%d download_start=%s download_end=%s download_seconds=%.3f parse_seconds=%.3f rows=%d columns=%d",
                    blob_path,
                    blob_name,
                    len(csv_bytes),
                    download_started_at_wall,
                    download_ended_at_wall,
                    download_duration_seconds,
                    parse_duration_seconds,
                    len(dataframe.index),
                    len(dataframe.columns),
                )
            except Exception:
                failed_files.append(blob_path)
                logger.exception("GCS CSV load failed: path=%s", blob_path)

        concat_started_at = perf_counter()
        if dataframes:
            combined_dataframe = pd.concat(dataframes, ignore_index=True)
        else:
            combined_dataframe = pd.DataFrame()
        concat_duration_seconds = perf_counter() - concat_started_at

        total_duration_seconds = perf_counter() - run_started_at
        logger.info(
            "GCS CSV batch load summary: discovered=%d loaded=%d failed=%d total_download_seconds=%.3f total_parse_seconds=%.3f concat_seconds=%.3f total_seconds=%.3f output_rows=%d output_columns=%d",
            len(blob_paths),
            len(loaded_files),
            len(failed_files),
            total_download_seconds,
            total_parse_seconds,
            concat_duration_seconds,
            total_duration_seconds,
            len(combined_dataframe.index),
            len(combined_dataframe.columns),
        )

        return GCSCSVLoadResult(
            discovered_files=list(blob_paths),
            loaded_files=loaded_files,
            failed_files=failed_files,
            combined_dataframe=combined_dataframe,
        )

    def load_blob_path(self, blob_path: str, **read_csv_kwargs: Any) -> pd.DataFrame:
        """Load a single ``gs://`` CSV path and return a DataFrame.

        Raises:
            ValueError: If the gs path is invalid.
            FileNotFoundError: If the blob does not exist.
        """
        bucket_name, blob_name = self._parse_gs_path(blob_path)
        blob = self.client.bucket(bucket_name).blob(blob_name)
        if not blob.exists(self.client):
            raise FileNotFoundError(f"CSV file was not found at path: {blob_path}")

        download_started_at_wall = datetime.now().astimezone().isoformat(timespec="seconds")
        download_started_at = perf_counter()
        csv_bytes = blob.download_as_bytes()
        download_ended_at = perf_counter()
        download_ended_at_wall = datetime.now().astimezone().isoformat(timespec="seconds")

        parse_started_at = perf_counter()
        dataframe = pd.read_csv(BytesIO(csv_bytes), **read_csv_kwargs)
        parse_duration_seconds = perf_counter() - parse_started_at
        logger.info(
            "Loaded CSV from GCS: path=%s object=%s size_bytes=%d download_start=%s download_end=%s download_seconds=%.3f parse_seconds=%.3f rows=%d columns=%d",
            blob_path,
            blob_name,
            len(csv_bytes),
            download_started_at_wall,
            download_ended_at_wall,
            download_ended_at - download_started_at,
            parse_duration_seconds,
            len(dataframe.index),
            len(dataframe.columns),
        )
        return dataframe

    @staticmethod
    def _parse_gs_path(path: str) -> tuple[str, str]:
        """Parse a ``gs://bucket/blob`` path into bucket and blob parts."""
        normalized = path.strip()
        match = re.match(r"^gs://([^/]+)/(.+)$", normalized)
        if not match:
            raise ValueError(f"Invalid GCS path: {path}")

        return match.group(1), match.group(2)
