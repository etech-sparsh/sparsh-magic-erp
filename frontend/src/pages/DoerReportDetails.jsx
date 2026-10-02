import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Navigate } from 'react-router-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ChevronLeft, Mail, Building2, Shield, CheckCircle2, Clock, AlertTriangle,
  ListTodo, Award, Timer, X, GitBranch,
} from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, Legend,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import { getDoerDetail, getDoerHistory, getDoerTimeline } from '../services/reportApi';

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
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { day: '2-digit', month: 'short', year: 'numeric' });
};
const fmtDateTime = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const SummaryCard = ({ label, value, icon: Icon, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} style={{ color }} />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
    </div>
    <p className="text-2xl font-black" style={{ color: color || 'var(--text-main)' }}>{value ?? '—'}</p>
  </div>
);

const DoerReportDetails = () => {
  const { doerId } = useParams();
  const { user } = useAuth();
  const { showError } = useNotification();
  const navigate = useNavigate();

  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [timeline, setTimeline] = useState(null); // { title, events } | null
  const [timelineLoading, setTimelineLoading] = useState(false);
  const PAGE_SIZE = 15;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, h] = await Promise.all([
        getDoerDetail(doerId, {}),
        getDoerHistory(doerId, { skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
      ]);
      setDetail(d);
      setHistory(h);
    } catch (err) {
      console.error('Doer detail error:', err);
      showError('Failed to load employee report');
      navigate('/admin/reports');
    } finally {
      setLoading(false);
    }
  }, [doerId, page, navigate, showError]);

  useEffect(() => { load(); }, [load]);

  const openTimeline = async (taskId, title) => {
    setTimelineLoading(true);
    setTimeline({ title, events: [] });
    try {
      const res = await getDoerTimeline(doerId, taskId);
      setTimeline({ title: res.title || title, events: res.events || [] });
    } catch (err) {
      showError('Failed to load timeline');
      setTimeline(null);
    } finally {
      setTimelineLoading(false);
    }
  };

  if (user && !['superadmin', 'admin'].includes(user.role)) return <Navigate to="/" replace />;

  if (loading && !detail) {
    return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading employee report…</div>;
  }
  if (!detail) return null;

  const emp = detail.employee;
  const s = detail.summary;
  const statusPie = [
    { name: 'Completed', value: s.completed, color: 'var(--accent-green)' },
    { name: 'Pending', value: s.pending, color: 'var(--accent-orange)' },
    { name: 'Overdue', value: s.overdue, color: 'var(--accent-red)' },
  ].filter((x) => x.value > 0);

  return (
    <div className="space-y-8 pb-16">
      <button onClick={() => navigate('/admin/reports')}
        className="group flex items-center gap-2 text-[12px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
        <ChevronLeft size={16} className="group-hover:-translate-x-1 transition-transform" /> Back to Reports
      </button>

      {/* Employee header */}
      <div className="flex flex-col md:flex-row md:items-center gap-5">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-white font-black text-xl shrink-0"
          style={{ background: 'var(--avatar-bg)' }}>
          {emp.name?.charAt(0)?.toUpperCase() || '?'}
        </div>
        <div className="flex-1">
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{emp.name}</h1>
          <div className="flex flex-wrap items-center gap-4 mt-1 text-[12px] font-bold text-[var(--text-muted)]">
            {emp.email && <span className="flex items-center gap-1.5"><Mail size={13} /> {emp.email}</span>}
            <span className="flex items-center gap-1.5"><Shield size={13} /> {emp.role || '—'}</span>
            <span className="flex items-center gap-1.5"><Building2 size={13} /> {emp.department}</span>
          </div>
        </div>
        <div className="text-center px-6 py-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <p className="text-3xl font-black text-[var(--accent-indigo)]">{s.score}</p>
          <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mt-1">{s.rating}</p>
        </div>
      </div>

      {/* Task summary */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        <SummaryCard label="Assigned" value={s.assigned} icon={ListTodo} color="var(--text-main)" />
        <SummaryCard label="Completed" value={s.completed} icon={CheckCircle2} color="var(--accent-green)" />
        <SummaryCard label="Pending" value={s.pending} icon={Clock} color="var(--accent-orange)" />
        <SummaryCard label="Overdue" value={s.overdue} icon={AlertTriangle} color="var(--accent-red)" />
        <SummaryCard label="Completion %" value={`${s.completionRate}%`} icon={Award} color="var(--accent-indigo)" />
        <SummaryCard label="Avg Days" value={s.avgCompletionDays ?? '—'} icon={Timer} color="var(--text-main)" />
      </div>

      {/* Trends */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <div className="md:col-span-2 xl:col-span-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm h-[320px] flex flex-col">
          <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight mb-4">Monthly Score Trend</h3>
          <div className="flex-1 min-h-0 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={detail.trends || []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} dy={8} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 900 }} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase' }} />
                <Line type="monotone" dataKey="completed" stroke="var(--accent-green)" strokeWidth={3} dot={{ r: 3 }} animationDuration={1200} />
                <Line type="monotone" dataKey="onTime" name="On Time" stroke="var(--accent-indigo)" strokeWidth={3} dot={{ r: 3 }} animationDuration={1400} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm h-[320px] flex flex-col">
          <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight mb-4">Task Status</h3>
          <div className="flex-1 min-h-0 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={statusPie} innerRadius={55} outerRadius={90} paddingAngle={6} dataKey="value" stroke="none" animationDuration={1400}>
                  {statusPie.map((e, i) => <Cell key={i} fill={e.color} />)}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 900, textTransform: 'uppercase' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Task history */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] overflow-hidden shadow-sm">
        <div className="p-5 border-b border-[var(--border)]">
          <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight">Task & Assignment History</h3>
          <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">
            Started/Approved dates are not tracked in the current workflow — shown as “—”. Click a task for its timeline.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1000px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                {['Task', 'Module', 'Assigned By', 'Assigned', 'Due', 'Started', 'Completed', 'Approved', 'Status', 'Priority', 'Score', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(history.items || []).length === 0 ? (
                <tr><td colSpan={12} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No tasks in this period.</td></tr>
              ) : history.items.map((t) => (
                <tr key={t.id} onClick={() => openTimeline(t.id, t.title)}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)] max-w-[220px] truncate">{t.title}</td>
                  <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.module}</td>
                  <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.assignedBy || '—'}</td>
                  <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.assignedDate)}</td>
                  <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.dueDate)}</td>
                  <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.startedDate)}</td>
                  <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.completedDate)}</td>
                  <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(t.approvedDate)}</td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                      style={{ color: STATUS_COLOR[t.status], background: 'var(--input-bg)' }}>{t.statusLabel}</span>
                  </td>
                  <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{t.priority}</td>
                  <td className="px-4 py-3 text-[13px] font-black text-[var(--text-main)]">{t.score ?? '—'}</td>
                  <td className="px-4 py-3 text-[var(--text-muted)]"><GitBranch size={14} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {history.total > PAGE_SIZE && (
          <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, history.total)} of {history.total}
            </p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= history.total} onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
            </div>
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
              onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between mb-6">
                <div>
                  <h3 className="text-lg font-black text-[var(--text-main)] uppercase italic tracking-tight">Performance Timeline</h3>
                  <p className="text-[12px] font-bold text-[var(--text-muted)] mt-1">{timeline.title}</p>
                </div>
                <button onClick={() => setTimeline(null)} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={18} /></button>
              </div>
              {timelineLoading ? (
                <p className="text-[12px] font-bold text-[var(--text-muted)]">Loading timeline…</p>
              ) : timeline.events.length === 0 ? (
                <p className="text-[12px] font-bold text-[var(--text-muted)]">No timeline events recorded for this task.</p>
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

export default DoerReportDetails;
