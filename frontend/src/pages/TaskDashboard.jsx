import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Table2, BarChart3 as BarChartIcon, Plus, ListChecks, Search } from 'lucide-react';
import api from '../services/api';
import { getTaskDashboard, getTasks } from '../services/taskApi';
import { getTaskCategories, getTaskTags, uniqueNames } from '../services/taskMetaApi';
import { openTaskEventStream } from '../services/taskEventsApi';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import { SelectField } from '../components/common/StyledSelect';
import DateRangeFilter from '../components/tasks/DateRangeFilter';
import TaskFormModal from '../components/tasks/TaskFormModal';
import StatusSummaryCards from '../components/tasks/StatusSummaryCards';
import StackedReportPanel from '../components/tasks/StackedReportPanel';
import TaskDonutPanel from '../components/tasks/TaskDonutPanel';
import ScoreRing from '../components/common/ScoreRing';
import { SUMMARY_CARD_ORDER, STATUS_CONFIG, CARD_KEY_TO_STATUS } from '../components/tasks/statusConfig';
import { formatDate } from '../components/tasks/taskDisplayUtils';

const ADMIN_ROLES = ['superadmin', 'admin', 'coach', 'staff'];

// Every task falls into exactly one of these 4 buckets for the stacked "X Wise" report
// panels — keeps the stacked bar segments mutually exclusive (no double-counting).
const bucketOf = (t) => {
  if (t.isOverdue) return 'overdue';
  if (t.status === 'completed') return 'completed';
  if (t.status === 'in_progress') return 'inProgress';
  return 'pending';
};

// Share-of-total as an integer percent, for the "count (X%)" cells in the report tables.
const pct = (count, total) => (total > 0 ? Math.round((count / total) * 100) : 0);

// Muted parenthetical percentage shown next to a count (e.g. "2 (100%)").
const Pct = ({ count, total }) => (
  <span className="text-[10px] font-medium text-[var(--text-muted)]"> ({pct(count, total)}%)</span>
);

const TABS = [
  { key: 'employees', label: 'Employees', groupBy: 'assignee' },
  { key: 'groups', label: 'Groups', groupBy: 'category' }, // no distinct "group" entity in the data model yet; grouped by category as the nearest analog
  { key: 'my_report', label: 'My Report', scope: 'my' },
  { key: 'delegated', label: 'Delegated', scope: 'delegated' },
  { key: 'daily', label: 'Daily', groupBy: 'day' },
  { key: 'monthly', label: 'Monthly' },
  { key: 'overdue', label: 'Overdue', scope: 'all', filterOverdue: true },
  { key: 'tags', label: 'Tags', groupBy: 'tags' },
  { key: 'categories', label: 'Categories', groupBy: 'category' },
];

const emptyFilters = { assignedTo: '', category: '', tag: '', frequency: '' };

// Dashboard view modes for the lower report section. The donut summary above the filters
// stays visible in both; this toggle only switches the tabular report vs. the stacked bars.
const VIEW_OPTIONS = [
  { key: 'table', label: 'Table', icon: Table2 },
  { key: 'barChart', label: 'Bar Chart', icon: BarChartIcon },
];

