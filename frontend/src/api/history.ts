import { api } from './client'
import type {
  HistoryPeriod, HistoryPage, HistoryRow, HistorySummary, AppSettings,
} from '../types'

export interface CreateHistoryPayload {
  entry_date:     string
  entry_text:     string
  merchant?:      string
  amount:         number
  category?:      string
  sub_category?:  string
  spend_type?:    string
  cadence?:       string
  divide_by?:     number
  shared_expense?: 'Y' | 'N'
  share_ratio?:   number
}

export interface PatchHistoryPayload {
  entry_date?:    string
  time_period?:   string
  entry_text?:    string
  merchant?:      string
  amount?:        number
  category?:      string
  sub_category?:  string
  spend_type?:    string
  cadence?:       string
  divide_by?:     number
  shared_expense?: 'Y' | 'N'
  share_ratio?:   number
}

export interface PatchHistoryResponse {
  ok: boolean
  amount: number
  monthly_amount: number
  final_amount: number
  rows_created?: number
}

export const historyApi = {
  periods:  () => api.get<HistoryPeriod[]>('/api/history/periods'),
  list:     (period: string, page = 1, pageSize = 5000) =>
              api.get<HistoryPage>(`/api/history?period=${encodeURIComponent(period)}&page=${page}&page_size=${pageSize}`),
  summary:  (period: string, prevPeriod?: string) =>
              api.get<HistorySummary>(
                `/api/history/summary?period=${encodeURIComponent(period)}` +
                (prevPeriod ? `&prev_period=${encodeURIComponent(prevPeriod)}` : '')
              ),
  create:   (payload: CreateHistoryPayload) => api.post<{ ok: boolean; count: number }>('/api/history', payload),
  patch:    (id: number, payload: PatchHistoryPayload) =>
              api.patch<PatchHistoryResponse>(`/api/history/${id}`, payload),
  delete:   (id: number) => api.delete(`/api/history/${id}`),
  row:      (id: number) => api.get<HistoryRow>(`/api/history/${id}`),

  getSettings:    () => api.get<AppSettings>('/api/settings'),
  patchSettings:  (payload: Partial<AppSettings>) => api.patch<AppSettings>('/api/settings', payload),
}
