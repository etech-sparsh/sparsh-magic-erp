import React, { useState, useEffect, useCallback } from 'react';
import { Plus, Pencil, Trash2, Check, X, Search } from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';

/**
 * Reusable CRUD list for task Categories / Tags.
 * Wraps the existing /task-categories and /task-tags endpoints — no backend change.
 *
 * Props: { title, subtitle, endpoint ('/task-categories'|'/task-tags'), icon, canManage, label }
 */
const MetaListSection = ({ title, subtitle, endpoint, icon: Icon, canManage, label = 'item' }) => {
  const { showSuccess, showError } = useNotification();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get(endpoint);
      setItems(res.data || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [endpoint]);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      await api.post(endpoint, { name });
      setNewName('');
      showSuccess(`${label} added`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || `Failed to add ${label.toLowerCase()}`);
    }
  };

  const saveEdit = async (id) => {
    const name = editName.trim();
    if (!name) return;
    try {
      await api.patch(`${endpoint}/${id}`, { name });
      setEditingId(null);
      setEditName('');
      showSuccess(`${label} updated`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || `Failed to update ${label.toLowerCase()}`);
    }
  };

  const toggleActive = async (item) => {
    try {
      await api.patch(`${endpoint}/${item.id}`, { active: !item.active });
      load();
    } catch (err) {
      showError('Failed to update status');
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`${endpoint}/${id}`);
      showSuccess(`${label} deleted`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || `Failed to delete ${label.toLowerCase()}`);
    }
  };

  const filtered = items.filter((i) => (i.name || '').toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="max-w-3xl mx-auto w-full space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]">
          <Icon size={20} />
        </div>
        <div>
          <h2 className="text-[15px] font-bold text-[var(--text-main)] tracking-tight">{title}</h2>
          <p className="text-[11px] text-[var(--text-muted)] font-medium">{subtitle}</p>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm overflow-hidden">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2.5 p-4 border-b border-[var(--border)]">
          <div className="relative flex-1 min-w-[160px]">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={`Search ${title.toLowerCase()}...`}
              className="w-full pl-9 pr-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-medium outline-none focus:border-[var(--accent-indigo)]"
            />
          </div>
          {canManage && (
            <div className="flex items-center gap-2 flex-1 min-w-[200px]">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && add()}
                placeholder={`New ${label.toLowerCase()} name...`}
                className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-medium outline-none focus:border-[var(--accent-indigo)]"
              />
              <button
                onClick={add}
                className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all shrink-0"
              >
                <Plus size={14} /> Add
              </button>
            </div>
          )}
        </div>

        {/* List */}
        <div className="max-h-[460px] overflow-y-auto no-scrollbar divide-y divide-[var(--border)]">
          {loading ? (
            <p className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--text-muted)]">
              No {title.toLowerCase()} found.
            </p>
          ) : (
            filtered.map((item) => (
              <div key={item.id} className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--input-bg)] transition-colors group">
                <span className={`w-2 h-2 rounded-full shrink-0 ${item.active ? 'bg-[var(--accent-green)]' : 'bg-[var(--text-muted)] opacity-40'}`} />
                {editingId === item.id ? (
                  <>
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && saveEdit(item.id)}
                      autoFocus
                      className="flex-1 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--accent-indigo)] rounded-lg text-[13px] font-bold outline-none"
                    />
                    <button onClick={() => saveEdit(item.id)} className="p-1.5 rounded-lg text-[var(--accent-green)] hover:bg-[var(--accent-green-bg)]"><Check size={15} /></button>
                    <button onClick={() => { setEditingId(null); setEditName(''); }} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={15} /></button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 text-[13px] font-bold text-[var(--text-main)] truncate">{item.name}</span>
                    {!item.active && (
                      <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] px-2 py-0.5 rounded bg-[var(--input-bg)]">Inactive</span>
                    )}
                    {canManage && (
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => toggleActive(item)} title={item.active ? 'Deactivate' : 'Activate'}
                          className="px-2 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-all">
                          {item.active ? 'Disable' : 'Enable'}
                        </button>
                        <button onClick={() => { setEditingId(item.id); setEditName(item.name); }} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]"><Pencil size={13} /></button>
                        <button onClick={() => remove(item.id)} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]"><Trash2 size={13} /></button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default MetaListSection;
