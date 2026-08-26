from __future__ import annotations

import re
from dataclasses import dataclass


REGULATION_ID = "2646-RG-2020-31151"
REGULATION_TITLE = (
    "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik"
)
REGULATION_URL = "https://www.resmigazete.gov.tr/eskiler/2020/06/20200610.pdf"


@dataclass(frozen=True)
class OfficialWritingRule:
    rule_id: str
    article: str
    title: str
    description: str


RULES = {
    "RY-10": OfficialWritingRule(
        "RY-10",
        "Madde 10",
        "Başlık",
        "Başlık, belgeyi gönderen idarenin ve gerekli durumda birimin adını gösterir.",
    ),
    "RY-11": OfficialWritingRule(
        "RY-11",
        "Madde 11",
        "Sayı",
        "Belge sayısı; ortam kodu, DETSİS numarası, standart dosya planı kodu "
        "ve kayıt numarasından oluşur.",
    ),
    "RY-12": OfficialWritingRule(
        "RY-12",
        "Madde 12",
        "Tarih",
        "Tarih gün, ay ve yıl olarak rakamla noktalı ya da ay adı harfle yazılır.",
    ),
    "RY-13": OfficialWritingRule(
        "RY-13",
        "Madde 13",
        "Konu",
        "Konu alanı belgenin içeriği hakkında kısa ve öz bilgi taşır.",
    ),
    "RY-14": OfficialWritingRule(
        "RY-14",
        "Madde 14",
        "Muhatap",
        "Muhatap belgenin gönderildiği idareyi veya kişiyi belirtir.",
    ),
    "RY-15": OfficialWritingRule(
        "RY-15",
        "Madde 15",
        "İlgi",
        "İlgi, belgenin bağlantılı olduğu belge veya belgeleri gösterir.",
    ),
    "RY-16": OfficialWritingRule(
        "RY-16",
        "Madde 16/12",
        "Metnin bitişi",
        "Arz/rica ifadesi makam ilişkisine; gerçek kişiye yazışmada kapanış "
        "ifadesi yönetmelikteki seçeneklere göre belirlenir.",
    ),
    "RY-17": OfficialWritingRule(
        "RY-17",
        "Madde 17",
        "İmza",
        "İmzalayanın adı, soyadı ve unvanı gösterilir; elektronik belgede güvenli "
        "elektronik imza kullanılır.",
    ),
    "RY-18": OfficialWritingRule(
        "RY-18",
        "Madde 18",
        "Ek",
        "Ekler imza bölümünden sonra gösterilir ve birden fazlaysa numaralandırılır.",
    ),
    "RY-19": OfficialWritingRule(
        "RY-19",
        "Madde 19",
        "Dağıtım",
        "Birden fazla muhatap varsa dağıtım bölümüne yer verilir.",
    ),
    "RY-28": OfficialWritingRule(
        "RY-28",
        "Madde 28",
        "Üstveri",
        "Elektronik belgenin zorunlu üstveri elemanları korunur.",
    ),
}


_TURKISH_MONTHS = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
_MONTH_PATTERN = "|".join(_TURKISH_MONTHS)


def valid_official_date(value: str) -> bool:
    normalized = value.strip()
    return bool(
        re.fullmatch(r"(?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2])\.\d{4}", normalized)
        or re.fullmatch(
            rf"(?:0?[1-9]|[12]\d|3[01])\s+(?:{_MONTH_PATTERN})\s+\d{{4}}",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def valid_official_number(value: str) -> bool:
    """Validate the visible number structure defined by article 11.

    This validates shape only. Whether the DETSİS identifier, standard file plan
    code and EBYS registration number are institutionally valid must still be
    checked against the authoritative systems.
    """

    return bool(
        re.fullmatch(
            r"(?:E|Z|O)-\d{8}-\d+(?:\.\d+)*-[A-Za-z0-9]+",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


ALLOWED_CLOSINGS_BY_RELATION = {
    "subordinate_internal": ("Rica ederim.", "Gereğini rica ederim."),
    "superior": ("Arz ederim.", "Bilgilerinize arz ederim."),
    "same_level": ("Arz ederim.", "Bilgilerinize arz ederim."),
    "mixed": ("Arz ve rica ederim.", "Arz/rica ederim."),
    "citizen_or_external": (
        "Saygılarımla.",
        "İyi dileklerimle.",
        "Bilgilerinize sunulur.",
    ),
}


def closing_matches_authority_relation(closing: str, relation: str) -> bool:
    normalized = " ".join(closing.casefold().split())
    return normalized in {
        " ".join(candidate.casefold().split())
        for candidate in ALLOWED_CLOSINGS_BY_RELATION.get(relation, ())
    }
