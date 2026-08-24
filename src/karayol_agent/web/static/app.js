"use strict";

const scenarios = {
  maintenance: {
    hint: "Beklenen: yol bakım talebi → Yol Yapım ve Bakım Birimi",
    expectedType: "yol_bakim_talebi",
    expectedUnit: "ORKGM-YB-001",
    semanticType: "yol_bakim_talebi",
    text: `Gönderen: Ayşe Örnek
Tarih: 23.08.2026
Konu: D-100 bağlantı yolundaki asfalt bozulması
Konum: Örnek İl, Örnek İlçe, D-100 bağlantı yolu 12. kilometre
Telefon: 0555 111 22 33

Belirtilen konumda yol yüzeyinde geniş çukurlar ve asfalt bozulmaları oluşmuştur.
Trafik güvenliği açısından gerekli yol bakım ve onarım çalışmasının yapılmasını talep ediyorum.`
  },
  missing: {
    hint: "Beklenen: trafik güvenliği bildirimi → gönderen ve konum eksik",
    expectedType: "trafik_guvenligi_bildirimi",
    expectedUnit: "ORKGM-TG-001",
    semanticType: "trafik_guvenligi_bildirimi",
    text: `Konu: Hasarlı trafik işaret levhası

Bölgemizde bulunan trafik işaret levhası devrilmiştir. Trafik güvenliği açısından gereğinin yapılmasını talep ediyorum.`
  },
  paraphrase: {
    hint: "Sınır testi: anahtar kelime kullanılmadığı için mevcut sürüm zorlanabilir",
    expectedType: "genel_basvuru",
    expectedUnit: "ORKGM-EB-001",
    semanticType: "yol_bakim_talebi",
    limitation: true,
    text: `Gönderen: Selin Örnek
Tarih: 23.08.2026
Konu: Sürüş yüzeyindeki derin oyuklar
Konum: Örnek İlçe, sanayi kavşağı yaklaşımı

Araç tekerlerinin içine girdiği derin oyuklar oluşmuştur. Bu bölümün düzeltilmesini istiyorum.`
  }
};

const statusLabels = {
  alindi: "Evrak alındı",
  okunuyor: "Evrak okunuyor",
  siniflandiriliyor: "Sınıflandırılıyor",
  mevzuat_araniyor: "Mevzuat aranıyor",
  kaynak_dogrulaniyor: "Kaynak doğrulanıyor",
  eksik_bilgi_bekleniyor: "Eksik bilgi bekleniyor",
  yazi_turu_seciliyor: "Yazı türü seçiliyor",
  birim_yonlendiriliyor: "Birim belirleniyor",
  taslak_hazirlaniyor: "Taslak hazırlanıyor",
  uygunluk_kontrolunde: "Uygunluk kontrolünde",
  kullanici_onayi_bekleniyor: "Kullanıcı onayı bekleniyor",
  tamamlandi: "Süreç tamamlandı",
  hata: "İşlem hatası"
};

const llmRoleLabels = {
  document_understanding: "LLM Yapılandırılmış Anlama Ajanı",
  adjudicator: "LLM Karar Ajanı (Adjudicator)"
};

const llmStatusLabels = {
  success: "Başarılı",
  disabled: "Devre dışı",
  policy_rejected: "Güvenlik politikasıyla engellendi",
  invalid_request: "Geçersiz istek",
  timeout: "Zaman aşımı",
  provider_error: "Sağlayıcı hatası",
  invalid_response: "Geçersiz yanıt",
  schema_rejected: "Şema doğrulaması başarısız"
};

const llmDataClassificationLabels = {
  synthetic: "Sentetik",
  public: "Kamuya açık",
  redacted: "Maskelenmiş",
  restricted: "Kısıtlı"
};

const documentTypeLabels = {
  yol_bakim_talebi: "Yol bakım talebi",
  trafik_guvenligi_bildirimi: "Trafik güvenliği bildirimi",
  hasar_bildirimi: "Hasar bildirimi",
  bilgi_talebi: "Bilgi talebi",
  sikayet: "Şikâyet",
  dilekce: "Dilekçe",
  ust_yazi: "Üst yazı",
  genel_basvuru: "Genel başvuru",
  cevap_yazisi: "Cevap yazısı",
  bilgilendirme_yazisi: "Bilgilendirme yazısı",
  eksik_bilgi_talebi: "Eksik bilgi talebi"
};

