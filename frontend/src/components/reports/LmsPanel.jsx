import React, { useState, useEffect, useCallback } from 'react';
import {
  Users, UserCheck, UserX, BookOpen, CheckCircle2, Clock, Percent, Award, Search, ChevronRight,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell, Legend,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { getLmsDashboard, getLmsEmployees } from '../../services/reportApi';
import { truncate } from './chartKit';

const tooltipStyle = {
  borderRadius: '16px', border: '1px solid var(--border)',
  background: 'var(--bg-card)', boxShadow: '0 20px 50px rgba(0,0,0,0.12)', padding: '10px 16px',
};
const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

const Card = ({ title, subtitle, children, className = '' }) => (
  <div className={`bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-5 shadow-sm flex flex-col ${className}`}>
    <div className="mb-3">
      <h4 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">{title}</h4>
      {subtitle && <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">{subtitle}</p>}
    </div>
    <div className="flex-1 w-full min-h-0 min-w-0">{children}</div>
  </div>
);

const Kpi = ({ label, value, icon: Icon }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </div>
);

const EmptyState = ({ text }) => (
  <div className="py-20 text-center">
    <BookOpen size={40} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
    <p className="text-[13px] font-bold text-[var(--text-muted)]">{text}</p>
  </div>
);

const LmsPanel = ({ batchId, period, startDate, endDate, onOpenEmployee }) => {
  const dateParams = (startDate && endDate) ? { startDate, endDate } : {};
  const [data, setData] = useState(null);
  const [employees, setEmployees] = useState({ items: [], total: 0 });
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getLmsDashboard(batchId, { period, ...dateParams });
      setData(d);
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, period, startDate, endDate]);

  const loadEmployees = useCallback(async () => {
    try {
      const res = await getLmsEmployees(batchId, { period, ...dateParams, search, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setEmployees(res);
    } catch (e) { /* handled globally */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, period, startDate, endDate, search, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadEmployees(); }, [loadEmployees]);
  useEffect(() => { setPage(0); }, [batchId, period, startDate, endDate, search]);

  if (loading && !data) {
    // loading skeleton
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="h-[92px] rounded-2xl bg-[var(--input-bg)] animate-pulse" />
        ))}
      </div>
    );
  }
  if (!data) return <EmptyState text="No LMS data available." />;

  const k = data.kpis || {};
  const kpis = [
    { label: 'Total Users', value: k.totalUsers, icon: Users },
    { label: 'Active Users', value: k.activeUsers, icon: UserCheck },
    { label: 'Inactive Users', value: k.inactiveUsers, icon: UserX },
    { label: 'Total Courses', value: k.totalCourses, icon: BookOpen },
    { label: 'Completed', value: k.completedCourses, icon: CheckCircle2 },
    { label: 'In Progress', value: k.inProgressCourses, icon: Clock },
    { label: 'Completion %', value: k.completionRate != null ? `${k.completionRate}%` : null, icon: Percent },
    { label: 'Avg Score', value: k.avgScore != null ? `${k.avgScore}%` : null, icon: Award },
    { label: 'Performance Index', value: k.performanceIndex, icon: Award },
    { label: 'Assigned Courses', value: k.assignedCourses, icon: BookOpen },
  ];

  const hasData = (k.totalUsers || 0) > 0 || (k.totalCourses || 0) > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] px-3 py-1.5 rounded-lg">
          {data.lms?.name}
        </span>
        <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase">LMS Report (Batch)</span>
      </div>

      {!hasData ? (
        <EmptyState text="This LMS has no users or courses in the selected period." />
      ) : (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {kpis.map((kp) => <Kpi key={kp.label} {...kp} />)}
          </div>

          {/* Charts row 1 */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            <Card title="Course Completion Trend" subtitle="Completed courses / month" className="md:col-span-2 xl:col-span-2 h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.monthly || []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10, fontWeight: 800 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Line type="monotone" dataKey="completed" name="Completed" stroke="var(--accent-green)" strokeWidth={3} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Active vs Inactive" subtitle="User status" className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.activeVsInactive || []} innerRadius={50} outerRadius={85} paddingAngle={5} dataKey="value" stroke="none">
                    {(data.activeVsInactive || []).map((e, i) => <Cell key={i} fill={e.color} />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '9px', fontWeight: 900, textTransform: 'uppercase' }} />
                </PieChart>
              </ResponsiveContainer>
            </Card>
          </div>

          {/* Charts row 2 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <Card title="Monthly Learning Activity" subtitle="Attendance events / month" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.monthly || []}>
                  <defs>
                    <linearGradient id="lmsAct" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--accent-indigo)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--accent-indigo)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="activity" stroke="var(--accent-indigo)" strokeWidth={3} fill="url(#lmsAct)" />
                </AreaChart>
              </ResponsiveContainer>
            </Card>
            <Card title="User Enrollment Trend" subtitle="Cumulative users" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.enrollment || []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Line type="monotone" dataKey="cumulative" name="Users" stroke="var(--accent-indigo)" strokeWidth={3} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </Card>
          </div>

          {/* Charts row 3 */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            <Card title="Completion vs Pending" subtitle="Courses" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.completionVsPending || []} innerRadius={50} outerRadius={85} paddingAngle={5} dataKey="value" stroke="none">
                    {(data.completionVsPending || []).map((e, i) => <Cell key={i} fill={e.color} />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '9px', fontWeight: 900, textTransform: 'uppercase' }} />
                </PieChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Score Distribution" subtitle="Assessment %" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.scoreDistribution || []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 9 }} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 9 }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--input-bg)' }} />
                  <Bar dataKey="value" fill="var(--accent-indigo)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Assignment vs Completion" subtitle="Tasks / month" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.monthly || []}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 9 }} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 9 }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '9px', fontWeight: 900, textTransform: 'uppercase' }} />
                  <Bar dataKey="assigned" fill="var(--accent-indigo)" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="assignCompleted" name="completed" fill="var(--accent-green)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>

          {/* Charts row 4 */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            <Card title="Top Performing Users" subtitle="By score" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.topPerformers || []} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text-muted)' }} />
                  <YAxis type="category" dataKey="name" width={90} tickFormatter={truncate} tick={{ fontSize: 10, fill: 'var(--text-muted)', fontWeight: 800 }} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--input-bg)' }} />
                  <Bar dataKey="score" fill="var(--accent-green)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Top Departments" subtitle="By score" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.topDepartments || []} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text-muted)' }} />
                  <YAxis type="category" dataKey="name" width={90} tickFormatter={truncate} tick={{ fontSize: 10, fill: 'var(--text-muted)', fontWeight: 800 }} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--input-bg)' }} />
                  <Bar dataKey="score" fill="var(--accent-indigo)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Top Courses" subtitle="By attendance" className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.topCourses || []} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" opacity={0.3} />
                  <XAxis type="number" tick={{ fontSize: 9, fill: 'var(--text-muted)' }} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={96} tickFormatter={truncate} tick={{ fontSize: 9, fill: 'var(--text-muted)', fontWeight: 700 }} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--input-bg)' }} />
                  <Bar dataKey="attendance" fill="var(--accent-orange)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>

          {/* Users table */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
              <div>
                <h4 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">LMS Users</h4>
                <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">Click a user for the full report</p>
              </div>
              <div className="relative min-w-[220px]">
                <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search user..."
                  className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[820px]">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    {['#', 'User', 'Dept', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Attendance', 'Assessment', 'Score', ''].map((h) => (
                      <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(employees.items || []).length === 0 ? (
                    <tr><td colSpan={11} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No users found for this LMS.</td></tr>
                  ) : employees.items.map((e) => (
                    <tr key={e.id} onClick={() => onOpenEmployee(e.id)}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                      <td className="px-4 py-3 text-[13px] font-black text-[var(--text-muted)]">{e.rank}</td>
                      <td className="px-4 py-3">
                        <p className="text-[13px] font-bold text-[var(--text-main)]">{e.name}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">{e.email}</p>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{e.department}</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.assigned}</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{e.completed}</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-orange)]">{e.pending}</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{e.overdue}</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.attendanceRate}%</td>
                      <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.avgAssessment}%</td>
                      <td className="px-4 py-3 text-[14px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.score}</td>
                      <td className="px-4 py-3 text-[var(--text-muted)]"><ChevronRight size={16} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {employees.total > PAGE_SIZE && (
              <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
                <p className="text-[11px] font-bold text-[var(--text-muted)]">
                  {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, employees.total)} of {employees.total}
                </p>
                <div className="flex items-center gap-2">
                  <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
                  <button disabled={(page + 1) * PAGE_SIZE >= employees.total} onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default LmsPanel;
