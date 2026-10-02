import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Search, RotateCcw, ChevronRight, History } from 'lucide-react';
import api from '../services/api';
import { getTaskActivity } from '../services/taskApi';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import DateRangeFilter from '../components/tasks/DateRangeFilter';
import { getInitials } from '../components/tasks/taskDisplayUtils';
import { metaFor, extractStatusChange, formatDateTime } from '../components/tasks/activityDisplayUtils';
import { SelectField } from '../components/common/StyledSelect';

const ADMIN_ROLES = ['superadmin', 'admin', 'coach', 'staff'];
const PAGE_SIZE = 30;

const TaskActivity = () => {
  const { user } = useAuth();
  const { showError } = useNotification();
  const isAdmin = ADMIN_ROLES.includes(user?.role?.toLowerCase());

  const [period, setPeriod] = useState('all_time');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [updatedBy, setUpdatedBy] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const [activities, setActivities] = useState([]);
  const [summary, setSummary] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const [users, setUsers] = useState([]);

  useEffect(() => {
    api.get('/users?active_only=true').then(res => setUsers(res.data || [])).catch(() => {});
  }, []);

  // Display-name / id → designation, to show each actor's role under their name.
  const roleById = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.designation || ''; });
    return m;
  }, [users]);

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  const queryParams = useMemo(() => ({
    period,
    startDate: period === 'custom' ? startDate : undefined,
    endDate: period === 'custom' ? endDate : undefined,
    updatedBy: updatedBy || undefined,
    search: debouncedSearch || undefined,
  }), [period, startDate, endDate, updatedBy, debouncedSearch]);

  const fetchActivity = useCallback(async (nextPage = 0, append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    setError(null);
    try {
      const res = await getTaskActivity({ ...queryParams, limit: PAGE_SIZE, skip: nextPage * PAGE_SIZE });
      const data = res.data || {};
      setActivities(prev => (append ? [...prev, ...(data.activities || [])] : (data.activities || [])));
      setSummary(data.summary || []);
      setTotal(data.total || 0);
      setPage(nextPage);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load activity');
      if (!append) showError(err.response?.data?.detail || 'Failed to load activity');
    } finally {
      append ? setLoadingMore(false) : setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryParams]);

  useEffect(() => { fetchActivity(0, false); }, [fetchActivity]);

  const resetFilters = () => {
    setPeriod('all_time');
    setStartDate('');
    setEndDate('');
    setUpdatedBy('');
    setSearch('');
  };

  const hasMore = activities.length < total;

  return (
    <div className="space-y-5 pb-24">
      {/* ─── Header ─── */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
          <History size={20} />
        </div>
        <div>
          <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">Activity</h1>
          <p className="text-[12px] text-[var(--text-muted)] font-bold">Task management activity log</p>
        </div>
      </div>

      {/* ─── Summary Cards (per-user activity counts) ─── */}
      {summary.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
          {summary.map(s => (
            <div key={s.userId || s.userName} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 flex items-center gap-3">
              <div className="w-11 h-11 rounded-full flex items-center justify-center text-white font-black text-[13px] shrink-0" style={{ background: 'var(--accent-indigo)' }}>
                {getInitials(s.userName)}
              </div>
              <div className="min-w-0">
                <p className="text-[13px] font-black text-[var(--text-main)] truncate">{s.userName}</p>
                <p className="text-[11px] font-bold text-[var(--text-muted)]">{s.count} {s.count === 1 ? 'activity' : 'activities'}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ─── Filter Bar ─── */}
      <div className="flex flex-wrap items-center gap-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-3">
        <DateRangeFilter variant="dropdown" period={period} onPeriodChange={setPeriod} startDate={startDate} endDate={endDate}
          onCustomChange={(field, value) => (field === 'startDate' ? setStartDate(value) : setEndDate(value))} />

        {isAdmin && (
          <SelectField value={updatedBy} onChange={setUpdatedBy}
            options={[{ id: '', name: 'Updated By' },
                      ...users.map(u => ({ id: u._id, name: u.full_name || u.email }))]} />
        )}

        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search activity, task or user..."
            className="w-full pl-10 pr-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>

        <button onClick={resetFilters}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-all">
          <RotateCcw size={14} /> Reset
        </button>
      </div>

      {/* ─── Activity Feed ─── */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
        {loading ? (
          <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading activity...</div>
        ) : error ? (
          <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold">{error}</div>
        ) : activities.length === 0 ? (
          <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
            <Activity size={40} className="mb-3 opacity-30" />
            <p className="text-[12px] font-bold">No activity found for the selected filters.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {activities.map(a => {
              const meta = metaFor(a.action);
              const Icon = meta.icon;
              const statusChange = a.action === 'Update Task Status' ? extractStatusChange(a.details) : null;
              const role = roleById[a.updatedBy];
              return (
                <div key={a.id} className="flex items-start gap-3.5 px-5 py-4 hover:bg-[var(--input-bg)] transition-colors group">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}>
                    <Icon size={16} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[12px] font-black text-[var(--text-main)]">{meta.label}</span>
                      {statusChange && (
                        <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-wider"
                          style={{ background: 'color-mix(in srgb, var(--accent-green) 14%, transparent)', color: 'var(--accent-green)' }}>
                          → {statusChange}
                        </span>
                      )}
                    </div>
                    {a.details && <p className="text-[12px] font-medium text-[var(--text-muted)] mt-0.5 break-words">{a.details}</p>}
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <div className="w-5 h-5 rounded-full flex items-center justify-center text-white font-black text-[8px] shrink-0" style={{ background: 'var(--accent-indigo)' }}>
                        {getInitials(a.updatedByName)}
                      </div>
                      <span className="text-[11px] font-bold text-[var(--text-main)]">{a.updatedByName || 'Unknown'}</span>
                      {role && <span className="text-[10px] font-bold text-[var(--accent-indigo)]">· {role}</span>}
                      <span className="text-[10px] font-bold text-[var(--text-muted)]">· {formatDateTime(a.updatedAt)}</span>
                    </div>
                  </div>

                  <ChevronRight size={16} className="text-[var(--text-muted)] opacity-0 group-hover:opacity-60 transition-opacity shrink-0 mt-1" />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ─── Load More ─── */}
      {!loading && !error && hasMore && (
        <div className="flex justify-center">
          <button onClick={() => fetchActivity(page + 1, true)} disabled={loadingMore}
            className="px-6 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)] border border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] disabled:opacity-50 transition-all">
            {loadingMore ? 'Loading...' : `Load More (${activities.length} of ${total})`}
          </button>
        </div>
      )}
    </div>
  );
};

export default TaskActivity;