const fieldLabels = {
  gonderen: "Gönderen / başvuran",
  konu: "Konu",
  konum: "Konum",
  tarih: "Tarih",
  talep: "Talep",
  eposta: "E-posta",
  telefon: "Telefon",
  sayi: "Evrak sayısı",
  imzalayan: "İmzalayan",
  unvan: "İmzalayan unvanı",
  muhatap: "Muhatap"
};

const fieldStatusLabels = {
  kaynaktan_alindi: "Kaynaktan alındı",
  metinden_cikarildi: "Metinden çıkarıldı",
  yonlendirmeden_uretildi: "Sistem tarafından üretildi",
  kullanici_girdisi_gerekli: "Kullanıcı girdisi gerekli"
};

const fieldSourceLabels = {
  kullanici_girdisi: "Kullanıcı girişi",
  sentetik_demo_kurumu: "Sentetik demo kurumu"
};

const corpusModeLabels = {
  competition_snapshot: "Sabit yarışma snapshot'ı",
  verified_public: "Doğrulanmış kamu mevzuatı",
  trusted_synthetic: "Sentetik demo kaynağı",
  mixed_or_unknown: "Karma veya bilinmeyen korpus",
  unknown: "Kaynak türü bilinmiyor"
};

const suggestedValues = {
  gonderen: "Ayşe Örnek",
  konu: "D-100 bağlantı yolundaki asfalt bozulması",
  konum: "Örnek İl, Örnek İlçe, D-100 yolu 12. kilometre",
  tarih: "23.08.2026",
  talep: "Gerekli inceleme ve çalışmanın yapılmasını talep ediyorum.",
  eposta: "ayse.ornek@example.test",
  telefon: "0555 111 22 33",
  sayi: "2026/42",
  imzalayan: "Mehmet Demir",
  unvan: "Şube Müdürü",
  muhatap: "Örnek Bölge Müdürlüğü"
};

const textArea = document.querySelector("#document-text");
const characterCount = document.querySelector("#character-count");
const hint = document.querySelector("#scenario-hint");
const processForm = document.querySelector("#process-form");
const processButton = document.querySelector("#process-button");
const resetButton = document.querySelector("#reset-button");
const emptyState = document.querySelector("#empty-state");
const resultContent = document.querySelector("#result-content");
const toast = document.querySelector("#toast");
const fileInput = document.querySelector("#document-file");
const fileDrop = document.querySelector("#file-drop");
const selectedFileLabel = document.querySelector("#selected-file");
const compilePdf = document.querySelector("#compile-pdf");

let activeScenario = "maintenance";
let inputMode = "text";
let selectedFile = null;
let currentState = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safePercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric * 100)));
}

function safeArtifactUrl(url) {
  const value = String(url || "");
  return /^\/v1\/process\/EVR-\d{8}-[A-F0-9]{8}\/artifacts\/(?:tex|pdf)$/.test(value)
    ? value
    : null;
}

function typeLabel(value) {
  return documentTypeLabels[value] || String(value || "Belirlenemedi").replaceAll("_", " ");
}

function fieldLabel(value) {
  return fieldLabels[value] || String(value || "Alan").replaceAll("_", " ");
}

function showToast(message, kind = "error") {
  toast.textContent = message;
  toast.classList.toggle("is-success", kind === "success");
  toast.hidden = false;
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => { toast.hidden = true; }, 5000);
}

function updateCount() {
  characterCount.textContent = inputMode === "text"
    ? `${textArea.value.length.toLocaleString("tr-TR")} karakter`
    : selectedFile
      ? `${(selectedFile.size / 1024).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} KB`
      : "Dosya seçilmedi";
}

function setGuideStep(step, completed = false) {
  document.querySelectorAll(".guide-steps li").forEach((item, index) => {
    const itemStep = index + 1;
    item.classList.toggle("is-current", !completed && itemStep === step);
    item.classList.toggle("is-complete", completed || itemStep < step);
  });
}

function resetResults() {
  currentState = null;
  resultContent.innerHTML = "";
  resultContent.hidden = true;
  emptyState.hidden = false;
  setGuideStep(1);
}

