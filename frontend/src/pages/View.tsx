import { useState, useMemo, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, ChevronLeft, ChevronRight } from 'lucide-react'
import { Layout } from '../components/Layout'
import { ComboInput } from '../components/ComboInput'
import { useToast } from '../hooks/useToast'
import { historyApi, type PatchHistoryPayload, type CreateHistoryPayload } from '../api/history'
import { batchesApi } from '../api/batches'
import type { HistoryRow, AppSettings, Cadence, SpendType } from '../types'

const PAGE_SIZE = 25
type SortKey = 'entry_date' | 'merchant' | 'category' | 'sub_category' | 'spend_type' | 'amount' | 'time_period'

function fmtAmt(n: number | null | undefined) {
  if (n == null) return '—'
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2 })
}

function fmtDateShort(s: string) {
  return new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}

const COL_WIDTH: Partial<Record<SortKey, number>> = {
  entry_date: 76, amount: 90, category: 128, sub_category: 148, spend_type: 106,
}

function prevPeriod(period: string): string | undefined {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const [mon, yr] = period.split('-')
  const mi = months.indexOf(mon)
  if (mi < 0) return undefined
  const prevMi = mi === 0 ? 11 : mi - 1
  const prevYr = mi === 0 ? parseInt(yr) - 1 : parseInt(yr)
  return `${months[prevMi]}-${prevYr}`
}

interface Filters {
  merchant: string; category: string; sub_category: string; spend_type: string; amount: string
  cadence: string; shared_expense: string
}
const BLANK_FILTERS: Filters = {
  merchant: '', category: '', sub_category: '', spend_type: '', amount: '',
  cadence: '', shared_expense: '',
}

function matchAmount(val: number, expr: string): boolean {
  const m = expr.match(/^([><=!]+)?\s*([\d.]+)$/)
  if (!m) return String(val).includes(expr)
  const [, op, raw] = m
  const n = parseFloat(raw)
  switch (op) {
    case '>=': return val >= n
    case '<=': return val <= n
    case '>':  return val > n
    case '<':  return val < n
    default:   return val === n
  }
}

