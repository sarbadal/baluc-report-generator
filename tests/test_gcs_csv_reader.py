"""Manual integration script for reading CSV data from GCS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.auth.exceptions import TransportError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.services import GCSCSVReader, GCSStorageClientProvider


def run_manual_gcs_csv_read() -> int:
    """Run a manual CSV read from GCS and print useful diagnostics."""
    bucket_name = os.getenv("TEST_GCS_BUCKET_NAME", "baluc").strip()
    object_prefix = os.getenv("TEST_GCS_OBJECT_PREFIX", "ev/2026/07").strip().strip("/")
    csv_file_name = os.getenv("TEST_GCS_CSV_FILE_NAME", "ev_dump_20260704.csv").strip()

    blob_name = (
        f"{object_prefix}/{csv_file_name}"
        if object_prefix
        else csv_file_name
    )

    if not bucket_name or not csv_file_name:
        print("Manual test not executed.")
        print("Set TEST_GCS_BUCKET_NAME and TEST_GCS_CSV_FILE_NAME first.")
        return 1

    try:
        provider = GCSStorageClientProvider()
        client = provider.get_client()
        reader = GCSCSVReader(client=client)
        resolved_bucket = reader.find_bucket_by_prefix(bucket_name)
        actual = reader.read_csv(bucket_name, blob_name)
    except (DefaultCredentialsError, TransportError, GoogleAPIError, FileNotFoundError, ValueError) as exc:
        print(f"Manual test failed: {exc}")
        return 1

    print(f"Resolved bucket name: {resolved_bucket.name}")
    print(f"Resolved object path: {blob_name}")
    print(f"Sample of CSV data read from GCS ({len(actual)} rows):")
    print(actual.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_manual_gcs_csv_read())
