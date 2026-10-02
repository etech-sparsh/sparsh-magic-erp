import React, { useCallback, useEffect, useState } from 'react';
import { FileSignature, Plus, ShieldCheck } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientOffers, getClientOfferCheckpoint, getClientCandidates,
  createClientOffer, updateClientOffer, actOnClientOffer,
  getClientReferenceChecks, recordClientReferenceCheck,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, money } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientList, useClientScope } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ offer.
 *
 * PRO-fit SOP sections 15 and 16. The recruiter prepares terms, Sparsh's Team Lead
 * verifies the paperwork, and the CLIENT releases the offer — releasing is theirs because
 * it is their employment contract, not Sparsh's.
 *
 * -- The section 16 checkpoint ---------------------------------------------------
 * Two conditions gate the submission: the figure sits inside the range the client
 * approved, and a reference check exists where the role level calls for one. The server
 * computes both in `offer_checkpoint` and this screen shows the result while the offer is
 * still a draft — meeting a control for the first time when it refuses you is a bad way
 * to learn it exists. The same function backs the gate, so the two cannot disagree.
 */

const MOVES = [
  { id: 'submit-for-verification', label: 'Submit for verification', tone: 'primary',
    cap: CAP.CLIENT_OFFER_WRITE, from: ['Draft'] },
  // ── The salary deviation, SOP section 16 ──
  // The other way out of Draft, open only when the figure is actually outside the range
  // the client approved. It goes straight to Client HR: the approved requisition range is
  // never touched, and no Sparsh role can decide it.
  { id: 'submit-deviation', label: 'Request salary deviation', tone: 'primary', remarks: true,
    cap: CAP.CLIENT_OFFER_WRITE, from: ['Draft'],
    reasonHint: 'Client HR reads this and nothing else. Say what the candidate is asking '
      + 'for, why they are worth it, and what happens if the role stays open.' },
  { id: 'deviation-approve', label: 'Approve the deviation', tone: 'primary',
    cap: CAP.CLIENT_OFFER_DEVIATE, from: ['Pending Salary Deviation'] },
  { id: 'deviation-reject', label: 'Reject the deviation', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_OFFER_DEVIATE, from: ['Pending Salary Deviation'],
    reasonHint: 'The candidate returns to the Available Candidates pool and can be '
      + 'offered to another client. Nothing is deleted.' },
  { id: 'verify', label: 'Verify', tone: 'primary',
    cap: CAP.CLIENT_OFFER_VERIFY, from: ['Pending Verification'] },
  { id: 'return', label: 'Return to draft', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_OFFER_VERIFY, from: ['Pending Verification'],
    reasonHint: 'The recruiter sees this when they reopen the draft.' },
  { id: 'client-release', label: 'Release offer', tone: 'primary',
    cap: CAP.CLIENT_OFFER_RELEASE, from: ['Pending Client Approval'] },
  { id: 'client-return', label: 'Send back', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_OFFER_RELEASE, from: ['Pending Client Approval'],
    reasonHint: 'Say which terms need to change before this can be issued.' },
  // Section 17: no verbal offer is valid, so the server demands both the date the written
  // acceptance arrived and the joining date before it will record one.
  { id: 'record-acceptance', label: 'Record acceptance', tone: 'primary',
    cap: CAP.CLIENT_OFFER_WRITE, from: ['Released'],
    reasonHint: 'Section 17: a verbal acceptance is not valid, so both dates are required.',
    fields: [
      { name: 'accepted_on', label: 'Written acceptance received on', type: 'date' },
      { name: 'joining_date', label: 'Joining date', type: 'date',
        hint: 'Confirms or corrects the date on the offer.' },
    ] },
  { id: 'record-decline', label: 'Record decline', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_OFFER_WRITE, from: ['Released'],
    reasonHint: 'What the candidate said. This is what makes the next offer better.' },
];

