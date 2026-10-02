import React, { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, Plus, Lock, LockOpen, AlertTriangle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getPendingVerifications, getCandidateVerification, recordBackgroundCheck,
  decideVerification,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, SignatureField } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ background verification, and the approval that unlocks an offer.
 *
 *     Background Verification → HR Approval → Offer Letter → Onboarding
 *
 * The screen's job is to make the LOCK legible. A recruiter who cannot raise an offer
 * should be able to see, on one row, exactly which of the three required checks is holding
 * it and whose signature is missing — otherwise the 409 at the offer screen is a mystery
 * and somebody starts asking for an override.
 *
 * So each candidate shows two separate facts, never merged into one badge:
 *
 *   checks complete    — the work is done
 *   cleared for offer  — the work is done AND HR has signed
 *
 * They are different states, and the gap between them is the whole point of the approval.
 */

const CHECK_TYPES = [
  'Identity / Document', 'Education', 'Employment', 'Address', 'Criminal Record', 'Other',
];
const STATUSES = ['Pending', 'In Progress', 'Cleared', 'Flagged'];

const STATUS_TONE = {
  Pending: 'neutral', 'In Progress': 'info', Cleared: 'good', Flagged: 'bad',
};

const BackgroundCheckBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [recording, setRecording] = useState(null);
  const [signing, setSigning] = useState(null);

  const canWrite = can(CAP.BACKGROUND_WRITE);
  const canApprove = can(CAP.BACKGROUND_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getPendingVerifications(scope);
      setRows(data?.candidates || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load verifications.');
    } finally {
      setLoading(false);
    }
  }, [companyId, scope]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (row) => {
    try {
      const { data } = await getCandidateVerification(row.uk, scope);
      setDetail(data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open that file.');
    }
  };

  return (
    <div className="space-y-4">
      <HrmsPageHeader
        title="Background verification"
        subtitle="Verification → HR approval → offer. Every later step stays locked until both are done."
        icon={ShieldCheck}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={ShieldCheck}
          title="Nobody awaiting verification"
          hint="Candidates appear here once they reach Selected or the offer stage."
        />
      )}

      <div className="grid gap-3">
        {rows.map((row) => (
          <div
            key={row.uk}
            className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4
                       space-y-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-[14px] font-bold text-[var(--text-main)]">
                    {row.candidate_name}
                  </p>
                  {/* The two facts, kept apart on purpose — see the module note. */}
                  <Chip tone={row.checks_complete ? 'good' : 'warn'}>
                    {row.checks_complete ? 'Checks complete' : 'Checks outstanding'}
                  </Chip>
                  <Chip tone={row.cleared_for_offer ? 'good' : 'neutral'}>
                    {row.cleared_for_offer
                      ? <><LockOpen size={11} /> Offer unlocked</>
                      : <><Lock size={11} /> Offer locked</>}
                  </Chip>
                  {!!row.flagged?.length && (
                    <Chip tone="bad"><AlertTriangle size={11} /> Flagged</Chip>
                  )}
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)] font-mono mt-0.5">
                  {row.uk}{row.request_no ? ` · ${row.request_no}` : ''}
                  {` · ${row.application_status}`}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Btn onClick={() => openDetail(row)}>View file</Btn>
                {canWrite && (
                  <Btn onClick={() => setRecording(row)}>
                    <Plus size={13} /> Record a check
                  </Btn>
                )}
                {canApprove && row.checks_complete && !row.cleared_for_offer
                  && !row.flagged?.length && (
                  <Btn tone="primary" onClick={() => setSigning(row)}>
                    Approve verification
                  </Btn>
                )}
              </div>
            </div>

            {!!row.outstanding?.length && (
              <p className="text-[12px] text-[var(--text-muted)]">
                <span className="font-semibold">Outstanding:</span>{' '}
                {row.outstanding.join(', ')}
              </p>
            )}
            {!!row.flagged?.length && (
              <p className="text-[12px] text-[var(--danger,#b3261e)]">
                <span className="font-semibold">Flagged:</span> {row.flagged.join(', ')} —
                an offer cannot be raised until this is resolved or an approved
                Background Verification Waived exception exists.
              </p>
            )}
            {row.checks_complete && !row.cleared_for_offer && !row.flagged?.length && (
              <p className="text-[12px] text-[var(--text-muted)]">
                All checks are done. The offer stays locked until HR approves the file —
                complete checks nobody reviewed are not an approval.
              </p>
            )}
          </div>
        ))}
      </div>

      {detail && (
        <Modal
          title={`${detail.candidate_name} — verification file`}
          subtitle={detail.cleared_for_offer
            ? 'Cleared for an offer'
            : 'Not cleared for an offer'}
          onClose={() => setDetail(null)}
          footer={<Btn onClick={() => setDetail(null)}>Close</Btn>}
        >
          <div className="space-y-3">
            <Facts items={[
              { label: 'Required checks', value: (detail.required || []).join(', ') },
              { label: 'Approval', value: detail.approval?.status },
              { label: 'Approved by', value: detail.approval?.decided_by_name },
              { label: 'Approved on', value: day(detail.approval?.decided_at) },
              { label: 'Signature', value: detail.approval?.signature },
            ]} />
            {detail.approval?.voided_reason && (
              <p className="text-[12px] text-[var(--text-muted)] border-l-2
                            border-[var(--border)] pl-2">
                Approval withdrawn: {detail.approval.voided_reason}
              </p>
            )}
            <div className="space-y-2">
              {(detail.checks || []).map((c) => (
                <div key={c.bgv_no}
                     className="rounded-lg border border-[var(--border)] p-2.5">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                      {c.check_type}
                    </p>
                    <Chip tone={STATUS_TONE[c.status] || 'neutral'}>{c.status}</Chip>
                  </div>
                  <p className="text-[11px] text-[var(--text-muted)] font-mono">
                    {c.bgv_no}{c.agency ? ` · ${c.agency}` : ''}
                    {c.completed_on ? ` · ${c.completed_on}` : ''}
                  </p>
                  {c.findings && (
                    <p className="mt-1 text-[12px] text-[var(--text-main)] whitespace-pre-wrap">
                      {c.findings}
                    </p>
                  )}
                </div>
              ))}
              {!detail.checks?.length && (
                <p className="text-[12px] text-[var(--text-muted)]">
                  No checks recorded yet.
                </p>
              )}
            </div>
          </div>
        </Modal>
      )}

      {recording && (
        <RecordModal
          scope={scope}
          candidate={recording}
          onClose={() => setRecording(null)}
          onDone={async (m) => { setRecording(null); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
      {signing && (
        <SignModal
          scope={scope}
          candidate={signing}
          onClose={() => setSigning(null)}
          onDone={async (m) => { setSigning(null); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
    </div>
  );
};

const RecordModal = ({ scope, candidate, onClose, onDone, onError }) => {
  const [form, setForm] = useState({
    check_type: 'Identity / Document', status: 'Pending', agency: '', reference: '',
    findings: '', completed_on: '',
  });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  // The server demands findings on a conclusion; asked for here so the refusal is not a
  // 422 the user has to decode.
  const needsFindings = ['Cleared', 'Flagged'].includes(form.status);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await recordBackgroundCheck({
        uk: candidate.uk, ...form, completed_on: form.completed_on || null,
      }, scope);
      await onDone(`${form.check_type} recorded for ${candidate.candidate_name}`);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not record that check.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Record a check — ${candidate.candidate_name}`}
      subtitle="Identity, education and prior employment must all clear before an offer."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit}
               disabled={saving || (needsFindings && !form.findings.trim())}>
            {saving ? 'Saving…' : 'Record check'}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="bg-type">Check *</label>
            <select id="bg-type" className={FIELD} value={form.check_type}
                    onChange={set('check_type')}>
              {CHECK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="bg-status">Result *</label>
            <select id="bg-status" className={FIELD} value={form.status}
                    onChange={set('status')}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="bg-agency">Verified by</label>
            <input id="bg-agency" className={FIELD} value={form.agency}
                   onChange={set('agency')} placeholder="Agency or person" />
          </div>
          <div>
            <label className={LABEL} htmlFor="bg-ref">Reference</label>
            <input id="bg-ref" className={FIELD} value={form.reference}
                   onChange={set('reference')} placeholder="Vendor case number" />
          </div>
          <div>
            <label className={LABEL} htmlFor="bg-done">Completed on</label>
            <input id="bg-done" type="date" className={FIELD} value={form.completed_on}
                   onChange={set('completed_on')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="bg-find">
            Findings {needsFindings ? '*' : ''}
          </label>
          <textarea id="bg-find" rows={3} className={TEXTAREA} value={form.findings}
                    onChange={set('findings')}
                    placeholder={needsFindings
                      ? 'Required — a result with nothing behind it cannot be reviewed later.'
                      : 'Optional while the check is still open.'} />
        </div>
      </form>
    </Modal>
  );
};

const SignModal = ({ scope, candidate, onClose, onDone, onError }) => {
  const [signature, setSignature] = useState('');
  const [remarks, setRemarks] = useState('');
  const [saving, setSaving] = useState(false);

  const decide = async (decision) => {
    setSaving(true);
    try {
      await decideVerification(candidate.uk,
        { decision, signature, remarks: remarks || null }, scope);
      await onDone(`Verification ${decision.toLowerCase()} for ${candidate.candidate_name}`);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not record that decision.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Approve verification — ${candidate.candidate_name}`}
      subtitle="This is the step that unlocks the offer letter."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="danger" onClick={() => decide('Rejected')}
               disabled={saving || !signature.trim()}>
            Reject
          </Btn>
          <Btn tone="primary" onClick={() => decide('Approved')}
               disabled={saving || !signature.trim()}>
            {saving ? 'Saving…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          Approving confirms the file is complete and sufficient. Recording a new check
          afterwards withdraws this approval automatically.
        </p>
        <SignatureField
          id="bg-sign"
          value={signature}
          onChange={setSignature}
          hint="Type your name to sign. An approval nobody signed is not one."
        />
        <div>
          <label className={LABEL} htmlFor="bg-remarks">Remarks</label>
          <textarea id="bg-remarks" rows={2} className={TEXTAREA} value={remarks}
                    onChange={(e) => setRemarks(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

export default BackgroundCheckBoard;
