import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Play, X } from 'lucide-react'
import { Layout } from '../components/Layout'
import { useToast } from '../hooks/useToast'
import { recurringApi, type RecurringPayload } from '../api/recurring'
import type { RecurringDef, Cadence, SpendType } from '../types'

const CADENCE_OPTS = ['O', 'M', 'Q', 'A']
const SPEND_OPTS: SpendType[] = ['Expense', 'Investment', 'Saving']

function fmtAmount(n: number) {
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2 })
}

const BLANK: RecurringPayload = {
  entry_text: '', merchant: '', amount: 0, category: '', sub_category: '',
  spend_type: 'Expense', cadence: 'M', divide_by: 1,
  shared_expense: 'N', share_ratio: 1.0, active: true,
}

export function RecurringPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const { data: defs = [], isLoading } = useQuery({
    queryKey: ['recurring'],
    queryFn: recurringApi.list,
  })

  const [modal, setModal] = useState<{ open: boolean; editing: RecurringDef | null }>({
    open: false, editing: null,
  })
  const [form, setForm] = useState<RecurringPayload>(BLANK)

  const createMut = useMutation({
    mutationFn: recurringApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); closeModal(); toast('Definition created', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: RecurringPayload }) =>
      recurringApi.update(id, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); closeModal(); toast('Updated', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: recurringApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); toast('Deleted', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const generateMut = useMutation({
    mutationFn: () => recurringApi.generate(),
    onSuccess: (r) => toast(`Generated ${r.count} entries`, 'success'),
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function openAdd()              { setForm(BLANK);   setModal({ open: true, editing: null }) }
  function openEdit(d: RecurringDef) {
    setForm({
      entry_text: d.entry_text, merchant: d.merchant ?? '', amount: d.amount,
      category: d.category ?? '', sub_category: d.sub_category ?? '',
      spend_type: (d.spend_type ?? 'Expense') as SpendType,
      cadence: d.cadence, divide_by: d.divide_by,
      shared_expense: d.shared_expense, share_ratio: d.share_ratio, active: d.active,
    })
    setModal({ open: true, editing: d })
  }
  function closeModal() { setModal({ open: false, editing: null }) }

  function f(k: keyof RecurringPayload, v: unknown) { setForm(p => ({ ...p, [k]: v })) }

  function save() {
    if (!form.entry_text.trim()) { toast('Description is required', 'error'); return }
    if (!form.amount || form.amount <= 0) { toast('Amount must be > 0', 'error'); return }
    if (modal.editing) {
      updateMut.mutate({ id: modal.editing.id, payload: form })
    } else {
      createMut.mutate(form)
    }
  }

  async function toggleActive(d: RecurringDef) {
    await recurringApi.update(d.id, {
      entry_text: d.entry_text, merchant: d.merchant ?? '', amount: d.amount,
      category: d.category ?? '', sub_category: d.sub_category ?? '',
      spend_type: (d.spend_type ?? 'Expense') as SpendType,
      cadence: d.cadence, divide_by: d.divide_by,
      shared_expense: d.shared_expense, share_ratio: d.share_ratio, active: !d.active,
    })
    qc.invalidateQueries({ queryKey: ['recurring'] })
  }

  const active = defs.filter(d => d.active).length
  const monthly = defs.filter(d => d.active).reduce((s, d) => s + d.amount / d.divide_by, 0)
  const lastGen = defs.reduce<string | null>((latest, d) => {
    if (!d.last_generated) return latest
    return !latest || d.last_generated > latest ? d.last_generated : latest
  }, null)

  const monthlyPreview = form.amount ? form.amount / (form.divide_by || 1) : 0
  const finalPreview   = form.shared_expense === 'Y'
    ? monthlyPreview * (form.share_ratio ?? 1)
    : monthlyPreview

  const headerExtra = (
    <button
      className="btn btn-primary btn-sm"
      onClick={() => generateMut.mutate()}
      disabled={generateMut.isPending}
    >
      <Play size={13} /> {generateMut.isPending ? 'Generating…' : 'Generate Now'}
    </button>
  )

  return (
    <Layout headerExtra={headerExtra}>
      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Definitions', value: defs.length },
          { label: 'Active',            value: active },
          { label: 'Est. Monthly',      value: fmtAmount(monthly) },
          { label: 'Last Generated',    value: lastGen ?? '—' },
        ].map(s => (
          <div key={s.label} className="card" style={{ flex: 1, padding: '12px 14px' }}>
            <div className="sc-label">{s.label}</div>
            <div className="sc-value" style={{ fontSize: 18 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Table card */}
      <div className="card">
        <div className="card-header">
          Recurring Definitions
          <button className="btn btn-primary btn-sm" onClick={openAdd}>
            <Plus size={13} /> Add
          </button>
        </div>
        {isLoading ? (
          <div className="empty-state">Loading…</div>
        ) : defs.length === 0 ? (
          <div className="empty-state">No recurring definitions yet</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Category</th>
                  <th>Amount</th>
                  <th>Monthly</th>
                  <th>Cadence</th>
                  <th>Shared</th>
                  <th>Active</th>
                  <th>Last Gen</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {defs.map(d => (
                  <tr key={d.id} style={{ opacity: d.active ? 1 : 0.45 }}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{d.entry_text}</div>
                      {d.merchant && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.merchant}</div>}
                    </td>
                    <td>
                      <div>{d.category}</div>
                      {d.sub_category && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.sub_category}</div>}
                    </td>
                    <td>{fmtAmount(d.amount)}</td>
                    <td>{fmtAmount(d.amount / d.divide_by)}</td>
                    <td>
                      <span className="pill" style={{
                        background: 'var(--surface2)', color: 'var(--muted)',
                      }}>{d.cadence}</span>
                    </td>
                    <td>{d.shared_expense === 'Y' ? `${Math.round(d.share_ratio * 100)}%` : '—'}</td>
                    <td>
                      <input
                        type="checkbox" className="active-toggle" checked={d.active}
                        onChange={() => toggleActive(d)}
                      />
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                      {d.last_generated ?? '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(d)}>Edit</button>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ color: 'var(--red)' }}
                          onClick={() => {
                            if (confirm('Delete this definition?')) deleteMut.mutate(d.id)
                          }}
                        >Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal */}
      {modal.open && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-box" style={{ width: 'min(560px, 95vw)' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              {modal.editing ? 'Edit Definition' : 'Add Definition'}
              <button className="btn btn-ghost btn-icon" onClick={closeModal}><X size={16} /></button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 14px' }}>
                {([
                  ['Description*', 'entry_text', 'text'],
                  ['Merchant',     'merchant',   'text'],
                ] as const).map(([label, key, type]) => (
                  <div key={key} style={{ gridColumn: key === 'entry_text' ? '1 / -1' : undefined }}>
                    <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
                    <input
                      type={type} className="field-input" style={{ width: '100%' }}
                      value={form[key] as string}
                      onChange={e => f(key, e.target.value)}
                    />
                  </div>
                ))}

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Amount*</label>
                  <input type="number" className="field-input" style={{ width: '100%' }} step="0.01"
                    value={form.amount || ''}
                    onChange={e => f('amount', parseFloat(e.target.value) || 0)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Cadence</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.cadence}
                    onChange={e => f('cadence', e.target.value as Cadence)}>
                    {CADENCE_OPTS.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Category</label>
                  <input type="text" className="field-input" style={{ width: '100%' }}
                    value={form.category} onChange={e => f('category', e.target.value)} />
                </div>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Subcategory</label>
                  <input type="text" className="field-input" style={{ width: '100%' }}
                    value={form.sub_category} onChange={e => f('sub_category', e.target.value)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Spend Type</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.spend_type}
                    onChange={e => f('spend_type', e.target.value as SpendType)}>
                    {SPEND_OPTS.map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Divide By</label>
                  <input type="number" className="field-input" style={{ width: '100%' }} min="1"
                    value={form.divide_by}
                    onChange={e => f('divide_by', parseInt(e.target.value) || 1)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Shared</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.shared_expense}
                    onChange={e => f('shared_expense', e.target.value as 'Y' | 'N')}>
                    <option value="N">No</option>
                    <option value="Y">Yes</option>
                  </select>
                </div>

                {form.shared_expense === 'Y' && (
                  <div>
                    <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Share Ratio</label>
                    <input type="number" className="field-input" style={{ width: '100%' }} min="0.01" max="1" step="0.01"
                      value={form.share_ratio}
                      onChange={e => f('share_ratio', parseFloat(e.target.value) || 1)} />
                  </div>
                )}

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Active</label>
                  <input type="checkbox" checked={form.active}
                    onChange={e => f('active', e.target.checked)}
                    style={{ width: 16, height: 16, cursor: 'pointer', accentColor: 'var(--teal)' }} />
                </div>
              </div>

              {/* Preview */}
              <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--surface2)',
                borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--muted)', display: 'flex', gap: 20 }}>
                <span>Monthly: <strong style={{ color: 'var(--text)' }}>{fmtAmount(monthlyPreview)}</strong></span>
                <span>Final: <strong style={{ color: 'var(--teal)' }}>{fmtAmount(finalPreview)}</strong></span>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeModal}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={save}
                disabled={createMut.isPending || updateMut.isPending}
              >
                {createMut.isPending || updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  )
}
