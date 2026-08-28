"""Regression tests for the document_type / operational_category split.

Today's commit (de14b88) intentionally changed the classification contract:
``ContentAnalysisAgent``/``ClassificationAgent`` still produce a specific
type (e.g. ``yol_bakim_talebi``), but ``EvrakOrchestrator._process_reserved_text``
now moves that specific value into the *new* ``operational_category`` field
and replaces ``document_type`` with the closed, six-value general category
(``general_document_type``: dilekce/sikayet/itiraz/talep/izin/belge). See
orchestrator.py around the two lines:

    state.analysis.operational_category = state.analysis.document_type
    state.analysis.document_type = state.analysis.general_document_type

``agents/routing.py`` and ``retrieval/relevance.py::resolve_relevance_profile``
were updated in the same commit to read ``operational_category`` (falling
back to ``document_type`` when it is absent). These tests lock that contract
in so it cannot silently regress back to the old single-field scheme.
"""

from __future__ import annotations

from pathlib import Path

from karayol_agent.config import Settings
from karayol_agent.llm import LLMConfig, LLMProviderName, StructuredLLMGateway
from karayol_agent.orchestrator import EvrakOrchestrator
from karayol_agent.retrieval.relevance import (
    ROAD_SURFACE_PROFILE,
    TRAFFIC_SIGN_PROFILE,
    resolve_relevance_profile,
)


ROOT = Path(__file__).resolve().parents[1]

CLOSED_GENERAL_TYPES = {"dilekce", "sikayet", "itiraz", "talep", "izin", "belge"}

# A fresh (non-fixture) road-maintenance request. Using text that is not one
# of the pinned synthetic fixtures, combined with ``NoNetworkTransport``,
# forces the orchestrator down its fully deterministic path (no LLM
# understanding/adjudication override), so these assertions exercise only
# the deterministic classifier + routing/relevance-profile contract that
# this test module is about.
ROAD_MAINTENANCE_TEXT = (
    "Gönderen: Deniz Karaca\n"
    "Tarih: 12.05.2026\n"
    "Konu: D-200 karayolunda asfalt çökmesi\n"
    "Konum: Örnek İl, Örnek İlçe, D-200 karayolu 8. kilometre\n\n"
    "Belirtilen kilometrede yol yüzeyinde büyük bir çökme oluşmuştur. "
    "Yol bakım ve onarım çalışması yapılmasını talep ediyorum."
)


class _NoNetworkTransport:
    def send(self, _request):
        raise AssertionError("Bu test için ağ çağrısı yapılmamalıydı.")


def _deterministic_only_gateway() -> StructuredLLMGateway:
    """A real gateway wired to a transport that must never be reached.

    Combined with real (non-synthetic-fixture) input text, the orchestrator
    classifies the data as RESTRICTED and every LLM step is policy-rejected
    before any network attempt, leaving only the deterministic classifier,
    router and relevance logic in play.
    """

    return StructuredLLMGateway(
        LLMConfig(
            provider=LLMProviderName.GEMINI,
            model="gemini-2.5-flash",
            api_key="unit-test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
        transport=_NoNetworkTransport(),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )


def test_classification_splits_specific_type_into_operational_category(
    tmp_path: Path,
) -> None:
    orchestrator = EvrakOrchestrator(
        _settings(tmp_path), llm_gateway=_deterministic_only_gateway()
    )

    state = orchestrator.process_text(ROAD_MAINTENANCE_TEXT)

    assert state.analysis is not None
    # The specific profile lives in operational_category now...
    assert state.analysis.operational_category == "yol_bakim_talebi"
    # ...and document_type is the closed, general six-value category.
    assert state.analysis.document_type == "talep"
    assert state.analysis.document_type in CLOSED_GENERAL_TYPES
    assert state.analysis.general_document_type == "talep"


def test_routing_uses_operational_category_not_just_general_type(
    tmp_path: Path,
) -> None:
    orchestrator = EvrakOrchestrator(
        _settings(tmp_path), llm_gateway=_deterministic_only_gateway()
    )

    state = orchestrator.process_text(ROAD_MAINTENANCE_TEXT)

    assert state.analysis is not None
    assert state.analysis.operational_category == "yol_bakim_talebi"
    assert state.routing is not None
    # RoutingAgent.run folds analysis.operational_category into its query;
    # the closed general type "talep" alone carries no unit-specific signal.
    assert state.routing.unit_id == "ORKGM-YB-001"


def test_resolve_relevance_profile_prefers_operational_category() -> None:
    analysis = {
        "operational_category": "yol_bakim_talebi",
        # A deliberately different/uninformative document_type: if the
        # resolver fell back to this instead of preferring
        # operational_category, it would fail to resolve a profile.
        "document_type": "talep",
        "summary": "Yol yüzeyinde bakım talebi",
        "fields": {},
        "keywords": [],
    }

    assert resolve_relevance_profile(analysis) == ROAD_SURFACE_PROFILE


def test_resolve_relevance_profile_falls_back_to_document_type_when_operational_category_missing() -> None:
    analysis = {
        "operational_category": None,
        "document_type": "yol_bakim_talebi",
        "summary": "Yol yüzeyinde bakım talebi",
        "fields": {},
        "keywords": [],
    }

    assert resolve_relevance_profile(analysis) == ROAD_SURFACE_PROFILE


def test_resolve_relevance_profile_traffic_sign_also_prefers_operational_category() -> None:
    analysis = {
        "operational_category": "trafik_guvenligi_bildirimi",
        "document_type": "talep",
        "summary": "Devrilen trafik işaret levhası bildirimi",
        "fields": {},
        "keywords": [],
    }

    assert resolve_relevance_profile(analysis) == TRAFFIC_SIGN_PROFILE


def test_resolve_relevance_profile_does_not_fabricate_for_closed_general_category_alone() -> None:
    # Once classification has been through the split, the closed general
    # category (e.g. "talep") on its own must never resolve to a concrete
    # relevance profile — only a real operational_category (or, in its
    # absence, a document_type carrying the same specific value) may.
    analysis = {
        "operational_category": "talep",
        "document_type": "talep",
        "summary": "Kurumsal etkinlikte konuşmacı daveti",
        "fields": {},
        "keywords": [],
    }

    assert resolve_relevance_profile(analysis) is None
