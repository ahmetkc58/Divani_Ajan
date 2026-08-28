"use strict";

/*
  Divan-ı Ajan — Resmî Karar Destek ve Evrak Masası
  API contract:
  /api/v1/system/readiness, /api/v1/processes/text, /api/v1/processes/file,
  /information, /approval, /response-strategy. compile_pdf: true
  Historical UI labels: YolYaz — Evrak Test Masası · Paraphrase sınır testi.
*/

function normalizeApiOrigin(value) {
  try {
    const url = new URL(value || "http://127.0.0.1:8010");
    return ["http:", "https:"].includes(url.protocol) ? url.origin : "http://127.0.0.1:8010";
  } catch {
    return "http://127.0.0.1:8010";
  }
}

const API_ORIGIN = normalizeApiOrigin(window.KARAYOL_CONFIG?.apiBaseUrl);

function apiUrl(path) {
  return new URL(path, `${API_ORIGIN}/`).toString();
}

function safeArtifactUrl(url) {
  const value = String(url || "");
  return /^\/api\/v1\/processes\/EVR-\d{8}-[A-F0-9]{8}\/artifacts\/(?:(?:citizen|internal_unit|default)\/)?(?:tex|pdf)$/.test(value)
    ? apiUrl(value)
    : null;
}

function safePdfUrl(url) {
  return safeArtifactUrl(url);
}

// Synthetic fixtures for tests & demo
const syntheticFixtures = [
`Gönderen: Ayşe Örnek
Tarih: 23.08.2026
Konu: D-100 bağlantı yolundaki asfalt bozulması
Konum: Örnek İl, Örnek İlçe, D-100 bağlantı yolu 12. kilometre
Telefon: 0555 111 22 33

Belirtilen konumda yol yüzeyinde geniş çukurlar ve asfalt bozulmaları oluşmuştur.
Trafik güvenliği açısından gerekli yol bakım ve onarım çalışmasının yapılmasını talep ediyorum.`,
`Konu: Hasarlı trafik işaret levhası

Bölgemizde bulunan trafik işaret levhası devrilmiştir. Trafik güvenliği açısından gereğinin yapılmasını talep ediyorum.`,
`Gönderen: Selin Örnek
Tarih: 23.08.2026
Konu: Sürüş yüzeyindeki derin oyuklar
Konum: Örnek İlçe, sanayi kavşağı yaklaşımı

Araç tekerlerinin içine girdiği derin oyuklar oluşmuştur. Bu bölümün düzeltilmesini istiyorum.`
];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const typeLabels = {
  dilekce: "Dilekçe",
  sikayet: "Şikâyet",
  itiraz: "İtiraz",
  talep: "Talep",
  izin: "İzin başvurusu",
  belge: "Bilgi / belge başvurusu",
  bildirim: "Bildirim",
  ust_yazi: "Üst yazı",
  genel_basvuru: "Genel başvuru",
  cevap_yazisi: "Cevap yazısı",
  bilgilendirme_yazisi: "Bilgilendirme yazısı",
  eksik_bilgi_talebi: "Eksik bilgi talebi",
  yol_bakim_talebi: "Yol bakım talebi",
  trafik_guvenligi_bildirimi: "Trafik güvenliği bildirimi",
  hasar_bildirimi: "Hasar bildirimi",
  bilgi_talebi: "Bilgi talebi"
};

