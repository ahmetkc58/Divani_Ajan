from __future__ import annotations

import json
from pathlib import Path

from karayol_agent.schemas import LegislationChunk


class LegislationRepository:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path

    def load(self) -> list[LegislationChunk]:
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        records = payload["data"] if isinstance(payload, dict) else payload
        return [LegislationChunk.model_validate(record) for record in records]

