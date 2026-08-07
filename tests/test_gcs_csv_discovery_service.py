"""Manual integration script for GCS CSV discovery service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.auth.exceptions import TransportError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.services import GCSCSVDiscoveryService, GCSStorageClientProvider
from app.services.gcs_csv_discovery_service import GCSCSVDiscoveryRequest


def run_manual_gcs_csv_discovery(file_type: str = "CONTACT", start_date: str = "2026-06-01", end_date: str = "2026-07-03") -> int:
    """Discover CSV files in GCS for a selected date range and file type."""
    bucket_name = os.getenv("TEST_GCS_BUCKET_NAME", "baluc").strip()
    file_type = os.getenv("TEST_GCS_FILE_TYPE", file_type).strip().upper()
    start_date = os.getenv("TEST_GCS_START_DATE", start_date).strip()
    end_date = os.getenv("TEST_GCS_END_DATE", end_date).strip()

    if not bucket_name:
        print("Manual discovery not executed.")
        print("Set TEST_GCS_BUCKET_NAME first.")
        return 1

    try:
        provider = GCSStorageClientProvider()
        client = provider.get_client()
        discovery_service = GCSCSVDiscoveryService(client=client)
        request = GCSCSVDiscoveryRequest(
            bucket_name_prefix=bucket_name,
            start_date=start_date,
            end_date=end_date,
            file_type=file_type,
        )
        matched_paths = discovery_service.find_matching_blob_paths(request=request)
    except (DefaultCredentialsError, TransportError, GoogleAPIError, FileNotFoundError, ValueError) as exc:
        print(f"Manual discovery failed: {exc}")
        return 1

    print("Manual discovery completed.")
    print(f"Bucket prefix: {bucket_name}")
    print(f"File type: {file_type}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Matched files: {len(matched_paths)}")
    for path in matched_paths:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_manual_gcs_csv_discovery("PRINT", "2026-07-01", "2026-07-15"))
