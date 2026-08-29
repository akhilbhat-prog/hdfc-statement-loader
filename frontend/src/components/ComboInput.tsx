import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  value:       string
  onChange:    (v: string) => void
  options:     string[]
  placeholder?: string
  className?:  string
  style?:      React.CSSProperties
  disabled?:   boolean
}

interface Pos { left: number; top: number; width: number; openUp: boolean; maxHeight: number }

const MARGIN = 8
const MAX_H = 180

export function ComboInput({ value, onChange, options, placeholder, className, style, disabled }: Props) {
  const [open, setOpen]     = useState(false)
  const [query, setQuery]   = useState(value)
  const [active, setActive] = useState(-1)
  const [pos, setPos]       = useState<Pos | null>(null)
  const wrapRef             = useRef<HTMLDivElement>(null)
  const inputRef            = useRef<HTMLInputElement>(null)
  const dropdownRef         = useRef<HTMLDivElement>(null)

  // Keep query in sync when value changes externally
  useEffect(() => { setQuery(value) }, [value])

  const filtered = query
    ? options.filter(o => o.toLowerCase().includes(query.toLowerCase()))
    : options

  function computePos() {
    const el = inputRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const spaceAbove = rect.top - MARGIN
    const spaceBelow = window.innerHeight - rect.bottom - MARGIN
    const width = Math.max(rect.width, 120)
    if (spaceAbove >= MAX_H) {
      setPos({ left: rect.left, top: rect.top - 2, width, openUp: true, maxHeight: MAX_H })
    } else if (spaceBelow >= MAX_H) {
      setPos({ left: rect.left, top: rect.bottom + 2, width, openUp: false, maxHeight: MAX_H })
    } else if (spaceAbove >= spaceBelow) {
      setPos({ left: rect.left, top: rect.top - 2, width, openUp: true, maxHeight: Math.max(60, spaceAbove) })
    } else {
      setPos({ left: rect.left, top: rect.bottom + 2, width, openUp: false, maxHeight: Math.max(60, spaceBelow) })
    }
  }

  function openDropdown() {
    computePos()
    setOpen(true)
  }

  function toggleDropdown() {
    if (open) {
      setOpen(false)
    } else {
      inputRef.current?.focus()
      openDropdown()
    }
  }

  function commit(val: string) {
    onChange(val)
    setQuery(val)
    setOpen(false)
    setActive(-1)
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (!open) { if (e.key === 'ArrowDown') openDropdown(); return }
    if (e.key === 'ArrowDown')  { setActive(i => Math.min(i + 1, filtered.length - 1)); e.preventDefault() }
    if (e.key === 'ArrowUp')    { setActive(i => Math.max(i - 1, 0)); e.preventDefault() }
    if (e.key === 'Enter')      { if (active >= 0) commit(filtered[active]); else commit(query); e.preventDefault() }
    if (e.key === 'Escape')     { setOpen(false) }
    if (e.key === 'Tab')        { setOpen(false) }
  }

  // Close on outside click (the dropdown is portaled to <body>, so it's checked separately from wrapRef)
  useEffect(() => {
    function onDown(e: MouseEvent) {
      const target = e.target as Node
      const insideWrap = wrapRef.current?.contains(target)
      const insideDropdown = dropdownRef.current?.contains(target)
      if (!insideWrap && !insideDropdown) {
        setOpen(false)
        // Commit whatever is typed
        if (query !== value) onChange(query)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [query, value, onChange])

  return (
    <div ref={wrapRef} className="combo-wrap" style={{ display: 'inline-block', position: 'relative', ...style }}>
      <input
        ref={inputRef}
        className={`field-input ${className ?? ''}`}
        style={{ width: '100%', paddingRight: 20 }}
        value={query}
        placeholder={placeholder}
        disabled={disabled}
        onChange={e => { setQuery(e.target.value); openDropdown(); setActive(-1) }}
        onFocus={openDropdown}
        onKeyDown={handleKey}
        onBlur={() => {
          // small delay so click on option fires first
          setTimeout(() => {
            if (query !== value) onChange(query)
          }, 120)
        }}
      />
      {!disabled && (
        <span
          className="combo-arrow"
          onMouseDown={e => { e.preventDefault(); toggleDropdown() }}
        >
          ▾
        </span>
      )}
      {open && !disabled && pos && createPortal(
        <div
          ref={dropdownRef}
          className="combo-dropdown"
          style={{
            position: 'fixed', left: pos.left, top: pos.top, width: pos.width, maxHeight: pos.maxHeight,
            transform: pos.openUp ? 'translateY(-100%)' : undefined,
          }}
        >
          {filtered.length === 0 ? (
            <div className="combo-no-match">No matches — type freely</div>
          ) : (
            filtered.slice(0, 50).map((opt, i) => (
              <div
                key={opt}
                className={`combo-option${active === i ? ' active' : ''}`}
                onMouseDown={() => commit(opt)}
                onMouseEnter={() => setActive(i)}
              >
                {opt}
              </div>
            ))
          )}
        </div>,
        document.body
      )}
    </div>
  )
}
