import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  ListChecks, CirclePlus, Filter as FilterIcon, Search, RefreshCw, Download,
  List as ListIcon, LayoutGrid, ArrowUpDown, Trash2, RotateCcw,
  Eye, X, Check, ChevronDown, ChevronLeft, ChevronRight, Repeat, Forward,
} from 'lucide-react';
import api from '../../services/api';
import { getTasks, softDeleteTask, restoreTask, updateTaskStatus, reviseTaskDeadline } from '../../services/taskApi';
import { getTaskCategories, getTaskTags, uniqueNames } from '../../services/taskMetaApi';
import { openTaskEventStream } from '../../services/taskEventsApi';
import { getHolidays } from '../../services/holidayApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, LIST_CARD_ORDER, CARD_KEY_TO_STATUS, cardKeyForStatus, statusesForCardKey, statusOptions, statusOptionLabel, REASON_REQUIRED_STATUSES, VERIFICATION_ACTIONS } from './statusConfig';
import { exportTasksToCsv, groupTasksByRecurrence, isRecurringTask, summarizeSeries, formatOccurrenceDate } from './taskDisplayUtils';
import StatusSummaryCards from './StatusSummaryCards';
import TaskKindTabs from './TaskKindTabs';
import TaskCard from './TaskCard';
import RecurrenceDetail from './RecurrenceDetail';
import DateRangeFilter from './DateRangeFilter';
import TaskFormModal from './TaskFormModal';
import TaskDetailsModal from './TaskDetailsModal';
import StatusReasonModal from './StatusReasonModal';
import { CategoryPill, AssigneeCell, PriorityPill, DateCell, SortableTh, RowActionsMenu, StatusControl } from './taskCells';
import MiniDatePicker from './MiniDatePicker';
import { SelectField } from '../common/StyledSelect';

const SORT_OPTIONS = [
  { key: 'end', label: 'Target Date' },
  { key: 'createdAt', label: 'Created Date' },
  { key: 'title', label: 'Title' },
];

// Rows per page in the table/card list. The reference design pages the table rather than
// scrolling it, which also keeps the row "#" column meaningful.
const PAGE_SIZE = 10;

// The summary cards and the status tab strip are two views of the same filter, so they're
// kept in sync: these translate between a card's response key (`inProgress`) and the
// statusFilter value the tabs use (`in_progress`).
const cardKeyToFilter = (key) => {
  if (!key || key === 'totalTasks') return 'all';
  if (key === 'overdue') return 'overdue';
  return CARD_KEY_TO_STATUS[key] || 'all';
};

const filterToCardKey = (filter) => {
  if (filter === 'all') return 'totalTasks';
  if (filter === 'overdue') return 'overdue';
  return Object.keys(CARD_KEY_TO_STATUS).find(k => CARD_KEY_TO_STATUS[k] === filter) || null;
};

