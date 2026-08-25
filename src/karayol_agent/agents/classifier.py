from __future__ import annotations

from karayol_agent.schemas import ClassificationResult
from karayol_agent.text_utils import normalize_for_search, tokenize


class ClassificationAgent:
    name = "Sınıflandırma Ajanı"

    LABEL_KEYWORDS: dict[str, tuple[str, ...]] = {
        "yol_bakim_talebi": (
            "yol bakım",
            "asfalt",
            "çukur",
            "bozuk yol",
            "kaplama",
            "yol onarım",
            "sürüş yüzeyi",
            "yol yüzeyi",
            "yüzey yenileme",
            "derin oyuk",
            "tekerlek izi",
            "yüzey dalgalanma",
        ),
        "trafik_guvenligi_bildirimi": (
            "trafik güvenliği",
            "işaret levhası",
            "bariyer",
            "sinyalizasyon",
            "kaza riski",
            "yaya geçidi",
            "yönlendirme tabelası",
            "yön gösteren tabela",
            "kavşak ışıkları",
            "kırmızı ve yeşil ışık",
            "ışık düzeni",
        ),
        "hasar_bildirimi": (
            "hasar",
            "zarar",
            "heyelan",
            "çökme",
            "sel",
            "istinat",
            "şev",
            "kaya parçası",
            "yamaçtan kopan",
            "destek duvarı",
            "duvarın dışa eğilmesi",
        ),
        "bilgi_talebi": (
            "bilgi edinme",
            "bilgi talep",
            "bilgi verilmesi",
            "hakkında bilgi",
            "faaliyet kayıtları",
            "yıllık istatistik",
            "kayıtların tarafıma gönderilmesi",
            "kayıtları gönder",
        ),
        "sikayet": ("şikayet", "mağdur", "rahatsızlık", "gereğinin yapılması"),
        "ust_yazi": ("arz ederim", "rica ederim", "dağıtım", "ilgi:"),
        "dilekce": ("dilekçe", "talep ediyorum", "arz ederim", "başvuru"),
    }

    KEYWORD_WEIGHTS: dict[str, dict[str, float]] = {
        "bilgi_talebi": {
            "bilgi edinme": 3.0,
            "bilgi talep": 2.5,
            "bilgi verilmesi": 2.0,
            "hakkında bilgi": 1.5,
        },
        "sikayet": {
            "şikayet": 2.5,
            "mağdur": 1.0,
            "rahatsızlık": 1.0,
            "gereğinin yapılması": 0.5,
        },
        "ust_yazi": {
            "ilgi:": 2.5,
            "dağıtım": 2.5,
            "arz ederim": 0.3,
            "rica ederim": 0.3,
        },
        "dilekce": {
            "dilekçe": 2.5,
            "başvuru": 0.5,
            "talep ediyorum": 0.25,
            "arz ederim": 0.25,
        },
    }

    def run(self, text: str) -> ClassificationResult:
        normalized = normalize_for_search(text)
        scored: list[tuple[float, str, list[str]]] = []
        for label, keywords in self.LABEL_KEYWORDS.items():
            matches = [
                keyword for keyword in keywords if self._keyword_matches(normalized, keyword)
            ]
            if matches:
                configured_weights = self.KEYWORD_WEIGHTS.get(label, {})
                score = sum(
                    configured_weights.get(
                        keyword, 1.5 if " " in keyword else 1.0
                    )
                    for keyword in matches
                )
                scored.append((score, label, matches))

        if not scored:
            return ClassificationResult(
                document_type="genel_basvuru",
                confidence=0.35,
                matched_keywords=[],
            )

        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, label, matches = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score
        # Birden fazla niyetin neredeyse aynı puanı alması halinde güveni
        # bilinçli olarak düşük tutar; TemplateSelectionAgent böyle bir kararı
        # insan onayına taşır.
        confidence = min(0.55 + best_score * 0.09, 0.97)
        if second_score and (margin < 0.75 or second_score >= best_score * 0.5):
            confidence = min(confidence, 0.58)
        return ClassificationResult(
            document_type=label,
            confidence=round(confidence, 2),
            matched_keywords=matches,
        )

    @staticmethod
    def _keyword_matches(text: str, keyword: str) -> bool:
        """Kelime içi yanlış eşleşmeyi engeller, Türkçe çekim eklerine tolerans tanır."""
        text_tokens = tokenize(text)
        keyword_tokens = tokenize(keyword)
        if not keyword_tokens or len(keyword_tokens) > len(text_tokens):
            return False
        for start in range(len(text_tokens) - len(keyword_tokens) + 1):
            candidate = text_tokens[start : start + len(keyword_tokens)]
            if all(
                actual == expected
                or (len(expected) >= 5 and actual.startswith(expected))
                for actual, expected in zip(candidate, keyword_tokens, strict=True)
            ):
                return True
        return False
