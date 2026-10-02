import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Navigate } from 'react-router-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ChevronLeft, Mail, Building2, Shield, CheckCircle2, Clock, AlertTriangle,
  ListTodo, Award, Timer, X, GitBranch, CalendarDays, Layers, GraduationCap,
  Download, ChevronDown, FileDown, FileSpreadsheet, FileText,
} from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import {
  getEmployeeReport, getEmployeeAssignments, getEmployeeAssessments,
  getEmployeeAttendance, getEmployeeTimeline, exportEmployeeReport,
} from '../services/reportApi';

const tooltipStyle = {
  borderRadius: '16px', border: '1px solid var(--border)',
  background: 'var(--bg-card)', boxShadow: '0 20px 50px rgba(0,0,0,0.12)', padding: '10px 16px',
};
const STATUS_COLOR = {
  pending: 'var(--accent-orange)', accepted: 'var(--accent-indigo)', in_progress: 'var(--accent-indigo)',
  dependent_on_others: 'var(--accent-yellow)', blocked: 'var(--accent-red)',
  verification: 'var(--accent-yellow)', dependency_completed: 'var(--accent-indigo)',
  completed: 'var(--accent-green)',
};

const fmtDate = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-US', { day: '2-digit', month: 'short', year: 'numeric' });
};
const fmtDateTime = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-US', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

const Summary = ({ label, value, icon: Icon, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} style={{ color: color || 'var(--accent-indigo)' }} />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
    </div>
    <p className="text-2xl font-black" style={{ color: color || 'var(--text-main)' }}>{value ?? '—'}</p>
  </div>
);

const TABS = ['Assignments', 'Assessments', 'Attendance'];

