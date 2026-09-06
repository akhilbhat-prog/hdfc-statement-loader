import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Play, CornerDownLeft, Trash2 } from 'lucide-react'
import { Layout } from '../components/Layout'
import { ComboInput } from '../components/ComboInput'
import { useToast } from '../hooks/useToast'
import { batchesApi, type PatchItemPayload } from '../api/batches'
import { api } from '../api/client'
import type { BatchItem, BatchStatus } from '../types'

const PAGE_SIZE = 25

type SortKey = keyof Pick<BatchItem, 'date' | 'merchant' | 'amount' | 'category' | 'subcategory' | 'type' | 'pred_source'>

interface Filters {
  date:           string
  merchant:       string
  amount:         string
  category:       string
  subcategory:    string
  type:           string
  cadence:        string
  shared_expense: string
  pred_source:    string
}
const BLANK_FILTERS: Filters = {
  date: '', merchant: '', amount: '', category: '', subcategory: '', type: '',
  cadence: '', shared_expense: '', pred_source: '',
}
const FILTER_PLACEHOLDERS: Partial<Record<keyof Filters, string>> = {
  date: 'e.g. 2026-05', merchant: 'Search…', amount: 'e.g. >500',
}
const COL_WIDTH: Partial<Record<SortKey, number>> = {
  date: 76, merchant: 220, amount: 96, category: 128, subcategory: 148, type: 106,
}