function switchInputMode(mode) {
  inputMode = mode === "file" ? "file" : "text";
  document.querySelectorAll(".input-mode-tab").forEach((tab) => {
    const active = tab.dataset.inputMode === inputMode;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelector("#text-mode-panel").hidden = inputMode !== "text";
  document.querySelector("#file-mode-panel").hidden = inputMode !== "file";
  hint.textContent = inputMode === "text"
    ? scenarios[activeScenario].hint
    : "Yüklenen dosya gerçek sistem akışındaki metin çıkarımı ve OCR kontrolünden geçer.";
  updateCount();
}

function setScenario(name, focus = true) {
  const scenario = scenarios[name];
  if (!scenario) return;
  activeScenario = name;
  document.querySelectorAll(".scenario-card").forEach((card) => {
    const active = card.dataset.scenario === name;
    card.classList.toggle("is-active", active);
    card.setAttribute("aria-pressed", String(active));
  });
  textArea.value = scenario.text;
  switchInputMode("text");
  resetResults();
  updateCount();
  if (focus) textArea.focus();
}

function setSelectedFile(file) {
  selectedFile = file || null;
  if (!selectedFile) {
    selectedFileLabel.hidden = true;
    selectedFileLabel.textContent = "";
  } else {
    selectedFileLabel.hidden = false;
    selectedFileLabel.textContent = `${selectedFile.name} · ${(selectedFile.size / 1024).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} KB`;
  }
  updateCount();
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "İşlem tamamlanamadı.");
  }
  return payload;
}

function renderLoading() {
  emptyState.hidden = true;
  resultContent.hidden = false;
  resultContent.innerHTML = `
    <div class="loading-state" role="status">
      <span class="loading-orbit" aria-hidden="true"></span>
      <h3>Ajan zinciri çalışıyor</h3>
      <p>Evrak okunuyor, kaynaklar aranıyor ve taslak hazırlanıyor…</p>
    </div>`;
  setGuideStep(2);
}

function scenarioExpectation(state) {
  if (inputMode === "file") return "";
  const scenario = scenarios[activeScenario];
  const actualType = state.analysis?.document_type;
  const actualUnit = state.routing?.unit_id;
  if (scenario.limitation) {
    if (actualType === scenario.semanticType) {
      return `<div class="expectation-banner"><span>✓</span><div><strong>Sınır örneği artık doğru anlaşıldı</strong>Paraphrase metni semantik olarak yol bakım talebi şeklinde sınıflandırıldı.</div></div>`;
    }
    return `<div class="expectation-banner is-warning"><span>!</span><div><strong>Beklenen MVP sınırı görüldü</strong>Metin semantik olarak yol bakım talebi olsa da mevcut anahtar kelime sürümü “${escapeHtml(typeLabel(actualType))}” sonucunu verdi. Bu örnek embedding/LLM geliştirmesi için bilerek korunuyor.</div></div>`;
  }
  const matched = actualType === scenario.expectedType && actualUnit === scenario.expectedUnit;
  return `<div class="expectation-banner${matched ? "" : " is-warning"}"><span>${matched ? "✓" : "!"}</span><div><strong>${matched ? "Senaryo beklentisi karşılandı" : "Senaryo beklentisinden sapma var"}</strong>Tür: ${escapeHtml(typeLabel(actualType))} · Birim: ${escapeHtml(state.routing?.unit_name || "bulunamadı")}</div></div>`;
}

