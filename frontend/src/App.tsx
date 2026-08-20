import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, waitForJob } from "./api";
import type { Analysis, DocumentRecord, Draft, Job, ModelSelection } from "./types";

const steps = ["Belge", "Metin", "Analiz", "Taslak", "Onay"];

export default function App() {
  const queryClient = useQueryClient();
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5_000 });
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: api.modelSettings, refetchInterval: 8_000 });

  const [modelSelection, setModelSelection] = useState<ModelSelection>({ chat_model: "", embedding_model: "" });
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [editedText, setEditedText] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selectedUnit, setSelectedUnit] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const selected = modelsQuery.data?.selected;
    if (selected) setModelSelection(selected);
  }, [modelsQuery.data?.selected]);

  useEffect(() => {
    if (analysis) setSelectedUnit(analysis.routing.recommended_unit_id);
  }, [analysis]);

  const activeStep = draft?.status === "approved" ? 4 : draft ? 3 : analysis ? 2 : document ? 1 : 0;
  const ready = Boolean(modelsQuery.data?.selected && modelsQuery.data?.index_ready);
  const fileUrl = document ? api.documentFileUrl(document.id) : "";

  async function perform(action: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Beklenmeyen bir hata oluştu.");
    } finally {
      setBusy(false);
    }
  }

  function progress(nextJob: Job) {
    setJob(nextJob);
  }

  async function saveModels() {
    await perform(async () => {
      if (!modelSelection.chat_model || !modelSelection.embedding_model) {
        throw new Error("Analiz ve embedding modeli seçilmelidir.");
      }
      await api.saveModels(modelSelection);
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      await queryClient.invalidateQueries({ queryKey: ["health"] });
      setNotice("Ollama modelleri doğrulandı ve kaydedildi.");
    });
  }

  async function buildIndex() {
    await perform(async () => {
      const created = await api.reindex();
      const completed = await waitForJob(created.id, progress);
      setJob(completed);
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      await queryClient.invalidateQueries({ queryKey: ["health"] });
      setNotice("Mevzuat ve belediye birim indeksi hazır.");
    });
  }

  async function uploadFile(file: File | undefined) {
    if (!file) return;
    await perform(async () => {
      setDocument(null);
      setAnalysis(null);
      setDraft(null);
      const uploaded = await api.upload(file);
      const completed = await waitForJob(uploaded.job_id, progress);
      setJob(completed);
      const loaded = await api.document(uploaded.document_id);
      setDocument(loaded);
      setEditedText(loaded.corrected_text ?? loaded.original_text ?? "");
      setNotice("Belge metni hazır. Analizden önce metni kontrol edin.");
    });
  }

  async function saveAndAnalyze() {
    if (!document) return;
    await perform(async () => {
      const updated = await api.saveText(document.id, editedText);
      setDocument(updated);
      const started = await api.analyze(document.id);
      const completed = await waitForJob(started.id, progress);
      setJob(completed);
      if (!completed.result_id) throw new Error("Analiz sonucu kimliği alınamadı.");
      const loaded = await api.analysis(completed.result_id);
      setAnalysis(loaded);
      setNotice("Analiz tamamlandı. Birim önerisini inceleyin.");
    });
  }

  async function generateDraft() {
    if (!analysis || !selectedUnit) return;
    await perform(async () => {
      const started = await api.createDraft(analysis.id, selectedUnit);
      const completed = await waitForJob(started.id, progress);
      setJob(completed);
      if (!completed.result_id) throw new Error("Taslak sonucu kimliği alınamadı.");
      setDraft(await api.draft(completed.result_id));
      setNotice("Taslak hazır. Onaylamadan önce metni ve kontrolleri inceleyin.");
    });
  }

  async function saveDraft() {
    if (!draft) return;
    await perform(async () => {
      const updated = await api.updateDraft(draft.id, {
        subject: draft.subject,
        body: draft.body,
        references: draft.references,
        attachments: draft.attachments,
        distribution: draft.distribution,
      });
      setDraft(updated);
      setNotice(`Taslak sürüm ${updated.version} kaydedildi.`);
    });
  }

  async function approveDraft() {
    if (!draft) return;
    await perform(async () => {
      const approved = await api.approveDraft(draft.id);
      setDraft(approved);
      setNotice("Taslak insan onayıyla dışa aktarmaya hazır.");
    });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">EA</div>
        <div>
          <p className="eyebrow">T.C. ÖRNEKŞEHİR BELEDİYESİ</p>
          <h1>EvrakAI Karar Destek Sistemi</h1>
        </div>
        <div className={`system-pill ${healthQuery.data?.status === "ok" ? "ok" : "warn"}`}>
          <span className="status-dot" />
          {healthQuery.data?.status === "ok" ? "Sistem hazır" : "Kurulum gerekli"}
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <div className="sidebar-card">
            <div className="sidebar-title">
              <span>Yerel yapay zekâ</span>
              <span className={`mini-badge ${modelsQuery.data?.ollama_reachable ? "green" : "red"}`}>
                {modelsQuery.data?.ollama_reachable ? "Bağlı" : "Bağlı değil"}
              </span>
            </div>
            <label>
              Analiz modeli
              <select
                value={modelSelection.chat_model}
                onChange={(event) => setModelSelection((current) => ({ ...current, chat_model: event.target.value }))}
                disabled={busy || !modelsQuery.data?.ollama_reachable}
              >
                <option value="">Model seçin</option>
                {modelsQuery.data?.available_models.map((model) => (
                  <option key={`chat-${model.name}`} value={model.name}>{model.name}</option>
                ))}
              </select>
            </label>
            <label>
              Embedding modeli
              <select
                value={modelSelection.embedding_model}
                onChange={(event) => setModelSelection((current) => ({ ...current, embedding_model: event.target.value }))}
                disabled={busy || !modelsQuery.data?.ollama_reachable}
              >
                <option value="">Model seçin</option>
                {modelsQuery.data?.available_models.map((model) => (
                  <option key={`embed-${model.name}`} value={model.name}>{model.name}</option>
                ))}
              </select>
            </label>
            <button className="button secondary full" onClick={saveModels} disabled={busy}>Modelleri doğrula</button>
            {!modelsQuery.data?.index_ready && modelsQuery.data?.selected && (
              <button className="button accent full" onClick={buildIndex} disabled={busy}>İndeksi oluştur</button>
            )}
            <p className="helper">{modelsQuery.data?.index_ready ? "Mevzuat indeksi hazır." : modelsQuery.data?.index_reason}</p>
          </div>

          <ol className="step-list">
            {steps.map((step, index) => (
              <li key={step} className={index === activeStep ? "active" : index < activeStep ? "done" : ""}>
                <span>{index < activeStep ? "✓" : index + 1}</span>
                {step}
              </li>
            ))}
          </ol>

          <div className="privacy-note">
            <strong>Yerel ve sentetik</strong>
            <p>Belgeler bu cihazda işlenir. Sistem karar vermez; insan onayı zorunludur.</p>
          </div>
        </aside>

        <section className="content">
          {(error || notice) && (
            <div className={`message ${error ? "error" : "success"}`}>{error || notice}</div>
          )}
          {job && busy && (
            <div className="job-banner">
              <div>
                <strong>{job.stage}</strong>
                <span>{job.progress}%</span>
              </div>
              <div className="progress"><span style={{ width: `${job.progress}%` }} /></div>
            </div>
          )}

          <section className="hero-card">
            <div>
              <p className="eyebrow">UÇTAN UCA EVRAK AKIŞI</p>
              <h2>Belgeyi yükleyin, kararı siz verin.</h2>
              <p>OCR, içerik analizi, mevzuat dayanağı, birim yönlendirmesi ve resmî yazı taslağı tek akışta.</p>
            </div>
            <label className={`upload-button ${busy ? "disabled" : ""}`}>
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.txt"
                onChange={(event) => uploadFile(event.target.files?.[0])}
                disabled={busy}
              />
              <span>Belge seç</span>
              <small>PDF, PNG, JPEG veya TXT · En fazla 10 MB</small>
            </label>
          </section>

          {!ready && (
            <section className="empty-state">
              <div className="empty-icon">01</div>
              <h3>Analiz için yerel modelleri hazırlayın</h3>
              <p>Sol panelden analiz ve embedding modellerini seçin, ardından mevzuat indeksini oluşturun. Belge OCR işlemi model olmadan da kullanılabilir.</p>
            </section>
          )}

          {document && (
            <section className="panel">
              <PanelHeader index="01" title="Belge ve metin kontrolü" subtitle={`${document.filename} · ${document.page_count} sayfa · ${Math.round(document.text_quality * 100)} kalite`} />
              <div className="split-view">
                <div className="document-preview">
                  {document.mime_type.includes("pdf") ? (
                    <iframe title="Yüklenen belge" src={fileUrl} />
                  ) : document.mime_type.includes("image") ? (
                    <img src={fileUrl} alt="Yüklenen belge" />
                  ) : (
                    <div className="text-file-preview">TXT belgesi<br/><strong>{document.filename}</strong></div>
                  )}
                </div>
                <div className="editor-column">
                  <div className="field-heading">
                    <strong>Çıkarılan metin</strong>
                    <span>{document.extraction_method}</span>
                  </div>
                  <textarea
                    className="ocr-editor"
                    value={editedText}
                    onChange={(event) => setEditedText(event.target.value)}
                    spellCheck
                  />
                  <button className="button primary" onClick={saveAndAnalyze} disabled={busy || !ready || editedText.trim().length === 0}>
                    Metni onayla ve analiz et
                  </button>
                </div>
              </div>
            </section>
          )}

          {analysis && (
            <section className="panel">
              <PanelHeader index="02" title="Evrak analizi" subtitle={`Model: ${analysis.model_name}`} />
              <div className="analysis-grid">
                <MetricCard label="Evrak türü" value={labelize(analysis.document_type.label)} level={analysis.document_type.decision_level} />
                <MetricCard label="Konu" value={analysis.topic} />
                <MetricCard label="Yönlendirme" value={analysis.routing.alternatives[0]?.unit_name ?? "Belirsiz"} level={analysis.routing.decision_level} />
              </div>
              <article className="summary-card"><strong>Kısa özet</strong><p>{analysis.summary}</p></article>
              {analysis.warnings.length > 0 && <WarningList items={analysis.warnings} />}

              <div className="detail-columns">
                <div>
                  <h3>Çıkarılan bilgiler</h3>
                  <div className="field-list">
                    {analysis.extracted_fields.map((field) => (
                      <div key={field.name} className="field-row">
                        <span>{labelize(field.name)}</span>
                        <strong className={field.status !== "present" ? "missing" : ""}>{field.value || "Eksik"}</strong>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <h3>Mevzuat dayanakları</h3>
                  <div className="evidence-list">
                    {analysis.regulations.length === 0 && <p className="muted">Doğrulanmış dayanak bulunamadı.</p>}
                    {analysis.regulations.map((item) => (
                      <details key={`${item.source_id}-${item.page}-${item.quote.slice(0, 12)}`}>
                        <summary>{item.title} · {item.article || `Sayfa ${item.page}`}</summary>
                        <p>{item.quote}</p>
                        <small>Erişim skoru: {item.retrieval_score.toFixed(3)}</small>
                      </details>
                    ))}
                  </div>
                </div>
              </div>

              <div className="routing-block">
                <h3>Birim yönlendirmesini onaylayın</h3>
                <div className="route-options">
                  {analysis.routing.alternatives.map((route, index) => (
                    <label key={route.unit_id} className={selectedUnit === route.unit_id ? "selected" : ""}>
                      <input type="radio" name="route" value={route.unit_id} checked={selectedUnit === route.unit_id} onChange={() => setSelectedUnit(route.unit_id)} />
                      <span className="rank">{index + 1}</span>
                      <span><strong>{route.unit_name}</strong><small>{route.rationale}</small></span>
                      <b>{route.score.toFixed(3)}</b>
                    </label>
                  ))}
                </div>
                <button className="button primary" onClick={generateDraft} disabled={busy || !selectedUnit}>Seçili birime taslak hazırla</button>
              </div>
            </section>
          )}

          {draft && (
            <section className="panel">
              <PanelHeader index="03" title="Resmî yazı taslağı" subtitle={`${draft.recipient_unit_name} · Sürüm ${draft.version}`} />
              <div className="draft-layout">
                <div className="paper">
                  <div className="watermark">SENTETİK TASLAK · RESMÎ BELGE DEĞİLDİR</div>
                  <h4>T.C.<br/>{draft.institution_name.toUpperCase()}</h4>
                  <div className="paper-meta"><span>Sayı: {draft.number}</span><span>Tarih: {draft.date}</span></div>
                  <label>Konu<input value={draft.subject} onChange={(event) => setDraft({ ...draft, subject: event.target.value, status: "draft" })} /></label>
                  <h5>{draft.recipient_unit_name.toUpperCase()}</h5>
                  <textarea value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value, status: "draft" })} />
                  <p className="signature">{draft.signatory}<br/><small>Yetkili (Sentetik)</small></p>
                </div>
                <div className="validation-panel">
                  <h3>Biçim kontrolleri</h3>
                  {draft.validations.map((check) => (
                    <div className={`validation ${check.status}`} key={check.rule_id}>
                      <span>{check.status === "pass" ? "✓" : "!"}</span>
                      <div><strong>{check.label}</strong><small>{check.message}</small></div>
                    </div>
                  ))}
                  <button className="button secondary full" onClick={saveDraft} disabled={busy}>Değişiklikleri kaydet</button>
                  <button className="button primary full" onClick={approveDraft} disabled={busy || draft.status === "approved"}>Taslağı insan onayıyla tamamla</button>
                  {draft.status === "approved" && (
                    <div className="export-actions">
                      <a className="button accent" href={api.exportUrl(draft.id, "docx")}>DOCX indir</a>
                      <a className="button accent" href={api.exportUrl(draft.id, "pdf")}>PDF indir</a>
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
        </section>
      </main>
      <footer>Yapay zekâ destekli karar destek demosu · Bütün veriler sentetiktir · İnsan onayı zorunludur</footer>
    </div>
  );
}

function PanelHeader({ index, title, subtitle }: { index: string; title: string; subtitle: string }) {
  return <header className="panel-header"><span>{index}</span><div><h2>{title}</h2><p>{subtitle}</p></div></header>;
}

function MetricCard({ label, value, level }: { label: string; value: string; level?: "high" | "medium" | "low" }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong>{level && <em className={`level ${level}`}>{decisionText(level)}</em>}</div>;
}

function WarningList({ items }: { items: string[] }) {
  return <div className="warning-list">{items.map((item) => <p key={item}><span>!</span>{item}</p>)}</div>;
}

function decisionText(level: "high" | "medium" | "low") {
  return level === "high" ? "Güçlü kanıt" : level === "medium" ? "Kontrol gerekli" : "Belirsiz";
}

function labelize(value: string) {
  return value.replaceAll("_", " ").replace(/(^|\s)\S/g, (letter) => letter.toLocaleUpperCase("tr-TR"));
}
