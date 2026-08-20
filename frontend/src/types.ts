export type DecisionLevel = "high" | "medium" | "low";

export interface Health {
  status: "ok" | "degraded";
  database: boolean;
  ollama: boolean;
  models_selected: boolean;
  index_ready: boolean;
  details: Record<string, unknown>;
}

export interface ModelInfo {
  name: string;
  size?: number;
  digest?: string;
  modified_at?: string;
}

export interface ModelSelection {
  chat_model: string;
  embedding_model: string;
}

export interface ModelSettings {
  ollama_reachable: boolean;
  available_models: ModelInfo[];
  selected: ModelSelection | null;
  index_ready: boolean;
  index_reason?: string;
}

export interface Job {
  id: string;
  job_type: string;
  document_id?: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage: string;
  error?: string;
  result_id?: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentRecord {
  id: string;
  filename: string;
  mime_type: string;
  sha256: string;
  page_count: number;
  extraction_method?: string;
  original_text?: string;
  corrected_text?: string;
  text_quality: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ExtractedField {
  name: string;
  value?: string;
  source_span?: string;
  status: "present" | "missing" | "uncertain";
}

export interface RouteCandidate {
  unit_id: string;
  unit_name: string;
  score: number;
  rationale: string;
}

export interface Analysis {
  schema_version: "1.0";
  id: string;
  document_id: string;
  document_type: {
    label: string;
    decision_level: DecisionLevel;
    evidence: string[];
  };
  topic: string;
  summary: string;
  extracted_fields: ExtractedField[];
  missing_fields: string[];
  regulations: Array<{
    source_id: string;
    title: string;
    article?: string;
    page?: number;
    quote: string;
    retrieval_score: number;
    verified: boolean;
  }>;
  routing: {
    recommended_unit_id: string;
    alternatives: RouteCandidate[];
    rationale: string;
    decision_level: DecisionLevel;
  };
  warnings: string[];
  requires_human_review: boolean;
  model_name: string;
  prompt_version: string;
  created_at: string;
}

export interface DraftValidation {
  rule_id: string;
  label: string;
  status: "pass" | "warning" | "error";
  message: string;
}

export interface Draft {
  schema_version: "1.0";
  id: string;
  analysis_id: string;
  document_id: string;
  institution_name: string;
  recipient_unit_id: string;
  recipient_unit_name: string;
  letter_type: string;
  number: string;
  date: string;
  subject: string;
  body: string;
  references: string[];
  signatory: string;
  attachments: string[];
  distribution: string[];
  validations: DraftValidation[];
  status: "draft" | "approved";
  version: number;
  model_name: string;
  created_at: string;
  updated_at: string;
}