function renderOverview(state) {
  const analysis = state.analysis || {};
  const routing = state.routing || {};
  const template = state.template_decision || {};
  const compliance = state.compliance || {};
  const confidence = safePercent(analysis.confidence);
  const complianceScore = safePercent(compliance.score);
  const verifiedCount = (state.verified_references || []).filter((item) => item.verified).length;
  const warnings = (compliance.warnings || []).map((item) => escapeHtml(item)).join(" · ");
  const llm = state.llm_trace || {};
  const graph = state.graph_decision_trace || {};
  const partialLlmFallback = Boolean(llm.used && llm.deterministic_fallback_used);
  const llmLabel = partialLlmFallback
    ? "Kısmi LLM · güvenli fallback"
    : llm.used
      ? `${llm.provider || "LLM"} · ${llm.model || "yapılandırılmış çıktı"}`
      : "Yerel deterministik akış";
  const llmStatus = llm.warning || (partialLlmFallback
    ? "Bazı aşamalarda yerel deterministik karar korundu"
    : llm.used
      ? "Kapalı JSON şeması doğrulandı"
      : "Güvenli fallback kullanıldı");
  const graphLabel = graph.applied
    ? "Seçici çok-adımlı graf izi"
    : "Graf abstention / devre dışı";

  return `
    ${scenarioExpectation(state)}
    <div class="overview-grid">
      <div class="info-card"><span>Evrak türü</span><strong>${escapeHtml(typeLabel(analysis.document_type))}</strong><small>Güven: %${confidence}</small><div class="score-line"><i style="width:${confidence}%"></i></div></div>
      <div class="info-card"><span>Önerilen birim</span><strong>${escapeHtml(routing.unit_name || "—")}</strong><small>${escapeHtml(routing.unit_id || "")}</small></div>
      <div class="info-card"><span>Resmî yazı türü</span><strong>${escapeHtml(typeLabel(template.document_type))}</strong><small>${escapeHtml(template.template_id || "")}</small></div>
      <div class="info-card"><span>Uygunluk</span><strong>%${complianceScore} · ${compliance.passed ? "Geçti" : "Kaldı"}</strong><small>${verifiedCount} doğrulanmış kaynak</small><div class="score-line"><i style="width:${complianceScore}%"></i></div></div>
      <div class="info-card"><span>LLM orkestrasyonu</span><strong>${escapeHtml(llmLabel)}</strong><small>${escapeHtml(llmStatus)}</small></div>
      <div class="info-card"><span>Kanıt grafı</span><strong>${escapeHtml(graphLabel)}</strong><small>${escapeHtml(graph.graph_id || graph.strategy || "Graf yok")}</small></div>
      <div class="info-card wide"><span>Özet</span><strong>${escapeHtml(analysis.summary || "Özet oluşturulamadı.")}</strong>${warnings ? `<small>${warnings}</small>` : ""}</div>
      <div class="info-card wide"><span>Yönlendirme gerekçesi</span><strong>${escapeHtml(routing.rationale || "—")}</strong></div>
    </div>
    ${renderNextAction(state)}
  `;
}

function renderNextAction(state) {
  if (state.status === "tamamlandi") {
    return `<div class="completed-banner"><span class="completed-mark">✓</span><h4>Evrak süreci tamamlandı</h4><p>Taslak onaylandı. Çıktıyı Taslak sekmesinden indirebilirsiniz.</p></div>`;
  }

  const missing = state.missing_information || [];
  if (missing.length) {
    const controls = missing.map((name, index) => {
      const safeName = escapeHtml(name);
      return `<div class="field-control"><label for="missing-field-${index}">${escapeHtml(fieldLabel(name))}</label><input id="missing-field-${index}" data-field="${safeName}" value="" placeholder="${escapeHtml(suggestedValues[name] || "Bilgiyi girin")}" autocomplete="off" required /></div>`;
    }).join("");
    return `<div class="action-card"><h4>Eksik bilgileri tamamlayın</h4><p>${escapeHtml(state.next_step)}</p><form class="field-form" id="missing-information-form">${controls}<div class="field-form-actions"><button class="mini-button is-secondary" id="fill-sample-values" type="button">Örnek değerleri doldur</button><button class="mini-button" type="submit">Bilgileri kaydet ve taslağı yenile</button></div></form></div>`;
  }

  if (state.status === "kullanici_onayi_bekleniyor") {
    return `<div class="action-card is-success"><h4>Taslak onaya hazır</h4><p>Önce Taslak ve Kaynaklar sekmelerini kontrol edin, ardından yetkili kullanıcı adıyla onaylayın.</p><form class="field-form" id="approval-form"><div class="field-control"><label for="approved-by">Onaylayan kişi</label><input id="approved-by" value="Yetkili Demo Kullanıcısı" minlength="2" maxlength="120" required /></div><div class="field-form-actions"><button class="mini-button" type="submit">Taslağı nihai olarak onayla</button></div></form></div>`;
  }

  return `<div class="action-card"><h4>Sıradaki adım</h4><p>${escapeHtml(state.next_step || "Sonucu inceleyin.")}</p></div>`;
}

function fieldSourceText(field) {
  const status = fieldStatusLabels[field?.status] || field?.status || "Durum bilinmiyor";
  const rawSource = field?.source;
  const source = rawSource
    ? fieldSourceLabels[rawSource] || rawSource
    : field?.status === "kullanici_girdisi_gerekli"
      ? "Kullanıcı girişi bekleniyor"
      : "Kaynak belirtilmedi";
  return `${status} · Kaynak: ${source}`;
}

function renderFieldRows(entries) {
  return entries.map(([name, field]) => `
    <div class="data-row"><dt>${escapeHtml(fieldLabel(name))}</dt><dd>${escapeHtml(field?.value || "[EKSİK]")}<span class="field-source">${escapeHtml(fieldSourceText(field))}</span></dd></div>`).join("");
}

