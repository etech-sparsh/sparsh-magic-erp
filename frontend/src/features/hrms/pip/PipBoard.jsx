import React, { useCallback, useEffect, useState } from 'react';
import { TrendingDown, Search } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees, initiatePip, listPips, getPip, acknowledgePip, addPipReview, decidePip,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Performance Improvement Plan (BA/Functional Design §22.5).
 *
 * A single list + detail-modal screen, unlike the tabbed boards elsewhere in this module —
 * PIP is one contained workflow (initiate -> acknowledge -> review -> decide), not several
 * related-but-distinct ones the way Movements/Discipline/Absconding/Retirement are.
 *
 * An employee reaches their OWN plan through the same list (hrms_pip_service scopes it to
 * their employee_code) to acknowledge it — granting the acknowledge action without a screen
 * that reaches it would be a dead-end control, so this phase builds the ownership-scoped
 * read alongside it rather than deferring it.
 */

const EmployeePicker = ({ scope, value, onChange }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!debounced.trim() || value) return;
    let live = true;
    Promise.resolve().then(() => { if (live) setSearching(true); });
    getEmployees({ ...scope, search: debounced, limit: 8 })
      .then(({ data }) => { if (live) setOptions(data?.employees || []); })
      .catch(() => { if (live) setOptions([]); })
      .finally(() => { if (live) setSearching(false); });
    return () => { live = false; };
  }, [debounced, value, scope]);

  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border
        border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
        <span className="text-[13px] text-[var(--text-main)] truncate">
          {value.name} <span className="text-[var(--text-muted)]">({value.employee_code})</span>
        </span>
        <button type="button" onClick={() => { onChange(null); setSearch(''); }}
          className="text-[11px] font-bold text-[var(--accent-indigo)] shrink-0">
          Change
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
      <input value={search} placeholder="Search by name or employee code…"
        className={`${FIELD} pl-8`} onChange={(e) => setSearch(e.target.value)} />
      {(searching || options.length > 0) && (
        <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg
          border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
          {searching && <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Searching…</p>}
          {!searching && options.map((o) => (
            <button key={o.user_id} type="button"
              onClick={() => { onChange(o); setOptions([]); }}
              className="block w-full text-left px-3 py-2 text-[12.5px] hover:bg-[var(--input-bg)]">
              <span className="text-[var(--text-main)]">{o.name}</span>
              <span className="block text-[11px] text-[var(--text-muted)]">
                {o.employee_code} · {o.designation || '—'} · {o.employment_status}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      await fn();
      if (successMsg) showSuccess(successMsg);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const PipBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [initiating, setInitiating] = useState(false);
  const [openPipNo, setOpenPipNo] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listPips({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load PIP records.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.pip_no}</span>
      </>
    ) },
    { key: 'dates', label: 'Start / Target End', render: (r) => (
      <span className="text-[var(--text-main)]">{day(r.start_date)} – {day(r.target_end_date)}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.closure_result || r.status)}>{r.closure_result || r.status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenPipNo(r.pip_no)}>Open</Btn>
      </div>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={TrendingDown}
        title="Performance Improvement Plan"
        subtitle="Objectives, support, periodic reviews and the final outcome (§22.5)."
        actions={can(CAP.PIP_MANAGE) && (
          <Btn tone="primary" onClick={() => setInitiating(true)}>
            <TrendingDown size={14} /> Initiate PIP
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading PIP records…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">{r.pip_no}</p>
                  </div>
                  <Chip tone={attLeaveToneFor(r.closure_result || r.status)}>{r.closure_result || r.status}</Chip>
                </div>
                <Facts items={[{ label: 'Start / Target End', value: `${day(r.start_date)} – ${day(r.target_end_date)}` }]} />
                <Btn tone="ghost" onClick={() => setOpenPipNo(r.pip_no)}>Open</Btn>
              </div>
            )}
            keyOf={(r) => r.pip_no} />
        ) : (
          <HrmsEmpty icon={TrendingDown} title="No PIP records"
            hint="A plan you're not authorised to see simply does not appear here." />
        )
      )}

      {initiating && (
        <InitiateModal scope={scope} onClose={() => setInitiating(false)}
          onDone={() => { setInitiating(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openPipNo && (
        <PipDetailModal pipNo={openPipNo} scope={scope} can={can}
          onClose={() => setOpenPipNo(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const InitiateModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [gapStatement, setGapStatement] = useState('');
  const [issueCategory, setIssueCategory] = useState('');
  const [reviewReference, setReviewReference] = useState('');
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [targetEndDate, setTargetEndDate] = useState('');
  const [reviewFrequency, setReviewFrequency] = useState('Monthly');
  const [objective, setObjective] = useState('');
  const [supportAction, setSupportAction] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !gapStatement.trim() || !targetEndDate) {
      showError('Select the employee, describe the gap, and set a target end date.');
      return;
    }
    run(() => initiatePip({
      employee_code: employee.employee_code, gap_statement: gapStatement.trim(),
      issue_category: issueCategory.trim() || undefined,
      review_reference: reviewReference.trim() || undefined,
      start_date: startDate, target_end_date: targetEndDate, review_frequency: reviewFrequency,
      objectives: objective.trim() ? [{ target_standard: objective.trim() }] : [],
      support: supportAction.trim() ? [{ action: supportAction.trim() }] : [],
    }, scope), 'PIP initiated.');
  };

  return (
    <Modal title="Initiate PIP" labelledBy="pip-init-title"
      subtitle="§22.5 steps 215-216." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Initiate'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="pip-gap">Performance Gap *</label>
        <textarea id="pip-gap" rows={2} value={gapStatement} className={TEXTAREA}
          onChange={(e) => setGapStatement(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="pip-category">Issue Category</label>
          <input id="pip-category" value={issueCategory} className={FIELD}
            onChange={(e) => setIssueCategory(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="pip-ref">Review / PSC Reference</label>
          <input id="pip-ref" value={reviewReference} className={FIELD}
            onChange={(e) => setReviewReference(e.target.value)} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="pip-start">Start Date *</label>
          <input id="pip-start" type="date" value={startDate} className={FIELD}
            onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="pip-end">Target End Date *</label>
          <input id="pip-end" type="date" value={targetEndDate} className={FIELD}
            onChange={(e) => setTargetEndDate(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="pip-frequency">Review Frequency</label>
        <select id="pip-frequency" value={reviewFrequency} className={FIELD}
          onChange={(e) => setReviewFrequency(e.target.value)}>
          <option>Weekly</option>
          <option>Bi-weekly</option>
          <option>Monthly</option>
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="pip-objective">Target / Expected Standard</label>
        <input id="pip-objective" value={objective} className={FIELD}
          onChange={(e) => setObjective(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="pip-support">Support / Coaching Action</label>
        <input id="pip-support" value={supportAction} className={FIELD}
          onChange={(e) => setSupportAction(e.target.value)} />
      </div>
    </Modal>
  );
};

const PipDetailModal = ({ pipNo, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState('');
  const [managerComments, setManagerComments] = useState('');
  const [closureResult, setClosureResult] = useState('Successfully Closed');
  const [finalRating, setFinalRating] = useState('');
  const [decisionRemarks, setDecisionRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getPip(pipNo, scope);
      setDetail(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this PIP.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipNo]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal title={pipNo} labelledBy="pip-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading PIP…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && detail && (
        <div className="space-y-4">
          <Chip tone={attLeaveToneFor(detail.closure_result || detail.status)}>
            {detail.closure_result || detail.status}
          </Chip>
          <Facts items={[
            { label: 'Employee', value: detail.employee_name || detail.employee_code },
            { label: 'Gap Statement', value: detail.gap_statement },
            { label: 'Category', value: detail.issue_category },
            { label: 'Start / Target End', value: `${day(detail.start_date)} – ${day(detail.target_end_date)}` },
            { label: 'Review Frequency', value: detail.review_frequency },
          ]} />

          {detail.objectives?.length > 0 && (
            <div>
              <p className={LABEL}>Objectives</p>
              <ul className="text-[12.5px] text-[var(--text-main)] list-disc pl-4">
                {detail.objectives.map((o, i) => <li key={i}>{o.target_standard}</li>)}
              </ul>
            </div>
          )}
          {detail.support?.length > 0 && (
            <div>
              <p className={LABEL}>Support</p>
              <ul className="text-[12.5px] text-[var(--text-main)] list-disc pl-4">
                {detail.support.map((s, i) => <li key={i}>{s.action}</li>)}
              </ul>
            </div>
          )}

          {detail.status === 'Draft' && can(CAP.PIP_ACKNOWLEDGE) && (
            <Btn tone="primary" disabled={busy} onClick={() => run(
              () => acknowledgePip(pipNo, scope), 'PIP acknowledged.')}>
              {busy ? 'Working…' : 'Acknowledge'}
            </Btn>
          )}

          {detail.reviews?.length > 0 && (
            <div>
              <p className={LABEL}>Review History</p>
              <div className="space-y-2">
                {detail.reviews.map((r, i) => (
                  <div key={i} className="rounded-lg border border-[var(--border)] p-2.5 text-[12px]">
                    <p className="font-bold text-[var(--text-main)]">{day(r.at)} — {r.progress}</p>
                    {r.manager_comments && <p className="text-[var(--text-muted)]">Manager: {r.manager_comments}</p>}
                    {r.employee_comments && <p className="text-[var(--text-muted)]">Employee: {r.employee_comments}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {detail.status === 'Active' && can(CAP.PIP_MANAGE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Record Review (§22.5 step 218)</p>
              <input value={progress} className={FIELD} placeholder="Progress"
                onChange={(e) => setProgress(e.target.value)} />
              <textarea rows={2} value={managerComments} className={TEXTAREA}
                placeholder="Manager comments" onChange={(e) => setManagerComments(e.target.value)} />
              <Btn disabled={busy || !progress.trim()} onClick={() => run(
                () => addPipReview(pipNo, {
                  progress: progress.trim(), manager_comments: managerComments.trim() || undefined,
                }, scope), 'Review recorded.')}>
                {busy ? 'Working…' : 'Add Review'}
              </Btn>
            </div>
          )}

          {['Draft', 'Active'].includes(detail.status) && can(CAP.PIP_DECIDE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Record Outcome (§22.5 step 220)</p>
              <select value={closureResult} className={FIELD}
                onChange={(e) => setClosureResult(e.target.value)}>
                {['Successfully Closed', 'Extended', 'Further Action Required',
                  'Separation Recommended'].map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <input value={finalRating} className={FIELD} placeholder="Final rating"
                onChange={(e) => setFinalRating(e.target.value)} />
              <textarea rows={2} value={decisionRemarks} className={TEXTAREA} placeholder="Remarks"
                onChange={(e) => setDecisionRemarks(e.target.value)} />
              <Btn tone="primary" disabled={busy} onClick={() => run(
                () => decidePip(pipNo, {
                  closure_result: closureResult, final_rating: finalRating.trim() || undefined,
                  remarks: decisionRemarks.trim() || undefined,
                }, scope), 'Outcome recorded.')}>
                {busy ? 'Working…' : 'Record Outcome'}
              </Btn>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

export default PipBoard;
