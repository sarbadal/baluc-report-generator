"""Report request manager that triggers external processing and reads stored metadata."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
import json
import logging
from urllib import error
from urllib import request
from zoneinfo import ZoneInfo

from app.services import GCSStorageClientProvider
from app.services import ReportStorageRepository


logger = logging.getLogger(__name__)
IST_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(slots=True)
class ReportJobManager:
    """Trigger external report processing and serve report status/download metadata."""

    storage_client_provider: GCSStorageClientProvider
    storage_repository: ReportStorageRepository
    reports_prefix: str = "reports/generated"
    history_limit: int = 100
    retention_days: int = 30
    trigger_function_url: str = ""
    trigger_timeout_seconds: float = 30.0
    trigger_auth_token: str = ""
    print_key_columns: list[str] = field(
        default_factory=lambda: ["pub_name", "state", "caption"]
    )
    print_date_column: str = "finalschdt"
    print_kpi_column: str | int | float = 0
    ev_join_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "pub_name": "pub_name",
            "state": "state",
            "caption": "caption",
        }
    )
    ev_date_column: str = "finalschdt"
    ev_kpi_column: str = "kpi"
    window_before: int = 2
    window_after: int = 2

    def __post_init__(self) -> None:
        """Validate setup and normalize persisted metadata according to retention."""
        if self.storage_client_provider is None:
            raise ValueError("storage_client_provider must not be None.")
        if self.storage_repository is None:
            raise ValueError("storage_repository must not be None.")
        if not self.reports_prefix.strip():
            raise ValueError("reports_prefix must not be empty.")
        if self.history_limit <= 0:
            raise ValueError("history_limit must be greater than 0.")
        if self.retention_days <= 0:
            raise ValueError("retention_days must be greater than 0.")
        if not self.print_key_columns:
            raise ValueError("print_key_columns must not be empty.")
        if not self.print_date_column.strip():
            raise ValueError("print_date_column must not be empty.")
        if self.window_before < 0 or self.window_after < 0:
            raise ValueError("window_before and window_after must be >= 0.")
        if self.trigger_timeout_seconds <= 0:
            raise ValueError("trigger_timeout_seconds must be greater than 0.")

    def submit_job(self, bucket_prefix: str, start_date: str, end_date: str) -> str:
        """Forward report request to the standalone processor Cloud Function."""
        logger.info(
            "Forwarding report job request: start_date=%s end_date=%s bucket_prefix=%s",
            start_date,
            end_date,
            bucket_prefix,
        )
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            # Keep payload extensible for future request parameters.
            "parameters": {
                "bucket_prefix": bucket_prefix,
            },
        }
        if not self.trigger_function_url.strip():
            raise RuntimeError("REPORT_TRIGGER_FUNCTION_URL is not configured.")
        response_payload = self._post_trigger_payload(payload)
        report_id = str(response_payload.get("report_id", "")).strip()
        if not report_id:
            raise RuntimeError("Trigger function response did not include report_id.")
        return report_id

    def list_recent_jobs(self, limit: int = 5) -> list[dict[str, str | None]]:
        """Return most recent jobs from metadata store."""
        try:
            history = self._read_history()
        except Exception:
            return []
        return history[:limit]

    def get_download_file(self, report_id: str) -> tuple[str, bytes] | None:
        """Return filename and CSV bytes for a completed report, if available."""
        try:
            history = self._read_history()
        except Exception:
            return None

        for job in history:
            if job.get("report_id") != report_id:
                continue
            if job.get("status") != "Completed":
                return None

            object_name = job.get("csv_object_name")
            if not isinstance(object_name, str) or not object_name:
                return None

            try:
                csv_bytes = self.storage_repository.download_csv(object_name)
            except FileNotFoundError:
                return None

            filename = object_name.rsplit("/", maxsplit=1)[-1]
            return filename, csv_bytes

        return None

    def _read_history(self) -> list[dict[str, str | None]]:
        """Read metadata history from repository and normalize entry types."""
        data = self.storage_repository.load_metadata()
        normalized: list[dict[str, str | None]] = []
        for entry in data:
            if isinstance(entry, dict):
                normalized.append(entry)
        if len(normalized) <= self.history_limit:
            return normalized

        cutoff = datetime.now(IST_TZ) - timedelta(days=self.retention_days)
        filtered: list[dict[str, str | None]] = []
        for row in normalized:
            status = str(row.get("status") or "")
            if status in {"Generating", "Processing"} or self._job_is_within_cutoff(row, cutoff):
                filtered.append(row)

        return filtered[: self.history_limit]

    def _post_trigger_payload(self, payload: dict[str, object]) -> dict[str, object]:
        """POST report request payload to the trigger Cloud Function URL."""
        encoded_payload = json.dumps(payload).encode("utf-8")
        http_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.trigger_auth_token.strip():
            http_headers["Authorization"] = f"Bearer {self.trigger_auth_token.strip()}"

        trigger_request = request.Request(
            url=self.trigger_function_url.strip(),
            data=encoded_payload,
            headers=http_headers,
            method="POST",
        )

        try:
            with request.urlopen(trigger_request, timeout=self.trigger_timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                status_code = int(response.status)
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Trigger function HTTP {exc.code}: {error_body}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Trigger function connection failed: {exc.reason}") from exc

        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"Trigger function returned non-success status: {status_code}")

        try:
            parsed_response = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Trigger function returned invalid JSON response.") from exc

        if not isinstance(parsed_response, dict):
            raise RuntimeError("Trigger function response must be a JSON object.")
        return parsed_response

    @staticmethod
    def _job_is_within_cutoff(job: dict[str, str | None], cutoff: datetime) -> bool:
        """Return True when a job timestamp is newer than retention cutoff."""
        requested_at = job.get("requested_at")
        if not isinstance(requested_at, str) or not requested_at:
            return True

        normalized = requested_at.replace("Z", "+00:00")
        try:
            created_at = datetime.fromisoformat(normalized)
        except ValueError:
            return True

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=IST_TZ)
        else:
            created_at = created_at.astimezone(IST_TZ)
        return created_at >= cutoff
