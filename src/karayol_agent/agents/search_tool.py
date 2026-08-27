"""The ``search_legislation`` tool KATMAN 2's Search-o1 agents may call.

Wraps the existing, unmodified deterministic retrieval primitives
(``LegislationResearchAgent.run_with_query`` + ``SourceVerificationAgent``)
so a search triggered by an LLM goes through the exact same trust-contract
verification as every other retrieval path in this project. Only
deterministically **verified** references are ever handed back to the model
— an unverified/untrusted hit is invisible to it, so it can never cite
something the trust-contract floor rejected.
"""

from __future__ import annotations

from typing import Any, Mapping

from karayol_agent.agents.legislation import LegislationResearchAgent, SourceVerificationAgent
from karayol_agent.llm.agentic_gateway import ToolDefinition
from karayol_agent.schemas import DocumentAnalysis, SearchHit, VerifiedReference
from karayol_agent.text_utils import truncate


SEARCH_LEGISLATION_TOOL_NAME = "search_legislation"

SEARCH_LEGISLATION_PARAMETERS_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "maxLength": 300,
            "description": "Aranacak mevzuat/kanıt sorgusu (Türkçe, doğal dil).",
        }
    },
    "required": ["query"],
    "additionalProperties": False,
}


class LegislationSearchTool:
    """Stateful executor: accumulates every verified reference seen this run."""

    name = SEARCH_LEGISLATION_TOOL_NAME
    description = (
        "Karayolu/mevzuat vektör veritabanında bir metin sorgusu arar; "
        "yalnız güven sözleşmesinden geçmiş (doğrulanmış) kanıt parçalarını "
        "döndürür. Doğrulanamayan sonuçlar hiç gösterilmez."
    )

    def __init__(
        self,
        researcher: LegislationResearchAgent,
        verifier: SourceVerificationAgent,
        analysis: DocumentAnalysis,
        *,
        top_k: int = 5,
    ) -> None:
        self._researcher = researcher
        self._verifier = verifier
        self._analysis = analysis
        self._top_k = top_k
        self._verified_references_by_id: dict[str, VerifiedReference] = {}
        self._verified_hits_by_id: dict[str, SearchHit] = {}

    def __call__(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"error": "query alanı boş olamaz."}
        result = self._researcher.run_with_query(query, self._analysis)
        hits = result.hits
        references = self._verifier.run(hits, self._analysis)
        verified: list[VerifiedReference] = []
        for hit, reference in zip(hits, references, strict=True):
            if not reference.verified:
                continue
            verified.append(reference)
            self._verified_references_by_id[reference.chunk_id] = reference
            self._verified_hits_by_id[reference.chunk_id] = hit
        if not verified:
            return {"results": [], "note": "Doğrulanmış kanıt bulunamadı."}
        return {
            "results": [
                {
                    "chunk_id": reference.chunk_id,
                    "title": reference.title,
                    "article": reference.article,
                    "excerpt": truncate(reference.excerpt, 500),
                }
                for reference in verified[: self._top_k]
            ]
        }

    @property
    def seen_chunk_ids(self) -> frozenset[str]:
        return frozenset(self._verified_references_by_id)

    @property
    def verified_references(self) -> list[VerifiedReference]:
        return list(self._verified_references_by_id.values())

    @property
    def verified_hits(self) -> list[SearchHit]:
        return list(self._verified_hits_by_id.values())

    def as_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters_schema=SEARCH_LEGISLATION_PARAMETERS_SCHEMA,
            executor=self,
        )


__all__ = [
    "SEARCH_LEGISLATION_PARAMETERS_SCHEMA",
    "SEARCH_LEGISLATION_TOOL_NAME",
    "LegislationSearchTool",
]
