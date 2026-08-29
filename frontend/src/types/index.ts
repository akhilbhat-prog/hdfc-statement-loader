// Spend types are always capitalised in the DB
export type SpendType = 'Expense' | 'Investment' | 'Saving'
export type TransactionType = 'debit' | 'credit'
export type BatchStatus = 'pending' | 'reviewed' | 'complete'
export type Cadence = 'O' | 'M' | 'Q' | 'A'
export type PredSource = 'memory' | 'rule' | 'ml' | 'none'

export interface User {
  username: string
  role: 'admin' | 'user'
}

// ── Batches / Review ─────────────────────────────────────────────
export interface Batch {
  id: number
  row_count: number
  status: BatchStatus
  created_at: string
}

export interface BatchItem {
  transaction_id: number
  date: string
  merchant: string
  raw_entry: string
  amount: number
  // ML predictions (read-only)
  pred_category: string
  pred_subcategory: string
  pred_type: string
  pred_confidence: number
  pred_source: PredSource
  // Editable (human review)
  category: string
  subcategory: string
  type: string
  cadence: Cadence
  divide_by: number
  shared_expense: 'Y' | 'N'
  share_ratio: number
}

export interface CategoriesResponse {
  categories: Record<string, string[]>
  types: string[]
}

// ── History / View ───────────────────────────────────────────────
export interface HistoryPeriod {
  period: string
  count: number
}

export interface HistoryRow {
  id: number
  entry_date: string
  time_period: string
  entry_text: string
  merchant: string | null
  amount: number
  monthly_amount: number
  final_amount: number
  category: string | null
  sub_category: string | null
  spend_type: SpendType | null
  cadence: Cadence
  divide_by: number
  shared_expense: 'Y' | 'N'
  share_ratio: number
}

export interface HistoryPage {
  items: HistoryRow[]
  total: number
  page: number
  pages: number
}

export interface SummaryCategory {
  category: string
  total: number
  count: number
  prev_total: number | null
}

export interface HistorySummary {
  top_categories: SummaryCategory[]
  period_total: number
}

export interface AppSettings {
  default_share_ratio: number
  default_annual_divisor: number
}

// ── Shared ───────────────────────────────────────────────────────
export interface SharedRow {
  id: number
  history_id: number | null
  paid_by: string
  owed_by: string
  amount: number
  monthly_amount: number | null
  share_ratio: number
  akhil_share: number
  aditi_share: number
  balance: number
  entry_date: string | null
  merchant: string | null
  category: string | null
  subcategory: string | null
  entry_text: string | null
  settled: boolean
  settled_at: string | null
  is_manual: boolean
  is_payment: boolean
  is_ignored: boolean
  created_at: string
}

export interface SharedSummary {
  net_balance: number
  total_akhil_paid: number
  total_aditi_paid: number
}

// ── Recurring ────────────────────────────────────────────────────
export interface RecurringDef {
  id: number
  entry_text: string
  merchant: string | null
  amount: number
  category: string | null
  sub_category: string | null
  spend_type: SpendType | null
  cadence: Cadence
  divide_by: number
  shared_expense: 'Y' | 'N'
  share_ratio: number
  active: boolean
  last_generated: string | null
  created_at: string
}
