import { api } from './client'
import type { Batch, BatchItem, CategoriesResponse } from '../types'

export interface BatchDetail { batch: Batch; items: BatchItem[] }
export interface PatchItemPayload {
  category?:       string
  subcategory?:    string
  type?:           string
  cadence?:        import('../types').Cadence
  divide_by?:      number
  shared_expense?: 'Y' | 'N'
  share_ratio?:    number
  amount?:         number
}

export const batchesApi = {
  list:         (includeComplete = false) =>
                  api.get<Batch[]>(`/api/batches${includeComplete ? '?include_complete=1' : ''}`),
  get:          (id: number) => api.get<BatchDetail>(`/api/batches/${id}`),
  patchItem:    (id: number, txnId: number, payload: PatchItemPayload) =>
                  api.patch(`/api/batches/${id}/items/${txnId}`, payload),
  deleteItem:   (id: number, txnId: number) =>
                  api.delete(`/api/batches/${id}/items/${txnId}`),
  deleteBatch:  (id: number) => api.delete(`/api/batches/${id}`),
  markReviewed: (id: number) => api.post(`/api/batches/${id}/mark-reviewed`),
  complete:     (id: number) => api.post<{ ok: boolean; inserted: number }>(`/api/batches/${id}/complete`),
  categories:   () => api.get<CategoriesResponse>('/api/categories'),
}