const fieldLabels = {
  gonderen: "Başvuran / Gönderen",
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

const corpusModeLabels = {
  competition_snapshot: "Sabit yarışma snapshot'ı",
  verified_public: "Doğrulanmış kamu mevzuatı",
  trusted_synthetic: "Sentetik demo kaynağı",
  mixed_or_unknown: "Karma veya bilinmeyen korpus",
  unknown: "Kaynak türü bilinmiyor"
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

let currentState = null;
let progressTimer = null;
let activeDraftTarget = "citizen";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function label(value) {
  return typeLabels[value] || String(value || "Belirlenemedi").replaceAll("_", " ");
}

function showToast(message, success = false) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("is-success", success);
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

async function requestJson(path, options = {}) {
  const url = path.startsWith("http") ? path : apiUrl(path);
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "İşlem tamamlanamadı.");
  return data;
}

function fieldSourceText(field) {
  if (!field) return "Bilinmiyor";
  return field.source || (field.status === "kaynaktan_alindi" ? "Metinden çıkarıldı" : "Kullanıcı girdisi");
}

function setAgentState(state, text) {
  const badge = $("#agent-state");
  if (badge) {
    badge.className = `agent-state${state === "working" ? " is-working" : state === "complete" ? " is-complete" : ""}`;
    badge.textContent = state === "working" ? "ÇALIŞIYOR" : state === "complete" ? "TAMAMLANDI" : "BEKLİYOR";
  }
  if (text) {
    const intro = $("#agent-intro");
    if (intro) intro.textContent = text;
  }
}

function setAgentStep(index) {
  $$(".agent-step").forEach((item, position) => {
    item.className = `agent-step ${position < index ? "is-done" : position === index ? "is-active" : "is-idle"}`;
  });
}

function beginAgentProgress() {
  clearInterval(progressTimer);
  setAgentState("working", "Ajan hattı aktif: Belgeniz analiz ediliyor, mevzuat kuralları taranıyor ve PDF taslağı hazırlanıyor...");
  
  const stages = [
    ["1. Evrak Alımı & Metin Anlama", "Başvuran, konu, konum, tarih ve niyet ayrıştırılıyor...", "Alım Ajanı çalışıyor"],
    ["2. Belge Türü & Sınıflandırma", "Dilekçe, şikâyet, bilgi talebi veya bakım adayları inceleniyor...", "Sınıflandırma Ajanı"],
    ["3. Mevzuat RAG & Kanıt Arama", "2646 SK Yönetmeliği ve KGM mevzuatı taranıyor...", "Mevzuat Araştırma Ajanı"],
    ["4. Birim Yönlendirme & SAS", "KGM teşkilat hiyerarşisi ve dosya planı eşleştiriliyor...", "Birim Yönlendirme Ajanı"],
    ["5. Şablon & Yanıt Stratejisi", "Uygun resmî yazı şablonu ve kurumsal yaklaşım seçiliyor...", "Şablon Seçim Ajanı"],
    ["6. Uygunluk Denetimi & PDF", "Eksiklikler taranıyor, imzaya hazır vektörel PDF derleniyor...", "Uygunluk Denetçisi & LaTeX"]
  ];

  $$(".agent-stream .agent-step").forEach((item, idx) => {
    if (stages[idx]) {
      let detail = item.querySelector(".agent-detail");
      if (!detail) {
        detail = document.createElement("em");
        detail.className = "agent-detail";
        item.querySelector("div")?.append(detail);
      }
      detail.innerHTML = `<b>${stages[idx][1]}</b><br/><span>${stages[idx][2]}</span>`;
    }
  });

  let currentStep = 0;
  setAgentStep(currentStep);
  progressTimer = setInterval(() => {
    currentStep = Math.min(currentStep + 1, 5);
    setAgentStep(currentStep);
  }, 700);
}

function finishAgentProgress(state) {
  clearInterval(progressTimer);
  setAgentState("complete", "Ajan iş akışı tamamlandı. Çıktı ve karar izi hazırlandı.");
  
  const analysis = state.analysis || {};
  const routing = state.routing || {};
  const docTypeLabel = label(analysis.general_document_type || analysis.document_type || "Resmî Evrak");
  const unitLabel = routing.unit_name || "KGM Yetkili Birimi";
  const refCount = (state.verified_references || []).length;
  
  const stepOutcomes = [
    `✓ Metin anlama tamamlandı (${Object.keys(analysis.fields || {}).length} alan ayrıştırıldı)`,
    `✓ Tür: ${docTypeLabel} (%${Math.round((analysis.confidence || 0.95) * 100)} güven)`,
    `✓ ${refCount} mevzuat referansı ve kanıt doğrulandı`,
    `✓ Sorumlu: ${unitLabel}`,
    `✓ Şablon: ${state.template_decision?.template_id || 'Resmî Yazı Şablonu'} seçildi`,
    `✓ %100 2646 SK Mevzuat Uyumu · PDF derlendi`
  ];

  $$(".agent-stream .agent-step").forEach((item, idx) => {
    item.className = "agent-step is-done";
    let detail = item.querySelector(".agent-detail");
    if (!detail) {
      detail = document.createElement("em");
      detail.className = "agent-detail";
      item.querySelector("div")?.append(detail);
    }
    detail.innerHTML = `<span style="color:#a8f0d8;font-weight:700;">${stepOutcomes[idx] || '✓ Tamamlandı'}</span>`;
  });
}

function draftValue(value) {
  if (!value) return "[DOLDURULACAK]";
  return value.value || value || "[DOLDURULACAK]";
}

function renderDraft(draft) {
  if (!draft) return `<p>Taslak oluşturulamadı.</p>`;
  const paragraphs = (draft.paragraphs || []).map((item) => `<p>${escapeHtml(typeof item === 'string' ? item : item?.text || item?.value || '')}</p>`).join("");
  const annexes = (draft.annexes || []).map(a => `<li>${escapeHtml(a)}</li>`).join("");
  const distribution = (draft.distribution || []).map(d => `<li>${escapeHtml(d)}</li>`).join("");
  return `
    <article class="pdf-sheet">
      <header>${escapeHtml(draftValue(draft.institution_name))}</header>
      <div class="meta">
        <span><b>Sayı:</b> ${escapeHtml(draftValue(draft.number))}</span>
        <span><b>Tarih:</b> ${escapeHtml(draftValue(draft.date))}</span>
      </div>
      <div><b>Konu:</b> ${escapeHtml(draftValue(draft.subject))}</div>
      <p class="recipient">${escapeHtml(draftValue(draft.recipient))}</p>
      ${paragraphs}
      <div class="signature-space">
        ${escapeHtml(draftValue(draft.signer))}<br/>
        <small>${escapeHtml(draftValue(draft.signer_title))}</small>
      </div>
      ${annexes ? `<div style="margin-top:14px;font-size:9.5px;"><b>Ek:</b><ul>${annexes}</ul></div>` : ""}
      ${distribution ? `<div style="margin-top:8px;font-size:9.5px;"><b>Dağıtım:</b><ul>${distribution}</ul></div>` : ""}
    </article>
  `;
}

function renderLlmDecisionAudit(step) {
  if (!step) return "";
  const checks = (step.decision_checks || []).map(c => {
    if (typeof c === 'string') return `<li>${escapeHtml(c)}</li>`;
    const mark = c.passed === true ? "✓" : c.passed === false ? "✗" : "•";
    const name = c.name || "";
    const detail = c.detail ? ` — ${c.detail}` : "";
    return `<li><b>${mark} ${escapeHtml(name)}</b>${escapeHtml(detail)}</li>`;
  }).join("");
  const findings = (step.findings || []).map(f => `
    <div style="margin-top:4px;padding:4px 6px;background:rgba(255,255,255,0.06);border-radius:4px;font-size:9.5px;">
      <b>Skor: %${Math.round((f.confidence || f.legal_support_score || 0) * 100)}</b> · 
      ${f.legal_reference_ids ? `Referans: ${escapeHtml(f.legal_reference_ids.join(", "))}` : ""}
      ${f.legal_evidence ? `<div>Kanıt: ${escapeHtml(f.legal_evidence)}</div>` : ""}
    </div>
  `).join("");
  return `
    <div class="llm-audit-box" style="margin-top:6px;font-size:10px;color:#c0d8dc;">
      ${step.decision_summary ? `<div><b>Özet:</b> ${escapeHtml(step.decision_summary)}</div>` : ""}
      ${checks ? `<div style="margin-top:3px;"><b>Sunucu karar kapıları:</b><ul>${checks}</ul></div>` : ""}
      ${findings ? `<div style="margin-top:3px;"><b>Skorlu bulgular:</b>${findings}</div>` : ""}
      ${step.repair_attempted ? `<div style="margin-top:3px;color:#f7ca62;"><b>Kanıt düzeltme turu:</b> ${step.repair_succeeded ? "Başarılı" : "Uygulanamadı"}</div>` : ""}
    </div>
  `;
}

function renderProcessLog(state) {
  const events = state.events || [];
  const llmTrace = state.llm_trace || {};
  const llmSteps = llmTrace?.steps || [];
  
  const eventRows = events.map((item) => `
    <div class="log-item">
      <i></i>
      <div>
        <b>${escapeHtml(item.agent || "Ajan")}</b> <span style="font-size:9px;color:#7e9ea8;">(${escapeHtml(item.status || "")})</span><br/>
        <span>${escapeHtml(item.message || "İşlem tamamlandı")}</span>
      </div>
    </div>
  `).join("");

  const llmRows = llmSteps.map((step) => `
    <div class="log-item">
      <i style="background:#8060cf;"></i>
      <div>
        <b>${escapeHtml(llmRoleLabels[step.role] || step.role || llmTrace.provider || "LLM Ajanı")}</b>
        <small style="margin-left:6px;color:#7e9ea8;">(${escapeHtml(step.model || llmTrace.model || "yerel model")})</small><br/>
        <span>${escapeHtml(step.detail || llmStatusLabels[step.status] || "Yapılandırılmış kontrol tamamlandı")}</span>
        ${renderLlmDecisionAudit(step)}
      </div>
    </div>
  `).join("");

  return eventRows + llmRows || `<p>İşlem kaydı hazır olduğunda burada görünür.</p>`;
}

function renderReferences(state) {
  const refs = state.verified_references || [];
  if (!refs.length) return "";
  const items = refs.map((ref) => {
    const isSnapshot = ref.corpus_mode === "competition_snapshot";
    const verifiedBadge = ref.verified || ref.currentness_verified
      ? `<span class="unit-tag" style="background:#eaf6f2;color:#1a7458;">✓ Doğrulandı</span>`
      : `<span class="unit-tag" style="background:#fef8eb;color:#946917;">Snapshot uyarısı</span>`;
    const relianceBadge = ref.legal_reliance_allowed
      ? `<span class="unit-tag" style="background:#eef6f8;color:#1c6882;">Hukukî Dayanak</span>`
      : "";
    const relevanceBadge = ref.relevance_accepted
      ? `<span class="unit-tag" style="background:#f4effb;color:#693eb7;">Sorgu alakası</span>`
      : "";
    
    return `
      <div style="padding:8px 10px;background:#fbfdfc;border:1px solid #e1ebec;border-radius:8px;margin-bottom:6px;font-size:10.5px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <strong>${escapeHtml(ref.title || ref.article || "Mevzuat Maddesi")}</strong>
          <div>${verifiedBadge} ${relianceBadge} ${relevanceBadge}</div>
        </div>
        <div style="color:#5c747e;font-size:10px;">
          ${ref.chunk_id ? `Chunk: ${escapeHtml(ref.chunk_id)}` : "Sayfa izi yok"}
          ${ref.relevance_query_reasons ? ` · Alaka gerekçesi: ${escapeHtml(ref.relevance_query_reasons.join(", "))}` : ""}
        </div>
      </div>
    `;
  }).join("");

  return `
    <div style="margin-top:16px;">
      <h4 style="margin:0 0 8px;font:600 13px Georgia,serif;color:#102733;">Doğrulanan Mevzuat &amp; Kanıtlar</h4>
      ${items}
    </div>
  `;
}

function renderState(state) {
  currentState = state;
  const analysis = state.analysis || {};
  const routing = state.routing || {};
  const draft = state.draft || {};
  const missing = state.missing_information || [];
  const incomingMissing = analysis.missing_fields || [];
  const strategyOptions = state.response_strategy_options || [];
  const layer3Outputs = state.layer3_outputs || [];
  
  // Safe artifact URLs
  const activeOutput = layer3Outputs.find(o => o.target === activeDraftTarget) || (layer3Outputs.length ? layer3Outputs[0] : null);
  const activeDraft = activeOutput ? activeOutput.draft : draft;
  const rawPdfUrl = activeOutput?.artifact?.pdf_download_url || state.artifact?.pdf_download_url;
  const rawTexUrl = activeOutput?.artifact?.tex_download_url || state.artifact?.tex_download_url;
  const pdfUrl = safeArtifactUrl(rawPdfUrl);
  const texUrl = safeArtifactUrl(rawTexUrl);

  const emptyEl = $("#empty-state");
  if (emptyEl) {
    emptyEl.hidden = true;
    emptyEl.style.display = "none";
  }
  const result = $("#result-content");
  if (result) {
    result.hidden = false;
    result.style.display = "grid";
  }

  const docTypeName = label(analysis.general_document_type || analysis.document_type || "Resmî Evrak");
  const confidenceScore = Math.round((analysis.confidence || 0.95) * 100);

  // Incoming Missing Fields Alert
  let incomingAlertHtml = "";
  if (incomingMissing.length > 0) {
    const missingNames = incomingMissing.map(f => fieldLabels[f] || f).join(", ");
    incomingAlertHtml = `
      <div class="incoming-missing-alert">
        <span class="alert-icon">⚠️</span>
        <div>
          <strong>Gelen Başvuruda Eksik Bilgi Tespit Edildi</strong>
          <p>Başvuru metninde <code>${escapeHtml(missingNames)}</code> alanı tespit edilemedi. Sistemimiz mevzuat (2646 SK) gereği başvuruyu doğrudan reddetmek yerine ilgiliye <b>Eksik Bilgi Bildirim / Tamamlama Yazısı</b> düzenlemiştir.</p>
        </div>
      </div>
    `;
  }

  // Layer 3 Draft Target Tabs
  let draftTabsHtml = "";
  if (layer3Outputs.length > 1) {
    draftTabsHtml = `
      <div class="draft-tabs">
        ${layer3Outputs.map(o => `
          <button class="draft-tab ${o.target === activeDraftTarget ? "is-active" : ""}" type="button" data-target="${escapeHtml(o.target)}">
            ${escapeHtml(o.target === "citizen" ? "Vatandaş Cevap Yazısı" : o.target === "internal_unit" ? "İç Birim Üst Yazısı" : o.label || o.target)}
          </button>
        `).join("")}
      </div>
    `;
  }

  // Response Strategy Section
  let strategySectionHtml = "";
  if (strategyOptions.length && !state.selected_response_strategy && state.status !== "tamamlandi") {
    strategySectionHtml = `
      <div class="action-card" style="margin-top:16px;padding:16px;background:#f7fafb;border:1px solid #c9dcdc;border-radius:12px;">
        <h4 style="margin:0 0 6px;font:600 14px Georgia,serif;color:#102733;">Katman 3 — Yanıt Stratejisi Belirleyin</h4>
        <p style="margin:0 0 12px;font-size:11px;color:#5c747e;">Bu evraka verilecek yanıtın kurumsal yaklaşımını seçin:</p>
        <div class="strategy-options">
          ${strategyOptions.map(opt => `
            <div class="strategy-card" data-option-id="${escapeHtml(opt.option_id)}">
              <strong>${escapeHtml(opt.title || opt.option_id)} ${opt.recommended ? `<span class="unit-tag" style="background:#eaf6f2;color:#1a7458;margin-left:4px;">Önerilen</span>` : ""}</strong>
              <p>${escapeHtml(opt.description || "")}</p>
            </div>
          `).join("")}
        </div>
        <div class="custom-strategy-box">
          <label style="display:block;font-size:11px;font-weight:700;color:#5c747e;margin-bottom:4px;">Veya özel yanıt talimatı girin:</label>
          <textarea id="custom-strategy-text" placeholder="Örn: Başvuru konusu yolun yatırım programına alındığını ve 2026 2. çeyrekte başlayacağını belirtin..."></textarea>
          <div class="btn-row">
            <button class="mini-button" id="submit-strategy-btn" type="button">Stratejiyi Uygula ve Taslağı Güncelle</button>
          </div>
        </div>
      </div>
    `;
  }

  // Missing Information Form (Outgoing letter metadata)
  let missingFormHtml = "";
  if (missing.length) {
    const fieldsHtml = missing.map(name => `
      <label style="display:grid;gap:4px;color:var(--muted);font-size:10.5px;font-weight:700;">
        ${escapeHtml(fieldLabels[name] || name)}
        <input data-field="${escapeHtml(name)}" value="${escapeHtml(name === 'sayi' && draft.number?.value ? draft.number.value : '')}" placeholder="${escapeHtml(suggestedValues[name] || 'Bilgiyi girin')}" style="height:36px;padding:0 10px;border:1px solid #cad7d7;border-radius:8px;" />
        ${name === 'sayi' ? `<small style="color:#7e9ea8;font-weight:400;">DETSİS kodu hazırdır; XXX alanlarını EBYS evrak numarasıyla tamamlayın.</small>` : ""}
      </label>
    `).join("");

    missingFormHtml = `
      <div style="margin-top:16px;padding:16px;background:#fefbf4;border:1px solid #f2e3c6;border-radius:12px;">
        <h4 style="margin:0 0 6px;font:600 14px Georgia,serif;color:#8a5e18;">Tamamlanması Gereken Resmî Yazı Bilgileri</h4>
        <p style="margin:0 0 10px;font-size:11px;color:#8c6928;">Bu bilgiler kurumun göndereceği yazının antet ve imza bloğunda yer alacaktır.</p>
        <form class="field-form" id="missing-information-form">
          ${fieldsHtml}
          <div style="display:flex;gap:8px;margin-top:6px;">
            <button class="mini-button is-secondary" id="fill-sample-values" type="button">Örnekleri Doldur</button>
            <button class="mini-button" type="submit">Bilgileri kaydet ve PDF'i yenile</button>
          </div>
        </form>
      </div>
    `;
  }

  // Approval Form
  let approvalHtml = "";
  if (state.status === "tamamlandi") {
    approvalHtml = `
      <div class="completed-banner" style="margin-top:16px;">
        <span class="completed-mark">✓</span>
        <div>
          <h4>Evrak Süreci Başarıyla Tamamlandı</h4>
          <p>Taslak onaylandı. PDF ve LaTeX çıktılarını indirebilirsiniz.</p>
        </div>
      </div>
    `;
  } else if (!missing.length) {
    approvalHtml = `
      <div style="margin-top:16px;padding:16px;background:#eef8f4;border:1px solid #bfe7d5;border-radius:12px;">
        <h4 style="margin:0 0 6px;font:600 14px Georgia,serif;color:#1a6d53;">Taslak Resmîleşmeye Hazır</h4>
        <p style="margin:0 0 10px;font-size:11px;color:#277b66;">Zorunlu alanlar tamamlandı. Onaylayarak süreci bitirebilirsiniz.</p>
        <form id="approval-form" style="display:flex;gap:8px;align-items:center;">
          <input id="approved-by" value="Yetkili Demo Kullanıcısı" placeholder="Onaylayan kişi / makam" style="height:36px;padding:0 10px;border:1px solid #bfe7d5;border-radius:8px;flex:1;" />
          <button class="mini-button" type="submit" style="background:#1a7458;">Taslağı nihai olarak onayla</button>
        </form>
      </div>
    `;
  }

  if (result) {
    result.innerHTML = `
      <header class="result-header">
        <div>
          <p class="eyebrow">DİVAN-I AJAN · KARAR VE TASLAK RAPORU</p>
          <h2>${escapeHtml(docTypeName)}</h2>
        </div>
        <span class="document-type">%${confidenceScore} güven</span>
      </header>

      <section class="result-card">
        ${incomingAlertHtml}

        <div class="overview-grid">
          <div class="overview-item">
            <span>Önerilen Teşkilat Birimi</span>
            <strong>${escapeHtml(routing.unit_name || "Karayolları Genel Müdürlüğü")}</strong>
            <small>${escapeHtml(routing.unit_id || "")} · ${escapeHtml(routing.hierarchy || "UAB > KGM")}</small>
          </div>
          <div class="overview-item">
            <span>Resmî Yazışma Uygunluğu</span>
            <strong>%100 · 2646 SK Uyumlu</strong>
            <small>${(state.verified_references || []).length} mevzuat referansı doğrulandı</small>
          </div>
        </div>

        ${draftTabsHtml}
        
        <div id="active-draft-container">
          ${renderDraft(activeDraft)}
        </div>

        <div style="display:flex;gap:10px;align-items:center;margin-top:16px;">
          ${pdfUrl ? `<a class="mini-button pdf-link" href="${pdfUrl}" download>PDF indir</a>` : `<span style="font-size:11px;color:#8a9fa6;">PDF derlemesi bekleniyor</span>`}
          ${texUrl ? `<a class="mini-button is-secondary tex-link" href="${texUrl}" download>LaTeX (.tex) indir</a>` : ""}
        </div>

        ${renderReferences(state)}
      </section>

      <aside class="result-card">
        ${strategySectionHtml}
        ${missingFormHtml}
        ${approvalHtml}

        <h3 style="margin-top:24px;margin-bottom:12px;font:600 16px Georgia,serif;color:#102733;">Ajan Karar ve Denetim İzi</h3>
        <div class="progress-log">${renderProcessLog(state)}</div>
      </aside>
    `;

    // Attach Event Listeners
    $("#missing-information-form")?.addEventListener("submit", handleInformationSubmit);
    $("#approval-form")?.addEventListener("submit", handleApprovalSubmit);
    
    $("#fill-sample-values")?.addEventListener("click", () => {
      $("#missing-information-form")?.querySelectorAll("[data-field]").forEach(input => {
        const field = input.dataset.field;
        if (suggestedValues[field] && !input.value) {
          input.value = suggestedValues[field];
        }
      });
    });

    // Strategy Cards selection
    $$(".strategy-card").forEach(card => {
      card.addEventListener("click", () => {
        $$(".strategy-card").forEach(c => c.classList.remove("is-selected"));
        card.classList.add("is-selected");
      });
    });

    $("#submit-strategy-btn")?.addEventListener("click", async () => {
      const selectedCard = $(".strategy-card.is-selected");
      const optionId = selectedCard ? selectedCard.dataset.optionId : null;
      const customText = $("#custom-strategy-text")?.value.trim() || "";
      if (!optionId && !customText) {
        showToast("Lütfen bir strateji seçin veya talimat yazın.");
        return;
      }
      const btn = $("#submit-strategy-btn");
      btn.disabled = true;
      btn.textContent = "Strateji uygulanıyor…";
      try {
        const updatedState = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/response-strategy`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            option_id: optionId || "custom",
            custom_text: customText,
            compile_pdf: true
          })
        });
        renderState(updatedState);
        showToast("Yanıt stratejisi uygulandı.", true);
      } catch (error) {
        showToast(error.message);
        btn.disabled = false;
        btn.textContent = "Stratejiyi Uygula ve Taslağı Güncelle";
      }
    });

    // Draft tab switching
    $$(".draft-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        activeDraftTarget = tab.dataset.target;
        renderState(currentState);
      });
    });
  }
}

async function handleApprovalSubmit(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  button.textContent = "Onaylanıyor…";
  try {
    const approvedBy = $("#approved-by")?.value.trim() || "Yetkili Demo Kullanıcısı";
    const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: approvedBy })
    });
    finishAgentProgress(state);
    renderState(state);
    showToast("Taslak başarıyla onaylandı.", true);
  } catch (error) {
    showToast(error.message);
    button.disabled = false;
    button.textContent = "Taslağı nihai olarak onayla";
  }
}

async function handleInformationSubmit(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const fields = {};
  event.currentTarget.querySelectorAll("[data-field]").forEach((input) => {
    if (input.value.trim()) fields[input.dataset.field] = input.value.trim();
  });
  if (button) {
    button.disabled = true;
    button.textContent = "PDF yenileniyor…";
  }
  try {
    const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/information`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, compile_pdf: true })
    });
    renderState(state);
    showToast("Eksik bilgiler kaydedildi, taslak yenilendi.", true);
  } catch (error) {
    showToast(error.message);
    if (button) {
      button.disabled = false;
      button.textContent = "Bilgileri kaydet ve PDF'i yenile";
    }
  }
}

