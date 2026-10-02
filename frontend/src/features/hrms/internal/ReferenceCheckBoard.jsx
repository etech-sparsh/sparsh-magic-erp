import React, { useCallback, useEffect, useState } from 'react';
import { PhoneCall, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getReferenceChecks, createReferenceCheck } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — reference checks.
 *
 * Mandatory before an internal offer, because Sparsh Magic carries the employment risk
 * directly rather than passing it to a client (SOP §6).
 *
 * The distinction the screen has to make obvious: a reference is COMPLETED WORK when the
 * call happened, and a CLEARANCE only when it was positive. "Unable to Verify" is a real,
 * recordable outcome that does not open the offer gate — so the outcome chip carries that
 * meaning rather than a generic "done" tick.
 */

const MODES = ['Phone', 'Email', 'Letter', 'In Person'];
const OUTCOMES = ['Positive', 'Negative', 'Unable to Verify'];

const ReferenceCheckBoard = () => {
  const { scope, companyId, companyName, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState('');
  const [adding, setAdding] = useState(false);

  const canWrite = can(CAP.REFERENCE_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getReferenceChecks({
        ...scope, outcome: outcome || undefined, limit: 200,
      });
      setRows(data?.reference_checks || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load reference checks.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, outcome]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'candidate', label: 'Candidate',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.candidate_name || r.uk}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.uk} · {r.ref_no}
          </span>
        </>
      ) },
    { key: 'referee', label: 'Referee',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.referee_name}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {[r.referee_designation, r.referee_organisation].filter(Boolean).join(', ')
              || r.relationship || '—'}
          </span>
        </>
      ) },
    { key: 'mode', label: 'Mode',
      render: (r) => <span className="text-[var(--text-muted)]">{r.mode}</span> },
    { key: 'checked', label: 'Checked',
      render: (r) => (
        <span className="text-[var(--text-muted)]">{day(r.checked_on)}</span>
      ) },
    { key: 'outcome', label: 'Outcome', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1">
          <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
          {r.outcome !== 'Positive' && (
            <span className="text-[10.5px] text-[var(--text-muted)]">
              does not clear an offer
            </span>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name || r.uk}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.ref_no}</p>
        </div>
        <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
      </div>
      <Facts items={[
        { label: 'Referee', value: r.referee_name },
        { label: 'Mode', value: r.mode },
        { label: 'Checked', value: day(r.checked_on) },
      ]} />
      {r.remarks && (
        <p className="text-[12px] text-[var(--text-muted)]">{r.remarks}</p>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={PhoneCall}
        title="Reference checks"
        subtitle={`Required before an internal offer — ${companyName || 'this company'} `
          + 'carries the employment risk directly'}
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> Record a check
          </Btn>
        )}
      />
      <HrmsScopeBar />

      <div className="flex items-center gap-2 flex-wrap">
        <label htmlFor="ref-outcome" className="text-[11px] font-bold uppercase
          tracking-widest text-[var(--text-muted)]">Outcome</label>
        <select id="ref-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}
          className="h-9 px-3 rounded-lg border border-[var(--border)]
            bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
          <option value="">All</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Only a <b>Positive</b> reference clears a candidate for an offer. Anything else
          needs an approved exception.
        </p>
      </div>

      {loading && <HrmsLoading label="Loading reference checks…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.ref_no}
          empty={<HrmsEmpty
            icon={PhoneCall}
            title="No reference checks recorded"
            hint="An internal offer cannot be raised until a candidate has a positive one."
          />}
        />
      )}

      {adding && (
        <RecordModal
          scope={scope}
          onClose={() => setAdding(false)}
          onDone={() => { setAdding(false); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

const RecordModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState({
    uk: '', referee_name: '', referee_designation: '', referee_organisation: '',
    relationship: '', referee_contact: '', mode: 'Phone',
    checked_on: new Date().toISOString().slice(0, 10),
    responses: '', outcome: 'Positive', remarks: '',
  });
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async () => {
    if (!form.uk.trim() || !form.referee_name.trim()) {
      showError('A candidate and a referee are both required.');
      return;
    }
    if (form.outcome !== 'Positive' && !form.remarks.trim()) {
      showError(`Record what was said — a "${form.outcome}" reference with no note cannot `
        + 'be acted on.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await createReferenceCheck(form, scope);
      showSuccess(form.outcome === 'Positive'
        ? `${data.ref_no} recorded — ${form.uk} is cleared for an offer`
        : `${data.ref_no} recorded — this does not clear ${form.uk} for an offer`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the reference check.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Record a reference check" labelledBy="ref-add-title"
      subtitle="Somebody who has worked with this person, asked before the offer goes out"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Record'}
          </Btn>
        </>
      )}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="ref-uk">Candidate ID *</label>
          <input id="ref-uk" value={form.uk} onChange={set('uk')} className={FIELD}
            placeholder="CAN-001" />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-name">Referee name *</label>
          <input id="ref-name" value={form.referee_name} onChange={set('referee_name')}
            className={FIELD} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-desig">Referee designation</label>
          <input id="ref-desig" value={form.referee_designation}
            onChange={set('referee_designation')} className={FIELD} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-org">Organisation</label>
          <input id="ref-org" value={form.referee_organisation}
            onChange={set('referee_organisation')} className={FIELD} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-rel">Relationship</label>
          <input id="ref-rel" value={form.relationship} onChange={set('relationship')}
            className={FIELD} placeholder="Reporting manager" />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-contact">Contact</label>
          <input id="ref-contact" value={form.referee_contact}
            onChange={set('referee_contact')} className={FIELD} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-mode">Mode</label>
          <select id="ref-mode" value={form.mode} onChange={set('mode')} className={FIELD}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="ref-date">Checked on</label>
          <input id="ref-date" type="date" value={form.checked_on}
            onChange={set('checked_on')} className={FIELD} />
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="ref-outcome-field">Outcome *</label>
        <select id="ref-outcome-field" value={form.outcome} onChange={set('outcome')}
          className={FIELD}>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          {form.outcome === 'Positive'
            ? 'A positive reference clears this candidate for an offer.'
            : 'This is completed work but not a clearance — nobody vouched for the '
              + 'candidate. An offer will need an approved exception.'}
        </p>
      </div>

      <div>
        <label className={LABEL} htmlFor="ref-responses">What was said</label>
        <textarea id="ref-responses" rows={3} value={form.responses}
          onChange={set('responses')} className={TEXTAREA} />
      </div>

      <div>
        <label className={LABEL} htmlFor="ref-remarks">
          Remarks {form.outcome === 'Positive' ? '' : '*'}
        </label>
        <textarea id="ref-remarks" rows={2} value={form.remarks} onChange={set('remarks')}
          className={TEXTAREA} />
      </div>
    </Modal>
  );
};

export default ReferenceCheckBoard;
