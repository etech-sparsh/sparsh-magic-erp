import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { CalendarDays, Plus, Search, Pencil, Trash2, X, FileSpreadsheet } from 'lucide-react';
import { getHolidays, deleteHoliday } from '../services/holidayApi';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import HolidayFormModal from '../components/holiday/HolidayFormModal';
import HolidayImportModal from '../components/holiday/HolidayImportModal';
import { SelectField } from '../components/common/StyledSelect';

// Holiday module is restricted to Super Admin / Admin only (view + manage).
const MANAGE_ROLES = ['superadmin', 'admin'];
const HOLIDAY_TYPES = ['National', 'Festival', 'Company', 'Optional'];

const todayKey = () => new Date().toISOString().slice(0, 10);

// Upcoming / Today / Past badge derived from the holiday date vs today (both YYYY-MM-DD,
// so a plain string comparison is timezone-safe).
const timingOf = (dateKey) => {
  const t = todayKey();
  if (!dateKey) return null;
  if (dateKey === t) return { label: 'Today', color: 'var(--accent-indigo)' };
  if (dateKey > t) return { label: 'Upcoming', color: 'var(--accent-green)' };
  return { label: 'Past', color: 'var(--text-muted)' };
};

const formatDate = (dateKey) => {
  if (!dateKey) return '—';
  const d = new Date(`${dateKey}T00:00:00`);
  if (isNaN(d.getTime())) return dateKey;
  return d.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
};

const Holiday = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const canManage = MANAGE_ROLES.includes(user?.role?.toLowerCase());

  const [holidays, setHolidays] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const [modalOpen, setModalOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const fetchHolidays = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getHolidays();
      setHolidays(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load holidays');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHolidays(); }, [fetchHolidays]);

  // Client-side search + type filter over the already-fetched list.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return holidays.filter(h => {
      if (typeFilter && (h.holiday_type || '') !== typeFilter) return false;
      if (!q) return true;
      return (h.holiday_name || '').toLowerCase().includes(q) || (h.description || '').toLowerCase().includes(q);
    });
  }, [holidays, search, typeFilter]);

  const openAdd = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (h) => { setEditing(h); setModalOpen(true); };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteHoliday(deleteTarget.id);
      showSuccess('Holiday deleted');
      setDeleteTarget(null);
      fetchHolidays();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to delete holiday');
    } finally {
      setDeleting(false);
    }
  };

  // Page guard: only Super Admin / Admin can open the Holiday module.
  if (user && !MANAGE_ROLES.includes(user?.role?.toLowerCase())) return <Navigate to="/" replace />;

  return (
    <div className="space-y-5 pb-24">
      {/* ─── Header ─── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
            <CalendarDays size={20} />
          </div>
          <div>
            <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">Holiday</h1>
            <p className="text-[12px] text-[var(--text-muted)] font-bold">Manage your organization's holiday calendar</p>
          </div>
        </div>
        {canManage && (
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={() => setImportOpen(true)}
              className="flex items-center gap-2 px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-xl text-[11px] font-black uppercase tracking-widest hover:border-[var(--accent-indigo)] transition-all">
              <FileSpreadsheet size={16} /> Import
            </button>
            <button onClick={openAdd}
              className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
              <Plus size={16} /> Holiday
            </button>
          </div>
        )}
      </div>

      {/* ─── Filters ─── */}
      <div className="flex flex-wrap items-center gap-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-3">
        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search holidays..."
            className="w-full pl-10 pr-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
        <SelectField value={typeFilter} onChange={setTypeFilter}
          options={[{ id: '', name: 'All Types' }, ...HOLIDAY_TYPES.map(t => ({ id: t, name: t }))]} />
        {(search || typeFilter) && (
          <button onClick={() => { setSearch(''); setTypeFilter(''); }}
            className="px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)]">
            Clear
          </button>
        )}
      </div>

      {/* ─── Table ─── */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
        {loading ? (
          <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading holidays...</div>
        ) : error ? (
          <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
            <CalendarDays size={40} className="mb-3 opacity-30" />
            <p className="text-[12px] font-bold">{holidays.length === 0 ? 'No holidays added yet.' : 'No holidays match your filters.'}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  {['Holiday', 'Date', 'Type', 'Status', 'When', canManage ? 'Action' : ''].filter(Boolean).map(h => (
                    <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(h => {
                  const timing = timingOf(h.holiday_date);
                  return (
                    <tr key={h.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                      <td className="px-5 py-3.5">
                        <p className="text-[13px] font-bold text-[var(--text-main)]">{h.holiday_name}</p>
                        {h.description && <p className="text-[11px] font-medium text-[var(--text-muted)] truncate max-w-[280px]">{h.description}</p>}
                      </td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{formatDate(h.holiday_date)}</td>
                      <td className="px-5 py-3.5">
                        <span className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]">{h.holiday_type || 'Company'}</span>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className="text-[11px] font-black uppercase tracking-wider" style={{ color: h.status === 'inactive' ? 'var(--text-muted)' : 'var(--accent-green)' }}>
                          {h.status === 'inactive' ? 'Inactive' : 'Active'}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        {timing && (
                          <span className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                            style={{ background: `color-mix(in srgb, ${timing.color} 14%, transparent)`, color: timing.color }}>
                            {timing.label}
                          </span>
                        )}
                      </td>
                      {canManage && (
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-1.5">
                            <button onClick={() => openEdit(h)} title="Edit"
                              className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--input-bg)] transition-all">
                              <Pencil size={15} />
                            </button>
                            <button onClick={() => setDeleteTarget(h)} title="Delete"
                              className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--input-bg)] transition-all">
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ─── Add / Edit Modal ─── */}
      <HolidayFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} holiday={editing} onSaved={fetchHolidays} />

      {/* ─── Bulk Import Modal ─── */}
      <HolidayImportModal isOpen={importOpen} onClose={() => setImportOpen(false)} existingHolidays={holidays} onImported={fetchHolidays} />

      {/* ─── Delete Confirm ─── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDeleteTarget(null)} />
          <div className="relative w-full max-w-sm bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[14px] font-black text-[var(--text-main)]">Delete Holiday</h3>
              <button onClick={() => setDeleteTarget(null)} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
            </div>
            <p className="text-[12px] font-medium text-[var(--text-muted)]">
              Remove <span className="font-black text-[var(--text-main)]">{deleteTarget.holiday_name}</span> ({formatDate(deleteTarget.holiday_date)})? This can't be undone.
            </p>
            <div className="flex items-center justify-end gap-3 mt-5">
              <button onClick={() => setDeleteTarget(null)} className="px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
              <button onClick={confirmDelete} disabled={deleting}
                className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-red)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 disabled:opacity-60 transition-all">
                <Trash2 size={14} /> {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Holiday;
