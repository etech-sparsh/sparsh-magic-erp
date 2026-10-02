import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, Check, X, Loader2, ToggleLeft, ToggleRight, Tag as TagIcon } from 'lucide-react';
import {
  getTaskCategories, createTaskCategory, updateTaskCategory, deleteTaskCategory,
  getTaskTags, createTaskTag, updateTaskTag, deleteTaskTag,
} from '../../services/taskMetaApi';
import { useNotification } from '../../context/NotificationContext';

// Shared CRUD manager for task categories & tags (Settings ▸ Categories / Tags).
// `kind` selects which API set to use; both back onto the same task_meta endpoints.
const API = {
  category: { list: getTaskCategories, create: createTaskCategory, update: updateTaskCategory, remove: deleteTaskCategory, label: 'Category' },
  tag: { list: getTaskTags, create: createTaskTag, update: updateTaskTag, remove: deleteTaskTag, label: 'Tag' },
};

const TaxonomyManager = ({ kind }) => {
  const api = API[kind];
  const { showSuccess, showError } = useNotification();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.list(); // no active_only -> full list incl. inactive
      setItems(res.data || []);
    } catch {
      showError(`Failed to load ${api.label.toLowerCase()}s`);
    } finally {
      setLoading(false);
    }
  }, [api, showError]);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    try {
      await api.create(name);
      setNewName('');
      showSuccess(`${api.label} created`);
      fetchItems();
    } catch (err) {
      showError(err.response?.data?.detail || `Failed to create ${api.label.toLowerCase()}`);
    } finally {
      setCreating(false);
    }
  };

  const handleRename = async (item) => {
    const name = editName.trim();
    if (!name) return;
    try {
      await api.update(item.id, { name });
      setEditingId(null);
      showSuccess(`${api.label} renamed`);
      fetchItems();
    } catch (err) {
      showError(err.response?.data?.detail || 'Rename failed');
    }
  };

  const handleToggle = async (item) => {
    try {
      await api.update(item.id, { active: !item.active });
      fetchItems();
    } catch (err) {
      showError(err.response?.data?.detail || 'Update failed');
    }
  };

  const handleDelete = async (item) => {
    try {
      await api.remove(item.id);
      showSuccess(`${api.label} deleted`);
      fetchItems();
    } catch (err) {
      showError(err.response?.data?.detail || 'Delete failed');
    }
  };

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm max-w-3xl">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]"><TagIcon size={16} /></div>
        <div>
          <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">{api.label === 'Category' ? 'Task Categories' : 'Task Tags'}</h2>
          <p className="text-[11px] font-medium text-[var(--text-muted)]">Active {api.label.toLowerCase()}s appear in the task creation form.</p>
        </div>
      </div>

      {/* Create */}
      <div className="flex items-center gap-2 mb-4">
        <input value={newName} onChange={e => setNewName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleCreate(); } }}
          placeholder={`New ${api.label.toLowerCase()} name...`}
          className="flex-1 px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        <button onClick={handleCreate} disabled={creating || !newName.trim()}
          className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest disabled:opacity-60">
          {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Add
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center py-10"><Loader2 size={20} className="animate-spin text-[var(--accent-indigo)]" /></div>
      ) : items.length === 0 ? (
        <p className="text-center text-[12px] font-bold text-[var(--text-muted)] py-10">No {api.label.toLowerCase()}s yet.</p>
      ) : (
        <div className="space-y-1.5">
          {items.map(item => (
            <div key={item.id} className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)]">
              {editingId === item.id ? (
                <>
                  <input autoFocus value={editName} onChange={e => setEditName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleRename(item); } if (e.key === 'Escape') setEditingId(null); }}
                    className="flex-1 px-2 py-1 bg-[var(--bg-card)] border border-[var(--accent-indigo)] rounded-lg text-[12px] font-bold outline-none" />
                  <button onClick={() => handleRename(item)} className="p-1.5 text-[var(--accent-green)] hover:bg-[var(--accent-green-bg)] rounded-lg"><Check size={15} /></button>
                  <button onClick={() => setEditingId(null)} className="p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-card)] rounded-lg"><X size={15} /></button>
                </>
              ) : (
                <>
                  <span className={`flex-1 text-[13px] font-bold ${item.active ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)] line-through'}`}>{item.name}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider ${item.active ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                    {item.active ? 'Active' : 'Inactive'}
                  </span>
                  <button onClick={() => handleToggle(item)} title={item.active ? 'Deactivate' : 'Activate'} className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                    {item.active ? <ToggleRight size={20} className="text-[var(--accent-indigo)]" /> : <ToggleLeft size={20} />}
                  </button>
                  <button onClick={() => { setEditingId(item.id); setEditName(item.name); }} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--bg-card)] rounded-lg"><Pencil size={14} /></button>
                  <button onClick={() => handleDelete(item)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-lg"><Trash2 size={14} /></button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default TaxonomyManager;
