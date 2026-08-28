from kaggle.kaggle_legal_rag_v2 import (
    SourceDocument,
    chunk_document,
    reference_edges,
)


def _document(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="uab-test",
        title="Test Yönetmeliği",
        source="test.pdf",
        source_url="https://example.test/source",
        source_sha256="a" * 64,
        document_type="Yönetmelik",
        domain="road_transport",
        subdomain="general",
        ocr_status="text_layer_available",
        pages=((1, text),),
    )


def test_year_in_parentheses_is_not_a_paragraph() -> None:
    document = _document(
        "Amaç MADDE 1 -\n(1) Bu düzenleme ITF/TMB/TR (2008) 12 numaralı "
        "kılavuza dayanır.\n(2) İkinci fıkradır."
    )

    parents, leaves = chunk_document(document, max_chars=1800)

    assert len(parents) == 1
    assert [leaf["paragraph"] for leaf in leaves] == ["1", "2"]
    assert "(2008)" in leaves[0]["text"]


def test_hierarchy_and_leaf_ids_are_stable_and_unique() -> None:
    document = _document(
        "Tanımlar MADDE 2 -\n(1) Bu maddede;\n"
        "a) Kurum: İdareyi,\n"
        "b) Belge: Yazıyı ifade eder."
    )

    parents, leaves = chunk_document(document, max_chars=1800)

    assert len(parents) == 1
    assert {leaf["clause"] for leaf in leaves} == {None, "a", "b"}
    assert len({leaf["leaf_id"] for leaf in leaves}) == len(leaves)
    assert all(leaf["parent_id"] == parents[0]["parent_id"] for leaf in leaves)


def test_explicit_external_reference_is_not_same_document_reference() -> None:
    document = _document(
        "Dayanak MADDE 3 -\n(1) 2918 sayılı Karayolları Trafik Kanununun "
        "35 inci maddesi uygulanır."
    )
    _, leaves = chunk_document(document, max_chars=1800)

    edges = reference_edges(leaves)

    assert len(edges) == 1
    assert edges[0]["target_law_number"] == "2918"
    assert edges[0]["target_article_candidate"] == "35"
    assert "target_document_id" not in edges[0]
