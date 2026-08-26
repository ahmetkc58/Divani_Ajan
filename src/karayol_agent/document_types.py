from __future__ import annotations

from karayol_agent.text_utils import normalize_for_search


GENERAL_DOCUMENT_TYPES = frozenset(
    {
        "dilekce",
        "sikayet",
        "itiraz",
        "talep",
        "izin",
        "belge",
        "bildirim",
        "ust_yazi",
        "genel_basvuru",
    }
)

# Eski ayrıntılı etiketler evrak türü değil, çalışma zamanı konu/niyet
# profilleridir. Bu eşleme mevcut yönlendirme ve RAG davranışını korurken
# kullanıcıya genel bir evrak türü sunar.
OPERATIONAL_PROFILE_TO_GENERAL_TYPE = {
    "yol_bakim_talebi": "talep",
    "trafik_guvenligi_bildirimi": "bildirim",
    "hasar_bildirimi": "bildirim",
    "bilgi_talebi": "belge",
    "sikayet": "sikayet",
    "ust_yazi": "ust_yazi",
    "dilekce": "dilekce",
    "genel_basvuru": "genel_basvuru",
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
    (
        "bildirim",
        ("bildiriyorum", "bildirim", "ihbar", "haber veriyorum"),
    ),
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
    if operational_profile == "ust_yazi":
        return "ust_yazi"
    for document_type, phrases in _TYPE_PHRASES:
        if any(normalize_for_search(phrase) in normalized for phrase in phrases):
            return document_type
    return OPERATIONAL_PROFILE_TO_GENERAL_TYPE.get(
        operational_profile,
        "genel_basvuru",
    )


__all__ = [
    "GENERAL_DOCUMENT_TYPES",
    "OPERATIONAL_PROFILE_TO_GENERAL_TYPE",
    "general_document_type_for",
]
