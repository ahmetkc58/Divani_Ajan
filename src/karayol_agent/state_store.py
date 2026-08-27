from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from uuid import uuid4

from karayol_agent.schemas import ProcessState


class FileProcessStore:
    """MVP için dosya tabanlı ve iş parçacığı güvenli süreç deposu."""

    _DOCUMENT_ID_PATTERN = re.compile(r"^EVR-\d{8}-[A-F0-9]{8}$")

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def save(self, state: ProcessState) -> None:
        destination = self._path_for(state.document_id)
        if destination is None:
            raise ValueError("Geçersiz evrak kimliği.")
        temporary = destination.with_name(
            f"{destination.name}.{uuid4().hex}.tmp"
        )
        payload = state.model_dump(mode="json")
        with self._lock:
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._replace_with_retry(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

    def get(self, document_id: str) -> ProcessState | None:
        source = self._path_for(document_id)
        if source is None:
            return None
        if not source.exists():
            return None
        with self._lock:
            return ProcessState.model_validate_json(source.read_text(encoding="utf-8"))

    def _path_for(self, document_id: str) -> Path | None:
        if not self._DOCUMENT_ID_PATTERN.fullmatch(document_id):
            return None
        return self.directory / f"{document_id}.json"

    @staticmethod
    def _replace_with_retry(source: Path, destination: Path) -> None:
        """Windows antivirüs/dizin taraması kaynaklı kısa kilitleri tolere eder."""
        for attempt in range(4):
            try:
                source.replace(destination)
                return
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.01 * (2**attempt))