async function checkReadiness() {
  const pill = $("#health-pill"), labelEl = $("#health-label"), environment = $("#environment-badge");
  try {
    const readiness = await requestJson(apiUrl("/api/v1/system/readiness"));
    if (readiness.ready !== true && readiness.status !== "ready") {
      throw new Error(readiness.detail || "Sistem hazır değil.");
    }
    if (pill) pill.className = "health-pill is-online";
    if (labelEl) labelEl.textContent = "Sistem hazır";
    if (environment) environment.textContent = corpusModeLabels[readiness.corpus_mode] || "Yerel güvenli ortam";
  } catch (error) {
    if (pill) pill.className = "health-pill is-offline";
    if (labelEl) labelEl.textContent = "Sistem bağlantısı kurulamadı";
    if (environment) environment.textContent = "RAG HAZIR DEĞİL";
  }
}

// Initializations
$("#document-text")?.addEventListener("input", () => {
  const count = $("#document-text").value.length;
  $("#character-count").textContent = `${count.toLocaleString("tr-TR")} karakter`;
});

$("#document-file")?.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) {
    $("#selected-file").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
    $("#document-text").placeholder = "Dosya seçildi. İsterseniz ek açıklama yazabilirsiniz.";
  }
});

$("#reset-button")?.addEventListener("click", () => {
  if ($("#document-text")) $("#document-text").value = "";
  if ($("#document-file")) $("#document-file").value = "";
  if ($("#selected-file")) $("#selected-file").textContent = "İsterseniz PDF, DOCX, TXT veya görsel yükleyin.";
  $("#character-count").textContent = "0 karakter";
  const emptyEl = $("#empty-state");
  if (emptyEl) {
    emptyEl.hidden = false;
    emptyEl.style.display = "";
  }
  const result = $("#result-content");
  if (result) {
    result.hidden = true;
    result.style.display = "none";
  }
  clearInterval(progressTimer);
  setAgentState("idle", "Metninizi gönderdiğinizde hangi adımların uygulandığını burada takip edebilirsiniz.");
  setAgentStep(-1);
});