export function ViewPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const [period, setPeriod]     = useState<string | null>(null)
  const [page, setPage]         = useState(1)
  const [sortCol, setSortCol]   = useState<SortKey>('entry_date')
  const [sortDir, setSortDir]   = useState<'asc' | 'desc'>('desc')
  const [filters, setFilters]   = useState<Filters>(BLANK_FILTERS)
  const [selectedIds, setSelected] = useState<Set<number>>(new Set())
  const [dirty, setDirty]       = useState<Map<number, Partial<HistoryRow>>>(new Map())
  const [addModal, setAddModal] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState<AppSettings>({ default_share_ratio: 0.7, default_annual_divisor: 12 })
  const [bulkFields, setBulkFields] = useState({ category: '', sub_category: '', spend_type: '' })

  const { data: periods = [] } = useQuery({
    queryKey: ['history-periods'],
    queryFn: historyApi.periods,
  })

  const { data: cats } = useQuery({
    queryKey: ['categories'],
    queryFn: batchesApi.categories,
  })

  const { data: settingsData } = useQuery({
    queryKey: ['settings'],
    queryFn: historyApi.getSettings,
  })

  useEffect(() => {
    if (settingsData) setSettings(settingsData)
  }, [settingsData])

  const activePeriod = period ?? periods[0]?.period ?? null

  const { data: histPage, isLoading } = useQuery({
    queryKey: ['history', activePeriod],
    queryFn: () => historyApi.list(activePeriod!, 1, 5000),
    enabled: !!activePeriod,
  })

  const { data: summary } = useQuery({
    queryKey: ['history-summary', activePeriod],
    queryFn: () => historyApi.summary(activePeriod!, prevPeriod(activePeriod!)),
    enabled: !!activePeriod,
  })

  useEffect(() => { setPage(1); setSelected(new Set()); setDirty(new Map()) }, [activePeriod])

  const allItems: HistoryRow[] = histPage?.items ?? []

  const categoryOptions = useMemo(() => Object.keys(cats?.categories ?? {}), [cats])
  const typeOptions = cats?.types ?? []

  function subcatsFor(cat: string) {
    return cats?.categories[cat] ?? []
  }

  const filterCategoryOptions    = useMemo(() => [...new Set(allItems.map(i => i.category).filter((v): v is string => !!v))].sort(), [allItems])
  const filterSubcategoryOptions = useMemo(() => [...new Set(allItems.map(i => i.sub_category).filter((v): v is string => !!v))].sort(), [allItems])
  const filterTypeOptions        = useMemo(() => [...new Set(allItems.map(i => i.spend_type).filter((v): v is SpendType => !!v))].sort(), [allItems])
  const filterCadenceOptions     = useMemo(() => [...new Set(allItems.map(i => i.cadence).filter(Boolean))].sort(), [allItems])

  // Apply filters + sort
  const filtered = useMemo(() => {
    let r = [...allItems]
    if (filters.merchant)       r = r.filter(i => (i.merchant ?? i.entry_text).toLowerCase().includes(filters.merchant.toLowerCase()))
    if (filters.category)       r = r.filter(i => i.category === filters.category)
    if (filters.sub_category)   r = r.filter(i => i.sub_category === filters.sub_category)
    if (filters.spend_type)     r = r.filter(i => i.spend_type === filters.spend_type)
    if (filters.cadence)        r = r.filter(i => i.cadence === filters.cadence)
    if (filters.shared_expense) r = r.filter(i => i.shared_expense === filters.shared_expense)
    if (filters.amount)         r = r.filter(i => matchAmount(i.amount, filters.amount))
    r.sort((a, b) => {
      const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
    return r
  }, [allItems, filters, sortCol, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageItems  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function sort(col: SortKey) {
    setSortDir(sortCol === col && sortDir === 'asc' ? 'desc' : 'asc')
    setSortCol(col)
    setPage(1)
  }

  function arr(col: SortKey) {
    return sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''
  }

  // Dirty row editing
  function getVal<K extends keyof HistoryRow>(row: HistoryRow, k: K): HistoryRow[K] {
    const d = dirty.get(row.id)
    return (d?.[k] !== undefined ? d[k] : row[k]) as HistoryRow[K]
  }

  function setField(id: number, k: keyof HistoryRow, v: unknown) {
    setDirty(prev => {
      const n = new Map(prev)
      const cur = n.get(id) ?? {}
      n.set(id, { ...cur, [k]: v })
      return n
    })
  }

  const patchMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: PatchHistoryPayload }) =>
      historyApi.patch(id, payload),
    onSuccess: (_r, { id }) => {
      qc.invalidateQueries({ queryKey: ['history', activePeriod] })
      qc.invalidateQueries({ queryKey: ['history-summary', activePeriod] })
      qc.invalidateQueries({ queryKey: ['history-periods'] })
      setDirty(prev => { const n = new Map(prev); n.delete(id); return n })
      toast('Updated', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: historyApi.delete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history', activePeriod] })
      qc.invalidateQueries({ queryKey: ['history-summary', activePeriod] })
      qc.invalidateQueries({ queryKey: ['history-periods'] })
      toast('Deleted', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function saveRow(row: HistoryRow) {
    const d = dirty.get(row.id)
    if (!d) return
    patchMut.mutate({ id: row.id, payload: d as PatchHistoryPayload })
  }

  // Selection
  const allSelected = pageItems.length > 0 && pageItems.every(i => selectedIds.has(i.id))
  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(pageItems.map(i => i.id)))
  }
  function toggleRow(id: number) {
    setSelected(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  function applyBulk() {
    const ids = [...selectedIds]
    const payloads = ids.map(id =>
      historyApi.patch(id, bulkFields as PatchHistoryPayload)
    )
    Promise.all(payloads)
      .then(() => {
        qc.invalidateQueries({ queryKey: ['history', activePeriod] })
        qc.invalidateQueries({ queryKey: ['history-summary', activePeriod] })
        setSelected(new Set())
        toast(`Updated ${ids.length} rows`, 'success')
      })
      .catch((e: Error) => toast(e.message, 'error'))
  }

  function bulkDelete() {
    if (!confirm(`Delete ${selectedIds.size} rows?`)) return
    Promise.all([...selectedIds].map(id => historyApi.delete(id)))
      .then(() => {
        qc.invalidateQueries({ queryKey: ['history', activePeriod] })
        qc.invalidateQueries({ queryKey: ['history-periods'] })
        setSelected(new Set())
        toast('Deleted selected rows', 'success')
      })
      .catch((e: Error) => toast(e.message, 'error'))
  }

  const saveSettings = useCallback((s: AppSettings) => {
    historyApi.patchSettings(s)
      .then(updated => { setSettings(updated); toast('Settings saved', 'success') })
      .catch((e: Error) => toast(e.message, 'error'))
  }, [toast])

  const sidebar = (
    <>
      <div className="sidebar-header">Time Periods</div>
      {periods.map(p => (
        <div
          key={p.period}
          className={`sidebar-item${activePeriod === p.period ? ' active' : ''}`}
          onClick={() => { setPeriod(p.period); setPage(1) }}
        >
          <div className="sidebar-item-title">{p.period}</div>
          <div className="sidebar-item-meta">{p.count} rows</div>
        </div>
      ))}
    </>
  )

  const headerExtra = (
    <div style={{ display: 'flex', gap: 8, position: 'relative' }}>
      <button className="btn btn-ghost" title="Defaults" style={{ fontSize: 15, padding: '5px 9px' }} onClick={() => setSettingsOpen(v => !v)}>
        ⚙
      </button>
      {settingsOpen && (
        <SettingsPanel
          settings={settings}
          onSave={saveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )

  return (
    <Layout sidebar={sidebar} headerExtra={headerExtra}>
      {/* Summary cards */}
      {summary && (
        <div className="summary-cards">
          {summary.top_categories.slice(0, 5).map(c => {
            const delta = c.prev_total != null ? c.total - c.prev_total : null
            return (
              <div key={c.category} className="summary-card">
                <div className="sc-label">{c.category}</div>
                <div className="sc-value" style={{ fontSize: 18 }}>{fmtAmt(c.total)}</div>
                {delta != null && (
                  <div className={`sc-sub ${delta > 0 ? 'sc-delta-up' : 'sc-delta-down'}`}>
                    {delta > 0 ? '▲' : '▼'} {fmtAmt(Math.abs(delta))} MoM
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Table */}
      <div className="card">
        <div className="card-header">
          <div>
            <div>
              {activePeriod
                ? summary?.period_total != null
                  ? `${activePeriod} (${fmtAmt(summary.period_total)})`
                  : activePeriod
                : 'Select a period'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 400, marginTop: 2 }}>
              {filtered.length} rows
            </div>
          </div>
          <button
            className="btn btn-ghost btn-sm"
            style={{ borderRadius: 6, border: '1px solid var(--border2)' }}
            onClick={() => setAddModal(true)}
          >
            + Add Entry
          </button>
        </div>
        {isLoading ? (
          <div className="empty-state">Loading…</div>
        ) : !activePeriod ? (
          <div className="empty-state">Select a period from the sidebar</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 32, textAlign: 'center' }}>
                    <input type="checkbox" checked={allSelected} onChange={toggleAll}
                      style={{ cursor: 'pointer' }} ref={el => { if (el) el.indeterminate = selectedIds.size > 0 && !allSelected }} />
                  </th>
                  {([
                    ['entry_date',   'Date'],
                    ['merchant',     'Merchant'],
                    ['amount',       'Amount'],
                    ['category',     'Category'],
                    ['sub_category', 'Subcategory'],
                    ['spend_type',   'Type'],
                  ] as [SortKey, string][]).map(([k, label]) => (
                    <th key={k} className={`sortable${sortCol === k ? ' sort-active' : ''}`} onClick={() => sort(k)}
                      style={{
                        ...(k === 'amount' ? { textAlign: 'right' as const } : {}),
                        ...(COL_WIDTH[k] ? { width: COL_WIDTH[k] } : {}),
                      }}>
                      {label}{arr(k)}
                    </th>
                  ))}
                  <th style={{ textAlign: 'right' }}>Monthly</th>
                  <th style={{ textAlign: 'right' }}>Final</th>
                  <th style={{ textAlign: 'center' }}>Shared</th>
                  <th style={{ width: 64 }}></th>
                </tr>
                {/* Filter row */}
                <tr className="filter-row">
                  <th></th>
                  {(['merchant', 'amount'] as (keyof Filters)[]).map(k => (
                    <th key={k}>
                      <input
                        className={`filter-input${filters[k] ? ' active' : ''}`}
                        value={filters[k]}
                        onChange={e => { setFilters(f => ({ ...f, [k]: e.target.value })); setPage(1) }}
                        placeholder={k === 'amount' ? 'e.g. >500' : 'Search…'}
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
                      value={filters.sub_category}
                      onChange={e => { setFilters(f => ({ ...f, sub_category: e.target.value })); setPage(1) }}>
                      <option value="">All</option>
                      {filterSubcategoryOptions.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </th>
                  <th>
                    <select className="filter-input" style={{ padding: '2px 4px' }}
                      value={filters.spend_type}
                      onChange={e => { setFilters(f => ({ ...f, spend_type: e.target.value })); setPage(1) }}>
                      <option value="">All</option>
                      {filterTypeOptions.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </th>
                  <th></th>
                  <th></th>
                  <th>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.cadence}
                        onChange={e => { setFilters(f => ({ ...f, cadence: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        {filterCadenceOptions.map(s => <option key={s}>{s}</option>)}
                      </select>
                      <select className="filter-input" style={{ padding: '2px 4px' }}
                        value={filters.shared_expense}
                        onChange={e => { setFilters(f => ({ ...f, shared_expense: e.target.value })); setPage(1) }}>
                        <option value="">All</option>
                        <option value="Y">Y</option>
                        <option value="N">N</option>
                      </select>
                    </div>
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
                {pageItems.map(row => {
                  const isDirty = dirty.has(row.id)
                  const cat  = getVal(row, 'category') ?? ''
                  const sub  = getVal(row, 'sub_category') ?? ''
                  const type = getVal(row, 'spend_type') ?? ''
                  const cadence   = getVal(row, 'cadence')
                  const divideBy  = getVal(row, 'divide_by') ?? 1
                  const shared    = getVal(row, 'shared_expense') ?? 'N'
                  const ratio     = getVal(row, 'share_ratio') ?? 1
                  const amount    = getVal(row, 'amount') ?? row.amount
                  const monthly   = amount / divideBy
                  const final_amt = monthly * ratio

                  return (
                    <tr key={row.id} className={`${selectedIds.has(row.id) ? 'selected' : ''}${isDirty ? ' dirty' : ''}`}>
                      <td style={{ textAlign: 'center' }}>
                        <input type="checkbox" checked={selectedIds.has(row.id)}
                          onChange={() => toggleRow(row.id)} style={{ cursor: 'pointer' }} />
                      </td>
                      <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap', fontSize: 12 }}>
                        {fmtDateShort(row.entry_date)}
                      </td>
                      <td>
                        <div style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {row.merchant ?? row.entry_text}
                        </div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <input type="number" className="field-input" style={{ width: 90 }} step="0.01"
                          value={amount}
                          onChange={e => setField(row.id, 'amount', parseFloat(e.target.value) || 0)} />
                      </td>
                      <td>
                        <ComboInput value={cat} options={categoryOptions}
                          onChange={v => { setField(row.id, 'category', v); setField(row.id, 'sub_category', '') }}
                          style={{ width: 140 }} />
                      </td>
                      <td>
                        <ComboInput value={sub} options={subcatsFor(cat)}
                          onChange={v => setField(row.id, 'sub_category', v)}
                          style={{ width: 140 }} />
                      </td>
                      <td>
                        <ComboInput value={type} options={typeOptions}
                          onChange={v => setField(row.id, 'spend_type', v as SpendType)}
                          style={{ width: 100 }} />
                      </td>
                      <td style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'right' }}>{monthly.toFixed(2)}</td>
                      <td style={{ color: 'var(--teal)', fontSize: 12, textAlign: 'right' }}>{final_amt.toFixed(2)}</td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                          <input type="checkbox" checked={shared === 'Y'}
                            onChange={e => {
                              setField(row.id, 'shared_expense', e.target.checked ? 'Y' : 'N')
                              if (e.target.checked) setField(row.id, 'share_ratio', settings.default_share_ratio)
                            }} />
                          {shared === 'Y' && (
                            <input type="number" className="field-input" style={{ width: 52, fontSize: 11 }}
                              min="0.01" max="1" step="0.01"
                              value={ratio}
                              onChange={e => setField(row.id, 'share_ratio', parseFloat(e.target.value) || 1)} />
                          )}
                          <input type="text" className="field-input" style={{ width: 38, fontSize: 11 }}
                            value={cadence ?? 'O'}
                            onChange={e => {
                              setField(row.id, 'cadence', e.target.value as Cadence)
                              if (e.target.value === 'A') setField(row.id, 'divide_by', settings.default_annual_divisor)
                            }} />
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {isDirty && (
                            <button className="btn btn-primary btn-sm" onClick={() => saveRow(row)}
                              disabled={patchMut.isPending}>
                              Update
                            </button>
                          )}
                          <button
                            className="btn btn-ghost btn-icon"
                            style={{ color: 'var(--red)' }}
                            onClick={() => { if (confirm('Delete row?')) deleteMut.mutate(row.id) }}
                          >×</button>
                        </div>
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
                <span className="page-info">Page {page} of {totalPages} · {filtered.length} rows</span>
                <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                  Next <ChevronRight size={12} />
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bulk bar */}
      <div className={`bulk-bar${selectedIds.size > 0 ? ' visible' : ''}`}>
        <span className="bulk-count">{selectedIds.size} rows selected</span>
        <div className="bulk-sep" />
        <ComboInput value={bulkFields.category} options={categoryOptions} placeholder="Category…"
          onChange={v => setBulkFields(f => ({ ...f, category: v, sub_category: '' }))}
          style={{ width: 140 }} />
        <ComboInput value={bulkFields.sub_category} options={subcatsFor(bulkFields.category)} placeholder="Subcategory…"
          onChange={v => setBulkFields(f => ({ ...f, sub_category: v }))}
          style={{ width: 150 }} />
        <ComboInput value={bulkFields.spend_type} options={typeOptions} placeholder="Type…"
          onChange={v => setBulkFields(f => ({ ...f, spend_type: v }))}
          style={{ width: 120 }} />
        <button className="btn btn-primary btn-sm"
          disabled={!bulkFields.category || !bulkFields.sub_category || !bulkFields.spend_type}
          onClick={applyBulk}>
          Apply to Selected
        </button>
        <div className="bulk-sep" />
        <button className="btn btn-danger btn-sm" onClick={bulkDelete}>Delete Selected</button>
        <button className="bulk-dismiss" onClick={() => setSelected(new Set())} title="Dismiss">×</button>
      </div>

      {/* Add Entry Modal */}
      {addModal && (
        <AddEntryModal
          settings={settings}
          categoryOptions={categoryOptions}
          subcatsFor={subcatsFor}
          typeOptions={typeOptions}
          onClose={() => setAddModal(false)}
          onSave={(payload) => {
            historyApi.create(payload)
              .then(r => {
                qc.invalidateQueries({ queryKey: ['history', activePeriod] })
                qc.invalidateQueries({ queryKey: ['history-periods'] })
                qc.invalidateQueries({ queryKey: ['history-summary', activePeriod] })
                toast(`Added ${r.count} row(s)`, 'success')
                setAddModal(false)
              })
              .catch((e: Error) => toast(e.message, 'error'))
          }}
        />
      )}
    </Layout>
  )
}

function SettingsPanel({ settings, onSave, onClose }: {
  settings: AppSettings
  onSave: (s: AppSettings) => void
  onClose: () => void
}) {
  const [local, setLocal] = useState(settings)
  return (
    <div style={{
      position: 'absolute', right: 0, top: 'calc(100% + 6px)', zIndex: 200,
      background: 'var(--surface)', border: '1px solid var(--border2)',
      borderRadius: 'var(--radius)', padding: '14px 16px', minWidth: 240,
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    }} onClick={e => e.stopPropagation()}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, fontWeight: 600, fontSize: 13 }}>
        Settings
        <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={14} /></button>
      </div>
      {([['Default Share Ratio', 'default_share_ratio', 0.01, 1, 0.01],
         ['Annual Divisor',      'default_annual_divisor', 1, 12, 1]] as const).map(([label, k, min, max, step]) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
          <input type="number" className="field-input" style={{ width: '100%' }}
            min={min} max={max} step={step}
            value={local[k]}
            onChange={e => setLocal(prev => ({ ...prev, [k]: parseFloat(e.target.value) }))} />
        </div>
      ))}
      <button className="btn btn-primary btn-sm" style={{ width: '100%' }} onClick={() => { onSave(local); onClose() }}>
        Save
      </button>
    </div>
  )
}

function AddEntryModal({ settings, categoryOptions, subcatsFor, typeOptions, onClose, onSave }: {
  settings: AppSettings
  categoryOptions: string[]
  subcatsFor: (cat: string) => string[]
  typeOptions: string[]
  onClose: () => void
  onSave: (payload: CreateHistoryPayload) => void
}) {
  const today = new Date().toISOString().slice(0, 10)
  interface FormRow {
    id:             number
    entry_date:     string
    entry_text:     string
    merchant:       string
    amount:         number
    category:       string
    sub_category:   string
    spend_type:     string
    cadence:        Cadence
    divide_by:      number
    shared_expense: 'Y' | 'N'
    share_ratio:    number
  }
  const blank = (id: number): FormRow => ({
    id, entry_date: today, entry_text: '', merchant: '', amount: 0,
    category: '', sub_category: '', spend_type: 'Expense',
    cadence: 'O', divide_by: 1, shared_expense: 'N', share_ratio: settings.default_share_ratio,
  })
  const [rows, setRows] = useState<FormRow[]>([blank(1)])
  const [counter, setCounter] = useState(2)

  function upd(id: number, k: keyof FormRow, v: unknown) {
    setRows(prev => prev.map(r => r.id === id ? { ...r, [k]: v } : r))
  }
  function addRow() { setRows(p => [...p, blank(counter)]); setCounter(c => c + 1) }
  function dupRow(r: FormRow) { setRows(p => [...p, { ...r, id: counter }]); setCounter(c => c + 1) }
  function delRow(id: number) { if (rows.length > 1) setRows(p => p.filter(r => r.id !== id)) }

  function submit() {
    if (rows.some(r => !r.entry_date || !r.entry_text.trim() || !r.amount)) return
    // Submit each row individually
    rows.forEach(r => {
      onSave({
        entry_date: r.entry_date, entry_text: r.entry_text, merchant: r.merchant,
        amount: r.amount, category: r.category, sub_category: r.sub_category,
        spend_type: r.spend_type, cadence: r.cadence, divide_by: r.divide_by,
        shared_expense: r.shared_expense, share_ratio: r.share_ratio,
      })
    })
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ width: 'min(1100px, 97vw)' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          Add Entry
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['Date*','Description*','Merchant','Amount*','Category','Subcategory','Type','Cadence','÷By','Shared','Ratio',''].map(h => (
                  <th key={h} style={{ padding: '4px 4px', fontWeight: 600, color: 'var(--muted)',
                    borderBottom: '1px solid var(--border2)', whiteSpace: 'nowrap', textAlign: 'left' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id}>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="date" className="field-input" style={{ width: 120 }}
                      value={r.entry_date} onChange={e => upd(r.id, 'entry_date', e.target.value)} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="text" className="field-input" style={{ width: 160 }}
                      value={r.entry_text} onChange={e => upd(r.id, 'entry_text', e.target.value)} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="text" className="field-input" style={{ width: 100 }}
                      value={r.merchant} onChange={e => upd(r.id, 'merchant', e.target.value)} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="number" className="field-input" style={{ width: 90 }} step="0.01"
                      value={r.amount || ''} onChange={e => upd(r.id, 'amount', parseFloat(e.target.value) || 0)} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <ComboInput value={r.category} options={categoryOptions}
                      onChange={v => { upd(r.id, 'category', v); upd(r.id, 'sub_category', '') }}
                      style={{ width: 130 }} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <ComboInput value={r.sub_category} options={subcatsFor(r.category)}
                      onChange={v => upd(r.id, 'sub_category', v)}
                      style={{ width: 130 }} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <ComboInput value={r.spend_type} options={typeOptions}
                      onChange={v => upd(r.id, 'spend_type', v)}
                      style={{ width: 90 }} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <select className="field-input" style={{ width: 48 }}
                      value={r.cadence}
                      onChange={e => {
                        upd(r.id, 'cadence', e.target.value as Cadence)
                        if (e.target.value === 'A') upd(r.id, 'divide_by', settings.default_annual_divisor)
                      }}>
                      {['O','M','Q','A'].map(c => <option key={c}>{c}</option>)}
                    </select>
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="number" className="field-input" style={{ width: 44 }} min="1"
                      value={r.divide_by} onChange={e => upd(r.id, 'divide_by', parseInt(e.target.value) || 1)} />
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <select className="field-input" style={{ width: 46 }}
                      value={r.shared_expense}
                      onChange={e => {
                        upd(r.id, 'shared_expense', e.target.value as 'Y'|'N')
                        if (e.target.value === 'Y') upd(r.id, 'share_ratio', settings.default_share_ratio)
                      }}>
                      <option value="N">N</option>
                      <option value="Y">Y</option>
                    </select>
                  </td>
                  <td style={{ padding: '2px 3px' }}>
                    <input type="number" className="field-input" style={{ width: 54 }}
                      min="0.01" max="1" step="0.01"
                      disabled={r.shared_expense === 'N'}
                      value={r.share_ratio}
                      onChange={e => upd(r.id, 'share_ratio', parseFloat(e.target.value) || 1)} />
                  </td>
                  <td style={{ padding: '2px 3px', whiteSpace: 'nowrap' }}>
                    <button className="btn btn-ghost btn-icon" style={{ fontSize: 12 }}
                      onClick={() => dupRow(r)} title="Duplicate">⊕</button>
                    <button className="btn btn-ghost btn-icon"
                      style={{ color: 'var(--red)', opacity: rows.length === 1 ? 0.3 : 1 }}
                      disabled={rows.length === 1}
                      onClick={() => delRow(r.id)}><X size={12} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={addRow}>+ Add Row</button>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary"
            disabled={rows.some(r => !r.entry_date || !r.entry_text.trim() || !r.amount)}
            onClick={submit}>
            Add {rows.length > 1 ? `${rows.length} Entries` : 'Entry'}
          </button>
        </div>
      </div>
    </div>
  )
}
