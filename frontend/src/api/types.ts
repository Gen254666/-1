export interface User {
  id: string;
  username: string;
  role: "admin" | "user";
  must_change_password: boolean;
}

export interface QuoteItem {
  point_id: string;
  code: string;
  category: string;
  spec: string;
  region: string;
  quote_date: string;
  price: number;
  change: number | null;
  source: string;
}

export interface QuotePage {
  total: number;
  page: number;
  page_size: number;
  items: QuoteItem[];
}

export interface InventoryItem {
  block: string;
  spec: string;
  unit_price: number | null;
  tax_add: number | null;
  weight_per_piece: number | null;
  pieces: number | null;
  total_weight: number | null;
  price_per_piece: number | null;
  manufacturer: string | null;
  row_no: number;
}

export interface InventoryPage {
  snapshot_date: string | null;
  warehouse: string | null;
  total: number;
  items: InventoryItem[];
}

export interface AnomalyItem {
  kind: string;
  name: string;
  value: number;
  threshold: number;
  message: string;
  point_id: string | null;
  spec: string | null;
}

export interface DashboardData {
  date: string | null;
  quotes: { total: number; items: QuoteItem[] };
  inventory: InventoryPage;
  anomalies: AnomalyItem[];
}

export interface Artifact {
  type: "cards" | "chart" | "table" | "quote" | "report" | "text";
  payload: any;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  artifacts: Artifact[] | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface QuoteLine {
  spec: string;
  unit_price: number;
  tax_add: number | null;
  weight_per_piece: number;
  pieces: number;
  price_per_piece: number;
  subtotal: number;
  ton_price: number;
}

export interface QuoteResult {
  lines: QuoteLine[];
  freight: number;
  processing_fee: number;
  total: number;
  total_weight: number;
  average_ton_price: number;
  tax_mode: string;
  warnings: string[];
  sources: any[];
  disclaimer: string;
  valid_until: string;
}

export interface ImportBatch {
  id: string;
  dataset_type: string;
  effective_date: string;
  file_name: string;
  status: string;
  rows_total: number;
  rows_ok: number;
  rows_failed: number;
  errors: any[];
  created_at: string;
  rolled_back_at: string | null;
}

export interface AnomalyConfig {
  daily_change_pct: number;
  consecutive_days: number;
  inventory_deviation_pct: number;
  low_stock_pieces: number;
}
