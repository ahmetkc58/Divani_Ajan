from __future__ import annotations

from karayol_agent.text_utils import normalize_for_search


COMPETITION_DOCUMENT_TYPES = (
    "dilekce",
    "sikayet",
    "itiraz",
    "talep",
    "izin",
    "belge",
)
GENERAL_DOCUMENT_TYPES = frozenset(COMPETITION_DOCUMENT_TYPES)

# Eski ayrıntılı etiketler evrak türü değil, çalışma zamanı konu/niyet
# profilleridir. Bu eşleme mevcut yönlendirme ve RAG davranışını korurken
# kullanıcıya genel bir evrak türü sunar.
OPERATIONAL_PROFILE_TO_GENERAL_TYPE = {
    "yol_bakim_talebi": "talep",
    "trafik_guvenligi_bildirimi": "sikayet",
    "hasar_bildirimi": "sikayet",
    "bilgi_talebi": "belge",
    "sikayet": "sikayet",
    "ust_yazi": "dilekce",
    "dilekce": "dilekce",
    "genel_basvuru": "dilekce",
}

_TYPE_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "itiraz",
        (
            "itiraz",
            "karara karşı",
            "kararin yeniden incelen",
            "kararın yeniden incelen",
            "işlemin yeniden değerlendiril",
        ),
    ),
    (
        "izin",
        (
            "izin başvuru",
            "izin veril",
            "iznin veril",
            "çalışma izni",
            "faaliyet izni",
            "müsaade",
        ),
    ),
    (
        "sikayet",
        (
            "şikayet",
            "şikâyet",
            "mağduriyet",
            "rahatsızlık hakkında",
            "rahatsızlığ",
        ),
    ),
    (
        "belge",
        (
            "belge talebi",
            "belgenin tarafıma",
            "belge örneği",
            "bilgi edinme",
            "kayıtların tarafıma",
            "bilgi ve belge",
        ),
    ),
    ("dilekce", ("dilekçe", "dilekçemin")),
    ("sikayet", ("bildiriyorum", "bildirim", "ihbar", "haber veriyorum")),
    (
        "talep",
        ("talep ediyorum", "talebim", "yapılmasını istiyorum", "başvuru"),
    ),
)


def general_document_type_for(
    operational_profile: str,
    text: str = "",
) -> str:
    """Return one broad document type without losing the operational profile."""

    normalized = normalize_for_search(text)
    for document_type, phrases in _TYPE_PHRASES:
        if any(normalize_for_search(phrase) in normalized for phrase in phrases):
            return document_type
    return OPERATIONAL_PROFILE_TO_GENERAL_TYPE.get(
        operational_profile,
        "dilekce",
    )


__all__ = [
    "COMPETITION_DOCUMENT_TYPES",
    "GENERAL_DOCUMENT_TYPES",
    "OPERATIONAL_PROFILE_TO_GENERAL_TYPE",
    "general_document_type_for",
]
