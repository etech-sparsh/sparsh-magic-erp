import React, { useCallback, useEffect, useState } from 'react';
import { Target, Plus, Trash2, CheckCircle2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getScorecards, createScorecard, approveScorecard, getRequisitions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList, SignatureField,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — position scorecards.
 *
 * What "good" looks like for one vacancy, agreed BEFORE anybody is interviewed. HR drafts,
 * the hiring manager approves, and Management approves as well for managerial roles.
 *
 * The builder shows a live weight breakdown as percentages. Weights do not have to sum to
 * anything — "SQL twice as important as culture fit" is the judgement being captured — but a
 * reader still wants to know what 3-2-1 actually means in practice, so the screen does that
 * arithmetic rather than leaving it to them.
 */

const CATEGORIES = [
  { value: 'skill', label: 'Skill' },
  { value: 'experience', label: 'Experience' },
  { value: 'culture_fit', label: 'Culture fit' },
];

/** The five rows the Position Scorecard template names, pre-filled so a new scorecard opens
 *  in the standard shape. They are a STARTING POINT, not a fixed list: each row can be
 *  renamed, reweighted or removed, and extra rows added. Categories are pre-matched to the
 *  row so the weighted maths and the category filter agree with the wording. */
const TEMPLATE_ROWS = [
  { label: 'Technical / Job Skill', category: 'skill' },
  { label: 'Relevant Experience', category: 'experience' },
  { label: 'Role Competency', category: 'skill' },
  { label: 'Communication / Professional Skill', category: 'skill' },
  { label: 'Culture-Fit Expectations', category: 'culture_fit' },
].map((r) => ({
  ...r, expected_level: '', evaluation_criteria: '', weight: 1, max_score: 5, remarks: '',
}));

const emptyRow = () => ({
  label: '', category: 'skill', expected_level: '', evaluation_criteria: '',
  weight: 1, max_score: 5, remarks: '',
});

const ScorecardLibrary = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [building, setBuilding] = useState(false);
  const [approving, setApproving] = useState(null);

  const canWrite = can(CAP.SCORECARD_WRITE);
  const canApprove = can(CAP.SCORECARD_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getScorecards({ ...scope, limit: 200 });
      setRows(data?.scorecards || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load scorecards.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'scr', label: 'Scorecard',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.title || r.designation_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.scr_no} · {r.request_no}
          </span>
        </>
      ) },
    { key: 'criteria', label: 'Criteria',
      render: (r) => (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="px-2 py-0.5 rounded-md bg-[var(--input-bg)] text-[11.5px] font-bold text-[var(--text-main)]">
            {(r.criteria || []).length}
          </span>
          <span className="text-[var(--text-muted)]">
            {(r.criteria || []).length === 1 ? 'criterion' : 'criteria'}
          </span>
          {r.managerial && (
            <span className="px-2 py-0.5 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10.5px] font-bold">
              Managerial
            </span>
          )}
        </div>
      ) },
    { key: 'created', label: 'Drafted',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.created_by_name || '—'}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {day(r.created_at)}
          </span>
        </>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.status)}>{r.status}</Chip>
          {r.status !== 'Approved' && canApprove && (
            <Btn tone="ghost" onClick={() => setApproving(r)}>Review</Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.title || r.designation_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.scr_no} · {r.request_no}
          </p>
        </div>
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Criteria', value: (r.criteria || []).length },
        { label: 'Managerial', value: r.managerial ? 'Yes' : 'No' },
        { label: 'Drafted', value: day(r.created_at) },
      ]} />
      {r.status !== 'Approved' && canApprove && (
        <Btn tone="ghost" onClick={() => setApproving(r)}>Review</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Target}
        title="Position scorecards"
        subtitle="The bar a role is hired against, agreed before sourcing begins"
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setBuilding(true)}>
            <Plus size={14} /> New scorecard
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {!loading && !error && rows.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {[['Awaiting approval', rows.filter((r) => r.status !== 'Approved').length,
             'var(--accent-orange)'],
            ['Approved', rows.filter((r) => r.status === 'Approved').length,
             'var(--accent-green)'],
            ['Managerial roles', rows.filter((r) => r.managerial).length,
             'var(--accent-indigo)']].map(([label, value, tone]) => (
            <div key={label}
              className="relative p-3.5 pl-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
              <span className="absolute left-0 top-0 bottom-0 w-1" style={{ background: tone }} />
              <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                {label}
              </p>
              <p className="mt-1.5 text-[22px] font-bold leading-none" style={{ color: tone }}>
                {value}
              </p>
            </div>
          ))}
        </div>
      )}

      {loading && <HrmsLoading label="Loading scorecards…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.scr_no}
          empty={<HrmsEmpty
            icon={Target}
            title="No scorecards yet"
            hint="An internal requisition cannot be approved until its scorecard is."
          />}
        />
      )}

      {building && (
        <ScorecardBuilder
          scope={scope}
          onClose={() => setBuilding(false)}
          onDone={() => { setBuilding(false); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {approving && (
        <ApproveModal
          row={approving} scope={scope}
          onClose={() => setApproving(null)}
          onDone={() => { setApproving(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** The builder, laid out as the Position Scorecard template itself: a numbered row per
 *  competency, with the requisition's own facts shown read-only above it. The five rows the
 *  template names are pre-filled so a scorecard starts from the standard shape rather than
 *  a blank page; any of them can be renamed or removed, and more can be added. */
const ScorecardBuilder = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [reqs, setReqs] = useState([]);
  const [requestNo, setRequestNo] = useState('');
  const [title, setTitle] = useState('');
  const [managerial, setManagerial] = useState(false);
  const [notes, setNotes] = useState('');
  const [criteria, setCriteria] = useState(() => TEMPLATE_ROWS.map((r) => ({ ...r })));
  const [busy, setBusy] = useState(false);

  const chosen = reqs.find((r) => r.request_no === requestNo);

  useEffect(() => {
    getRequisitions({ ...scope, limit: 200 })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalWeight = criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);
  const setRow = (index, key, value) => setCriteria((rows) =>
    rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  const submit = async () => {
    const cleaned = criteria
      .map((c) => ({ ...c, label: c.label.trim(), weight: Number(c.weight) || 0 }))
      .filter((c) => c.label);
    if (!requestNo) { showError('Choose the requisition this scorecard is for.'); return; }
    if (!cleaned.length) { showError('Add at least one criterion.'); return; }
    if (cleaned.some((c) => c.weight <= 0)) {
      showError('Every criterion needs a weight greater than zero.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await createScorecard({
        request_no: requestNo, title: title.trim() || null, managerial,
        notes: notes.trim() || null, criteria: cleaned,
      }, scope);
      showSuccess(`${data.scr_no} drafted — it needs approval before sourcing`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the scorecard.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New position scorecard" labelledBy="scr-build-title"
      subtitle="Weights express relative importance — they do not have to add up to anything"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Create'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="scr-req">Requisition *</label>
        <select id="scr-req" value={requestNo} className={FIELD}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Select an internal requisition…</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
      </div>

      {/* The template's header block — read straight off the chosen requisition so the
          scorecard cannot disagree with the role it is scoring. */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] p-3
                      grid grid-cols-2 gap-x-4 gap-y-2">
        {[
          ['Position', chosen?.designation_name],
          ['Department', chosen?.department_name],
          ['Requisition ID', chosen?.request_no],
          ['Prepared By', 'HR'],
          ['Approved By', managerial ? 'HOD + Management' : 'HOD'],
        ].map(([label, value]) => (
          <div key={label}>
            <span className="block text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              {label}
            </span>
            <span className="text-[12.5px] font-semibold text-[var(--text-main)]">
              {value || '—'}
            </span>
          </div>
        ))}
      </div>

      <div>
        <label className={LABEL} htmlFor="scr-title">Title</label>
        <input id="scr-title" value={title} onChange={(e) => setTitle(e.target.value)}
          className={FIELD} placeholder="Defaults to the designation" />
      </div>

      <label className="flex items-start gap-2.5 cursor-pointer">
        <input type="checkbox" checked={managerial} className="mt-0.5"
          onChange={(e) => setManagerial(e.target.checked)} />
        <span>
          <span className="block text-[13px] font-semibold text-[var(--text-main)]">
            Managerial or above
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            Needs Management&rsquo;s approval as well as the hiring manager&rsquo;s — two
            different people.
          </span>
        </span>
      </label>

      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <p className={`${LABEL} mb-0`}>Competencies *</p>
          <p className="text-[11px] text-[var(--text-muted)]">
            Score (1–5) is filled per candidate at evaluation, not here.
          </p>
        </div>
        {criteria.map((row, index) => (
          <div key={index}
            className="rounded-lg border border-[var(--border)] p-2.5 space-y-2">
            <div className="flex gap-2 items-center">
              <span className="shrink-0 h-9 w-7 grid place-items-center rounded-md
                bg-[var(--input-bg)] text-[11.5px] font-bold text-[var(--text-muted)]">
                {index + 1}
              </span>
              <input
                aria-label={`Row ${index + 1} competency or skill`}
                value={row.label} className={FIELD} placeholder="Competency / Skill"
                onChange={(e) => setRow(index, 'label', e.target.value)}
              />
              <button type="button" aria-label={`Remove row ${index + 1}`}
                onClick={() => setCriteria((rows) => rows.filter((_, i) => i !== index))}
                disabled={criteria.length === 1}
                className="shrink-0 h-9 w-9 grid place-items-center rounded-lg
                  border border-[var(--border)] text-[var(--text-muted)]
                  hover:text-[var(--accent-red)] disabled:opacity-40">
                <Trash2 size={14} />
              </button>
            </div>
            <input
              aria-label={`Row ${index + 1} requirement or expected level`}
              value={row.expected_level} className={FIELD}
              placeholder="Requirement / Expected Level — the bar for this row"
              onChange={(e) => setRow(index, 'expected_level', e.target.value)}
            />
            <input
              aria-label={`Row ${index + 1} evaluation criteria`}
              value={row.evaluation_criteria} className={FIELD}
              placeholder="Evaluation Criteria — how it is measured"
              onChange={(e) => setRow(index, 'evaluation_criteria', e.target.value)}
            />
            <div className="grid grid-cols-3 gap-2">
              <select aria-label={`Row ${index + 1} category`}
                value={row.category} className={FIELD}
                onChange={(e) => setRow(index, 'category', e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <input type="number" min="0.5" step="0.5"
                aria-label={`Row ${index + 1} weightage`}
                value={row.weight} className={FIELD}
                onChange={(e) => setRow(index, 'weight', e.target.value)} />
              <div className="grid place-items-center rounded-lg bg-[var(--input-bg)]
                text-[12px] font-bold text-[var(--text-muted)]">
                {totalWeight
                  ? `${Math.round(((Number(row.weight) || 0) / totalWeight) * 100)}%`
                  : '—'}
              </div>
            </div>
            <input
              aria-label={`Row ${index + 1} remarks`}
              value={row.remarks} className={FIELD} placeholder="Remarks (optional)"
              onChange={(e) => setRow(index, 'remarks', e.target.value)}
            />
          </div>
        ))}
        <Btn onClick={() => setCriteria((rows) => [...rows, emptyRow()])}>
          <Plus size={13} /> Add competency
        </Btn>
      </div>

      <div>
        <label className={LABEL} htmlFor="scr-notes">HR Remarks</label>
        <textarea id="scr-notes" rows={2} value={notes} className={TEXTAREA}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="HR's own note on this scorecard" />
      </div>

      {/* The template's footer, stated rather than collected: both are produced by the
          system later, and a blank box for them here would invite HR to write a verdict
          before anyone has been interviewed. */}
      <p className="text-[11px] text-[var(--text-muted)]">
        <strong>Overall Score</strong> and the <strong>Final Recommendation</strong>
        {' '}(Strong / Consider / Hold / Reject) are computed from these weights when a
        candidate is scored against this scorecard. <strong>HOD Remarks</strong> are captured
        on the approval itself.
      </p>
    </Modal>
  );
};

/** One approval signature. The dialog names who is still outstanding, so a managerial
 *  scorecard does not look stuck for no visible reason after the first signature. */
const ApproveModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [signature, setSignature] = useState('');
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const outstanding = row.approval_state?.outstanding_roles || [];

  const decide = async (decision) => {
    if (!signature.trim()) { showError('Type your name to sign this approval.'); return; }
    if (decision === 'Fail' && !remarks.trim()) {
      showError('Say why it is being sent back, so HR can act on it.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await approveScorecard(row.scr_no,
        { decision, signature: signature.trim(), remarks: remarks.trim() }, scope);
      showSuccess(data.status === 'Approved'
        ? `${row.scr_no} approved`
        : `${row.scr_no} recorded — still waiting on `
          + `${(data.approval_state?.outstanding_roles || []).join(', ') || 'approval'}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the approval.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Review ${row.scr_no}`} labelledBy="scr-approve-title"
      subtitle={row.title || row.designation_name} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => decide('Fail')} disabled={busy}>Send back</Btn>
          <Btn tone="primary" onClick={() => decide('Pass')} disabled={busy}>
            <CheckCircle2 size={14} /> {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Criteria
        </p>
        <ul className="mt-2 space-y-2">
          {(row.criteria || []).map((c) => (
            <li key={c.label} className="text-[12.5px]">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[var(--text-main)] font-semibold">{c.label}</span>
                <span className="text-[var(--text-muted)] shrink-0">
                  weight {c.weight} · out of {c.max_score}
                </span>
              </div>
              {c.expected_level && (
                <p className="text-[11.5px] text-[var(--text-main)]">
                  Expected: {c.expected_level}
                </p>
              )}
              {c.evaluation_criteria && (
                <p className="text-[11.5px] text-[var(--text-muted)]">{c.evaluation_criteria}</p>
              )}
              {c.remarks && (
                <p className="text-[11px] italic text-[var(--text-muted)]">Remarks: {c.remarks}</p>
              )}
            </li>
          ))}
        </ul>
      </div>

      {outstanding.length > 0 && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Still outstanding after this: <b>{outstanding.join(', ')}</b>. A managerial
          scorecard needs two different people.
        </p>
      )}

      <SignatureField id="scr-sign" value={signature} onChange={setSignature} />

      <div>
        <label className={LABEL} htmlFor="scr-remarks">
          Remarks (required to send back)
        </label>
        <textarea id="scr-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ScorecardLibrary;