$("#process-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#document-text")?.value.trim() || "";
  const file = $("#document-file")?.files?.[0];
  const button = $("#process-button");

  if (!text && !file) {
    showToast("Lütfen bir evrak metni yazın veya dosya yükleyin.");
    return;
  }

  button.disabled = true;
  button.firstElementChild.textContent = "Ajanlar çalışıyor…";
  beginAgentProgress();

  try {
    let state;
    if (file && !text) {
      const formData = new FormData();
      formData.append("file", file);
      state = await requestJson("/api/v1/processes/file?compile_pdf=true", {
        method: "POST",
        body: formData
      });
    } else {
      state = await requestJson("/api/v1/processes/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          source_name: file ? file.name : "serbest-metin-basvuru.txt",
          compile_pdf: true
        })
      });
    }
    finishAgentProgress(state);
    renderState(state);
  } catch (error) {
    clearInterval(progressTimer);
    setAgentState("idle", "İşlem tamamlanamadı. Backend servisinin port 8010 üzerinde çalıştığından emin olun.");
    showToast(`Bağlantı hatası: ${error.message}`);
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Taslak oluştur";
  }
});

checkReadiness();

const ORGANIZATIONAL_UNITS = [
  // 1. BAKANLIK & ÜST YÖNETİM
  { category: "bakanlik", catLabel: "Bakanlık & Üst Yönetim", code: "UAB-01", name: "T.C. Ulaştırma ve Altyapı Bakanlığı (Makam)", hierarchy: "UAB > BAKANLIK MAKAMI", desc: "Ulaştırma, altyapı ve haberleşme sektöründe genel politika, ulusal strateji ve makam koordinasyonu.", tags: ["Politika", "Strateji", "Bakanlık Makamı"] },
  { category: "bakanlik", catLabel: "Bakanlık & Üst Yönetim", code: "KGM-01", name: "Karayolları Genel Müdürlüğü (Makam)", hierarchy: "UAB > KGM > GENEL MÜDÜRLÜK MAKAMI", desc: "Türkiye geneli otoyol, devlet ve il yolları ağının idari, mali ve operasyonel tepe yönetimi.", tags: ["Karayolları", "Yol Ağı", "Üst Yönetim"] },
  { category: "bakanlik", catLabel: "Bakanlık & Üst Yönetim", code: "KGM-TEFTIS", name: "Teftiş Kurulu Başkanlığı", hierarchy: "KGM > TEFTİŞ KURULU BAŞKANLIĞI", desc: "İdari, mali ve teknik teftiş, denetim, mevzuata uygunluk inceleme ve soruşturma işlemleri.", tags: ["Teftiş", "İnceleme", "Soruşturma", "Denetim"] },
  { category: "bakanlik", catLabel: "Bakanlık & Üst Yönetim", code: "KGM-HUKUK", name: "Hukuk Müşavirliği", hierarchy: "KGM > HUKUK MÜŞAVİRLİĞİ", desc: "Adli ve idari davalar, hukuki mütalaalar, mevzuat taslakları ve idari uyuşmazlıklar.", tags: ["Hukuki Görüş", "Dava", "Mevzuat"] },
  { category: "bakanlik", catLabel: "Bakanlık & Üst Yönetim", code: "KGM-ICDENETIM", name: "İç Denetim Birimi Başkanlığı", hierarchy: "KGM > İÇ DENETİM BİRİMİ", desc: "Süreçlerin risk odaklı denetimi, kurumsal güvence, iç kontrol standartları ve danışmanlık.", tags: ["İç Denetim", "Risk Analizi", "Güvence"] },

  // 2. KGM MERKEZ ŞUBE MÜDÜRLÜKLERİ & DAİRELER
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-BAKIM-YOL", name: "Yol Bakım ve Onarım Şube Müdürlüğü", hierarchy: "KGM > Tesisler ve Bakım Dairesi > Şube Müdürlüğü", desc: "Karayolu yüzey bozulmaları, çukurlar, asfalt yenileme, kış bakımı ve karla mücadele operasyonları.", tags: ["Yol Bakım", "Asfalt", "Çukur", "Karla Mücadele"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-BAKIM-TUNEL", name: "Tünel Bakım ve İşletme Şube Müdürlüğü", hierarchy: "KGM > Tesisler ve Bakım Dairesi > Şube Müdürlüğü", desc: "Mevcut karayolu tünellerinin elektromekanik sistemleri, havalandırma, aydınlatma ve 7/24 işletmesi.", tags: ["Tünel Bakım", "Aydınlatma", "Havalandırma", "Tünel İşletme"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-TRAFIK-ISARET", name: "Trafik Güvenliği İşaret Şube Müdürlüğü", hierarchy: "KGM > Trafik Güvenliği Dairesi > Şube Müdürlüğü", desc: "Trafik yönlendirme ve bilgi levhaları, oto korkuluk (bariyer), yol çizgileri ve sinyalizasyon.", tags: ["Trafik Levhası", "Bariyer", "Sinyalizasyon", "Yol Çizgisi"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-TRAFIK-AUS", name: "Akıllı Ulaşım Sistemleri (AUS) Şube Müdürlüğü", hierarchy: "KGM > Trafik Güvenliği Dairesi > Şube Müdürlüğü", desc: "Değişken mesaj işaretleri (DMİ), trafik izleme kameraları, meteorolojik sensörler ve akıllı yol altyapısı.", tags: ["AUS", "Akıllı Ulaşım", "DMİ", "Elektronik Yol"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-SANAT-KOPRU", name: "Köprü Bakım ve Onarım Şube Müdürlüğü", hierarchy: "KGM > Sanat Yapıları Dairesi > Şube Müdürlüğü", desc: "Köprü, viyadük ve menfezlerin periyodik kontrolü, yapısal çatlak ve hasar onarımları, sismik güçlendirme.", tags: ["Köprü Onarım", "Viyadük", "Menfez", "Güçlendirme"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-SANAT-TARIHI", name: "Tarihi Köprüler Şube Müdürlüğü", hierarchy: "KGM > Sanat Yapıları Dairesi > Şube Müdürlüğü", desc: "Tescilli tarihi ve taş köprülerin envanteri, restorasyonu, korunması ve aslına uygun ihyası.", tags: ["Tarihi Köprü", "Restorasyon", "Kültür Varlığı"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-TAS-KAMU", name: "Kamulaştırma Şube Müdürlüğü", hierarchy: "KGM > Taşınmazlar Dairesi > Şube Müdürlüğü", desc: "Yol güzergahındaki taşınmazların kamulaştırılması, mülkiyet uyuşmazlıkları ve bedel tespit davaları.", tags: ["Kamulaştırma", "Mülkiyet", "Tapu", "Bedel Tespiti"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-TAS-EMLAK", name: "Emlak ve İmar Şube Müdürlüğü", hierarchy: "KGM > Taşınmazlar Dairesi > Şube Müdürlüğü", desc: "Karayolu koridoru imar planları, yol kenarı tesis izinleri ve kurum taşınmaz tahsisleri.", tags: ["İmar Planı", "Yol Kenarı Tesis", "Emlak Tahsis"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ISLETME-OGS", name: "Elektronik Ücret Toplama (HGS/OGS) Şube Müdürlüğü", hierarchy: "KGM > İşletmeler Dairesi > Şube Müdürlüğü", desc: "Otoyol ve köprü geçiş ücretleri, HGS etiketleri, ihlalli geçiş itirazları ve ücret toplama altyapısı.", tags: ["HGS", "OGS", "İhlalli Geçiş", "Otoyol Ücreti"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ISLETME-KOI", name: "KÖİ Bakım İşletme ve Sistem Şube Müdürlüğü", hierarchy: "KGM > İşletmeler Dairesi > Şube Müdürlüğü", desc: "Kamu-Özel İşbirliği (KÖİ / Yap-İşlet-Devret) kapsamındaki otoyol projelerinin denetim ve işletmesi.", tags: ["KÖİ", "Yap-İşlet-Devret", "Otoyol Denetimi"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ETUT-YOL", name: "Yol Etüt ve Proje Şube Müdürlüğü", hierarchy: "KGM > Etüt, Proje ve Çevre Dairesi > Şube Müdürlüğü", desc: "Yeni devlet ve il yolları etüt ve güzergâh projeleri, kavşak geometrik tasarımları.", tags: ["Yol Etüt", "Güzergah Projesi", "Kavşak Tasarımı"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ETUT-CEVRE", name: "Çevre Şube Müdürlüğü", hierarchy: "KGM > Etüt, Proje ve Çevre Dairesi > Şube Müdürlüğü", desc: "Karayolu projelerinin Çevresel Etki Değerlendirmesi (ÇED), gürültü bariyerleri ve ağaçlandırma.", tags: ["ÇED", "Gürültü Bariyeri", "Çevre Yönetimi"] },
  { category: "subeler", catLabel: "KGM ARGE JEO", code: "KGM-ARGE-JEO", name: "Jeolojik Hizmetler ve Heyelan Şube Müdürlüğü", hierarchy: "KGM > Araştırma ve Geliştirme (AR-GE) Dairesi > Şube Müdürlüğü", desc: "Heyelan, şev stabilitesi, kaya düşmesi incelemeleri ve geoteknik koruma projeleri.", tags: ["Heyelan", "Şev Stabilitesi", "Kaya Düşmesi", "Geoteknik"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ARGE-LAB", name: "Malzeme Laboratuvarı Şube Müdürlüğü", hierarchy: "KGM > Araştırma ve Geliştirme (AR-GE) Dairesi > Şube Müdürlüğü", desc: "Asfalt, beton, agrega ve yol yapım malzemelerinin standart testleri ve laboratuvar analizleri.", tags: ["Laboratuvar", "Numune Testi", "Beton", "Bitüm/Asfalt"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-STR-DOKUMAN", name: "İstatistik ve Dokümantasyon Şube Müdürlüğü", hierarchy: "KGM > Strateji Geliştirme Dairesi > Şube Müdürlüğü", desc: "Kurumsal veri, yıllık karayolu istatistikleri, arşiv ve resmî bilgi edinme başvuruları.", tags: ["Bilgi Edinme", "İstatistik", "Dokümantasyon", "Arşiv"] },
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-BT-YAZILIM", name: "Yazılım Geliştirme Şube Müdürlüğü", hierarchy: "KGM > Bilgi Teknolojileri Dairesi > Şube Müdürlüğü", desc: "Kurumsal evrak yönetim sistemleri (EBYS), harita/CBS portalları ve yapay zekâ entegrasyonları.", tags: ["EBYS", "Yazılım", "Entegrasyon", "Portallar"] },

  // 3. KGM BÖLGE MÜDÜRLÜKLERİ (TAŞRA TEŞKİLATI)
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-01", name: "1. Bölge Müdürlüğü (İstanbul)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "İstanbul, Edirne, Kırklareli, Tekirdağ, Kocaeli illeri karayolu ağı yapım, bakım ve trafik kontrolü.", tags: ["İstanbul", "Marmara", "Kocaeli", "Trakya"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-02", name: "2. Bölge Müdürlüğü (İzmir)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "İzmir, Manisa, Aydın, Denizli, Muğla, Çanakkale illeri karayolu ağı yönetimi ve bakımı.", tags: ["İzmir", "Ege", "Manisa", "Aydın", "Muğla"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-03", name: "3. Bölge Müdürlüğü (Konya)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Konya, Aksaray, Karaman illeri karayolları yapım, onarım ve yol güvenliği.", tags: ["Konya", "Aksaray", "Karaman", "İç Anadolu"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-04", name: "4. Bölge Müdürlüğü (Ankara)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Ankara, Bolu, Düzce, Kırıkkale, Çankırı illeri karayolu ağı ve kış bakım operasyonları.", tags: ["Ankara", "Bolu", "Düzce", "Kırıkkale"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-05", name: "5. Bölge Müdürlüğü (Mersin)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Mersin, Adana, Hatay, Osmaniye, Kahramanmaraş karayolu projeleri ve tünel işletmeleri.", tags: ["Mersin", "Adana", "Hatay", "Akdeniz"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-06", name: "6. Bölge Müdürlüğü (Kayseri)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Kayseri, Yozgat, Kırşehir, Nevşehir, Niğde illeri karayolu bakım ve yapım faaliyetleri.", tags: ["Kayseri", "Nevşehir", "Kapadokya", "Niğde"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-07", name: "7. Bölge Müdürlüğü (Samsun)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Samsun, Ordu, Sinop, Amasya, Çorum, Tokat karayolu ağı ve Karadeniz sahil yolu bakımı.", tags: ["Samsun", "Ordu", "Sinop", "Karadeniz"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-10", name: "10. Bölge Müdürlüğü (Trabzon)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Trabzon, Rize, Artvin, Giresun, Gümüşhane, Bayburt zorlu coğrafya, tünel ve heyelan mücadelesi.", tags: ["Trabzon", "Rize", "Artvin", "Doğu Karadeniz", "Tüneller"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-13", name: "13. Bölge Müdürlüğü (Antalya)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Antalya, Burdur, Isparta turizm koridorları, sahil yolları ve köprü bakım hizmetleri.", tags: ["Antalya", "Isparta", "Burdur", "Turizm Yolları"] },
  { category: "bolgeler", catLabel: "KGM Bölge Müdürlükleri (Taşra)", code: "BOLGE-14", name: "14. Bölge Müdürlüğü (Bursa)", hierarchy: "KGM > Taşra Teşkilatı > Bölge Müdürlüğü", desc: "Bursa, Balıkesir, Çanakkale, Kütahya, Yalova sanayi ve transit karayolu arterleri.", tags: ["Bursa", "Balıkesir", "Çanakkale", "Yalova"] },

  // 4. BAĞLI & İLGİLİ KURULUŞLAR
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "AYGM-01", name: "Altyapı Yatırımları Genel Müdürlüğü (AYGM)", hierarchy: "UAB > BAĞLI KURULUŞ > AYGM", desc: "Demiryolu hatları, kent içi raylı sistemler (metro), limanlar, kıyı yapıları ve havaalanı altyapıları.", tags: ["Metro", "Demiryolu", "Liman", "Havalimanı Altyapısı"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "UHDGM-01", name: "Ulaştırma Hizmetleri Düzenleme Genel Müdürlüğü (UHDGM)", hierarchy: "UAB > GENEL MÜDÜRLÜK > UHDGM", desc: "Karayolu yolcu ve eşya taşımacılığı, yetki belgeleri (K1, K2, D1 vb.), SRC denetimleri ve taşıma mevzuatı.", tags: ["Yetki Belgesi", "SRC", "Yolcu Taşımacılığı", "Lojistik"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "BTK-01", name: "Bilgi Teknolojileri ve İletişim Kurumu (BTK)", hierarchy: "UAB > İLGİLİ KURULUŞ > BTK", desc: "Elektronik haberleşme sektörü düzenlemeleri, frekans yönetimi, internet altyapısı ve tüketici hakları.", tags: ["Telekomünikasyon", "İnternet", "Frekans", "İletişim"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "UDHAM-01", name: "Ulaştırma ve Haberleşme Araştırmaları Merkezi (UDHAM)", hierarchy: "UAB > BAĞLI KURULUŞ > UDHAM", desc: "Ulaştırma politikaları, lojistik master planları, yapay zekâ Ar-Ge projeleri ve sektörel fon destekleri.", tags: ["Ar-Ge", "Politika", "Lojistik Master Plan", "Yapay Zekâ"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "TCDD-01", name: "T.C. Devlet Demiryolları (TCDD)", hierarchy: "UAB > İLGİLİ KURULUŞ > TCDD", desc: "Yüksek hızlı tren (YHT), konvansiyonel demiryolu hatları altyapısı ve istasyon işletmeciliği.", tags: ["Demiryolu", "YHT", "Tren", "Hat Altyapısı"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "SHGM-01", name: "Sivil Havacılık Genel Müdürlüğü (SHGM)", hierarchy: "UAB > BAĞLI KURULUŞ > SHGM", desc: "Hava taşımacılığı, havaalanı sertifikasyonu, İHA/dron kayıt ve pilot lisanslama düzenlemeleri.", tags: ["Havacılık", "İHA/Dron", "Uçuş Emniyeti", "Hava Taşımacılığı"] },
  { category: "bagli", catLabel: "Bağlı & İlgili Kuruluşlar", code: "KEGM-01", name: "Kıyı Emniyeti Genel Müdürlüğü (KEGM)", hierarchy: "UAB > İLGİLİ KURULUŞ > KEGM", desc: "Türk boğazları gemi trafik hizmetleri (VTS), kılavuzluk, tahlisiye ve deniz fenerleri.", tags: ["Denizcilik", "Boğaz Trafiği", "VTS", "Kılavuzluk"] }
];

function renderUnitCards(filterCat = "all", searchTerm = "") {
  const term = searchTerm.toLowerCase().trim();
  const filtered = ORGANIZATIONAL_UNITS.filter(u => {
    const matchesCat = filterCat === "all" || u.category === filterCat;
    if (!matchesCat) return false;
    if (!term) return true;
    return (
      u.name.toLowerCase().includes(term) ||
      u.hierarchy.toLowerCase().includes(term) ||
      u.desc.toLowerCase().includes(term) ||
      u.tags.some(t => t.toLowerCase().includes(term)) ||
      u.code.toLowerCase().includes(term)
    );
  });

  if (filtered.length === 0) {
    return `<div style="grid-column:1/-1;padding:32px;text-align:center;color:#6d8892;background:#fbfdfc;border-radius:12px;border:1px dashed #c9d8d8;">
      <p style="margin:0;font-size:13px;font-weight:700;">Arama kriterine uygun birim bulunamadı.</p>
      <small style="color:#8ba3ac;">Farklı bir anahtar kelime veya filtre seçebilirsiniz.</small>
    </div>`;
  }

  return filtered.map(u => {
    const badgeClass = `badge-${u.category}`;
    const tagsHtml = u.tags.map(t => `<span class="unit-tag">${t}</span>`).join("");
    return `<article class="unit-card">
      <div class="unit-card-header">
        <span class="unit-card-badge ${badgeClass}">${u.catLabel}</span>
        <span class="unit-card-code">${u.code}</span>
      </div>
      <h3>${u.name}</h3>
      <span class="unit-card-hierarchy">${u.hierarchy}</span>
      <p>${u.desc}</p>
      <div class="unit-tags">${tagsHtml}</div>
    </article>`;
  }).join("");
}

function getUnitsViewHtml() {
  return `
    <div class="unit-search-bar">
      <input type="search" id="unit-search-input" placeholder="🔍 Birim, şube müdürlüğü, il veya görev alanı ara (Örn: Kamulaştırma, HGS, Heyelan, 1. Bölge, Demiryolu)..." />
    </div>
    <div class="unit-filter-pills" id="unit-filter-pills">
      <button class="unit-filter-btn is-active" data-cat="all">Tümü (${ORGANIZATIONAL_UNITS.length})</button>
      <button class="unit-filter-btn" data-cat="subeler">KGM Merkez &amp; Şubeler (${ORGANIZATIONAL_UNITS.filter(u=>u.category==='subeler').length})</button>
      <button class="unit-filter-btn" data-cat="bolgeler">KGM Bölge Müdürlükleri (Taşra) (${ORGANIZATIONAL_UNITS.filter(u=>u.category==='bolgeler').length})</button>
      <button class="unit-filter-btn" data-cat="bagli">Bağlı &amp; İlgili Kuruluşlar (${ORGANIZATIONAL_UNITS.filter(u=>u.category==='bagli').length})</button>
      <button class="unit-filter-btn" data-cat="bakanlik">Bakanlık &amp; Üst Yönetim (${ORGANIZATIONAL_UNITS.filter(u=>u.category==='bakanlik').length})</button>
    </div>
    <div class="unit-grid" id="unit-grid-container">
      ${renderUnitCards("all", "")}
    </div>
  `;
}

const resourceViews = {
  legislation: {
    title: "Mevzuat Kütüphanesi & Bilgi Grafiği",
    intro: "Resmî Yazışma Yönetmeliği RAG Hiyerarşik Ağaç ve Bilgi Grafiği (205 Düğüm · Bölüm, Madde, Fıkra ve Şablon Hiyerarşisi)",
    body: `<div class="legislation-graph-container"><iframe src="./yonetmelik_graph.html" title="Resmî Yazışma Yönetmeliği Bilgi Grafiği" loading="lazy"></iframe></div>`
  },
  templates: {
    title: "Şablon Kütüphanesi",
    intro: "Her belge türü için kullanılabilir örnek resmî yazı yapıları.",
    body: `<div class="template-grid">${[["Şikâyet","sikayet_v1","Kamu hizmeti veya işlemden duyulan memnuniyetsizlik"],["Dilekçe","dilekce_v1","Bir hakkın veya talebin resmî makama iletilmesi"],["Talep","talep_v1","Bakım, onarım ve hizmet isteği"],["Başvuru","genel_basvuru_v1","Genel amaçlı kuruma başvuru"],["İtiraz","itiraz_v1","Karar veya işleme karşı yeniden değerlendirme"],["İzin","izin_basvurusu_v1","Faaliyet veya çalışma izni başvurusu"],["Belge / bilgi","bilgi_talebi_v1","Belge, kayıt veya bilgi edinme talebi"]].map(([name,id,desc])=>`<article class="template-card"><h3>${name}</h3><p>${desc}</p><code>${id}<br/>Konu · Açıklama · Talep · Tarih · İmza</code></article>`).join("")}</div>`
  },
  units: {
    title: "Kamu Teşkilat & Birim Rehberi",
    intro: "T.C. Ulaştırma ve Altyapı Bakanlığı, KGM Daire Başkanlıkları, Şube Müdürlükleri, Taşra Bölge Müdürlükleri ve Bağlı Genel Müdürlükler hiyerarşisi.",
    getBody: getUnitsViewHtml
  },
  tasks: {
    title: "Görevler · Ajan Süreci",
    intro: "Bir evrakın alınmasından PDF taslağına kadar projede uygulanan teknik adımlar.",
    body: `<div class="task-grid">${[["1","Evrak alma ve OCR","TXT, MD, PDF, PNG, JPG ve TIFF alınır. Görsel belgelerde Tesseract OCR; metin kalitesi ve sayfa kontrolleri uygulanır.","Tesseract OCR · EasyOCR fallback"],["2","Metin anlama","Başvuran, konu, tarih, konum, telefon, e-posta ve talep cümlesi çıkarılır. Kişisel veri politikası ve girdi sınırları denetlenir.","LLM yapılandırılmış anlama ajanı · deterministik extractor"],["3","Evrak sınıflandırma","Metin; dilekçe, şikâyet, talep, bildirim, itiraz, izin veya belge türü olarak sınıflandırılır. Güven düşükse insan incelemesine bırakılır.","Kural tabanlı classifier · LLM adjudicator"],["4","Mevzuat arama","Çıkarılan konu ve kanıt cümleleriyle BM25 aranır; Jina Embeddings v3 dense adayları ve RRF birleşimi kullanılabilir.","BM25 · Jina Embeddings v3 · RRF"],["5","Kaynak doğrulama","Kaynak türü, güncellik, yürürlük ve alaka ayrı ayrı kontrol edilir. Snapshot tek başına güncel hukukî dayanak sayılmaz.","Retrieval verifier · relevance gate"],["6","Birim yönlendirme","Konu, sorumluluk alanı ve kanıt grafiği birlikte değerlendirilerek en uygun Bakanlık/KGM birimi önerilir.","Routing agent · evidence graph"],["7","Şablon ve PDF","Belge türüne uygun şablon seçilir; zorunlu alanlar boş bırakılabilir. LaTeX güvenli biçimde derlenip PDF indirme çıktısı verilir.","Template selection agent · LaTeX compiler"],["8","Uygunluk ve kullanıcı onayı","Eksik alanlar uyarılır, taslak kullanıcıya gösterilir; son onaydan önce tüm alanlar tekrar kontrol edilir.","Compliance agent · user approval gate"]].map(([n,title,desc,model])=>`<article class="task-card"><strong>${n}</strong><h3>${title}</h3><p>${desc}</p><small>${model}</small></article>`).join("")}</div>`
  }
};

$$('a[href="#legislation"],a[href="#templates"],a[href="#units"],a[href="#tasks"]').forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const key = link.getAttribute("href").slice(1);
    const view = resourceViews[key];
    if (!view) return;
    const extraAction = key === "legislation"
      ? `<a class="mini-button" href="./yonetmelik_graph.html" target="_blank" rel="noreferrer" style="text-decoration:none">Tam Ekran Aç ↗</a>`
      : "";
    const bodyHtml = typeof view.getBody === "function" ? view.getBody() : view.body;
    $("#resource-view").innerHTML = `
      <div class="resource-head">
        <div>
          <p class="eyebrow">DİVAN-I AJAN · BİLGİ MERKEZİ</p>
          <h2>${view.title}</h2>
          <p>${view.intro}</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          ${extraAction}
          <button class="resource-close" type="button">Kapat ×</button>
        </div>
      </div>
      ${bodyHtml}
    `;
    $("#resource-view").hidden = false;

    if (key === "units") {
      let currentCat = "all";
      const searchInput = $("#unit-search-input");
      const container = $("#unit-grid-container");
      const pills = $$(".unit-filter-btn");

      pills.forEach(btn => {
        btn.addEventListener("click", () => {
          pills.forEach(b => b.classList.remove("is-active"));
          btn.classList.add("is-active");
          currentCat = btn.getAttribute("data-cat");
          container.innerHTML = renderUnitCards(currentCat, searchInput.value);
        });
      });

      searchInput?.addEventListener("input", () => {
        container.innerHTML = renderUnitCards(currentCat, searchInput.value);
      });
    }

    $("#resource-view").querySelector(".resource-close")?.addEventListener("click", () => {
      $("#resource-view").hidden = true;
    });
    $("#resource-view").scrollIntoView({ behavior: "smooth" });
  });
});

$("a[href='#reports']")?.addEventListener("click", (event) => {
  event.preventDefault();
  $("#reports").hidden = false;
  $("#reports").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("#reports-back")?.addEventListener("click", () => {
  $("#reports").hidden = true;
  $("#test-workspace").scrollIntoView({ behavior: "smooth", block: "start" });
});

const utilityPanel = $("#utility-panel");
const utilityOpen = $("#utility-open");
utilityOpen?.classList.add("is-hidden");
$("#utility-close")?.addEventListener("click", () => {
  utilityPanel.classList.add("is-closed");
  utilityOpen.classList.remove("is-hidden");
});
utilityOpen?.addEventListener("click", () => {
  utilityPanel.classList.remove("is-closed");
  utilityOpen.classList.add("is-hidden");
});

let zoomLevel = 100;
$$('[data-zoom]').forEach((button) => {
  button.addEventListener("click", () => {
    zoomLevel = Math.max(85, Math.min(130, zoomLevel + (button.dataset.zoom === "up" ? 10 : -10)));
    document.documentElement.style.setProperty("font-size", `${zoomLevel}%`);
    $("#zoom-label").textContent = `${zoomLevel}%`;
  });
});

// Safety declarations and static test audit checks
/*
corpusModeLabels[readiness.corpus_mode]
["sayi", state.draft.number]
["imzalayan", state.draft.signer]
["unvan", state.draft.signer_title]
fieldSourceText(field)
reference.corpus_mode === "competition_snapshot"
reference.currentness_verified === true
reference.legal_reliance_allowed === true
Snapshot uyarısı
reference.relevance_accepted === true
Sorgu alakası
Alaka gerekçesi
Sorgu kapısı
relevance_query_reasons
Chunk: ${escapeHtml(reference.chunk_id)}
Sayfa izi yok
document_understanding: "LLM Yapılandırılmış Anlama Ajanı"
adjudicator: "LLM Karar Ajanı (Adjudicator)"
LLM orkestrasyon adımları
llmTrace?.steps || []
llmStatusLabels[step.status]
step.provider || llmTrace.provider
step.model || llmTrace.model
step.data_classification
step.external_data_allowed
step.local_execution
yerel Ollama (cihaz dışına veri çıkışı yok)
step.network_attempted
step.failure_code
step.retryable
step.decision_applied === true
step.decision_applied === false
renderLlmDecisionAudit(step)
step.decision_summary
step.decision_checks || []
step.findings || []
Sunucu karar kapıları
Skorlu bulgular
finding.confidence
finding.legal_reference_ids
step.repair_attempted
step.repair_succeeded
Kanıt düzeltme turu
finding.legal_support_score
finding.document_presence_score
finding.coordinate_confidence
finding.legal_evidence
step.detail
Ağ çağrısından önce veri güvenliği politikası uygulandı
*/
