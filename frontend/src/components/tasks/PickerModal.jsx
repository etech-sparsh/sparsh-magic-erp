import React, { useEffect, useState, useRef } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Search, Save, Plus, Check } from 'lucide-react';
import { getInitials } from './taskDisplayUtils';

// Shared search + scrollable-list + Cancel/Apply popover, used for the Assignee,
// In Loop and Category pickers (they all share the same header/search/list/footer shape).
//
// `bulkOption` (optional): a checkbox above the list that selects/deselects a whole SET of
// ids at once — e.g. "Include MD" on the In Loop picker. It stages onto `pending` like every
// other click here, so Cancel still discards it and Apply still commits it; a control that
// wrote straight through to the parent would survive a Cancel and surprise the user.
//     bulkOption = { label, ids: [...], hint?, emptyHint? }
//
// `onAddNew` (optional): when provided, the "Add More" flow CREATES + APPENDS an item
// (via the parent) and keeps the modal open WITHOUT changing the current selection —
// so e.g. adding a new category never clears the already-selected one. Without it,
// Add More falls back to the legacy behaviour (stage for multi / apply+close for single).
const PickerModal = ({
  isOpen, onClose, title, searchPlaceholder = 'Search...', items, multi = true,
  selected, onApply, onAddNew, renderAvatar = false, renderDot = false, allowAddMore = false, addMoreLabel = 'Add More',
  bulkOption = null,
}) => {
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState(multi ? [] : null);
  const [newItemName, setNewItemName] = useState('');
  const [addingNew, setAddingNew] = useState(false);
  // Names created via Add More this session — merged into the list so they show instantly,
  // even before the parent's refetched `items` prop lands.
  const [localExtra, setLocalExtra] = useState([]);
  const selectedRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    setPending(multi ? [...(selected || [])] : (selected ?? null));
    setSearch('');
    setAddingNew(false);
    setNewItemName('');
    setLocalExtra([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Auto-scroll to the currently selected item when the modal opens.
  useEffect(() => {
    if (!isOpen) return undefined;
    const t = setTimeout(() => selectedRef.current?.scrollIntoView({ block: 'nearest' }), 60);
    return () => clearTimeout(t);
  }, [isOpen]);

  if (!isOpen) return null;

  // Merge parent items with session-added names (deduped, case-insensitive).
  const extraItems = localExtra
    .filter((n) => !items.some((it) => String(it.id).toLowerCase() === n.toLowerCase()))
    .map((n) => ({ id: n, primary: n }));
  const allItems = [...items, ...extraItems];

  const filtered = allItems.filter(it =>
    it.primary?.toLowerCase().includes(search.toLowerCase()) ||
    it.secondary?.toLowerCase().includes(search.toLowerCase())
  );

  const toggle = (id) => {
    if (multi) {
      setPending(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]));
    } else {
      setPending(id);
    }
  };

  // ── bulkOption ───────────────────────────────────────────────
  // Checked only when EVERY id in the set is staged, so ticking the last one by hand lights
  // the box and unticking any one clears it — the checkbox can never contradict the list.
  const bulkIds = bulkOption?.ids || [];
  const bulkChecked = multi && bulkIds.length > 0 && bulkIds.every(id => pending.includes(id));
  const toggleBulk = () => {
    if (!multi || !bulkIds.length) return;
    setPending(p => (bulkChecked
      ? p.filter(id => !bulkIds.includes(id))
      : [...p, ...bulkIds.filter(id => !p.includes(id))]));
  };

  const handleAddNew = () => {
    const name = newItemName.trim();
    if (!name) return;

    // Preferred flow: create + append without disturbing the current selection.
    if (onAddNew) {
      Promise.resolve(onAddNew(name)).catch(() => {}); // parent handles create + list refresh + errors
      setLocalExtra(prev => (prev.some(x => x.toLowerCase() === name.toLowerCase()) ? prev : [...prev, name]));
      setNewItemName('');
      setAddingNew(false);
      return; // keep modal open, keep `pending` (selection) untouched
    }

    // Legacy fallback (unchanged) for pickers that don't pass onAddNew.
    if (multi) {
      toggle(name);
      setNewItemName('');
      setAddingNew(false);
    } else {
      setNewItemName('');
      setAddingNew(false);
      onApply(name);
      onClose();
    }
  };

  const handleApply = () => {
    onApply(pending);
    onClose();
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm max-h-[80vh] flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between shrink-0">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{title}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="px-5 pt-4 shrink-0">
            <div className="relative">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={searchPlaceholder}
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--bg-card)] border-2 border-[var(--accent-indigo)] rounded-full text-[12px] font-bold outline-none" />
            </div>
          </div>

          {bulkOption && multi && (
            <div className="px-5 pt-3 shrink-0">
              <label className={`flex items-start gap-2.5 px-3 py-2.5 rounded-xl border transition-all ${
                bulkIds.length === 0
                  ? 'border-[var(--border)] opacity-60 cursor-not-allowed'
                  : `cursor-pointer ${bulkChecked
                    ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                    : 'border-[var(--border)] hover:bg-[var(--input-bg)]'}`
              }`}>
                <input type="checkbox" className="mt-0.5 shrink-0" checked={bulkChecked}
                  disabled={bulkIds.length === 0} onChange={toggleBulk} />
                <span className="min-w-0">
                  <span className={`block text-[12px] font-black ${bulkChecked ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>
                    {bulkOption.label}
                    {bulkIds.length > 0 && (
                      <span className="ml-1.5 font-bold text-[var(--text-muted)]">({bulkIds.length})</span>
                    )}
                  </span>
                  {(bulkIds.length === 0 ? bulkOption.emptyHint : bulkOption.hint) && (
                    <span className="block text-[10.5px] font-medium text-[var(--text-muted)] mt-0.5 leading-relaxed">
                      {bulkIds.length === 0 ? bulkOption.emptyHint : bulkOption.hint}
                    </span>
                  )}
                </span>
              </label>
            </div>
          )}

          <div className="flex-1 overflow-y-auto no-scrollbar px-5 py-3 space-y-1">
            {filtered.map(it => {
              const isSelected = multi ? pending.includes(it.id) : pending === it.id;
              return (
                <button type="button" key={it.id} ref={isSelected ? selectedRef : null} onClick={() => toggle(it.id)}
                  className={`w-full flex items-center gap-3 px-2 py-2.5 rounded-xl text-left transition-all ${isSelected ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                  {renderAvatar && (
                    <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-black text-[11px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {getInitials(it.primary)}
                    </div>
                  )}
                  {renderDot && <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: 'var(--accent-indigo)' }} />}
                  <div className="min-w-0 flex-1">
                    <p className={`text-[13px] font-bold truncate ${isSelected ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{it.primary}</p>
                    {it.secondary && <p className="text-[11px] font-medium text-[var(--text-muted)] truncate">{it.secondary}</p>}
                  </div>
                  {isSelected && <Check size={16} className="text-[var(--accent-indigo)] shrink-0" />}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-6">
                {search ? 'No matches' : 'No items yet'}
              </p>
            )}
          </div>

          {allowAddMore && addingNew && (
            <div className="px-5 pb-2 shrink-0">
              <div className="flex items-center gap-2">
                <input autoFocus value={newItemName} onChange={e => setNewItemName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddNew(); } }}
                  placeholder="New name..."
                  className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
                <button type="button" onClick={handleAddNew} className="px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[11px] font-black">Add</button>
              </div>
            </div>
          )}

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3 shrink-0">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <div className="flex items-center gap-2">
              {allowAddMore && !addingNew && (
                <button type="button" onClick={() => setAddingNew(true)} className="flex items-center gap-1.5 px-4 py-2 border border-[var(--accent-indigo)] text-[var(--accent-indigo)] rounded-xl text-[10px] font-black uppercase tracking-widest">
                  <Plus size={13} /> {addMoreLabel}
                </button>
              )}
              <button type="button" onClick={handleApply} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
                <Save size={13} /> Apply Changes
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default PickerModal;
