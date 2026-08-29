import { api } from './client'
import type { SharedRow, SharedSummary } from '../types'

export interface CreateSharedPayload {
  entry_date:     string
  merchant?:      string
  category?:      string
  subcategory?:   string
  monthly_amount: number
  share_ratio?:   number
  paid_by?:       string
  owed_by?:       string
}

export interface PaymentPayload {
  entry_date: string
  paid_by:    string
  owed_by?:   string
  amount:     number
  note?:      string
}

export interface PatchSharedPayload {
  paid_by?:     string
  owed_by?:     string
  share_ratio?: number
  settled?:     boolean
  is_ignored?:  boolean
}

export const sharedApi = {
  fyList:   () => api.get<number[]>('/api/shared/fy-list'),
  list:     (fy: number) => api.get<SharedRow[]>(`/api/shared?fy=${fy}`),
  summary:  (fy: number) => api.get<SharedSummary>(`/api/shared/summary?fy=${fy}`),
  create:   (rows: CreateSharedPayload[]) => api.post<{ ok: boolean; count: number }>('/api/shared', rows),
  payment:  (payload: PaymentPayload) => api.post<SharedRow>('/api/shared/payment', payload),
  patch:    (id: number, payload: PatchSharedPayload) => api.patch<SharedRow>(`/api/shared/${id}`, payload),
  delete:   (id: number) => api.delete(`/api/shared/${id}`),
}
