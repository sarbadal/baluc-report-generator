"""Service for reading CSV files from Google Cloud Storage."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd
from google.cloud import storage
from google.cloud.storage import Bucket


@dataclass(slots=True)
class GCSCSVReader:
    """Read CSV files from GCS using a bucket-name prefix and file path."""

    client: storage.Client

    def __post_init__(self) -> None:
        """Validate injected dependencies after dataclass initialization."""
        if self.client is None:
            raise ValueError("client must not be None.")

    def find_bucket_by_prefix(self, bucket_name_prefix: str) -> Bucket:
        """Return the first bucket whose name starts with the provided prefix."""
        prefix = bucket_name_prefix.strip()
        if not prefix:
            raise ValueError("bucket_name_prefix must not be empty.")

        buckets = list(self.client.list_buckets(prefix=prefix, max_results=1))
        if not buckets:
            raise FileNotFoundError(
                f"No GCS bucket found with prefix '{bucket_name_prefix}'."
            )

        return buckets[0]

    def read_csv(self, bucket_name_prefix: str, csv_file_name: str, **read_csv_kwargs: Any) -> pd.DataFrame:
        """Read a CSV blob into a DataFrame using bucket prefix and blob name.

        Args:
            bucket_name_prefix: Prefix used to find the target bucket.
            csv_file_name: Blob path/name inside the resolved bucket.
            **read_csv_kwargs: Optional kwargs forwarded to ``pandas.read_csv``.
        """
        blob_name = csv_file_name.strip()
        if not blob_name:
            raise ValueError("csv_file_name must not be empty.")

        bucket = self.find_bucket_by_prefix(bucket_name_prefix)
        blob = bucket.blob(blob_name)

        if not blob.exists(self.client):
            raise FileNotFoundError(
                f"CSV file '{csv_file_name}' was not found in bucket '{bucket.name}'."
            )

        csv_bytes = blob.download_as_bytes()
        return pd.read_csv(BytesIO(csv_bytes), **read_csv_kwargs)