function renderFields(state) {
  const analysisEntries = Object.entries(state.analysis?.fields || {});
  const draftEntries = state.draft ? [
    ["sayi", state.draft.number],
    ["imzalayan", state.draft.signer],
    ["unvan", state.draft.signer_title]
  ] : [];
  const sections = [];

  if (analysisEntries.length) {
    sections.push(`<section class="field-group"><h4>Belgeden çıkarılan alanlar</h4><dl class="data-list">${renderFieldRows(analysisEntries)}</dl></section>`);
  }
  if (draftEntries.length) {
    sections.push(`<section class="field-group"><h4>Zorunlu taslak alanları</h4><p>Sayı, imzalayan ve unvan taslağın tamamlanması için kullanıcı tarafından doğrulanmalıdır.</p><dl class="data-list">${renderFieldRows(draftEntries)}</dl></section>`);
  }
  return sections.join("") || `<div class="empty-state"><h3>Alan bulunamadı</h3><p>Henüz çıkarılmış veya taslağa bağlı bir alan yok.</p></div>`;
}

function renderReferences(state) {
  const references = state.verified_references || [];
  if (!references.length) {
    const diagnostics = state.retrieval_diagnostics || {};
    const warning = diagnostics.warning || "Bu evrak için mevzuat eşleşmesi üretilemedi.";
    const queryReasons = (diagnostics.relevance_query_reasons || []).join(" ");
    return `<div class="empty-state"><h3>Kaynak üretilmedi</h3><p>${escapeHtml(warning)}</p>${queryReasons ? `<p><strong>Sorgu kapısı:</strong> ${escapeHtml(queryReasons)}</p>` : ""}</div>`;
  }
  return references.map((reference) => {
    const isSnapshot = reference.corpus_mode === "competition_snapshot";
    const currentnessVerified = reference.currentness_verified === true;
    const legalRelianceAllowed = reference.legal_reliance_allowed === true;
    const relevanceAccepted = reference.relevance_accepted === true;
    const relevanceScore = Number(reference.relevance_score);
    const pageLabel = reference.page
      ? `Sayfa: ${reference.page_end && reference.page_end !== reference.page ? `${reference.page}-${reference.page_end}` : reference.page}`
      : "Sayfa izi yok";
    const corpusLabel = corpusModeLabels[reference.corpus_mode] || reference.corpus_mode || corpusModeLabels.unknown;
    const usageNotice = reference.usage_notice || (isSnapshot
      ? "Bu sabit yarışma snapshot'ının güncelliği ve yürürlük durumu doğrulanmamıştır; yalnız retrieval ve kaynak izi için kullanılabilir."
      : "");
    return `
      <article class="reference-card${isSnapshot ? " is-snapshot" : ""}">
        <div class="reference-top"><strong>${escapeHtml(reference.title)}${reference.article ? ` · ${escapeHtml(reference.article)}` : ""}</strong><span class="verification-badge${reference.verified ? "" : " is-rejected"}">${reference.verified ? "Kaynak sözleşmesi geçti" : "Kaynak reddedildi"}</span></div>
        <div class="reference-disclosures" aria-label="Kaynak güvenilirlik durumu">
          <span>${escapeHtml(corpusLabel)}</span>
          <span class="${currentnessVerified ? "is-positive" : "is-caution"}">Güncellik: ${currentnessVerified ? "doğrulandı" : "doğrulanmadı"}</span>
          <span class="${legalRelianceAllowed ? "is-positive" : "is-caution"}">Hukuki dayanak: ${legalRelianceAllowed ? "kullanılabilir" : "kullanılamaz"}</span>
          ${Number.isFinite(relevanceScore) ? `<span class="${relevanceAccepted ? "is-positive" : "is-caution"}">Sorgu alakası: %${safePercent(relevanceScore)}</span>` : ""}
        </div>
        ${usageNotice ? `<div class="reference-warning" role="note"><strong>${isSnapshot ? "Snapshot uyarısı" : "Kaynak kullanım uyarısı"}</strong><span>${escapeHtml(usageNotice)}</span></div>` : ""}
        <p>${escapeHtml(reference.excerpt)}</p>
        ${reference.verification_note ? `<p class="verification-note"><strong>Doğrulama notu:</strong> ${escapeHtml(reference.verification_note)}</p>` : ""}
        ${(reference.relevance_reasons || []).length ? `<p class="verification-note"><strong>Alaka gerekçesi:</strong> ${escapeHtml(reference.relevance_reasons.join(" "))}</p>` : ""}
        <div class="reference-meta"><span>Chunk: ${escapeHtml(reference.chunk_id)}</span><span>${escapeHtml(pageLabel)}</span><span>Retrieval skoru: %${safePercent(reference.score)}</span><span>${escapeHtml(reference.source)}</span></div>
      </article>`;
  }).join("");
}