const ClientOffers = ({ embedded, onChanged }) => {
  // Every mutation already reloads this screen's own list. The workspace's stage rail
  // counts the same records independently, so it has to be told as well -- otherwise
  // acting inside a panel leaves the rail above it showing figures from before the
  // action, which reads as the action not having worked.
  const refresh = () => { reload(); onChanged?.(); };
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientOffers, 'client_offers');

  const [drafting, setDrafting] = useState(false);
  const [editing, setEditing] = useState(null);
  const [opened, setOpened] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.CLIENT_OFFER_WRITE);

  const act = async (cofNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientOffer(cofNo, { action, ...payload }, scope);
      showSuccess(`${cofNo} updated`);
      setOpened(null);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'off', label: 'Offer',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.candidate_name || r.ccn_no}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.cof_no} · {r.cr_no}
          </span>
        </>
      ) },
    { key: 'desig', label: 'Designation',
      render: (r) => (
        <span className="text-[var(--text-muted)]">{r.designation || '—'}</span>
      ) },
    { key: 'ctc', label: 'Offered',
      render: (r) => (
        <span className="tabular-nums font-semibold text-[var(--text-main)]">
          {r.offered_ctc != null ? money(r.offered_ctc) : '—'}
        </span>
      ) },
    { key: 'join', label: 'Joining',
      render: (r) => (
        <span className="text-[var(--text-muted)]">
          {r.joining_date ? day(r.joining_date) : '—'}
        </span>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canWrite && r.status === 'Draft' && (
            <Btn onClick={() => setEditing(r)}>Edit</Btn>
          )}
          <Btn onClick={() => setOpened(r)}>Open</Btn>
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name || r.ccn_no}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.cof_no} · {r.cr_no}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Designation', value: r.designation || '—' },
        { label: 'Offered', value: r.offered_ctc != null ? money(r.offered_ctc) : '—' },
        { label: 'Joining', value: r.joining_date ? day(r.joining_date) : '—' },
      ]} />
      <div className="flex items-center gap-1.5">
        {canWrite && r.status === 'Draft' && <Btn onClick={() => setEditing(r)}>Edit</Btn>}
        <Btn onClick={() => setOpened(r)}>Open</Btn>
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader
          title="Offers"
          subtitle="Terms, reference checks and the section 16 checkpoint (SOP sections 15–16)"
          actions={canWrite && (
          <Btn tone="primary" onClick={() => setDrafting(true)}>
            <Plus size={14} /> Draft an offer
          </Btn>
        )}
        />
      ) : (
        <>
          <HrmsPageHeader
            icon={FileSignature}
            title="Offers"
            subtitle="Terms, reference checks and the section 16 checkpoint (SOP sections 15–16)"
            actions={canWrite && (
          <Btn tone="primary" onClick={() => setDrafting(true)}>
            <Plus size={14} /> Draft an offer
          </Btn>
        )}
          />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        {isInternal ? (
          <>
            Sparsh prepares and verifies; the client releases. Two conditions gate the
            submission — the figure inside the range the client approved, and a reference
            check where the role level asks for one — and both are shown on the offer
            while it is still a draft.
          </>
        ) : (
          <>
            Sparsh prepares the terms and verifies the paperwork; you release the offer,
            because it is your employment contract. Two conditions gate it before it
            reaches you — the figure inside the range you approved, and a reference check
            where the role level asks for one.
          </>
        )}
      </WhoseMove>

      {loading && <HrmsLoading label="Loading offers…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.cof_no}
          empty={<HrmsEmpty
            icon={FileSignature}
            title="No offers yet"
            hint={canWrite
              ? 'Draft one for a candidate the client selected after interview.'
              : 'Nothing is waiting for your release.'}
          />}
        />
      )}

      {drafting && (
        <OfferModal
          busy={busy}
          onClose={() => setDrafting(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await createClientOffer(payload, scope);
              showSuccess(`${data.cof_no} drafted`);
              setDrafting(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be drafted.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editing && (
        <OfferModal
          row={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientOffer(editing.cof_no, payload, scope);
              showSuccess(`${editing.cof_no} saved`);
              setEditing(null);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be saved.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {opened && (
        <OfferDetail
          row={opened}
          busy={busy}
          onClose={() => setOpened(null)}
          onAct={(action, payload) => act(opened.cof_no, action, payload)}
        />
      )}
    </div>
  );
};

/** Draft new terms, or correct a draft that came back from verification. */
const OfferModal = ({ row, busy, onClose, onSubmit }) => {
  const scope = useClientScope();
  const editing = !!row;
  const [form, setForm] = useState(() => ({
    ccn_no: row?.ccn_no || '',
    offered_ctc: row?.offered_ctc ?? '',
    joining_date: row?.joining_date ? String(row.joining_date).slice(0, 10) : '',
    designation: row?.designation || '',
    terms: row?.terms || '',
    negotiation_notes: row?.negotiation_notes || '',
  }));
  const [candidates, setCandidates] = useState([]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const loadCandidates = useCallback(async () => {
    if (editing) return;
    try {
      const { data } = await getClientCandidates({ ...scope, limit: 200 });
      // Only somebody the client selected after interview can carry an offer. The API
      // refuses the rest; listing them here would just be offering a dead end.
      setCandidates((data?.client_candidates || [])
        .filter((c) => c.status === 'Selected'));
    } catch { setCandidates([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, JSON.stringify(scope)]);

  useEffect(() => { loadCandidates(); }, [loadCandidates]);

  const ready = (editing || form.ccn_no) && form.offered_ctc !== '';

  return (
    <Modal
      title={editing ? `Edit ${row.cof_no}` : 'Draft an offer'}
      subtitle="The figure is checked against the range the client approved on the requisition."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready}
            onClick={() => onSubmit({
              ...(editing ? {} : { ccn_no: form.ccn_no }),
              offered_ctc: Number(form.offered_ctc),
              joining_date: form.joining_date || undefined,
              designation: form.designation || undefined,
              terms: form.terms || undefined,
              ...(editing ? { negotiation_notes: form.negotiation_notes || undefined } : {}),
            })}>
            {busy ? 'Saving…' : (editing ? 'Save' : 'Create draft')}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        {editing ? (
          <Detail label="Candidate">{row.candidate_name || row.ccn_no}</Detail>
        ) : (
          <div>
            <label className={LABEL} htmlFor="of-ccn">Candidate</label>
            <select id="of-ccn" className={FIELD} value={form.ccn_no} onChange={set('ccn_no')}>
              <option value="">Select a selected candidate…</option>
              {candidates.map((c) => (
                <option key={c.ccn_no} value={c.ccn_no}>
                  {c.candidate_name} — {c.cr_no}
                </option>
              ))}
            </select>
            {!candidates.length && (
              <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
                Nobody has been selected by the client yet. The selection after the
                interview is what opens this stage.
              </p>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="of-ctc">Offered CTC</label>
            <input id="of-ctc" className={FIELD} type="number" value={form.offered_ctc}
              onChange={set('offered_ctc')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="of-join">Joining date</label>
            <input id="of-join" className={FIELD} type="date" value={form.joining_date}
              onChange={set('joining_date')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="of-desig">Designation</label>
          <input id="of-desig" className={FIELD} value={form.designation}
            onChange={set('designation')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="of-terms">Terms</label>
          <textarea id="of-terms" className={TEXTAREA} rows={3} value={form.terms}
            onChange={set('terms')} />
        </div>
        {editing && (
          <div>
            <label className={LABEL} htmlFor="of-neg">Negotiation notes</label>
            <textarea id="of-neg" className={TEXTAREA} rows={2}
              value={form.negotiation_notes} onChange={set('negotiation_notes')} />
          </div>
        )}
      </div>
    </Modal>
  );
};

/** The offer, what section 16 still wants, and the reference checks behind it. */
/**
 * The salary deviation request, as Client HR reads it.
 *
 * They are being asked to spend above the range they themselves approved, so the three
 * things that decide it are together and above the fold: the figure, the gap, and the
 * argument. The requisition's own range is NOT editable from here and never changes --
 * a deviation is permission for this one offer, not a new budget.
 */
const DeviationPanel = ({ deviation }) => {
  const asked = deviation.requested || {};
  const decided = deviation.decision || null;
  const lo = deviation.salary_range_min;
  const hi = deviation.salary_range_max;
  const ctc = deviation.offered_ctc;
  const over = (lo != null && hi != null && ctc != null)
    ? (ctc > hi ? ctc - hi : (ctc < lo ? lo - ctc : 0)) : null;

  return (
    <div className="border-t border-[var(--border)] pt-3.5">
      <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        Salary deviation
      </p>

      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <Detail label="Asking">{ctc != null ? money(ctc) : '—'}</Detail>
        <Detail label="Approved range">
          {lo != null && hi != null ? `${money(lo)} – ${money(hi)}` : '—'}
        </Detail>
        <Detail label={ctc != null && hi != null && ctc > hi ? 'Over by' : 'Outside by'}>
          {over ? money(over) : '—'}
        </Detail>
      </div>

      {asked.remarks && (
        <div className="mt-2.5 rounded-lg bg-[var(--input-bg)] px-3 py-2">
          <p className="text-[12px] text-[var(--text-main)]">{asked.remarks}</p>
          <p className="mt-1 text-[10.5px] text-[var(--text-muted)]">
            {asked.by_name || 'Sparsh'}{asked.at ? ` · ${day(asked.at)}` : ''}
          </p>
        </div>
      )}

      {decided ? (
        <p className={`mt-2 text-[12px] font-bold ${
          decided.decision === 'approve'
            ? 'text-[var(--accent-green,var(--accent-indigo))]'
            : 'text-[var(--accent-red)]'}`}>
          {decided.decision === 'approve' ? 'Approved' : 'Rejected'} by{' '}
          {decided.by_name || 'Client HR'}{decided.at ? ` · ${day(decided.at)}` : ''}
          {decided.remarks ? ` — ${decided.remarks}` : ''}
        </p>
      ) : (
        <p className="mt-2 text-[11.5px] text-[var(--text-muted)]">
          With Client HR. The approved requisition range is unchanged either way.
        </p>
      )}
    </div>
  );
};

const OfferDetail = ({ row, busy, onClose, onAct }) => {
  const { can } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const [checkpoint, setCheckpoint] = useState(null);
  const [references, setReferences] = useState([]);
  const [adding, setAdding] = useState(false);
  const [refBusy, setRefBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cp, refs] = await Promise.all([
        getClientOfferCheckpoint(row.cof_no, scope),
        getClientReferenceChecks({ ...scope, ccn_no: row.ccn_no, limit: 50 }),
      ]);
      setCheckpoint(cp.data || null);
      setReferences(refs.data?.client_reference_checks || []);
    } catch {
      setCheckpoint(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.cof_no, row.ccn_no, JSON.stringify(scope)]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal
      title={row.cof_no}
      subtitle={`${row.candidate_name || row.ccn_no} · ${row.cr_no}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Moves row={row} moves={MOVES} busy={busy} onAct={onAct} />
        </>
      )}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <StatusChip status={row.status} />
          {row.returned_reason && (
            <span className="text-[11.5px] text-[var(--accent-orange)]">
              Sent back: {row.returned_reason}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Detail label="Offered CTC">
            {row.offered_ctc != null ? money(row.offered_ctc) : '—'}
          </Detail>
          <Detail label="Approved range">
            {row.salary_range_min != null
              ? `${money(row.salary_range_min)} – ${money(row.salary_range_max)}`
              : '—'}
          </Detail>
          <Detail label="Designation">{row.designation}</Detail>
          <Detail label="Joining date">
            {row.joining_date ? day(row.joining_date) : '—'}
          </Detail>
          {row.terms && <Detail label="Terms" span>{row.terms}</Detail>}
          {row.negotiation_notes && (
            <Detail label="Negotiation" span>{row.negotiation_notes}</Detail>
          )}
        </div>

        {checkpoint && (
          <div className="border-t border-[var(--border)] pt-3.5">
            <div className="flex items-center gap-2">
              <ShieldCheck size={14} className={checkpoint.ready
                ? 'text-[var(--accent-green,var(--accent-indigo))]'
                : 'text-[var(--accent-orange)]'} />
              <p className="text-[10px] font-bold uppercase tracking-widest
                text-[var(--text-muted)]">Section 16 checkpoint</p>
            </div>
            {checkpoint.ready ? (
              <p className="mt-1.5 text-[12px] text-[var(--text-main)]">
                Nothing outstanding — this may be submitted for verification.
              </p>
            ) : (
              <ul className="mt-1.5 space-y-1">
                {(checkpoint.outstanding || []).map((o) => (
                  <li key={o} className="text-[12px] text-[var(--accent-orange)]">• {o}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {row.deviation && <DeviationPanel deviation={row.deviation} />}

        <div className="border-t border-[var(--border)] pt-3.5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest
                text-[var(--text-muted)]">Reference checks</p>
              <p className="text-[11px] text-[var(--text-muted)]">
                Section 15 asks for one before release on senior roles.
              </p>
            </div>
            {can(CAP.CLIENT_REFERENCE_WRITE) && (
              <Btn onClick={() => setAdding(true)}>Record one</Btn>
            )}
          </div>
          <div className="mt-2.5 space-y-2">
            {!references.length && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                None recorded yet.
              </p>
            )}
            {references.map((r, idx) => (
              <div key={r.reference_no || idx}
                className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)]
                  p-2.5 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                    {r.referee_name}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {[r.referee_organisation, r.relationship].filter(Boolean).join(' · ')
                      || '—'}
                    {r.checked_on ? ` · ${day(r.checked_on)}` : ''}
                  </p>
                  {r.remarks && (
                    <p className="text-[11px] text-[var(--text-muted)]">{r.remarks}</p>
                  )}
                </div>
                <StatusChip status={r.outcome} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {adding && (
        <ReferenceModal
          busy={refBusy}
          onClose={() => setAdding(false)}
          onSubmit={async (payload) => {
            setRefBusy(true);
            try {
              await recordClientReferenceCheck(
                { ...payload, ccn_no: row.ccn_no }, scope);
              showSuccess('Reference recorded');
              setAdding(false);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be recorded.');
            } finally {
              setRefBusy(false);
            }
          }}
        />
      )}
    </Modal>
  );
};

const ReferenceModal = ({ busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    referee_name: '', referee_organisation: '', relationship: '', referee_contact: '',
    outcome: 'Positive', checked_on: '', remarks: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Modal
      title="Record a reference check"
      subtitle="Who was spoken to, and what they said."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !form.referee_name.trim()}
            onClick={() => onSubmit({
              referee_name: form.referee_name.trim(),
              referee_organisation: form.referee_organisation || undefined,
              relationship: form.relationship || undefined,
              referee_contact: form.referee_contact || undefined,
              outcome: form.outcome,
              checked_on: form.checked_on || undefined,
              remarks: form.remarks || undefined,
            })}>
            {busy ? 'Saving…' : 'Record'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="rf-name">Referee</label>
            <input id="rf-name" className={FIELD} value={form.referee_name}
              onChange={set('referee_name')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="rf-org">Organisation</label>
            <input id="rf-org" className={FIELD} value={form.referee_organisation}
              onChange={set('referee_organisation')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="rf-rel">Relationship</label>
            <input id="rf-rel" className={FIELD} value={form.relationship}
              onChange={set('relationship')} placeholder="Reporting manager" />
          </div>
          <div>
            <label className={LABEL} htmlFor="rf-contact">Contact</label>
            <input id="rf-contact" className={FIELD} value={form.referee_contact}
              onChange={set('referee_contact')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="rf-outcome">Outcome</label>
            <select id="rf-outcome" className={FIELD} value={form.outcome}
              onChange={set('outcome')}>
              <option>Positive</option>
              <option>Mixed</option>
              <option>Negative</option>
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="rf-when">Checked on</label>
            <input id="rf-when" className={FIELD} type="date" value={form.checked_on}
              onChange={set('checked_on')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="rf-remarks">What they said</label>
          <textarea id="rf-remarks" className={TEXTAREA} rows={3} value={form.remarks}
            onChange={set('remarks')} />
        </div>
      </div>
    </Modal>
  );
};

export default ClientOffers;
