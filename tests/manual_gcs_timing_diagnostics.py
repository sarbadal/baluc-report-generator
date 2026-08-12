"""Manual timing diagnostics for GCS download and pandas parse behavior.

Usage (local):
    python tests/manual_gcs_timing_diagnostics.py

Environment variables:
- TEST_GCS_BUCKET_NAME_PREFIX (default: inventory-baluc)
- TEST_GCS_FILE_TYPE (default: PRINT)
- TEST_GCS_START_DATE (default: 2026-07-01)
- TEST_GCS_END_DATE (default: 2026-07-03)
- TEST_GCS_METADATA_GS_PATH (default: gs://reports-baluc/reports/report_history.json)
"""

from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path
from time import perf_counter

import pandas as pd
from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.auth.exceptions import TransportError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.services import GCSCSVDiscoveryRequest
from app.services import GCSCSVDiscoveryService
from app.services import GCSStorageClientProvider


def _parse_gs_path(gs_path: str) -> tuple[str, str]:
    normalized = gs_path.strip()
    if not normalized.startswith("gs://"):
        raise ValueError(f"Invalid gs path: {gs_path}")

    without_scheme = normalized[len("gs://") :]
    if "/" not in without_scheme:
        raise ValueError(f"Invalid gs path: {gs_path}")

    bucket_name, blob_name = without_scheme.split("/", 1)
    if not bucket_name or not blob_name:
        raise ValueError(f"Invalid gs path: {gs_path}")
    return bucket_name, blob_name


def run_manual_gcs_timing_diagnostics() -> int:
    bucket_prefix = os.getenv("TEST_GCS_BUCKET_NAME_PREFIX", "inventory-baluc").strip()
    file_type = os.getenv("TEST_GCS_FILE_TYPE", "PRINT").strip().upper()
    start_date = os.getenv("TEST_GCS_START_DATE", "2026-07-01").strip()
    end_date = os.getenv("TEST_GCS_END_DATE", "2026-07-03").strip()
    metadata_gs_path = os.getenv(
        "TEST_GCS_METADATA_GS_PATH",
        "gs://reports-baluc/reports/report_history.json",
    ).strip()

    try:
        provider = GCSStorageClientProvider()
        client = provider.get_client()

        print("=== Diagnostic 1: Tiny object download (report_history.json) ===")
        metadata_bucket_name, metadata_blob_name = _parse_gs_path(metadata_gs_path)
        metadata_blob = client.bucket(metadata_bucket_name).blob(metadata_blob_name)

        small_started_at = perf_counter()
        metadata_bytes = metadata_blob.download_as_bytes()
        small_duration = perf_counter() - small_started_at

        print(f"Object: {metadata_gs_path}")
        print(f"Size (bytes): {len(metadata_bytes)}")
        print(f"Download seconds: {small_duration:.3f}")

        print("\n=== Diagnostic 2: One representative CSV (download vs parse) ===")
        discovery = GCSCSVDiscoveryService(client=client)
        request = GCSCSVDiscoveryRequest(
            bucket_name_prefix=bucket_prefix,
            start_date=start_date,
            end_date=end_date,
            file_type=file_type,
        )
        paths = discovery.find_matching_blob_paths(request=request)
        if not paths:
            print("No CSV files matched the supplied criteria.")
            return 1

        csv_path = paths[0]
        csv_bucket_name, csv_blob_name = _parse_gs_path(csv_path)
        csv_blob = client.bucket(csv_bucket_name).blob(csv_blob_name)

        download_started_at = perf_counter()
        csv_bytes = csv_blob.download_as_bytes()
        download_seconds = perf_counter() - download_started_at

        parse_started_at = perf_counter()
        dataframe = pd.read_csv(BytesIO(csv_bytes))
        parse_seconds = perf_counter() - parse_started_at

        print(f"CSV path: {csv_path}")
        print(f"CSV size (bytes): {len(csv_bytes)}")
        print(f"Download seconds: {download_seconds:.3f}")
        print(f"Parse seconds: {parse_seconds:.3f}")
        print(f"Rows: {len(dataframe.index)}  Columns: {len(dataframe.columns)}")

        print("\n=== Suggested Comparison Table ===")
        print("File,Local Download (s),Local Parse (s),Cloud Download (s),Cloud Parse (s)")
        print(f"{csv_blob_name},{download_seconds:.3f},{parse_seconds:.3f},<cloud>,<cloud>")
        return 0
    except (DefaultCredentialsError, TransportError, GoogleAPIError, FileNotFoundError, ValueError) as exc:
        print(f"Diagnostics failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run_manual_gcs_timing_diagnostics())
