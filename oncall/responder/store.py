"""Incident state on disk: which alert fingerprints have an open incident.

Layout under the incidents directory:

    open/<fingerprint>        text file holding the id of the open incident (the dedupe marker)
    <incident-id>/            one folder per incident (incident.json, alert.json, captures)

The marker is created with O_EXCL, so two concurrent notifications cannot both open an incident,
and it survives a restart because it is a file.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_FINGERPRINT = re.compile(r"[A-Za-z0-9_-]{1,64}")


class InvalidFingerprintError(ValueError):
    pass


def check_fingerprint(fingerprint: str) -> str:
    """Fingerprints become file names, so only a safe alphabet is accepted."""
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise InvalidFingerprintError("unsupported fingerprint")
    return fingerprint


@dataclass(frozen=True)
class Incident:
    id: str
    path: Path


class IncidentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._open_dir = root / "open"
        self._lock = threading.Lock()
        self._open_dir.mkdir(parents=True, exist_ok=True)

    def open_incident(self, fingerprint: str) -> Incident | None:
        """Open an incident for the fingerprint, or None if one is already open."""
        check_fingerprint(fingerprint)
        with self._lock:
            marker = self._open_dir / fingerprint
            now = datetime.now(UTC)
            incident_id = f"{now:%Y%m%dT%H%M%SZ}-{fingerprint[:12]}"
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return None
            with os.fdopen(fd, "w") as fh:
                fh.write(incident_id)
            path = self.root / incident_id
            suffix = 1
            while path.exists():  # two incidents for one fingerprint within the same second
                suffix += 1
                path = self.root / f"{incident_id}-{suffix}"
            path.mkdir(parents=True)
            self._write_json(
                path / "incident.json",
                {
                    "id": path.name,
                    "fingerprint": fingerprint,
                    "opened_at": now.isoformat(timespec="seconds"),
                    "closed_at": None,
                },
            )
            marker.write_text(path.name)
            return Incident(id=path.name, path=path)

    def close_incident(self, fingerprint: str) -> Incident | None:
        """Close the open incident for the fingerprint; None if there was none."""
        check_fingerprint(fingerprint)
        with self._lock:
            marker = self._open_dir / fingerprint
            try:
                incident_id = marker.read_text().strip()
            except FileNotFoundError:
                return None
            path = self.root / incident_id
            meta = path / "incident.json"
            if meta.exists():
                data = json.loads(meta.read_text())
                data["closed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                self._write_json(meta, data)
            marker.unlink(missing_ok=True)
            return Incident(id=incident_id, path=path)

    def open_incidents(self) -> list[Incident]:
        """Currently open incidents (the dedupe markers), e.g. to resume after a restart."""
        found = []
        for marker in sorted(self._open_dir.iterdir()):
            incident_id = marker.read_text().strip()
            if incident_id and (self.root / incident_id).is_dir():
                found.append(Incident(id=incident_id, path=self.root / incident_id))
        return found

    @staticmethod
    def _write_json(path: Path, data: object) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(path)
