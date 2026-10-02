import React, { useState, useEffect, useCallback } from 'react';
import {
  Building2, Users, ClipboardList, CheckCircle2, Clock, AlertTriangle, Percent,
  Award, CalendarDays, ChevronRight, FileDown, Search,
} from 'lucide-react';
import { getCompanies, getCompanyEmployees, downloadCsv } from '../../services/reportApi';
import { motion } from 'framer-motion';

const Stat = ({ icon: Icon, label, value, color }) => (
  <div className="flex items-center gap-2">
    <Icon size={13} style={{ color: color || 'var(--text-muted)' }} className="shrink-0" />
    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</span>
    <span className="ml-auto text-[13px] font-black" style={{ color: color || 'var(--text-main)' }}>{value}</span>
  </div>
);

const CompanyCards = ({ params, periodLabel, onViewDetails }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [exporting, setExporting] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getCompanies({ ...params, limit: 300 });
      setRows(res.items || []);
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [params]);

  useEffect(() => { load(); }, [load]);

  const filtered = rows.filter((c) => (c.name || '').toLowerCase().includes(search.toLowerCase()));

  const exportCompany = async (company) => {
    setExporting(company.id);
    try {
      const res = await getCompanyEmployees(company.id, { ...params, limit: 1000 });
      const headers = ['Employee', 'Department', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Completion %', 'Attendance %', 'Assessment %', 'Score'];
      const data = (res.items || []).map((e) => [e.name, e.department, e.assigned, e.completed, e.pending, e.overdue, `${e.completionRate}%`, `${e.attendanceRate}%`, `${e.avgAssessment}%`, e.score]);
      downloadCsv(`company_${(company.name || 'report').replace(/[^a-z0-9]+/gi, '_')}.csv`, headers, data);
    } catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest">{filtered.length} Companies · {periodLabel}</p>
        <div className="relative min-w-[200px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search company..."
            className="w-full pl-9 pr-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-64 rounded-[24px] bg-[var(--input-bg)] animate-pulse" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <Building2 size={40} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
          <p className="text-[13px] font-bold text-[var(--text-muted)]">No companies for this period.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((c, i) => (
            <motion.div key={c.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}
              className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-5 shadow-sm hover:shadow-md transition-all flex flex-col">
              <div className="flex items-start gap-3 mb-4">
                <div className="w-11 h-11 rounded-2xl flex items-center justify-center text-white font-black shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                  {(c.name?.charAt(0) || 'C').toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-[15px] font-black text-[var(--text-main)] truncate">{c.name}</h3>
                  <span className="inline-block mt-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-widest"
                    style={{ color: c.status === 'active' ? 'var(--accent-green)' : 'var(--accent-orange)', background: 'var(--input-bg)' }}>
                    {c.status || 'active'}
                  </span>
                </div>
                <span className="text-[26px] font-black text-[var(--accent-indigo)] leading-none">{c.score}</span>
              </div>

              <div className="grid grid-cols-2 gap-x-4 gap-y-2 flex-1">
                <Stat icon={Users} label="Employees" value={c.employees} />
                <Stat icon={ClipboardList} label="Assigned" value={c.assigned} />
                <Stat icon={CheckCircle2} label="Completed" value={c.completed} color="var(--accent-green)" />
                <Stat icon={Clock} label="Pending" value={c.pending} color="var(--accent-orange)" />
                <Stat icon={AlertTriangle} label="Overdue" value={c.overdue} color="var(--accent-red)" />
                <Stat icon={Percent} label="Completion" value={`${c.completionRate}%`} />
                <Stat icon={Award} label="Assessment" value={`${c.avgAssessment}%`} />
                <Stat icon={CalendarDays} label="Attendance" value={`${c.attendanceRate}%`} />
                <Stat icon={ClipboardList} label="Sessions" value={c.sessions} />
                <Stat icon={CalendarDays} label="Last Activity" value="—" />
              </div>

              <div className="flex items-center gap-2 mt-4 pt-4 border-t border-[var(--border)]">
                <button onClick={() => onViewDetails(c)}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest hover:opacity-90 transition-all">
                  View Details <ChevronRight size={13} />
                </button>
                <button onClick={() => exportCompany(c)} disabled={exporting === c.id} title="Export company report"
                  className="flex items-center gap-1.5 px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-xl text-[10px] font-black uppercase tracking-widest hover:text-[var(--accent-indigo)] transition-all disabled:opacity-50">
                  <FileDown size={13} /> {exporting === c.id ? '...' : 'Export'}
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CompanyCards;
