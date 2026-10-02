import React, { useEffect, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Globe, Save, Trash2 } from 'lucide-react';

// Paste-a-URL variant of the shared Cancel/Apply-Changes popover shape (see PickerModal),
// used from Extra Options -> Add Link.
const ReferenceLinksModal = ({ isOpen, onClose, links = [], onApply }) => {
  const [pending, setPending] = useState([]);
  const [url, setUrl] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending([...links]);
    setUrl('');
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  const handleAdd = () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    setPending(p => [...p, { id: `link-${Date.now()}`, name: withProtocol, url: withProtocol, type: 'link' }]);
    setUrl('');
  };

  const handleRemove = (id) => setPending(p => p.filter(l => l.id !== id));

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
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">Reference Links</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="px-5 pt-4 shrink-0">
            <div className="flex items-center gap-2">
              <div className="flex-1 flex items-center gap-2 px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-full">
                <Globe size={14} className="text-[var(--text-muted)] shrink-0" />
                <input value={url} onChange={e => setUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAdd(); } }}
                  placeholder="Paste URL here..."
                  className="flex-1 min-w-0 bg-transparent text-[12px] font-bold outline-none" />
              </div>
              <button type="button" onClick={handleAdd}
                className="px-4 py-2.5 bg-[var(--accent-green)] text-white rounded-full text-[10px] font-black uppercase tracking-widest shrink-0">
                Add
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto no-scrollbar px-5 py-3 space-y-1.5">
            {pending.length === 0 && (
              <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-6">No links added yet</p>
            )}
            {pending.map(l => (
              <div key={l.id} className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-[var(--input-bg)]">
                <Globe size={13} className="shrink-0 text-[var(--text-muted)]" />
                <a href={l.url} target="_blank" rel="noreferrer" className="flex-1 min-w-0 text-[12px] font-bold text-[var(--text-main)] truncate hover:text-[var(--accent-indigo)]">
                  {l.name}
                </a>
                <button type="button" onClick={() => handleRemove(l.id)} className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-red)] shrink-0">
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3 shrink-0">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <button type="button" onClick={handleApply} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
              <Save size={13} /> Apply Changes
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default ReferenceLinksModal;
