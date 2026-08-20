from typing import Any

from app.schemas import AnalysisCore, ExtractedField
from app.services.analysis import analyze_document
from app.services.rag import SearchResult


class FakeOllama:
    def chat_structured(self, *_: Any, **__: Any) -> AnalysisCore:
        return AnalysisCore(
            document_type="dilekce",
            topic="Gıda Yardımı",
            summary="Gıda yardımı başvurusu karşılanmıştır.",
            extracted_fields=[
                ExtractedField(name="basvuru_sahibi", value="yanlış kişi"),
                ExtractedField(name="iletisim", value="sentetik@example.invalid"),
            ],
            evidence=["Kaynakta bulunmayan model cümlesi"],
        )


class FakeRag:
    def retrieve(self, *_: Any, **__: Any) -> list[SearchResult]:
        return []

    def route(self, *_: Any, **__: Any) -> list[SearchResult]:
        return [
            SearchResult(
                payload={
                    "id": "BRM-SOSYAL",
                    "name": "Sosyal Yardım İşleri Müdürlüğü",
                    "description": "Sosyal yardım başvuruları.",
                },
                score=0.9,
            ),
            SearchResult(
                payload={
                    "id": "BRM-HALKLA",
                    "name": "Halkla İlişkiler Müdürlüğü",
                    "description": "Başvuru kabul hizmetleri.",
                },
                score=0.5,
            ),
        ]


def test_analysis_grounds_labeled_fields_and_removes_unsupported_claims() -> None:
    text = """SENTETİK BELGE
Belge Türü: Dilekçe
Başvuru Sahibi: SENTETİK KİŞİ 005
İletişim: sentetik@example.invalid
Konu: Gıda Yardımı
Talep: Gıda yardımı başvurusu
Tarih: 20.08.2026
"""

    result = analyze_document(
        document_id="document-1",
        text=text,
        text_quality=0.95,
        chat_model="fake-chat",
        embedding_model="fake-embed",
        ollama=FakeOllama(),  # type: ignore[arg-type]
        rag=FakeRag(),  # type: ignore[arg-type]
    )

    values = {field.name: field.value for field in result.extracted_fields}
    assert values["basvuru_sahibi"] == "SENTETİK KİŞİ 005"
    assert values["talep"] == "Gıda yardımı başvurusu"
    assert values["tarih"] == "20.08.2026"
    assert result.missing_fields == []
    assert result.document_type.evidence == ["Belge Türü: Dilekçe"]
    assert "karşılan" not in result.summary
