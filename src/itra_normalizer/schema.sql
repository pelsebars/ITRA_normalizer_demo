PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sites (
  site_id TEXT PRIMARY KEY,
  site_name TEXT NOT NULL,
  business_application TEXT,
  application_id TEXT,
  state TEXT
);

CREATE TABLE IF NOT EXISTS control_catalog (
  control_id TEXT PRIMARY KEY,
  section_prefix TEXT NOT NULL,
  control_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS control_answers (
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  control_id TEXT NOT NULL REFERENCES control_catalog(control_id),
  status_raw TEXT NOT NULL,
  type TEXT,
  detailed_description TEXT NOT NULL,
  implementation_considerations TEXT,
  normalized_value_json TEXT,
  status_reconciled TEXT,
  reconciliation_note TEXT,
  confidence REAL,
  needs_review INTEGER,
  llm_agreement_rate TEXT,
  model_version TEXT,
  prompt_version TEXT,
  normalized_input_hash TEXT,
  normalized_at TEXT,
  PRIMARY KEY (site_id, control_id)
);

CREATE TABLE IF NOT EXISTS scoping_answers (
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  question_id TEXT NOT NULL,
  question TEXT,
  answer TEXT,
  rationale TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE IF NOT EXISTS technical_answers (
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  question_id TEXT NOT NULL,
  question TEXT,
  answer TEXT,
  comment TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE IF NOT EXISTS security_answers (
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  question_id TEXT NOT NULL,
  question TEXT,
  answer TEXT,
  comment TEXT,
  PRIMARY KEY (site_id, question_id)
);

CREATE TABLE IF NOT EXISTS risks (
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  risk_id TEXT NOT NULL,
  name TEXT,
  gross_impact TEXT,
  gross_likelihood TEXT,
  gross_risk INTEGER,
  net_impact TEXT,
  net_likelihood TEXT,
  net_risk INTEGER,
  comments TEXT,
  PRIMARY KEY (site_id, risk_id)
);

CREATE TABLE IF NOT EXISTS normalization_jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
  planned_api_calls INTEGER NOT NULL,
  actual_api_calls INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_running_normalization_job
ON normalization_jobs(status) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS api_usage_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES normalization_jobs(job_id),
  occurred_at TEXT NOT NULL,
  action TEXT NOT NULL,
  model TEXT NOT NULL,
  response_id TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK(status IN ('completed', 'failed'))
);
