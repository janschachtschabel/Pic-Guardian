// Spiegelt den Ergebnis-Contract des FastAPI-Backends (app/schemas.py).

export type Verdict = 'red' | 'yellow' | 'green' | 'neutral' | 'info';
export type SignalStatus = 'done' | 'skipped' | 'unavailable' | 'error';

export interface CheckSignal {
  id: string;
  label: string;
  category: string;
  status: SignalStatus;
  verdict: Verdict;
  confidence: number;
  summary: string;
  evidence: string[];
  external: boolean;
  duration_ms: number | null;
  data: Record<string, unknown>;
}

export interface ExtractedFields {
  license_status: Verdict;
  license_uri: string | null;
  license_label: string | null;
  license_field: string | null;
  acquire_url: string | null;
  credit_text: string | null;
  creator: string | null;
  supplier: string | null;
  source_domain: string | null;
  source_page: string | null;
  phash: string | null;
  sha1: string | null;
  c2pa_status: string | null;
  watermark_score: number | null;
}

export interface SourceInfo {
  mode: string;
  origin_url: string | null;
  source_page: string | null;
  filename: string | null;
  mime: string | null;
  width: number | null;
  height: number | null;
  size_bytes: number | null;
  node_id: string | null;
  repository: string | null;
  node_render_url: string | null;
}

export type ResultCategory =
  | 'unproblematisch' | 'zu_pruefen' | 'nicht_messbar' | 'problematisch';

export interface CheckReport {
  verdict: Verdict;
  category: ResultCategory;
  category_label: string;
  confidence: number;
  headline: string;
  recommendation: string;
  signals: CheckSignal[];
  fields: ExtractedFields;
  source: SourceInfo;
  image_data_uri: string | null;
  external_used: boolean;
  checked_at: string | null;
}

export interface RepositoryInfo {
  id: string;
  label: string;
  base_url: string;
}

export interface RepositoryList {
  repositories: RepositoryInfo[];
  default: string;
}

export interface BatchStatus {
  job_id: string;
  kind: string;
  source: string;
  status: 'pending' | 'running' | 'done' | 'error';
  total: number | null;
  done: number;
  counts: { red: number; yellow: number; green: number; error: number };
  kategorien?: {
    problematisch: number; zu_pruefen: number; nicht_messbar: number;
    unproblematisch: number; fehler: number;
  };
  truncated: boolean;
  warnings: string[];
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

/** Einzelergebnis eines Batch-Laufs (Contract: app/batch.py BatchItemResult). */
export interface BatchItem {
  node_id: string;
  repository: string;
  verdict: 'red' | 'yellow' | 'green' | 'error' | '';
  category: ResultCategory | '';
  confidence: number;
  headline: string;
  license_label: string;
  supplier: string;
  credit_text: string;
  source_page: string;
  source_domain: string;
  render_url: string;
  reasons: string;
  error: string;
}

export interface BatchResults {
  job: BatchStatus;
  results: BatchItem[];
}

export interface ReviewConfirmResponse {
  added: { phash: string | null; sha1: string | null; note: string } | null;
  duplicate: boolean;
  risk_hub_size: number;
}
