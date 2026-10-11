export type QueryType = "SELECT_SIMPLE" | "SELECT_AGGREGATE" | "SELECT_JOIN" | "SELECT_TEMPORAL" | "UNSUPPORTED";
export const QUERY_TYPES: QueryType[] = ["SELECT_SIMPLE", "SELECT_AGGREGATE", "SELECT_JOIN", "SELECT_TEMPORAL"];

export type QueryStatus =
  | "success" | "unsupported" | "validation_failed" | "execution_error" | "needs_clarification" | "error";

export interface Ambiguity { term: string; candidates: string[]; reason: string }
export interface TableData { columns: string[]; rows: unknown[][] }

export interface QueryResponse {
  status: QueryStatus;
  question: string;
  query_type: QueryType | null;
  sql: string | null;
  explanation: string | null;
  table: TableData | null;
  nl_summary: string | null;
  latency_ms: number;
  row_count: number;
  ambiguities: Ambiguity[];
  message: string | null;
  stage_timings_ms: Record<string, number>;
  log_id: number | null;
  transpiled_sql: string | null;
  target_dialect: string | null;
  cached: boolean;
}

export interface ColumnInfo {
  name: string; type: string; description: string; sensitive: boolean;
  is_primary_key: boolean; foreign_key: string | null;
}
export interface TableInfo { name: string; description: string; columns: ColumnInfo[] }

export interface ExampleRecord { id: number; question: string; sql: string; query_type: QueryType | null }
export interface ExampleHit extends ExampleRecord { score: number }
export interface ExampleIn { question: string; sql: string; query_type: QueryType | null }

export interface QueryLogEntry {
  id: number; created_at: string; question: string; query_type: string | null; sql: string | null;
  status: string; error: string | null; latency_ms: number; row_count: number;
  stage_timings_ms: Record<string, number>;
}

export interface GuardrailConfig {
  allow_select: boolean; allow_insert: boolean; allow_update: boolean; allow_delete: boolean;
  allow_drop: boolean; allow_truncate: boolean; allow_alter: boolean; allow_create: boolean;
  max_rows: number; allowed_table_prefixes: string[]; allowed_schemas: string[];
}

export interface ModelConfig {
  provider: "anthropic" | "claude_cli" | "openai" | "ollama"; model: string; temperature: number;
  dialect: "sqlite" | "postgresql" | "mysql"; max_tokens: number;
}

export type ColumnType = "INTEGER" | "REAL" | "TEXT" | "DATE" | "DATETIME";
export const COLUMN_TYPES: ColumnType[] = ["INTEGER", "REAL", "TEXT", "DATE", "DATETIME"];

export interface PreviewColumn {
  original_name: string; name: string; type: ColumnType; sample_values: string[]; null_count: number;
  suggested_description: string; suggested_sensitive: boolean; sensitive_reason: string | null;
}
export interface PreviewResponse {
  filename: string; suggested_table_name: string; suggested_table_description: string; delimiter: string; encoding: string;
  row_count: number; columns: PreviewColumn[]; sample_rows: (string | null)[][]; warnings: string[];
  name_conflict: boolean; can_replace: boolean;
}
export interface ImportColumn { original_name: string; name: string; type: ColumnType; description: string; sensitive: boolean }
export interface ImportConfig { table_name: string; description: string; mode: "create" | "replace"; columns: ImportColumn[] }
export interface ImportResult { table: TableInfo; rows_imported: number; replaced: boolean }
export interface ImportedTableInfo { table_name: string; source_filename: string; row_count: number; created_at: string }
