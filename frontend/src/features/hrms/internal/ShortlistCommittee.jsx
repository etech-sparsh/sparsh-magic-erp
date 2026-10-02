import React, { useCallback, useEffect, useState } from 'react';
import { Users2, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getShortlistReviews, getShortlistReview, createShortlistReview, updateShortlistReview,
  getRequisitions, getCandidates, getEmployees,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ internal track — the shortlisting committee (SOP §5).
 *
 * "HR and the Department Head shall jointly finalise the shortlist before the final
 * interview."
 *
 * The screen leads with what is PENDING, for the same reason the exception log does: a
 * sitting that was convened and never decided is a hire stalled and a control in limbo at
 * the same time.
 *
 * -- The two rules are shown, not just enforced --------------------------------------
 * A committee needs HR AND the Department Head, and two DIFFERENT people. The server
 * refuses a finalisation that does not meet both; this screen says which is outstanding
 * while the record is being assembled, so nobody meets the rule for the first time as a 422.
 *
 * -- The score is beside the name ------------------------------------------------------
 * Each candidate carries their weighted scorecard result and its band, so the committee
 * decides on the evidence rather than on who is remembered most vividly. The band is
 * advice: nothing here moves anybody, and finalising a candidate the guide bands as Reject
 * is a decision the committee is allowed to make and is recorded making.
 */

// Filter values only. 'Finalised' and 'Deferred' are how sittings were recorded before
// Final Commit; they can still be searched for, but never chosen (see DecideModal).
const OUTCOMES = ['Pending', 'Selected', 'Rejected', 'Final Interview Required',
  'Finalised', 'Deferred'];

const GOOD_OUTCOMES = ['Selected', 'Finalised'];

const outcomeTone = (outcome) => (GOOD_OUTCOMES.includes(outcome) ? 'good'
  : outcome === 'Rejected' ? 'bad'
    : outcome === 'Pending' ? 'warn' : 'neutral');

const ShortlistCommittee = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState('');
  const [convening, setConvening] = useState(false);
  const [deciding, setDeciding] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.SHORTLIST_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getShortlistReviews({
        ...scope, outcome: outcome || undefined,
      });
      setRows(data?.shortlist_reviews || []);
      setPending(data?.pending ?? 0);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the committee record.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, outcome]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    {
      key: 'slr',
      label: 'Sitting',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.slr_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.request_no}
          </span>
        </>
      ),
    },
    {
      key: 'candidates',
      label: 'Candidates',
      render: (r) => (
        <span className="text-[var(--text-main)]">
          {(r.candidate_uks || []).length}
        </span>
      ),
    },
    {
      key: 'committee',
      label: 'Committee',
      render: (r) => {
        const state = r.committee_state || {};
        return state.complete
          ? <Chip tone="good">{state.covered_roles?.join(' + ')}</Chip>
          : (
            <Chip tone="warn" title="SOP section 5 needs HR and the Department Head, and two different people.">
              needs {state.outstanding_roles?.join(', ') || 'a committee'}
            </Chip>
          );
      },
    },
    {
      key: 'outcome',
      label: 'Outcome',
      render: (r) => (
        <Chip tone={outcomeTone(r.outcome)}>{r.outcome}</Chip>
      ),
    },
    { key: 'decided', label: 'Decided', render: (r) => day(r.decided_at) },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (canWrite && r.outcome === 'Pending' ? (
        <Btn onClick={() => setDeciding(r)}>Decide</Btn>
      ) : null),
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Users2}
        title="Shortlisting committee"
        subtitle="HR and the Department Head jointly finalise the shortlist before the final interview (SOP section 5)."
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setConvening(true)}>
            <Plus size={14} /> Convene
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {pending > 0 && (
        <div className="rounded-xl border border-[var(--accent-orange)]/30
          bg-[var(--accent-orange-bg)] px-4 py-3">
          <p className="text-[12.5px] font-semibold text-[var(--accent-orange)]">
            {pending} sitting{pending === 1 ? '' : 's'} convened and not yet decided.
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            A candidate cannot reach Selected until a sitting has finalised them.
          </p>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <label className={LABEL} htmlFor="slr-outcome">Outcome</label>
        <select id="slr-outcome" className={`${FIELD} w-auto`} value={outcome}
          onChange={(e) => setOutcome(e.target.value)}>
          <option value="">All</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading committee sittings…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Users2}
          title="No committee sittings yet"
          hint="Convene one to record who agreed which candidates go to the final interview."
        />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.slr_no}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-[13px] text-[var(--text-main)]">
                    {r.slr_no}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">{r.request_no}</p>
                </div>
                <Chip tone={outcomeTone(r.outcome)}>{r.outcome}</Chip>
              </div>
              <Facts items={[
                { label: 'Candidates', value: (r.candidate_uks || []).length },
                { label: 'Members', value: r.committee_state?.member_count },
                { label: 'Decided', value: day(r.decided_at) },
              ]} />
              {canWrite && r.outcome === 'Pending' && (
                <Btn onClick={() => setDeciding(r)}>Decide</Btn>
              )}
            </div>
          )}
        />
      )}

      {convening && (
        <ConveneModal
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          onClose={() => setConvening(false)}
          onDone={() => { setConvening(false); load(); showSuccess('Sitting convened.'); }}
          onError={(m) => showError(m)}
        />
      )}

      {deciding && (
        <DecideModal
          review={deciding}
          scope={scope}
          busy={busy}
          onError={showError}
          onClose={() => setDeciding(null)}
          onSubmit={async (value) => {
            setBusy(true);
            try {
              await updateShortlistReview(deciding.slr_no, { outcome: value }, scope);
              showSuccess(`${deciding.slr_no} recorded as ${value}.`);
              setDeciding(null);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'The decision could not be recorded.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
};

/** Convene a sitting: pick the requisition, the candidates on it and who sat. */
const ConveneModal = ({ scope, busy, setBusy, onClose, onDone, onError }) => {
  const [reqs, setReqs] = useState([]);
  const [people, setPeople] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [requestNo, setRequestNo] = useState('');
  const [picked, setPicked] = useState([]);
  const [members, setMembers] = useState([]);
  const [notes, setNotes] = useState('');

  useEffect(() => {
    getRequisitions({ ...scope })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    // A committee member needs a real login account — a profile onboarded before the
    // person has one (`pending_user_link`) has no `user_id`, so it cannot be picked here.
    getEmployees(scope)
      .then(({ data }) => setPeople((data?.employees || []).filter((e) => e.user_id)))
      .catch(() => setPeople([]));
  }, [scope]);

  useEffect(() => {
    if (!requestNo) { setCandidates([]); setPicked([]); return; }
    getCandidates({ ...scope, request_no: requestNo })
      .then(({ data }) => setCandidates(data?.candidates || []))
      .catch(() => setCandidates([]));
  }, [requestNo, scope]);

  const toggle = (list, setList, value) =>
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const submit = async () => {
    setBusy(true);
    try {
      await createShortlistReview({
        request_no: requestNo,
        candidate_uks: picked,
        committee_members: members.map((user_id) => ({ user_id, decision: 'Agree' })),
        outcome: 'Pending',
        notes,
      }, scope);
      onDone();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The sitting could not be convened.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Convene a shortlisting committee"
      subtitle="Convening decides nothing. Finalise it once the committee has agreed."
      labelledBy="slr-convene"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !requestNo || !members.length}
            onClick={submit}>
            Convene
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="slr-req">Requisition *</label>
        <select id="slr-req" className={FIELD} value={requestNo}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Choose an internal requisition</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
      </div>

      {!!candidates.length && (
        <div>
          <span className={LABEL}>Candidates</span>
          <div className="space-y-1.5 max-h-52 overflow-y-auto">
            {candidates.map((c) => (
              <label key={c.uk}
                className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
                <input type="checkbox" checked={picked.includes(c.uk)}
                  onChange={() => toggle(picked, setPicked, c.uk)} />
                <span className="flex-1 min-w-0 truncate">{c.candidate_name}</span>
                {/* The evidence, beside the name. Advice, never a decision. */}
                {c.scorecard_band && (
                  <Chip tone={toneFor(c.scorecard_band)} title="Scoring decision guide">
                    {c.scorecard_score} · {c.scorecard_band}
                  </Chip>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      <div>
        <span className={LABEL}>Committee members *</span>
        <p className="text-[11px] text-[var(--text-muted)] mb-1.5">
          SOP section 5 needs HR and the Department Head — two different people. The server
          checks the roles; it will not accept one person covering both.
        </p>
        <div className="space-y-1.5 max-h-40 overflow-y-auto">
          {people.map((p) => (
            <label key={p.user_id}
              className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" checked={members.includes(p.user_id)}
                onChange={() => toggle(members, setMembers, p.user_id)} />
              <span className="truncate">{p.display_name || p.full_name || p.email}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="slr-notes">Notes</label>
        <textarea id="slr-notes" rows={3} className={TEXTAREA} value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What the committee weighed up." />
      </div>
    </Modal>
  );
};

/**
 * Final Commit — record each member's verdict; the outcome follows from them.
 *
 * There is deliberately no outcome dropdown. Selected, Rejected and Final Interview Required
 * are CONSEQUENCES, not choices: they follow from what each approver said and how senior the
 * role is. Offering a menu asked the committee for a conclusion instead of the facts behind
 * it, which is how a sitting could once be recorded as agreed over a Head's objection.
 *
 * What the menu HID, and what this modal now exposes, is the input. Convening stamped every
 * member as agreeing and there was nowhere at all to say otherwise, so "Rejected" was
 * unreachable through the interface however the backend behaved. The verdict controls below
 * are that missing input, and the member picker is how an inquorate sitting gets fixed
 * without abandoning it.
 *
 * Changes are saved as they are made and the preview is then re-read FROM THE SERVER. The
 * rule is never re-implemented here: a predicted outcome that disagreed with the recorded
 * one would be worse than no prediction at all.
 */
const DecideModal = ({ review, scope, busy, onClose, onSubmit, onError }) => {
  const [full, setFull] = useState(null);
  const [people, setPeople] = useState([]);
  const [adding, setAdding] = useState('');
  const [saving, setSaving] = useState(false);
  const [loadErr, setLoadErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await getShortlistReview(review.slr_no, scope);
      setFull(data || null);
      setLoadErr(null);
    } catch (err) {
      setLoadErr(err?.response?.data?.detail || 'Could not load this sitting.');
    }
  }, [review.slr_no, scope]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    getEmployees(scope)
      .then(({ data }) => setPeople((data?.employees || []).filter((e) => e.user_id)))
      .catch(() => setPeople([]));
  }, [scope]);

  const members = full?.committee_members || [];
  const state = full?.committee_state || review.committee_state || {};
  const preview = full?.commit_preview || null;
  const uks = full?.candidate_uks || review.candidate_uks || [];

  /** Persist the committee as it now stands, then re-read the server's verdict. */
  const saveMembers = async (next) => {
    setSaving(true);
    try {
      await updateShortlistReview(review.slr_no, {
        committee_members: next.map((m) => ({
          user_id: m.user_id,
          decision: m.decision || 'Agree',
          recused: !!m.recused,
        })),
      }, scope);
      await load();
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not update the committee.');
    } finally {
      setSaving(false);
    }
  };

  const setVerdict = (userId, decision) =>
    saveMembers(members.map((m) => (m.user_id === userId ? { ...m, decision } : m)));

  const removeMember = (userId) =>
    saveMembers(members.filter((m) => m.user_id !== userId));

  const addMember = () => {
    if (!adding) return;
    saveMembers([...members, { user_id: adding, decision: 'Agree' }]);
    setAdding('');
  };

  const unpicked = people.filter(
    (p) => !members.some((m) => String(m.user_id) === String(p.user_id)));
  const outcome = preview?.outcome;
  const working = busy || saving;

  return (
    <Modal
      title={`Final Commit — ${review.slr_no}`}
      subtitle="A decided sitting is frozen. A second decision is a second sitting."
      labelledBy="slr-decide"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={working}>Cancel</Btn>
          <Btn tone={outcome === 'Rejected' ? 'danger' : 'primary'}
            disabled={working || !outcome}
            onClick={() => onSubmit(outcome)}>
            {working ? 'Working…' : `Record ${outcome || ''}`.trim()}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Requisition', value: review.request_no },
        { label: 'Candidates', value: uks.length },
        { label: 'Role level', value: preview?.designation_level || '—' },
      ]} />

      <div>
        <p className={LABEL}>Committee verdicts</p>
        <div className="mt-1.5 space-y-1.5">
          {members.map((m) => {
            const objecting = m.decision === 'Object';
            return (
              <div key={m.user_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] px-3 py-2">
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)] truncate">
                    {m.name || m.user_id}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {m.role || 'no HRMS role'}{m.recused ? ' · recused' : ''}
                  </p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <Btn tone={objecting ? 'ghost' : 'primary'} disabled={working}
                    onClick={() => setVerdict(m.user_id, 'Agree')}>
                    Approve
                  </Btn>
                  <Btn tone={objecting ? 'danger' : 'ghost'} disabled={working}
                    onClick={() => setVerdict(m.user_id, 'Object')}>
                    Do not approve
                  </Btn>
                  <Btn disabled={working} onClick={() => removeMember(m.user_id)}>
                    Remove
                  </Btn>
                </div>
              </div>
            );
          })}
          {!members.length && (
            <p className="text-[12px] text-[var(--text-muted)]">
              Nobody is on this committee yet.
            </p>
          )}
        </div>

        <div className="mt-2 flex items-center gap-2">
          <select className={FIELD} value={adding} aria-label="Add a committee member"
            onChange={(e) => setAdding(e.target.value)}>
            <option value="">Add a member…</option>
            {unpicked.map((p) => (
              <option key={p.user_id} value={p.user_id}>
                {p.display_name || p.full_name || p.employee_code}
              </option>
            ))}
          </select>
          <Btn disabled={working || !adding} onClick={addMember}>Add</Btn>
        </div>
      </div>

      {!state.complete && (
        <p className="text-[12px] text-[var(--accent-orange)] font-semibold">
          Still needed: {(state.outstanding_roles || []).join(', ')}. A sitting can only be
          committed once Human Resources and the hiring manager are both on it, as two
          different people.
        </p>
      )}
      {loadErr && (
        <p className="text-[12px] text-[var(--accent-red,var(--accent-orange))]">{loadErr}</p>
      )}

      {outcome ? (
        <div>
          <p className={LABEL}>This commit records</p>
          <div className="flex items-center gap-2 mt-1">
            <Chip tone={outcomeTone(outcome)}>{outcome}</Chip>
            <span className="text-[12px] text-[var(--text-muted)]">{preview.because}</span>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-2">
            {outcome === 'Selected'
              ? 'The named candidates move to Selected and can be made an offer.'
              : outcome === 'Rejected'
                ? 'The named candidates are rejected on this requisition.'
                : 'The named candidates go to the Management final round. Nobody is selected until it is passed.'}
          </p>
        </div>
      ) : !loadErr && (
        <p className="text-[12px] text-[var(--text-muted)]">
          {!state.complete
            ? 'Add the missing member above and the outcome will appear here.'
            : !uks.length
              ? 'This sitting names no candidates, so there is nothing to decide about.'
              : 'Working out what this sitting decides…'}
        </p>
      )}
    </Modal>
  );
};

export default ShortlistCommittee;
