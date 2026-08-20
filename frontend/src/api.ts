import type {
  Analysis,
  DocumentRecord,
  Draft,
  Health,
  Job,
  ModelSelection,
  ModelSettings,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `İstek başarısız (${response.status})`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Sunucu JSON döndürmediyse durum mesajı yeterlidir.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  modelSettings: () => request<ModelSettings>("/api/v1/settings/models"),
  saveModels: (selection: ModelSelection) =>
    request<ModelSettings>("/api/v1/settings/models", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(selection),
    }),
  reindex: () => request<Job>("/api/v1/admin/reindex", { method: "POST" }),
  upload: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ document_id: string; job_id: string }>("/api/v1/documents", {
      method: "POST",
      body,
    });
  },
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  document: (id: string) => request<DocumentRecord>(`/api/v1/documents/${id}`),
  documentFileUrl: (id: string) => `${API_BASE}/api/v1/documents/${id}/file`,
  saveText: (id: string, text: string) =>
    request<DocumentRecord>(`/api/v1/documents/${id}/text`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  analyze: (id: string) => request<Job>(`/api/v1/documents/${id}/analyze`, { method: "POST" }),
  analysis: (id: string) => request<Analysis>(`/api/v1/analyses/${id}`),
  createDraft: (analysisId: string, unitId: string) =>
    request<Job>(`/api/v1/analyses/${analysisId}/drafts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit_id: unitId }),
    }),
  draft: (id: string) => request<Draft>(`/api/v1/drafts/${id}`),
  updateDraft: (id: string, payload: Partial<Pick<Draft, "subject" | "body" | "references" | "attachments" | "distribution">>) =>
    request<Draft>(`/api/v1/drafts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  approveDraft: (id: string) => request<Draft>(`/api/v1/drafts/${id}/approve`, { method: "POST" }),
  exportUrl: (id: string, format: "docx" | "pdf") => `${API_BASE}/api/v1/drafts/${id}/export?format=${format}`,
};

export async function waitForJob(jobId: string, onProgress: (job: Job) => void): Promise<Job> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 10 * 60 * 1000) {
    const job = await api.job(jobId);
    onProgress(job);
    if (job.status === "succeeded") return job;
    if (job.status === "failed") throw new Error(job.error ?? "İşlem başarısız oldu.");
    await new Promise((resolve) => window.setTimeout(resolve, 900));
  }
  throw new Error("İşlem zaman aşımına uğradı.");
}
