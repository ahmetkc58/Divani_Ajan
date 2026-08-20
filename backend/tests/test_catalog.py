from app.services.catalog import document_catalog, municipality_catalog


def test_catalog_counts_and_unique_ids() -> None:
    document_types = document_catalog()["document_types"]
    units = municipality_catalog()["units"]
    assert len(document_types) == 10
    assert len(units) == 12
    assert len({item["id"] for item in document_types}) == 10
    assert len({item["id"] for item in units}) == 12
    assert all(item["required_fields"] for item in document_types)
    assert all(item["keywords"] for item in units)
