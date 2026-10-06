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
