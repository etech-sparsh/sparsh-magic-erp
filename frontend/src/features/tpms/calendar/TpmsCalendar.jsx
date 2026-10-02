import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CalendarDays, Plus, RefreshCw, Inbox, X, Clock, Building2, Tag, Users2,
  UserCog, CheckCircle2, Paperclip, Upload, FileText, RotateCcw, Trash2, Pencil, Pin,
  Download, FileSpreadsheet, AlertTriangle, Ban,
} from 'lucide-react';
import { DashboardHero, HeroButton, KpiTile, FilterSelect } from '../common/dashboardKit';
import ScheduleCalendarModal from '../../../components/calendar/ScheduleCalendarModal';
import { useAuth } from '../../../context/AuthContext';
import { useNotification } from '../../../context/NotificationContext';
import {
  getSchedules, getActivities, getDepartments, deleteSchedule, updateSchedule, markLearnerDone, confirmCompletion,
  requestReschedule, getRescheduleRequests, decideRescheduleRequest,
  getScheduleUploads, uploadScheduleFile,
  exportTpms, importTpms, saveExportedWorkbook,
} from '../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   TPMS ▸ Calendar — the module's core screen.

   Month grid of scheduled activities with the full lifecycle inline:
     • doers  → Mark Done / Request Reschedule / upload proof
     • staff  → Confirm Complete, approve or reject reschedule requests
     • admin  → edit / delete

   Completion is deliberately TWO-STEP: a doer marking done only sets
   `learner_done`; internal staff must confirm before the activity counts as
   Completed. See backend tpms_lifecycle_service.py.
   ───────────────────────────────────────────────────────────── */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const STATUSES = ['Scheduled', 'Rescheduled', 'Cancelled', 'Completed', 'Lapsed'];

// Recurrence options for the client-side recurrence filter. Values match the
// labels the catalogue/scheduler uses on `activity_meta.recurrence` (or a flat
// `recurrence` field). If events carry no recurrence data the filter no-ops.
const RECURRENCES = ['One-time', 'Daily', 'Weekly', 'Monthly', 'Periodically'];

// "Scheduled by" filter options — value matches the event's scheduled_by field.
const SCHED_BY_OPTIONS = [
  { id: '', name: 'All Scheduled by' },
  { id: 'internal', name: 'OM/Staff' },
  { id: 'client', name: 'Client' },
];

