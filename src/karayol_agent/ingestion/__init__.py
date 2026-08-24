"""Mevzuat kalite kontrolü ve yapısal parçalama."""

from .chunker import LegalStructureChunker, StructureNotFoundError
from .ocr_candidate import (
    CORE_OCR_CANDIDATE_SPECS,
    OFFICIAL_WRITING_GUIDE_SPEC,
    OFFICIAL_WRITING_REGULATION_SPEC,
    OcrCandidateIngestionError,
    OcrCandidateSpec,
    build_core_ocr_candidate_payloads,
    build_ocr_candidate_payload,
    parse_ocr_candidate_text,
)
from .service import (
    IngestionApprovalError,
    IngestionError,
    LegislationIngestionService,
)
from .snapshot import CompetitionSnapshotCorpusBuilder, SnapshotBuildError

__all__ = [
    "CORE_OCR_CANDIDATE_SPECS",
    "OFFICIAL_WRITING_GUIDE_SPEC",
    "OFFICIAL_WRITING_REGULATION_SPEC",
    "OcrCandidateIngestionError",
    "OcrCandidateSpec",
    "IngestionApprovalError",
    "IngestionError",
    "LegalStructureChunker",
    "LegislationIngestionService",
    "CompetitionSnapshotCorpusBuilder",
    "SnapshotBuildError",
    "StructureNotFoundError",
    "build_core_ocr_candidate_payloads",
    "build_ocr_candidate_payload",
    "parse_ocr_candidate_text",
]
