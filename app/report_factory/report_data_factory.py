"""Reusable report factory for discovery, download, and data preparation."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from app.services import GCSCSVDataLoader
from app.services import GCSCSVDiscoveryRequest
from app.services import GCSCSVDiscoveryService
from app.services import GCSCSVLoadResult
from app.services import GCSStorageClientProvider


@dataclass(slots=True)
class ReportDataFactory:
    """Coordinate report file discovery and CSV loading into one dataset."""

    storage_client_provider: GCSStorageClientProvider
    bucket_prefix: str
    start_date: str
    end_date: str
    report_type: str
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
        if not self.report_type.strip():
            raise ValueError("report_type must not be empty.")

    def build_report_data(self) -> GCSCSVLoadResult:
        """Discover matching report files and load them into one DataFrame."""
        request_payload = GCSCSVDiscoveryRequest(
            bucket_name_prefix=self.bucket_prefix,
            start_date=self.start_date,
            end_date=self.end_date,
            file_type=self.report_type,
        )

        client = self.storage_client_provider.get_client()
        discovery_service = GCSCSVDiscoveryService(client=client)
        data_loader = GCSCSVDataLoader(client=client)

        discovered_paths = discovery_service.find_matching_blob_paths(request=request_payload)
        return data_loader.load_blob_paths(discovered_paths, **self.read_csv_kwargs)
