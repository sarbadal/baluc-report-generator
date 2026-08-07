"""Factory/provider for Google Cloud Storage client instances."""

from __future__ import annotations

import json
import os

from google.cloud import storage
from google.oauth2 import service_account


class GCSStorageClientProvider:
    """Provide configured Google Cloud Storage clients."""

    def __init__(self, project: str | None = None) -> None:
        """Initialize provider with an optional GCP project override."""
        self.project = project

    def get_client(self) -> storage.Client:
        """Return a Google Cloud Storage client instance.

        If ``GOOGLE_AUTH_KEY_JSON`` is set, it is parsed as service account
        JSON content or treated as a file path to a service account JSON file.
        """
        key_source = os.getenv("GOOGLE_AUTH_KEY_JSON", "").strip()
        if key_source:
            credentials, resolved_project = self._build_credentials_from_env_value(
                key_source
            )
            project = self.project or resolved_project
            return storage.Client(project=project, credentials=credentials)

        return storage.Client(project=self.project)

    def _build_credentials_from_env_value(self, key_source: str) -> tuple[service_account.Credentials, str | None]:
        """Build credentials from raw JSON content or a JSON file path."""
        try:
            key_info = json.loads(key_source)
            credentials = service_account.Credentials.from_service_account_info(
                key_info
            )
            return credentials, key_info.get("project_id")
        except json.JSONDecodeError:
            pass

        if os.path.isfile(key_source):
            try:
                with open(key_source, "r", encoding="utf-8") as file:
                    key_info = json.load(file)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "GOOGLE_AUTH_KEY_JSON points to a file with invalid JSON."
                ) from exc

            credentials = service_account.Credentials.from_service_account_file(
                key_source
            )
            return credentials, key_info.get("project_id")

        raise ValueError(
            "GOOGLE_AUTH_KEY_JSON must be valid JSON content or a valid JSON file path."
        )