function draftValue(field) {
  return field?.value || "[DOLDURULACAK]";
}

function renderDraft(state) {
  const draft = state.draft;
  if (!draft) return `<div class="empty-state"><h3>Taslak bulunmuyor</h3><p>Henüz bir resmî yazı taslağı oluşturulmadı.</p></div>`;
  const texUrl = safeArtifactUrl(state.artifact?.tex_download_url);
  const pdfUrl = safeArtifactUrl(state.artifact?.pdf_download_url);
  const paragraphs = (draft.paragraphs || []).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
  return `
    <div class="artifact-actions">${texUrl ? `<a class="download-link" href="${texUrl}">↓ LaTeX taslağını indir</a>` : ""}${pdfUrl ? `<a class="download-link" href="${pdfUrl}">↓ PDF çıktısını indir</a>` : `<span class="download-link is-disabled">PDF derleyicisi / çıktısı yok</span>`}</div>
    <article class="draft-sheet"><div class="draft-letterhead"><strong>${escapeHtml(draftValue(draft.institution_name))}</strong></div><div class="draft-meta"><span><b>Sayı:</b> ${escapeHtml(draftValue(draft.number))}</span><span><b>Tarih:</b> ${escapeHtml(draftValue(draft.date))}</span><span><b>Konu:</b> ${escapeHtml(draftValue(draft.subject))}</span><span><b>Şablon:</b> ${escapeHtml(draft.template_id)}</span></div><div class="draft-recipient">${escapeHtml(draftValue(draft.recipient))}</div>${paragraphs}<div class="draft-signature"><strong>${escapeHtml(draftValue(draft.signer))}</strong><br />${escapeHtml(draftValue(draft.signer_title))}</div></article>`;
}

function llmStepDescription(step) {
  const descriptions = {
    success: "Yapılandırılmış LLM çağrısı ve kapalı JSON şeması doğrulaması tamamlandı.",
    disabled: "LLM sağlayıcısı etkin olmadığı için yerel deterministik sonuç kullanıldı.",
    policy_rejected: "Ağ çağrısından önce veri güvenliği politikası uygulandı; yerel deterministik sonuç korundu.",
    invalid_request: "LLM isteği doğrulanamadı; yerel deterministik sonuç korundu.",
    timeout: "LLM çağrısı zaman aşımına uğradı; yerel deterministik sonuç korundu.",
    provider_error: "LLM sağlayıcısı çağrıyı tamamlayamadı; yerel deterministik sonuç korundu.",
    invalid_response: "LLM yanıtı geçerli bir yapılandırılmış çıktı üretmedi; yerel deterministik sonuç korundu.",
    schema_rejected: "LLM yanıtı kapalı JSON şemasından geçmedi; yerel deterministik sonuç korundu."
  };
  const details = [descriptions[step.status] || "LLM adımı kayda alındı."];
  if (step.decision_applied === true) {
    details.push("Öneri güven ve kanıt kapılarından geçerek uygulandı.");
  } else if (step.decision_applied === false) {
    details.push("Öneri uygulanmadı; deterministik karar korundu.");
  }
  if (step.human_review_required) details.push("İnsan incelemesi gerekli.");
  if (step.detail) details.push(step.detail);
  return details.join(" ");
}

