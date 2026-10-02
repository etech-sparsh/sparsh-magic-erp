import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, AlertTriangle, Building2, Download, ChevronDown, FileDown, FileSpreadsheet, FileText } from 'lucide-react';
import Modal from '../common/Modal';
import EmployeeTable from './EmployeeTable';
import { getCompanyDashboard, exportCompanies } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';

const pct = (v) => (v == null ? '—' : `${v}%`);

const Tile = ({ label, value, color }) => (
  <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-3">
    <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{label}</p>
    <p className="text-xl font-black mt-1" style={{ color: color || 'var(--text-main)' }}>{value ?? '—'}</p>
  </div>
);

// Tab 1 — company-wise aggregated report (real data via the existing company dashboard endpoint,
// filter/date-range aware). Same values as the Company-wise table, plus Active Employees.
const CompanyReportTab = ({ company, params }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError(false); setData(null);
    getCompanyDashboard(company.id, params)
      .then((res) => { if (alive) setData(res); })
      .catch(() => { if (alive) setError(true); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [company.id, params]);

  // Reuse the existing company export (CSV / Excel / PDF), scoped to this company by name.
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');
  const exportRef = useRef(null);
  useEffect(() => {
    if (!exportOpen) return undefined;
    const h = (ev) => { if (exportRef.current && !exportRef.current.contains(ev.target)) setExportOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [exportOpen]);
  const doExport = async (format) => {
    setExportOpen(false); setExporting(format);
    try { await exportCompanies({ format, ...params, search: company.name }); }
    catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  if (loading) return <div className="flex items-center justify-center gap-2 py-14 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 size={16} className="animate-spin" /> Loading company report…</div>;
  if (error) return <div className="flex flex-col items-center py-12 text-center"><AlertTriangle size={34} className="text-[var(--accent-red)] opacity-60 mb-2" /><p className="text-[12px] font-bold text-[var(--accent-red)]">Failed to load this company's report.</p></div>;
  if (!data) return <div className="flex flex-col items-center py-12 text-center"><Building2 size={34} className="text-[var(--text-muted)] opacity-30 mb-2" /><p className="text-[12px] font-bold text-[var(--text-muted)]">No data for this company.</p></div>;

  const k = data.kpis || {};
  const tiles = [
    ['Total Employees', k.totalEmployees],
    ['Active Employees', k.activeUsers, 'var(--accent-green)'],
    ['Total Tasks', k.totalAssignments],
    ['Completed', k.completedAssignments, 'var(--accent-green)'],
    ['Pending', k.pendingAssignments, 'var(--accent-orange)'],
    ['Overdue', k.overdueAssignments, 'var(--accent-red)'],
    ['Attendance %', pct(k.avgAttendance)],
    ['Assessment', pct(k.avgAssessment)],
    ['Completion %', pct(k.completionRate), 'var(--accent-indigo)'],
    ['Courses', k.totalSessions],
    ['Sessions', k.totalSessions],
    ['Productivity', pct(k.productivity)],
    ['Performance', pct(k.productivity), 'var(--accent-indigo)'],
    ['Last Activity', company.lastActivity ? fmtDate(company.lastActivity) : '—'],
  ];

  return (
    <div>
      <div className="flex justify-end mb-3">
        <div className="relative" ref={exportRef}>
          <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting}
            className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export'} <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
          </button>
          {exportOpen && (
            <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-50 overflow-hidden">
              {[['csv', 'CSV', FileDown], ['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText]].map(([fmt, label, Icon]) => (
                <button key={fmt} onClick={() => doExport(fmt)} className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all">
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
        {tiles.map(([label, value, color]) => <Tile key={label} label={label} value={value} color={color} />)}
      </div>
    </div>
  );
};

// Company detail modal with two tabs: Company Report (aggregated) + Employee Report (existing
// EmployeeTable, unchanged). Default = Employee Report (matches prior behavior).
const CompanyModal = ({ company, params, onClose }) => {
  const navigate = useNavigate();
  const [tab, setTab] = useState('employee'); // 'company' | 'employee'

  // Reset to the default tab each time a different company is opened.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (company) setTab('employee'); }, [company?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal isOpen={!!company} onClose={onClose} wide title={`Report · ${company?.name || ''}`}>
      {company && (
        <>
          {/* Tab bar */}
          <div className="flex items-center gap-1 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl w-max mb-4">
            {[['company', 'Company Report'], ['employee', 'Employee Report']].map(([key, label]) => (
              <button key={key} onClick={() => setTab(key)}
                className={`px-4 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${
                  tab === key ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'company' ? (
            <CompanyReportTab company={company} params={params} />
          ) : (
            <EmployeeTable
              embedded
              company={company}
              params={params}
              onOpenEmployee={(id) => navigate(`/members/${id}`)}
            />
          )}
        </>
      )}
    </Modal>
  );
};

export default CompanyModal;
