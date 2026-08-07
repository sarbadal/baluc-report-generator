"""Background report job management with persistent metadata and GCS artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
import threading
import uuid

from app.report_factory.report_data_factory import ReportDataFactory
from app.report_factory.report_generator import ReportGenerator
from app.services import GCSStorageClientProvider
from app.services import ReportStorageRepository


@dataclass(slots=True)
class ReportJobManager:
    """Manage asynchronous report-generation jobs and downloadable CSV artifacts."""

    storage_client_provider: GCSStorageClientProvider
    storage_repository: ReportStorageRepository
    reports_prefix: str = "reports/generated"
    history_limit: int = 100
    retention_days: int = 30

    _lock: threading.RLock = field(init=False, repr=False)
    _active_threads: dict[str, threading.Thread] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )

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

        self._lock = threading.RLock()
        self._active_threads = {}

    def submit_job(self, bucket_prefix: str, start_date: str, end_date: str, report_type: str) -> str:
        """Create and enqueue a background report generation job."""
        report_id = str(uuid.uuid4())
        now = self._now_iso()

        job = {
            "report_id": report_id,
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "requested_at": now,
            "updated_at": now,
            "status": "Generating",
            "csv_object_name": None,
            "download_object_name": None,
            "error": None,
        }

        with self._lock:
            history = self._read_history_unlocked()
            history.insert(0, job)
            history, removed_objects = self._apply_retention_unlocked(history)
            self._write_history_unlocked(history)
            self._delete_csv_objects_unlocked(removed_objects)

            worker = threading.Thread(
                target=self._run_job,
                args=(report_id, bucket_prefix, start_date, end_date, report_type),
                name=f"report-job-{report_id[:8]}",
                daemon=True,
            )
            self._active_threads[report_id] = worker
            worker.start()

        return report_id

    def list_recent_jobs(self, limit: int = 5) -> list[dict[str, str | None]]:
        """Return most recent jobs from metadata store."""
        with self._lock:
            try:
                history = self._read_history_unlocked()
            except Exception:
                return []
        return history[:limit]

    def get_download_file(self, report_id: str) -> tuple[str, bytes] | None:
        """Return filename and CSV bytes for a completed report, if available."""
        with self._lock:
            try:
                history = self._read_history_unlocked()
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

    def _run_job(self, report_id: str, bucket_prefix: str, start_date: str, end_date: str, report_type: str) -> None:
        """Execute report generation pipeline and persist result artifacts."""
        try:
            report_factory = ReportDataFactory(
                storage_client_provider=self.storage_client_provider,
                bucket_prefix=bucket_prefix,
                start_date=start_date,
                end_date=end_date,
                report_type=report_type,
            )
            load_result = report_factory.build_report_data()

            report_generator = ReportGenerator(
                dataframe=load_result.combined_dataframe,
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
            )
            report_dataframe = report_generator.generate_report()

            filename = self._build_download_filename(
                report_id=report_id,
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
            )
            object_name = f"{self.reports_prefix.strip().strip('/')}/{filename}"
            csv_payload = report_dataframe.to_csv(index=False).encode("utf-8")
            self.storage_repository.upload_csv(object_name=object_name, content=csv_payload)

            self._update_job(
                report_id,
                {
                    "status": "Completed",
                    "csv_object_name": object_name,
                    "download_object_name": object_name,
                    "error": None,
                },
            )
        except Exception as exc:
            self._update_job(
                report_id,
                {
                    "status": "Failed",
                    "csv_object_name": None,
                    "download_object_name": None,
                    "error": str(exc),
                },
            )
        finally:
            with self._lock:
                self._active_threads.pop(report_id, None)

    def _update_job(self, report_id: str, fields: dict[str, str | None]) -> None:
        """Update one job in metadata and enforce retention after changes."""
        with self._lock:
            history = self._read_history_unlocked()
            for job in history:
                if job.get("report_id") != report_id:
                    continue
                job.update(fields)
                job["updated_at"] = self._now_iso()
                break

            history, removed_objects = self._apply_retention_unlocked(history)
            self._write_history_unlocked(history)
            self._delete_csv_objects_unlocked(removed_objects)

    def _read_history_unlocked(self) -> list[dict[str, str | None]]:
        """Read metadata history from repository and normalize entry types."""
        data = self.storage_repository.load_metadata()
        normalized: list[dict[str, str | None]] = []
        for entry in data:
            if isinstance(entry, dict):
                normalized.append(entry)
        return normalized

    def _write_history_unlocked(self, history: list[dict[str, str | None]]) -> None:
        """Persist normalized metadata history to repository."""
        self.storage_repository.save_metadata(history)

    def _apply_retention_unlocked(self, history: list[dict[str, str | None]]) -> tuple[list[dict[str, str | None]], set[str]]:
        """Apply retention and return kept entries plus removed CSV object names."""
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        kept: list[dict[str, str | None]] = []
        removed_objects: set[str] = set()

        for index, job in enumerate(history):
            status = str(job.get("status") or "")
            keep_by_limit = index < self.history_limit
            keep_by_age = self._job_is_within_cutoff(job, cutoff)
            keep_generating = status == "Generating"

            if keep_generating or (keep_by_limit and keep_by_age):
                kept.append(job)
                continue

            object_name = job.get("csv_object_name")
            if isinstance(object_name, str) and object_name:
                removed_objects.add(object_name)

        referenced_objects = {
            str(job.get("csv_object_name"))
            for job in kept
            if isinstance(job.get("csv_object_name"), str) and job.get("csv_object_name")
        }
        removed_objects = {name for name in removed_objects if name not in referenced_objects}

        return kept, removed_objects

    def _delete_csv_objects_unlocked(self, object_names: set[str]) -> None:
        """Delete removed CSV objects from repository storage backend."""
        for object_name in object_names:
            self.storage_repository.delete_csv(object_name)

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

        if created_at.tzinfo is not None:
            created_at = created_at.astimezone().replace(tzinfo=None)
        return created_at >= cutoff

    @staticmethod
    def _build_download_filename(report_id: str, report_type: str, start_date: str, end_date: str) -> str:
        """Build safe file name for generated CSV artifacts."""
        normalized_type = "".join(
            char
            for char in report_type.strip().lower()
            if char.isalnum() or char == "_"
        )
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        return f"{normalized_type}_{start}_{end}_{report_id[:8]}.csv"

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC timestamp in ISO format."""
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