const EmployeeReport = () => {
  const { userId } = useParams();
  const { user } = useAuth();
  const { showError } = useNotification();
  const navigate = useNavigate();

  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState('Assignments');
  const [assignments, setAssignments] = useState({ items: [], total: 0 });
  const [assessments, setAssessments] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [timeline, setTimeline] = useState(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');
  const exportRef = useRef(null);
  const PAGE_SIZE = 15;

  // Close export dropdown on outside click
  useEffect(() => {
    if (!exportOpen) return undefined;
    const handler = (e) => { if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [exportOpen]);

  const doExport = async (format) => {
    setExportOpen(false);
    setExporting(format);
    try {
      await exportEmployeeReport(userId, { format });
    } catch (err) {
      showError('Export failed');
    } finally {
      setExporting('');
    }
  };

  const loadCore = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getEmployeeReport(userId, {});
      setDetail(d);
    } catch (err) {
      showError('Failed to load employee report');
      navigate('/admin/reports');
    } finally {
      setLoading(false);
    }
  }, [userId, navigate, showError]);

  useEffect(() => { loadCore(); }, [loadCore]);

  useEffect(() => {
    if (tab === 'Assignments') {
      getEmployeeAssignments(userId, { skip: page * PAGE_SIZE, limit: PAGE_SIZE }).then(setAssignments).catch(() => {});
    } else if (tab === 'Assessments' && assessments.length === 0) {
      getEmployeeAssessments(userId).then((r) => setAssessments(r.items || [])).catch(() => {});
    } else if (tab === 'Attendance' && attendance.length === 0) {
      getEmployeeAttendance(userId).then((r) => setAttendance(r.items || [])).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, page, userId]);

  const openTimeline = async (taskId, title) => {
    setTimelineLoading(true);
    setTimeline({ title, events: [] });
    try {
      const res = await getEmployeeTimeline(userId, taskId);
      setTimeline({ title: res.title || title, events: res.events || [] });
    } catch (err) {
      showError('Failed to load timeline');
      setTimeline(null);
    } finally {
      setTimelineLoading(false);
    }
  };

  if (user && !['superadmin', 'admin'].includes(user.role)) return <Navigate to="/" replace />;
  if (loading && !detail) return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading employee report…</div>;
  if (!detail) return null;

  const e = detail.employee;
  const s = detail.summary;

  return (
    <div className="space-y-8 pb-16">
      <div className="flex items-center justify-between gap-3">
        <button onClick={() => navigate('/admin/reports')}
          className="group flex items-center gap-2 text-[12px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
          <ChevronLeft size={16} className="group-hover:-translate-x-1 transition-transform" /> Back to Reports
        </button>

        {/* Single Export dropdown (CSV / Excel / PDF) for this employee's report */}
        <div className="relative" ref={exportRef}>
          <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting} title="Export"
            className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export'}
            <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
          </button>
          {exportOpen && (
            <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-[60] overflow-hidden">
              {[['csv', 'CSV', FileDown], ['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText]].map(([fmt, label, Icon]) => (
                <button key={fmt} onClick={() => doExport(fmt)} disabled={!!exporting}
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all disabled:opacity-50">
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center gap-5">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-white font-black text-xl shrink-0" style={{ background: 'var(--avatar-bg)' }}>
          {e.name?.charAt(0)?.toUpperCase() || '?'}
        </div>
        <div className="flex-1">
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{e.name}</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-[12px] font-bold text-[var(--text-muted)]">
            {e.email && <span className="flex items-center gap-1.5"><Mail size={13} /> {e.email}</span>}
            <span className="flex items-center gap-1.5"><Shield size={13} /> {e.role || '—'}</span>
            {e.company && <span className="flex items-center gap-1.5"><Building2 size={13} /> {e.company}</span>}
            <span className="flex items-center gap-1.5"><GraduationCap size={13} /> {e.department}</span>
            {e.batch && <span className="flex items-center gap-1.5"><Layers size={13} /> {e.batch}</span>}
            <span className="flex items-center gap-1.5"><CalendarDays size={13} /> Joined {fmtDate(e.joiningDate)}</span>
          </div>
        </div>
        <div className="text-center px-6 py-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <p className="text-3xl font-black text-[var(--accent-indigo)]">{s.productivity}</p>
          <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mt-1">{s.rating}</p>
        </div>
      </div>

      {/* Learning summary */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        <Summary label="Sessions" value={s.totalSessions} icon={CalendarDays} />
        <Summary label="Assignments" value={s.assigned} icon={ListTodo} />
        <Summary label="Completed" value={s.completed} icon={CheckCircle2} color="var(--accent-green)" />
        <Summary label="Overdue" value={s.overdue} icon={AlertTriangle} color="var(--accent-red)" />
        <Summary label="Attendance %" value={`${s.attendanceRate}%`} icon={Clock} color="var(--accent-indigo)" />
        <Summary label="Avg Assessment" value={`${s.avgAssessment}%`} icon={Award} color="var(--accent-orange)" />
      </div>

      {/* Performance graphs */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <div className="md:col-span-2 xl:col-span-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm h-[300px] flex flex-col">
          <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight mb-4">Monthly Progress</h3>
          <div className="flex-1 min-h-0 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={detail.trends || []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 800 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase' }} />
                <Line type="monotone" dataKey="completed" stroke="var(--accent-green)" strokeWidth={3} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="avgScore" name="Avg Score" stroke="var(--accent-indigo)" strokeWidth={3} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm h-[300px] flex flex-col">
          <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight mb-4">Attendance Trend</h3>
          <div className="flex-1 min-h-0 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={detail.trends || []}>
                <defs>
                  <linearGradient id="erAtt" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-green)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--accent-green)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="attendance" stroke="var(--accent-green)" strokeWidth={3} fill="url(#erAtt)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl w-fit">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${
              tab === t ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
            {t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] overflow-hidden shadow-sm">
        {tab === 'Assignments' && (
          <>
            <div className="p-4 border-b border-[var(--border)]">
              <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">
                Started/Approved not tracked in current workflow → shown “—”. Click a row for the timeline.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[1000px]">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {['Assignment', 'Module', 'Assigned By', 'Assigned', 'Due', 'Started', 'Completed', 'Approved', 'Status', 'Priority', 'Score', ''].map((h) => (
                      <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(assignments.items || []).length === 0 ? (
                    <tr><td colSpan={12} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No assignments in this period.</td></tr>
                  ) : assignments.items.map((t) => (
                    <tr key={t.id} onClick={() => openTimeline(t.id, t.title)}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)] max-w-[200px] truncate">{t.title}</td>
                      <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.module}</td>
                      <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.assignedBy || '—'}</td>
                      <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.assignedDate)}</td>
                      <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.dueDate)}</td>
                      <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.startedDate)}</td>
                      <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.completedDate)}</td>
                      <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.approvedDate)}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider" style={{ color: STATUS_COLOR[t.status], background: 'var(--input-bg)' }}>{t.statusLabel}</span>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.priority}</td>
                      <td className="px-4 py-3 text-[13px] font-black text-[var(--text-main)]">{t.score ?? '—'}</td>
                      <td className="px-4 py-3 text-[var(--text-muted)]"><GitBranch size={14} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {assignments.total > PAGE_SIZE && (
              <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
                <p className="text-[11px] font-bold text-[var(--text-muted)]">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, assignments.total)} of {assignments.total}</p>
                <div className="flex items-center gap-2">
                  <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
                  <button disabled={(page + 1) * PAGE_SIZE >= assignments.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
                </div>
              </div>
            )}
          </>
        )}

        {tab === 'Assessments' && (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[720px]">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  {['Assessment', 'Date', 'Score', 'Percentage', 'Result', 'Time Taken'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {assessments.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No assessments recorded.</td></tr>
                ) : assessments.map((a) => (
                  <tr key={a.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{a.name}</td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(a.date)}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-main)]">{a.score ?? '—'}{a.totalMarks ? ` / ${a.totalMarks}` : ''}</td>
                    <td className="px-4 py-3 text-[13px] font-black text-[var(--text-main)]">{a.percentage}%</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                        style={{ color: a.passed ? 'var(--accent-green)' : 'var(--accent-red)', background: 'var(--input-bg)' }}>
                        {a.passed ? 'Pass' : 'Fail'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{a.timeTaken ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'Attendance' && (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[720px]">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  {['Session', 'Date', 'Check In', 'Check Out', 'Duration', 'Status'].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {attendance.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No attendance records.</td></tr>
                ) : attendance.map((a, i) => (
                  <tr key={i} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{a.sessionName}</td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(a.date)}</td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{a.checkIn ?? '—'}</td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{a.checkOut ?? '—'}</td>
                    <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{a.duration ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                        style={{ color: a.status === 'present' ? 'var(--accent-green)' : 'var(--accent-red)', background: 'var(--input-bg)' }}>
                        {a.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Timeline drawer */}
      <AnimatePresence>
        {timeline && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex justify-end bg-black/30 backdrop-blur-sm" onClick={() => setTimeline(null)}>
            <motion.div initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 400, damping: 40 }}
              className="w-full max-w-md h-full bg-[var(--bg-card)] border-l border-[var(--border)] p-6 overflow-y-auto no-scrollbar"
              onClick={(ev) => ev.stopPropagation()}>
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight">Activity Timeline</h3>
                  <p className="text-[12px] font-bold text-[var(--text-muted)] mt-1">{timeline.title}</p>
                </div>
                <button onClick={() => setTimeline(null)} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={18} /></button>
              </div>
              {timelineLoading ? (
                <p className="text-[12px] font-bold text-[var(--text-muted)]">Loading…</p>
              ) : timeline.events.length === 0 ? (
                <p className="text-[12px] font-bold text-[var(--text-muted)]">No timeline events recorded.</p>
              ) : (
                <div className="relative pl-6">
                  <div className="absolute left-[7px] top-1 bottom-1 w-0.5 bg-[var(--border)]" />
                  {timeline.events.map((ev, i) => (
                    <div key={i} className="relative pb-6 last:pb-0">
                      <span className="absolute -left-6 top-0.5 w-3.5 h-3.5 rounded-full border-2 border-[var(--bg-card)]"
                        style={{ background: STATUS_COLOR[ev.status] || 'var(--accent-indigo)' }} />
                      <p className="text-[13px] font-black text-[var(--text-main)]">{ev.label}</p>
                      <p className="text-[11px] font-bold text-[var(--text-muted)]">{fmtDateTime(ev.at)}</p>
                      {ev.by && <p className="text-[10px] text-[var(--text-muted)] opacity-70">by {ev.by}</p>}
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default EmployeeReport;
