import React, { useEffect, useMemo, useRef, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  X, CalendarClock, Bell, Building2, Activity as ActivityIcon, Users2,
  UserCog, ClipboardList, RefreshCw, Save, Check, Search, ChevronDown,
} from 'lucide-react';
import api from '../../services/api';
import {
  checkScheduleConflict as checkTpmsConflict,
  createSchedule as createTpmsSchedule,
  updateSchedule as updateTpmsSchedule,
  uploadScheduleFile,
} from '../../services/tpmsApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import ReminderModal from './ReminderModal';

/**
 * Schedule Calendar modal — schedule an activity for a company, assign the internal
 * staff (SMOps) driving it and the company-side doers (by department), set a recurrence
 * and reminders. Saves through POST /calendar/events so it reuses the existing
 * recurrence engine, the on-save notification email, and the reminder scheduler.
 */

// No backend Activity catalogue exists yet — this is the editable source of truth.
const ACTIVITIES = [
  'Org Structure Update',
  'DRM & KPI data available',
  'Calendar Discipline',
  'WRM',
  'Monthly Management Review (MMR)',
  'One pager Memo',
  'Action Closure Review',
  'Accountability & Ownership Rating',
  'Culture Rating',
  'RRO',
  'Implementation Update Feedback',
  'Team Engagement Index',
  'Customer Satisfaction Index',
  'Organization Result Matrix',
];

// Client-side departments the doers are grouped by.
const DEPARTMENTS = ['HOD', 'MD', 'HR', 'IMPLEMENTOR'];

// These four are governance ROLES (see tpms.TPMS_DEPARTMENTS, seeded with is_governance_role).
// A company user carries theirs in `governance_role`, with `department` as the fallback for
// un-migrated users — `department` is free text from the user import and may legitimately hold
// a real org department ("Sales", "Operations") instead. Reading only `department` left the
// doer pool empty for every migrated user. Same precedence the backend uses:
// forms._user_department, and the HOD lookup in tpms.py.
const govRole = (u) => ((u?.governance_role || u?.department || '') + '').trim().toUpperCase();
const inDept = (u, dept) => govRole(u) === (dept || '').trim().toUpperCase();

// Recurrence label → backend `repeat` value (see calendar_event.py / _next_occurrence).
const RECURRENCE = [
  { label: 'One-time', repeat: 'Does not repeat' },
  { label: 'Daily',    repeat: 'Daily' },
  { label: 'Weekly',   repeat: 'Weekly' },
  { label: 'Monthly',  repeat: 'Monthly' },
  { label: 'Yearly',   repeat: 'Annually' },
];

