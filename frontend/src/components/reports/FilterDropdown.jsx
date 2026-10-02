import React, { useState, useRef, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { ChevronDown, Check, Search } from 'lucide-react';

/**
 * Modern filter dropdown used by the Reports section only.
 * Pure UI wrapper — it does not change any filter/data logic; it just calls
 * onChange(value) with the same values the previous <select> elements produced.
 *
 * Props:
 *   value, onChange(value)
 *   options: [{ value, label, sublabel? }]
 *   icon        — leading icon on the button (lucide component)
 *   optionIcon  — icon shown before each option (lucide component)
 *   searchable  — show a search box inside the panel
 *   align       — 'left' | 'right' (panel alignment under the button)
 */
const FilterDropdown = ({
  value,
  onChange,
  options,
  icon: Icon,
  optionIcon: OptionIcon,
  searchable = false,
  align = 'left',
  placeholder = 'Select',
  searchPlaceholder = 'Search...',
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);
  const searchRef = useRef(null);

  // Outside-click + Escape close
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Autofocus the search box when opened
  useEffect(() => {
    if (open && searchable) {
      const t = setTimeout(() => searchRef.current?.focus(), 40);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [open, searchable]);

  const selected = options.find((o) => o.value === value);
  const buttonLabel = selected ? selected.label : placeholder;

  const q = query.trim().toLowerCase();
  const filtered = searchable && q
    ? options.filter(
        (o) => o.label.toLowerCase().includes(q) || (o.sublabel || '').toLowerCase().includes(q)
      )
    : options;

  const choose = (v) => {
    onChange(v);
    setOpen(false);
    setQuery('');
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2.5 px-4 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-sm text-[13px] font-bold text-[var(--text-main)] hover:border-[var(--accent-indigo)] transition-all outline-none focus-visible:border-[var(--accent-indigo)]"
      >
        {Icon && <Icon size={16} className="text-[var(--text-muted)] shrink-0" />}
        <span className="truncate max-w-[150px] text-left flex-1">{buttonLabel}</span>
        <ChevronDown
          size={15}
          className={`text-[var(--text-muted)] shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            role="listbox"
            className={`absolute top-full mt-2 w-[280px] max-w-[80vw] bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.15)] z-[60] overflow-hidden ${
              align === 'right' ? 'right-0' : 'left-0'
            }`}
          >
            {searchable && (
              <div className="p-2.5 border-b border-[var(--border)]">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                  <input
                    ref={searchRef}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={searchPlaceholder}
                    className="w-full pl-9 pr-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-medium text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
                  />
                </div>
              </div>
            )}

            <div className="max-h-[300px] overflow-y-auto py-1.5 [scrollbar-width:thin] [scrollbar-color:var(--border)_transparent]">
              {filtered.length === 0 ? (
                <p className="px-4 py-6 text-center text-[12px] font-bold text-[var(--text-muted)]">No results</p>
              ) : (
                filtered.map((o) => {
                  const active = o.value === value;
                  return (
                    <button
                      key={o.value || '__all'}
                      type="button"
                      role="option"
                      aria-selected={active}
                      onClick={() => choose(o.value)}
                      className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-left transition-colors ${
                        active ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'
                      }`}
                    >
                      {OptionIcon && (
                        <OptionIcon
                          size={15}
                          className={`shrink-0 ${active ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}
                        />
                      )}
                      <span
                        className={`flex-1 truncate text-[13px] ${
                          active ? 'font-black text-[var(--accent-indigo)]' : 'font-semibold text-[var(--text-main)]'
                        }`}
                      >
                        {o.label}
                        {o.sublabel && <span className="font-medium text-[var(--text-muted)]"> - {o.sublabel}</span>}
                      </span>
                      {active && <Check size={15} className="text-[var(--accent-indigo)] shrink-0" />}
                    </button>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default FilterDropdown;
