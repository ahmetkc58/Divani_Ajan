"use strict";

function normalizeApiOrigin(value) {
  try {
    const url = new URL(value || "http://127.0.0.1:8010");
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error("unsupported protocol");
    return url.origin;
  } catch {
    return "http://127.0.0.1:8010";
  }
}

const API_ORIGIN = normalizeApiOrigin(window.KARAYOL_CONFIG?.apiBaseUrl);

function apiUrl(path) {
  return new URL(path, `${API_ORIGIN}/`).toString();
}

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
  yanit_stratejisi_bekleniyor: "Yanıt stratejisi bekleniyor",
  taslak_hazirlaniyor: "Taslak hazırlanıyor",
  uygunluk_kontrolunde: "Uygunluk kontrolünde",
  kullanici_onayi_bekleniyor: "Kullanıcı onayı bekleniyor",
  tamamlandi: "Süreç tamamlandı",
  hata: "İşlem hatası"
};

const llmRoleLabels = {
  document_understanding: "LLM Yapılandırılmış Anlama Ajanı",
  adjudicator: "LLM Karar Ajanı (Adjudicator)",
  llm3_template_selection: "LLM3 — Şablon Seçim Ajanı",
  llm4_template_fill: "LLM4 — Şablon Doldurma Ajanı",
  llm5_routing: "LLM5 — Birim Yönlendirme Ajanı",
  llm6_response_strategy: "LLM6 — Yanıt Stratejisi Ajanı"
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
  talep: "Talep",
  bildirim: "Bildirim",
  itiraz: "İtiraz",
  izin: "İzin başvurusu",
  belge: "Belge / bilgi başvurusu",
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
  return /^\/api\/v1\/processes\/EVR-\d{8}-[A-F0-9]{8}\/artifacts\/(?:(?:citizen|internal_unit|default)\/)?(?:tex|pdf)$/.test(value)
    ? apiUrl(value)
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
  const response = await fetch(apiUrl(url), options);
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

const terminalProcessStatuses = new Set([
  "eksik_bilgi_bekleniyor",
  "yanit_stratejisi_bekleniyor",
  "kullanici_onayi_bekleniyor",
  "tamamlandi",
  "hata"
]);

function renderLiveProgress(state) {
  const events = (state.events || []).slice(-12);
  const rows = events.map((event, index) => `
    <li class="${index === events.length - 1 ? "is-current" : "is-complete"}">
      <span>${index === events.length - 1 ? "…" : "✓"}</span>
      <div><strong>${escapeHtml(event.agent || "Ajan")}</strong><small>${escapeHtml(event.message || event.status || "İşleniyor")}</small></div>
    </li>`).join("");
  emptyState.hidden = true;
  resultContent.hidden = false;
  resultContent.innerHTML = `
    <div class="loading-state live-agent-state" role="status" aria-live="polite">
      <span class="loading-orbit" aria-hidden="true"></span>
      <h3>Ajan zinciri çalışıyor</h3>
      <p>${escapeHtml(state.source_name || "Evrak")} · ${escapeHtml(state.current_stage || state.status || "başlatıldı")}</p>
      <ol class="live-agent-list">${rows || "<li class=\"is-current\"><span>…</span><div><strong>Sistem</strong><small>İşlem başlatılıyor.</small></div></li>"}</ol>
    </div>`;
  setGuideStep(2);
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollProcess(documentId) {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const state = await requestJson(`/api/v1/processes/${encodeURIComponent(documentId)}`, {
      headers: { "Accept": "application/json" }
    });
    if (terminalProcessStatuses.has(state.status)) return state;
    renderLiveProgress(state);
    await wait(700);
  }
  throw new Error("Canlı işlem 30 dakika içinde tamamlanmadı.");
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
  const routingReview = routing.requires_human_review
    ? "İnsan incelemesi gerekli"
    : "Otomatik öneri hazır";
  const routingEvidence = (routing.evidence || []).map((item) => escapeHtml(item)).join(" · ");
  const templateAlternatives = template.alternatives || [];
  const templateAlternativesText = templateAlternatives
    .map((item) => escapeHtml(item.display_name || item.template_id))
    .join(", ");

  return `
    ${scenarioExpectation(state)}
    <div class="overview-grid">
      <div class="info-card"><span>Evrak türü</span><strong>${escapeHtml(typeLabel(analysis.general_document_type || analysis.document_type))}</strong><small>Konu/işlem profili: ${escapeHtml(typeLabel(analysis.document_type))} · Güven: %${confidence}</small><div class="score-line"><i style="width:${confidence}%"></i></div></div>
      <div class="info-card"><span>Önerilen birim</span><strong>${escapeHtml(routing.unit_name || "—")}</strong><small>${escapeHtml(routing.unit_id || "")} · ${escapeHtml(routingReview)}</small></div>
      <div class="info-card"><span>Resmî yazı türü</span><strong>${escapeHtml(typeLabel(template.document_type))}</strong>${templateAlternativesText ? `<small>Değerlendirilen diğer seçenekler: ${templateAlternativesText} (seçilmedi)</small>` : ""}</div>
      <div class="info-card"><span>Uygunluk</span><strong>%${complianceScore} · ${compliance.passed ? "Geçti" : "Kaldı"}</strong><small>${verifiedCount} doğrulanmış kaynak</small><div class="score-line"><i style="width:${complianceScore}%"></i></div></div>
      <div class="info-card"><span>LLM orkestrasyonu</span><strong>${escapeHtml(llmLabel)}</strong><small>${escapeHtml(llmStatus)}</small></div>
      <div class="info-card"><span>Kanıt grafı</span><strong>${escapeHtml(graphLabel)}</strong><small>${escapeHtml(graph.graph_id || graph.strategy || "Graf yok")}</small></div>
      <div class="info-card wide"><span>Özet</span><strong>${escapeHtml(analysis.summary || "Özet oluşturulamadı.")}</strong>${warnings ? `<small>${warnings}</small>` : ""}</div>
      <div class="info-card wide"><span>Yönlendirme gerekçesi</span><strong>${escapeHtml(routing.rationale || "—")}</strong></div>
      <div class="info-card wide"><span>Yönlendirme izi</span><strong>${escapeHtml(routing.hierarchy || "—")}</strong><small>Katalog: ${escapeHtml(routing.organization_version || "belirtilmedi")} · Skor farkı: ${safePercent(routing.score_margin)}%${routingEvidence ? ` · ${routingEvidence}` : ""}</small></div>
    </div>
    ${renderNextAction(state)}
  `;
}

function renderNextAction(state) {
  if (state.status === "tamamlandi") {
    return `<div class="completed-banner"><span class="completed-mark">✓</span><h4>Evrak süreci tamamlandı</h4><p>Taslak onaylandı. Çıktıyı Taslak sekmesinden indirebilirsiniz.</p></div>`;
  }

  const cards = [];
  const incomingMissing = state.analysis?.missing_fields || [];
  if (incomingMissing.length) {
    const items = incomingMissing.map((name) => `<li>${escapeHtml(fieldLabel(name))}</li>`).join("");
    cards.push(`<div class="action-card"><h4>Gelen evrakta tespit edilen eksikler</h4><p>Bu alanlar bilgi amaçlı bildirilir; sistem gelen evrakı kullanıcı girdisiyle değiştirmez.</p><ul>${items}</ul></div>`);
  }

  const missing = (state.missing_information || []).filter((name) => !incomingMissing.includes(name));
  if (missing.length) {
    const controls = missing.map((name, index) => {
      const safeName = escapeHtml(name);
      const currentDraftValue = name === "sayi" ? (state.draft?.number?.value || "") : "";
      return `<div class="field-control"><label for="missing-field-${index}">${escapeHtml(fieldLabel(name))}</label><input id="missing-field-${index}" data-field="${safeName}" value="${escapeHtml(currentDraftValue)}" placeholder="${escapeHtml(suggestedValues[name] || "Bilgiyi girin")}" autocomplete="off" required />${name === "sayi" && currentDraftValue.includes("XXX") ? `<small>DETSİS kodu hazırdır; XXX alanlarını kurumun dosya planı ve EBYS kayıt numarasıyla değiştirin.</small>` : ""}</div>`;
    }).join("");
    cards.push(`<div class="action-card"><h4>Gönderilecek resmî yazının bilgileri</h4><p>Bunlar gelen evraka eklenmez; yalnız kurumun oluşturacağı yazıda kullanılır.</p><form class="field-form" id="missing-information-form">${controls}<div class="field-form-actions"><button class="mini-button is-secondary" id="fill-sample-values" type="button">Örnek değerleri doldur</button><button class="mini-button" type="submit">Yazı bilgilerini kaydet</button></div></form></div>`);
  }

  const strategyOptions = state.response_strategy_options || [];
  if (
    strategyOptions.length &&
    !state.selected_response_strategy &&
    !state.selected_response_custom_text
  ) {
    const controls = strategyOptions.map((option, index) => {
      const references = (option.reference_ids || []).join(", ");
      return `<div class="field-control"><label><input type="radio" name="response-strategy-option" value="${escapeHtml(option.option_id)}" ${index === 0 ? "checked" : ""} /> <strong>${escapeHtml(option.label)}</strong> — ${escapeHtml(option.description)}</label>${references ? `<small>Kaynaklar: ${escapeHtml(references)}</small>` : ""}</div>`;
    }).join("");
    const targetControls = `
      <div class="field-control"><strong>Taslak nereye gönderilecek?</strong>
        <label><input type="radio" name="delivery-target" value="citizen" checked /> Vatandaşa / dış başvuru sahibine cevap</label>
        <label><input type="radio" name="delivery-target" value="internal_unit" /> Alt birime havale / üst yazı</label>
        <label><input type="radio" name="delivery-target" value="both" /> İkisini de ayrı LaTeX ve PDF olarak hazırla</label>
      </div>`;
    cards.push(`<div class="action-card"><h4>Katman 3 — gönderim ve yanıt stratejisi</h4><p>Yazının kime gönderileceğini ve içerik yaklaşımını seçin.</p><form class="field-form" id="response-strategy-form">${targetControls}${controls}<div class="field-control"><label for="response-strategy-custom-text">Kendi talimatınız</label><textarea id="response-strategy-custom-text" rows="3" maxlength="4000" placeholder="Yalnız kendi stratejinizi seçtiyseniz nasıl yanıt verilmesini istediğinizi yazın"></textarea></div><div class="field-form-actions"><button class="mini-button" type="submit">Seçimleri kaydet ve LaTeX taslaklarını oluştur</button></div></form></div>`);
  }

  if (cards.length) return cards.join("");

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

function renderLayer2(state) {
  const layer = state.layer2_assessment;
  if (!layer) {
    return `<div class="empty-state"><h3>Katman 2 sonucu yok</h3><p>İçerik değerlendirmesi bu işlem için çalıştırılmadı.</p></div>`;
  }
  const layerStatusLabels = {
    completed: "Tamamlandı", abstained: "Kaynak yetersiz — çekimser",
    disabled: "Devre dışı", failed: "Başarısız", applicable: "Uygulanabilir",
    conditional: "Koşullu uygulanabilir", contextual_only: "Yalnız bağlamsal",
    uncertain: "Uygulanabilirlik belirsiz"
  };
  const relationshipLabels = {
    supports: "Talebi destekliyor", limits: "Talebi sınırlıyor",
    defines_procedure: "Usulü belirliyor", creates_obligation: "Yükümlülük doğuruyor",
    prohibits: "Yasaklıyor", unclear: "Hukuki ilişki belirsiz"
  };
  const riskLabels = { low: "Düşük risk", medium: "Orta risk", high: "Yüksek risk", uncertain: "Risk belirsiz" };
  const findings = (layer.findings || []).map((finding) => {
    const evidence = (finding.document_evidence_ids || []).join(", ") || "Belge kanıtı yok";
    const sourceTrail = (finding.equivalent_reference_ids || [finding.legal_reference_id]).filter(Boolean).join(", ");
    return `<article class="llm-finding is-informational"><div><strong>${escapeHtml(finding.issue || "Hukuki mesele")}</strong><span>${escapeHtml(layerStatusLabels[finding.applicability] || finding.applicability)}</span></div><p><strong>Evraktaki iddia/talep:</strong> ${escapeHtml(finding.document_statement || "")}</p><blockquote><strong>Kaynak alıntısı:</strong> ${escapeHtml(finding.legal_quote || "")}</blockquote><p><strong>Hukuki bağlam değerlendirmesi:</strong> ${escapeHtml(finding.legal_assessment || "")}</p><p><strong>Pratik etki:</strong> ${escapeHtml(finding.practical_effect || "")}</p><small>Kaynak metnine dayalı · ${escapeHtml(relationshipLabels[finding.legal_relationship] || finding.legal_relationship || "")} · ${escapeHtml(riskLabels[finding.risk_level] || finding.risk_level || "")} · ${escapeHtml(finding.legal_title || "")}${finding.legal_article ? ` · ${escapeHtml(finding.legal_article)}` : ""} · Kaynak izi: ${escapeHtml(sourceTrail)} · Evrak satırı: ${escapeHtml(evidence)} · Güven: %${safePercent(finding.confidence)}</small><div class="score-line"><i style="width:${safePercent(finding.confidence)}%"></i></div></article>`;
  }).join("");
  const tools = (layer.tool_trace || []).map((trace) => `<li><strong>Tur ${trace.round} · ${escapeHtml(trace.executed_tool)}</strong><small>${escapeHtml(trace.query || trace.note || "Araç çağrısı tamamlandı")} · Kaynak: ${(trace.returned_reference_ids || []).length} · Satır: ${(trace.returned_line_ids || []).length}</small></li>`).join("");
  const agents = (layer.agent_trace || []).map((trace) => `<li><strong>${escapeHtml(trace.role)} · ${escapeHtml(trace.status)}</strong><small>${escapeHtml(trace.model || layer.model)}${trace.failure_code ? ` · ${escapeHtml(trace.failure_code)}` : ""}${trace.note ? ` · ${escapeHtml(trace.note)}` : ""}</small></li>`).join("");
  const warnings = (layer.validation_warnings || []).map((warning) => `<li>${escapeHtml(warning)}</li>`).join("");
  return `<div class="overview-grid"><div class="info-card"><span>Katman 2 durumu</span><strong>${escapeHtml(layerStatusLabels[layer.status] || layer.status)}</strong><small>${escapeHtml(layer.model || "llm-large")} · Yalnız kaynak: ${layer.source_only_policy_applied ? "evet" : "hayır"}</small></div><div class="info-card"><span>İnsan incelemesi</span><strong>${layer.requires_human_review ? "Gerekli" : "Gerekli değil"}</strong><small>${escapeHtml(layer.document_type || "")} · ${escapeHtml(layer.operational_category || "")}</small></div><div class="info-card wide"><span>İçerik değerlendirmesi</span><strong>${escapeHtml(layer.summary || "Özet yok")}</strong></div></div>${findings ? `<div class="llm-audit-block"><strong>Kaynağa bağlı içerik bulguları</strong><div class="llm-findings">${findings}</div></div>` : `<div class="empty-state"><h3>Doğrulanmış bulgu yok</h3><p>Model önbilgisi kullanılmadı; yeterli ve uygulanabilir kaynak bulunamadığında sistem çekimser kaldı.</p></div>`}${warnings ? `<div class="llm-audit-block"><strong>Doğrulama uyarıları</strong><ul>${warnings}</ul></div>` : ""}${tools ? `<div class="llm-audit-block"><strong>Search-o1 araç izi</strong><ul class="llm-check-list">${tools}</ul></div>` : ""}${agents ? `<div class="llm-audit-block"><strong>Ajan izi</strong><ul class="llm-check-list">${agents}</ul></div>` : ""}`;
}

function draftValue(field) {
  return field?.value || "[DOLDURULACAK]";
}

function isInternalDraftNotice(paragraph) {
  const value = String(paragraph || "").toLocaleLowerCase("tr-TR");
  return value.includes("yarışma veri kümesine dayanır")
    || value.includes("mevzuatın güncelliği/yürürlüğü doğrulanmamıştır")
    || value.includes("hukuki dayanak: kullanılamaz");
}

function renderDraft(state) {
  const outputs = (state.layer3_outputs || []).length
    ? state.layer3_outputs
    : state.draft
      ? [{ label: "Resmî yazı taslağı", draft: state.draft, artifact: state.artifact, compliance: state.compliance }]
      : [];
  if (!outputs.length) return `<div class="empty-state"><h3>Taslak bulunmuyor</h3><p>Henüz bir resmî yazı taslağı oluşturulmadı.</p></div>`;
  return outputs.map((output) => {
    const draft = output.draft;
    const pdfUrl = safeArtifactUrl(output.artifact?.pdf_download_url);
    const texUrl = safeArtifactUrl(output.artifact?.tex_download_url);
    const paragraphs = (draft.paragraphs || []).filter((paragraph) => !isInternalDraftNotice(paragraph)).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
    return `<section class="layer3-draft-output"><h3>${escapeHtml(output.label || "Resmî yazı")}</h3><div class="artifact-actions">${texUrl ? `<a class="download-link" href="${texUrl}" download>↓ LaTeX (.tex) indir</a>` : ""}${pdfUrl ? `<a class="download-link" href="${pdfUrl}" download>↓ PDF indir</a>` : `<span class="download-link is-disabled">PDF hazırlanamadı</span>`}<span class="download-link is-disabled">Uygunluk: %${safePercent(output.compliance?.score)}</span></div><article class="draft-sheet"><div class="draft-letterhead"><strong>${escapeHtml(draftValue(draft.institution_name))}</strong></div><div class="draft-meta"><span><b>Sayı:</b> ${escapeHtml(draftValue(draft.number))}</span><span><b>Tarih:</b> ${escapeHtml(draftValue(draft.date))}</span><span><b>Konu:</b> ${escapeHtml(draftValue(draft.subject))}</span></div><div class="draft-recipient">${escapeHtml(draftValue(draft.recipient))}</div>${paragraphs}<div class="draft-signature"><strong>${escapeHtml(draftValue(draft.signer))}</strong><br />${escapeHtml(draftValue(draft.signer_title))}</div></article></section>`;
  }).join("");
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

function renderLlmDecisionAudit(step) {
  const summary = step.decision_summary
    ? `<div class="llm-decision-summary"><strong>Karar özeti</strong><p>${escapeHtml(step.decision_summary)}</p></div>`
    : "";
  const checks = (step.decision_checks || []).map((check) => {
    const hasScore = check.observed_score !== null && check.observed_score !== undefined;
    const hasThreshold = check.required_score !== null && check.required_score !== undefined;
    const score = hasScore ? Number(check.observed_score) : NaN;
    const threshold = hasThreshold ? Number(check.required_score) : NaN;
    const scoreText = Number.isFinite(score)
      ? ` · Skor: %${safePercent(score)}${Number.isFinite(threshold) ? ` / Eşik: %${safePercent(threshold)}` : ""}`
      : "";
    return `<li class="${check.passed ? "is-passed" : "is-failed"}"><span>${check.passed ? "✓" : "!"}</span><div><strong>${escapeHtml(check.name)}</strong><small>${escapeHtml(check.detail || "")}${escapeHtml(scoreText)}</small></div></li>`;
  }).join("");
  const checksBlock = checks
    ? `<div class="llm-audit-block"><strong>Sunucu karar kapıları</strong><ul class="llm-check-list">${checks}</ul></div>`
    : "";
  const repairBlock = step.repair_attempted
    ? `<div class="llm-repair ${step.repair_succeeded ? "is-success" : "is-warning"}"><strong>Kanıt düzeltme turu: ${step.repair_succeeded ? "başarılı" : "tamamlanamadı"}</strong><small>${escapeHtml(step.repair_detail || (step.repair_succeeded ? `Sağlayıcı durumu: ${step.repair_status || "başarılı"}` : `Sağlayıcı durumu: ${step.repair_status || "bilinmiyor"}; doğrulama hataları sürdü.`))}</small></div>`
    : "";
  const scoreBasisLabels = {
    agent_overall_confidence: "Ajan genel güveni",
    finding_confidence: "Bulgu güveni",
    server_validation: "Sunucu doğrulaması"
  };
  const findingStatusLabels = {
    accepted: "Kabul edildi",
    rejected: "Reddedildi",
    informational: "Bilgilendirme"
  };
  const findings = (step.findings || []).map((finding) => {
    const hasScore = finding.confidence !== null && finding.confidence !== undefined;
    const score = hasScore ? Number(finding.confidence) : NaN;
    const scoreText = Number.isFinite(score) ? `%${safePercent(score)}` : "Skor yok";
    const evidence = [
      ...(finding.document_evidence_ids || []).map((id) => `Satır: ${id}`),
      ...(finding.legal_reference_ids || []).map((id) => `Kaynak: ${id}`)
    ];
    const serverScores = [
      finding.legal_support_score !== null && finding.legal_support_score !== undefined ? `Mevzuat desteği: %${safePercent(finding.legal_support_score)}` : "",
      finding.document_presence_score !== null && finding.document_presence_score !== undefined ? `Belgede bulunma: %${safePercent(finding.document_presence_score)}` : "",
      finding.coordinate_confidence !== null && finding.coordinate_confidence !== undefined ? `Koordinat güveni: %${safePercent(finding.coordinate_confidence)}` : ""
    ].filter(Boolean);
    const legalQuote = finding.legal_evidence
      ? `<blockquote><strong>Mevzuat kanıtı:</strong> ${escapeHtml(finding.legal_evidence)}</blockquote>`
      : "";
    return `<article class="llm-finding is-${escapeHtml(finding.status || "informational")}"><div><strong>${escapeHtml(finding.label || finding.kind || "Bulgu")}</strong><span>${escapeHtml(findingStatusLabels[finding.status] || finding.status || "")}</span></div><p>${escapeHtml(finding.finding || "")}</p>${legalQuote}<small>${escapeHtml(scoreText)} · ${escapeHtml(scoreBasisLabels[finding.score_basis] || finding.score_basis || "Skor kaynağı belirtilmedi")}${serverScores.length ? ` · ${escapeHtml(serverScores.join(" · "))}` : ""}${evidence.length ? ` · ${escapeHtml(evidence.join(" · "))}` : ""}</small><div class="score-line"><i style="width:${Number.isFinite(score) ? safePercent(score) : 0}%"></i></div></article>`;
  }).join("");
  const findingsBlock = findings
    ? `<div class="llm-audit-block"><strong>Skorlu bulgular</strong><div class="llm-findings">${findings}</div></div>`
    : "";
  return `${summary}${repairBlock}${checksBlock}${findingsBlock}`;
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
      step.local_execution
        ? "Çalıştırma: yerel Ollama (cihaz dışına veri çıkışı yok)"
        : `Harici API izni: ${step.external_data_allowed ? "verildi" : "verilmedi"}`,
      `${step.local_execution ? "Yerel HTTP" : "Ağ"} çağrısı: ${step.network_attempted ? "yapıldı" : "yapılmadı"}`,
      step.failure_code ? `Hata kodu: ${step.failure_code}${step.retryable ? " (yeniden denenebilir)" : ""}` : "",
      step.redacted ? `Maskeleme: ${step.redaction_count || 0} alan` : ""
    ].filter(Boolean).join(" · ");
    return `<div class="timeline-item"><span class="timeline-dot" aria-hidden="true"></span><div><strong>${escapeHtml(role)} · ${escapeHtml(status)}</strong><p>${escapeHtml(llmStepDescription(step))}</p><small>${escapeHtml(metadata)}</small>${renderLlmDecisionAudit(step)}</div></div>`;
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
    <div class="result-headline"><div><span class="result-label">${escapeHtml(statusLabels[state.status] || state.status)}</span><h3>${escapeHtml(typeLabel(state.analysis?.general_document_type || state.analysis?.document_type))}</h3><p>${escapeHtml(state.next_step || "Sonucu inceleyin.")}</p></div><button class="document-id" id="copy-document-id" type="button" title="Evrak kimliğini kopyala">${escapeHtml(state.document_id)} ⧉</button></div>
    <nav class="result-tabs" role="tablist" aria-label="Sonuç bölümleri"><button class="result-tab is-active" type="button" role="tab" aria-selected="true" data-result-tab="overview">Genel</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="fields">Alanlar</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="sources">Kaynaklar</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="layer2">Katman 2</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="draft">Taslak</button><button class="result-tab" type="button" role="tab" aria-selected="false" data-result-tab="timeline">Akış</button></nav>
    <section class="tab-panel" data-tab-panel="overview">${renderOverview(state)}</section><section class="tab-panel" data-tab-panel="fields" hidden>${renderFields(state)}</section><section class="tab-panel" data-tab-panel="sources" hidden>${renderReferences(state)}</section><section class="tab-panel" data-tab-panel="layer2" hidden>${renderLayer2(state)}</section><section class="tab-panel" data-tab-panel="draft" hidden>${renderDraft(state)}</section><section class="tab-panel" data-tab-panel="timeline" hidden>${renderTimeline(state)}</section>`;

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
  document.querySelector("#response-strategy-form")?.addEventListener("submit", handleResponseStrategySubmit);
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
    const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/information`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, compile_pdf: true })
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
    const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/approval`, {
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

async function handleResponseStrategySubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector("button[type='submit']");
  const selected = form.querySelector("input[name='response-strategy-option']:checked");
  const optionId = selected ? selected.value : null;
  const target = form.querySelector("input[name='delivery-target']:checked")?.value || "citizen";
  const customText = form.querySelector("#response-strategy-custom-text").value.trim();
  submit.disabled = true;
  submit.textContent = "Kaynak-bağlı taslak hazırlanıyor…";
  try {
    const state = await requestJson(
      `/api/v1/processes/${encodeURIComponent(currentState.document_id)}/response-strategy`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          option_id: optionId,
          custom_text: customText || null,
          delivery_target: target,
          compile_pdf: true
        })
      }
    );
    renderState(state);
    showToast("Yanıt stratejisi kaydedildi ve Katman 3 taslağı oluşturuldu.", "success");
  } catch (error) {
    showToast(error.message);
    submit.disabled = false;
    submit.textContent = "Stratejiyi seç ve taslağı oluştur";
  }
}

async function checkReadiness() {
  const pill = document.querySelector("#health-pill");
  const label = document.querySelector("#health-label");
  const environmentBadge = document.querySelector("#environment-badge");
  pill.classList.remove("is-online", "is-offline");
  try {
    const response = await fetch(apiUrl("/api/v1/system/readiness"), { headers: { "Accept": "application/json" } });
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
      const started = await requestJson("/api/v1/processes/file/start?compile_pdf=true", { method: "POST", body: formData });
      state = await pollProcess(started.document_id);
    } else {
      const started = await requestJson("/api/v1/processes/text/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textArea.value.trim(), source_name: `${activeScenario}-arayuz-senaryosu.txt`, compile_pdf: true })
      });
      state = await pollProcess(started.document_id);
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
document.querySelector("#api-docs-link").href = apiUrl("/docs");
checkReadiness();
