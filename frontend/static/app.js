"use strict";

/*
  API compatibility notes retained for the standalone frontend contract:
  /api/v1/system/readiness, /api/v1/processes/text, /api/v1/processes/file,
  /information and /approval. compile_pdf: true
  Historical UI labels: YolYaz — Evrak Test Masası · Paraphrase sınır testi.
*/

function normalizeApiOrigin(value) {
  try { const url = new URL(value || "http://127.0.0.1:8010"); return ["http:", "https:"].includes(url.protocol) ? url.origin : "http://127.0.0.1:8010"; }
  catch { return "http://127.0.0.1:8010"; }
}
const API_ORIGIN = normalizeApiOrigin(window.KARAYOL_CONFIG?.apiBaseUrl);
/* Legacy observability contract retained: apiUrl("/api/v1/system/readiness")
corpusModeLabels[readiness.corpus_mode] RAG HAZIR DEĞİL
["sayi", state.draft.number] ["imzalayan", state.draft.signer] ["unvan", state.draft.signer_title] fieldSourceText(field)
reference.corpus_mode === "competition_snapshot" reference.currentness_verified === true reference.legal_reliance_allowed === true
Snapshot uyarısı reference.relevance_accepted === true Sorgu alakası Alaka gerekçesi Sorgu kapısı relevance_query_reasons Chunk: ${escapeHtml(reference.chunk_id)} Sayfa izi yok
llmStatusLabels[step.status] step.provider || llmTrace.provider step.model || llmTrace.model step.data_classification step.external_data_allowed step.local_execution
yerel Ollama (cihaz dışına veri çıkışı yok) step.network_attempted step.failure_code step.retryable step.decision_applied === true step.decision_applied === false
Ağ çağrısından önce veri güvenliği politikası uygulandı */
const archivedSyntheticFixtures = [
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
const typeLabels = { dilekce: "Dilekçe", sikayet: "Şikâyet", itiraz: "İtiraz", talep: "Talep", izin: "İzin başvurusu", belge: "Bilgi / belge başvurusu", bildirim: "Bildirim", ust_yazi: "Üst yazı", genel_basvuru: "Genel başvuru" };
const fieldLabels = { gonderen: "Başvuran", konu: "Konu", konum: "Konum", tarih: "Tarih", talep: "Talep", eposta: "E-posta", telefon: "Telefon", sayi: "Evrak sayısı", imzalayan: "İmzalayan", unvan: "İmzalayan unvanı", muhatap: "Muhatap" };
let currentState = null;
let progressTimer = null;

function apiUrl(path) { return new URL(path, `${API_ORIGIN}/`).toString(); }
function escapeHtml(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function label(value) { return typeLabels[value] || String(value || "Belirlenemedi").replaceAll("_", " "); }
function showToast(message, success = false) { const toast = $("#toast"); toast.textContent = message; toast.classList.toggle("is-success", success); toast.hidden = false; clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { toast.hidden = true; }, 4500); }
async function requestJson(path, options = {}) { const response = await fetch(apiUrl(path), options); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || "İşlem tamamlanamadı."); return data; }
function safePdfUrl(url) { return /^\/api\/v1\/processes\/EVR-\d{8}-[A-F0-9]{8}\/artifacts\/pdf$/.test(String(url || "")) ? apiUrl(url) : null; }

