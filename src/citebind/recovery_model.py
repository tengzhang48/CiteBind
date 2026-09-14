"""Recovered foreign references, separate from the verified citebind/1 contract.

Recovery preserves what a manuscript contains. It does not certify the source
metadata, resolve identifiers, or transfer ownership of the citation fields.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


class RecoveryError(ValueError):
    """The input cannot be inspected reliably; no complete recovery is claimed."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


@dataclass
class RecoveryFinding:
    code: str
    message: str
    severity: str = "warning"
    part: str | None = None
    field_index: int | None = None
    record_id: str | None = None


@dataclass
class RecoveredRecord:
    id: str
    source: str
    csl: dict[str, Any]
    raw: dict[str, Any] | str
    source_ids: list[str] = field(default_factory=list)


@dataclass
class CitationOccurrence:
    source: str
    part: str
    field_index: int
    record_ids: list[str]
    instruction: str


@dataclass
class RecoveryReport:
    source_sha256: str
    records: list[RecoveredRecord] = field(default_factory=list)
    citations: list[CitationOccurrence] = field(default_factory=list)
    findings: list[RecoveryFinding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "citebind-recovery/1",
            "metadata_status": "recovered_not_verified",
            **asdict(self),
        }