// Shared list used by MyTasks, DelegatedTasks, SubscribedTasks, AllTasks and DeletedTasks —
// each just passes a different `scope` to GET /api/tasks. Visual design follows the
// reference "My Tasks" screenshot: dot-style summary cards, toolbar, scrollable status
// tabs, and avatar/badge row cards.
const TaskListView = ({ scope, heading, subheading, emptyMessage, allowCreate = true, groupId = null, embedded = false, splitByRecurrence = false }) => {
  const { user } = useAuth();
  const isAdmin = ['superadmin', 'admin'].includes(user?.role);
  const { showSuccess, showError } = useNotification();
  const [tasks, setTasks] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [period, setPeriod] = useState('all_time');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [assignedTo, setAssignedTo] = useState('');
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const [frequency, setFrequency] = useState('');
  const [search, setSearch] = useState('');

  // Top-level Recurring / one-time split (My Tasks). Inert unless `splitByRecurrence`.
  const [taskKind, setTaskKind] = useState('recurring');
  const [statusFilter, setStatusFilter] = useState('all');
  // Default to newest-created first so the latest task is always on top (#15). The backend
  // already returns tasks created-desc; this keeps that order as the default client sort too.
  const [sortKey, setSortKey] = useState('createdAt');
  const [sortDir, setSortDir] = useState('desc');
  // The dense table is the primary layout (the reference's "List View"); the card layout stays
  // available behind the grid toggle.
  const [viewMode, setViewMode] = useState('table');
  const [page, setPage] = useState(1);

  const [selected, setSelected] = useState(new Set());
  const [openMenuId, setOpenMenuId] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [detailsTaskId, setDetailsTaskId] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState(new Set());
  const [completing, setCompleting] = useState(new Set()); // task ids with an in-flight status change
  const [reasonTarget, setReasonTarget] = useState(null); // { task, status } awaiting Doer Name + Reason
  const [savingReason, setSavingReason] = useState(false);
  // Reopen (assigner, from Pending Verification): the task awaiting a new deadline + reason.
  const [reopenTarget, setReopenTarget] = useState(null);
  // Holidays + Sunday weekly-off block selection in the Reopen picker, matching the create form.
  const [holidayDates, setHolidayDates] = useState([]);
  const WEEKLY_OFFS = [0];

  const userMap = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTasks({
        scope,
        period,
        startDate: period === 'custom' ? startDate : undefined,
        endDate: period === 'custom' ? endDate : undefined,
        assignedTo: assignedTo || undefined,
        category: category || undefined,
        tag: tag || undefined,
        frequency: frequency || undefined,
        search: search || undefined,
        groupId: groupId || undefined,
      });
      setTasks(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [scope, period, startDate, endDate, assignedTo, category, tag, frequency, search, groupId]);

  const [categories, setCategories] = useState([]);
  const [tagOptions, setTagOptions] = useState([]);

  // Categories/tags are persisted server-side (task_categories / task_tags collections) and
  // shared across every task view — fetched once here rather than derived from whichever
  // tasks this particular scoped/filtered list happens to have loaded.
  const fetchTaxonomy = useCallback(async () => {
    try {
      const [catRes, tagRes] = await Promise.all([getTaskCategories(), getTaskTags()]);
      // See uniqueNames — blank/duplicate names would become repeated React keys.
      setCategories(uniqueNames(catRes.data));
      setTagOptions(uniqueNames(tagRes.data));
    } catch {
      // Non-fatal: task list/creation still works, just without a live options list.
    }
  }, []);

  useEffect(() => {
    // Name-resolution map — full directory so every participant renders (not just assignable users).
    api.get('/tasks/assignable-users?all=true').then(res => setUsers(res.data || [])).catch(() => {});
    // Holidays block dates in the Reopen picker.
    getHolidays().then(res => setHolidayDates((res.data || []).map(h => h.holiday_date).filter(Boolean))).catch(() => setHolidayDates([]));
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);
  useEffect(() => { fetchTaxonomy(); }, [fetchTaxonomy]);
  useEffect(() => { setSelected(new Set()); }, [scope, statusFilter]);
  // Switching Recurring ↔ Delegated swaps the whole underlying list, so a status filter,
  // selection or expanded series carried over from the other tab would apply to rows that are
  // no longer there. The frequency filter goes too: it's only offered on the Recurring tab, so
  // a value left behind would silently empty the Delegated tab with no visible way to undo it.
  useEffect(() => {
    setStatusFilter('all');
    setFrequency('');
    setSelected(new Set());
    setExpandedGroups(new Set());
  }, [taskKind]);

  // ─── Real-time: refetch (debounced) when a task involving me changes elsewhere ───
  // The server (SSE) is the source of truth, so a debounced refetch keeps the current tab
  // correct without fragile client-side list merging (no dupes; tasks that left this
  // tab drop off). Keep fetchTasks in a ref so the stream isn't reopened on every filter change.
  const fetchTasksRef = useRef(fetchTasks);
  useEffect(() => { fetchTasksRef.current = fetchTasks; }, [fetchTasks]);
  const currentUserId = user?._id || user?.id;
  useEffect(() => {
    let debounce = null;
    const TOASTS = {
      task_created: 'New task assigned',
      task_assigned: 'New task assigned',
      task_completed: 'A task was completed',
      task_deleted: 'A task was removed',
    };
    // The verification hand-off is directional: only the assigner is asked to verify, and only
    // the assignee is told their task came back for rework. Toasting either event to everyone
    // on the task (watchers, the other side) would be noise, so these are addressed explicitly.
    const directedToast = (type, data) => {
      const isAssigner = data?.assigned_by && String(data.assigned_by) === String(currentUserId);
      const isAssignee = (data?.assigned_to || []).some(id => String(id) === String(currentUserId));
      if (type === 'task_verification_requested' && isAssigner) return 'A task is awaiting your verification';
      if (type === 'task_verification_rejected' && isAssignee) return 'A task was sent back to you for rework';
      return null;
    };
    const cleanup = openTaskEventStream((type, data) => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => fetchTasksRef.current?.(), 300);
      // Don't toast the user for their own action (they already see the optimistic update).
      const isSelf = data?.actor_id && currentUserId && String(data.actor_id) === String(currentUserId);
      if (isSelf) return;
      const message = TOASTS[type] || directedToast(type, data);
      if (message) showSuccess(message);
    });
    return () => { if (debounce) clearTimeout(debounce); cleanup(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUserId]);

  // Counts for the Recurring / Delegated tabs themselves. Recurring is counted in SERIES (one
  // per recurring_group_id), not occurrences, so "Recurring — 3" matches the 3 rows the tab
  // actually renders once the series are collapsed.
  const kindCounts = useMemo(() => {
    const seriesKeys = new Set();
    let onetime = 0;
    tasks.forEach(t => {
      if (isRecurringTask(t)) seriesKeys.add(t.recurringGroupId || t.id);
      else onetime += 1;
    });
    return { recurring: seriesKeys.size, onetime };
  }, [tasks]);

  // Everything below the tabs — summary cards, status tabs, the list — works off the active
  // kind's slice, so the numbers always describe what's on screen.
  const scopedTasks = useMemo(() => {
    if (!splitByRecurrence) return tasks;
    return tasks.filter(t => (taskKind === 'recurring' ? isRecurringTask(t) : !isRecurringTask(t)));
  }, [tasks, splitByRecurrence, taskKind]);

  const summary = useMemo(() => {
    const s = { totalTasks: scopedTasks.length, overdue: 0, pending: 0, accepted: 0, dependentOnOthers: 0, blocked: 0, inProgress: 0, verification: 0, completed: 0 };
    scopedTasks.forEach(t => {
      if (t.isOverdue) s.overdue += 1;
      // Every task lands on exactly one card — a status without a card of its own (Reopened,
      // Dependency Completed) counts as In Progress rather than being counted by nothing.
      const key = cardKeyForStatus(t.status);
      if (key in s) s[key] += 1;
    });
    return s;
  }, [scopedTasks]);

  const visibleTasks = useMemo(() => {
    let rows = scopedTasks;
    if (statusFilter === 'overdue') rows = rows.filter(t => t.isOverdue);
    else if (statusFilter !== 'all') {
      // Filter by what the card COUNTED, so a card showing 3 opens a list of 3.
      const statuses = statusesForCardKey(filterToCardKey(statusFilter));
      rows = rows.filter(t => (statuses.length ? statuses.includes(t.status) : t.status === statusFilter));
    }

    rows = [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'title') cmp = (a.title || '').localeCompare(b.title || '');
      else {
        const av = a[sortKey] ? new Date(a[sortKey]).getTime() : 0;
        const bv = b[sortKey] ? new Date(b[sortKey]).getTime() : 0;
        cmp = av - bv;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return rows;
  }, [scopedTasks, statusFilter, sortKey, sortDir]);

  // Collapses same-series occurrences (see groupTasksByRecurrence) into one row each,
  // preserving visibleTasks' sort order via the first-seen occurrence in each group.
  const groupedRows = useMemo(() => groupTasksByRecurrence(visibleTasks), [visibleTasks]);

  // Client-side paging over the GROUPED rows, so a recurring series counts as the one row it
  // renders as. currentPage is clamped rather than stored back, so deleting the last row on
  // page 3 falls back to page 2 instead of showing an empty table.
  const totalPages = Math.max(1, Math.ceil(groupedRows.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pagedRows = useMemo(
    () => groupedRows.slice(pageStart, pageStart + PAGE_SIZE),
    [groupedRows, pageStart],
  );

  // Any change that reshapes the list starts it again from page 1.
  useEffect(() => { setPage(1); }, [taskKind, statusFilter, scope, search, period, assignedTo, category, tag, frequency, sortKey, sortDir]);

  const toggleGroupExpand = (key) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const toggleGroupSelect = (group) => {
    const ids = group.items.map(t => t.id);
    const allSelected = ids.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      ids.forEach(id => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  };

  const clearFilters = () => {
    setPeriod('all_time'); setStartDate(''); setEndDate('');
    setAssignedTo(''); setCategory(''); setTag(''); setFrequency(''); setSearch('');
    setStatusFilter('all');
  };

  const hasActiveFilters = period !== 'all_time' || assignedTo || category || tag || frequency || search || statusFilter !== 'all';

  const handleRestore = async (task) => {
    setOpenMenuId(null);
    try {
      await restoreTask(task.id);
      showSuccess('Task restored');
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to restore task');
    }
  };

  // In-Loop member (a watcher who is neither the assigner nor a doer): read-only observer, so
  // every status control is frozen for them. Mirrors isPureWatcher in TaskDetailsModal; the
  // backend rejects their status writes too (only admin/creator/assignee may update).
  const isWatcherOnly = (t) => !t.isCreator
    && !(t.assignedTo || []).includes(currentUserId)
    && (t.watchers || []).includes(currentUserId);

  // Dependency doer: the task was handed to them via "Dependent on Other". They hold ONLY the
  // dependency, so their options are limited to Complete / Dependent on Other (see statusConfig).
  const isDependencyDoer = (t) => !!t.dependencyDoerId && t.dependencyDoerId === currentUserId;
  // The assignee who raised the dependency still owns the task, but can't move it until the doer
  // resolves it — their control stays visible at "Dependent on Other" but frozen.
  const isAwaitingDependency = (t) => !!t.dependencyDoerId
    && t.dependencyDoerId !== currentUserId
    && (t.assignedTo || []).includes(currentUserId);
  // Why a row's status control is frozen, or null when it's live.
  const frozenReason = (t) => {
    if (isWatcherOnly(t)) return "Read-only — In-Loop members can't change the task status";
    if (isAwaitingDependency(t)) return 'Waiting on the dependency doer to complete their part';
    return null;
  };

  // Dependent on Other / Blocked need a Doer Name + Reason first, and Reopen needs a NEW
  // deadline + a mandatory reason — both open a modal; every other status applies immediately.
  const handleStatusChange = (task, status) => {
    if (frozenReason(task)) return;
    if (REASON_REQUIRED_STATUSES.includes(status)) {
      setReasonTarget({ task, status });
      return;
    }
    if (status === 'in_progress_reopened') {
      setReopenTarget(task);
      return;
    }
    doStatusUpdate(task, status);
  };

  // Reopen (assigner, from Pending Verification): set the new deadline first, then flip the
  // status back to the assignee. The reason lands in both the deadline-revision history and
  // the status history — same flow as TaskDetailsModal.
  const handleReopenWithDeadline = async (iso, remark) => {
    const task = reopenTarget;
    setReopenTarget(null);
    if (!task) return;
    setCompleting(prev => new Set(prev).add(task.id));
    try {
      await reviseTaskDeadline(task.id, iso, remark);
      await updateTaskStatus(task.id, 'in_progress_reopened', remark);
      showSuccess('Task reopened — sent back to the assignee for rework');
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to reopen the task');
    } finally {
      setCompleting(prev => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const doStatusUpdate = async (task, status, { reason, doerName, doerId } = {}) => {
    if (completing.has(task.id)) return; // guard against double-click / duplicate requests
    const prevStatus = task.status;
    // Optimistic: reflect the new status immediately, mark in-flight.
    setCompleting(prev => new Set(prev).add(task.id));
    setTasks(ts => ts.map(t => (t.id === task.id ? { ...t, status } : t)));
    if (reasonTarget) setSavingReason(true);
    try {
      await updateTaskStatus(task.id, status, reason, doerName, doerId);
      setReasonTarget(null);
      fetchTasks(); // reconcile with server (also picked up via SSE for other users)
    } catch (err) {
      // Revert optimistic change on failure.
      setTasks(ts => ts.map(t => (t.id === task.id ? { ...t, status: prevStatus } : t)));
      showError(err.response?.data?.detail || 'Failed to update status');
    } finally {
      setSavingReason(false);
      setCompleting(prev => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected(prev => (prev.size === visibleTasks.length ? new Set() : new Set(visibleTasks.map(t => t.id))));
  };

  const handleBulkAction = async () => {
    const ids = Array.from(selected);
    try {
      if (scope === 'deleted') {
        await Promise.all(ids.map(id => restoreTask(id)));
        showSuccess(`Restored ${ids.length} task(s)`);
      } else {
        await Promise.all(ids.map(id => softDeleteTask(id)));
        showSuccess(`Deleted ${ids.length} task(s)`);
      }
      setSelected(new Set());
      fetchTasks();
    } catch (err) {
      showError(err.response?.data?.detail || 'Bulk action failed');
    }
  };

  // Clicking a sortable column header: same column flips direction, a new column starts
  // ascending. Keeps the toolbar's sort dropdown and the table headers on one piece of state.
  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('asc'); }
  };

  // Row actions: View only. Editing and deleting live inside the details modal — the list
  // payload carries no reminders / checklist / attachments, so acting on a task straight from
  // a row risks operating on a partial copy of it. Restore is the exception and stays, because
  // it is the Deleted Tasks page's only action; without it a deleted task can't be recovered.
  // Both cases are a single action, so RowActionsMenu renders them as a plain button.
  const rowActions = (task) => (scope === 'deleted'
    ? [{ label: 'Restore Task', icon: RotateCcw, onClick: () => handleRestore(task) }]
    : [{ label: 'View', icon: Eye, onClick: () => setDetailsTaskId(task.id) }]);

  // The table's Status cell, shared by a series' parent row and its expanded occurrence rows.
  // Shared by the table rows and the grid cards, so both views apply exactly the same
  // rules about who may act and on what.
  const renderStatusCell = (task) => {
    const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
    if (scope === 'deleted') return <StatusControl cfg={cfg} />;
    // A reporting manager is a verifier for their reports' tasks — treat them like the
    // assigner so they see Complete / Approve, not "Request for Verification".
    const rowIsAssigner = task.isCreator || isAdmin || task.isReportingManager;
    const rowIsDoerSide = scope === 'my' && !rowIsAssigner;
    // In-Loop observer, or an assignee waiting on a dependency doer: frozen.
    const rowFrozenReason = frozenReason(task);
    if (rowFrozenReason) return <StatusControl cfg={cfg} title={rowFrozenReason} frozen />;
    // Submitted for verification → the assigner's call, so read-only here.
    if (rowIsDoerSide && task.status === 'verification') return <StatusControl cfg={cfg} />;
    // The assigner's side of verification: Approve or Reopen, nothing else.
    if (task.status === 'verification') {
      return (
        <StatusControl cfg={cfg} value={task.status} disabled={completing.has(task.id)}
          onChange={(v) => handleStatusChange(task, v)}
          options={[[task.status, cfg.label, true], ...VERIFICATION_ACTIONS]} />
      );
    }
    const rowIsDependencyDoer = isDependencyDoer(task);
    return (
      <StatusControl cfg={cfg} value={task.status} disabled={completing.has(task.id)}
        onChange={(v) => handleStatusChange(task, v)}
        options={statusOptions(task.status, { isDependencyDoer: rowIsDependencyDoer })
          .map(st => [st, statusOptionLabel(st, { verificationRequired: task.verificationRequired, isAssigner: rowIsAssigner, isDependencyDoer: rowIsDependencyDoer, currentStatus: task.status })])} />
    );
  };

  // Who the row is "with" — the assigner on my/subscribed lists, the assignees on delegated.
  // A dependency doer is ADDED to the assignee list when a task is handed on (the real assignee
  // stays there, and still owns it), so listing everyone read as though the task had two
  // assignees. They are named on their own line instead — see dependencyNoteOf.
  const counterpartOf = (task) => (scope === 'delegated'
    ? ((task.assignedTo || []).filter(id => id !== task.dependencyDoerId)
        .map(id => userMap[id] || id).join(', ') || 'Myself')
    : (userMap[task.assignedBy] || 'Someone'));

  // The person the task is currently waiting on, for the line under the assignee. Only on the
  // delegated list, where the cell shows assignees at all.
  const dependencyNoteOf = (task) => (scope === 'delegated' && task.dependencyDoerId
    ? `Dependent on Other: ${userMap[task.dependencyDoerId] || 'Unknown'}`
    : null);

  // Only the Recurring tab gets the series detail line — on a one-time delegation there's no
  // series to summarise, and every row would just read "One Time".
  const showRecurrenceDetail = splitByRecurrence && taskKind === 'recurring';
  // Fixed columns + the Progress column the Recurring tab adds. Used by the expanded-series
  // row, which spans the whole table.
  const tableColSpan = showRecurrenceDetail ? 11 : 10;

  return (
    <div className="space-y-5 pb-24" onClick={() => openMenuId && setOpenMenuId(null)}>
      {!embedded && (
        <>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
              <ListChecks size={20} />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">{heading}</h1>
              <p className="text-[12px] text-[var(--text-muted)] font-bold">{subheading}</p>
            </div>
          </div>

          {/* ─── Recurring vs one-time delegation split ─── */}
          {splitByRecurrence && (
            <TaskKindTabs value={taskKind} onChange={setTaskKind} counts={kindCounts} scope={scope} />
          )}

          {/* ─── Toolbar ─── */}
          <div className="flex flex-wrap items-center gap-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-3">
            {allowCreate && (
              <button onClick={() => { setEditingTask(null); setModalOpen(true); }}
                className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
                <CirclePlus size={15} /> Assign Task
              </button>
            )}

            <DateRangeFilter variant="dropdown" period={period} onPeriodChange={setPeriod} startDate={startDate} endDate={endDate}
              onCustomChange={(field, value) => (field === 'startDate' ? setStartDate(value) : setEndDate(value))} />

            <button onClick={() => setFiltersOpen(o => !o)}
              className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${filtersOpen ? 'bg-[var(--accent-indigo)] text-white border border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)] hover:text-[var(--text-main)]'}`}>
              <FilterIcon size={14} /> Filters
              <ChevronDown size={13} className={`transition-transform ${filtersOpen ? 'rotate-180' : ''}`} />
            </button>

            <div className="relative flex-1 min-w-[200px]">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search eg: task name..."
                className="w-full pl-10 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <button onClick={fetchTasks} title="Refresh" className="p-2.5 rounded-full bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo-border)] transition-all">
              <RefreshCw size={15} />
            </button>

            {/* Export follows the active tab — the file is named for what's actually in it. */}
            <button onClick={() => exportTasksToCsv(visibleTasks, userMap,
              `${heading.toLowerCase().replace(/\s+/g, '-')}${splitByRecurrence ? (taskKind === 'recurring' ? '-recurring' : '-delegated') : ''}.csv`)}
              title="Export to CSV"
              className="p-2.5 rounded-full bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo-border)] transition-all">
              <Download size={15} />
            </button>

            {/* "List View" is the table — the reference calls the dense row layout the list and
                keeps the card layout behind the grid icon beside it. */}
            <div className="flex items-center gap-1.5">
              <button onClick={() => setViewMode('table')} title="List view"
                className={`flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${viewMode === 'table' ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                <ListIcon size={14} /> List View
              </button>
              <button onClick={() => setViewMode('list')} title="Card view"
                className={`p-2.5 rounded-xl transition-all ${viewMode === 'list' ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                <LayoutGrid size={15} />
              </button>
            </div>

            <SelectField value={sortKey} onChange={setSortKey}
              options={SORT_OPTIONS.map(o => ({ id: o.key, name: o.label }))} />
            <button onClick={() => setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))}
              title={`Sort ${sortDir === 'asc' ? 'ascending' : 'descending'} — click to flip`}
              className="p-2.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
              <ArrowUpDown size={15} />
            </button>
          </div>

          {filtersOpen && (
            <div className="flex flex-wrap items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
              <SelectField value={assignedTo} onChange={setAssignedTo}
                options={[{ id: '', name: 'Assigned To' },
                          ...users.map(u => ({ id: u._id, name: u.full_name || u.email }))]} />
              <SelectField value={category} onChange={setCategory}
                options={[{ id: '', name: 'Category' }, ...categories.map(c => ({ id: c, name: c }))]} />
              <SelectField value={tag} onChange={setTag}
                options={[{ id: '', name: 'Tag' }, ...tagOptions.map(t => ({ id: t, name: t }))]} />
              {/* The Delegated tab IS "Does not repeat", so a frequency filter there can only
                  ever empty the list — it's offered as a narrowing filter on the Recurring
                  tab only, and drops the "Does not repeat" option there for the same reason. */}
              {(!splitByRecurrence || taskKind === 'recurring') && (
                <SelectField value={frequency} onChange={setFrequency}
                  options={[{ id: '', name: 'Frequency' },
                            ...(splitByRecurrence
                              ? ['Daily', 'Weekly', 'Monthly', 'Yearly']
                              : ['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly']
                            ).map(f => ({ id: f, name: f }))]} />
              )}
              {hasActiveFilters && (
                <button onClick={clearFilters} className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)]">
                  <X size={13} /> Clear
                </button>
              )}
            </div>
          )}
        </>
      )}

      {/* The cards are now the filter control too — clicking one drives the same statusFilter
          as the tab strip below (click again to clear). */}
      <StatusSummaryCards cardOrder={LIST_CARD_ORDER} summary={summary}
        activeKey={filterToCardKey(statusFilter)}
        onSelect={(key) => setStatusFilter(cardKeyToFilter(key))} />

      {/* ─── Bulk action bar ─── */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-xl px-4 py-2.5">
          <span className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-wider">{selected.size} selected</span>
          <button onClick={handleBulkAction} className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest">
            {scope === 'deleted' ? <><RotateCcw size={12} /> Restore</> : <><Trash2 size={12} /> Delete</>}
          </button>
        </div>
      )}

      {/* ─── List ─── */}
      {loading ? (
        // Skeleton rows rather than a "Loading tasks..." block, so the page doesn't collapse
        // and jump back to full height on every refetch (the SSE stream refetches often).
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl px-4 py-3.5 animate-pulse">
              <span className="w-9 h-9 rounded-full bg-[var(--input-bg)] shrink-0" />
              <span className="flex-1 min-w-0 space-y-2">
                <span className="block h-2.5 rounded-full bg-[var(--input-bg)]" style={{ width: `${55 + ((i * 9) % 30)}%` }} />
                <span className="block h-2 rounded-full bg-[var(--input-bg)] w-1/4" />
              </span>
              <span className="w-24 h-6 rounded-full bg-[var(--input-bg)] shrink-0" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">{error}</div>
      ) : visibleTasks.length === 0 ? (
        <div className="p-16 flex flex-col items-center justify-center text-center text-[var(--text-muted)] bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">
          {showRecurrenceDetail ? <Repeat size={40} className="mb-3 opacity-30" />
            : splitByRecurrence ? <Forward size={40} className="mb-3 opacity-30" />
            : <ListChecks size={40} className="mb-3 opacity-30" />}
          <p className="text-[12px] font-bold">
            {splitByRecurrence
              ? (showRecurrenceDetail ? 'No recurring tasks here.' : 'No one-time tasks delegated to you.')
              : (emptyMessage || 'No tasks found.')}
          </p>
          {splitByRecurrence && showRecurrenceDetail && (
            <p className="text-[11px] font-bold opacity-70 mt-1 max-w-xs">
              Tasks created with a Daily, Weekly, Monthly or Yearly repeat appear here.
            </p>
          )}
          {hasActiveFilters && (
            <button onClick={clearFilters}
              className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)]">
              <X size={12} /> Clear filters
            </button>
          )}
        </div>
      ) : viewMode === 'table' ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[1080px]">
            <thead>
              <tr className="bg-[var(--input-bg)] border-b border-[var(--border)]">
                <th className="px-4 py-3 w-10">
                  <input type="checkbox" title="Select all"
                    checked={visibleTasks.length > 0 && selected.size === visibleTasks.length}
                    onChange={toggleSelectAll} />
                </th>
                <SortableTh label="#" sortKey={null} />
                <SortableTh label="Task Name" sortKey="title" activeKey={sortKey} dir={sortDir} onSort={handleSort} />
                <SortableTh label="Category" sortKey={null} />
                {showRecurrenceDetail && <SortableTh label="Progress" sortKey={null} />}
                <SortableTh label={scope === 'delegated' ? 'Assigned To' : 'Assigned By'} sortKey={null} />
                <SortableTh label="Priority" sortKey={null} />
                <SortableTh label="Status" sortKey={null} />
                {/* Created before due: a task is raised, then it falls due, so the dates read
                    left to right in the order they happen. */}
                <SortableTh label="Created On" sortKey="createdAt" activeKey={sortKey} dir={sortDir} onSort={handleSort} />
                {/* The Recurring tab's cell below this header shows the CHECKLIST's end date
                    (seriesEnd), not a per-occurrence due date — "Due Date" would misdescribe it,
                    so the header follows the same tab-based switch as the cell. */}
                <SortableTh label={showRecurrenceDetail ? 'End Date' : 'Due Date'} sortKey="end" activeKey={sortKey} dir={sortDir} onSort={handleSort} />
                <SortableTh label="Actions" sortKey={null} align="right" />
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((group, idx) => {
                const task = group.primary;
                const isSeries = group.items.length > 1;
                const isExpanded = expandedGroups.has(group.key);
                const seriesInfo = showRecurrenceDetail ? summarizeSeries(group) : null;
                return (
                  <React.Fragment key={group.key}>
                    <tr className={`border-b border-[var(--border)] transition-colors ${isExpanded ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                      <td className="px-4 py-3">
                        <input type="checkbox" checked={isSeries ? group.items.every(t => selected.has(t.id)) : selected.has(task.id)}
                          onChange={() => (isSeries ? toggleGroupSelect(group) : toggleSelect(task.id))} />
                      </td>
                      <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{pageStart + idx + 1}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button type="button" onClick={() => setDetailsTaskId(task.id)}
                            className="text-left text-[13px] font-bold text-[var(--text-main)] hover:text-[var(--accent-indigo)] transition-colors truncate max-w-[240px]">
                            {task.title}
                          </button>
                          {/* The ×N badge is the expander: a series is one row until you open it,
                              then every occurrence is listed underneath and tracked on its own. */}
                          {isSeries && (
                            <button type="button" onClick={() => toggleGroupExpand(group.key)}
                              title={isExpanded ? 'Hide occurrences' : `Show all ${group.items.length} occurrences`}
                              className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)] shrink-0 hover:bg-[var(--accent-indigo)] hover:text-white transition-colors">
                              <Repeat size={10} /> ×{group.items.length}
                              <ChevronDown size={11} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                            </button>
                          )}
                        </div>
                        {/* The repeat rule sits under the title rather than in its own column, so
                            the Recurring tab keeps Category and only adds one column. Progress is
                            skipped here (showProgress=false) — the table already has its own
                            Progress column — but the series' overdue count, next occurrence, and
                            end date only lived on the card/grid view until now, so a list-view
                            user had no way to see when a series runs out without opening it. */}
                        <div className="flex items-center gap-2 mt-0.5">
                          {!seriesInfo && task.isOverdue && <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest">Overdue</span>}
                          {seriesInfo ? (
                            <RecurrenceDetail task={task} series={seriesInfo} showProgress={false} showNextDue={false} showEnds={false} />
                          ) : null}
                        </div>
                      </td>
                      <td className="px-4 py-3"><CategoryPill name={task.category} /></td>
                      {seriesInfo && (
                        <td className="px-4 py-3">
                          <span className="flex items-center gap-1.5">
                            <span className="w-16 h-1.5 rounded-full overflow-hidden bg-[var(--input-bg)] border border-[var(--border)]">
                              <span className="block h-full rounded-full"
                                style={{ width: `${seriesInfo.percent}%`, background: seriesInfo.done === seriesInfo.total ? 'var(--accent-green)' : seriesInfo.overdue ? 'var(--accent-red)' : 'var(--accent-indigo)' }} />
                            </span>
                            <span className="text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{seriesInfo.done}/{seriesInfo.total}</span>
                          </span>
                        </td>
                      )}
                      <td className="px-4 py-3"><AssigneeCell name={counterpartOf(task)} note={dependencyNoteOf(task)} /></td>
                      <td className="px-4 py-3"><PriorityPill priority={task.priority} /></td>
                      <td className="px-4 py-3">{renderStatusCell(task)}</td>
                      <td className="px-4 py-3"><DateCell value={task.createdAt} /></td>
                      {/* Recurring tab: this row stands for the whole series, so "Due Date"
                          shows when the CHECKLIST itself ends (seriesEnd), not just the one
                          occurrence happening to be primary right now. Delegated (one-time)
                          tasks are unaffected — they keep their own real deadline. */}
                      <td className="px-4 py-3">
                        <DateCell
                          value={seriesInfo ? seriesInfo.seriesEnd : task.end}
                          overdue={seriesInfo ? false : task.isOverdue}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <RowActionsMenu
                          open={openMenuId === group.key}
                          onToggle={() => setOpenMenuId(openMenuId === group.key ? null : group.key)}
                          onClose={() => setOpenMenuId(null)}
                          items={rowActions(task)} />
                      </td>
                    </tr>

                    {/* Expanded series. Title, category, assignee and priority are identical on
                        every occurrence — repeating them as full table rows buried the two things
                        that actually differ, so this lists only the day and its status. */}
                    {isSeries && isExpanded && (
                      <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                        <td colSpan={tableColSpan} className="px-4 py-3">
                          <div className="ml-6 rounded-2xl border border-[var(--accent-indigo-border)] bg-[var(--bg-card)] overflow-hidden">
                            <div className="flex items-center justify-between gap-3 px-4 py-2 bg-[var(--accent-indigo-bg)] border-b border-[var(--accent-indigo-border)]">
                              <span className="text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">
                                {group.items.length} occurrences · {group.items.filter(t => t.status === 'completed').length} done
                              </span>
                              <button type="button" onClick={() => toggleGroupSelect(group)}
                                className="text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] hover:underline">
                                Select all
                              </button>
                            </div>
                            <div className="divide-y divide-[var(--border)]">
                              {group.items.map((child, childIdx) => {
                                const done = child.status === 'completed';
                                // The number badge carries the state, so the row needs no extra
                                // status colour to be scannable top to bottom.
                                const badgeTone = done
                                  ? { bg: 'var(--accent-green-bg)', color: 'var(--accent-green)', border: 'var(--accent-green-border)' }
                                  : child.isOverdue
                                    ? { bg: 'var(--accent-red-bg)', color: 'var(--accent-red)', border: 'var(--accent-red-border)' }
                                    : { bg: 'var(--input-bg)', color: 'var(--text-muted)', border: 'var(--border)' };
                                return (
                                  <div key={child.id} className="flex items-center gap-3 px-4 py-2 hover:bg-[var(--input-bg)] transition-colors">
                                    <input type="checkbox" className="shrink-0"
                                      checked={selected.has(child.id)} onChange={() => toggleSelect(child.id)} />
                                    <span className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-black shrink-0"
                                      style={{ background: badgeTone.bg, color: badgeTone.color, border: `1px solid ${badgeTone.border}` }}>
                                      {done ? <Check size={12} /> : childIdx + 1}
                                    </span>
                                    <button type="button" onClick={() => setDetailsTaskId(child.id)}
                                      className={`text-[12px] font-bold whitespace-nowrap transition-colors hover:text-[var(--accent-indigo)] ${child.isOverdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
                                      {formatOccurrenceDate(child.end || child.start)}
                                    </button>
                                    {child.isOverdue && !done && (
                                      <span className="text-[9px] font-black text-[var(--accent-red)] uppercase tracking-widest shrink-0">Overdue</span>
                                    )}
                                    <span className="flex-1" />
                                    {renderStatusCell(child)}
                                    <button type="button" onClick={() => setDetailsTaskId(child.id)} title="View details"
                                      className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--input-bg)] shrink-0">
                                      <Eye size={14} />
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <label className="flex items-center gap-2 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest cursor-pointer">
              <input type="checkbox" checked={visibleTasks.length > 0 && selected.size === visibleTasks.length} onChange={toggleSelectAll} /> Select All
            </label>
            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">
              {groupedRows.length} {showRecurrenceDetail ? 'series' : (groupedRows.length === 1 ? 'task' : 'tasks')}
            </span>
          </div>

          {/* A real grid — the whole point of the grid toggle. `items-start` keeps each card
              at its natural height so an expanded series doesn't stretch its whole row. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3 items-start">
            {pagedRows.map(group => {
              const task = group.primary;
              const isSeries = group.items.length > 1;
              return (
                <TaskCard
                  key={group.key}
                  task={task}
                  group={group}
                  scope={scope}
                  userMap={userMap}
                  series={showRecurrenceDetail ? summarizeSeries(group) : null}
                  checked={isSeries ? group.items.every(t => selected.has(t.id)) : selected.has(task.id)}
                  onToggleSelect={() => (isSeries ? toggleGroupSelect(group) : toggleSelect(task.id))}
                  onOpenDetails={() => setDetailsTaskId(task.id)}
                  statusCell={renderStatusCell(task)}
                  isExpanded={expandedGroups.has(group.key)}
                  onToggleExpand={() => toggleGroupExpand(group.key)}
                  onOccurrenceOpen={(id) => setDetailsTaskId(id)}
                  actions={(
                    <RowActionsMenu
                      open={openMenuId === group.key}
                      onToggle={() => setOpenMenuId(openMenuId === group.key ? null : group.key)}
                      onClose={() => setOpenMenuId(null)}
                      items={rowActions(task)} />
                  )}
                />
              );
            })}
          </div>
        </div>
      )}
      {/* ─── Pager ─── */}
      {!loading && !error && groupedRows.length > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl px-4 py-2.5">
          <span className="text-[11px] font-black text-[var(--text-muted)]">
            {pageStart + 1}-{Math.min(pageStart + PAGE_SIZE, groupedRows.length)} of {groupedRows.length}
          </span>
          <div className="flex items-center gap-1.5">
            <button onClick={() => setPage(Math.max(1, currentPage - 1))} disabled={currentPage <= 1} title="Previous page"
              className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] enabled:hover:text-[var(--accent-indigo)] enabled:hover:border-[var(--accent-indigo-border)] disabled:opacity-35 disabled:cursor-not-allowed transition-all">
              <ChevronLeft size={14} />
            </button>
            <span className="px-2 text-[11px] font-black text-[var(--text-muted)]">{currentPage} / {totalPages}</span>
            <button onClick={() => setPage(Math.min(totalPages, currentPage + 1))} disabled={currentPage >= totalPages} title="Next page"
              className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] enabled:hover:text-[var(--accent-indigo)] enabled:hover:border-[var(--accent-indigo-border)] disabled:opacity-35 disabled:cursor-not-allowed transition-all">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}

      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} task={editingTask} onSaved={fetchTasks}
        categories={categories} tags={tagOptions} onTaxonomyChanged={fetchTaxonomy} groupId={groupId} />
      <TaskDetailsModal isOpen={!!detailsTaskId} taskId={detailsTaskId} scope={scope} onClose={() => setDetailsTaskId(null)} onChanged={fetchTasks}
        onEdit={(t) => { setDetailsTaskId(null); setEditingTask(t); setModalOpen(true); }} />
      {/* Reopen (from Pending Verification): a NEW deadline + an optional reason, then the task
          goes back to the assignee for rework. */}
      <MiniDatePicker
        isOpen={!!reopenTarget}
        onClose={() => setReopenTarget(null)}
        value={reopenTarget?.end}
        title="Reopen Task"
        onApply={(iso, remark) => handleReopenWithDeadline(iso, remark)}
        holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
        disablePast
        remarkLabel="Reason for Reopening"
      />
      {/* Doer Name + Reason capture for Dependent on Other / Blocked (from either list dropdown). */}
      <StatusReasonModal
        isOpen={!!reasonTarget}
        status={reasonTarget?.status}
        users={users}
        // Same rule as the details modal: a task can't be made to wait on someone already on it.
        excludeIds={[...(reasonTarget?.task?.assignedTo || []), reasonTarget?.task?.dependencyDoerId].filter(Boolean)}
        saving={savingReason}
        onClose={() => setReasonTarget(null)}
        onSubmit={({ reason, doerName, doerId }) => doStatusUpdate(reasonTarget.task, reasonTarget.status, { reason, doerName, doerId })}
      />
    </div>
  );
};

export default TaskListView;