// TPMS uses its own recurrence set — the backend generator (tpms_schedule_service.
// build_occurrences) implements One-time / Daily / Weekly / Monthly / Periodically-by-weekday.
const TPMS_RECURRENCE = ['One-time', 'Daily', 'Weekly', 'Monthly', 'Periodically'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const emptyForm = () => ({
  title: '',
  time: '',
  activity: '',
  companyId: '',
  recurrence: 'One-time',
  planDate: '',
  planEndDate: '',
  weekdays: [],
  staffIds: [],
  departments: [],
  doerIds: [],
  comment: '',
  reminders: [],
});

const uid = (u) => String(u?._id || u?.id || '');
const displayName = (u) => u?.full_name || [u?.first_name, u?.last_name].filter(Boolean).join(' ') || u?.email || 'Unknown';

/** Searchable single-select: a value button that opens a filterable option list. */
const SearchableSelect = ({ options, value, onChange, placeholder }) => {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const selected = options.find((o) => o.id === value);
  const ql = q.trim().toLowerCase();
  const filtered = options.filter((o) => o.label.toLowerCase().includes(ql));

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold outline-none focus:border-indigo-500 transition-all">
        <span className={selected ? 'text-gray-800 truncate' : 'text-gray-400'}>{selected ? selected.label : (placeholder || '— Select —')}</span>
        <ChevronDown size={15} className="text-gray-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full rounded-xl bg-white border border-gray-200 shadow-xl overflow-hidden">
          <div className="relative p-2 border-b border-gray-100">
            <Search size={13} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…"
              className="w-full pl-8 pr-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-[12px] font-semibold text-gray-800 outline-none focus:border-indigo-500" />
          </div>
          <div className="max-h-52 overflow-y-auto no-scrollbar py-1">
            {filtered.length === 0 && <div className="px-3 py-2 text-[11px] text-gray-400 font-medium">No matches.</div>}
            {filtered.map((o) => (
              <button key={o.id} type="button" onClick={() => { onChange(o.id); setOpen(false); setQ(''); }}
                className={`w-full flex items-center justify-between px-3 py-2 text-[12px] font-semibold hover:bg-gray-50 transition-all ${o.id === value ? 'text-indigo-600' : 'text-gray-700'}`}>
                <span className="truncate">{o.label}</span>
                {o.id === value && <Check size={14} className="text-indigo-600 shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/** Searchable multi-select: selected items as removable chips + a filterable dropdown. */
const SearchableMultiSelect = ({ options, selectedIds, onToggle, placeholder, disabled, accent = 'indigo' }) => {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  if (disabled) {
    return <div className="w-full px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-medium text-gray-400">{placeholder}</div>;
  }

  const selected = options.filter((o) => selectedIds.includes(o.id));
  const ql = q.trim().toLowerCase();
  const filtered = options.filter((o) => o.label.toLowerCase().includes(ql));
  const chipCls = accent === 'violet' ? 'bg-violet-600 border-violet-600' : 'bg-indigo-600 border-indigo-600';
  const checkCls = accent === 'violet' ? 'text-violet-600' : 'text-indigo-600';

  return (
    <div ref={ref} className="relative">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map((o) => (
            <span key={o.id} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold text-white border ${chipCls}`}>
              {o.label}
              <X size={11} className="cursor-pointer opacity-80 hover:opacity-100" onClick={() => onToggle(o.id)} />
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder={selected.length ? 'Add more…' : (placeholder || 'Search…')}
          className="w-full pl-9 pr-8 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold text-gray-800 outline-none focus:border-indigo-500 transition-all"
        />
        <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 cursor-pointer" onClick={() => setOpen((o) => !o)} />
      </div>
      {open && (
        <div className="absolute z-30 mt-1 w-full max-h-56 overflow-y-auto no-scrollbar rounded-xl bg-white border border-gray-200 shadow-xl py-1">
          {filtered.length === 0 && <div className="px-3 py-2 text-[11px] text-gray-400 font-medium">No matches.</div>}
          {filtered.map((o) => {
            const on = selectedIds.includes(o.id);
            return (
              <button key={o.id} type="button" onClick={() => onToggle(o.id)}
                className={`w-full flex items-center justify-between px-3 py-2 text-[12px] font-semibold hover:bg-gray-50 transition-all ${on ? checkCls : 'text-gray-700'}`}>
                <span className="truncate">{o.label}</span>
                {on && <Check size={14} className={checkCls} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

/**
 * @param {'erp'|'tpms'} mode  'erp' (default) posts to /calendar/events and keeps the
 *   existing behaviour untouched. 'tpms' posts to /tpms/schedules, uses the TPMS
 *   recurrence set, keeps doers and staff in separate fields, and runs the
 *   once-per-month conflict check before saving.
 */
// `initialDate` ("YYYY-MM-DD") seeds the Plan Date when the modal is opened for a NEW activity
// — used by the TPMS calendar so clicking an empty day opens this form already set to that day.
// Ignored in edit mode, where the date comes from the event being edited.
const ScheduleCalendarModal = ({ isOpen, onClose, onSaved, mode = 'erp', event = null, initialDate = '', activities = [], departments = [] }) => {
  const isTpms = mode === 'tpms';
  // Edit mode is TPMS-only: an `event` turns the create modal into an edit-in-place
  // form. Left null (or in ERP mode) the modal behaves exactly as before.
  const isEditing = isTpms && !!event;
  const [conflict, setConflict] = useState(null);   // {info, payload} — TPMS duplicate warning
  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();
  // Client-side users schedule only for their OWN company and don't assign internal staff.
  const isClient = ['clientadmin', 'clientuser'].includes(user?.role);

  // Prefer the live admin-managed masters passed in from the TPMS calendar; fall back to the
  // built-in lists so standalone/ERP use still works and an empty fetch never blanks the
  // pickers. Admin-added activities and custom departments now appear when scheduling.
  const activityOptions = (activities && activities.length)
    ? activities.map((a) => (typeof a === 'string' ? a : a.name)).filter(Boolean)
    : ACTIVITIES;
  const deptOptions = (departments && departments.length)
    ? departments.filter((d) => typeof d === 'string' || d.active !== false)
        .map((d) => (typeof d === 'string' ? d : d.name)).filter(Boolean)
    : DEPARTMENTS;

  const [form, setForm] = useState(emptyForm());
  const [uploadFile, setUploadFile] = useState(null);
  const selectedActivityMeta = (activities || []).find((a) => (typeof a === 'string' ? a : a.name) === form.activity);
  const uploadRequired = !!(selectedActivityMeta && typeof selectedActivityMeta === 'object' && selectedActivityMeta.upload_required);
  useEffect(() => { setUploadFile(null); }, [isOpen, form.activity]);

  const [companyName, setCompanyName] = useState('');
  const [companies, setCompanies] = useState([]);
  const [staff, setStaff] = useState([]);
  const [companyUsers, setCompanyUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [showReminders, setShowReminders] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  // On open: staff load all companies + the internal-staff picker; client users are
  // locked to their own company (no company list, no staff picker — both are staff-only).
  useEffect(() => {
    if (!isOpen) return;
    let base;
    if (isTpms && event) {
      // Edit mode — pre-fill from the existing event. Recurrence is NOT edited
      // per-occurrence, so it's forced to One-time and its controls are hidden.
      base = {
        ...emptyForm(),
        title: event.title || '',
        time: event.time || '',
        activity: event.activity || '',
        companyId: event.company_id != null && event.company_id !== '' ? String(event.company_id) : '',
        recurrence: 'One-time',
        planDate: event.date || '',
        departments: event.departments || [],
        doerIds: (event.member_ids || []).map(String),
        staffIds: (event.staff_ids || event.coach_ids || []).map(String),
        comment: event.comment || event.additional_details || '',
      };
    } else {
      base = emptyForm();
      if (isClient && user?.company_id) base.companyId = String(user.company_id);
      // Pre-fill the day the user clicked. Only the date is seeded — everything else stays
      // blank, so this is the same create form, just opened on the right day.
      if (initialDate) base.planDate = initialDate;
    }
    setForm(base);
    setCompanyUsers([]);
    setCompanyName('');
    let alive = true;
    (async () => {
      try {
        if (isClient) {
          if (user?.company_id) {
            const co = await api.get(`/companies/${user.company_id}`);
            if (alive) setCompanyName(co.data?.name || user?.company_name || 'Your Company');
          }
        } else {
          const [coRes, stRes] = await Promise.all([
            api.get('/companies'),
            api.get('/tasks/assignable-users'),
          ]);
          if (!alive) return;
          setCompanies(coRes.data || []);
          setStaff(stRes.data || []);
        }
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form data');
      }
    })();
    return () => { alive = false; };
  }, [isOpen, isClient, user, showError, isTpms, event, initialDate]);

  // Load the selected company's users (the doer pool).
  //
  // `isOpen` is a dependency, not just a guard: the open effect above clears companyUsers on
  // every open, but companyId is often UNCHANGED between opens (reopening the same activity,
  // or editing a second activity of the same company). Keyed on companyId alone this effect
  // would not re-run, so the list stayed permanently empty after the first close — the doer
  // dropdown showed "No matches." for every activity except the first one opened per page load.
  useEffect(() => {
    if (!isOpen) return;
    if (!form.companyId) { setCompanyUsers([]); return; }
    let alive = true;
    (async () => {
      setLoadingUsers(true);
      try {
        const res = await api.get(`/companies/${form.companyId}/users?active_only=true`);
        if (!alive) return;
        setCompanyUsers(res.data || []);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load company users');
      } finally {
        if (alive) setLoadingUsers(false);
      }
    })();
    return () => { alive = false; };
  }, [isOpen, form.companyId, showError]);

  /* TPMS is opt-in per company (companies.tpms_enabled, default false) and the API rejects a
     schedule aimed at a disabled one. Offer only what can actually be saved; the ERP calendar
     path has no such gate, so it keeps the full list. An event being edited keeps its own
     company visible even if TPMS was switched off afterwards. */
  const selectableCompanies = useMemo(() => {
    if (!isTpms) return companies;
    return companies.filter((c) => c.tpms_enabled || String(c._id || c.id) === form.companyId);
  }, [companies, isTpms, form.companyId]);

  // Doers available for the currently-selected departments (or all if none chosen).
  const doerPool = useMemo(() => {
    if (!form.departments.length) return companyUsers;
    return companyUsers.filter((u) => form.departments.some((d) => inDept(u, d)));
  }, [companyUsers, form.departments]);

  // How much of the VISIBLE pool is ticked — drives the counter and disables the bulk
  // buttons when they would be no-ops.
  const selectedInPool = useMemo(
    () => doerPool.filter((u) => form.doerIds.includes(uid(u))).length,
    [doerPool, form.doerIds],
  );
  const allPoolSelected = doerPool.length > 0 && selectedInPool === doerPool.length;

  /* Whether the Title is still the one we auto-filled from the Activity, rather than a name
     the user typed. Only an auto-filled title is rewritten when the Activity changes.

     This is what stops the mail from naming two different activities. Title is free text and
     is what every TPMS mail is HEADED with ("Scheduled - {{Title}}", "[LAPSED] {{Title}} ...")
     while the BODY comes from the template keyed on Activity. The old rule only seeded the
     title while it was empty, so picking "Action Closure Review" and then switching to
     "Accountability & Ownership Rating" left the first name in the title for good — and the
     recipient got a mail headed "Action Closure Review" whose content was the Accountability
     & Ownership template. A hand-written title ("WRM- KEPL") is still never touched. */
  const titleFollowsActivity = () => {
    const t = (form.title || '').trim();
    return !t || t === (form.activity || '').trim();
  };

  const toggleStaff = (id) => set({ staffIds: form.staffIds.includes(id) ? form.staffIds.filter((s) => s !== id) : [...form.staffIds, id] });
  const toggleDoer = (id) => set({ doerIds: form.doerIds.includes(id) ? form.doerIds.filter((s) => s !== id) : [...form.doerIds, id] });

  /* Bulk selection over the visible pool. Selecting a department deliberately does NOT
     pre-tick its people (that is what made every HOD a recipient by default) — picking them
     is an explicit act, which is what these two controls are for. */
  const poolIds = () => doerPool.map(uid);
  const selectAllDoers = () => set({ doerIds: [...new Set([...form.doerIds, ...poolIds()])] });
  const clearDoers = () => {
    const shown = new Set(poolIds());
    set({ doerIds: form.doerIds.filter((id) => !shown.has(id)) });
  };

  const toggleDept = (dept) => {
    const has = form.departments.includes(dept);
    const nextDepts = has ? form.departments.filter((d) => d !== dept) : [...form.departments, dept];
    const matchIds = companyUsers.filter((u) => inDept(u, dept)).map(uid);
    const nextDoers = has
      ? form.doerIds.filter((id) => !matchIds.includes(id))       // removing dept → drop its doers
      : form.doerIds;                                             // adding dept → filter pool, allow user to pick doers
    set({ departments: nextDepts, doerIds: nextDoers });
  };

  const buildTimes = () => {
    if (!form.time) {
      const startISO = new Date(`${form.planDate}T00:00:00`).toISOString();
      return { start: startISO, end: startISO, all_day: true };
    }
    const startDt = new Date(`${form.planDate}T${form.time}:00`);
    const endDt = new Date(startDt.getTime() + 60 * 60 * 1000);
    return { start: startDt.toISOString(), end: endDt.toISOString(), all_day: false };
  };

  /** TPMS payload — doers and internal staff stay in SEPARATE fields (the ERP path
   *  merges both into assigned_member_ids; TPMS needs them apart so escalation can tell
   *  the doer from the SMOps owner). */
  const tpmsPayload = () => ({
    title: form.title.trim(),
    activity: form.activity,
    company_id: form.companyId,
    company_name: isClient
      ? companyName
      : (companies.find((c) => String(c._id || c.id) === form.companyId)?.name || ''),
    plan_start: form.planDate,
    plan_end: form.recurrence === 'One-time' ? '' : form.planEndDate,
    event_time: form.time,
    recurrence: form.recurrence,
    weekdays: form.weekdays,
    departments: form.departments,
    member_ids: form.doerIds,
    staff_ids: form.staffIds,
    comment: form.comment,
    reminders: (form.reminders || []).map((r) => {
      // Preserve the user's granularity: pick the coarsest unit that divides evenly, so a
      // 30-minute reminder stays 30 MINS instead of rounding up to a whole hour.
      const mins = Math.max(1, r.offset_minutes || 0);
      const [value, unit] = mins % 1440 === 0 ? [mins / 1440, 'DAYS']
        : mins % 60 === 0 ? [mins / 60, 'HRS']
        : [mins, 'MINS'];
      return {
        channel: r.reminder_type === 'whatsapp' ? 'WhatsApp' : r.reminder_type === 'both' ? 'Both' : 'Email',
        type: 'offset',
        dir: r.timing_type || 'before',
        value,
        unit,
      };
    }),
  });

  const saveTpms = async (payload) => {
    setSaving(true);
    try {
      if (isEditing) {
        await updateTpmsSchedule(event.id, payload);
        if (uploadRequired && uploadFile) {
          try { await uploadScheduleFile(event.id, uploadFile); }
          catch { showError('Activity updated, but the file upload failed — attach it from the activity card.'); }
        }
        showSuccess('Activity updated.');
      } else {
        const res = await createTpmsSchedule(payload);
        const eventIds = res?.data?.event_ids || [];
        if (uploadRequired && uploadFile && eventIds.length) {
          try { await uploadScheduleFile(eventIds[0], uploadFile); }
          catch { showError('Activity scheduled, but the file upload failed — attach it from the activity card.'); }
        }
        showSuccess('Activity scheduled — reminders and mails are on their way.');
      }
      setUploadFile(null);
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || (isEditing ? 'Failed to update activity' : 'Failed to schedule activity'));
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    if (!form.title.trim()) return showError('Enter a title');
    if (!form.activity) return showError('Select an activity');
    if (!form.companyId) return showError('Select a company');
    if (!form.planDate) return showError('Pick a plan date');

    if (isTpms) {
      if (!form.departments.length) return showError('Select at least one Department');
      if (!form.doerIds.length) return showError('Select at least one Company Assigner (doer)');
      if (!isClient && !form.staffIds.length) return showError('Select at least one Staff Assigner');
      if (form.recurrence !== 'One-time') {
        if (!form.planEndDate) return showError('Select Plan end Date');
        if (form.planEndDate < form.planDate) return showError('Plan end must be after start');
        if (form.recurrence === 'Periodically' && !form.weekdays.length)
          return showError('Select at least one weekday');
      }
      const payload = tpmsPayload();
      // Editing an existing activity skips the duplicate/conflict check — that guard
      // is for brand-new schedules only.
      if (isEditing) return saveTpms(payload);
      // Advisory duplicate check for once-a-month activities — the user may proceed.
      try {
        const { data } = await checkTpmsConflict(payload);
        if (data?.conflict) return setConflict({ info: data, payload });
      } catch { /* check failed → fall through and save, matching the source */ }
      return saveTpms(payload);
    }

    const rec = RECURRENCE.find((r) => r.label === form.recurrence) || RECURRENCE[0];
    const { start, end, all_day } = buildTimes();
    const recurring = rec.repeat !== 'Does not repeat';
    let repeat_end_date = '';
    if (recurring) {
      const d = new Date(form.planDate);
      d.setFullYear(d.getFullYear() + 1);
      repeat_end_date = d.toISOString().slice(0, 10);
    }

    const assigned_member_ids = [...new Set([...form.staffIds, ...form.doerIds])];
    const reminders = (form.reminders || []).map((r) => ({ ...r, parent_type: 'event' }));

    // Snapshot names/company so any assignee can view details without extra lookups.
    const coName = isClient ? companyName : (companies.find((c) => String(c._id || c.id) === form.companyId)?.name || '');
    const smops = staff.filter((u) => form.staffIds.includes(uid(u))).map((u) => ({ id: uid(u), name: displayName(u) }));
    // `department` on the snapshot carries the governance role the doer was picked under, so it
    // stays consistent with the DEPARTMENTS filter rather than showing a blank or an org dept.
    const doers = companyUsers.filter((u) => form.doerIds.includes(uid(u))).map((u) => ({ id: uid(u), name: displayName(u), department: govRole(u) }));

    const payload = {
      title: form.title.trim(),
      type: 'event',
      activity: form.activity,
      company_id: form.companyId,
      company_name: coName,
      session_type: form.activity,
      start, end, all_day,
      status: 'schedule',
      category: 'General',
      repeat: rec.repeat,
      repeat_end_date,
      repeat_interval: 1,
      assigned_departments: form.departments,
      assigned_member_ids,
      additional_details: form.comment,
      reminders,
      activity_meta: { company_name: coName, departments: form.departments, smops, doers },
    };

    setSaving(true);
    try {
      await api.post('/calendar/events', payload);
      showSuccess('Schedule created — invites & reminders will be sent.');
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save schedule');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const Label = ({ children, req }) => (
    <label className="block text-[11px] font-black text-gray-500 uppercase tracking-wider mb-1.5">
      {children}{req && <span className="text-indigo-500"> *</span>}
    </label>
  );
  const field = 'w-full px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold text-gray-800 outline-none focus:border-indigo-500 transition-all';

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[250] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}
          className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative bg-white w-full max-w-2xl rounded-[28px] shadow-2xl overflow-hidden flex flex-col max-h-[92vh]" style={{ color: '#1a202c' }}>

          {/* Header */}
          <div className="px-6 py-5 flex items-center justify-between text-white bg-gradient-to-r from-indigo-600 to-violet-500">
            <div className="flex items-center gap-2.5">
              <CalendarClock size={20} />
              <h3 className="text-[15px] font-black tracking-tight">{isEditing ? 'Edit Activity' : 'Schedule Activity'}</h3>
            </div>
            <button onClick={onClose} className="p-1.5 hover:bg-white/20 rounded-full transition-all"><X size={20} /></button>
          </div>

          {/* Body */}
          <div className="p-6 overflow-y-auto no-scrollbar space-y-5">
            <div>
              <Label req>Title</Label>
              <input value={form.title} onChange={(e) => set({ title: e.target.value })} placeholder="Enter title" className={field} />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label>Time</Label>
                <input type="time" value={form.time} onChange={(e) => set({ time: e.target.value })} className={field} />
              </div>
              <div>
                <Label req><ActivityIcon size={11} className="inline mr-1" />Activity</Label>
                <SearchableSelect
                  options={activityOptions.map((a) => ({ id: a, label: a }))}
                  value={form.activity}
                  onChange={(a) => set({ activity: a, ...(titleFollowsActivity() ? { title: a } : {}) })}
                  placeholder="— Select —"
                />
              </div>
              <div>
                <Label req><Building2 size={11} className="inline mr-1" />Company Name</Label>
                {isClient ? (
                  <div className={`${field} truncate`}>{companyName || 'Your Company'}</div>
                ) : (
                  <SearchableSelect
                    options={selectableCompanies.map((c) => ({ id: String(c._id || c.id), label: c.name }))}
                    value={form.companyId}
                    onChange={(id) => set({ companyId: id, doerIds: [], departments: [] })}
                    placeholder="— Select —"
                  />
                )}
                {/* The backend refuses to schedule into a TPMS-disabled company, so the picker
                    must not offer one. When that leaves nothing to pick, say why — otherwise an
                    empty dropdown reads as a broken page. */}
                {isTpms && !isClient && companies.length > 0 && selectableCompanies.length === 0 && (
                  <p className="text-[11px] font-bold text-amber-600 mt-1.5 leading-snug">
                    No company has TPMS enabled yet. Turn TPMS on for a company from its
                    Company Details page, then schedule here.
                  </p>
                )}
              </div>
              {/* Recurrence is not editable per-occurrence — hidden entirely in edit mode. */}
              {!isEditing && (
                <div>
                  <Label req><RefreshCw size={11} className="inline mr-1" />Recurrence</Label>
                  <select value={form.recurrence} onChange={(e) => set({ recurrence: e.target.value })} className={field}>
                    {isTpms
                      ? TPMS_RECURRENCE.map((r) => <option key={r} value={r}>{r === 'Periodically' ? 'Periodically (specific weekdays)' : r}</option>)
                      : RECURRENCE.map((r) => <option key={r.label} value={r.label}>{r.label}</option>)}
                  </select>
                </div>
              )}
              <div>
                <Label req>{isTpms && form.recurrence !== 'One-time' ? 'Plan start Date' : 'Plan Date'}</Label>
                <input type="date" value={form.planDate} onChange={(e) => set({ planDate: e.target.value })} className={field} />
              </div>
              {isTpms && form.recurrence !== 'One-time' && (
                <div>
                  <Label req>Plan end Date</Label>
                  <input type="date" value={form.planEndDate} min={form.planDate}
                    onChange={(e) => set({ planEndDate: e.target.value })} className={field} />
                </div>
              )}
              {isTpms && form.recurrence === 'Periodically' && (
                <div className="sm:col-span-2">
                  <Label req>Weekdays</Label>
                  <div className="flex flex-wrap gap-2">
                    {WEEKDAYS.map((d, i) => {
                      const on = form.weekdays.includes(i);
                      return (
                        <button key={d} type="button"
                          onClick={() => set({ weekdays: on ? form.weekdays.filter((w) => w !== i) : [...form.weekdays, i] })}
                          className={`px-3 py-1.5 rounded-lg text-[11.5px] font-black border transition-all ${
                            on ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]'
                               : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--input-border)] hover:border-[var(--accent-indigo)]'}`}>
                          {d}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {!isClient && (
                <div>
                  <Label req><UserCog size={11} className="inline mr-1" />Staff Assigner (multi-select)</Label>
                  <SearchableMultiSelect
                    disabled={!form.companyId}
                    placeholder={!form.companyId ? 'Select a company first' : 'Search staff…'}
                    options={staff.map((u) => ({ id: uid(u), label: displayName(u) }))}
                    selectedIds={form.staffIds}
                    onToggle={toggleStaff}
                    accent="indigo"
                  />
                  <p className="text-[10px] text-gray-400 font-medium mt-1">Internal staff who will drive this activity.</p>
                </div>
              )}
            </div>

            {/* Departments */}
            <div>
              <Label req><Users2 size={11} className="inline mr-1" />Departments (multi-select)</Label>
              <div className="flex flex-wrap gap-2">
                {deptOptions.map((d) => {
                  const on = form.departments.includes(d);
                  return (
                    <button key={d} type="button" onClick={() => toggleDept(d)} disabled={!form.companyId}
                      className={`px-3.5 py-1.5 rounded-xl text-[11px] font-black border transition-all disabled:opacity-40 ${on ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-500 border-gray-200 hover:border-indigo-400'}`}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Company Assigners (doers) */}
            <div>
              <div className="flex items-end justify-between gap-3 mb-1.5">
                <Label>Company Assigners (doers) (multi-select)</Label>
                {doerPool.length > 0 && (
                  <div className="flex items-center gap-2 pb-1.5">
                    <span className="text-[10px] font-black text-gray-400 tabular-nums">
                      {selectedInPool} / {doerPool.length} selected
                    </span>
                    <button type="button" onClick={selectAllDoers} disabled={allPoolSelected}
                      className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-wide border border-indigo-200 text-indigo-600 bg-indigo-50 hover:bg-indigo-600 hover:text-white disabled:opacity-40 disabled:hover:bg-indigo-50 disabled:hover:text-indigo-600 transition-all">
                      Select all
                    </button>
                    <button type="button" onClick={clearDoers} disabled={selectedInPool === 0}
                      className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-wide border border-gray-200 text-gray-500 bg-white hover:border-gray-400 disabled:opacity-40 transition-all">
                      Clear
                    </button>
                  </div>
                )}
              </div>
              <div className="max-h-56 overflow-y-auto rounded-xl border border-gray-200 divide-y divide-gray-100">
                {!form.companyId ? (
                  <div className="px-3 py-3 text-[12px] text-gray-400">Select a company &amp; departments first.</div>
                ) : loadingUsers ? (
                  <div className="px-3 py-3 text-[12px] text-gray-400">Loading…</div>
                ) : doerPool.length === 0 ? (
                  <div className="px-3 py-3 text-[12px] text-gray-400">No doers for the selected departments.</div>
                ) : (
                  doerPool.map((u) => {
                    const id = uid(u);
                    const on = form.doerIds.includes(id);
                    return (
                      <label key={id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50">
                        <input type="checkbox" checked={on} onChange={() => toggleDoer(id)}
                          className="w-4 h-4 accent-indigo-600 cursor-pointer" />
                        <span className="text-[13px] text-gray-700">
                          {displayName(u)}{govRole(u) ? <span className="text-gray-400"> — {govRole(u)}</span> : null}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            <div>
              <Label>Comment</Label>
              <textarea rows={3} value={form.comment} onChange={(e) => set({ comment: e.target.value })} placeholder="Optional notes…" className={`${field} resize-y`} />
            </div>

            {/* Proof upload — only for activities flagged upload_required in Activity Management. */}
            {uploadRequired && (
              <div className="p-4 rounded-2xl border border-dashed border-indigo-200 bg-indigo-50/40">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-black uppercase text-indigo-600 tracking-widest">📎 Upload for {form.activity}</span>
                  <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-orange-50 text-orange-500 uppercase tracking-wide">Required</span>
                </div>
                <input type="file" onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="block w-full text-[12px] text-gray-600 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-indigo-600 file:text-white file:text-[11px] file:font-black file:cursor-pointer file:hover:brightness-110" />
                <p className="text-[10px] text-gray-400 font-medium mt-2">
                  {isEditing ? 'Attaches to this activity on save.' : 'Attaches to the first occurrence on save.'} You can also upload later from the activity card. Max&nbsp;25&nbsp;MB.
                </p>
              </div>
            )}

            {/* Reminders */}
            <div className="p-4 rounded-2xl border border-dashed border-orange-200 bg-orange-50/40">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell size={14} className="text-orange-500" />
                  <span className="text-[10px] font-black uppercase text-orange-600 tracking-widest">Reminders ({form.reminders.length})</span>
                </div>
                <button type="button" onClick={() => setShowReminders(true)}
                  className="px-3 py-1.5 bg-white border border-orange-200 text-orange-600 rounded-lg text-[10px] font-black hover:bg-orange-500 hover:text-white transition-all">
                  {form.reminders.length ? 'MANAGE' : '+ ADD REMINDER'}
                </button>
              </div>
              {form.reminders.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {form.reminders.map((r, i) => (
                    <span key={i} className="px-2 py-1 bg-white border border-gray-100 rounded text-[9px] font-bold text-gray-500">
                      {r.reminder_type === 'whatsapp' ? '💬' : r.reminder_type === 'both' ? '⚡' : '📧'} {r.offset_minutes}m {r.timing_type}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-[10px] text-gray-400 font-medium mt-2">Before/After reminders apply to every occurrence. A schedule email is sent on save; reminder emails at their time.</p>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-3 bg-gray-50">
            <button onClick={onClose} className="px-5 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-[12px] font-black hover:bg-gray-100 transition-all">Cancel</button>
            <button onClick={handleSave} disabled={saving}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-500 text-white text-[12px] font-black shadow-lg shadow-indigo-500/30 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-60">
              {saving ? <RefreshCw size={15} className="animate-spin" /> : <Save size={15} />}
              {saving ? 'Saving…' : (isEditing ? 'Save Changes' : 'Save Schedule')}
            </button>
          </div>
        </motion.div>
      </div>

      {/* TPMS ▸ once-per-month duplicate warning. Advisory only — "Schedule Anyway"
          overrides it, exactly as the source's conflict modal did.
          z-index must stay ABOVE the schedule modal (z-250): this dialog is opened *from*
          it and asks the user to confirm. Underneath it, Save appeared to do nothing at
          all — no dialog, no request, no toast. */}
      {conflict && (
        <div className="fixed inset-0 z-[310] flex items-center justify-center p-4 bg-black/40">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl overflow-hidden">
            <div className="px-6 py-4 bg-amber-50 border-b border-amber-200">
              <h3 className="text-[15px] font-black text-amber-700">⚠ Already Scheduled</h3>
            </div>
            <div className="px-6 py-4 max-h-[50vh] overflow-y-auto">
              <p className="text-[12.5px] text-amber-800 font-semibold mb-3">
                {conflict.info.scope === 'HOD'
                  ? <>This activity is <b>HOD-wise once a month</b> and the selected doer already has it this month ({conflict.info.period}).</>
                  : <>This activity is <b>company-wise once a month</b> and this client already has it this month ({conflict.info.period}).</>}
              </p>
              {(conflict.info.existing || []).map((m) => (
                <div key={m.event_id} className="rounded-xl border border-gray-200 px-3 py-2 mb-2">
                  <div className="text-[12.5px] font-black text-gray-800">{m.title || '(no title)'}</div>
                  <div className="text-[11.5px] text-gray-500 font-semibold">
                    📅 {m.date}{m.time ? ` · 🕒 ${m.time}` : ''} · {m.status}
                  </div>
                </div>
              ))}
            </div>
            <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3 bg-gray-50">
              <button onClick={() => setConflict(null)}
                className="px-5 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-[12px] font-black hover:bg-gray-100 transition-all">
                Cancel
              </button>
              <button
                onClick={() => { const p = conflict.payload; setConflict(null); saveTpms(p); }}
                className="px-6 py-2.5 rounded-xl bg-amber-500 text-white text-[12px] font-black shadow-lg hover:scale-[1.02] active:scale-95 transition-all">
                Schedule Anyway
              </button>
            </div>
          </div>
        </div>
      )}

      <ReminderModal
        isOpen={showReminders}
        onClose={() => setShowReminders(false)}
        reminders={form.reminders}
        onApply={(reminders) => set({ reminders })}
      />
    </AnimatePresence>
  );
};

export default ScheduleCalendarModal;
