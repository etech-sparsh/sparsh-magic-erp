import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronLeft, Users, Briefcase, GraduationCap, CalendarDays, ClipboardList,
  CheckCircle2, Clock, AlertTriangle, Percent, Award, Search, ChevronRight,
} from 'lucide-react';
import { getCompanyDashboard, getCompanyEmployees } from '../../services/reportApi';

const Kpi = ({ label, value, icon: Icon }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </div>
);

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

const CompanyDetail = ({ company, params, periodLabel, onBack, onOpenEmployee }) => {
  const [data, setData] = useState(null);
  const [employees, setEmployees] = useState({ items: [], total: 0 });
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getCompanyDashboard(company.id, params);
      setData(d);
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [company.id, params]);

  const loadEmployees = useCallback(async () => {
    try {
      const res = await getCompanyEmployees(company.id, { ...params, search, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setEmployees(res);
    } catch (e) { /* handled globally */ }
  }, [company.id, params, search, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadEmployees(); }, [loadEmployees]);
  useEffect(() => { setPage(0); }, [search]);

  const k = data?.kpis || {};

  return (
    <div className="space-y-6">
      <button onClick={onBack}
        className="group flex items-center gap-2 text-[12px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
        <ChevronLeft size={16} className="group-hover:-translate-x-1 transition-transform" /> Back to Companies
      </button>

      {/* Company header */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center text-white text-xl font-black shrink-0" style={{ background: 'var(--avatar-bg)' }}>
          {(company.name?.charAt(0) || 'C').toUpperCase()}
        </div>
        <div>
          <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight">{company.name}</h1>
          <p className="text-[12px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Company Report · {periodLabel}</p>
        </div>
      </div>

      {/* Summary KPIs (no charts) */}
      {loading && !data ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array.from({ length: 12 }).map((_, i) => <div key={i} className="h-24 rounded-2xl bg-[var(--input-bg)] animate-pulse" />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <Kpi label="Employees" value={k.totalEmployees} icon={Users} />
          <Kpi label="Coaches" value={k.totalCoaches} icon={Briefcase} />
          <Kpi label="Learners" value={k.totalLearners} icon={GraduationCap} />
          <Kpi label="Sessions" value={k.totalSessions} icon={CalendarDays} />
          <Kpi label="Assigned" value={k.totalAssignments} icon={ClipboardList} />
          <Kpi label="Completed" value={k.completedAssignments} icon={CheckCircle2} />
          <Kpi label="Pending" value={k.pendingAssignments} icon={Clock} />
          <Kpi label="Overdue" value={k.overdueAssignments} icon={AlertTriangle} />
          <Kpi label="Completion %" value={k.completionRate != null ? `${k.completionRate}%` : '—'} icon={Percent} />
          <Kpi label="Attendance %" value={k.avgAttendance != null ? `${k.avgAttendance}%` : '—'} icon={CalendarDays} />
          <Kpi label="Assessment %" value={k.avgAssessment != null ? `${k.avgAssessment}%` : '—'} icon={Award} />
          <Kpi label="Performance" value={k.productivity} icon={Award} />
        </div>
      )}

      {/* Employee list */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
          <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Employees</h3>
          <div className="relative min-w-[220px]">
            <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee..."
              className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[820px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                {['Employee', 'Dept', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Completion %', 'Attendance', 'Assessment', 'Score', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(employees.items || []).length === 0 ? (
                <tr><td colSpan={11} className="px-4 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">No employees found.</td></tr>
              ) : employees.items.map((e) => (
                <tr key={e.id} onClick={() => onOpenEmployee(e.id)}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                  <td className="px-4 py-3">
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{e.name}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">{e.email}</p>
                  </td>
                  <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{e.department}</td>
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.assigned}</td>
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{e.completed}</td>
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-orange)]">{e.pending}</td>
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{e.overdue}</td>
                  <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.completionRate}%</td>
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
            <p className="text-[11px] font-bold text-[var(--text-muted)]">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, employees.total)} of {employees.total}</p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= employees.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CompanyDetail;
