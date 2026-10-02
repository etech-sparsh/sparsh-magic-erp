import React, { useEffect, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Plus, Save, Tag as TagIcon } from 'lucide-react';

// Pill-grid variant of the shared Cancel/Apply-Changes popover shape (see PickerModal),
// used from Extra Options -> Add Tags. `tags` is the distinct set of tags already used
// across tasks (same "derive from existing data" pattern as the Category picker's items).
const TaskTagsModal = ({ isOpen, onClose, tags = [], selected = [], onApply }) => {
  const [pending, setPending] = useState([]);
  const [addingNew, setAddingNew] = useState(false);
  const [newTag, setNewTag] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending([...selected]);
    setAddingNew(false);
    setNewTag('');
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  // `pending` has to be part of this list, not just `tags` + `selected`: a tag the user has
  // just typed exists ONLY in pending, so leaving it out meant the new tag was added to the
  // selection but never rendered — it looked like nothing happened, and it could not be
  // deselected. It is still persisted on Apply (see TaskFormModal.handleTagsApply).
  const allTags = Array.from(new Set([...tags, ...selected, ...pending]));

  const toggle = (tag) => {
    setPending(p => (p.includes(tag) ? p.filter(t => t !== tag) : [...p, tag]));
  };

  const handleAddNew = () => {
    const name = newTag.trim();
    if (!name) return;
    // Match the backend's case-insensitive get-or-create (task_meta.ensure_name), so typing
    // "Urgent" when "urgent" exists selects the existing tag instead of creating a near-
    // duplicate that the server would collapse anyway.
    const existing = allTags.find(t => t.toLowerCase() === name.toLowerCase());
    const canonical = existing || name;
    if (!pending.includes(canonical)) toggle(canonical);
    setNewTag('');
    setAddingNew(false);
  };

  const handleDone = () => {
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
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">Task Tags</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="flex-1 overflow-y-auto no-scrollbar px-5 py-4">
            {allTags.length === 0 && !addingNew && (
              <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-6">No tags yet — add one below</p>
            )}
            <div className="flex flex-wrap gap-2">
              {allTags.map(tag => (
                <button type="button" key={tag} onClick={() => toggle(tag)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${
                    pending.includes(tag) ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)]'
                  }`}>
                  <TagIcon size={11} /> {tag}
                </button>
              ))}
            </div>
          </div>

          {addingNew && (
            <div className="px-5 pb-2 shrink-0">
              <div className="flex items-center gap-2">
                <input autoFocus value={newTag} onChange={e => setNewTag(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddNew(); } }}
                  placeholder="New tag..."
                  className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
                <button type="button" onClick={handleAddNew} className="px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[11px] font-black">Add</button>
              </div>
            </div>
          )}

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3 shrink-0">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <div className="flex items-center gap-2">
              {!addingNew && (
                <button type="button" onClick={() => setAddingNew(true)} className="flex items-center gap-1.5 px-4 py-2 border border-[var(--accent-indigo)] text-[var(--accent-indigo)] rounded-xl text-[10px] font-black uppercase tracking-widest">
                  <Plus size={13} /> Add More
                </button>
              )}
              <button type="button" onClick={handleDone} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
                <Save size={13} /> Done
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default TaskTagsModal;
