"""Service for loading multiple CSV files from GCS into one DataFrame."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

import pandas as pd
from google.cloud import storage


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
        dataframes: list[pd.DataFrame] = []
        loaded_files: list[str] = []
        failed_files: list[str] = []

        for blob_path in blob_paths:
            try:
                bucket_name, blob_name = self._parse_gs_path(blob_path)
                blob = self.client.bucket(bucket_name).blob(blob_name)
                csv_bytes = blob.download_as_bytes()
                dataframe = pd.read_csv(BytesIO(csv_bytes), **read_csv_kwargs)
                dataframes.append(dataframe)
                loaded_files.append(blob_path)
            except Exception:
                failed_files.append(blob_path)

        if dataframes:
            combined_dataframe = pd.concat(dataframes, ignore_index=True)
        else:
            combined_dataframe = pd.DataFrame()

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

        csv_bytes = blob.download_as_bytes()
        return pd.read_csv(BytesIO(csv_bytes), **read_csv_kwargs)

    @staticmethod
    def _parse_gs_path(path: str) -> tuple[str, str]:
        """Parse a ``gs://bucket/blob`` path into bucket and blob parts."""
        normalized = path.strip()
        match = re.match(r"^gs://([^/]+)/(.+)$", normalized)
        if not match:
            raise ValueError(f"Invalid GCS path: {path}")

        return match.group(1), match.group(2)