// TPMS status → ERP accent tokens. No hex literals: dark mode comes free.
const TONE = {
  Scheduled:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  Rescheduled: { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  Completed:   { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Cancelled:   { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Lapsed:      { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};
const toneOf = (s) => TONE[s] || TONE.Scheduled;

// "Scheduled by" tone tokens — internal (OM/Staff) reads indigo, client reads amber.
const SCHED_BY = {
  internal: { label: 'OM/Staff', c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  client:   { label: 'Client',   c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};

// Small badge naming who put the activity on the calendar; hidden when unknown.
const SchedByBadge = ({ by, name }) => {
  const t = SCHED_BY[by];
  if (!t) return null;
  return (
    <span title={name ? `Scheduled by ${name}` : `Scheduled by ${t.label}`}
      className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      {t.label}
    </span>
  );
};

const ymd = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

const Badge = ({ status }) => {
  const t = toneOf(status);
  return (
    <span className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      {status}
    </span>
  );
};

// Small pin marking activities the current user created. Cosmetic only.
const MinePin = () => (
  <Pin size={11} title="Created by you" aria-label="Created by you"
    className="shrink-0" style={{ color: 'var(--accent-indigo)' }} />
);

// Legend mapping each status to the exact color dot the pills use (reuses TONE).
const StatusLegend = () => (
  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5 border-t border-[var(--border)]">
    <span className="text-[10.5px] font-black text-[var(--text-muted)] uppercase tracking-wide">Legend</span>
    {STATUSES.map((s) => {
      const t = toneOf(s);
      return (
        <span key={s} className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
          <span className="w-2.5 h-2.5 rounded-full border"
            style={{ background: t.c, borderColor: t.bd }} />
          {s}
        </span>
      );
    })}
    <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
      <MinePin /> Created by you
    </span>
  </div>
);

/** Proof-of-work panel, shown only for activities the catalogue flags upload_required. */
const UploadBlock = ({ eventId, canUpload }) => {
  const [files, setFiles] = useState(null);
  const [busy, setBusy] = useState(false);
  const { showError, showSuccess } = useNotification();

  const load = useCallback(async () => {
    try {
      const { data } = await getScheduleUploads(eventId);
      setFiles(data.uploads || []);
    } catch { setFiles([]); }
  }, [eventId]);

  useEffect(() => { load(); }, [load]);

  const onPick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) return showError('Max file size 25 MB');
    setBusy(true);
    try {
      await uploadScheduleFile(eventId, file);
      showSuccess('Uploaded');
      await load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  };

  return (
    <div className="mt-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--input-bg)] p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11.5px] font-black text-[var(--text-main)] inline-flex items-center gap-1.5">
          <Paperclip size={12} /> Proof of work
        </span>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full border"
          style={files?.length
            ? { color: 'var(--accent-green)', background: 'var(--accent-green-bg)', borderColor: 'var(--accent-green-border)' }
            : { color: 'var(--accent-red)', background: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          {files === null ? '…' : files.length ? `${files.length} file(s)` : 'Pending'}
        </span>
      </div>
      {files?.length > 0 && (
        <div className="space-y-1 mb-2">
          {files.map((f) => (
            <a key={f._id} href={f.url} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--accent-indigo)] hover:underline">
              <FileText size={12} /> {f.file_name}
              <span className="text-[10px] text-[var(--text-muted)] font-medium">
                {f.uploaded_by_name}{f.uploaded_at ? ` · ${String(f.uploaded_at).slice(0, 10)}` : ''}
              </span>
            </a>
          ))}
        </div>
      )}
      {canUpload && (
        <label className="inline-flex items-center gap-1.5 text-[11.5px] font-black text-[var(--accent-indigo)] cursor-pointer hover:underline">
          <Upload size={12} /> {busy ? 'Uploading…' : 'Upload file'}
          <input type="file" className="hidden" onChange={onPick} disabled={busy} />
        </label>
      )}
    </div>
  );
};

const TpmsCalendar = () => {
  const { user } = useAuth();
  const { showError, showSuccess } = useNotification();

  const role = (user?.role || '').toLowerCase();
  const isClient = role === 'clientadmin' || role === 'clientuser';
  const isAdmin = role === 'superadmin' || role === 'admin';
  const isStaffSide = !isClient;

  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);   // 1-12
  const [events, setEvents] = useState([]);
  const [activities, setActivities] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);

  const [fActivity, setFActivity] = useState('');
  const [fStatus, setFStatus] = useState('');
  const [fCompany, setFCompany] = useState('');       // company_id (as string) or ''
  const [fRecurrence, setFRecurrence] = useState(''); // one of RECURRENCES or ''
  const [fSchedBy, setFSchedBy] = useState('');       // 'internal' | 'client' | ''

  const [openDay, setOpenDay] = useState(null);
  const [showModal, setShowModal] = useState(false);
  // The day an empty cell was clicked on, pre-filled into the Schedule modal's Plan Date.
  // Cleared whenever the modal closes and by the header Schedule button, so that one still
  // opens a blank form.
  const [scheduleDate, setScheduleDate] = useState('');
  const [editEvent, setEditEvent] = useState(null);   // event being edited (null = create)
  const [requests, setRequests] = useState([]);
  const [showRequests, setShowRequests] = useState(false);
  const [rr, setRr] = useState(null);        // reschedule-request form target

  // ── Bulk export / import ──
  // The file input is hidden and driven by the Import button: a styled <label> would work too,
  // but a ref lets the input be RESET after every pick, so choosing the same file twice in a
  // row still fires onChange (the browser suppresses it otherwise).
  const fileRef = useRef(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [report, setReport] = useState(null);   // import result, shown in a dialog
  // Confirmation for an action that notifies people or cannot be undone. One state object
  // drives one dialog, so Cancel, Delete and Reject all read the same way instead of each
  // reaching for window.confirm — which renders as a bare "localhost:5173 says" box that
  // carries none of the page's wording and cannot say what the action will actually do.
  // Shape: { title, lead, detail, confirmLabel, keepLabel, withNote, notePlaceholder, run }
  const [confirmBox, setConfirmBox] = useState(null);
  const [confirmNote, setConfirmNote] = useState('');
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getSchedules({ year, month });
      setEvents(data.events || []);
    } catch (e) {
      showError(e.response?.data?.detail || 'Failed to load calendar');
    } finally {
      setLoading(false);
    }
  }, [year, month, showError]);

  const loadRequests = useCallback(async () => {
    if (!isStaffSide) return;
    try {
      const { data } = await getRescheduleRequests('Pending');
      setRequests(data.requests || []);
    } catch { /* non-fatal — the badge just stays empty */ }
  }, [isStaffSide]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRequests(); }, [loadRequests]);
  useEffect(() => {
    getActivities().then(({ data }) => setActivities(data.activities || [])).catch(() => {});
    getDepartments().then(({ data }) => setDepartments(data.items || [])).catch(() => {});
  }, []);

  // Download the whole of TPMS as one workbook. The Schedules sheet is the fillable one:
  // add rows with a blank "Schedule ID", then bring the file back through Import.
  const handleExport = useCallback(async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await exportTpms();
      saveExportedWorkbook(res);
      const rows = res.headers?.['x-tpms-export-rows'];
      showSuccess(`Exported${rows ? ` ${rows} rows` : ''} — fill the Schedules sheet, then Import.`);
    } catch (e) {
      // An error response to a blob request arrives as a Blob, not JSON, so the usual
      // e.response.data.detail is unreadable without decoding it first.
      let detail = 'Export failed';
      try { detail = JSON.parse(await e.response?.data?.text?.() || '{}').detail || detail; } catch { /* keep default */ }
      showError(detail);
    } finally {
      setExporting(false);
    }
  }, [exporting, showError, showSuccess]);

  const handleImport = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';                 // let the same file be picked again later
    if (!file || importing) return;
    setImporting(true);
    try {
      const { data } = await importTpms(file);
      setReport(data);
      const created = data?.schedules?.created || 0;
      if (created) showSuccess(`${created} activity${created === 1 ? '' : 's'} scheduled from the workbook.`);
      await load();                          // new activities should appear without a refresh
    } catch (e) {
      showError(e.response?.data?.detail || 'Import failed');
    } finally {
      setImporting(false);
    }
  }, [importing, load, showError, showSuccess]);

  // Recurrence lives on activity_meta.recurrence (preferred) or a flat recurrence
  // field; may be absent on older/sparse events.
  const recurrenceOf = (e) => e?.activity_meta?.recurrence || e?.recurrence || '';

  // Company dropdown is derived from the current month's loaded events — keyed by
  // company_id (falling back to company name) so labels stay stable.
  const companyOptions = useMemo(() => {
    const map = new Map();
    events.forEach((e) => {
      const key = e.company_id ?? e.company;
      if (key == null || key === '') return;
      const id = String(key);
      if (!map.has(id)) map.set(id, e.company || id);
    });
    return [...map.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [events]);

  const filtered = useMemo(() => events.filter((e) =>
    (!fActivity || e.activity === fActivity)
    && (!fStatus || e.status === fStatus)
    && (!fCompany || String(e.company_id ?? e.company) === fCompany)
    // Recurrence filters client-side; events with no recurrence value always pass
    // so the control degrades to a no-op when the data isn't present.
    && (!fRecurrence || !recurrenceOf(e) || recurrenceOf(e) === fRecurrence)
    // Scheduled-by filters client-side; events missing scheduled_by only show under "All".
    && (!fSchedBy || e.scheduled_by === fSchedBy)),
  [events, fActivity, fStatus, fCompany, fRecurrence, fSchedBy]);

  const clearFilters = () => {
    setFActivity(''); setFStatus(''); setFCompany(''); setFRecurrence(''); setFSchedBy('');
  };

  const byDate = useMemo(() => {
    const map = {};
    filtered.forEach((e) => { (map[e.date] ||= []).push(e); });
    return map;
  }, [filtered]);

  const stats = useMemo(() => {
    const s = { total: filtered.length };
    STATUSES.forEach((k) => { s[k] = filtered.filter((e) => e.status === k).length; });
    return s;
  }, [filtered]);

  const changeMonth = (delta) => {
    let m = month + delta, y = year;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    setMonth(m); setYear(y);
  };

  // Seeding the note here (rather than in the dialog) keeps a previous rejection's reason
  // from reappearing in the next one.
  const askConfirm = (box) => { setConfirmNote(''); setConfirmBox(box); };

  const runConfirm = async () => {
    if (!confirmBox || confirmBusy) return;
    setConfirmBusy(true);
    try {
      // `run` goes through act(), which reports its own failures as a toast — so the dialog
      // closes either way and never strands the user in front of a spinner.
      await confirmBox.run(confirmNote.trim());
    } finally {
      setConfirmBusy(false);
      setConfirmBox(null);
      setConfirmNote('');
    }
  };

  const act = async (fn, okMsg) => {
    try {
      await fn();
      showSuccess(okMsg);
      setOpenDay(null);
      await load();
      await loadRequests();
    } catch (e) {
      showError(e.response?.data?.detail || 'Action failed');
    }
  };

  const submitReschedule = async () => {
    if (!rr?.new_date) return showError('Choose a new date');
    if (!rr?.reason?.trim()) return showError('A reason is required to request a reschedule');
    await act(() => requestReschedule(rr.id, {
      new_date: rr.new_date, new_time: rr.new_time, reason: rr.reason,
    }), 'Request sent — staff will review it');
    setRr(null);
  };

  /* ── grid ── */
  const firstDow = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const todayStr = ymd(today.getFullYear(), today.getMonth() + 1, today.getDate());

  const kpis = [
    { value: stats.total,        label: 'Total',       sub: 'This month',   tone: 'plain',  icon: CalendarDays },
    { value: stats.Scheduled,    label: 'Scheduled',   sub: 'Upcoming',     tone: 'indigo', icon: Clock },
    { value: stats.Rescheduled,  label: 'Rescheduled', sub: 'Moved',        tone: 'yellow', icon: RotateCcw },
    { value: stats.Completed,    label: 'Completed',   sub: 'Done',         tone: 'green',  icon: CheckCircle2 },
    { value: stats.Cancelled,    label: 'Cancelled',   sub: 'Dropped',      tone: 'red',    icon: X },
    { value: stats.Lapsed,       label: 'Lapsed',      sub: 'Auto-lapsed',  tone: 'plain',  icon: Clock },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={CalendarDays} title="Calendar" subtitle="Scheduled activities, reminders & completion">
        {isStaffSide && (
          <HeroButton icon={Inbox} onClick={() => setShowRequests(true)}>
            Requests{requests.length ? ` (${requests.length})` : ''}
          </HeroButton>
        )}
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        {/* Bulk load. Admin-only to match the backend, which refuses both endpoints for any
            other role — showing the buttons to someone who can only get a 403 is worse than
            not showing them. Export first: the workbook it produces IS the import template. */}
        {isAdmin && (
          <>
            <HeroButton icon={Download} onClick={handleExport}>
              {exporting ? 'Exporting…' : 'Export'}
            </HeroButton>
            <HeroButton icon={FileSpreadsheet} onClick={() => fileRef.current?.click()}>
              {importing ? 'Importing…' : 'Import'}
            </HeroButton>
            <input ref={fileRef} type="file" accept=".xlsx,.xlsm" className="hidden"
              onChange={handleImport} />
          </>
        )}
        {/* Clears any day carried over from a cell click, so the header button keeps opening a
            blank form with no date pre-selected. */}
        <HeroButton icon={Plus} onClick={() => { setScheduleDate(''); setShowModal(true); }}>Schedule</HeroButton>
      </DashboardHero>

      <div className="grid grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        {/* month nav + filters */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <button onClick={() => changeMonth(-1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]">‹</button>
            <span className="text-[14px] font-black text-[var(--text-main)] min-w-[150px] text-center">
              {MONTHS[month - 1]} {year}
            </span>
            <button onClick={() => changeMonth(1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]">›</button>
          </div>
          <div className="flex-1" />
          <FilterSelect value={fActivity} onChange={setFActivity}
            options={[{ id: '', name: 'All Activities' }, ...activities.map((a) => ({ id: a.name, name: a.name }))]} />
          <FilterSelect value={fStatus} onChange={setFStatus}
            options={[{ id: '', name: 'All Status' }, ...STATUSES.map((s) => ({ id: s, name: s }))]} />
          <FilterSelect value={fCompany} onChange={setFCompany}
            options={[{ id: '', name: 'All Companies' }, ...companyOptions]} />
          <FilterSelect value={fRecurrence} onChange={setFRecurrence}
            options={[{ id: '', name: 'All Recurrence' }, ...RECURRENCES.map((r) => ({ id: r, name: r }))]} />
          <FilterSelect value={fSchedBy} onChange={setFSchedBy} options={SCHED_BY_OPTIONS} />
          {(fActivity || fStatus || fCompany || fRecurrence || fSchedBy) && (
            <button onClick={clearFilters}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]">
              <RotateCcw size={13} /> Clear
            </button>
          )}
        </div>

        <div className="grid grid-cols-7 gap-px bg-[var(--border)]">
          {DOW.map((d) => (
            <div key={d} className="bg-[var(--table-header-bg)] px-2 py-2 text-center text-[11px] font-black text-[var(--text-muted)]">{d}</div>
          ))}
          {Array.from({ length: firstDow }).map((_, i) => <div key={`e${i}`} className="bg-[var(--bg-card)] min-h-[104px]" />)}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const ds = ymd(year, month, day);
            const evs = byDate[ds] || [];
            const isToday = ds === todayStr;
            // A day that already has activities keeps its existing behaviour — the drawer
            // listing them, from which each one opens its own details/edit view. An EMPTY day
            // opens the Schedule modal pre-filled with that date.
            return (
              <button key={ds} title={evs.length ? undefined : `Schedule an activity on ${ds}`}
                onClick={() => {
                  if (evs.length) { setOpenDay(ds); return; }
                  setScheduleDate(ds);
                  setShowModal(true);
                }}
                className="bg-[var(--bg-card)] min-h-[104px] p-1.5 text-left align-top hover:bg-[var(--table-hover)] transition-colors cursor-pointer">
                <div className={`text-[11.5px] font-black mb-1 ${isToday
                  ? 'inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--accent-indigo)] text-white'
                  : 'text-[var(--text-muted)]'}`}>{day}</div>
                <div className="space-y-1">
                  {evs.slice(0, 3).map((e) => {
                    const t = toneOf(e.status);
                    return (
                      <div key={e.id} title={`${e.title} — ${e.status}${e.mine ? ' · Created by you' : ''}`}
                        className="truncate text-[10px] font-bold px-1.5 py-0.5 rounded border"
                        style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
                        {e.mine ? '📌 ' : ''}{e.time ? `${e.time} ` : ''}{e.title}
                      </div>
                    );
                  })}
                  {evs.length > 3 && (
                    <div className="text-[10px] font-bold text-[var(--text-muted)] px-1.5">+{evs.length - 3} more</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
        <StatusLegend />
        {loading && <div className="px-5 py-3 text-[12px] font-bold text-[var(--text-muted)]">Loading…</div>}
      </div>

      {/* ── Day drawer ── */}
      {openDay && (
        <Overlay onClose={() => setOpenDay(null)} title={`Activities on ${openDay}`}>
          {/* Schedule another activity on this same day. */}
          <button type="button"
            onClick={() => { setScheduleDate(openDay); setShowModal(true); setOpenDay(null); }}
            className="w-full mb-3 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[12.5px] font-black hover:bg-[var(--accent-indigo)] hover:text-white transition-all">
            <Plus size={15} /> Schedule an activity on this day
          </button>
          {(byDate[openDay] || []).map((e) => {
            const canAct = !['Completed', 'Cancelled', 'Lapsed'].includes(e.status);
            return (
              <div key={e.id} className="rounded-xl border border-[var(--border)] p-3 mb-2.5">
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h4 className="text-[13.5px] font-black text-[var(--text-main)] inline-flex items-center gap-1.5">
                    {e.mine && <MinePin />}{e.title}
                  </h4>
                  <div className="flex items-center gap-1.5">
                    {e.reschedule_count > 0 && (
                      <span className="text-[10px] font-bold text-[var(--text-muted)]">↻ {e.reschedule_count}</span>
                    )}
                    <SchedByBadge by={e.scheduled_by} name={e.scheduled_by_name} />
                    <Badge status={e.status} />
                  </div>
                </div>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold space-y-0.5">
                  {e.time && <div className="flex items-center gap-1.5"><Clock size={11} /> {e.time}</div>}
                  {e.activity && <div className="flex items-center gap-1.5"><Tag size={11} /> {e.activity}</div>}
                  {e.company && <div className="flex items-center gap-1.5"><Building2 size={11} /> {e.company}</div>}
                  {!!e.departments?.length && <div className="flex items-center gap-1.5"><Users2 size={11} /> {e.departments.join(', ')}</div>}
                  {!!e.staff_ids?.length && <div className="flex items-center gap-1.5"><UserCog size={11} /> {e.staff_ids.length} staff assigned</div>}
                </div>

                {e.learner_done && e.status !== 'Completed' && (
                  <div className="mt-2 rounded-lg px-2.5 py-1.5 text-[11px] font-bold"
                    style={{ color: 'var(--accent-green)', background: 'var(--accent-green-bg)' }}>
                    ✅ Marked done by the doer — awaiting staff confirmation
                  </div>
                )}

                {e.upload_required && <UploadBlock eventId={e.id} canUpload={canAct} />}

                <div className="flex flex-wrap gap-2 mt-3">
                  {/* Edit — Admin/Staff may edit any activity; a learner only their own. */}
                  {(isStaffSide || e.mine) && (
                    <Btn ghost onClick={() => { setEditEvent(e); setOpenDay(null); }}>
                      <Pencil size={12} /> Edit
                    </Btn>
                  )}
                  {isClient && canAct && !e.learner_done && (
                    <>
                      <Btn onClick={() => act(() => markLearnerDone(e.id), 'Marked done — staff will confirm')}>✅ Mark Done</Btn>
                      <Btn ghost onClick={() => setRr({ id: e.id, title: e.title, new_date: e.date, new_time: e.time, reason: '' })}>
                        🔄 Request Reschedule
                      </Btn>
                    </>
                  )}
                  {isStaffSide && e.learner_done && canAct && (
                    <Btn onClick={() => act(() => confirmCompletion(e.id), 'Completed')}>✔ Confirm Complete</Btn>
                  )}
                  {isStaffSide && canAct && (
                    <Btn danger ghost onClick={() => askConfirm({
                      title: 'Cancel this activity?',
                      lead: e.title,
                      detail: 'Its pending reminders stop immediately, and both the doer and the staff '
                            + 'side are notified that it was cancelled. The activity stays on the '
                            + 'calendar marked Cancelled — it is not deleted.',
                      confirmLabel: 'Cancel Activity',
                      keepLabel: 'Keep it',
                      run: () => act(() => updateSchedule(e.id, { status: 'Cancelled' }), 'Activity cancelled'),
                    })}><Ban size={12} /> Cancel</Btn>
                  )}
                  {isAdmin && (
                    <Btn danger ghost onClick={() => askConfirm({
                      title: 'Delete this activity?',
                      lead: e.title,
                      detail: 'The activity and everything derived from it go with it — its pending '
                            + 'reminders, tracker rows and any form links already issued. Unlike '
                            + 'Cancel, this leaves no record on the calendar and cannot be undone.',
                      confirmLabel: 'Delete Activity',
                      keepLabel: 'Keep it',
                      run: () => act(() => deleteSchedule(e.id), 'Deleted'),
                    })}><Trash2 size={12} /> Delete</Btn>
                  )}
                </div>
              </div>
            );
          })}
        </Overlay>
      )}

      {/* ── Reschedule request (doer) ── */}
      {rr && (
        <Overlay onClose={() => setRr(null)} title="Request Reschedule" narrow>
          <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-3">{rr.title}</p>
          <Field label="New Date">
            <input type="date" value={rr.new_date} onChange={(e) => setRr({ ...rr, new_date: e.target.value })} className={inputCls} />
          </Field>
          <Field label="New Time">
            <input type="time" value={rr.new_time || ''} onChange={(e) => setRr({ ...rr, new_time: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Reason">
            <textarea rows={3} value={rr.reason} onChange={(e) => setRr({ ...rr, reason: e.target.value })}
              placeholder="Why reschedule?" className={inputCls} />
          </Field>
          <p className="text-[11px] text-[var(--text-muted)] font-semibold mb-3">
            Requests must be raised at least 12 hours before the activity. Staff will approve or reject.
          </p>
          <div className="flex justify-end gap-2">
            <Btn ghost onClick={() => setRr(null)}>Cancel</Btn>
            <Btn onClick={submitReschedule}>Send Request</Btn>
          </div>
        </Overlay>
      )}

      {/* ── Pending requests (staff) ── */}
      {showRequests && (
        <Overlay onClose={() => setShowRequests(false)} title="Reschedule Requests" narrow>
          {requests.length === 0
            ? <p className="text-[12.5px] font-bold text-[var(--text-muted)]">No pending requests.</p>
            : requests.map((r) => (
              <div key={r._id} className="rounded-xl border border-[var(--border)] p-3 mb-2.5">
                <h4 className="text-[13px] font-black text-[var(--text-main)]">{r.title || r.activity}</h4>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold mb-1.5">{r.activity} · {r.company_name}</div>
                <div className="text-[12px] font-bold text-[var(--text-main)]">
                  📅 {r.old_date} {r.old_time} → <span className="text-[var(--accent-indigo)]">{r.new_date} {r.new_time}</span>
                </div>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold mt-1">
                  🙋 {r.requested_by_name}{r.reason ? ` — ${r.reason}` : ''}
                </div>
                <div className="flex gap-2 mt-2.5">
                  <Btn onClick={() => act(() => decideRescheduleRequest(r._id, true), 'Approved')}>✔ Approve</Btn>
                  {/* window.prompt was the worst of the three: an unstyled input whose text
                      is mailed to the requester, with no way to say so and no cancel that
                      reads as a cancel — dismissing it returned '' and rejected anyway. */}
                  <Btn danger ghost onClick={() => askConfirm({
                    title: 'Reject this reschedule request?',
                    lead: r.title || r.activity,
                    detail: `The activity stays on ${r.old_date}${r.old_time ? ` ${r.old_time}` : ''} and `
                          + `${r.requested_by_name || 'the requester'} is notified. A reason is optional, `
                          + 'but whatever you write here is included in what they receive.',
                    confirmLabel: 'Reject Request',
                    keepLabel: 'Go Back',
                    withNote: true,
                    notePlaceholder: 'Why is this being rejected?',
                    run: (note) => act(() => decideRescheduleRequest(r._id, false, note), 'Rejected'),
                  })}>✕ Reject</Btn>
                </div>
              </div>
            ))}
        </Overlay>
      )}

      {/* ── Confirmation ──
          Rendered last, and therefore above the day list and the requests overlay it is
          opened from: Overlay pins every dialog at z-50, so paint order is what decides.
          It also lives outside those blocks deliberately — act() closes the day list on
          success, and a dialog nested inside it would unmount mid-action. */}
      {confirmBox && (
        <Overlay narrow title={confirmBox.title}
          onClose={() => { if (!confirmBusy) setConfirmBox(null); }}>
          {confirmBox.lead && (
            <p className="text-[12.5px] font-black text-[var(--text-main)] mb-2">{confirmBox.lead}</p>
          )}
          <p className="text-[12px] font-semibold text-[var(--text-muted)] mb-3 leading-relaxed">
            {confirmBox.detail}
          </p>
          {confirmBox.withNote && (
            <Field label="Reason">
              <textarea rows={3} value={confirmNote} onChange={(ev) => setConfirmNote(ev.target.value)}
                placeholder={confirmBox.notePlaceholder} className={inputCls} />
            </Field>
          )}
          <div className="flex justify-end gap-2">
            <Btn ghost disabled={confirmBusy} onClick={() => setConfirmBox(null)}>
              {confirmBox.keepLabel || 'Go Back'}
            </Btn>
            <Btn danger disabled={confirmBusy} onClick={runConfirm}>
              {confirmBusy ? 'Working…' : confirmBox.confirmLabel}
            </Btn>
          </div>
        </Overlay>
      )}

      {/* ── Import result ──
          Shown after every import, success or not. A bulk load that silently half-worked is
          the worst outcome, so per-row failures are listed with their sheet line number rather
          than collapsed into a single toast. */}
      {report && (
        <Overlay onClose={() => setReport(null)} title="Import Complete" narrow>
          <div className="grid grid-cols-3 gap-2 mb-4">
            {[
              { label: 'Scheduled', value: report.schedules?.created || 0, tone: 'var(--accent-green)' },
              { label: 'Skipped',   value: report.schedules?.skipped || 0, tone: 'var(--text-muted)' },
              { label: 'Failed',    value: report.schedules?.failed || 0,  tone: 'var(--accent-red)' },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-[var(--border)] px-3 py-2.5 text-center">
                <div className="text-[19px] font-black tabular-nums" style={{ color: s.tone }}>{s.value}</div>
                <div className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">{s.label}</div>
              </div>
            ))}
          </div>

          {!!report.schedules?.events && (
            <p className="text-[11.5px] font-semibold text-[var(--text-muted)] mb-3">
              {report.schedules.events} calendar occurrence{report.schedules.events === 1 ? '' : 's'} created
              (recurrence expanded). Reminders, schedule mails and form links were sent exactly as
              they are for an activity scheduled by hand.
            </p>
          )}

          {!!report.schedules?.errors?.length && (
            <div className="rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] p-3 mb-3">
              <div className="flex items-center gap-1.5 text-[11.5px] font-black text-[var(--accent-red)] mb-1.5">
                <AlertTriangle size={13} /> Rows that could not be scheduled
              </div>
              <ul className="space-y-1">
                {report.schedules.errors.map((msg) => (
                  <li key={msg} className="text-[11.5px] font-semibold text-[var(--text-main)]">{msg}</li>
                ))}
              </ul>
            </div>
          )}

          {(() => {
            const restored = Object.entries(report.collections || {})
              .filter(([, c]) => c.inserted > 0);
            return restored.length ? (
              <div className="rounded-xl border border-[var(--border)] p-3">
                <div className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-1.5">
                  Other sheets restored
                </div>
                {restored.map(([name, c]) => (
                  <div key={name} className="flex justify-between text-[11.5px] font-semibold text-[var(--text-main)]">
                    <span>{name}</span><span className="tabular-nums">+{c.inserted}</span>
                  </div>
                ))}
              </div>
            ) : null;
          })()}

          <div className="flex justify-end mt-4">
            <Btn onClick={() => setReport(null)}>Done</Btn>
          </div>
        </Overlay>
      )}

      <ScheduleCalendarModal
        mode="tpms"
        event={editEvent}
        initialDate={scheduleDate}
        activities={activities}
        departments={departments}
        isOpen={showModal || !!editEvent}
        onClose={() => { setShowModal(false); setEditEvent(null); setScheduleDate(''); }}
        onSaved={() => { load(); setShowModal(false); setEditEvent(null); setScheduleDate(''); }}
      />
    </div>
  );
};

/* ── small local primitives ── */
const inputCls = 'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]';

const Field = ({ label, children }) => (
  <div className="mb-3">
    <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1">{label}</label>
    {children}
  </div>
);

const Btn = ({ children, onClick, ghost, danger, disabled }) => (
  <button onClick={onClick} disabled={disabled}
    className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[11.5px] font-black transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none ${
      ghost
        ? `border ${danger ? 'border-[var(--accent-red-border)] text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]'
                          : 'border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--table-hover)]'}`
        // Solid red for the confirm button of a destructive dialog. Every pre-existing
        // `danger` call site also passes `ghost`, so this branch is additional, not a
        // restyle of anything that already renders.
        : danger
          ? 'bg-[var(--accent-red)] text-white hover:opacity-90'
          : 'bg-[var(--accent-indigo)] text-white hover:opacity-90'}`}>
    {children}
  </button>
);

const Overlay = ({ title, children, onClose, narrow }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()}
      className={`w-full ${narrow ? 'max-w-md' : 'max-w-2xl'} rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden`}>
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border)]">
        <h3 className="text-[14px] font-black text-[var(--text-main)]">{title}</h3>
        <button onClick={onClose} className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)]"><X size={17} /></button>
      </div>
      <div className="px-5 py-4 max-h-[65vh] overflow-y-auto">{children}</div>
    </div>
  </div>
);

export default TpmsCalendar;
