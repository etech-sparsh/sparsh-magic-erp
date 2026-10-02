import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, ChevronDown, Building2, Download, FileDown, FileSpreadsheet, FileText } from 'lucide-react';
import { getCompanies, exportCompanies } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';
import CompanyModal from './CompanyModal';

const COLS = [
  ['name', 'Company Name'], ['employees', 'Total Emp'], ['activeEmployees', 'Active Emp'],
  ['assigned', 'Total Tasks'], ['completed', 'Completed'], ['pending', 'Pending'], ['overdue', 'Overdue'],
  ['attendanceRate', 'Attendance %'], ['avgAssessment', 'Assessment'], ['completionRate', 'Completion %'],
  ['sessions', 'Courses'], ['sessions2', 'Sessions'], ['score', 'Productivity'], ['performance', 'Performance'],
  ['lastActivity', 'Last Activity'],
];

const CompanyTable = ({ params, expandedId: _expandedId, onToggle: _onToggle }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [modalCompany, setModalCompany] = useState(null);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await getCompanies({ ...params, search, limit: 300 });
      setRows(res.items || []);
    } catch (e) { setError(true); }
    finally { setLoading(false); }
  }, [params, search]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [params, search]);

  const total = rows.length;
  const paged = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap';

  // Export the full company dataset (CSV / Excel / PDF), respecting current filters + search.
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');
  const exportRef = useRef(null);
  useEffect(() => {
    if (!exportOpen) return undefined;
    const h = (e) => { if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [exportOpen]);

  const doExport = async (format) => {
    setExportOpen(false); setExporting(format);
    try { await exportCompanies({ format, ...params, search }); }
    catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
        <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Company-wise Report</h3>
        <div className="flex items-center gap-2">
          <div className="relative" ref={exportRef}>
            <button onClick={() => setExportOpen((o) => !o)} disabled={!total || !!exporting}
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
          <div className="relative min-w-[220px]">
            <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search Company..."
              className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
      </div>

      {error ? (
        <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Failed to load company report.</p>
      ) : loading ? (
        <div className="p-5 space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
      ) : total === 0 ? (
        <div className="py-16 text-center"><Building2 size={38} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No companies for this period.</p></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1300px]">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                <th className="sticky left-0 z-20 bg-[var(--input-bg)] w-[46px] min-w-[46px] px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">#</th>
                {COLS.map(([k, label]) => <th key={k} className={`px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap ${k === 'name' ? 'sticky left-[46px] z-20 bg-[var(--input-bg)]' : ''}`}>{label}</th>)}
                <th className="sticky right-0 z-20 bg-[var(--input-bg)] border-l border-[var(--border)] px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Action</th>
              </tr>
            </thead>
            <tbody>
              {paged.map((c, i) => {
                const isActive = modalCompany?.id === c.id;
                const stickyBg = isActive ? 'bg-[var(--accent-indigo-bg)]' : 'bg-[var(--bg-card)]';
                return (
                  <tr key={c.id} onClick={() => setModalCompany(c)}
                    className={`group border-b border-[var(--border)] last:border-0 cursor-pointer transition-colors ${isActive ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                    <td className={`sticky left-0 z-10 ${stickyBg} group-hover:bg-[var(--input-bg)] w-[46px] min-w-[46px] px-3 py-3 text-[12px] font-black text-[var(--text-muted)]`}>{page * PAGE_SIZE + i + 1}</td>
                    <td className={`${cell} font-black sticky left-[46px] z-10 ${stickyBg} group-hover:bg-[var(--input-bg)]`}>
                      <button onClick={(ev) => { ev.stopPropagation(); setModalCompany(c); }}
                        className="text-left hover:text-[var(--accent-indigo)] hover:underline transition-colors" title="View company report">
                        {c.name}
                      </button>
                    </td>
                    <td className={cell}>{c.employees}</td>
                    <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                    <td className={cell}>{c.assigned}</td>
                    <td className={`${cell} text-[var(--accent-green)]`}>{c.completed}</td>
                    <td className={`${cell} text-[var(--accent-orange)]`}>{c.pending}</td>
                    <td className={`${cell} text-[var(--accent-red)]`}>{c.overdue}</td>
                    <td className={cell}>{c.attendanceRate}%</td>
                    <td className={cell}>{c.avgAssessment}%</td>
                    <td className={cell}>{c.completionRate}%</td>
                    <td className={cell}>{c.sessions}</td>
                    <td className={cell}>{c.sessions}</td>
                    <td className={cell}>{c.score}%</td>
                    <td className={`${cell} text-[var(--accent-indigo)]`}>{c.score}%</td>
                    <td className={`${cell} text-[var(--text-muted)]`}>{fmtDate(c.lastActivity)}</td>
                    <td className={`sticky right-0 z-10 ${stickyBg} group-hover:bg-[var(--input-bg)] border-l border-[var(--border)] px-3 py-3 text-center`}>
                      <span className="text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">View</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
          <p className="text-[11px] font-bold text-[var(--text-muted)]">Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, total)} of {total} entries</p>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
            <button disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
          </div>
        </div>
      )}

      {/* Selected-company Employee-wise Report modal (real data, filter-aware) */}
      <CompanyModal
        company={modalCompany}
        params={params}
        onClose={() => setModalCompany(null)}
      />
    </div>
  );
};

export default CompanyTable;