const TaskDashboard = () => {
  const { user } = useAuth();
  const { showError } = useNotification();
  const [period, setPeriod] = useState('this_month');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [filters, setFilters] = useState(emptyFilters);
  const [search, setSearch] = useState('');
  const [activeCardKey, setActiveCardKey] = useState(null);
  const activeStatus = activeCardKey === 'overdue' ? 'overdue' : (CARD_KEY_TO_STATUS[activeCardKey] || null);
  const [activeTab, setActiveTab] = useState('monthly');
  const [viewType, setViewType] = useState('table');

  const [users, setUsers] = useState([]);
  const [dashboard, setDashboard] = useState({ summary: null, monthly: [] });
  const [tabTasks, setTabTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    // Name-resolution map — full directory so every participant renders (not just assignable users).
    api.get('/tasks/assignable-users?all=true').then(res => setUsers(res.data || [])).catch(() => {});
  }, []);

  const userMap = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  // Display-name → designation, used to render the role subtitle under each employee bar.
  const designationByName = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u.full_name || u.email] = u.designation || ''; });
    return m;
  }, [users]);

  const queryParams = useMemo(() => ({
    period,
    startDate: period === 'custom' ? startDate : undefined,
    endDate: period === 'custom' ? endDate : undefined,
    assignedTo: filters.assignedTo || undefined,
    category: filters.category || undefined,
    tag: filters.tag || undefined,
    frequency: filters.frequency || undefined,
    search: search || undefined,
  }), [period, startDate, endDate, filters, search]);

  const tab = TABS.find(t => t.key === activeTab);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const dashRes = await getTaskDashboard({ ...queryParams, viewType, reportType: activeTab });
      setDashboard(dashRes.data);

      if (activeTab !== 'monthly') {
        const listRes = await getTasks({ ...queryParams, scope: tab.scope || 'all' });
        setTabTasks(listRes.data || []);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load dashboard');
      showError(err.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryParams, viewType, activeTab]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Real-time: debounced refresh of the dashboard when a task involving me changes.
  const fetchAllRef = useRef(fetchAll);
  useEffect(() => { fetchAllRef.current = fetchAll; }, [fetchAll]);
  useEffect(() => {
    let debounce = null;
    const cleanup = openTaskEventStream(() => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => fetchAllRef.current?.(), 400);
    });
    return () => { if (debounce) clearTimeout(debounce); cleanup(); };
  }, []);

  const [categories, setCategories] = useState([]);
  const [tags, setTags] = useState([]);

  // Persisted server-side (task_categories / task_tags) rather than derived from whichever
  // tasks the active tab/filters happen to have loaded — see TaskListView.jsx's fetchTaxonomy.
  const fetchTaxonomy = useCallback(async () => {
    try {
      const [catRes, tagRes] = await Promise.all([getTaskCategories(), getTaskTags()]);
      // Names are rendered as <option key={name}>, so blanks and duplicates would collide
      // into repeated React keys. A nameless category/tag is meaningless as an option.
      setCategories(uniqueNames(catRes.data));
      setTags(uniqueNames(tagRes.data));
    } catch {
      // Non-fatal
    }
  }, []);

  useEffect(() => { fetchTaxonomy(); }, [fetchTaxonomy]);

  const clearFilters = () => {
    setFilters(emptyFilters);
    setSearch('');
    setActiveCardKey(null);
  };

  // ─── Grouped rows for Employees / Groups / Daily / Tags / Categories tabs ───
  const groupedRows = useMemo(() => {
    if (!tab?.groupBy) return [];
    let source = tabTasks;
    if (tab.filterOverdue) source = source.filter(t => t.isOverdue);
    if (activeStatus) source = source.filter(t => t.status === activeStatus || (activeStatus === 'overdue' && t.isOverdue));

    const groupByFn = (t) => {
      if (tab.groupBy === 'assignee') return (t.assignedTo?.length ? t.assignedTo.map(id => userMap[id] || id) : ['Unassigned']);
      if (tab.groupBy === 'category') return [t.category || 'Uncategorized'];
      if (tab.groupBy === 'tags') return (t.tags?.length ? t.tags : ['Untagged']);
      if (tab.groupBy === 'day') return [t.start ? new Date(t.start).toLocaleDateString() : 'No Date'];
      return ['—'];
    };

    const map = new Map();
    source.forEach(t => {
      groupByFn(t).forEach(key => {
        if (!map.has(key)) map.set(key, { label: key, total: 0, pending: 0, inProgress: 0, completed: 0, overdue: 0 });
        const row = map.get(key);
        row.total += 1;
        if (t.status === 'pending') row.pending += 1;
        if (t.status === 'in_progress') row.inProgress += 1;
        if (t.status === 'completed') row.completed += 1;
        if (t.isOverdue) row.overdue += 1;
      });
    });
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [tab, tabTasks, activeStatus, userMap]);

  // Flat task rows for My Report / Delegated / Overdue tabs
  const flatRows = useMemo(() => {
    if (tab?.groupBy) return [];
    let rows = tabTasks;
    if (tab?.filterOverdue) rows = rows.filter(t => t.isOverdue);
    if (activeStatus) rows = rows.filter(t => t.status === activeStatus || (activeStatus === 'overdue' && t.isOverdue));
    return rows;
  }, [tab, tabTasks, activeStatus]);

  // ─── Bar Chart view: multi-panel stacked reports (Employee/Category/Daily/Monthly/Delegated) ───
  const isAdminRole = ADMIN_ROLES.includes(user?.role?.toLowerCase());
  const [chartAllTasks, setChartAllTasks] = useState([]);
  const [chartDelegatedTasks, setChartDelegatedTasks] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);

  // Bar and Line views both derive their series from the same fetched task lists; Pie uses
  // dashboard.summary (already loaded on every fetch) and Table needs neither, so only pull
  // the heavier all/delegated lists when a series-based view is actually showing.
  const needsChartData = viewType === 'barChart' || viewType === 'lineChart';

  useEffect(() => {
    if (!needsChartData) return;
    let cancelled = false;
    setChartLoading(true);
    Promise.all([
      getTasks({ ...queryParams, scope: isAdminRole ? 'all' : 'my' }),
      getTasks({ ...queryParams, scope: 'delegated' }),
    ]).then(([allRes, delRes]) => {
      if (cancelled) return;
      setChartAllTasks(allRes.data || []);
      setChartDelegatedTasks(delRes.data || []);
    }).catch(() => { if (!cancelled) showError('Failed to load chart reports'); })
      .finally(() => { if (!cancelled) setChartLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsChartData, queryParams, isAdminRole]);

  const groupStacked = (tasks, labelFn) => {
    const map = new Map();
    tasks.forEach(t => {
      const label = labelFn(t);
      if (!label) return;
      if (!map.has(label)) map.set(label, { label, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0, sortKey: label });
      const row = map.get(label);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return map;
  };

  const employeeRows = useMemo(() => {
    const map = groupStacked(chartAllTasks, t => (t.assignedTo?.length ? (userMap[t.assignedTo[0]] || 'Unknown') : 'Myself'));
    return Array.from(map.values())
      .map(r => ({ ...r, sub: designationByName[r.label] || '' }))
      .sort((a, b) => b.total - a.total);
  }, [chartAllTasks, userMap, designationByName]);

  const categoryRows = useMemo(() => {
    const map = groupStacked(chartAllTasks, t => t.category || 'Uncategorized');
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [chartAllTasks]);

  const dailyRows = useMemo(() => {
    const map = new Map();
    chartAllTasks.forEach(t => {
      if (!t.start) return;
      const d = new Date(t.start);
      const key = d.toISOString().slice(0, 10);
      if (!map.has(key)) map.set(key, { label: d.toLocaleDateString(undefined, { day: '2-digit', month: 'long', year: 'numeric' }), sortKey: key, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0 });
      const row = map.get(key);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return Array.from(map.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }, [chartAllTasks]);

  const monthlyChartRows = useMemo(() => {
    const map = new Map();
    chartAllTasks.forEach(t => {
      if (!t.start) return;
      const d = new Date(t.start);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      if (!map.has(key)) map.set(key, { label: d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' }), sortKey: key, pending: 0, overdue: 0, inProgress: 0, completed: 0, total: 0 });
      const row = map.get(key);
      row[bucketOf(t)] += 1;
      row.total += 1;
    });
    return Array.from(map.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }, [chartAllTasks]);

  const delegatedChartRows = useMemo(() => {
    const map = groupStacked(chartDelegatedTasks, t => (t.assignedTo?.length ? (userMap[t.assignedTo[0]] || 'Unknown') : 'Unassigned'));
    return Array.from(map.values())
      .map(r => ({ ...r, sub: designationByName[r.label] || '' }))
      .sort((a, b) => b.total - a.total);
  }, [chartDelegatedTasks, userMap, designationByName]);

  // ─── Donut breakdowns (shown above the toggle in both views) ───
  // Sourced from the same server-computed `dashboard.summary` the cards use, so the donut
  // slices always agree with the summary card counts for the current period/filters.
  const donutPanels = useMemo(() => {
    const s = dashboard.summary || {};
    const total = s.totalTasks || 0;
    const completed = s.completed || 0;
    return [
      {
        title: 'Overdue, Pending & In-Progress',
        slices: [
          { label: 'Overdue', value: s.overdue || 0, color: 'var(--accent-red)' },
          { label: 'Pending', value: s.pending || 0, color: 'var(--accent-orange)' },
          { label: 'In Progress', value: s.inProgress || 0, color: 'var(--accent-yellow)' },
        ],
      },
      {
        title: 'Completed & Not Completed',
        slices: [
          { label: 'Completed', value: completed, color: 'var(--accent-green)' },
          { label: 'Not Completed', value: Math.max(0, total - completed), color: 'var(--accent-red)' },
        ],
      },
      {
        title: 'In-Time & Delayed',
        slices: [
          { label: 'In-Time', value: s.inTime || 0, color: 'var(--accent-green)' },
          { label: 'Delayed', value: s.delayed || 0, color: 'var(--text-muted)' },
        ],
      },
    ];
  }, [dashboard.summary]);

  return (
    <div className="space-y-6 pb-24">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Task Dashboard</h1>
          <p className="text-[13px] text-[var(--text-muted)] font-bold">Organization task performance overview</p>
        </div>
        <button onClick={() => setModalOpen(true)}
          className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all shrink-0">
          <Plus size={16} /> Create Task
        </button>
      </div>

      <DateRangeFilter
        period={period}
        onPeriodChange={setPeriod}
        startDate={startDate}
        endDate={endDate}
        onCustomChange={(field, value) => (field === 'startDate' ? setStartDate(value) : setEndDate(value))}
      />

      {/* ─── Summary Cards (hidden in Bar Chart view) ─── */}
      {viewType !== 'barChart' && (
        <StatusSummaryCards
          cardOrder={SUMMARY_CARD_ORDER}
          summary={dashboard.summary}
          activeKey={activeCardKey}
          onSelect={(key) => setActiveCardKey(prev => (prev === key ? null : key))}
          columnsClass="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4"
        />
      )}

      {/* ─── Donut Breakdowns (Bar Chart view only) ─── */}
      {viewType === 'barChart' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {donutPanels.map(p => <TaskDonutPanel key={p.title} title={p.title} slices={p.slices} />)}
        </div>
      )}

      {/* ─── Filters ─── */}
      <div className="flex flex-wrap items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tasks..."
            className="w-full pl-10 pr-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
        {/* The leading `{ id: '', name: … }` entry is the old `<option value="">` placeholder:
            it is what shows while the filter is unset, and picking it clears the filter. */}
        <SelectField value={filters.assignedTo} onChange={v => setFilters({ ...filters, assignedTo: v })}
          options={[{ id: '', name: 'Assigned To' },
                    ...users.map(u => ({ id: u._id, name: u.full_name || u.email }))]} />
        <SelectField value={filters.category} onChange={v => setFilters({ ...filters, category: v })}
          options={[{ id: '', name: 'Category' }, ...categories.map(c => ({ id: c, name: c }))]} />
        <SelectField value={filters.tag} onChange={v => setFilters({ ...filters, tag: v })}
          options={[{ id: '', name: 'Tag' }, ...tags.map(t => ({ id: t, name: t }))]} />
        <SelectField value={filters.frequency} onChange={v => setFilters({ ...filters, frequency: v })}
          options={[{ id: '', name: 'Frequency' },
                    ...['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'].map(f => ({ id: f, name: f }))]} />
        {(search || filters.assignedTo || filters.category || filters.tag || filters.frequency || activeCardKey) && (
          <button onClick={clearFilters}
            className="ml-auto px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)]">
            Clear
          </button>
        )}
      </div>

      {/* ─── View Toggle (Table / Bar Chart — one visible at a time) ─── */}
      <div className="flex justify-center">
        <div className="flex items-center gap-1 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
          {VIEW_OPTIONS.map(v => {
            const Icon = v.icon;
            return (
              <button key={v.key} onClick={() => setViewType(v.key)}
                className={`flex items-center gap-2 px-5 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${viewType === v.key ? 'bg-[var(--accent-green)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                <Icon size={15} /> {v.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ─── Bar Chart view: one stacked-bar panel per report ─── */}
      {viewType === 'barChart' && (
        chartLoading ? (
          <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px]">Loading reports...</div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <StackedReportPanel title="Employee Wise" axisLabel="Employee Name" rows={employeeRows} />
            <StackedReportPanel title="Category Wise" axisLabel="Category Name" rows={categoryRows} />
            <StackedReportPanel title="Daily Report" axisLabel="Date" rows={dailyRows} />
            <StackedReportPanel title="Monthly Report" axisLabel="Month" rows={monthlyChartRows} />
            <StackedReportPanel title="Delegated Tasks Report" axisLabel="Assigned To" rows={delegatedChartRows} />
          </div>
        )
      )}

      {/* ─── Table view ─── */}
      {viewType === 'table' && (
        <>
          {/* ─── Tabs ─── */}
          <div className="flex flex-wrap bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl shadow-sm gap-1">
            {TABS.map(t => (
              <button key={t.key} onClick={() => setActiveTab(t.key)}
                className={`px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                  activeTab === t.key ? 'bg-[var(--accent-indigo)] text-white shadow-md' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* ─── Content ─── */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] overflow-hidden shadow-sm">
            {loading ? (
              <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading dashboard...</div>
            ) : error ? (
              <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold">{error}</div>
            ) : activeTab === 'monthly' ? (
              dashboard.monthly.length === 0 ? (
                <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
                  <ListChecks size={40} className="mb-3 opacity-30" />
                  <p className="text-[12px] font-bold">No monthly data for the selected filters.</p>
                </div>
              ) : (
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      {['Month', 'Total', 'Score', 'Overdue', 'Pending', 'In-Progress', 'In Time', 'Delayed'].map(h => (
                        <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.monthly.map(row => (
                      <tr key={row.month} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                        <td className="px-5 py-3.5 text-[13px] font-bold text-[var(--text-main)]">
                          <span className="inline-flex items-center gap-2.5">
                            <ScoreRing value={row.total > 0 ? (row.inTime / row.total) * 100 : 0} />
                            <span className="truncate">{row.month}</span>
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{row.total}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-green)]">{(row.total > 0 ? (row.inTime / row.total) * 100 : 0).toFixed(1)}%</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.overdue}<Pct count={row.overdue} total={row.total} /></td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-yellow)]">{row.pending}<Pct count={row.pending} total={row.total} /></td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-indigo)]">{row.inProgress}<Pct count={row.inProgress} total={row.total} /></td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-green)]">{row.inTime}<Pct count={row.inTime} total={row.total} /></td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.delayed}<Pct count={row.delayed} total={row.total} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            ) : (tab?.groupBy ? groupedRows.length === 0 : flatRows.length === 0) ? (
              <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
                <ListChecks size={40} className="mb-3 opacity-30" />
                <p className="text-[12px] font-bold">No tasks found for the selected filters.</p>
              </div>
            ) : tab?.groupBy ? (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {[tab.label.replace(/s$/, ''), 'Total', 'Pending', 'In Progress', 'Completed', 'Overdue'].map(h => (
                      <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groupedRows.map(row => (
                    <tr key={row.label} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                      <td className="px-5 py-3.5 text-[13px] font-bold text-[var(--text-main)]">
                        {tab?.groupBy === 'assignee' ? (
                          <span className="inline-flex items-center gap-2.5">
                            <ScoreRing value={row.total > 0 ? Math.round((row.completed / row.total) * 100) : 0} />
                            <span className="truncate">{row.label}</span>
                          </span>
                        ) : row.label}
                      </td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{row.total}</td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-yellow)]">{row.pending}<Pct count={row.pending} total={row.total} /></td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-indigo)]">{row.inProgress}<Pct count={row.inProgress} total={row.total} /></td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-green)]">{row.completed}<Pct count={row.completed} total={row.total} /></td>
                      <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--accent-red)]">{row.overdue}<Pct count={row.overdue} total={row.total} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {['Title', 'Category', 'Assigned To', 'Due', 'Status'].map(h => (
                      <th key={h} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {flatRows.map(t => {
                    const cfg = STATUS_CONFIG[t.status] || STATUS_CONFIG.pending;
                    return (
                      <tr key={t.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                        <td className="px-5 py-3.5">
                          <p className="text-[13px] font-bold text-[var(--text-main)]">{t.title}</p>
                          {t.isOverdue && <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest">Overdue</span>}
                        </td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{t.category || '—'}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{(t.assignedTo || []).map(id => userMap[id] || id).join(', ') || 'Myself'}</td>
                        <td className="px-5 py-3.5 text-[12px] font-bold text-[var(--text-muted)]">{t.end ? formatDate(t.end) : '—'}</td>
                        <td className="px-5 py-3.5">
                          <span className="px-3 py-1.5 rounded-lg text-[10px] font-black border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>{cfg.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} onSaved={fetchAll}
        categories={categories} tags={tags} onTaxonomyChanged={fetchTaxonomy} />
    </div>
  );
};

export default TaskDashboard;
