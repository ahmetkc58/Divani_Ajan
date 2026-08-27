from __future__ import annotations

from dataclasses import dataclass

from karayol_agent.curation.models import CurationDomain, ScopeStatus
from karayol_agent.text_utils import normalize_for_search


@dataclass(frozen=True, slots=True)
class DomainClassification:
    domain: CurationDomain
    secondary_domains: list[CurationDomain]
    subdomain: str
    confidence: float
    reasons: list[str]
    scope_status: ScopeStatus
    candidate_for_active_rag: bool


class LegislationDomainClassifier:
    """Mevzuat başlığından açıklanabilir ve muhafazakâr kapsam adayı üretir."""

    DOMAIN_RULES: dict[CurationDomain, tuple[tuple[str, int], ...]] = {
        CurationDomain.OFFICIAL_WRITING: (
            ("resmî yazışma", 10),
            ("resmi yazışma", 10),
            ("standart dosya planı", 8),
            ("elektronik belge yönetim", 8),
        ),
        CurationDomain.GENERAL_APPLICATION: (
            ("bilgi edinme hakkı", 10),
            ("dilekçe hakkı", 10),
            ("kişisel verilerin korunması", 8),
            ("başvuru usul", 5),
        ),
        CurationDomain.KGM_INFRASTRUCTURE: (
            ("karayolları genel müdürlüğü", 10),
            ("karayolu yapımı", 10),
            ("karayolu altyapısı", 10),
            ("karayolu trafik", 8),
            ("karayolları trafik", 8),
            ("otoyol", 7),
            ("yol yapım", 7),
            ("yol bakım", 7),
            ("yol kenarı tesis", 7),
            ("trafik işaret", 7),
            ("trafik güvenli", 7),
            ("kamulaştır", 6),
            ("geçiş ücret", 5),
            ("tünel", 4),
            ("köprü", 4),
            ("viyadük", 4),
        ),
        CurationDomain.ROAD_TRANSPORT: (
            ("karayolu taşıma", 10),
            ("karayoluyla taşı", 10),
            ("karayolu taşımacılık", 10),
            ("karayolu düzenleme genel müdürlüğü", 9),
            ("kara ulaştırması genel müdürlüğü", 9),
            ("yola elverişlilik muayenesi", 9),
            ("motorlu karayolu taşıt", 9),
            ("araçların yüklenmesi", 8),
            ("yol kenarı denetim", 9),
            ("yolcu taşımacılığı", 8),
            ("eşya taşımacılığı", 8),
            ("yük taşımacılığı", 8),
            ("araç muayene", 8),
            ("muayene merkez", 7),
            ("yetki belgesi", 6),
            ("ubak izin", 7),
            ("geçiş belgeleri", 6),
            ("takograf", 7),
            ("kış lastiği", 7),
            ("terminal", 5),
            ("mesleki yeterlilik", 5),
            ("araç şoför", 5),
            ("taşıt kart", 6),
            ("tavan ücret", 4),
        ),
        CurationDomain.MARITIME: (
            ("deniz ve içsular", 12),
            ("deniz ulaştırması", 10),
            ("denizyolu", 9),
            ("denizcilik", 8),
            ("deniz ticareti", 8),
            ("deniz çevresi", 8),
            ("su motosikleti", 14),
            ("konteyner", 9),
            ("gemi", 7),
            ("liman", 6),
            ("kıyı tesis", 7),
            ("tekne", 6),
            ("tersane", 7),
            ("marpol", 7),
            ("gemiadam", 7),
            ("denizci", 7),
            ("sualtı", 7),
            ("dalgıç", 7),
            ("balıkçı barınağı", 7),
            ("tanker", 7),
            ("kabotaj", 7),
            ("sörvey", 7),
            ("stcw", 8),
            ("imo", 8),
            ("ism kod", 8),
            ("filika", 7),
            ("bayrak devleti", 7),
            ("lrit", 8),
            ("epirb", 8),
            ("gmdss", 8),
        ),
        CurationDomain.AVIATION: (
            ("havayolu", 9),
            ("havacılık", 8),
            ("havaalan", 7),
            ("hava liman", 7),
            ("havaliman", 7),
            ("hava aracı", 7),
            ("hava sahası", 7),
            ("uçak", 7),
            ("uçuş", 6),
            ("sivil hava", 8),
        ),
        CurationDomain.RAILWAY: (
            ("demiryolu", 10),
            ("demiryolları", 10),
            ("raylı sistem", 8),
            ("lokomotif", 7),
            ("vagon", 7),
            ("tren", 5),
            ("metro", 5),
        ),
        CurationDomain.COMMUNICATIONS: (
            ("haberleşme", 8),
            ("elektronik iletişim", 8),
            ("telekom", 8),
            ("kamunet", 7),
            ("siber olay", 7),
            ("internet", 5),
            ("uydu haberleş", 7),
            ("posta hizmet", 7),
            ("telsiz", 7),
            ("baz istasyonu", 8),
            ("evrensel hizmet", 7),
        ),
        CurationDomain.INTERNAL_ADMINISTRATION: (
            ("personel", 7),
            ("disiplin", 7),
            ("izin yönergesi", 7),
            ("güvenlik soruşturması", 7),
            ("etik komisyon", 6),
            ("teşkilat görev ve sorumluluk", 5),
            ("teşkilat, görev ve sorumluluk", 5),
        ),
    }

    ACTIVE_CANDIDATE_DOMAINS = {
        CurationDomain.OFFICIAL_WRITING,
        CurationDomain.GENERAL_APPLICATION,
        CurationDomain.KGM_INFRASTRUCTURE,
        CurationDomain.ROAD_TRANSPORT,
    }
    OUT_OF_SCOPE_DOMAINS = {
        CurationDomain.MARITIME,
        CurationDomain.AVIATION,
        CurationDomain.RAILWAY,
        CurationDomain.COMMUNICATIONS,
        CurationDomain.INTERNAL_ADMINISTRATION,
    }
    ROAD_MARKERS = ("karayolu", "karayolları", "kara yolu", "otoyol")

    def classify(self, title: str, document_type: str = "") -> DomainClassification:
        normalized = normalize_for_search(f"{title} {document_type}")
        scores: dict[CurationDomain, int] = {}
        matches: dict[CurationDomain, list[tuple[str, int]]] = {}
        for domain, rules in self.DOMAIN_RULES.items():
            domain_matches = [(phrase, weight) for phrase, weight in rules if phrase in normalized]
            if domain_matches:
                matches[domain] = domain_matches
                scores[domain] = sum(weight for _, weight in domain_matches)

        if not scores:
            return DomainClassification(
                domain=CurationDomain.UNKNOWN,
                secondary_domains=[],
                subdomain="unknown",
                confidence=0.0,
                reasons=["Başlıkta güvenilir bir alan göstergesi bulunamadı."],
                scope_status=ScopeStatus.REVIEW_REQUIRED,
                candidate_for_active_rag=False,
            )

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
        domain, top_score = ranked[0]
        secondary = [item[0] for item in ranked[1:] if item[1] > 0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        ambiguous = second_score >= 3 and second_score >= top_score * 0.55
        road_cross_domain = (
            domain in self.OUT_OF_SCOPE_DOMAINS
            and any(marker in normalized for marker in self.ROAD_MARKERS)
        )
        if road_cross_domain:
            ambiguous = True

        margin = (top_score - second_score) / max(top_score, 1)
        confidence = min(0.98, 0.52 + min(top_score, 15) * 0.025 + margin * 0.20)
        if ambiguous:
            confidence = min(confidence, 0.64)

        evidence = sorted(matches[domain], key=lambda item: (-item[1], item[0]))
        reasons = [f"{domain.value}: '{phrase}' (+{weight})" for phrase, weight in evidence]
        if ambiguous:
            competing = ", ".join(
                f"{candidate.value}={score}" for candidate, score in ranked[1:4]
            )
            reasons.append(
                "Birden fazla ulaşım alanı işareti bulundu; insan kapsam kontrolü "
                f"zorunlu ({competing or 'karayolu çapraz alan işareti'})."
            )

        candidate = domain in self.ACTIVE_CANDIDATE_DOMAINS and not ambiguous
        if domain in self.OUT_OF_SCOPE_DOMAINS and not ambiguous:
            scope_status = ScopeStatus.OUT_OF_SCOPE
        else:
            scope_status = ScopeStatus.REVIEW_REQUIRED

        return DomainClassification(
            domain=domain,
            secondary_domains=secondary,
            subdomain=self._subdomain(domain, normalized),
            confidence=round(confidence, 2),
            reasons=reasons,
            scope_status=scope_status,
            candidate_for_active_rag=candidate,
        )

    @staticmethod
    def _subdomain(domain: CurationDomain, text: str) -> str:
        if domain == CurationDomain.KGM_INFRASTRUCTURE:
            rules = (
                ("expropriation", ("kamulaştır", "taşınmaz", "trampa")),
                ("traffic_safety", ("trafik güven", "trafik işaret", "bariyer")),
                ("tolling", ("geçiş ücret", "ücretli yol")),
                ("roadside_facilities", ("yol kenarı", "tesis")),
                ("structures", ("köprü", "tünel", "viyadük", "sanat yapı")),
                ("maintenance", ("bakım", "onarım", "kaplama", "asfalt")),
            )
        elif domain == CurationDomain.ROAD_TRANSPORT:
            rules = (
                ("dangerous_goods", ("tehlikeli madde", "tehlikeli yük")),
                ("vehicle_inspection", ("araç muayene", "muayene merkez")),
                ("international_permissions", ("ubak", "geçiş belge")),
                ("passenger_transport", ("yolcu taşı", "terminal", "servis taşı")),
                ("freight_transport", ("eşya taşı", "yük taşı")),
                ("professional_competence", ("mesleki yeterlilik", "şoför")),
                ("tariffs", ("tavan ücret", "ücret tarife")),
            )
        else:
            return domain.value

        for label, terms in rules:
            if any(term in text for term in terms):
                return label
        return "general"
