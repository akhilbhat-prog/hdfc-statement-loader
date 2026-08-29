import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, CreditCard, X } from 'lucide-react'
import { Layout } from '../components/Layout'
import { useToast } from '../hooks/useToast'
import { sharedApi, type CreateSharedPayload, type PaymentPayload } from '../api/shared'
import type { SharedRow } from '../types'

function fmtAmt(n: number)  { return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

type SortKey = keyof Pick<SharedRow, 'entry_date' | 'amount' | 'balance' | 'merchant' | 'category'>

export function SharedPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const [fy, setFy] = useState<number | null>(null)
  const [sortCol, setSortCol]   = useState<SortKey>('entry_date')
  const [sortDir, setSortDir]   = useState<'asc' | 'desc'>('desc')
  const [filter, setFilter]     = useState('')
  const [pending, setPending]   = useState<Record<number, Partial<SharedRow>>>({})
  const [addModal, setAddModal] = useState(false)
  const [payModal, setPayModal] = useState(false)

  const { data: fyList = [] } = useQuery({
    queryKey: ['shared-fy'],
    queryFn: sharedApi.fyList,
    select: (list) => {
      if (!fy && list.length) setFy(list[0])
      return list
    },
  })

  const activeFy = fy ?? fyList[0] ?? new Date().getFullYear()

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['shared', activeFy],
    queryFn: () => sharedApi.list(activeFy),
    enabled: !!activeFy,
  })

  const { data: summary } = useQuery({
    queryKey: ['shared-summary', activeFy],
    queryFn: () => sharedApi.summary(activeFy),
    enabled: !!activeFy,
  })

  const patchMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Parameters<typeof sharedApi.patch>[1] }) =>
      sharedApi.patch(id, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] }) },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: sharedApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['shared'] }); toast('Deleted', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function sort(col: SortKey) {
    setSortDir(sortCol === col && sortDir === 'asc' ? 'desc' : 'asc')
    setSortCol(col)
  }

  function sortArrow(col: SortKey) {
    if (sortCol !== col) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  const displayed = useMemo(() => {
    let r = [...rows]
    if (filter) {
      const q = filter.toLowerCase()
      r = r.filter(row =>
        (row.merchant ?? '').toLowerCase().includes(q) ||
        (row.entry_text ?? '').toLowerCase().includes(q) ||
        (row.category ?? '').toLowerCase().includes(q)
      )
    }
    r.sort((a, b) => {
      const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
    return r
  }, [rows, filter, sortCol, sortDir])

  function setPend(id: number, field: keyof SharedRow, value: unknown) {
    setPending(p => ({ ...p, [id]: { ...p[id], [field]: value } }))
  }

  function saveRow(row: SharedRow) {
    const edits = pending[row.id] ?? {}
    if (!Object.keys(edits).length) return
    patchMut.mutate({ id: row.id, payload: edits })
    setPending(p => { const n = { ...p }; delete n[row.id]; return n })
  }

  function isDirty(id: number) { return !!Object.keys(pending[id] ?? {}).length }

  function get<K extends keyof SharedRow>(row: SharedRow, k: K): SharedRow[K] {
    return (pending[row.id]?.[k] as SharedRow[K]) ?? row[k]
  }

  const fyLabel = (y: number) => `${y}–${String(y + 1).slice(2)}`

  const sidebar = (
    <>
      <div className="sidebar-header">Financial Year</div>
      {fyList.map(y => (
        <div
          key={y}
          className={`fy-item${activeFy === y ? ' active' : ''}`}
          onClick={() => setFy(y)}
        >
          FY {fyLabel(y)}
        </div>
      ))}
    </>
  )

  return (
    <Layout
      sidebar={sidebar}
      headerExtra={
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => setPayModal(true)}>
            <CreditCard size={13} /> Payment
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => setAddModal(true)}>
            <Plus size={13} /> Add Entry
          </button>
        </div>
      }
    >
      {/* Summary cards */}
      {summary && (
        <div className="summary-cards">
          {[
            { label: 'Net Balance', value: summary.net_balance, isBalance: true },
            { label: 'Akhil Paid', value: summary.total_akhil_paid },
            { label: 'Aditi Paid', value: summary.total_aditi_paid },
          ].map(s => (
            <div key={s.label} className="summary-card">
              <div className="sc-label">{s.label}</div>
              <div className="sc-value" style={{
                color: s.isBalance
                  ? (s.value >= 0 ? 'var(--green)' : 'var(--red)')
                  : 'var(--text)',
                fontSize: 18,
              }}>
                {fmtAmt(s.isBalance ? Math.abs(s.value) : s.value)}
              </div>
              {s.isBalance && (
                <div className="sc-sub">
                  {s.value >= 0 ? 'Aditi owes Akhil' : 'Akhil owes Aditi'}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="card">
        <div className="card-header" style={{ gap: 8 }}>
          <span>Shared Transactions — FY {fyLabel(activeFy)}</span>
          <input
            className="field-input"
            placeholder="Filter…"
            style={{ marginLeft: 'auto', width: 200, fontSize: 12 }}
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>
        {isLoading ? (
          <div className="empty-state">Loading…</div>
        ) : displayed.length === 0 ? (
          <div className="empty-state">No shared transactions</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th className="sortable sort-active" onClick={() => sort('entry_date')}>Date{sortArrow('entry_date')}</th>
                  <th className="sortable" onClick={() => sort('merchant')}>Merchant{sortArrow('merchant')}</th>
                  <th className="sortable" onClick={() => sort('category')}>Category{sortArrow('category')}</th>
                  <th className="sortable" style={{ textAlign: 'right' }} onClick={() => sort('amount')}>Amount{sortArrow('amount')}</th>
                  <th>Paid By</th>
                  <th style={{ textAlign: 'right' }}>Ratio</th>
                  <th style={{ textAlign: 'right' }}>Akhil</th>
                  <th style={{ textAlign: 'right' }}>Aditi</th>
                  <th className="sortable" style={{ textAlign: 'right' }} onClick={() => sort('balance')}>Balance{sortArrow('balance')}</th>
                  <th>Settled</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {displayed.map(row => {
                  const dirty = isDirty(row.id)
                  const ratio = (get(row, 'share_ratio') ?? row.share_ratio)
                  const monthly = row.monthly_amount ?? row.amount
                  const akhil = row.is_payment ? 0 : Math.round(monthly * ratio * 100) / 100
                  const aditi = row.is_payment ? 0 : Math.round(monthly * (1 - ratio) * 100) / 100
                  const paidBy = get(row, 'paid_by') ?? row.paid_by
                  const balance = row.is_payment ? row.balance
                    : (paidBy === 'Akhil' ? aditi : akhil)
                  const settled = get(row, 'settled') ?? row.settled
                  const ignored = get(row, 'is_ignored') ?? row.is_ignored

                  return (
                    <tr
                      key={row.id}
                      className={dirty ? 'dirty' : ''}
                      style={{
                        opacity: ignored ? 0.3 : settled ? 0.6 : 1,
                        background: row.is_payment ? 'var(--teal-dim)' : undefined,
                      }}
                    >
                      <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>{fmtDate(row.entry_date)}</td>
                      <td>
                        <div>{row.merchant ?? row.entry_text}</div>
                        {row.category && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{row.category}</div>}
                      </td>
                      <td style={{ color: 'var(--muted)' }}>{row.category ?? '—'}</td>
                      <td className="amt">{fmtAmt(row.amount)}</td>
                      <td>
                        {row.is_payment ? (
                          <span style={{ color: 'var(--teal)', fontSize: 12 }}>Payment</span>
                        ) : (
                          <select
                            className="field-input"
                            style={{ padding: '3px 6px', fontSize: 12 }}
                            value={paidBy as string}
                            onChange={e => { setPend(row.id, 'paid_by', e.target.value) }}
                          >
                            <option>Akhil</option>
                            <option>Aditi</option>
                          </select>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {row.is_payment ? '—' : (
                          <input
                            type="number" className="field-input"
                            style={{ width: 64, padding: '3px 6px', fontSize: 12 }}
                            min="0.01" max="1" step="0.01"
                            value={ratio}
                            onChange={e => setPend(row.id, 'share_ratio', parseFloat(e.target.value) || 1)}
                          />
                        )}
                      </td>
                      <td className="amt">{row.is_payment ? fmtAmt(row.amount) : fmtAmt(akhil)}</td>
                      <td className="amt">{row.is_payment ? '—' : fmtAmt(aditi)}</td>
                      <td className="amt" style={{ color: balance > 0 ? 'var(--red)' : 'var(--green)', fontWeight: 600 }}>
                        {fmtAmt(balance)}
                      </td>
                      <td>
                        <input
                          type="checkbox" checked={!!settled}
                          onChange={() => patchMut.mutate({ id: row.id, payload: { settled: !settled } })}
                          style={{ cursor: 'pointer' }}
                        />
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {dirty && (
                            <button className="btn btn-primary btn-sm" onClick={() => saveRow(row)}>Update</button>
                          )}
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ color: ignored ? 'var(--muted)' : 'var(--amber)', fontSize: 11 }}
                            onClick={() => patchMut.mutate({ id: row.id, payload: { is_ignored: !ignored } })}
                            title={ignored ? 'Include in balance' : 'Ignore from balance'}
                          >
                            {ignored ? 'Include' : 'Ignore'}
                          </button>
                          {!row.history_id && (
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ color: 'var(--red)' }}
                              onClick={() => { if (confirm('Delete?')) deleteMut.mutate(row.id) }}
                            >×</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Entry Modal */}
      {addModal && (
        <AddEntryModal
          onClose={() => setAddModal(false)}
          onSave={(rows) => {
            sharedApi.create(rows)
              .then(r => { toast(`Added ${r.count} entries`, 'success'); qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] }); setAddModal(false) })
              .catch((e: Error) => toast(e.message, 'error'))
          }}
        />
      )}

      {/* Payment Modal */}
      {payModal && (
        <PaymentModal
          onClose={() => setPayModal(false)}
          onSave={(payload) => {
            sharedApi.payment(payload)
              .then(() => { toast('Payment recorded', 'success'); qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] }); setPayModal(false) })
              .catch((e: Error) => toast(e.message, 'error'))
          }}
        />
      )}
    </Layout>
  )
}

function AddEntryModal({ onClose, onSave }: { onClose: () => void; onSave: (rows: CreateSharedPayload[]) => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const blank = (): CreateSharedPayload => ({
    entry_date: today, merchant: '', category: '', monthly_amount: 0, share_ratio: 0.7, paid_by: 'Akhil', owed_by: 'Aditi',
  })
  const [rows, setRows] = useState<CreateSharedPayload[]>([blank()])

  function update(i: number, k: keyof CreateSharedPayload, v: unknown) {
    setRows(prev => prev.map((r, idx) => idx === i ? { ...r, [k]: v } : r))
  }

  function submit() {
    if (rows.some(r => !r.entry_date || !r.monthly_amount || r.monthly_amount <= 0)) {
      return
    }
    onSave(rows)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ width: 'min(700px, 97vw)' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          Add Shared Entry
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['Date', 'Merchant', 'Category', 'Amount*', 'Ratio', 'Paid By', ''].map(h => (
                  <th key={h} style={{ padding: '4px 6px', fontWeight: 600, color: 'var(--muted)',
                    textAlign: 'left', borderBottom: '1px solid var(--border2)', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="date" className="field-input" style={{ width: 120 }}
                      value={row.entry_date} onChange={e => update(i, 'entry_date', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="text" className="field-input" style={{ width: 110 }}
                      value={row.merchant ?? ''} onChange={e => update(i, 'merchant', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="text" className="field-input" style={{ width: 100 }}
                      value={row.category ?? ''} onChange={e => update(i, 'category', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="number" className="field-input" style={{ width: 90 }} step="0.01"
                      value={row.monthly_amount || ''}
                      onChange={e => update(i, 'monthly_amount', parseFloat(e.target.value) || 0)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="number" className="field-input" style={{ width: 60 }} min="0.01" max="1" step="0.01"
                      value={row.share_ratio} onChange={e => update(i, 'share_ratio', parseFloat(e.target.value) || 1)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <select className="field-input" style={{ width: 80 }}
                      value={row.paid_by} onChange={e => update(i, 'paid_by', e.target.value)}>
                      <option>Akhil</option>
                      <option>Aditi</option>
                    </select>
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <button
                      className="btn btn-ghost btn-icon"
                      style={{ color: 'var(--red)', opacity: rows.length === 1 ? 0.3 : 1 }}
                      disabled={rows.length === 1}
                      onClick={() => setRows(prev => prev.filter((_, idx) => idx !== i))}
                    ><X size={13} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }}
            onClick={() => setRows(prev => [...prev, { ...prev[prev.length - 1] }])}>
            + Add Row
          </button>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit}>Add Entries</button>
        </div>
      </div>
    </div>
  )
}

function PaymentModal({ onClose, onSave }: { onClose: () => void; onSave: (p: PaymentPayload) => void }) {
  const [form, setForm] = useState<PaymentPayload>({
    entry_date: new Date().toISOString().slice(0, 10),
    paid_by: 'Aditi', amount: 0,
  })
  function f(k: keyof PaymentPayload, v: unknown) { setForm(p => ({ ...p, [k]: v })) }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ width: 360 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">Record Payment<button className="btn btn-ghost btn-icon" onClick={onClose}><X size={16} /></button></div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {([['Date*', 'entry_date', 'date'], ['Amount*', 'amount', 'number'], ['Note', 'note', 'text']] as const).map(([label, key, type]) => (
            <div key={key}>
              <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
              <input type={type} className="field-input" style={{ width: '100%' }}
                value={(form[key] as string | number | undefined) ?? ''}
                onChange={e => f(key, type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value)} />
            </div>
          ))}
          <div>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Paid By</label>
            <select className="field-input" style={{ width: '100%' }} value={form.paid_by}
              onChange={e => f('paid_by', e.target.value)}>
              <option>Akhil</option>
              <option>Aditi</option>
            </select>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary"
            disabled={!form.amount || form.amount <= 0}
            onClick={() => onSave(form)}>Record</button>
        </div>
      </div>
    </div>
  )
}
