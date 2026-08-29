import { api } from './client'
import type { RecurringDef } from '../types'

export interface RecurringPayload {
  entry_text:      string
  merchant?:       string
  amount:          number
  category?:       string
  sub_category?:   string
  spend_type?:     string
  cadence?:        string
  divide_by?:      number
  shared_expense?: 'Y' | 'N'
  share_ratio?:    number
  active?:         boolean
}

export const recurringApi = {
  list:     () => api.get<RecurringDef[]>('/api/recurring'),
  create:   (payload: RecurringPayload) => api.post<RecurringDef>('/api/recurring', payload),
  update:   (id: number, payload: RecurringPayload) => api.put<{ ok: boolean }>(`/api/recurring/${id}`, payload),
  delete:   (id: number) => api.delete(`/api/recurring/${id}`),
  generate: (date?: string) =>
              api.post<{ ok: boolean; count: number; generated: number[] }>(
                `/api/recurring/generate${date ? `?date=${date}` : ''}`
              ),
}