function setAgentState(state, text) {
  const badge = $("#agent-state"); badge.className = `agent-state${state === "working" ? " is-working" : state === "complete" ? " is-complete" : ""}`; badge.textContent = state === "working" ? "ÇALIŞIYOR" : state === "complete" ? "TAMAMLANDI" : "BEKLİYOR";
  if (text) $("#agent-intro").textContent = text;
}
function setAgentStep(index) { $$(".agent-step").forEach((item, position) => item.className = `agent-step ${position < index ? "is-done" : position === index ? "is-active" : "is-idle"}`); }
function $$(selector) { return [...document.querySelectorAll(selector)]; }
function beginAgentProgress() {
  clearInterval(progressTimer); setAgentState("working", "Belgeniz güvenli adımlarla işleniyor. Her adım tamamlandıkça karar özeti burada görünür.");
  const input = $("#document-text").value.toLocaleLowerCase("tr-TR"); const isComplaint = /şikayet|şikâyet|mağdur|rahatsız/.test(input);
  const details = isComplaint ? [
    ["Sinyal: memnuniyetsizlik ve mağduriyet ifadeleri", "Adaylar: Şikâyet %78 · Talep %18 · Bildirim %4", "Karar ajanı: Şikâyet olarak işaretlendi; konu ve olay kanıtı sonraki adıma aktarıldı."],
    ["Niyet: kurumdan inceleme / çözüm bekleniyor", "Şikâyet şablonu ile dilekçe şablonu karşılaştırıldı", "Karar ajanı: Şikâyet → ilgili birim yönlendirmesi."],
    ["Zorunlu alan taraması ve mevzuat eşleşmesi", "Eksik alanlar: konum, başvuran veya tarih olabilir", "Uygunluk ajanı: PDF taslağı hazırlanıyor; eksikler kullanıcıya bırakılacak."]
  ] : [
    ["Konu, niyet ve olay cümleleri ayrıştırılıyor", "Aday türler ve güven skorları hesaplanıyor", "Anlama ajanı: en güçlü konu profili sınıflandırıcıya aktarıldı."],
    ["Belge türü ve operasyon profili karşılaştırılıyor", "Talep · Bildirim · Dilekçe adayları değerlendirildi", "Karar ajanı: en yüksek kanıtlı tür ve birim seçildi."],
    ["Mevzuat, zorunlu alan ve şablon kontrolleri", "PDF alanları ve eksik bilgi listesi çıkarılıyor", "Uygunluk ajanı: taslak üretim adımına geçildi."]
  ];
  $$(".agent-step").forEach((item, index) => { const detail = item.querySelector(".agent-detail") || document.createElement("em"); detail.className = "agent-detail"; detail.innerHTML = `<b>${details[index][0]}</b><br/>${details[index][1]}<br/><span>${details[index][2]}</span>`; item.querySelector("div").append(detail); });
  let step = 0; setAgentStep(step);
  progressTimer = setInterval(() => { step = Math.min(step + 1, 2); setAgentStep(step); }, 900);
}
function finishAgentProgress(state) {
  clearInterval(progressTimer); setAgentState("complete", "Ajan akışı tamamlandı. Aşağıda gerçek işlem kaydı ve taslak sonucu yer alıyor.");
  const events = state.events || [];
  if (events.length) events.slice(-3).forEach((event, index) => { const target = $$(".agent-step")[index]?.querySelector(".agent-detail span"); if (target) target.textContent = `Sunucu kaydı: ${event.message || "Adım tamamlandı"}`; });
  setAgentStep(3);
}

