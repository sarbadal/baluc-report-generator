"""Storage abstraction and GCS implementation for generated reports."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
import json

from google.cloud import storage

from app.services.storage_client_provider import GCSStorageClientProvider


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

    def __post_init__(self) -> None:
        """Validate required repository configuration."""
        if self.storage_client_provider is None:
            raise ValueError("storage_client_provider must not be None.")
        if not self.bucket_name.strip():
            raise ValueError("bucket_name must not be empty.")
        if not self.metadata_object_name.strip():
            raise ValueError("metadata_object_name must not be empty.")

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
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(self.metadata_object_name)
        payload = json.dumps(metadata, indent=2)
        blob.upload_from_string(payload, content_type="application/json")

    def upload_csv(self, object_name: str, content: bytes) -> None:
        """Upload generated CSV bytes to GCS."""
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        blob.upload_from_string(content, content_type="text/csv")

    def download_csv(self, object_name: str) -> bytes:
        """Download generated CSV bytes from GCS."""
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        if not blob.exists(client):
            raise FileNotFoundError(f"CSV object not found: {object_name}")
        return blob.download_as_bytes()

    def delete_csv(self, object_name: str) -> None:
        """Delete CSV object from GCS when it exists."""
        client = self.storage_client_provider.get_client()
        blob = client.bucket(self.bucket_name.strip()).blob(object_name)
        if blob.exists(client):
            blob.delete()