function renderLlmTimeline(llmTrace) {
  const steps = llmTrace?.steps || [];
  if (!steps.length) return "";
  const items = steps.map((step) => {
    const role = llmRoleLabels[step.role] || step.role || "LLM ajanı";
    const status = llmStatusLabels[step.status] || step.status || "Durum bilinmiyor";
    const provider = step.provider || llmTrace.provider;
    const model = step.model || llmTrace.model;
    const classification = llmDataClassificationLabels[step.data_classification]
      || step.data_classification;
    const metadata = [
      provider ? `Sağlayıcı: ${provider}${model ? ` / ${model}` : ""}` : "",
      classification ? `Veri sınıfı: ${classification}` : "",
      `Harici API izni: ${step.external_data_allowed ? "verildi" : "verilmedi"}`,
      `Ağ çağrısı: ${step.network_attempted ? "yapıldı" : "yapılmadı"}`,
      step.failure_code ? `Hata kodu: ${step.failure_code}${step.retryable ? " (yeniden denenebilir)" : ""}` : "",
      step.redacted ? `Maskeleme: ${step.redaction_count || 0} alan` : ""
    ].filter(Boolean).join(" · ");
    return `<div class="timeline-item"><span class="timeline-dot" aria-hidden="true"></span><div><strong>${escapeHtml(role)} · ${escapeHtml(status)}</strong><p>${escapeHtml(llmStepDescription(step))}</p><small>${escapeHtml(metadata)}</small></div></div>`;
  }).join("");
  return `<section class="timeline-group" aria-label="LLM orkestrasyon adımları"><h4>LLM orkestrasyon adımları</h4><div class="timeline">${items}</div></section>`;
}

function renderTimeline(state) {
  const events = state.events || [];
  const eventItems = events.map((event) => {
    const date = new Date(event.timestamp);
    const time = Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `<div class="timeline-item"><span class="timeline-dot" aria-hidden="true"></span><div><strong>${escapeHtml(event.agent)} · ${escapeHtml(statusLabels[event.status] || event.status)}</strong><p>${escapeHtml(event.message)}</p><time>${escapeHtml(time)}</time></div></div>`;
  }).join("");
  const localTimeline = events.length
    ? `<section class="timeline-group" aria-label="Yerel ajan olayları"><h4>Yerel ajan olayları</h4><div class="timeline">${eventItems}</div></section>`
    : "";
  return `${renderLlmTimeline(state.llm_trace)}${localTimeline}`;
}

function renderState(state) {
  currentState = state;
  emptyState.hidden = true;
  resultContent.hidden = false;
  resultContent.innerHTML = `
    <div class="result-headline"><div><span class="result-label">${escapeHtml(statusLabels[state.status] || state.status)}</span><h3>${escapeHtml(typeLabel(state.analysis?.document_type))}</h3><p>${escapeHtml(state.next_step || "Sonucu inceleyin.")}</p></div><button class="document-id" id="copy-document-id" type="button" title="Evrak kimliğini kopyala">${escapeHtml(state.document_id)} ⧉</button></div>
    <nav class="result-tabs" role="tablist" aria-label="Sonuç bölümleri"><button class="result-tab is-active" type="button" role="tab" aria-selected="true" data-result-tab="overview">Genel</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="fields">Alanlar</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="sources">Kaynaklar</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="draft">Taslak</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="timeline">Akış</button></nav>
    <section class="tab-panel" data-tab-panel="overview">${renderOverview(state)}</section><section class="tab-panel" data-tab-panel="fields" hidden>${renderFields(state)}</section><section class="tab-panel" data-tab-panel="sources" hidden>${renderReferences(state)}</section><section class="tab-panel" data-tab-panel="draft" hidden>${renderDraft(state)}</section><section class="tab-panel" data-tab-panel="timeline" hidden>${renderTimeline(state)}</section>`;

  bindResultInteractions();
  if (state.status === "tamamlandi") setGuideStep(4, true);
  else setGuideStep(4);
}

function bindResultInteractions() {
  document.querySelectorAll(".result-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".result-tab").forEach((item) => {
        const active = item === tab;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.tabPanel !== tab.dataset.resultTab;
      });
    });
  });

  document.querySelector("#copy-document-id")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(currentState.document_id);
      showToast("Evrak kimliği kopyalandı.", "success");
    } catch {
      showToast(`Evrak kimliği: ${currentState.document_id}`, "success");
    }
  });

  const missingForm = document.querySelector("#missing-information-form");
  document.querySelector("#fill-sample-values")?.addEventListener("click", () => {
    missingForm.querySelectorAll("input[data-field]").forEach((input) => {
      input.value = suggestedValues[input.dataset.field] || "Örnek bilgi";
    });
  });
  missingForm?.addEventListener("submit", handleInformationSubmit);
  document.querySelector("#approval-form")?.addEventListener("submit", handleApprovalSubmit);
}