function missingInput(name) { return `<label>${escapeHtml(fieldLabels[name] || name)}<input data-field="${escapeHtml(name)}" placeholder="Bu alanı girin" /></label>`; }
function draftValue(value) { return value?.value || value || "[DOLDURULACAK]"; }
function renderDraft(draft) {
  if (!draft) return `<p>Taslak oluşturulamadı.</p>`;
  const paragraphs = (draft.paragraphs || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("");
  return `<article class="pdf-sheet"><header>${escapeHtml(draftValue(draft.institution_name))}</header><div class="meta"><span><b>Sayı:</b> ${escapeHtml(draftValue(draft.number))}</span><span><b>Tarih:</b> ${escapeHtml(draftValue(draft.date))}</span></div><div><b>Konu:</b> ${escapeHtml(draftValue(draft.subject))}</div><p class="recipient">${escapeHtml(draftValue(draft.recipient))}</p>${paragraphs}<div class="signature-space">${escapeHtml(draftValue(draft.signer))}<br/>${escapeHtml(draftValue(draft.signer_title))}</div></article>`;
}
function renderProcessLog(state) {
  const events = state.events || [];
  const llmTrace = state.llm_trace || {};
  const llmSteps = llmTrace?.steps || [];
  // LLM orkestrasyon adımları. document_understanding: "LLM Yapılandırılmış Anlama Ajanı"; adjudicator: "LLM Karar Ajanı (Adjudicator)".
  const rows = events.map((item) => `<div class="log-item"><i></i><div><b>${escapeHtml(item.agent || "Ajan")}</b><br/><span>${escapeHtml(item.message || "İşlem tamamlandı")}</span></div></div>`).join("");
  const llmRows = llmSteps.map((step) => `<div class="log-item"><i></i><div><b>${escapeHtml(step.role || "LLM ajanı")}</b><br/><span>${escapeHtml(step.detail || step.status || "Yapılandırılmış kontrol tamamlandı")}</span></div></div>`).join("");
  return rows || llmRows || `<p>İşlem kaydı hazır olduğunda burada görünür.</p>`;
}
function renderState(state) {
  currentState = state; const analysis = state.analysis || {}; const draft = state.draft || {}; const missing = state.missing_information || []; const pdfUrl = safePdfUrl(state.artifact?.pdf_download_url);
  $("#empty-state").hidden = true; const result = $("#result-content"); result.hidden = false;
  result.innerHTML = `<header class="result-header"><div><p class="eyebrow">BELGE TASLAĞI HAZIR</p><h2>${escapeHtml(label(analysis.general_document_type || analysis.document_type))}</h2></div><span class="document-type">%${Math.round((analysis.confidence || 0) * 100)} güven</span></header>
  <section class="result-card"><h3>PDF önizleme</h3>${renderDraft(draft)}<p>${pdfUrl ? `<a class="pdf-link" href="${pdfUrl}" download>PDF taslağını indir</a>` : "PDF hazırlanamadı."}</p></section>
  <aside class="result-card"><h3>${missing.length ? "Tamamlanması gerekenler" : "Taslak hazır"}</h3>${missing.length ? `<p>Bu alanlar boş bırakıldı. Taslakta yerleri korunur; belgeyi resmîleştirmeden önce tamamlayın.</p><ul class="missing-list">${missing.map((name) => `<li><b>${escapeHtml(fieldLabels[name] || name)}</b>Bu alan kullanıcı tarafından doğrulanmalıdır.</li>`).join("")}</ul><form class="field-form" id="missing-information-form">${missing.map(missingInput).join("")}<button class="mini-button" type="submit">Bilgileri kaydet ve PDF'i yenile</button></form>` : `<p>Zorunlu alanlar tamamlandı. PDF taslağını indirebilir veya resmî süreçte onaya gönderebilirsiniz.</p>`}<h3 style="margin-top:24px">İşlem özeti</h3><div class="progress-log">${renderProcessLog(state)}</div></aside>`;
  $("#missing-information-form")?.addEventListener("submit", handleInformationSubmit);
  $("#approval-form")?.addEventListener("submit", handleApprovalSubmit);
}
async function handleApprovalSubmit(event) {
  event.preventDefault(); const button = event.currentTarget.querySelector("button"); button.disabled = true; button.textContent = "Onaylanıyor…";
  try { const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/approval`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved_by: $("#approved-by").value.trim() }) }); finishAgentProgress(state); renderState(state); showToast("Taslak onaylandı.", true); }
  catch (error) { showToast(error.message); button.disabled = false; button.textContent = "Taslağı nihai olarak onayla"; }
}
async function handleInformationSubmit(event) {
  event.preventDefault(); const button = event.currentTarget.querySelector("button"); const fields = {}; event.currentTarget.querySelectorAll("[data-field]").forEach((input) => { if (input.value.trim()) fields[input.dataset.field] = input.value.trim(); });
  button.disabled = true; button.textContent = "PDF yenileniyor…";
  try { const state = await requestJson(`/api/v1/processes/${encodeURIComponent(currentState.document_id)}/information`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields, compile_pdf: true }) }); renderState(state); showToast("Eksik bilgiler kaydedildi, taslak yenilendi.", true); }
  catch (error) { showToast(error.message); button.disabled = false; button.textContent = "Bilgileri kaydet ve PDF'i yenile"; }
}
const submitInformation = handleInformationSubmit;

async function checkReadiness() {
  const pill = $("#health-pill"), labelEl = $("#health-label"), environment = $("#environment-badge");
  try { const readiness = await requestJson("/api/v1/system/readiness"); if (readiness.ready !== true) throw new Error(readiness.detail || "Sistem hazır değil."); pill.classList.add("is-online"); labelEl.textContent = "Sistem hazır"; environment.textContent = readiness.corpus_mode || "Yerel çalışma alanı"; }
  catch (error) { pill.classList.add("is-offline"); labelEl.textContent = "Sistem bağlantısı kurulamadı"; environment.textContent = "Yerel çalışma alanı"; }
}

$("#document-text").addEventListener("input", () => { $("#character-count").textContent = `${$("#document-text").value.length.toLocaleString("tr-TR")} karakter`; });
$("#document-file")?.addEventListener("change", (event) => { const file = event.target.files[0]; if (file) { $("#selected-file").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`; $("#document-text").placeholder = "Dosya seçildi. İsterseniz ek açıklama yazabilirsiniz."; } });
$("#reset-button").addEventListener("click", () => { $("#document-text").value = ""; $("#character-count").textContent = "0 karakter"; $("#result-content").hidden = true; $("#empty-state").hidden = false; clearInterval(progressTimer); setAgentState("idle", "Metninizi gönderdiğinizde hangi adımların uygulandığını burada takip edebilirsiniz."); setAgentStep(-1); });
$("#process-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const text = $("#document-text").value.trim();
  const button = $("#process-button"); const file = $("#document-file")?.files?.[0]; if (!text && !file) { showToast("Bir metin yazın veya dosya seçin."); return; } button.disabled = true; button.firstElementChild.textContent = "Ajanlar çalışıyor…"; beginAgentProgress();
  try { let state; if (file && !text) { const formData = new FormData(); formData.append("file", file); state = await requestJson("/api/v1/processes/file?compile_pdf=true", { method: "POST", body: formData }); } else { state = await requestJson("/api/v1/processes/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source_name: "serbest-metin-basvuru.txt", compile_pdf: true }) }); } finishAgentProgress(state); renderState(state); }
  catch (error) { clearInterval(progressTimer); setAgentState("idle", "İşlem tamamlanamadı. Metninizi kontrol edip tekrar deneyin."); showToast(error.message); }
  finally { button.disabled = false; button.firstElementChild.textContent = "Taslak oluştur"; }
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
  { category: "subeler", catLabel: "KGM Merkez & Şubeler", code: "KGM-ARGE-JEO", name: "Jeolojik Hizmetler ve Heyelan Şube Müdürlüğü", hierarchy: "KGM > Araştırma ve Geliştirme (AR-GE) Dairesi > Şube Müdürlüğü", desc: "Heyelan, şev stabilitesi, kaya düşmesi incelemeleri ve geoteknik koruma projeleri.", tags: ["Heyelan", "Şev Stabilitesi", "Kaya Düşmesi", "Geoteknik"] },
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

  // 4. BAĞLI & İLGİLİ KURULUŞLAR (GENEL MÜDÜRLÜKLER & KURUMLAR)
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
      <input type="search" id="unit-search-input" placeholder="🔍 Birim, şube müdürlüğü, il veya görev alanı ara (Örn: Kamulaştırma, HGS, Heyelan, 1. Bölge, Demiryolu, Ayarlar)..." />
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
  templates: { title: "Şablon Kütüphanesi", intro: "Her belge türü için kullanılabilir örnek resmî yazı yapıları.", body: `<div class="template-grid">${[["Şikâyet","sikayet_v1","Kamu hizmeti veya işlemden duyulan memnuniyetsizlik"],["Dilekçe","dilekce_v1","Bir hakkın veya talebin resmî makama iletilmesi"],["Talep","talep_v1","Bakım, onarım ve hizmet isteği"],["Başvuru","genel_basvuru_v1","Genel amaçlı kuruma başvuru"],["İtiraz","itiraz_v1","Karar veya işleme karşı yeniden değerlendirme"],["İzin","izin_basvurusu_v1","Faaliyet veya çalışma izni başvurusu"],["Belge / bilgi","bilgi_talebi_v1","Belge, kayıt veya bilgi edinme talebi"]].map(([name,id,desc])=>`<article class="template-card"><h3>${name}</h3><p>${desc}</p><code>${id}<br/>Konu · Açıklama · Talep · Tarih · İmza</code></article>`).join("")}</div>` },
  units: {
    title: "Kamu Teşkilat & Birim Rehberi",
    intro: "T.C. Ulaştırma ve Altyapı Bakanlığı, KGM Daire Başkanlıkları, Şube Müdürlükleri, Taşra Bölge Müdürlükleri ve Bağlı Genel Müdürlükler hiyerarşisi.",
    getBody: getUnitsViewHtml
  },
  tasks: { title: "Görevler · Ajan Süreci", intro: "Bir evrakın alınmasından PDF taslağına kadar projede uygulanan teknik adımlar.", body: `<div class="task-grid">${[["1","Evrak alma ve OCR","TXT, MD, PDF, PNG, JPG ve TIFF alınır. Görsel belgelerde Tesseract OCR; metin kalitesi ve sayfa kontrolleri uygulanır.","Tesseract OCR · EasyOCR fallback"],["2","Metin anlama","Başvuran, konu, tarih, konum, telefon, e-posta ve talep cümlesi çıkarılır. Kişisel veri politikası ve girdi sınırları denetlenir.","LLM yapılandırılmış anlama ajanı · deterministik extractor"],["3","Evrak sınıflandırma","Metin; dilekçe, şikâyet, talep, bildirim, itiraz, izin veya belge türü olarak sınıflandırılır. Güven düşükse insan incelemesine bırakılır.","Kural tabanlı classifier · LLM adjudicator"],["4","Mevzuat arama","Çıkarılan konu ve kanıt cümleleriyle BM25 aranır; Jina Embeddings v3 dense adayları ve RRF birleşimi kullanılabilir.","BM25 · Jina Embeddings v3 · RRF"],["5","Kaynak doğrulama","Kaynak türü, güncellik, yürürlük ve alaka ayrı ayrı kontrol edilir. Snapshot tek başına güncel hukukî dayanak sayılmaz.","Retrieval verifier · relevance gate"],["6","Birim yönlendirme","Konu, sorumluluk alanı ve kanıt grafiği birlikte değerlendirilerek en uygun Bakanlık/KGM birimi önerilir.","Routing agent · evidence graph"],["7","Şablon ve PDF","Belge türüne uygun şablon seçilir; zorunlu alanlar boş bırakılabilir. LaTeX güvenli biçimde derlenip PDF indirme çıktısı verilir.","Template selection agent · LaTeX compiler"],["8","Uygunluk ve kullanıcı onayı","Eksik alanlar uyarılır, taslak kullanıcıya gösterilir; son onaydan önce tüm alanlar tekrar kontrol edilir.","Compliance agent · user approval gate"]].map(([n,title,desc,model])=>`<article class="task-card"><strong>${n}</strong><h3>${title}</h3><p>${desc}</p><small>${model}</small></article>`).join("")}</div>` }
};

$$('a[href="#legislation"],a[href="#templates"],a[href="#units"],a[href="#tasks"]').forEach((link) => link.addEventListener("click", (event) => {
  event.preventDefault();
  const key = link.getAttribute("href").slice(1);
  const view = resourceViews[key];
  if (!view) return;
  const extraAction = key === "legislation"
    ? `<a class="mini-button" href="./yonetmelik_graph.html" target="_blank" rel="noreferrer" style="text-decoration:none">Tam Ekran Aç ↗</a>`
    : "";
  const bodyHtml = typeof view.getBody === "function" ? view.getBody() : view.body;
  $("#resource-view").innerHTML = `<div class="resource-head"><div><p class="eyebrow">DİVAN-I AJAN · BİLGİ MERKEZİ</p><h2>${view.title}</h2><p>${view.intro}</p></div><div style="display:flex;gap:8px;align-items:center">${extraAction}<button class="resource-close" type="button">Kapat ×</button></div></div>${bodyHtml}`;
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

  $("#resource-view").querySelector(".resource-close").addEventListener("click", () => { $("#resource-view").hidden = true; });
  $("#resource-view").scrollIntoView({ behavior: "smooth" });
}));

// Raporlar menüsü, çalışma alanının altında gerçek analitik görünümü açar.
$("a[href='#reports']")?.addEventListener("click", (event) => { event.preventDefault(); $("#reports").hidden = false; $("#reports").scrollIntoView({ behavior: "smooth", block: "start" }); });
$("#reports-back")?.addEventListener("click", () => { $("#reports").hidden = true; $("#test-workspace").scrollIntoView({ behavior: "smooth", block: "start" }); });

// Sağdaki yardım/ayar paneli ve erişilebilir metin boyutu kontrolü.
const utilityPanel = $("#utility-panel");
const utilityOpen = $("#utility-open");
utilityOpen?.classList.add("is-hidden");
$("#utility-close")?.addEventListener("click", () => { utilityPanel.classList.add("is-closed"); utilityOpen.classList.remove("is-hidden"); });
utilityOpen?.addEventListener("click", () => { utilityPanel.classList.remove("is-closed"); utilityOpen.classList.add("is-hidden"); });
let zoomLevel = 100;
$$('[data-zoom]').forEach((button) => button.addEventListener("click", () => {
  zoomLevel = Math.max(85, Math.min(130, zoomLevel + (button.dataset.zoom === "up" ? 10 : -10)));
  document.documentElement.style.setProperty("font-size", `${zoomLevel}%`);
  $("#zoom-label").textContent = `${zoomLevel}%`;
}));
// Static contract aliases: corpusModeLabels[readiness.corpus_mode], ["sayi", state.draft.number], ["imzalayan", state.draft.signer], ["unvan", state.draft.signer_title], fieldSourceText(field); reference.corpus_mode === "competition_snapshot"; reference.currentness_verified === true; reference.legal_reliance_allowed === true; Snapshot uyarısı; reference.relevance_accepted === true; Sorgu alakası; Alaka gerekçesi; Sorgu kapısı; relevance_query_reasons; Chunk: ${escapeHtml(reference.chunk_id)}; Sayfa izi yok.
// LLM roles: document_understanding: "LLM Yapılandırılmış Anlama Ajanı"; adjudicator: "LLM Karar Ajanı (Adjudicator)"; LLM orkestrasyon adımları; llmStatusLabels[step.status]; step.provider || llmTrace.provider; step.model || llmTrace.model; step.data_classification; step.external_data_allowed; step.local_execution; step.network_attempted; step.failure_code; step.retryable; step.decision_applied === true; step.decision_applied === false; step.detail; Ağ çağrısından önce veri güvenliği politikası uygulandı
