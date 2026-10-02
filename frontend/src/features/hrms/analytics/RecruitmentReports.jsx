import React, { useCallback, useEffect, useState } from 'react';
import {
  FileSpreadsheet, Search, Download, ChevronLeft, ChevronRight, AlertTriangle,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getHrmsReport, exportHrmsReport } from '../../../services/hrmsApi';
import { nf } from './analyticsKit';
import { RangePicker, ScopeNotice } from './analyticsKit.jsx';

/**
 * HRMS ▸ detailed reports.
 *
 * The columns are decided by the SERVER, not here — `columns` arrives with each page and
 * this component renders exactly what it is given. That is what makes salary redaction
 * work: a caller without `employee.salary.read` never receives the CTC column, so it is
 * absent from the payload rather than merely hidden in the DOM.
 *
 * Export is a separate capability. A hiring manager can read these tables and cannot
 * download them.
 */

const TABS = [
  ['candidates', 'Candidates'],
  ['requisitions', 'Requisitions'],
  ['interviews', 'Interviews'],
  ['offers', 'Offers'],
  ['onboarding', 'Onboarding'],
];

const BTN =
  'h-9 px-3.5 rounded-lg text-[12.5px] font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

const RecruitmentReports = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [entity, setEntity] = useState('candidates');
  const [range, setRange] = useState({ from: '', to: '' });
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);

  const mayExport = can(CAP.REPORT_EXPORT);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Switching tab or window must reset paging — page 7 of candidates is meaningless once
  // the table becomes offers.
  useEffect(() => { setPage(1); }, [entity, range.from, range.to]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getHrmsReport(entity, {
        ...scope,
        page,
        search: debounced || undefined,
        date_from: range.from || undefined,
        date_to: range.to || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this report.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, entity, page, debounced, range.from, range.to]);

  useEffect(() => { load(); }, [load]);

  const download = async (fmt) => {
    setExporting(true);
    try {
      const result = await exportHrmsReport(entity, {
        ...scope,
        fmt,
        search: debounced || undefined,
        date_from: range.from || undefined,
        date_to: range.to || undefined,
      });
      // Truncation is announced, never silent — a short file that looks complete is worse
      // than no file.
      if (result.truncated) {
        showError(`Exported the first ${nf(result.rows)} of ${nf(result.total)} rows. `
          + 'Narrow the date range to get the rest.');
      } else {
        showSuccess(`Exported ${nf(result.rows)} rows`);
      }
    } catch (err) {
      showError(err?.response?.data?.detail || 'The export failed.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={FileSpreadsheet}
        title="Recruitment reports"
        subtitle={data?.range ? `${data.range.from} to ${data.range.to}` : 'Detailed tables'}
        actions={mayExport && (
          <div className="flex items-center gap-2">
            <button type="button" disabled={exporting || !data?.total}
              onClick={() => download('csv')}
              className={`${BTN} border border-[var(--border)] text-[var(--text-muted)] flex items-center gap-1.5`}>
              <Download size={14} /> CSV
            </button>
            <button type="button" disabled={exporting || !data?.total}
              onClick={() => download('xlsx')}
              className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
              <Download size={14} /> Excel
            </button>
          </div>
        )}
      />
      <HrmsScopeBar />

      <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--border)] pb-2">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" onClick={() => setEntity(key)}
            className={`h-8 px-3 rounded-lg text-[12.5px] font-bold transition-colors ${
              entity === key
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder={`Search ${entity}`} aria-label={`Search ${entity}`}
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <RangePicker value={range} onChange={setRange} />
      </div>

      {data && !data.salary_visible && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-[var(--text-muted)]">
          <AlertTriangle size={12} /> Compensation columns are not included for your role.
        </p>
      )}
      {data?.scoped_to_own_requisitions && <ScopeNotice />}

      {loading && <HrmsLoading label="Loading the report…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && data?.total === 0 && (
        <HrmsEmpty
          icon={FileSpreadsheet}
          title="Nothing to report"
          hint="No rows match this period and search. Try widening the date range."
        />
      )}

      {!loading && !error && !!data?.total && (
        <>
          <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
            <table className="w-full text-[13px] min-w-[820px]">
              <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
                <tr>
                  {data.columns.map((c) => (
                    <th key={c.key}
                      className="text-left px-3 py-2.5 text-[10.5px] font-bold uppercase tracking-widest whitespace-nowrap">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={`${row[data.columns[0].key] || i}`}
                    className="border-t border-[var(--border)] hover:bg-[var(--input-bg)]">
                    {data.columns.map((c) => (
                      <td key={c.key} className="px-3 py-2.5 text-[var(--text-main)] whitespace-nowrap">
                        {row[c.key] === '' || row[c.key] == null
                          ? <span className="text-[var(--text-muted)]">—</span>
                          : String(row[c.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-[12px] text-[var(--text-muted)]">
            <span>
              {nf(data.total)} rows · page {data.page} of {data.pages}
            </span>
            <div className="flex gap-1">
              <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                aria-label="Previous page"
                className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] disabled:opacity-40">
                <ChevronLeft size={15} />
              </button>
              <button type="button" disabled={page >= data.pages}
                onClick={() => setPage((p) => p + 1)} aria-label="Next page"
                className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] disabled:opacity-40">
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default RecruitmentReports;
