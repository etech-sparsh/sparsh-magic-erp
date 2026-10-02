import React, { useCallback, useEffect, useState } from 'react';
import { Star, Mail, Phone, FileText, Download } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getCandidates, getCandidateCv } from '../../../services/hrmsApi';

/**
 * HRMS ▸ Shortlisted candidates.
 *
 * A cross-requisition view: everyone currently sitting at any of the statuses that count as
 * "shortlisted" (see PIPELINE_COLUMNS's "shortlisted" column on the server), gathered onto
 * one screen instead of a column buried inside the general Kanban board.
 *
 */
const SHORTLISTED_STATUSES = ['Shortlisted', 'Telephonic Passed'];

const ShortlistedCandidates = () => {
  const { scope } = useHrms();
  const { showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getCandidates({
        ...scope, status: SHORTLISTED_STATUSES.join(','), limit: 500,
      });
      setRows(data?.candidates || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load shortlisted candidates.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  useEffect(() => { load(); }, [load]);

  const downloadResume = async (uk) => {
    try {
      const { data } = await getCandidateCv(uk, scope);
      if (!data?.url) return;
      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.name || 'resume.pdf';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not download the resume.');
    }
  };

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Star}
        title="Shortlisted candidates"
        subtitle={`${rows.length} ${rows.length === 1 ? 'candidate' : 'candidates'} shortlisted, across every requisition`}
        actions={<HrmsScopeBar />}
      />

      {loading ? (
        <HrmsLoading label="Loading shortlisted candidates…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : rows.length === 0 ? (
        <HrmsEmpty icon={Star} title="Nobody is shortlisted yet"
          hint="Candidates appear here once they clear screening on any requisition." />
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[720px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                {['Candidate', 'Requisition', 'Stage', 'Resume'].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.uk} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2.5">
                    <p className="font-semibold text-[var(--text-main)]">{c.candidate_name}</p>
                    <p className="font-mono text-[11px] text-[var(--text-muted)]">{c.uk}</p>
                    <div className="mt-1 flex items-center gap-3 text-[11.5px] text-[var(--text-muted)]">
                      {c.can_email && (
                        <span className="flex items-center gap-1"><Mail size={11} /> {c.can_email}</span>
                      )}
                      {c.can_contact && (
                        <span className="flex items-center gap-1"><Phone size={11} /> {c.can_contact}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[12px] text-[var(--text-main)]">
                    {c.request_no || '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] whitespace-nowrap">
                      {c.application_status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {c.resume?.name ? (
                      <button type="button" onClick={() => downloadResume(c.uk)}
                        className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--accent-indigo)] hover:underline">
                        <FileText size={13} /> CV <Download size={12} />
                      </button>
                    ) : (
                      <span className="text-[12px] text-[var(--text-muted)]">No CV</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default ShortlistedCandidates;