function fmtAmt(n: number) { return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtDateShort(s: string) {
  return new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}

function matchAmount(val: number, expr: string): boolean {
  const m = expr.match(/^([><=]+)?\s*([\d.]+)$/)
  if (!m) return String(val).includes(expr)
  const [, op, raw] = m
  const n = parseFloat(raw)
  switch (op) {
    case '>=': return val >= n; case '<=': return val <= n
    case '>':  return val > n;  case '<':  return val < n
    default:   return val === n
  }
}

type ItemState = BatchItem & { _saving?: boolean }

export function ReviewPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const [showAll, setShowAll]     = useState(false)
  const [batchId, setBatchId]     = useState<number | null>(null)
  const [items, setItems]         = useState<ItemState[]>([])
  const [sortCol, setSortCol]     = useState<SortKey>('date')
  const [sortDir, setSortDir]     = useState<'asc' | 'desc'>('desc')
  const [filters, setFilters]     = useState<Filters>(BLANK_FILTERS)
  const [page, setPage]           = useState(1)
  const [selectedIds, setSelected] = useState<Set<number>>(new Set())
  const [bulkFields, setBulkFields] = useState({ category: '', subcategory: '', type: '' })
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null)
  const [pipelineRunning, setPipelineRunning] = useState(false)

  const { data: batches = [] } = useQuery({
    queryKey: ['batches', showAll],
    queryFn: () => batchesApi.list(showAll),
    placeholderData: prev => prev,
  })

  const { data: cats } = useQuery({
    queryKey: ['categories'],
    queryFn: batchesApi.categories,
  })

  const activeBatch = batches.find(b => b.id === batchId) ?? null

  const loadBatch = useCallback(async (id: number) => {
    setBatchId(id)
    setPage(1)
    setSelected(new Set())
    setFilters(BLANK_FILTERS)
    const detail = await batchesApi.get(id)
    setItems(detail.items)
  }, [])

  const categoryOptions  = useMemo(() => Object.keys(cats?.categories ?? {}), [cats])
  const typeOptions      = cats?.types ?? []
  const predSrcOptions   = useMemo(
    () => [...new Set(items.map(i => i.pred_source))].sort() as string[],
    [items]
  )
  const filterCategoryOptions    = useMemo(() => [...new Set(items.map(i => i.category).filter(Boolean))].sort(), [items])
  const filterSubcategoryOptions = useMemo(() => [...new Set(items.map(i => i.subcategory).filter(Boolean))].sort(), [items])
  const filterTypeOptions        = useMemo(() => [...new Set(items.map(i => i.type).filter(Boolean))].sort(), [items])
  const filterCadenceOptions     = useMemo(() => [...new Set(items.map(i => i.cadence).filter(Boolean))].sort(), [items])

  function subcatsFor(cat: string) { return cats?.categories[cat] ?? [] }

  // Patch one item — optimistic local update, then persist
  const patchItem = useCallback(async (txnId: number, payload: PatchItemPayload) => {
    if (!batchId) return
    setItems(prev => prev.map(i =>
      i.transaction_id === txnId ? ({ ...i, ...payload, _saving: true } as ItemState) : i
    ))
    try {
      await batchesApi.patchItem(batchId, txnId, payload)
      setItems(prev => prev.map(i =>
        i.transaction_id === txnId ? { ...i, _saving: false } : i
      ))
    } catch (e) {
      toast((e as Error).message, 'error')
      setItems(prev => prev.map(i =>
        i.transaction_id === txnId ? { ...i, _saving: false } : i
      ))
    }
  }, [batchId, toast])

  // Delete item from batch
  const deleteItem = useCallback(async (txnId: number) => {
    if (!batchId) return
    try {
      await batchesApi.deleteItem(batchId, txnId)
      setItems(prev => prev.filter(i => i.transaction_id !== txnId))
      qc.invalidateQueries({ queryKey: ['batches'] })
      toast('Removed from batch', 'success')
    } catch (e) { toast((e as Error).message, 'error') }
  }, [batchId, qc, toast])

  // Revert to prediction
  function revertItem(item: BatchItem) {
    patchItem(item.transaction_id, {
      category:    item.pred_category,
      subcategory: item.pred_subcategory,
      type:        item.pred_type,
    })
  }

  const markReviewedMut = useMutation({
    mutationFn: () => batchesApi.markReviewed(batchId!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['batches'] }); toast('Marked as reviewed', 'success') },
    onError:   (e: Error) => toast(e.message, 'error'),
  })

  const completeMut = useMutation({
    mutationFn: () => batchesApi.complete(batchId!),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['batches'] })
      toast(`Completed — ${r.inserted} rows inserted`, 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteBatchMut = useMutation({
    mutationFn: () => batchesApi.deleteBatch(batchId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['batches'] })
      setBatchId(null); setItems([])
      toast('Batch deleted', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  async function runPipeline() {
    setPipelineRunning(true); setPipelineMsg(null)
    try {
      const r = await api.post<{ processed: number; skipped: number; failed: number }>('/trigger')
      setPipelineMsg(`${r.processed} processed · ${r.skipped} skipped · ${r.failed} failed`)
      qc.invalidateQueries({ queryKey: ['batches'] })
    } catch (e) {
      setPipelineMsg(`Error: ${(e as Error).message}`)
    } finally { setPipelineRunning(false) }
  }

  // Filters + sort
  function sort(col: SortKey) {
    setSortDir(sortCol === col && sortDir === 'asc' ? 'desc' : 'asc')
    setSortCol(col)
    setPage(1)
  }
  function arr(col: SortKey) { return sortCol === col && sortDir === 'desc' ? ' ▼' : ' ▲' }

  const filtered = useMemo(() => {
    let r = [...items]
    if (filters.date)        r = r.filter(i => i.date.includes(filters.date))
    if (filters.merchant)    r = r.filter(i => i.merchant.toLowerCase().includes(filters.merchant.toLowerCase()))
    if (filters.amount)      r = r.filter(i => matchAmount(i.amount, filters.amount))
    if (filters.category)       r = r.filter(i => i.category === filters.category)
    if (filters.subcategory)    r = r.filter(i => i.subcategory === filters.subcategory)
    if (filters.type)           r = r.filter(i => i.type === filters.type)
    if (filters.cadence)        r = r.filter(i => i.cadence === filters.cadence)
    if (filters.shared_expense) r = r.filter(i => i.shared_expense === filters.shared_expense)
    if (filters.pred_source)    r = r.filter(i => i.pred_source === filters.pred_source)
    r.sort((a, b) => {
      const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
    return r
  }, [items, filters, sortCol, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageItems  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const allSelected = pageItems.length > 0 && pageItems.every(i => selectedIds.has(i.transaction_id))
  function toggleAll() {
    allSelected
      ? setSelected(new Set())
      : setSelected(new Set(pageItems.map(i => i.transaction_id)))
  }
  function toggleRow(id: number) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function applyBulk() {
    if (!bulkFields.category || !bulkFields.subcategory || !bulkFields.type) return
    for (const txnId of selectedIds) {
      await patchItem(txnId, bulkFields as PatchItemPayload)
    }
    setSelected(new Set())
    toast(`Applied to ${selectedIds.size} rows`, 'success')
  }

  async function bulkDelete() {
    if (!confirm(`Remove ${selectedIds.size} rows from batch?`)) return
    for (const txnId of selectedIds) { await deleteItem(txnId) }
    setSelected(new Set())
  }

  function statusPill(status: BatchStatus) {
    return <span className={`pill pill-${status}`}>{status}</span>
  }

  const isComplete = activeBatch?.status === 'complete'

  const sidebar = (
    <>
      <div className="sidebar-header">
        Batches
        <button
          className={`sidebar-toggle${showAll ? ' active' : ''}`}
          onClick={() => setShowAll(v => !v)}
        >
          {showAll ? 'Hide completed' : 'Show all'}
        </button>
      </div>
      {batches.map(b => (
        <div
          key={b.id}
          className={`sidebar-item${b.id === batchId ? ' active' : ''}`}
          onClick={() => loadBatch(b.id)}
        >
          <div className="sidebar-item-title">Batch #{b.id}</div>
          <div className="sidebar-item-meta">{b.row_count} items {statusPill(b.status)}</div>
          <div className="sidebar-item-meta">{fmtDate(b.created_at)}</div>
        </div>
      ))}
      {batches.length === 0 && (
        <div className="empty-state" style={{ padding: 20, fontSize: 12 }}>No batches</div>
      )}
      <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', marginTop: 'auto' }}>
        <button
          className="btn btn-secondary btn-sm"
          style={{ width: '100%', marginBottom: 6, justifyContent: 'center' }}
          onClick={runPipeline}
          disabled={pipelineRunning}
        >
          <Play size={12} /> {pipelineRunning ? 'Running…' : 'Run Pipeline'}
        </button>
        {pipelineMsg && (
          <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'center', marginTop: 4 }}>
            {pipelineMsg}
          </div>
        )}
      </div>
    </>
  )

  return (
    <Layout sidebar={sidebar}>
      {!activeBatch ? (
        <div className="empty-state">Select a batch from the sidebar</div>
      ) : (
        <>
          {/* Table */}
          <div className="card">
            <div className="card-header">
              <div>
                <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-0.2px' }}>Batch #{activeBatch.id}</div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                  {activeBatch.row_count} items · {activeBatch.status}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {!isComplete && (
                  <>
                    <button
                      className="btn btn-ghost"
                      onClick={() => markReviewedMut.mutate()}
                      disabled={activeBatch.status !== 'pending' || markReviewedMut.isPending}
                    >Mark Reviewed</button>
                    <button
                      className="btn btn-primary"
                      onClick={() => completeMut.mutate()}
                      disabled={activeBatch.status !== 'reviewed' || completeMut.isPending}
                    >{completeMut.isPending ? 'Completing…' : 'Complete Batch'}</button>
                    <button
                      className="btn btn-danger"
                      onClick={() => { if (confirm('Delete batch?')) deleteBatchMut.mutate() }}
                      disabled={deleteBatchMut.isPending}
                    >Delete Batch</button>
                  </>
                )}
              </div>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className={`data-table${isComplete ? ' batch-complete' : ''}`}>
                <thead>
                  <tr>
                    {!isComplete && (
                      <th style={{ width: 36, textAlign: 'center' }}>
                        <input type="checkbox" checked={allSelected} onChange={toggleAll}
                          style={{ cursor: 'pointer' }}
                          ref={el => { if (el) el.indeterminate = selectedIds.size > 0 && !allSelected }} />
                      </th>
                    )}
                    {([
                      ['date',      'Date'],
                      ['merchant',  'Merchant'],
                      ['amount',    'Amount'],
                      ['category',  'Category'],
                      ['subcategory','Subcategory'],
                      ['type',      'Type'],
                    ] as [SortKey, string][]).map(([k, label]) => (
                      <th key={k} className={`sortable${sortCol === k ? ' sort-active' : ''}`} onClick={() => sort(k)}
                        style={{
                          ...(k === 'amount' ? { textAlign: 'right' as const } : {}),
                          ...(COL_WIDTH[k] ? { width: COL_WIDTH[k] } : {}),
                        }}>
                        {label}{arr(k)}
                      </th>
                    ))}
                    <th style={{ textAlign: 'right', width: 56 }}>Cadence</th>
                    <th style={{ textAlign: 'right', width: 56 }}>Div By</th>
                    <th style={{ width: 50 }}>Shared</th>
                    <th style={{ textAlign: 'right', width: 66 }}>Share %</th>
                    <th style={{ textAlign: 'right', width: 86 }}>Mo. Amt</th>
                    <th style={{ textAlign: 'right', width: 86 }}>Final Amt</th>
                    <th className={`sortable${sortCol === 'pred_source' ? ' sort-active' : ''}`} onClick={() => sort('pred_source')}
                      style={{ width: 68 }}>
                      Source{arr('pred_source')}
                    </th>
                    <th style={{ width: 54 }}></th>
                  </tr>
                  {/* Filter row */}
                  <tr className="filter-row">
                    {!isComplete && <th></th>}
                    {(['date','merchant','amount'] as (keyof Filters)[]).map(k => (
                      <th key={k}>
                        <input
                          className={`filter-input${filters[k] ? ' active' : ''}`}
                          value={filters[k]}
                          onChange={e => { setFilters(f => ({ ...f, [k]: e.target.value })); setPage(1) }}
                          placeholder={FILTER_PLACEHOLDERS[k]}
                        />
                      </th>
                    ))}
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.category}
                        onChange={e => { setFilters(f => ({ ...f, category: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {filterCategoryOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                    </th>
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.subcategory}
                        onChange={e => { setFilters(f => ({ ...f, subcategory: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {filterSubcategoryOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                    </th>
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.type}
                        onChange={e => { setFilters(f => ({ ...f, type: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {filterTypeOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                    </th>
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.cadence}
                        onChange={e => { setFilters(f => ({ ...f, cadence: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {filterCadenceOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                    </th>
                    <th></th>
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.shared_expense}
                        onChange={e => { setFilters(f => ({ ...f, shared_expense: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        <option value="Y">Y</option>
                        <option value="N">N</option>
                      </select>
                    </th>
                    <th></th>
                    <th></th>
                    <th></th>
                    <th>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.pred_source}
                        onChange={e => { setFilters(f => ({ ...f, pred_source: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {predSrcOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                    </th>
                    <th>
                      {Object.values(filters).some(Boolean) && (
                        <button className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}
                          onClick={() => setFilters(BLANK_FILTERS)}>Clear</button>
                      )}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map(item => {
                    const diffCat = item.category !== item.pred_category
                    const diffSub = item.subcategory !== item.pred_subcategory
                    return (
                      <tr key={item.transaction_id}
                        className={selectedIds.has(item.transaction_id) ? 'selected' : ''}
                        style={{ opacity: (item as ItemState)._saving ? 0.6 : 1 }}>
                        {!isComplete && (
                          <td style={{ textAlign: 'center' }}>
                            <input type="checkbox" checked={selectedIds.has(item.transaction_id)}
                              onChange={() => toggleRow(item.transaction_id)} style={{ cursor: 'pointer' }} />
                          </td>
                        )}
                        <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap', fontSize: 12 }}>
                          {fmtDateShort(item.date)}
                        </td>
                        <td>
                          <div className="merchant-name" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {item.merchant}
                          </div>
                          <div className="merchant-entry" title={item.raw_entry}>{item.raw_entry}</div>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {isComplete ? (
                            fmtAmt(item.amount)
                          ) : (
                            <input type="text" inputMode="decimal" className="field-input" style={{ width: 90 }}
                              value={item.amount}
                              onChange={e => patchItem(item.transaction_id, { amount: parseFloat(e.target.value) || item.amount })} />
                          )}
                        </td>
                        <td>
                          {isComplete ? item.category : (
                            <div>
                              <ComboInput value={item.category} options={categoryOptions}
                                onChange={v => patchItem(item.transaction_id, { category: v, subcategory: '' })}
                                style={{ width: '100%' }} />
                              <div className={`pred-hint${diffCat ? ' differs' : ''}`}>
                                ML: {item.pred_category}
                              </div>
                            </div>
                          )}
                        </td>
                        <td>
                          {isComplete ? item.subcategory : (
                            <div>
                              <ComboInput value={item.subcategory} options={subcatsFor(item.category)}
                                onChange={v => patchItem(item.transaction_id, { subcategory: v })}
                                style={{ width: '100%' }} />
                              <div className={`pred-hint${diffSub ? ' differs' : ''}`}>
                                ML: {item.pred_subcategory}
                              </div>
                            </div>
                          )}
                        </td>
                        <td>
                          {isComplete ? item.type : (
                            <ComboInput value={item.type} options={typeOptions}
                              onChange={v => patchItem(item.transaction_id, { type: v })}
                              style={{ width: '100%' }} />
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {isComplete ? item.cadence : (
                            <input type="text" className="field-input" style={{ width: 46 }}
                              value={item.cadence}
                              onChange={e => patchItem(item.transaction_id, { cadence: e.target.value as BatchItem['cadence'] })} />
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {isComplete ? item.divide_by : (
                            <input type="text" inputMode="numeric" className="field-input" style={{ width: 44 }}
                              value={item.divide_by}
                              onChange={e => patchItem(item.transaction_id, { divide_by: parseInt(e.target.value) || 1 })} />
                          )}
                        </td>
                        <td>
                          {isComplete ? item.shared_expense : (
                            <input type="checkbox" checked={item.shared_expense === 'Y'}
                              onChange={e => patchItem(item.transaction_id, { shared_expense: e.target.checked ? 'Y' : 'N' })} />
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {isComplete ? item.share_ratio.toFixed(2) : (
                            <input type="text" inputMode="decimal" className="field-input" style={{ width: 52 }}
                              value={item.share_ratio}
                              onChange={e => patchItem(item.transaction_id, { share_ratio: parseFloat(e.target.value) || 1 })} />
                          )}
                        </td>
                        <td style={{ textAlign: 'right', fontSize: 12, color: 'var(--muted)' }}>
                          {(item.amount / (item.divide_by || 1)).toFixed(2)}
                        </td>
                        <td style={{ textAlign: 'right', fontSize: 12, color: 'var(--muted)' }}>
                          {((item.amount / (item.divide_by || 1)) * (item.share_ratio ?? 1)).toFixed(2)}
                        </td>
                        <td>
                          <span className={`pred-source pred-source-${item.pred_source || 'none'}`}>{item.pred_source || 'none'}</span>
                          {item.pred_confidence > 0 && (
                            <div className="confidence">{Math.round(item.pred_confidence * 100)}%</div>
                          )}
                        </td>
                        <td>
                          {!isComplete && (
                            <div style={{ display: 'flex', gap: 4 }}>
                              <button className="btn btn-ghost btn-icon" title="Revert to prediction"
                                onClick={() => revertItem(item)}>
                                <CornerDownLeft size={12} />
                              </button>
                              <button className="btn btn-ghost btn-icon danger" title="Delete row"
                                onClick={() => { if (confirm('Remove from batch?')) deleteItem(item.transaction_id) }}>
                                <Trash2 size={12} />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination">
                  <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                    <ChevronLeft size={12} /> Prev
                  </button>
                  <span className="page-info">Page {page} of {totalPages} · {filtered.length} items</span>
                  <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                    Next <ChevronRight size={12} />
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Bulk bar */}
          {!isComplete && (
            <div className={`bulk-bar${selectedIds.size > 0 ? ' visible' : ''}`}>
              <span className="bulk-count">{selectedIds.size} rows selected</span>
              <div className="bulk-sep" />
              <span className="bulk-label">Edit:</span>
              <ComboInput value={bulkFields.category} options={categoryOptions} placeholder="Category…"
                onChange={v => setBulkFields(f => ({ ...f, category: v, subcategory: '' }))}
                style={{ width: 140 }} />
              <ComboInput value={bulkFields.subcategory} options={subcatsFor(bulkFields.category)} placeholder="Subcategory…"
                onChange={v => setBulkFields(f => ({ ...f, subcategory: v }))}
                style={{ width: 150 }} />
              <ComboInput value={bulkFields.type} options={typeOptions} placeholder="Type…"
                onChange={v => setBulkFields(f => ({ ...f, type: v }))}
                style={{ width: 120 }} />
              <button className="btn btn-primary btn-sm"
                disabled={!bulkFields.category || !bulkFields.subcategory || !bulkFields.type}
                onClick={applyBulk}>
                Apply to selected
              </button>
              <div className="bulk-sep" />
              <button className="btn btn-danger btn-sm" onClick={bulkDelete}>
                <Trash2 size={12} /> Delete selected
              </button>
              <button className="bulk-dismiss" onClick={() => setSelected(new Set())} title="Dismiss">×</button>
            </div>
          )}
        </>
      )}
    </Layout>
  )
}
