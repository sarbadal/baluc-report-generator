"""Service for discovering CSV files in Google Cloud Storage by date range."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from enum import Enum
import re
from typing import Iterable

from google.cloud import storage
from google.cloud.storage import Blob
from google.cloud.storage import Bucket

from app.config import GCS_FILE_DISCOVERY_RULES


@dataclass(frozen=True, slots=True)
class GCSFileTypeRule:
    """Naming and folder configuration for one supported CSV file type."""

    folder: str
    filename_pattern: str


@dataclass(frozen=True, slots=True)
class GCSCSVDiscoveryRequest:
    """Input payload for discovering matching CSV files in GCS."""

    bucket_name_prefix: str
    start_date: date | datetime | str
    end_date: date | datetime | str
    file_type: SupportedCSVFileType | str


class SupportedCSVFileType(str, Enum):
    """Supported file types for CSV discovery in GCS."""

    EV = "EV"
    PRINT = "PRINT"
    CONTACT = "CONTACT"


@dataclass(slots=True)
class GCSCSVDiscoveryService:
    """Discover CSV blobs in GCS that match date range and file-type criteria."""

    client: storage.Client
    file_type_rules: dict[SupportedCSVFileType, GCSFileTypeRule] | None = None

    def __post_init__(self) -> None:
        """Validate injected dependencies and initialize default rules."""
        if self.client is None:
            raise ValueError("client must not be None.")

        if self.file_type_rules is None:
            self.file_type_rules = self._build_default_rules()

    def find_matching_blob_paths(self, request: GCSCSVDiscoveryRequest) -> list[str]:
        """Return fully qualified ``gs://`` paths for matching CSV blobs."""
        blobs = self.find_matching_blobs(request=request)
        return [f"gs://{blob.bucket.name}/{blob.name}" for blob in blobs]

    def find_matching_blobs(self, request: GCSCSVDiscoveryRequest) -> list[Blob]:
        """Return matching GCS blob objects for the requested criteria."""
        prefix = request.bucket_name_prefix.strip()
        if not prefix:
            raise ValueError("bucket_name_prefix must not be empty.")

        start = self._normalize_date(request.start_date)
        end = self._normalize_date(request.end_date)
        if start > end:
            raise ValueError("start_date must be on or before end_date.")

        resolved_file_type = self._normalize_file_type(request.file_type)
        rule = self._get_rule(resolved_file_type)
        patterns = [
            re.compile(pattern, flags=re.IGNORECASE)
            for pattern in self._get_filename_patterns(
                file_type=resolved_file_type,
                primary_pattern=rule.filename_pattern,
            )
        ]

        bucket = self._find_bucket_by_prefix(prefix)
        blobs: list[Blob] = []
        seen_blob_names: set[str] = set()

        for folder in self._get_folder_candidates(file_type=resolved_file_type, primary_folder=rule.folder):
            for month_prefix in self._iter_month_prefixes(folder, start, end):
                for blob in bucket.list_blobs(prefix=month_prefix):
                    if blob.name in seen_blob_names:
                        continue

                    blob_file_name = blob.name.rsplit("/", maxsplit=1)[-1]
                    for pattern in patterns:
                        match = pattern.match(blob_file_name)
                        if not match:
                            continue

                        blob_date = datetime.strptime(match.group(1), "%Y%m%d").date()
                        if start <= blob_date <= end:
                            blobs.append(blob)
                            seen_blob_names.add(blob.name)
                        break

        blobs.sort(key=lambda item: item.name)
        return blobs

    def _find_bucket_by_prefix(self, bucket_name_prefix: str) -> Bucket:
        """Return the first bucket whose name starts with the provided prefix."""
        buckets = list(self.client.list_buckets(prefix=bucket_name_prefix, max_results=1))
        if not buckets:
            raise FileNotFoundError(
                f"No GCS bucket found with prefix '{bucket_name_prefix}'."
            )

        return buckets[0]

    def _get_rule(self, file_type: SupportedCSVFileType) -> GCSFileTypeRule:
        """Return discovery rule for the requested file type."""
        if self.file_type_rules is None:
            raise ValueError("file_type_rules must not be None.")

        try:
            return self.file_type_rules[file_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported file type: {file_type.value}") from exc

    @staticmethod
    def _normalize_date(value: date | datetime | str) -> date:
        """Normalize accepted date inputs into a ``datetime.date`` value."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            for fmt in ("%Y-%m-%d", "%Y%m%d"):
                try:
                    return datetime.strptime(normalized, fmt).date()
                except ValueError:
                    continue

        raise ValueError("Dates must be date/datetime or strings in YYYY-MM-DD or YYYYMMDD format.")

    @staticmethod
    def _normalize_file_type(file_type: SupportedCSVFileType | str) -> SupportedCSVFileType:
        """Normalize enum or string file-type inputs to enum values."""
        if isinstance(file_type, SupportedCSVFileType):
            return file_type
        if isinstance(file_type, str):
            normalized = file_type.strip().upper()
            try:
                return SupportedCSVFileType(normalized)
            except ValueError as exc:
                raise ValueError(f"Unsupported file type: {file_type}") from exc

        raise ValueError("file_type must be a SupportedCSVFileType value or matching string.")

    @staticmethod
    def _iter_month_prefixes(folder: str, start: date, end: date) -> Iterable[str]:
        """Yield GCS folder prefixes for each month in the requested range."""
        year = start.year
        month = start.month

        while year < end.year or (year == end.year and month <= end.month):
            yield f"{folder}/{year:04d}/{month:02d}/"
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1

    @staticmethod
    def _iter_folder_variants(folder: str) -> Iterable[str]:
        """Yield unique folder-name variants to support case differences in GCS."""
        candidates = (folder.strip(), folder.strip().lower(), folder.strip().upper())
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            yield candidate

    @classmethod
    def _get_folder_candidates(cls, file_type: SupportedCSVFileType, primary_folder: str) -> list[str]:
        """Return ordered folder candidates, including known naming aliases."""
        aliases: list[str] = []
        if file_type == SupportedCSVFileType.CONTACT:
            aliases.extend(["contact"])

        candidates: list[str] = []
        seen: set[str] = set()
        for folder in [primary_folder, *aliases]:
            for variant in cls._iter_folder_variants(folder):
                if variant in seen:
                    continue
                seen.add(variant)
                candidates.append(variant)
        return candidates

    @staticmethod
    def _get_filename_patterns(file_type: SupportedCSVFileType, primary_pattern: str) -> list[str]:
        """Return ordered filename regex patterns, including known aliases."""
        patterns = [primary_pattern]
        if file_type == SupportedCSVFileType.EV:
            patterns.extend(
                [
                    r"^ev_fact_(\d{8})\.csv$",
                    r"^ev_dump_(\d{8})\.csv$",
                    r"^ev_(\d{8})\.csv$",
                ]
            )
        if file_type == SupportedCSVFileType.PRINT:
            patterns.extend(
                [
                    r"^print_fact_(\d{8})\.csv$",
                    r"^print_dump_(\d{8})\.csv$",
                    r"^print_(\d{8})\.csv$",
                ]
            )
        if file_type == SupportedCSVFileType.CONTACT:
            patterns.extend(
                [
                    r"^contact_fact_(\d{8})\.csv$",
                    r"^contact_dump_(\d{8})\.csv$",
                    r"^contact_(\d{8})\.csv$",
                ]
            )

        unique_patterns: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            if pattern in seen:
                continue
            seen.add(pattern)
            unique_patterns.append(pattern)
        return unique_patterns

    @staticmethod
    def _build_default_rules() -> dict[SupportedCSVFileType, GCSFileTypeRule]:
        """Build discovery rules from centralized app configuration."""
        rules: dict[SupportedCSVFileType, GCSFileTypeRule] = {}
        for file_type_name, config in GCS_FILE_DISCOVERY_RULES.items():
            file_type = SupportedCSVFileType(file_type_name)
            rules[file_type] = GCSFileTypeRule(
                folder=config["folder"],
                filename_pattern=config["filename_pattern"],
            )
        return rules