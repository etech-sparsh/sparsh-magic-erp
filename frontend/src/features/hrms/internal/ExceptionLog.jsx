import React, { useCallback, useEffect, useState } from 'react';
import { ShieldAlert, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getExceptions, raiseException, decideException, getRequisitions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList, SignatureField,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — the exception log.
 *
 * Every gate on this track can be lifted, and this is the only way to lift one. There is no
 * override switch anywhere in the UI because there is none in the API: the reference-check
 * and salary-band gates ask this log whether an APPROVED exception exists, and nothing else
 * will do.
 *
 * The screen therefore leads with what is PENDING. An exception nobody has decided is a
 * blocked hire and a control in limbo at the same time, which makes it the most urgent thing
 * on the page.
 */

const TYPES = [
  'Extended TAT', 'Relaxed Scorecard', 'Offer Outside Budget',
  'Reference Check Waived', 'Other',
];

const GATE_COPY = {
  reference_check: 'Lets an offer be raised without a clearing reference check.',
  salary_band: 'Lets an offer sit outside the approved salary band.',
  scorecard: 'Relaxes the position scorecard criteria.',
  sla: 'Accepts a milestone running past its target.',
};

const ExceptionLog = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('');
  const [raising, setRaising] = useState(false);
  const [deciding, setDeciding] = useState(null);
  const [busy, setBusy] = useState(false);

  const canRaise = can(CAP.EXCEPTION_WRITE);
  const canDecide = can(CAP.EXCEPTION_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getExceptions({ ...scope, status: status || undefined });
      setRows(data?.exceptions || []);
      setPending(data?.pending ?? 0);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the exception log.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'exc', label: 'Exception',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.exc_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.exception_type}
          </span>
        </>
      ) },
    { key: 'scope', label: 'Applies to',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.request_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.uk ? `${r.candidate_name || r.uk} only` : 'All candidates'}
          </span>
        </>
      ) },
    { key: 'reason', label: 'Reason',
      render: (r) => (
        <span className="text-[var(--text-muted)] line-clamp-2">{r.reason}</span>
      ) },
    { key: 'raised', label: 'Raised by',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.raised_by_name || '—'}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {day(r.raised_at)}
          </span>
        </>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.status)}>{r.status}</Chip>
          {r.status === 'Pending' && canDecide && (
            <Btn tone="ghost" onClick={() => setDeciding(r)}>Decide</Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.exc_no}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.exception_type}</p>
        </div>
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Requisition', value: r.request_no },
        { label: 'Scope', value: r.uk ? (r.candidate_name || r.uk) : 'All candidates' },
        { label: 'Raised by', value: r.raised_by_name },
      ]} />
      <p className="text-[12px] text-[var(--text-muted)]">{r.reason}</p>
      {r.status === 'Pending' && canDecide && (
        <Btn tone="ghost" onClick={() => setDeciding(r)}>Decide</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={ShieldAlert}
        title="Exception log"
        subtitle="Every deviation from the internal recruitment policy, with a reason and an approver"
        actions={canRaise && (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise exception
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {pending > 0 && (
        <div className="rounded-xl border border-[var(--accent-orange,var(--accent-red))]
          bg-[var(--accent-orange-bg,var(--accent-red-bg))] px-4 py-3">
          <p className="text-[12.5px] font-semibold
            text-[var(--accent-orange,var(--accent-red))]">
            {pending} exception{pending === 1 ? '' : 's'} awaiting a decision.
          </p>
          <p className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
            Until one is approved it lifts nothing — the hire it was raised for is still
            blocked.
          </p>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <label htmlFor="exc-status" className="text-[11px] font-bold uppercase
          tracking-widest text-[var(--text-muted)]">Status</label>
        <select id="exc-status" value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-3 rounded-lg border border-[var(--border)]
            bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
          <option value="">All</option>
          <option value="Pending">Pending</option>
          <option value="Approved">Approved</option>
          <option value="Rejected">Rejected</option>
        </select>
      </div>

      {loading && <HrmsLoading label="Loading the exception log…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.exc_no}
          empty={<HrmsEmpty
            icon={ShieldAlert}
            title="No exceptions logged"
            hint="Nothing has needed to deviate from the policy. That is the healthy state."
          />}
        />
      )}

      {raising && (
        <RaiseModal
          scope={scope}
          onClose={() => setRaising(false)}
          onDone={() => { setRaising(false); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {deciding && (
        <DecideModal
          row={deciding} scope={scope} busy={busy} setBusy={setBusy}
          onClose={() => setDeciding(null)}
          onDone={() => { setDeciding(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** Raise one. The requisition list is filtered to the internal track, because the client
 *  track has no gates for an exception to lift and the server refuses one anyway. */
const RaiseModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [reqs, setReqs] = useState([]);
  const [form, setForm] = useState({
    request_no: '', exception_type: 'Reference Check Waived', reason: '', uk: '',
    requested_ctc: '',
  });
  // An Offer Outside Budget request IS a request for a figure, so the form asks for one.
  const needsAmount = form.exception_type === 'Offer Outside Budget';
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRequisitions({ ...scope, limit: 200 })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (!form.request_no || !form.reason.trim()) {
      showError('Choose a requisition and say why the deviation is needed.');
      return;
    }
    if (needsAmount && !(Number(form.requested_ctc) > 0)) {
      showError('Say what CTC you are asking Finance to approve.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await raiseException({
        ...form,
        uk: form.uk || null,
        requested_ctc: needsAmount ? Number(form.requested_ctc) : null,
      }, scope);
      showSuccess(`${data.exc_no} logged — it lifts nothing until it is approved`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not raise the exception.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Raise an exception" labelledBy="exc-raise-title"
      subtitle="Recorded for approval. Raising one grants nothing on its own."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Raise'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="exc-req">Requisition *</label>
        <select id="exc-req" value={form.request_no} className={FIELD}
          onChange={(e) => setForm((f) => ({ ...f, request_no: e.target.value }))}>
          <option value="">Select an internal requisition…</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={LABEL} htmlFor="exc-type">Type *</label>
        <select id="exc-type" value={form.exception_type} className={FIELD}
          onChange={(e) => setForm((f) => ({ ...f, exception_type: e.target.value }))}>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          {GATE_COPY[{
            'Reference Check Waived': 'reference_check',
            'Offer Outside Budget': 'salary_band',
            'Relaxed Scorecard': 'scorecard',
            'Extended TAT': 'sla',
          }[form.exception_type]] || 'Recorded for the trail. Lifts no gate on its own.'}
        </p>
      </div>

      {needsAmount && (
        <div>
          <label className={LABEL} htmlFor="exc-ctc">CTC you are asking Finance for *</label>
          <input id="exc-ctc" type="number" min="1" value={form.requested_ctc}
            className={FIELD} placeholder="1300000"
            onChange={(e) => setForm((f) => ({ ...f, requested_ctc: e.target.value }))} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Finance approves a figure, not a direction. The offer is then held to whatever
            they approve, so an offer above it is refused exactly as one above the band is.
          </p>
        </div>
      )}

      <div>
        <label className={LABEL} htmlFor="exc-uk">Candidate (optional)</label>
        <input id="exc-uk" value={form.uk} className={FIELD} placeholder="CAN-001"
          onChange={(e) => setForm((f) => ({ ...f, uk: e.target.value }))} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Leave empty to cover every candidate on the requisition. A candidate named here is
          the only one it covers.
        </p>
      </div>

      <div>
        <label className={LABEL} htmlFor="exc-reason">Reason *</label>
        <textarea id="exc-reason" rows={4} value={form.reason} className={TEXTAREA}
          placeholder="Why is the deviation needed?"
          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
      </div>
    </Modal>
  );
};

/** Approve or reject. The server refuses a decision from whoever raised it, so the dialog
 *  says so up front rather than letting somebody type a signature to be told no. */
const DecideModal = ({ row, scope, busy, setBusy, onClose, onDone,
  showSuccess, showError }) => {
  const [signature, setSignature] = useState('');
  const [remarks, setRemarks] = useState('');
  // A budget request names a figure, and Finance may grant less than was asked for.
  // Pre-filled with the request so approving unchanged means "yes, that amount".
  const isBudget = row.exception_type === 'Offer Outside Budget';
  const [approvedCtc, setApprovedCtc] = useState(
    row.requested_ctc != null ? String(row.requested_ctc) : '');

  const decide = async (decision) => {
    if (!signature.trim()) {
      showError('Type your name to sign this decision.');
      return;
    }
    if (decision === 'Rejected' && !remarks.trim()) {
      showError('Say why it is refused, so the raiser knows what to do next.');
      return;
    }
    if (isBudget && decision === 'Approved' && !(Number(approvedCtc) > 0)) {
      showError('Say what CTC you are approving.');
      return;
    }
    setBusy(true);
    try {
      await decideException(row.exc_no, {
        decision,
        signature: signature.trim(),
        remarks: remarks.trim(),
        approved_ctc: isBudget && decision === 'Approved' ? Number(approvedCtc) : null,
      }, scope);
      showSuccess(`${row.exc_no} ${decision.toLowerCase()}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Decide ${row.exc_no}`} labelledBy="exc-decide-title"
      subtitle={row.exception_type} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => decide('Rejected')} disabled={busy}>Reject</Btn>
          <Btn tone="primary" onClick={() => decide('Approved')} disabled={busy}>
            {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
        <Facts items={[
          { label: 'Requisition', value: row.request_no },
          { label: 'Scope', value: row.uk ? (row.candidate_name || row.uk) : 'All candidates' },
          { label: 'Raised by', value: row.raised_by_name },
          { label: 'Raised on', value: day(row.raised_at) },
          ...(isBudget ? [
            { label: 'Approved band',
              value: row.band_max_at_request != null
                ? `up to ${Number(row.band_max_at_request).toLocaleString()}` : '—' },
            { label: 'Asking for',
              value: row.requested_ctc != null
                ? Number(row.requested_ctc).toLocaleString() : '—' },
          ] : []),
        ]} />
        <p className="mt-2.5 text-[12.5px] text-[var(--text-main)]">{row.reason}</p>
        {row.gate && (
          <p className="mt-2 text-[11.5px] font-semibold text-[var(--accent-orange,var(--accent-red))]">
            Approving this {GATE_COPY[row.gate]?.toLowerCase()
              || 'lifts a control on this requisition.'}
          </p>
        )}
      </div>

      {isBudget && (
        <div>
          <label className={LABEL} htmlFor="exc-approved-ctc">CTC you approve *</label>
          <input id="exc-approved-ctc" type="number" min="1" value={approvedCtc}
            className={FIELD}
            onChange={(e) => setApprovedCtc(e.target.value)} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            You can approve less than was asked for, never more. The offer is held to this
            figure — anything above it is refused.
          </p>
        </div>
      )}

      <p className="text-[11.5px] text-[var(--text-muted)]">
        A deviation is granted by somebody other than the person who asked for it — if you
        raised this one, it will be refused.
      </p>

      <SignatureField id="exc-sign" value={signature} onChange={setSignature}
        hint="Recorded against your name on the exception." />

      <div>
        <label className={LABEL} htmlFor="exc-remarks">
          Remarks (required to reject)
        </label>
        <textarea id="exc-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ExceptionLog;