async function handleInformationSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector("button[type='submit']");
  const fields = {};
  form.querySelectorAll("input[data-field]").forEach((input) => {
    if (input.value.trim()) fields[input.dataset.field] = input.value.trim();
  });
  submit.disabled = true;
  submit.textContent = "Taslak yenileniyor…";
  try {
    const state = await requestJson(`/v1/process/${encodeURIComponent(currentState.document_id)}/information`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, compile_pdf: compilePdf.checked })
    });
    renderState(state);
    showToast("Bilgiler kaydedildi ve taslak yenilendi.", "success");
  } catch (error) {
    showToast(error.message);
    submit.disabled = false;
    submit.textContent = "Bilgileri kaydet ve taslağı yenile";
  }
}

async function handleApprovalSubmit(event) {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type='submit']");
  const approvedBy = document.querySelector("#approved-by").value.trim();
  submit.disabled = true;
  submit.textContent = "Onaylanıyor…";
  try {
    const state = await requestJson(`/v1/process/${encodeURIComponent(currentState.document_id)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: approvedBy })
    });
    renderState(state);
    showToast("Evrak onaylandı ve süreç tamamlandı.", "success");
  } catch (error) {
    showToast(error.message);
    submit.disabled = false;
    submit.textContent = "Taslağı nihai olarak onayla";
  }
}

async function checkReadiness() {
  const pill = document.querySelector("#health-pill");
  const label = document.querySelector("#health-label");
  const environmentBadge = document.querySelector("#environment-badge");
  pill.classList.remove("is-online", "is-offline");
  try {
    const response = await fetch("/ready", { headers: { "Accept": "application/json" } });
    const readiness = await response.json().catch(() => ({}));
    if (!response.ok || readiness.ready !== true) {
      throw new Error(readiness.detail || "Retrieval altyapısı hazır değil.");
    }
    pill.classList.add("is-online");
    environmentBadge.textContent = corpusModeLabels[readiness.corpus_mode]
      || readiness.data_mode
      || corpusModeLabels.unknown;
    label.textContent = `RAG hazır · ${readiness.detail || readiness.retrieval_mode || "readiness doğrulandı"}`;
    pill.title = readiness.detail || "RAG ve retrieval altyapısı hazır.";
  } catch (error) {
    pill.classList.add("is-offline");
    environmentBadge.textContent = "Korpus doğrulanamadı";
    const detail = error instanceof Error ? error.message : "Readiness kontrolü tamamlanamadı.";
    label.textContent = `RAG HAZIR DEĞİL · ${detail}`;
    pill.title = detail;
  }
}

document.querySelectorAll(".scenario-card").forEach((card) => {
  card.addEventListener("click", () => setScenario(card.dataset.scenario));
});

document.querySelectorAll(".input-mode-tab").forEach((tab) => {
  tab.addEventListener("click", () => switchInputMode(tab.dataset.inputMode));
});

textArea.addEventListener("input", updateCount);
fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((name) => fileDrop.addEventListener(name, (event) => {
  event.preventDefault();
  fileDrop.classList.add("is-dragging");
}));
["dragleave", "drop"].forEach((name) => fileDrop.addEventListener(name, (event) => {
  event.preventDefault();
  fileDrop.classList.remove("is-dragging");
}));
fileDrop.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    setSelectedFile(file);
  }
});

resetButton.addEventListener("click", () => {
  if (inputMode === "text") textArea.value = "";
  else {
    fileInput.value = "";
    setSelectedFile(null);
  }
  resetResults();
  updateCount();
});

processForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (inputMode === "text" && !textArea.value.trim()) {
    showToast("İşlenecek bir evrak metni girin.");
    textArea.focus();
    return;
  }
  if (inputMode === "file" && !selectedFile) {
    showToast("Önce TXT, MD veya PDF dosyası seçin.");
    fileInput.focus();
    return;
  }

  processButton.disabled = true;
  processButton.firstElementChild.textContent = "Ajanlar çalışıyor…";
  renderLoading();
  try {
    let state;
    if (inputMode === "file") {
      const formData = new FormData();
      formData.append("file", selectedFile);
      state = await requestJson(`/v1/process/file?compile_pdf=${compilePdf.checked}`, { method: "POST", body: formData });
    } else {
      state = await requestJson("/v1/process/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textArea.value.trim(), source_name: `${activeScenario}-arayuz-senaryosu.txt`, compile_pdf: compilePdf.checked })
      });
    }
    renderState(state);
  } catch (error) {
    resetResults();
    showToast(error.message);
  } finally {
    processButton.disabled = false;
    processButton.firstElementChild.textContent = "Evrakı işle";
  }
});

setScenario("maintenance", false);
checkReadiness();
