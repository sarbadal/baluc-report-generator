"""Storage abstraction and GCS implementation for generated reports."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
import json
import logging
from time import perf_counter

from google.api_core.retry import Retry
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY

from app.services.storage_client_provider import GCSStorageClientProvider


logger = logging.getLogger(__name__)


class ReportStorageRepository(ABC):
    """Abstract repository for report metadata and CSV artifact storage."""

    @abstractmethod
    def load_metadata(self) -> list[dict[str, str | None]]:
        """Load report metadata entries from storage."""

    @abstractmethod
    def save_metadata(self, metadata: list[dict[str, str | None]]) -> None:
        """Persist report metadata entries to storage."""

    @abstractmethod
    def upload_csv(self, object_name: str, content: bytes) -> None:
        """Upload generated CSV content to storage."""

    @abstractmethod
    def download_csv(self, object_name: str) -> bytes:
        """Download generated CSV content from storage."""

    @abstractmethod
    def delete_csv(self, object_name: str) -> None:
        """Delete generated CSV object from storage if it exists."""


@dataclass(slots=True)
class GCSReportStorageRepository(ReportStorageRepository):
    """Google Cloud Storage implementation for report artifacts and metadata."""

    storage_client_provider: GCSStorageClientProvider
    bucket_name: str
    metadata_object_name: str = "reports/report_history.json"
    gcs_upload_timeout_seconds: float = 300.0
    gcs_upload_retry_deadline_seconds: float = 600.0

    def __post_init__(self) -> None:
        """Validate required repository configuration."""
        if self.storage_client_provider is None:
            raise ValueError("storage_client_provider must not be None.")
        if not self.bucket_name.strip():
            raise ValueError("bucket_name must not be empty.")
        if not self.metadata_object_name.strip():
            raise ValueError("metadata_object_name must not be empty.")
        if self.gcs_upload_timeout_seconds <= 0:
            raise ValueError("gcs_upload_timeout_seconds must be greater than 0.")
        if self.gcs_upload_retry_deadline_seconds <= 0:
            raise ValueError("gcs_upload_retry_deadline_seconds must be greater than 0.")

    def _upload_retry_policy(self) -> Retry:
        """Build a retry policy for upload operations with an explicit deadline."""
        return DEFAULT_RETRY.with_deadline(self.gcs_upload_retry_deadline_seconds)

    def load_metadata(self) -> list[dict[str, str | None]]:
        """Load metadata JSON from GCS; return empty list when missing."""
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(self.metadata_object_name)
        if not blob.exists(client):
            return []

        payload = blob.download_as_text(encoding="utf-8")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []

        normalized: list[dict[str, str | None]] = []
        for item in data:
            if isinstance(item, dict):
                normalized.append(item)
        return normalized

    def save_metadata(self, metadata: list[dict[str, str | None]]) -> None:
        """Save metadata JSON to GCS."""
        started_at = perf_counter()
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(self.metadata_object_name)
        payload = json.dumps(metadata, indent=2)
        blob.upload_from_string(
            payload,
            content_type="application/json",
            timeout=self.gcs_upload_timeout_seconds,
            retry=self._upload_retry_policy(),
        )
        logger.info(
            "Saved report metadata to GCS in %.2fs: bucket=%s object=%s entries=%d bytes=%d",
            perf_counter() - started_at,
            self.bucket_name.strip(),
            self.metadata_object_name,
            len(metadata),
            len(payload.encode("utf-8")),
        )

    def upload_csv(self, object_name: str, content: bytes) -> None:
        """Upload generated CSV bytes to GCS."""
        started_at = perf_counter()
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        blob.upload_from_string(
            content,
            content_type="text/csv",
            timeout=self.gcs_upload_timeout_seconds,
            retry=self._upload_retry_policy(),
            if_generation_match=0,
        )
        logger.info(
            "Uploaded report CSV to GCS in %.2fs: bucket=%s object=%s bytes=%d",
            perf_counter() - started_at,
            self.bucket_name.strip(),
            object_name,
            len(content),
        )

    def download_csv(self, object_name: str) -> bytes:
        """Download generated CSV bytes from GCS."""
        started_at = perf_counter()
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        if not blob.exists(client):
            raise FileNotFoundError(f"CSV object not found: {object_name}")
        content = blob.download_as_bytes()
        logger.info(
            "Downloaded report CSV from GCS in %.2fs: bucket=%s object=%s bytes=%d",
            perf_counter() - started_at,
            self.bucket_name.strip(),
            object_name,
            len(content),
        )
        return content

    def delete_csv(self, object_name: str) -> None:
        """Delete CSV object from GCS when it exists."""
        started_at = perf_counter()
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        if blob.exists(client):
            blob.delete()
            logger.info(
                "Deleted report CSV from GCS in %.2fs: bucket=%s object=%s",
                perf_counter() - started_at,
                self.bucket_name.strip(),
                object_name,
            )