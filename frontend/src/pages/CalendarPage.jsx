import React, { useState, useEffect, useRef } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import listPlugin from '@fullcalendar/list';
import multiMonthPlugin from '@fullcalendar/multimonth';
import interactionPlugin from '@fullcalendar/interaction';
import {  AnimatePresence , motion } from 'framer-motion';
import api from '../services/api';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import { useMemo } from 'react';

import {
    ChevronLeft, ChevronRight, Clock, X, UserCircle2,
    Zap, ListChecks, Users2, Activity, CalendarDays, Building2,
    Layers, Trash2, AlertCircle, Link, Check, UserPlus2,
    Edit2, CheckCircle, ArrowRightLeft, Ban, PlayCircle, MoreHorizontal,
    PlusCircle, LayoutGrid, Calendar as CalendarIcon, Briefcase, Video, Bell,
    Eye, Lock, ClipboardList, FileText, ChevronDown, CheckCircle2, Circle,
    ShieldCheck
} from 'lucide-react';
import ReminderModal from '../components/calendar/ReminderModal';
import MiniDatePicker from '../components/tasks/MiniDatePicker';
import { canAccessTaskManagement } from '../utils/taskAccess';

const CustomTimePicker = ({ value, onChange, label: _label }) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef(null);
    
    // Parse initial value (expected HH:mm)
    const [hours, minutes] = (value || "00:00").split(':');
    
    const hoursList = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));
    const minutesList = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'));

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelect = (h, m) => {
        onChange(`${h}:${m}`);
    };

    return (
        <div className="relative" ref={containerRef}>
            <button
                type="button"
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center gap-2 bg-transparent px-3 py-1.5 text-[12px] font-black text-[var(--accent-indigo)] outline-none hover:bg-white/50 rounded-lg transition-all"
            >
                {value || "00:00"}
                <Clock size={12} className="opacity-60" />
            </button>

            <AnimatePresence>
                {isOpen && (
                    <motion.div
                        initial={{ opacity: 0, y: 10, scale: 0.95 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 10, scale: 0.95 }}
                        className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-white rounded-2xl shadow-2xl border border-gray-100 flex overflow-hidden z-[1000] min-w-[140px]"
                    >
                        {/* Hours Column */}
                        <div className="flex-1 max-h-[200px] overflow-y-auto no-scrollbar border-r border-gray-50 py-2">
                            <div className="px-3 py-1 text-[8px] font-black text-gray-400 uppercase tracking-widest text-center sticky top-0 bg-white">Hrs</div>
                            {hoursList.map(h => (
                                <button
                                    key={h}
                                    onClick={() => handleSelect(h, minutes)}
                                    className={`w-full px-4 py-2 text-[12px] font-black transition-all ${h === hours ? 'bg-[var(--accent-indigo)] text-white' : 'text-gray-600 hover:bg-indigo-50 hover:text-[var(--accent-indigo)]'}`}
                                >
                                    {h}
                                </button>
                            ))}
                        </div>
                        {/* Minutes Column */}
                        <div className="flex-1 max-h-[200px] overflow-y-auto no-scrollbar py-2">
                            <div className="px-3 py-1 text-[8px] font-black text-gray-400 uppercase tracking-widest text-center sticky top-0 bg-white">Min</div>
                            {minutesList.map(m => (
                                <button
                                    key={m}
                                    onClick={() => {
                                        handleSelect(hours, m);
                                        setIsOpen(false);
                                    }}
                                    className={`w-full px-4 py-2 text-[12px] font-black transition-all ${m === minutes ? 'bg-[var(--accent-indigo)] text-white' : 'text-gray-600 hover:bg-indigo-50 hover:text-[var(--accent-indigo)]'}`}
                                >
                                    {m}
                                </button>
                            ))}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

// ─── Todo recurrence ───
// Frequency options, the repeat_data shape, the controls and the validation below are taken
// from the Task & Delegation "Repeat" control (components/tasks/TaskFormModal.jsx) unchanged,
// so a repeating todo and a repeating task are the same thing on the wire.
//
// The two differ in two ways. WHEN the occurrences appear: a repeating TASK is created one
// occurrence at a time by a nightly job, while a repeating TODO is generated in FULL on save —
// every date up to the Repeat End Date at once (backend:
// recurring_task_service.build_series_occurrences), so the whole series is on the calendar
// immediately. That is also why the End Date is REQUIRED here — there is no "generate up to no
// end date". And HOLIDAYS: a todo landing on a holiday or a weekly off is skipped, with no todo
// created for that day at all — unlike a task, it is never moved onto the next working day.
// "periodic" is the stored value behind the "Periodically" label; "Yearly" is reference-only
// (the engine matches "Annually"), exactly as it is for tasks today.
const REPEAT_OPTIONS = [
    { value: 'Daily', label: 'Daily' },
    { value: 'Weekly', label: 'Weekly' },
    { value: 'Monthly', label: 'Monthly' },
    { value: 'Yearly', label: 'Yearly' },
    { value: 'periodic', label: 'Periodically' },
    { value: 'Custom', label: 'Custom' },
];

const EMPTY_REPEAT_DATA = { monthlyDates: [], weekdays: [], lastDay: false };

// Reconciles whatever shape repeat_data comes back as (including the older single-value
// day_of_month/weekday shape) into the { monthlyDates, weekdays, lastDay } shape the controls
// use — same helper the task form applies, so editing an older doc doesn't crash.
const normalizeRepeatData = (data) => {
    if (!data) return { ...EMPTY_REPEAT_DATA };
    if (Array.isArray(data.monthlyDates) || Array.isArray(data.weekdays)) {
        return { ...EMPTY_REPEAT_DATA, ...data };
    }
    if (data.day_of_month === 'last') return { ...EMPTY_REPEAT_DATA, lastDay: true };
    if (typeof data.day_of_month === 'number') return { ...EMPTY_REPEAT_DATA, monthlyDates: [data.day_of_month] };
    if (typeof data.weekday === 'number') return { ...EMPTY_REPEAT_DATA, weekdays: [data.weekday] };
    return { ...EMPTY_REPEAT_DATA };
};

const customUnitLabel = (unit, interval) => {
    const singular = { Weeks: 'Week', Months: 'Month' }[unit || 'Months'];
    return (interval || 1) === 1 ? singular : (unit || 'Months');
};

// The repeat rules from TaskFormModal.validate(), applied verbatim. A todo's due date is its
// series start, so `start` is always present — the Start Date check is kept anyway so the two
// forms stay line-for-line comparable. Returns an error string, or null when valid.
const validateRepeat = (form) => {
    if (form.repeat === 'Does not repeat') return null;
    if (!form.start) return 'Start Date is required when Repeat is enabled';
    if (!form.repeat) return 'Frequency is required when Repeat is enabled';
    const data = form.repeat_data || EMPTY_REPEAT_DATA;
    if (form.repeat === 'Monthly' && !data.lastDay && !(data.monthlyDates || []).length) {
        return 'Select at least one date (or Last Day) for a Monthly repeat';
    }
    if (form.repeat === 'Custom' && (data.customUnit || 'Months') === 'Months' && !data.lastDay && !(data.monthlyDates || []).length) {
        return 'Select at least one date (or Last Day) for a Custom repeat';
    }
    // The whole series is generated up front, bounded by this date — so it is required, not
    // optional as it was while a todo rolled forward one day at a time forever.
    if (!form.repeat_end_date) return 'Select a Repeat End Date — the series is generated up to that date';
    if (new Date(form.repeat_end_date) < new Date(form.start)) {
        return 'End Date cannot be before Start Date';
    }
    return null;
};

// The Repeat control itself. Kept as its own component (rather than inlined in the already
// long modal) purely for readability; the markup mirrors the task form's control.
const TodoRepeatSection = ({ form, setForm, minEndDate: _minEndDate }) => {
    const [freqOpen, setFreqOpen] = useState(false);
    const [customIntervalOpen, setCustomIntervalOpen] = useState(false);
    const [customUnitOpen, setCustomUnitOpen] = useState(false);
    const [repeatEndPickerOpen, setRepeatEndPickerOpen] = useState(false);

    const data = form.repeat_data || EMPTY_REPEAT_DATA;
    const isRepeating = form.repeat !== 'Does not repeat';
    const setRepeatData = (patch) => setForm({ ...form, repeat_data: { ...data, ...patch } });

    const toggleMonthlyDate = (day) => {
        const current = data.monthlyDates || [];
        const monthlyDates = current.includes(day) ? current.filter(d => d !== day) : [...current, day].sort((a, b) => a - b);
        setRepeatData({ monthlyDates, lastDay: false });
    };
    const toggleLastDay = () => setRepeatData({ lastDay: !data.lastDay, monthlyDates: [] });
    const toggleWeekday = (idx) => {
        const current = data.weekdays || [];
        setRepeatData({ weekdays: current.includes(idx) ? current.filter(d => d !== idx) : [...current, idx].sort((a, b) => a - b) });
    };

    const dayGrid = (
        <div className="grid grid-cols-10 gap-1.5">
            {Array.from({ length: 31 }, (_, i) => i + 1).map(day => (
                <button type="button" key={day} onClick={() => toggleMonthlyDate(day)}
                    className={`aspect-square flex items-center justify-center rounded-lg text-[11px] font-bold border transition-all ${(data.monthlyDates || []).includes(day) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'}`}>
                    {day}
                </button>
            ))}
            <button type="button" onClick={toggleLastDay}
                className={`col-span-3 flex items-center justify-center rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${data.lastDay ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'}`}>
                Last Day
            </button>
        </div>
    );

    const weekdayGrid = (order) => (
        <div className="grid grid-cols-7 gap-1.5">
            {order.map(([idx, label]) => (
                <button type="button" key={label} onClick={() => toggleWeekday(idx)}
                    className={`py-2 rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${(data.weekdays || []).includes(idx) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'}`}>
                    {label}
                </button>
            ))}
        </div>
    );

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap p-3 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">
                <button type="button"
                    onClick={() => setForm({
                        ...form,
                        repeat: isRepeating ? 'Does not repeat' : 'Daily',
                        // Turning Repeat off drops the series settings, so a stale end date or
                        // day selection can never resurrect a recurrence the user cancelled.
                        ...(isRepeating ? { repeat_end_date: '', repeat_interval: 1, repeat_data: { ...EMPTY_REPEAT_DATA } } : {}),
                    })}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${isRepeating ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                    {isRepeating ? <CheckCircle2 size={12} /> : <Circle size={12} />} Repeat
                </button>

                {isRepeating && (
                    <>
                        <div className="relative" onClick={e => e.stopPropagation()}>
                            <button type="button" onClick={() => { setFreqOpen(o => !o); setCustomIntervalOpen(false); setCustomUnitOpen(false); }}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-full text-[10px] font-black uppercase tracking-wider text-[var(--text-main)]">
                                {REPEAT_OPTIONS.find(o => o.value === form.repeat)?.label || 'Daily'}
                                <ChevronDown size={12} className={`transition-transform ${freqOpen ? 'rotate-180' : ''}`} />
                            </button>
                            {freqOpen && (
                                <div className="absolute top-full left-0 mt-1.5 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-xl overflow-hidden z-20 p-1.5 space-y-0.5">
                                    {REPEAT_OPTIONS.map(o => (
                                        <button type="button" key={o.value}
                                            onClick={() => { setForm({ ...form, repeat: o.value }); setFreqOpen(false); }}
                                            className={`w-full text-left px-3 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider transition-all ${form.repeat === o.value ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                                            {o.label}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* The task form carries a separate Start Date chip because a task's
                            `start` is a recurrence anchor distinct from its deadline. A todo's
                            due date IS its start, so the series simply runs from the Due Date
                            picked above — only the end of the series is collected here. */}
                        {/* Required: the series is generated in full up to this date, so an
                            unset End Date has nothing to generate against. Flagged in red until
                            it is picked rather than only failing on save. */}
                        <button type="button" onClick={() => setRepeatEndPickerOpen(true)}
                            className={`relative flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-card)] border rounded-full text-[10px] font-black uppercase tracking-wider cursor-pointer hover:border-[var(--accent-indigo)] ${form.repeat_end_date ? 'border-[var(--border)] text-[var(--text-muted)]' : 'border-rose-300 text-rose-500'}`}>
                            <CalendarDays size={12} />
                            {form.repeat_end_date ? new Date(form.repeat_end_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'End Date *'}
                        </button>
                        <MiniDatePicker
                            isOpen={repeatEndPickerOpen}
                            onClose={() => setRepeatEndPickerOpen(false)}
                            value={form.repeat_end_date}
                            title="Repeat End Date"
                            dateOnly
                            onApply={(iso) => setForm({ ...form, repeat_end_date: iso })}
                        />
                    </>
                )}
            </div>

            {form.repeat === 'periodic' && (
                <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] flex items-center justify-between">
                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Repeat Every</span>
                    <input type="number" min="1" value={form.repeat_interval}
                        onChange={e => setForm({ ...form, repeat_interval: parseInt(e.target.value) || 1 })}
                        className="w-16 text-center px-2 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]" />
                    <span className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-wider">Days</span>
                </div>
            )}

            {form.repeat === 'Monthly' && (
                <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">{dayGrid}</div>
            )}

            {form.repeat === 'Weekly' && (
                <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">
                    {weekdayGrid([[0, 'Sun'], [1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat']])}
                </div>
            )}

            {form.repeat === 'Custom' && (
                <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] space-y-3">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Occur Every</span>

                        <div className="relative" onClick={e => e.stopPropagation()}>
                            <button type="button" onClick={() => { setCustomIntervalOpen(o => !o); setCustomUnitOpen(false); }}
                                className="flex items-center gap-1 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)]">
                                {form.repeat_interval || 1}
                                <ChevronDown size={12} className={`transition-transform ${customIntervalOpen ? 'rotate-180' : ''}`} />
                            </button>
                            {customIntervalOpen && (
                                <div className="absolute top-full left-0 mt-1.5 w-16 max-h-48 overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-20 p-1">
                                    {Array.from({ length: 30 }, (_, i) => i + 1).map(n => (
                                        <button type="button" key={n}
                                            onClick={() => { setForm({ ...form, repeat_interval: n }); setCustomIntervalOpen(false); }}
                                            className={`w-full text-center px-2 py-1.5 rounded-lg text-[11px] font-bold ${(form.repeat_interval || 1) === n ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                                            {n}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="relative" onClick={e => e.stopPropagation()}>
                            <button type="button" onClick={() => { setCustomUnitOpen(o => !o); setCustomIntervalOpen(false); }}
                                className="flex items-center gap-1 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)]">
                                {customUnitLabel(data.customUnit, form.repeat_interval)}
                                <ChevronDown size={12} className={`transition-transform ${customUnitOpen ? 'rotate-180' : ''}`} />
                            </button>
                            {customUnitOpen && (
                                <div className="absolute top-full left-0 mt-1.5 w-24 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-20 p-1 space-y-0.5">
                                    {['Weeks', 'Months'].map(unit => (
                                        <button type="button" key={unit}
                                            onClick={() => { setRepeatData({ customUnit: unit }); setCustomUnitOpen(false); }}
                                            className={`w-full text-left px-2.5 py-1.5 rounded-lg text-[12px] font-bold ${(data.customUnit || 'Months') === unit ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                                            {customUnitLabel(unit, form.repeat_interval)}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {data.customUnit === 'Weeks' && (
                        <div>
                            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Select Days :</span>
                            <div className="mt-1.5">
                                {weekdayGrid([[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [0, 'Sun']])}
                            </div>
                        </div>
                    )}

                    {(data.customUnit || 'Months') === 'Months' && (
                        <div>
                            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Select Dates :</span>
                            <div className="mt-1.5">{dayGrid}</div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

const CalendarPage = () => {
    const calendarRef = useRef(null);
    // The card the grid is drawn inside. Watched for width changes — see the observer below.
    const calendarShellRef = useRef(null);
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    // Show task-related stat cards only when the user has access to the Delegation module.
    const showTaskStats = canAccessTaskManagement(user);
    const [events, setEvents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [viewName, setViewName] = useState('dayGridMonth');
    const [viewMode, setViewMode] = useState('personal'); 

    const [batches, setBatches] = useState([]);
    const [quarters, setQuarters] = useState([]);
    const [templates, setTemplates] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    const [statFilter, setStatFilter] = useState(null);
    const [backdateSettings, setBackdateSettings] = useState({ allow_backdate: false, exception_users: [] });
    const [_gptProjects, setGptProjects] = useState([]);

    const [showSummary, setShowSummary] = useState(false);
    const [summaryDate, setSummaryDate] = useState(null);
    const [dayEvents, setDayEvents] = useState([]);
    const [currentViewDate, setCurrentViewDate] = useState(new Date());

    const monthsList = [
        'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
        'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'
    ];

    const [showModal, setShowModal] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [currentEventId, setCurrentEventId] = useState(null);
    const [showReminderModal, setShowReminderModal] = useState(false);
    const [dueDatePickerOpen, setDueDatePickerOpen] = useState(false); // todo Due date/time calendar

    const initialForm = {
        title: '', type: 'event', start: '', end: '', all_day: true,
        session_type: 'Core', priority: 'Normal', session_template_id: '',
        batch_id: '', quarter_id: '', status: 'schedule', meeting_link: '',
        assigned_departments: [], assigned_member_ids: [], coach_ids: [],
        additional_details: '', category: 'General', repeat: 'Does not repeat',
        repeat_end_date: '', repeat_interval: 1, repeat_data: { ...EMPTY_REPEAT_DATA },
        assigned_to: 'myself', target_staff_id: [],
        reminders: [], status_remark: '', gpt_projects: [], created_at: null
    };

    const navigate = useNavigate();

    const [eventForm, setEventForm] = useState(initialForm);

    const departments = ['HOD', 'Manager', 'EA', 'MD', 'Implementor', 'HR', 'Other'];

    const fetchData = async () => {
        setLoading(true);
        const role = user?.role?.toLowerCase();
        const isStaffRole = ['superadmin', 'admin', 'coach', 'staff'].includes(role);
        const usersEndpoint = isStaffRole ? '/users?active_only=true' : `/companies/${user?.company_id}/users?active_only=true`;
        try {
            const [evRes, bRes, qRes, tRes, uRes, sRes, gRes] = await Promise.all([
                api.get(`/calendar/events?view_mode=${viewMode}`), api.get('/batches'),
                api.get('/quarters'), api.get('/session-templates'),
                api.get(usersEndpoint), api.get('/settings/backdate-control'),
                api.get('/gpt/projects')
            ]);
            setEvents(mapApiEvents(evRes.data));
            setBatches(bRes.data); setQuarters(qRes.data); setTemplates(tRes.data); setAllUsers(uRes.data);
            setBackdateSettings(sRes.data); setGptProjects(gRes.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };
    // Re-measure the grid whenever this column's width changes.
    //
    // The sidebar expands on hover, and the rail reserving its space (components/common/
    // PrivateRoute.jsx) follows it with a spring from 72px to 240px. The main column is
    // `flex-1 min-w-0`, so its width moves with that spring — but the WINDOW never resizes,
    // and a window resize is the only thing that makes FullCalendar re-measure after mount.
    //
    // That is exactly why the gap appeared on the way IN: clicking "Calendar" means the
    // cursor is on the sidebar, so it is expanded to 240px at the moment the grid measures
    // itself. Move the mouse onto the page, the sidebar collapses back to 72px, the column
    // grows 168px wider — and the table stays the width it was born at, leaving a dead band
    // down the right-hand side.
    //
    // Observing the container rather than hooking the sidebar keeps the two unaware of each
    // other, and covers the notification drawer, browser zoom and split-screen for free.
    useEffect(() => {
        const shell = calendarShellRef.current;
        if (!shell || typeof ResizeObserver === 'undefined') return undefined;

        let frame = 0;
        let lastWidth = 0;
        const observer = new ResizeObserver(([entry]) => {
            // Width only: this box also grows taller as events load and as day cells fill,
            // and re-laying out the grid for that would be work with nothing to show for it.
            const width = Math.round(entry.contentRect.width);
            if (width === lastWidth) return;
            lastWidth = width;
            // The spring reports a new width every frame; coalesce so the grid is measured
            // once per paint instead of sixty times per collapse.
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => calendarRef.current?.getApi?.().updateSize());
        });
        observer.observe(shell);
        return () => { cancelAnimationFrame(frame); observer.disconnect(); };
    }, []);

    useEffect(() => { fetchData(); }, [viewMode]); // eslint-disable-line react-hooks/exhaustive-deps

    const formatIST = (dateStr) => {
        if (!dateStr) return "";
        let d = new Date(dateStr);
        if (typeof dateStr === 'string' && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
            d = new Date(dateStr + 'Z');
        }
        return d.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };

    const formatShortIST = (dateStr) => {
        if (!dateStr) return "";
        let d = new Date(dateStr);
        if (typeof dateStr === 'string' && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
            d = new Date(dateStr + 'Z');
        }
        return d.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: 'numeric', month: 'short',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };

    // ─── Todo date display ───
    // A todo's due date is picked in the user's OWN timezone, so it has to be displayed in
    // that same timezone. formatIST/formatShortIST above render in Asia/Kolkata, which shows a
    // different DAY for anyone not on IST: a todo set for 11 July (stored at local midday)
    // reads back as "12 July, 12:30 AM". These render from the same local clock the date
    // picker writes with, so the date shown always equals the date chosen.
    // A full-day todo shows no time at all — the time carries no meaning for it.
    const formatTodoDateTime = (dateStr, allDay) => {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleString(undefined, {
            weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
            ...(allDay ? {} : { hour: '2-digit', minute: '2-digit', hour12: true }),
        });
    };

    // Creation timestamp for the Personal Todo header — e.g. "Tue, Aug 03, 2026 at 09:48 PM".
    // Rendered in the user's OWN local timezone (exactly like the Due date above), so the date
    // shown always equals the calendar date the todo was actually created on. Forcing a fixed
    // zone (Asia/Kolkata) rolled a late-evening creation to the NEXT day for anyone whose clock
    // isn't IST — that was the off-by-one. Captured when the modal opens and then frozen.
    const formatCreatedLocal = (iso) => {
        if (!iso) return "";
        const d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        const datePart = d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: '2-digit', year: 'numeric' });
        const timePart = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: true });
        return `${datePart} at ${timePart}`;
    };

    const formatTodoShort = (dateStr, allDay) => {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleString(undefined, {
            day: 'numeric', month: 'short',
            ...(allDay ? {} : { hour: '2-digit', minute: '2-digit', hour12: true }),
        });
    };


    // ─── Todo due TIME ───
    // A todo's due date AND time are both interpreted in IST by the backend
    // (_apply_todo_due_end_of_day), so these read and write IST wall-clock explicitly rather
    // than in the browser's zone — otherwise a user outside IST would pick 10:00 and store a
    // different hour. 23:59:59 is the "no time chosen" value: it is what a todo has always been
    // due at, so an existing todo reads back as blank and keeps behaving exactly as before.
    const IST_OFFSET_MIN = 330;
    const toIstWallClock = (dateStr) => {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return null;
        // Shift so the Date's LOCAL getters read as IST clock fields.
        return new Date(d.getTime() + (d.getTimezoneOffset() + IST_OFFSET_MIN) * 60000);
    };

    /** "HH:MM" for the time input, or "" when the todo has no chosen time (end of day). */
    const todoDueTimeValue = (dateStr) => {
        const ist = toIstWallClock(dateStr);
        if (!ist) return "";
        if (ist.getHours() === 23 && ist.getMinutes() === 59) return "";
        return `${String(ist.getHours()).padStart(2, '0')}:${String(ist.getMinutes()).padStart(2, '0')}`;
    };

    /** Human summary of a todo's due moment, all in IST — the single source of truth for the
     *  Due card, so the date, the time and the caption can never disagree. */
    const todoDueSummary = (dateStr) => {
        const hhmm = todoDueTimeValue(dateStr);
        const d = new Date(dateStr);
        const valid = !isNaN(d.getTime());
        return {
            hasTime: !!hhmm,
            dateLabel: valid
                ? d.toLocaleDateString(undefined, { timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
                : '—',
            timeLabel: valid
                ? d.toLocaleTimeString(undefined, { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: true })
                : '—',
        };
    };

    /** The same calendar day as `dateStr`, at "HH:MM" IST, as a UTC ISO string. */
    const withTodoDueTime = (dateStr, hhmm) => {
        const ist = toIstWallClock(dateStr) || toIstWallClock(new Date().toISOString());
        const ymdIst = `${ist.getFullYear()}-${String(ist.getMonth() + 1).padStart(2, '0')}-${String(ist.getDate()).padStart(2, '0')}`;
        return new Date(`${ymdIst}T${hhmm}:00+05:30`).toISOString();
    };

    const getLocalDatePart = (dateStr) => {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };

    const getLocalTimePart = (dateStr) => {
        if (!dateStr) return "00:00";
        const d = new Date(dateStr);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    };

    const updateDateTimePart = (dateStr, newPart, isDate = true) => {
        if (!dateStr) return dateStr;
        const d = new Date(dateStr);
        if (isDate) {
            const [y, m, day] = newPart.split('-');
            d.setFullYear(parseInt(y), parseInt(m) - 1, parseInt(day));
        } else {
            const [h, min] = newPart.split(':');
            d.setHours(parseInt(h), parseInt(min));
        }
        return d.toISOString();
    };

    const categories = useMemo(() => {
        const set = new Set(['General', 'Maintenance', 'Meeting', 'Call', 'Private', 'Check-in']);
        events.forEach(e => { if (e.extendedProps?.category) set.add(e.extendedProps.category); });
        return Array.from(set);
    }, [events]);

    const getRescheduleColor = (status, type, color, isCreator) => {
        if (status === 'reschedule') return '#f59e0b'; // Amber/Orange
        if (status === 'completed') return '#10b981'; // Emerald
        if (status === 'canceled') return '#ef4444'; // Red
        // A todo whose due date/time passed while still pending — set by the backend sweep, not
        // by the user. Red overrides the module's violet: a missed todo must not read as normal.
        if (status === 'overdue') return '#e11d48'; // Rose

        // Todos are always the creator's own (private), so they get one fixed colour.
        if (type === 'todo') return '#8b5cf6'; // Violet

        if (isCreator) {
            return color || (type === 'task' ? '#f97316' : '#6366f1'); // Orange / Indigo
        } else {
            return color || (type === 'task' ? '#e11d48' : '#0d9488'); // Rose / Teal
        }
    };

    // ─── Day-cell key: the ONE place that decides which day an entry belongs to ───
    //
    // Everything on this page (the grid, the Day Summary, the stats, the post-action refresh)
    // must agree, and must agree with FullCalendar — which runs at timeZone:'local' and places
    // each entry in its LOCAL day cell.
    //
    // The bug this replaces: the Day Summary compared the RAW STORED STRING's date part
    // (`e.start.split('T')[0]`), which is the UTC date. For anything stored as a Z timestamp
    // whose UTC date differs from its local date, that is a different day than the grid drew it
    // on — e.g. a task due 2026-05-13T19:30:00Z is 14 May in IST: drawn on the 14th, but listed
    // under the 13th. Hence "click a date, see another date's tasks".
    //
    // Three stored shapes exist in the DB and each needs its own rule:
    //   'YYYY-MM-DD'            (date-only, all-day)  -> already a day key; DO NOT feed to Date(),
    //                                                    JS reads it as UTC midnight and can slide
    //                                                    it a day in negative-offset zones.
    //   '...Z' / '...+00:00'    (instant)             -> convert to the local day.
    const dayKey = (value) => {
        if (!value) return "";
        if (typeof value === 'string' && !value.includes('T')) return value.slice(0, 10);
        const d = new Date(value);
        if (isNaN(d.getTime())) return "";
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };

    // A task's `start` is only its creation / recurrence anchor — the date the user actually
    // picked is the due date (`end`, "Set Deadline"). Anchor tasks to that, so a task lands on
    // the day it is DUE. Sessions keep their own start.
    const anchorOf = (e) => {
        const evType = e.extendedProps?.type || e.type;
        return (evType === 'task' && e.end) ? e.end : e.start;
    };

    const isTodoRow = (e) => (e.extendedProps?.type || e.type) === 'todo';

    // A todo's REAL stored due instant, read straight off the document. The grid entry a todo is
    // published with is an all-day date (see mapApiEvents), so anything that displays or edits a
    // todo's due date/time must come through here instead of the top-level start/end.
    const todoDueRaw = (e) => e.extendedProps?.end || e.extendedProps?.start || e.end || e.start;

    // Shape the API payload for FullCalendar. Shared by the initial load AND the post-action
    // refresh, so both agree on the anchor — previously the refresh re-keyed tasks on their
    // creation date and they jumped days after a complete/delete.
    //
    // ─── Todos are single-day entries, always ───
    // A todo carries no meaningful time: the form never offers one, and the backend pins every
    // todo to 23:59:59 IST on its date. Publishing that instant as a TIMED event made a todo
    // occupy TWO cells — with start == end FullCalendar treats the end as absent and applies its
    // default one-hour duration, which from 23:59:59 crosses midnight, so a todo due on the 5th
    // also painted the 6th. (In the Week/Day views the same event drew a full-height block down
    // the whole day.)
    //
    // So a todo is published as an ALL-DAY entry on its own local date with no end at all. That
    // is unconditional — it cannot span regardless of what time the document carries — and it
    // renders as a single chip in every view: the month cell, the all-day row of Week/Day, and
    // Year. Nothing else changes shape: tasks, sessions and events keep their exact previous
    // start/end/allDay, so genuine multi-day rendering is untouched.
    const mapApiEvents = (rows) => (rows || []).map(e => {
        const todo = isTodoRow(e);
        return {
            id: e.id, title: e.title,
            start: todo ? dayKey(anchorOf(e)) : anchorOf(e),
            end: todo ? undefined : e.end,
            allDay: todo ? true : e.allDay,
            backgroundColor: 'transparent', borderColor: 'transparent', textColor: 'var(--text-main)',
            extendedProps: {
                ...e.extendedProps, id: e.id,
                dotColor: getRescheduleColor(e.extendedProps?.status || e.status, e.extendedProps?.type || e.type, e.color, e.extendedProps?.isCreator)
            }
        };
    });

    // Entries drawn on `key`'s cell. Batches/quarters are backdrop markers, not day entries.
    const eventsOnDay = (key, list) => (list || []).filter(e =>
        dayKey(e.start) === key && !['batch', 'quarter'].includes(e.extendedProps?.type || e.type)
    );

    // ─── Stats Calculation ───
    const currentMonthStats = useMemo(() => {
        const currentYear = currentViewDate.getFullYear();
        const currentMonth = currentViewDate.getMonth();

        const data = events.filter(e => {
            const key = dayKey(e.start);
            if (!key) return false;
            const [y, m] = key.split('-');
            return Number(y) === currentYear && Number(m) - 1 === currentMonth;
        });

        const getCount = (type, status) => {
            return data.filter(e => {
                const eType = e.extendedProps?.type || e.type;
                const eStatus = e.extendedProps?.status || e.status || "schedule";
                if (type && eType !== type) return false;
                // "pending" is the label for the stored value "schedule". A todo past its due
                // date carries "overdue" instead, so it drops out of Pending automatically and
                // is counted by its own card — no overlap between the two.
                if (status === 'pending') return eStatus === 'schedule';
                if (status && eStatus !== status) return false;
                return true;
            }).length;
        };

        // Grouped by the module each metric belongs to, so Session / Task / Todo figures read
        // as three separate stories instead of one undifferentiated row. Card definitions
        // (labels, counts, colors, icons, filters) are unchanged — only their grouping is new.
        const groups = [
            {
                key: 'sessions',
                label: 'Sessions',
                cards: [
                    { id: 'ev_total', label: 'Total Sessions', count: getCount('event', null), color: 'indigo', icon: <Activity size={14} />, filter: { type: 'event', status: null } },
                    { id: 'ev_com', label: 'Completed', count: getCount('event', 'completed'), color: 'emerald', icon: <CheckCircle size={14} />, filter: { type: 'event', status: 'completed' } },
                    { id: 'ev_pen', label: 'Pending', count: getCount('event', 'pending'), color: 'amber', icon: <Clock size={14} />, filter: { type: 'event', status: 'pending' } },
                    { id: 'ev_res', label: 'Rescheduled', count: getCount('event', 'reschedule'), color: 'orange', icon: <ArrowRightLeft size={14} />, filter: { type: 'event', status: 'reschedule' } },
                ],
            },
            // Hidden entirely when the company's Delegation module is off — no heading, no cards.
            ...(showTaskStats ? [{
                key: 'tasks',
                label: 'Task & Delegation',
                cards: [
                    { id: 'tk_total', label: 'Total Tasks', count: getCount('task', null), color: 'slate', icon: <ListChecks size={14} />, filter: { type: 'task', status: null } },
                    { id: 'tk_com', label: 'Task Complete', count: getCount('task', 'completed'), color: 'emerald', icon: <CheckCircle size={14} />, filter: { type: 'task', status: 'completed' } },
                    { id: 'tk_pen', label: 'Task Pending', count: getCount('task', 'pending'), color: 'rose', icon: <AlertCircle size={14} />, filter: { type: 'task', status: 'pending' } },
                ],
            }] : []),
            {
                // Always shown: todos are personal and independent of the Delegation module.
                // Counts are computed the same way but on type "todo", so they can never
                // overlap the Task counts above (a document is one type or the other).
                key: 'todos',
                label: 'Personal Todo',
                cards: [
                    { id: 'td_total', label: 'Total Todos', count: getCount('todo', null), color: 'violet', icon: <ClipboardList size={14} />, filter: { type: 'todo', status: null } },
                    { id: 'td_com', label: 'Completed Todos', count: getCount('todo', 'completed'), color: 'emerald', icon: <CheckCircle size={14} />, filter: { type: 'todo', status: 'completed' } },
                    // Overdue is its own stored status, so it is NOT double-counted in Pending
                    // below (which matches "schedule" only) — Total = Pending + Overdue + Completed.
                    { id: 'td_over', label: 'Overdue Todos', count: getCount('todo', 'overdue'), color: 'rose', icon: <AlertCircle size={14} />, filter: { type: 'todo', status: 'overdue' } },
                    // Amber, not violet: violet is the Todo module's own colour and is already
                    // carried by the Total card, so a violet Pending card read as a duplicate.
                    // Amber also matches "Pending" in the Sessions group.
                    { id: 'td_pen', label: 'Pending Todos', count: getCount('todo', 'pending'), color: 'amber', icon: <Clock size={14} />, filter: { type: 'todo', status: 'pending' } },
                ],
            },
        ];
        return groups;
    }, [events, currentViewDate, showTaskStats]);

    // The logged-in user's own todos for the day shown in the Day Summary. `isCreator` is a
    // belt-and-braces guard: the API already scopes todos to their owner.
    const dayTodos = useMemo(
        () => dayEvents.filter(e => e.extendedProps?.type === 'todo' && e.extendedProps?.isCreator !== false),
        [dayEvents]
    );

    const activeFilter = statFilter;
    const filteredEvents = useMemo(() => {
        if (!activeFilter) return events;
        return events.filter(e => {
            const eType = e.extendedProps?.type || e.type;
            const eStatus = e.extendedProps?.status || e.status || "schedule";
            if (activeFilter.type && eType !== activeFilter.type) return false;
            if (activeFilter.status === 'pending') return eStatus === 'schedule';
            if (activeFilter.status && eStatus !== activeFilter.status) return false;
            return true;
        });
    }, [events, activeFilter]);

    // ─── Summary Logic ───
    // Reads `filteredEvents` — what the grid is actually drawing — so with a stat card active
    // the summary can't list entries that aren't on screen.
    const openDaySummary = (key) => {
        setSummaryDate(key);
        setDayEvents(eventsOnDay(key, filteredEvents));
        setShowSummary(true);
    };

    const handleDateSelect = (info) => openDaySummary(info.startStr.split('T')[0]);

    const openCreateModal = (type) => {
        setIsEdit(false); setCurrentEventId(null);
        if (type === 'todo') {
            // A todo is due at 11:59 PM on the SELECTED calendar day (the day whose Day Summary
            // this was opened from), defaulting to today when none is selected. The time is
            // automatic — there is no time picker; only the chosen date matters.
            const base = summaryDate ? new Date(`${summaryDate}T00:00:00`) : new Date();
            base.setHours(23, 59, 59, 0);
            const iso = base.toISOString();
            // Freeze the moment the todo modal opens — shown as the "Created" timestamp in the
            // header. This is independent of the Due date/time and never changes afterwards.
            setEventForm({ ...initialForm, type, start: iso, end: iso, all_day: true, created_at: new Date().toISOString() });
        } else {
            setEventForm({ ...initialForm, type, start: summaryDate, end: summaryDate });
        }
        setShowModal(true);
    };

    const openEditModal = (ev) => {
        const props = ev.extendedProps;
        setIsEdit(true);
        setCurrentEventId(ev.id || ev._id);
        // A todo's grid entry is an all-day DATE (see mapApiEvents), so its real instants have to
        // come off extendedProps. Saving the grid value would write a date-only string into
        // start/end and destroy the todo's 11:59 PM IST due time — which the reminder anchor and
        // the Overdue sweep both measure against.
        const isTodoEvent = props.type === 'todo';
        const startRaw = isTodoEvent ? (props.start || props.end) : ev.start;
        const endRaw = isTodoEvent ? (props.end || props.start) : (ev.end || ev.start);
        setEventForm({
            ...initialForm, title: ev.title, type: props.type, start: startRaw, end: endRaw,
            all_day: props.type === 'todo' ? !todoDueTimeValue(props.end || props.start) : ev.allDay, session_type: props.session_type, priority: props.priority || 'Normal',
            session_template_id: props.session_template_id, batch_id: props.batch_id,
            quarter_id: props.quarter_id, assigned_departments: props.assigned_departments || [],
            assigned_member_ids: props.assigned_member_ids || [], coach_ids: props.coach_ids || [],
            meeting_link: props.meeting_link, additional_details: props.additional_details,
            category: props.category || 'General',
            status: props.status || 'schedule',
            repeat: props.repeat || 'Does not repeat',
            repeat_end_date: props.repeat_end_date || '',
            repeat_interval: props.repeat_interval || 1,
            repeat_data: normalizeRepeatData(props.repeat_data),
            assigned_to: props.assigned_to || 'myself',
            target_staff_id: props.target_staff_id || [],
            reminders: props.reminders || [],
            status_remark: props.status_remark || '',
            gpt_projects: props.gpt_projects || [],
            completed_at: props.completed_at || null,
            isCreator: props.isCreator,
            isAssigned: props.isAssigned,
            created_at: props.created_at || null
        });

        setShowModal(true);
    };

    const handleQuickAction = async (id, action) => {
        if (!id) return showError("Invalid operation: Blueprint ID missing.");
        try {
            const ev = events.find(e => e.id === id || e._id === id);
            const isCreator = ev?.extendedProps?.isCreator;

            if (action === 'delete') { 
                if (!canDelete && !isCreator) return showError("Forbidden: You do not have digital authority to delete this blueprint.");
                await api.delete(`/calendar/events/${id}`); 
                showSuccess("Entity removed from calendar"); 
            }
            else if (action === 'complete') { 
                if (!canUpdate && !isCreator) return showError("Forbidden: You do not have digital authority to modify this event.");
                // Use the specialized completion endpoint for better reliability
                await api.patch(`/calendar/events/${id}/complete`); 
                showSuccess("Status updated"); 
            }
            fetchData();
            // If in summary modal, refresh current day list
            if (showSummary) {
                // Fast refresh for the open summary. Goes through the SAME mapper + day-key as
                // the grid — it used to re-key on the raw `start` (a task's creation date), so a
                // task due on the 15th but created on the 13th jumped to the 13th after a
                // complete/delete.
                const res = await api.get(`/calendar/events?view_mode=${viewMode}`);
                setDayEvents(eventsOnDay(summaryDate, mapApiEvents(res.data)));
            }
        } catch (err) {
            console.error(err);
            // Surface the backend's real reason (e.g. "Complete all check points before
            // completing this task") instead of a generic failure message, so the user knows
            // what's blocking Complete rather than assuming the request just didn't land.
            const detail = err.response?.data?.detail;
            showError(typeof detail === 'string' && detail ? detail : "Communication Failure: The session architect could not be reached.");
        }
    };

    const handleSave = async () => {
        if (!eventForm.title) return showError(eventForm.type === 'todo' ? "Add a todo title" : "Add a title");
        // A todo must say what actually has to be done — the details are the todo.
        if (eventForm.type === 'todo' && !(eventForm.additional_details || '').trim()) {
            return showError("Add the task details for this todo");
        }
        // Recurrence is validated by the Task & Delegation rules, unchanged — see validateRepeat.
        if (eventForm.type === 'todo') {
            const repeatError = validateRepeat(eventForm);
            if (repeatError) return showError(repeatError);
        }

        const eventStart = new Date(eventForm.start);
        const now = new Date();
        const isBackdated = eventStart < now;
        const canBackdate = backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email);

        if (isBackdated && !canBackdate && eventForm.status === 'schedule') {
            console.warn("RESTRICTED: Backdated attempt blocked in UI.");
            return showError("Operation Blocked: You do not have permission to schedule tasks or events in the past.");
        }


        const isTodo = eventForm.type === 'todo';

        // ─── CONFLICT DETECTION WARNING (Logged) ───
        // Skipped for todos: they have no attendees, so there is nobody to clash with.
        if (!isTodo) {
            try {
                const conflictCheck = await api.post('/calendar/events/validate-conflict', {
                    ...eventForm, id: currentEventId
                });
                if (conflictCheck.data.has_conflict) {
                    console.warn("Conflict detected:", conflictCheck.data.conflicts.map(c => c.title).join(", "));
                }
            } catch (e) { console.error("Conflict check failed", e); }
        }

        try {
            if (isEdit) await api.patch(`/calendar/events/${currentEventId}`, eventForm);
            else await api.post('/calendar/events', eventForm);
            showSuccess(isTodo ? (isEdit ? 'Todo updated' : 'Todo created') : (isEdit ? 'Event updated' : 'Event scheduled successfully'));
            fetchData(); setShowModal(false); setShowSummary(false);
        } catch (err) {
            // Surface the backend's real reason (e.g. a past-date block) instead of a generic
            // message, so the user knows what to fix rather than seeing "Failed to save".
            const detail = err.response?.data?.detail;
            showError(typeof detail === 'string' && detail ? detail : (isTodo ? 'Failed to save todo' : 'Failed to save event'));
            console.error(err);
        }
    };

    const role = user?.role?.toLowerCase();
    // Institutional roles (Staff) with global management authority
    const isPowerRole = ['superadmin', 'admin', 'coach', 'staff'].includes(role);
    const isStaff = isPowerRole;
    
    // Learners and Client Admins can create their own events.
    const isLearner = ['learner', 'clientadmin', 'clientdoer', 'clientuser'].includes(role);
    const canCreate = isStaff || isLearner || user?.permissions?.calendar?.create;

    // Only staff have global update/delete rights. Learners only have it if they are the creator (checked in the UI).
    const canUpdate = isStaff || user?.permissions?.calendar?.update;
    const canDelete = isStaff || user?.permissions?.calendar?.delete;

    // List of Staff users (Coaching side) for coaching team & task delegation
    const staffMembers = allUsers.filter(u => ['superadmin', 'admin', 'coach', 'staff'].includes(u.role?.toLowerCase()));

    // List of internal company members (including myself)
    const companyMembers = allUsers.filter(u => u.company_id === user?.company_id);

    // List of Learners for Staff Assignment (filtered by batch/department & session type compatibility)
    const assignableLearners = allUsers.filter(u => {
        const uRole = u.role?.toLowerCase();
        if (['superadmin', 'admin', 'coach', 'staff'].includes(uRole)) return false;

        // 1. Strict Batch & Company Linkage (Requirement: Only show batch-attached members)
        if (eventForm.batch_id) {
            const batch = batches.find(b => b._id === eventForm.batch_id || b.id === eventForm.batch_id);
            if (batch) {
                const belongsToBatch = (u.batch_id === eventForm.batch_id) || 
                                     (batch.companies || []).includes(u.company_id);
                if (!belongsToBatch) return false;
            }
        } else if (eventForm.type === 'event') {
            // For sessions, if no batch is selected, show no one to ensure accuracy
            return false;
        }

        // 2. Session Type Compatibility
        if (u.session_type === 'Both' || u.session_type === eventForm.session_type) return true;
        
        return false;
    });

    const visibleMembers = isStaff ? assignableLearners : companyMembers;

    const handleDeptToggle = (dept) => {
        const currentDepts = [...eventForm.assigned_departments];
        const idx = currentDepts.indexOf(dept);
        let newDepts = []; let newMemberIds = [...eventForm.assigned_member_ids];

        const isMatch = (userDept, targetDept) => userDept?.toString().toUpperCase() === targetDept?.toUpperCase();

        if (idx > -1) {
            newDepts = currentDepts.filter(d => d !== dept);
            const membersToRemove = visibleMembers.filter(u => isMatch(u.department, dept)).map(u => u._id || u.id);
            newMemberIds = newMemberIds.filter(id => !membersToRemove.includes(id));
        } else {
            newDepts = [...currentDepts, dept];
            const membersToAdd = visibleMembers.filter(u => isMatch(u.department, dept)).map(u => u._id || u.id);
            newMemberIds = [...new Set([...newMemberIds, ...membersToAdd])];
        }
        setEventForm({ ...eventForm, assigned_departments: newDepts, assigned_member_ids: newMemberIds });
    };

    const renderEventTile = (ev) => {
        const s = ev.extendedProps.status;
        const type = ev.extendedProps.type;
        const isCreator = ev.extendedProps.isCreator;
        const color = ev.extendedProps.dotColor;

        const statusBadges = {
            completed: <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-md text-[8px] font-black uppercase tracking-widest border border-emerald-200">Completed</span>,
            reschedule: <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded-md text-[8px] font-black uppercase tracking-widest border border-amber-200">Rescheduled</span>,
            canceled: <span className="px-2 py-0.5 bg-rose-100 text-rose-700 rounded-md text-[8px] font-black uppercase tracking-widest border border-rose-200">Canceled</span>,
            // Todos only: the due date/time passed with the todo still pending. Written by the
            // backend sweep (todo_status_service), so it is a real stored status, not a
            // render-time guess — the counts and filters below read the same value.
            overdue: <span className="px-2 py-0.5 bg-rose-100 text-rose-700 rounded-md text-[8px] font-black uppercase tracking-widest border border-rose-200 flex items-center gap-1"><AlertCircle size={8} /> Overdue</span>,
            schedule: <span className="px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-md text-[8px] font-black uppercase tracking-widest border border-indigo-100">Scheduled</span>
        };

        return (
            <motion.div key={ev.id} layout 
                className={`group relative rounded-[24px] border p-4 hover:shadow-xl hover:shadow-black/5 transition-all overflow-hidden ${s === 'completed' ? 'opacity-50' : ''}`}
                style={{ 
                    background: isCreator ? 'var(--input-bg)' : (type === 'task' ? 'rgba(225, 29, 72, 0.03)' : 'rgba(13, 148, 136, 0.03)'),
                    borderColor: isCreator ? 'var(--border)' : (type === 'task' ? 'rgba(225, 29, 72, 0.2)' : 'rgba(13, 148, 136, 0.2)')
                }}
            >
                <div className="absolute top-0 right-0 w-1.5 h-full" style={{ background: color }} />
                <div className="flex items-start justify-between mb-2">
                    <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                                {type === 'todo' ? <ClipboardList size={10} style={{ color: '#8b5cf6' }} /> :
                                 type === 'task' ? <CheckCircle size={10} style={{ color: isCreator ? '#f97316' : '#e11d48' }} /> :
                                 type === 'orm_reminder' ? <Layers size={10} className="text-amber-600" /> :
                                 <Activity size={10} style={{ color: isCreator ? '#6366f1' : '#0d9488' }} />}
                                {type === 'orm_reminder' ? 'ORM REMINDER' : type}
                            </div>
                            {statusBadges[s] || statusBadges.schedule}
                            {type === 'orm_reminder' && <span className="px-2 py-0.5 bg-amber-500 text-white rounded-md text-[8px] font-black uppercase tracking-widest border border-amber-600">Strategic</span>}
                            {!isCreator && <span className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded-md text-[8px] font-black uppercase tracking-widest border border-slate-200 flex items-center gap-1"><UserCircle2 size={8}/> Assigned</span>}
                        <h4 className="text-[14px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors pr-10 leading-tight">{ev.title}</h4>
                    </div>
                </div>
                <div className="flex flex-col gap-1.5 text-[10px] font-bold text-[var(--text-muted)] mt-2 border-t border-[var(--border)] pt-2 border-dashed">
                    <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1 opacity-60"> <Clock size={11} /> {type === 'todo' ? 'Due:' : 'Deadline:'} </span>
                        {/* Todos render in the user's own timezone so the card matches the date
                            they picked; sessions/tasks keep the existing IST rendering. */}
                        {/* The todo's own stored instant, not its all-day grid date — the grid
                            entry carries no time, so reading it here would drop the 11:59 PM. */}
                        <span className="text-[var(--text-main)]">{type === 'todo' ? formatTodoShort(todoDueRaw(ev), ev.extendedProps?.all_day) : formatShortIST(ev.start)}</span>
                    </div>
                    {ev.extendedProps.completed_at && (
                        <div className="flex items-center justify-between text-emerald-600 bg-emerald-500/5 px-2 py-0.5 rounded-md">
                            <span className="flex items-center gap-1 uppercase text-[8px] font-black"> <CheckCircle size={11} /> Completed: </span>
                            <span className="font-black italic">{formatShortIST(ev.extendedProps.completed_at)}</span>
                        </div>
                    )}
                    <div className="flex items-center gap-2 mt-0.5">
                        {ev.extendedProps.target_staff_id?.length > 0 && (
                            <div className="flex items-center gap-1 text-orange-600 bg-orange-500/5 px-1.5 py-0.5 rounded border border-orange-500/10 text-[9px]">
                                <UserCircle2 size={11} /> {ev.extendedProps.target_staff_id.map(id => allUsers.find(u => u._id === id || u.id === id)?.full_name).filter(Boolean).join(", ") || "Delegated"}
                            </div>
                        )}
                        {ev.extendedProps.meeting_link && <span className="flex items-center gap-1 text-[var(--accent-indigo)] text-[9px]"> <Video size={11} /> Linked </span>}
                    </div>
                </div>

                <div className="mt-3 flex items-center justify-between border-t border-dashed border-gray-200 pt-3">
                    <div className="flex items-center gap-2">
                        {(canUpdate || ev.extendedProps.isCreator) && (type !== 'event' || !isStaff) && (
                            <button onClick={() => handleQuickAction(ev.id, 'complete')} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[9px] font-black transition-all ${s === 'completed' ? 'bg-green-100/10 text-green-600 border border-green-200' : 'bg-[var(--bg-main)] text-[var(--text-muted)] hover:bg-green-500 hover:text-white border border-[var(--border)]'}`}>
                                {s === 'completed' ? <Check size={12} /> : <CheckCircle size={12} />} {s === 'completed' ? 'Done' : 'Complete'}
                            </button>
                        )}
                        <button onClick={() => openEditModal(ev)} className="p-1.5 bg-[var(--bg-main)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-indigo-500/10 rounded-lg transition-all">
                            { ((canUpdate || ev.extendedProps.isCreator) && !(isStaff && type === 'event' && s === 'completed')) ? <Edit2 size={12} /> : <Eye size={12} /> }
                        </button>
                    </div>
                    {(canDelete || ev.extendedProps.isCreator) && (
                        <button onClick={() => handleQuickAction(ev.id, 'delete')} className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all opacity-0 group-hover:opacity-100"> <Trash2 size={12} /> </button>
                    )}
                </div>
            </motion.div>
        );
    };

    return (
        <div className="space-y-6 flex flex-col min-h-screen pb-20">

            <div className="flex flex-col gap-3 px-2">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                    <div>
                        <h1 className="text-lg sm:text-xl font-black text-[var(--text-main)] tracking-tight uppercase">
                            Calendar <span className="text-[var(--accent-indigo)] px-1 hidden sm:inline">•</span>
                            <span className="hidden sm:inline">{currentViewDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</span>
                        </h1>
                        <p className="text-[11px] text-[var(--text-muted)] font-bold italic tracking-wide hidden sm:block">Elite session governance & operational accountability engine.</p>
                    </div>
                </div>

                {/* Controls Row - scrollable on mobile */}
                <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
                    {/* Focus Toggle */}
                    {(role === 'superadmin' || role === 'admin' || role === 'clientadmin') && (
                        <div className="flex items-center gap-1 p-1 bg-white/40 backdrop-blur-md border border-white/40 rounded-xl shadow-sm shrink-0">
                             <button onClick={() => setViewMode('personal')} className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${viewMode === 'personal' ? 'bg-[var(--accent-indigo)] text-white shadow-lg shadow-indigo-100' : 'text-[var(--text-muted)]'}`}>
                                 MY
                             </button>
                             <button onClick={() => setViewMode('team')} className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${viewMode === 'team' ? 'bg-orange-600 text-white shadow-lg shadow-orange-100' : 'text-[var(--text-muted)]'}`}>
                                 TEAM
                             </button>
                        </div>
                    )}

                    {/* View Mode Toggle */}
                    <div className="flex items-center bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-1 shadow-sm shrink-0">
                        {['dayGridMonth', 'timeGridWeek', 'timeGridDay', 'multiMonthYear'].map((view) => (
                            <button
                                key={view}
                                onClick={() => {
                                    setViewName(view);
                                    calendarRef.current.getApi().changeView(view);
                                }}
                                className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${viewName === view ? 'bg-[var(--accent-indigo)] text-white shadow-lg shadow-indigo-100' : 'text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)]'}`}
                            >
                                {view === 'dayGridMonth' ? 'Mo' : view === 'timeGridWeek' ? 'Wk' : view === 'timeGridDay' ? 'Dy' : 'Yr'}
                            </button>
                        ))}
                    </div>

                    {/* Today + Nav */}
                    <button onClick={() => calendarRef.current.getApi().today()} className="shrink-0 h-9 px-3 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] rounded-xl text-[11px] font-black hover:border-[var(--accent-indigo)] transition-all">Today</button>
                    <div className="flex items-center bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-1 shadow-sm shrink-0">
                        <button onClick={() => calendarRef.current.getApi().prev()} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ChevronLeft size={15} /></button>
                        <button onClick={() => calendarRef.current.getApi().next()} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ChevronRight size={15} /></button>
                    </div>

                    {/* Month label on mobile only */}
                    <span className="text-[11px] font-black text-[var(--text-muted)] shrink-0 sm:hidden">
                        {currentViewDate.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}
                    </span>
                </div>
            </div>

            <div ref={calendarShellRef}
                className="flex-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] md:rounded-[40px] overflow-hidden shadow-2xl p-3 md:p-6 fc-theme-orlando relative">
                {loading && (<div className="absolute inset-0 flex items-center justify-center bg-[var(--bg-card)]/80 backdrop-blur-sm z-[100]"> <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div> </div>)}
                {/* ─── Stats Dashboard — one container per module, side by side ─── */}
                {/* flex-wrap + flex-1 (rather than a fixed grid) is what keeps the row gap-free:
                    3 containers share the row on desktop, 2 per row on tablet with the third
                    growing to full width, 1 per row on mobile — and when the Task & Delegation
                    container is hidden the remaining two expand to fill the space on their own.
                    Equal height comes free from the flex row's default `align-items: stretch`. */}
                <div className="flex flex-wrap items-stretch gap-3 mb-6">
                    {currentMonthStats.map(group => (
                        <div key={group.key} className="flex-1 min-w-[260px] flex flex-col gap-2.5 p-3 md:p-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-[24px]">
                            <div className="flex items-center gap-2">
                                <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] whitespace-nowrap">{group.label}</span>
                                <span className="flex-1 h-px bg-[var(--border)]" />
                            </div>
                            {/* Two columns inside every container so the cards line up across all
                                three. A container with an odd number of cards lets its last card
                                span both columns, so there is never a hole in the grid. */}
                            <div className="grid grid-cols-2 gap-2.5 [&>*:last-child:nth-child(odd)]:col-span-2">
                                {group.cards.map(s => {
                        const isActive = statFilter?.type === s.filter.type && statFilter?.status === s.filter.status;
                        const colorMap = {
                            indigo: 'bg-indigo-50 border-indigo-100 text-indigo-700 active:bg-indigo-500 active:text-white',
                            emerald: 'bg-emerald-50 border-emerald-100 text-emerald-700 active:bg-emerald-500 active:text-white',
                            amber: 'bg-amber-50 border-amber-100 text-amber-700 active:bg-amber-500 active:text-white',
                            orange: 'bg-orange-50 border-orange-100 text-orange-700 active:bg-orange-500 active:text-white',
                            slate: 'bg-slate-50 border-slate-100 text-slate-700 active:bg-slate-500 active:text-white',
                            rose: 'bg-rose-50 border-rose-100 text-rose-700 active:bg-rose-500 active:text-white',
                            violet: 'bg-violet-50 border-violet-100 text-violet-700 active:bg-violet-500 active:text-white',
                        };
                        const activeColorMap = {
                            indigo: 'bg-indigo-600 border-indigo-600 text-white ring-4 ring-indigo-100',
                            emerald: 'bg-emerald-600 border-emerald-600 text-white ring-4 ring-emerald-100',
                            amber: 'bg-amber-600 border-amber-600 text-white ring-4 ring-amber-100',
                            orange: 'bg-orange-600 border-orange-600 text-white ring-4 ring-orange-100',
                            slate: 'bg-slate-700 border-slate-700 text-white ring-4 ring-slate-100',
                            rose: 'bg-rose-600 border-rose-600 text-white ring-4 ring-rose-100',
                            violet: 'bg-violet-600 border-violet-600 text-white ring-4 ring-violet-100',
                        };

                        return (
                            <button key={s.id} onClick={() => setStatFilter(isActive ? null : s.filter)}
                                className={`flex flex-col justify-between w-full min-w-0 p-3 rounded-[20px] border-2 transition-all duration-300 transform active:scale-95 text-left ${isActive ? activeColorMap[s.color] : colorMap[s.color]}`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className={`p-1.5 rounded-lg ${isActive ? 'bg-white/20' : 'bg-white shadow-sm'}`}>{s.icon}</div>
                                    <span className="text-[18px] font-black leading-none">{s.count}</span>
                                </div>
                                <span className={`text-[10px] font-black uppercase tracking-widest opacity-80 truncate ${isActive ? 'text-white' : ''}`}>{s.label}</span>
                            </button>
                        );
                                })}
                            </div>
                        </div>
                    ))}
                </div>

                {/* ─── Month Jump Bar ─── */}
                <div className="flex items-center gap-1 mb-6 bg-[var(--input-bg)] p-1.5 rounded-2xl border border-[var(--border)] overflow-x-auto no-scrollbar">
                    {monthsList.map((m, idx) => {
                        const isCurrentMonth = currentViewDate.getMonth() === idx;
                        return (
                            <button
                                key={m}
                                onClick={() => {
                                    const newDate = new Date(currentViewDate);
                                    newDate.setMonth(idx);
                                    calendarRef.current.getApi().gotoDate(newDate);
                                }}
                                className={`flex-1 min-w-[50px] py-2 rounded-xl text-[11px] font-black transition-all ${
                                    isCurrentMonth 
                                    ? 'bg-[var(--accent-indigo)] text-white shadow-lg' 
                                    : 'text-[var(--text-muted)] hover:bg-white hover:text-[var(--accent-indigo)]'
                                }`}
                            >
                                {m}
                            </button>
                        );
                    })}
                </div>

                <FullCalendar
                    ref={calendarRef} plugins={[dayGridPlugin, timeGridPlugin, listPlugin, multiMonthPlugin, interactionPlugin]}
                    initialView="dayGridMonth" headerToolbar={false} events={filteredEvents} height="auto" selectable={true}
                    datesSet={(arg) => setCurrentViewDate(arg.view.currentStart)}
                    // ─── No phantom bar on the day AFTER the one an entry belongs to ───
                    // A task is published with start == end (its deadline — see anchorOf), so
                    // FullCalendar drops the end and applies its default one-hour duration. A task
                    // due at 23:30 therefore "ends" at 00:30 the next day, and with the default
                    // threshold of 00:00 ANY spill past midnight claims that day: the next cell drew
                    // a second, untitled bar for a task that isn't due then — untitled because it is
                    // the same segment continuing, and the title is rendered once, at its start. It
                    // was a phantom in every other respect too: the day summary for that cell listed
                    // nothing, and clicking the bar opened the PREVIOUS day.
                    // Requiring three hours into the next day keeps a genuinely multi-day session
                    // spanning exactly as before, while a few minutes past midnight no longer does.
                    nextDayThreshold="03:00:00"

                    select={handleDateSelect}
                    eventClick={(info) => openDaySummary(dayKey(info.event.startStr))}
                    dayMaxEvents={3} eventContent={(info) => {
                        const s = info.event.extendedProps.status;
                        const type = info.event.extendedProps.type;
                        const isCreator = info.event.extendedProps.isCreator;
                        const dotColor = info.event.extendedProps.dotColor;
                        const isTask = type === 'task';
                        const isORM = type === 'orm_reminder';
                        const isTodo = type === 'todo';

                        return (
                            <div className={`flex items-center gap-1.5 px-2 py-0.5 max-w-full overflow-hidden group/ev transition-all border border-transparent hover:border-indigo-200/50 ${s === 'completed' ? 'opacity-40 grayscale' : ''} ${info.isStart ? 'rounded-l-lg' : ''} ${info.isEnd ? 'rounded-r-lg' : ''} ${!info.isStart && !info.isEnd ? '' : 'rounded-lg'}`}
                                 style={{ 
                                     background: isORM
                                        ? 'rgba(245, 158, 11, 0.1)'
                                        : isTodo
                                           ? 'rgba(139, 92, 246, 0.08)'
                                           : (isCreator
                                              ? (isTask ? 'rgba(249, 115, 22, 0.08)' : 'rgba(99, 102, 241, 0.08)')
                                              : (isTask ? 'rgba(225, 29, 72, 0.08)' : 'rgba(13, 148, 136, 0.08)')),
                                     marginLeft: info.isStart ? '0' : '-8px',
                                     marginRight: info.isEnd ? '0' : '-8px',
                                 }}>
                                <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: isORM ? '#f59e0b' : dotColor }}></div>
                                {isORM && <span className="px-1.5 py-0.5 bg-amber-500 text-white rounded text-[7px] font-black uppercase tracking-tighter shrink-0">ORM</span>}
                                <span className={`text-[10px] font-black truncate ${isORM ? 'text-amber-700' : isTodo ? 'text-violet-700' : (isTask ? 'text-orange-700' : 'text-indigo-700')}`} style={{ textDecoration: s === 'completed' ? 'line-through' : 'none' }}>
                                    {info.event.title}
                                </span>
                            </div>
                        );
                    }}
                />
            </div>

            {/* ─── Day Summary Modal (Tile View) ─── */}
            <AnimatePresence>
                {showSummary && (
                    <div className="fixed inset-0 z-[190] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowSummary(false)} className="absolute inset-0 bg-black/40 backdrop-blur-[4px]" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[820px] rounded-[32px] shadow-2xl relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[90vh]"
                        >
                            <div className="flex px-6 py-4 items-center justify-between border-b border-[var(--border)] bg-[var(--table-header-bg)]">
                                <div className="flex items-center gap-3">
                                    <div className="p-2.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-xl shadow-inner"> <CalendarIcon size={20} /> </div>
                                    <div>
                                        <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">Day Summary</h2>
                                        <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">
                                            {/* "T00:00:00" forces a LOCAL parse. new Date("2026-07-14") is UTC
                                                midnight and would print the 13th in a negative-offset zone —
                                                i.e. a header contradicting the cell the user just clicked. */}
                                            {summaryDate && new Date(summaryDate + "T00:00:00").toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
                                            {(summaryDate && new Date(summaryDate + "T23:59:59") < new Date()) && <span className="ml-2 text-red-500">[PAST]</span>}
                                        </p>
                                    </div>
                                </div>
                                <button onClick={() => setShowSummary(false)} className="p-2 text-[var(--text-muted)] hover:bg-gray-100 rounded-xl transition-all"> <X size={20} /> </button>
                            </div>

                            <div className="p-6 overflow-y-auto no-scrollbar space-y-8">
                                {/* ─── Section 1: Corporate Sessions ─── */}
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                                        <h3 className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.2em] flex items-center gap-1.5"> <Activity size={14} /> Sessions ({dayEvents.filter(e => e.extendedProps.type === 'event').length}) </h3>
                                        {(canCreate && (!summaryDate || new Date(summaryDate + "T23:59:59") >= new Date() || backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email))) && (
                                            <button onClick={() => openCreateModal('event')} className="flex items-center gap-1.5 px-4 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black shadow-md shadow-indigo-200/40 hover:opacity-90 transition-all uppercase tracking-widest"> <PlusCircle size={12} /> Add Session </button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').map(ev => renderEventTile(ev))}
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').length === 0 && (
                                            <div className="col-span-full py-8 flex flex-col items-center justify-center bg-gray-50/50 rounded-[24px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest">No sessions scheduled.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* ─── Section 2: Personal Todos ─── */}
                                {/* Todos only — the user's own private planning list. The backend
                                    never returns anyone else's todo, and the isCreator guard keeps
                                    that true here too. Delegation tasks live in Task & Delegation. */}
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                                        <h3 className="text-[11px] font-black text-violet-500 uppercase tracking-[0.2em] flex items-center gap-1.5"> <ClipboardList size={14} /> Todos ({dayTodos.length}) </h3>
                                        {(canCreate && (!summaryDate || new Date(summaryDate + "T23:59:59") >= new Date() || backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email))) && (
                                            <button onClick={() => openCreateModal('todo')} className="flex items-center gap-1.5 px-4 py-1.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-lg text-[10px] font-black hover:bg-gray-100 transition-all uppercase tracking-widest"> <PlusCircle size={12} /> Add Todo </button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {dayTodos.map(ev => renderEventTile(ev))}
                                        {dayTodos.length === 0 && (
                                            <div className="col-span-full py-8 flex flex-col items-center justify-center bg-gray-50/50 rounded-[24px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest">No todos listed.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="p-4 border-t border-[var(--border)] bg-[var(--table-header-bg)] flex items-center justify-center gap-3">
                                <Zap size={16} className="text-orange-400" />
                                <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-none">Select a tile above to modify or confirm the session architect.</p>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>

            {/* ─── Event Architect Modal (Create/Edit) ─── */}
            <AnimatePresence>
                {showModal && (
                    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowModal(false)} className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[780px] rounded-[32px] shadow-[0_50px_100px_-20px_rgba(0,0,0,0.5)] relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[95vh]"
                        >
                            <div className="flex px-6 py-4 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-main)]">
                                <div className="flex items-center gap-3">
                                    <div className={`w-2.5 h-2.5 rounded-full animate-pulse ${eventForm.status === 'completed' ? 'bg-green-500' : 'bg-indigo-500'}`} />
                                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)]"> 
                                        {isEdit ? `Edit Operation [${eventForm.status}]` : (eventForm.type === 'todo' ? 'Personal Todo' : (eventForm.type === 'task' ? 'Architect Tasks' : 'Architect Session'))}
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    {(isEdit && (canUpdate || eventForm.isCreator)) && eventForm.status !== 'completed' && (
                                        <div className="flex items-center bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-1 shrink-0">
                                            {/* Staff cannot mark as completed from here, but can cancel/reschedule */}
                                            {(!isStaff) && (
                                                <button onClick={() => setEventForm({ ...eventForm, status: 'completed' })} className={`p-2 rounded-lg transition-all ${eventForm.status === 'completed' ? 'bg-green-500 text-white shadow-lg' : 'text-gray-400 hover:text-green-500'}`}> <CheckCircle size={16} /> </button>
                                            )}
                                            {eventForm.type !== 'todo' && (
                                                <button onClick={() => setEventForm({ ...eventForm, status: 'canceled' })} className={`p-2 rounded-lg transition-all ${eventForm.status === 'canceled' ? 'bg-red-500 text-white shadow-lg' : 'text-gray-400 hover:text-red-500'}`}> <Ban size={16} /> </button>
                                            )}
                                            
                                            {canDelete && <button onClick={() => handleQuickAction(currentEventId, 'delete')} className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-500/10 rounded-lg"> <Trash2 size={16} /> </button>}
                                        </div>
                                    )}
                                    {isEdit && !(canUpdate || eventForm.isCreator) && (
                                        <div className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 text-amber-600 rounded-xl text-[8px] font-black uppercase tracking-tighter flex items-center gap-1">
                                            <Lock size={10} /> Read-Only Access
                                        </div>
                                    )}
                                    <button onClick={() => setShowModal(false)} className="p-2 text-[var(--text-muted)] hover:text-[var(--text-main)] rounded-full transition-all"> <X size={20} /> </button>
                                </div>
                            </div>

                            <div className="p-6 overflow-y-auto no-scrollbar space-y-6">
                                {((!isStaff && isEdit && !eventForm.isCreator) || (eventForm.status === 'completed' && eventForm.type === 'event')) ? (
                                    /* ─── SIMPLIFIED LEARNER TICKET VIEW ─── */
                                    <div className="space-y-8 py-4">
                                        <div className="flex flex-col items-center text-center space-y-2">
                                            <div className="w-16 h-16 rounded-full bg-indigo-50 flex items-center justify-center mb-2"> <PlayCircle size={32} className="text-[var(--accent-indigo)]" /> </div>
                                            <h2 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{eventForm.title}</h2>
                                            <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.3em]">Official Training Session</p>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div className="p-5 bg-gray-50/50 border border-dashed border-gray-200 rounded-[24px] space-y-2">
                                                <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest flex items-center gap-1.5"><Building2 size={12}/> Organizational Batch</label>
                                                <p className="text-[13px] font-black text-[var(--text-main)]">{batches.find(b => b._id === eventForm.batch_id)?.name || "N/A"}</p>
                                            </div>
                                            <div className="p-5 bg-gray-50/50 border border-dashed border-gray-200 rounded-[24px] space-y-2">
                                                <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest flex items-center gap-1.5"><LayoutGrid size={12}/> Session Module</label>
                                                <p className="text-[13px] font-black text-[var(--text-main)]">{templates.find(t => t._id === eventForm.session_template_id)?.title || "Custom Curriculum"}</p>
                                            </div>
                                        </div>

                                        <div className="p-6 bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-[32px] flex items-center justify-between shadow-inner">
                                            <div className="flex items-center gap-4">
                                                <div className="p-3 bg-white rounded-2xl text-[var(--accent-indigo)] shadow-sm"> <CalendarDays size={24} /> </div>
                                                <div className="space-y-1">
                                                    <p className="text-[14px] font-black text-[var(--accent-indigo)]">{new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</p>
                                                    <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-widest">{formatIST(eventForm.start)} • Indian Standard Time</p>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="pt-4 flex flex-col items-center space-y-4">
                                            {eventForm.meeting_link ? (
                                                <>
                                                    <a href={eventForm.meeting_link} target="_blank" rel="noreferrer" 
                                                       className="w-full py-4 bg-indigo-600 text-white rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 shadow-xl shadow-indigo-500/40 hover:bg-indigo-700 hover:scale-[1.01] transition-all">
                                                        <Video size={18} /> Join Live Session
                                                    </a>
                                                    <button onClick={() => navigate(`/sessions/${currentEventId}`)} 
                                                       className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest hover:underline">
                                                        View Curriculum & Resources
                                                    </button>
                                                </>
                                            ) : (
                                                <button onClick={() => navigate(`/sessions/${currentEventId}`)} 
                                                   className="w-full py-4 bg-[var(--bg-main)] border border-[var(--border)] text-[var(--accent-indigo)] rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 hover:bg-[var(--accent-indigo-bg)] transition-all">
                                                    <Eye size={18} /> View Session Details
                                                </button>
                                            )}
                                        </div>

                                        <div className="pt-2 border-t border-dashed border-gray-200">
                                            <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest block mb-2">Final Briefing:</label>
                                            <div className="text-[12px] font-medium text-gray-600 leading-relaxed bg-gray-50/50 p-4 rounded-xl italic">
                                                {eventForm.additional_details || "No additional instructions provided for this session."}
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        <div className="space-y-3">
                                    <input autoFocus placeholder={eventForm.type === 'todo' ? "Example: Prepare weekly report" : (eventForm.type === 'task' ? "Task Name" : "Session Title")} className="w-full text-2xl font-black bg-transparent border-b border-dashed border-gray-200 focus:border-[var(--accent-indigo)] outline-none pb-2 text-[var(--text-main)] transition-colors"
                                        value={eventForm.title} onChange={e => setEventForm({ ...eventForm, title: e.target.value })} />

                                    <div className="flex flex-wrap items-center gap-3">
                                        <div className="flex items-center gap-1.5 px-2 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[9px] font-black uppercase tracking-widest rounded-lg">
                                            <Clock size={12} />
                                            {eventForm.type === 'todo'
                                                ? (eventForm.created_at
                                                    ? `Created: ${formatCreatedLocal(eventForm.created_at)}`
                                                    : formatTodoDateTime(eventForm.start, eventForm.all_day))
                                                : `IST • ${formatIST(eventForm.start)}`}
                                        </div>
                                        {isEdit && (
                                            <div className="flex items-center gap-1.5">
                                                <label className="text-[9px] font-black text-gray-400 uppercase">Status:</label>
                                                {(eventForm.isCreator || canUpdate) ? (
                                                    eventForm.type === 'todo' ? (
                                                        <button type="button"
                                                            onClick={() => setEventForm({ ...eventForm, status: eventForm.status === 'completed' ? 'schedule' : 'completed' })}
                                                            className={`flex items-center gap-1 px-3 py-1 rounded-md text-[10px] font-black uppercase transition-all ${eventForm.status === 'completed' ? 'bg-green-500 text-white shadow-lg' : 'bg-[var(--input-bg)] border border-[var(--border)] text-[var(--accent-indigo)] hover:border-green-500 hover:text-green-500'}`}>
                                                            <CheckCircle size={12} /> {eventForm.status === 'completed' ? 'Completed' : 'Mark Complete'}
                                                        </button>
                                                    ) : (
                                                    <select value={eventForm.status} onChange={e => setEventForm({ ...eventForm, status: e.target.value })}
                                                        className="bg-[var(--input-bg)] border border-[var(--border)] rounded-md px-2 py-0.5 text-[10px] font-black text-[var(--accent-indigo)] uppercase outline-none focus:border-[var(--accent-indigo)]">
                                                        <option value="schedule">Scheduled</option>
                                                        <option value="reschedule">Rescheduled</option>
                                                        <option value="canceled">Canceled</option>
                                                        {!isStaff && <option value="completed">Completed</option>}
                                                    </select>
                                                    )
                                                ) : (
                                                    <span className="px-2 py-0.5 bg-gray-100 rounded text-[9px] font-black uppercase text-gray-500">{eventForm.status}</span>
                                                )}
                                            </div>
                                        )}
                                    </div>

                                    {isEdit && eventForm.status === 'reschedule' && (
                                        <div className="p-4 bg-amber-50 border border-amber-200 rounded-2xl space-y-3 shadow-inner">
                                            <div className="flex items-center justify-between">
                                                <label className="text-[9px] font-black text-amber-600 uppercase flex items-center gap-1 underline tracking-widest">Handover Note:</label>
                                                <div className="px-2 py-0.5 bg-amber-500 text-white rounded text-[8px] font-black uppercase">Rescheduled</div>
                                            </div>
                                            <textarea placeholder="Reason for change..."
                                                className="w-full bg-white border border-amber-100 p-3 rounded-xl text-xs font-bold outline-none text-amber-800 placeholder:text-amber-300"
                                                value={eventForm.status_remark} onChange={e => setEventForm({ ...eventForm, status_remark: e.target.value })}
                                            />
                                            <div className="grid grid-cols-2 gap-3">
                                                <div className="space-y-1">
                                                    <label className="text-[8px] font-black text-amber-600 uppercase">New Date</label>
                                                    <input type="date" className="w-full px-3 py-2 bg-white border border-amber-100 rounded-lg text-xs font-black text-amber-900 outline-none"
                                                           value={getLocalDatePart(eventForm.start)}
                                                           onChange={(e) => {
                                                               const newStart = updateDateTimePart(eventForm.start, e.target.value, true);
                                                               const newEnd = updateDateTimePart(eventForm.end, e.target.value, true);
                                                               setEventForm({...eventForm, start: newStart, end: newEnd});
                                                           }} />
                                                </div>
                                                <div className="space-y-1">
                                                    {/* Placeholder to maintain grid if needed, or we can use full width row above */}
                                                </div>
                                            </div>
                                            {!eventForm.all_day && (
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div className="space-y-1">
                                                        <label className="text-[8px] font-black text-amber-600 uppercase">New Start Time</label>
                                                        <input type="time" className="w-full px-3 py-2 bg-white border border-amber-100 rounded-lg text-xs font-black text-amber-900 outline-none"
                                                               value={getLocalTimePart(eventForm.start)}
                                                               onChange={(e) => {
                                                                    const newStart = updateDateTimePart(eventForm.start, e.target.value, false);
                                                                    const duration = new Date(eventForm.end).getTime() - new Date(eventForm.start).getTime();
                                                                    const newEnd = new Date(new Date(newStart).getTime() + duration).toISOString();
                                                                    setEventForm({...eventForm, start: newStart, end: newEnd});
                                                               }} />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[8px] font-black text-amber-600 uppercase">New End Time</label>
                                                        <input type="time" className="w-full px-3 py-2 bg-white border border-amber-100 rounded-lg text-xs font-black text-amber-900 outline-none"
                                                               value={getLocalTimePart(eventForm.end)}
                                                               onChange={(e) => setEventForm({...eventForm, end: updateDateTimePart(eventForm.end, e.target.value, false)})} />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* A todo has no configuration grid at all — it is just a title, details, a due
                    date and an optional reminder (all rendered below, shared with the other
                    types). No category, priority, repeat or delegation, matching a standard
                    personal todo app. */}
                {eventForm.type !== 'todo' && (
                                <div className={`grid grid-cols-1 md:grid-cols-2 gap-6 ${(isEdit && !eventForm.isCreator && !canUpdate && eventForm.isAssigned) ? 'opacity-40 pointer-events-none' : ''}`}>
                                    {isStaff ? (
                                        eventForm.type === 'event' ? (
                                            /* ─── STAFF ARCHITECT: SESSION ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Zap size={12} /> Strategic Strategy</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.session_type} onChange={e => setEventForm({ ...eventForm, session_type: e.target.value })}><option>Core</option><option>Support</option></select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Session Template</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.session_template_id} onChange={e => setEventForm({ ...eventForm, session_template_id: e.target.value })}><option value="">None / Custom</option>{templates.map(t => <option key={t._id} value={t._id}>{t.title}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Building2 size={12} /> Organizational Batch</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.batch_id} onChange={e => setEventForm({ ...eventForm, batch_id: e.target.value, quarter_id: '' })}><option value="">Select Batch</option>{batches.map(b => <option key={b._id} value={b._id}>{b.name}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Link size={12} /> Live Link</label>
                                                        <input placeholder="Zoom / Meet URL" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.meeting_link} onChange={e => setEventForm({ ...eventForm, meeting_link: e.target.value })} />
                                                    </div>
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Layers size={12} /> Quarter Selection</label>
                                                        <select disabled={!eventForm.batch_id} className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold disabled:opacity-50" value={eventForm.quarter_id} onChange={e => setEventForm({ ...eventForm, quarter_id: e.target.value })}><option value="">{eventForm.batch_id ? "Select Quarter" : "Select Batch First"}</option>{quarters.filter(q => q.batch_id === eventForm.batch_id).map(q => <option key={q._id} value={q._id}>{q.name}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><UserCircle2 size={12} /> Coaching Team</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] min-h-[40px] max-h-[80px] overflow-y-auto no-scrollbar">
                                                            {staffMembers.map(c => (
                                                                <div key={c._id} onClick={() => {
                                                                    const current = [...(eventForm.coach_ids || [])];
                                                                    setEventForm({ ...eventForm, coach_ids: current.includes(c._id) ? current.filter(id => id !== c._id) : [...current, c._id] })
                                                                }}
                                                                    className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all flex items-center gap-1.5 ${eventForm.coach_ids?.includes(c._id) ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                                                                    {c.full_name || c.name}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        ) : (
                                            /* ─── STAFF ARCHITECT: TASKS ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Task Category</label>
                                                        <input list="task-categories" placeholder="Category" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.category} onChange={e => setEventForm({ ...eventForm, category: e.target.value })} />
                                                        <datalist id="task-categories">{categories.map(c => <option key={c} value={c} />)}</datalist>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><AlertCircle size={12} /> Critical Level</label>
                                                        <div className="flex gap-2">
                                                            {['Normal', 'High', 'Urgent'].map(p => (
                                                                <button key={p} onClick={() => setEventForm({ ...eventForm, priority: p })} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black transition-all ${eventForm.priority === p ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white text-[var(--text-muted)] border border-[var(--border)]'}`}>{p.toUpperCase()}</button>
                                                            ))}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><ArrowRightLeft size={12} /> Strategic Repetition</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat} onChange={e => setEventForm({ ...eventForm, repeat: e.target.value })}>
                                                            <option value="Does not repeat">Does not repeat</option><option value="Daily">Daily</option><option value="Weekly">Weekly</option><option value="Monthly">Monthly</option><option value="periodic">Periodically</option>
                                                        </select>
                                                    </div>
                                                    {eventForm.repeat === 'periodic' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Clock size={12} /> Repeat in Days</label>
                                                            <input type="number" min="1" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_interval} onChange={e => setEventForm({ ...eventForm, repeat_interval: parseInt(e.target.value) })} />
                                                        </div>
                                                    )}
                                                    {eventForm.repeat !== 'Does not repeat' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><CalendarDays size={12} /> End Repetition</label>
                                                            <input type="date" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_end_date ? eventForm.repeat_end_date.split('T')[0] : ''} onChange={e => setEventForm({ ...eventForm, repeat_end_date: e.target.value })} />
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><UserPlus2 size={12} /> Assignment Delegation</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] max-h-[140px] overflow-y-auto no-scrollbar">
                                                            <div onClick={() => setEventForm({ ...eventForm, target_staff_id: [user._id] })} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.target_staff_id?.includes(user._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>Myself</div>
                                                            {staffMembers.map(m => (
                                                                <div key={m._id} onClick={() => {
                                                                    const current = [...(eventForm.target_staff_id || [])];
                                                                    setEventForm({ ...eventForm, target_staff_id: current.includes(m._id) ? current.filter(id => id !== m._id) : [...current, m._id] })
                                                                }} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.target_staff_id?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>{m.full_name || m.name}</div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        )
                                    ) : (
                                        eventForm.type === 'event' ? (
                                            /* ─── LEARNER ARCHITECT: SESSION ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Link size={12} /> Live Link</label>
                                                        <input placeholder="Zoom / Meet URL" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.meeting_link} onChange={e => setEventForm({ ...eventForm, meeting_link: e.target.value })} />
                                                    </div>
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Users2 size={12} /> Participant (Company)</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] min-h-[40px] max-h-[140px] overflow-y-auto no-scrollbar">
                                                            {companyMembers.map(m => (
                                                                <div key={m._id} onClick={() => {
                                                                    const current = [...(eventForm.assigned_member_ids || [])];
                                                                    setEventForm({ ...eventForm, assigned_member_ids: current.includes(m._id) ? current.filter(id => id !== m._id) : [...current, m._id] })
                                                                }} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.assigned_member_ids?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>{m.full_name || m.name}</div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        ) : (
                                            /* ─── LEARNER ARCHITECT: TASKS ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Task Category</label>
                                                        <input list="task-categories" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.category} onChange={e => setEventForm({ ...eventForm, category: e.target.value })} />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><AlertCircle size={12} /> Critical Level</label>
                                                        <div className="flex gap-2">
                                                            {['Normal', 'High', 'Urgent'].map(p => (
                                                                <button key={p} onClick={() => setEventForm({ ...eventForm, priority: p })} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black transition-all ${eventForm.priority === p ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white text-[var(--text-muted)] border border-[var(--border)]'}`}>{p.toUpperCase()}</button>
                                                            ))}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><ArrowRightLeft size={12} /> Strategic Repetition</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat} onChange={e => setEventForm({ ...eventForm, repeat: e.target.value })}>
                                                            <option value="Does not repeat">Does not repeat</option><option value="Daily">Daily</option><option value="Weekly">Weekly</option><option value="Monthly">Monthly</option><option value="periodic">Periodically</option>
                                                        </select>
                                                    </div>
                                                    {eventForm.repeat === 'periodic' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Clock size={12} /> Repeat in Days</label>
                                                            <input type="number" min="1" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_interval} onChange={e => setEventForm({ ...eventForm, repeat_interval: parseInt(e.target.value) })} />
                                                        </div>
                                                    )}
                                                    {eventForm.repeat !== 'Does not repeat' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><CalendarDays size={12} /> End Repetition</label>
                                                            <input type="date" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_end_date ? eventForm.repeat_end_date.split('T')[0] : ''} onChange={e => setEventForm({ ...eventForm, repeat_end_date: e.target.value })} />
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-4">
                                                    {/* Additional Learner Task Fields can go here */}
                                                </div>
                                            </>
                                        )
                                    )}
                                </div>
                                )}

                                {/* Participant management never applies to a todo — it is personal. */}
                                {eventForm.type !== 'todo' && !(isStaff && eventForm.type === 'task') && (
                                    <div className="space-y-3 p-4 bg-[var(--input-bg)] rounded-2xl border border-[var(--border)] shadow-sm">
                                        <div className="space-y-2">
                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                                                <Users2 size={12} /> {isStaff ? (eventForm.type === 'event' ? `Active Assignment: ${eventForm.assigned_departments.join(", ") || "None"}` : "Participant Scope") : "Participant Management"}
                                            </label>
                                            {(isStaff && eventForm.type === 'event') && (
                                                <div className="flex flex-wrap gap-1">
                                                    {departments.map(dept => (
                                                        <button key={dept} onClick={() => handleDeptToggle(dept)}
                                                            className={`px-3 py-1 rounded-lg text-[9px] font-black border transition-all ${eventForm.assigned_departments.includes(dept) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-sm' : 'bg-white text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                                                            {dept}
                                                        </button>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex flex-wrap gap-1 p-1 min-h-[40px] max-h-[100px] overflow-y-auto no-scrollbar">
                                            {visibleMembers.filter(u => {
                                                if (!isStaff || eventForm.type !== 'event') return true;
                                                if (!eventForm.assigned_departments || eventForm.assigned_departments.length === 0) return true;
                                                return eventForm.assigned_departments.some(dept => u.department?.toString().toUpperCase() === dept.toUpperCase());
                                            }).map(m => (
                                                <div key={m._id} onClick={() => {
                                                    const ids = [...(eventForm.assigned_member_ids || [])];
                                                    setEventForm({ ...eventForm, assigned_member_ids: ids.includes(m._id) ? ids.filter(id => id !== m._id) : [...ids, m._id] })
                                                }}
                                                    className={`px-2 py-0.5 rounded-md text-[9px] font-bold cursor-pointer transition-all flex items-center gap-1.5 ${eventForm.assigned_member_ids?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white shadow-sm border border-[var(--accent-indigo-border)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] opacity-50 border border-dotted border-gray-400'}`}>
                                                    {m.full_name || m.name} <X size={10} className={eventForm.assigned_member_ids?.includes(m._id) ? 'text-white' : 'hidden'} />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div className="space-y-4">
                                    {eventForm.type === 'todo' && (
                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                                            <CalendarDays size={12} /> Due Date / Time
                                        </label>
                                    )}
                                    <div className="flex items-center gap-4 flex-wrap">
                                        {eventForm.type === 'todo' ? (
                                            /* The due DATE is unchanged: still the day the todo was added for,
                                               set authoritatively by the backend. The TIME is now optional and
                                               the user's to pick — leave it blank and the todo stays due at
                                               11:59 PM (IST), exactly as every todo has been until now. */
                                            (() => {
                                              const due = eventForm.end || eventForm.start;
                                              const { hasTime, dateLabel, timeLabel } = todoDueSummary(due);
                                              return (
                                                <div className="flex flex-col gap-1">
                                                  <span className="text-[9px] font-black uppercase tracking-wider text-[var(--text-muted)]">Due</span>
                                                  <div className="flex items-center gap-2 bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)]">
                                                    <Clock size={18} className="text-[var(--accent-indigo)]" />
                                                    <div className="flex flex-col leading-tight">
                                                      <span className="text-[13px] font-black flex items-center gap-1.5">
                                                        {/* Date stays plain, read-only text — nothing about it invites a
                                                            click, so the one interactive thing in the row is unambiguous. */}
                                                        <span className="text-[var(--text-main)]">{dateLabel}</span>
                                                        <span className="text-[var(--text-muted)] font-bold">·</span>
                                                        {/* The time IS the picker: a transparent <input type="time"> sits
                                                            over the label, so clicking it opens the native picker and the
                                                            chosen value replaces the text in place — the same overlay
                                                            pattern the session date field below uses. It is styled as a
                                                            standing chip (tinted, dashed outline, chevron) rather than
                                                            relying on hover, so the affordance is visible before the user
                                                            moves the mouse — which is what was missing. */}
                                                        <span title="Click to change the due time"
                                                          className="relative inline-flex items-center gap-1 px-2 py-0.5 rounded-lg cursor-pointer
                                                            bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]
                                                            border border-dashed border-[var(--accent-indigo-border)]
                                                            hover:border-solid hover:shadow-sm transition-all">
                                                          {timeLabel}
                                                          <ChevronDown size={12} className="opacity-70" />
                                                          <input type="time" aria-label="Due time"
                                                            value={todoDueTimeValue(due)}
                                                            onClick={(e) => { try { e.currentTarget.showPicker(); } catch { /* click still focuses */ } }}
                                                            onChange={(e) => {
                                                                const hhmm = e.target.value;
                                                                // Cleared → back to 11:59 PM, the end-of-day default.
                                                                // `all_day` is the backend's "no time picked" signal.
                                                                const iso = withTodoDueTime(due, hhmm || '23:59');
                                                                setEventForm(f => ({ ...f, start: iso, end: iso, all_day: !hhmm }));
                                                            }}
                                                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" />
                                                        </span>
                                                      </span>
                                                      <span className="text-[9px] font-bold uppercase tracking-wider text-[var(--accent-indigo)]">
                                                        Click the time to change
                                                        <span className="text-[var(--text-muted)] normal-case font-bold">
                                                          {hasTime ? ' — selected time (IST)' : ' — end of the selected day (IST)'}
                                                        </span>
                                                      </span>
                                                    </div>
                                                  </div>
                                                </div>
                                              );
                                            })()
                                        ) : (
                                            <>
                                                <div className="flex items-center gap-2 bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] relative cursor-pointer hover:border-[var(--accent-indigo)] transition-all">
                                                    <CalendarDays size={18} className="text-[var(--accent-indigo)]" />
                                                    <span className="text-[13px] font-black">{new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}</span>
                                                    <input type="date" className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                                           value={getLocalDatePart(eventForm.start)}
                                                           onClick={(e) => { try { e.currentTarget.showPicker(); } catch { /* click still focuses */ } }}
                                                           onChange={(e) => {
                                                               const newStart = updateDateTimePart(eventForm.start, e.target.value, true);
                                                               const newEnd = updateDateTimePart(eventForm.end, e.target.value, true);
                                                               setEventForm({...eventForm, start: newStart, end: newEnd});
                                                           }} />
                                                </div>
                                                <label className="flex items-center gap-3 cursor-pointer bg-[var(--input-bg)] border border-[var(--border)] px-4 py-2.5 rounded-xl shadow-inner group">
                                                    <input type="checkbox" checked={eventForm.all_day} onChange={e => setEventForm({ ...eventForm, all_day: e.target.checked })} className="w-4 h-4 accent-[var(--accent-indigo)]" />
                                                    <span className="text-[11px] font-black uppercase text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] transition-colors">Full Day Block</span>
                                                </label>
                                                {!eventForm.all_day && (
                                                    <div className="flex items-center gap-2 bg-[var(--accent-indigo-bg)] p-1 rounded-xl border border-[var(--border)] shadow-inner">
                                                        <CustomTimePicker
                                                            value={new Date(eventForm.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                                                            onChange={(newTime) => {
                                                                const [hours, minutes] = newTime.split(':');
                                                                const newDate = new Date(eventForm.start);
                                                                newDate.setHours(parseInt(hours), parseInt(minutes));
                                                                setEventForm({ ...eventForm, start: newDate.toISOString() });
                                                            }}
                                                        />
                                                        <ArrowRightLeft size={10} className="text-[var(--accent-indigo)] opacity-40" />
                                                        <CustomTimePicker
                                                            value={new Date(eventForm.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                                                            onChange={(newTime) => {
                                                                const [hours, minutes] = newTime.split(':');
                                                                const newDate = new Date(eventForm.end);
                                                                newDate.setHours(parseInt(hours), parseInt(minutes));
                                                                setEventForm({ ...eventForm, end: newDate.toISOString() });
                                                            }}
                                                        />
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </div>

                                    {/* ─── Frequency (todo only) ───
                                        The Task & Delegation Repeat control, reused as-is: same
                                        options, same repeat_data, same validation. The whole
                                        series is generated on save, up to the (required) End
                                        Date. A todo's due date doubles as the series start, so
                                        the control sits directly under it. */}
                                    {eventForm.type === 'todo' && (
                                        <div className="space-y-3 pt-2">
                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                                                <ArrowRightLeft size={12} /> Frequency
                                            </label>
                                            <TodoRepeatSection form={eventForm} setForm={setEventForm} minEndDate={getLocalDatePart(eventForm.start)} />
                                        </div>
                                    )}
                                </div>
                                <div className="space-y-4 p-5 bg-orange-50/20 rounded-[24px] border border-orange-100 border-dashed">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <Bell size={14} className="text-orange-500" />
                                            <span className="text-[9px] font-black uppercase text-orange-600 tracking-widest">Active Reminders ({eventForm.reminders?.length || 0})</span>
                                        </div>
                                        <button type="button" onClick={() => setShowReminderModal(true)} className="px-3 py-1.5 bg-white border border-orange-100 text-orange-600 rounded-lg text-[9px] font-black hover:bg-orange-500 hover:text-white transition-all">
                                            {eventForm.reminders?.length > 0 ? 'MANAGE' : 'ADD'}
                                        </button>
                                    </div>
                                    {eventForm.reminders?.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5">
                                            {eventForm.reminders.map((r, i) => (
                                                <div key={i} className="px-2 py-1 bg-white border border-gray-100 rounded text-[8px] font-bold text-gray-500 flex items-center gap-1.5">
                                                    {r.reminder_type === 'whatsapp' ? '💬' : r.reminder_type === 'email' ? '📧' : '⚡'}
                                                    {r.offset_minutes}m {r.timing_type}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {eventForm.type === 'todo' ? (
                                    <div className="space-y-2">
                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                                            <FileText size={12} /> Task Details <span className="text-[var(--accent-indigo)]">*</span>
                                        </label>
                                        <textarea placeholder="Example: Review all pending reports before 5 PM." rows={6} className="w-full bg-[var(--input-bg)] p-4 rounded-2xl text-[12px] font-medium border border-[var(--border)] outline-none focus:bg-white transition-all shadow-inner resize-y"
                                            value={eventForm.additional_details} onChange={e => setEventForm({ ...eventForm, additional_details: e.target.value })} />
                                    </div>
                                ) : (
                                    <textarea placeholder={eventForm.type === 'task' ? "Task Details..." : "Instruction..."} rows={3} className="w-full bg-[var(--input-bg)] p-4 rounded-2xl text-[12px] font-medium border border-[var(--border)] outline-none focus:bg-white transition-all shadow-inner"
                                        value={eventForm.additional_details} onChange={e => setEventForm({ ...eventForm, additional_details: e.target.value })} />
                                )}
                                    </>
                                )}
                            </div>

                            {/* ReminderModal is shared by sessions, tasks and todos and defaults every
                                new reminder to parent_type "event" ("set correctly on save"), which
                                this call site never did — so a todo's reminders were stored labelled
                                as event reminders. Stamp the form's own type instead. The backend
                                picks a reminder template from the DOCUMENT type, so this label never
                                selects the template; it just keeps the stored data truthful. */}
                            <ReminderModal
                                isOpen={showReminderModal}
                                onClose={() => setShowReminderModal(false)}
                                reminders={eventForm.reminders}
                                onApply={(reminders) => setEventForm({
                                    ...eventForm,
                                    reminders: reminders.map(r => ({ ...r, parent_type: eventForm.type })),
                                })}
                            />

                            {/* Todo Due date/time — the shared month-grid DATE/TIME calendar. */}
                            <MiniDatePicker
                                isOpen={dueDatePickerOpen}
                                onClose={() => setDueDatePickerOpen(false)}
                                value={eventForm.end}
                                title="Select Due Date"
                                onApply={(iso) => setEventForm(f => ({ ...f, end: iso }))}
                            />

                            {!(isEdit && !isStaff && !eventForm.isCreator) && eventForm.status !== 'completed' && (
                                <div className="p-5 border-t border-[var(--border)] flex justify-between items-center bg-[var(--table-header-bg)]">
                                    <div className="flex items-center gap-3">
                                        <ShieldCheck size={20} className="text-[var(--accent-indigo)] opacity-30" />
                                        <div className="space-y-0">
                                            <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-tight">Digital Authorization</p>
                                            <p className="text-[10px] font-bold text-gray-400 italic leading-tight">Changes sync to calendars instantly.</p>
                                        </div>
                                    </div>
                                    <button onClick={handleSave}
                                        disabled={isEdit && !(user.role === 'superadmin' || user.role === 'admin' || eventForm.isCreator)}
                                        className={`bg-[var(--btn-primary)] text-white px-10 py-3 rounded-xl text-[12px] font-black shadow-xl shadow-indigo-500/30 hover:scale-[1.02] active:scale-[0.98] transition-all tracking-[0.1em] uppercase ${isEdit && !(user.role === 'superadmin' || user.role === 'admin' || eventForm.isCreator) ? 'opacity-20 cursor-not-allowed grayscale' : ''}`}>
                                        {isEdit ? (eventForm.type === 'todo' ? 'Save Todo' : 'Authorize Updates') : (eventForm.type === 'todo' ? 'Create Todo' : (eventForm.type === 'task' ? 'Schedule Task' : 'Schedule Session'))}
                                    </button>
                                </div>
                            )}

                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default CalendarPage;
