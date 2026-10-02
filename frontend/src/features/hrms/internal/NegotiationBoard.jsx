import React, { useCallback, useEffect, useState } from 'react';
import { Scale, Plus, Search } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getNegotiationRounds, getCandidateNegotiation, recordNegotiationRound,
  getExceptions, raiseException,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — salary negotiation (SOP step 9, spec §16).
 *
 * The rule was always enforced at the offer: a CTC outside the band stamped at the budget
 * gate is refused. This screen is the RECORD the rule never had — the rounds, what the
 * candidate asked for, what was proposed, and how each sat against the band.
 *
 * Two things it has to make obvious:
 *
 *   - WITHIN / ABOVE / BELOW, at a glance, for every round. That is what spec §16 asks to
 *     display, and a number with no band beside it displays nothing.
 *   - THAT RECORDING A ROUND DECIDES NOTHING. An above-band round is allowed to exist —
 *     the conversation is allowed to happen — but the offer will still be refused until the
 *     budget is re-approved or an exception is approved. The candidate drawer says which.
 */

const money = (v) => (v == null ? '—'
  : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));

const verdictTone = (v) => ({ within: 'good', above: 'bad', below: 'warn' }[v] || 'neutral');
const verdictLabel = (v) => ({
  within: 'Within band', above: 'Above band', below: 'Below band',
}[v] || 'Unbanded');

const NegotiationBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(null);     // null | {} | { uk }
  const [inspecting, setInspecting] = useState(null);
  // Budget requests already raised, so a round can show where its approval stands instead
  // of inviting a second request the server would refuse as a duplicate.
  const [budgetAsks, setBudgetAsks] = useState([]);
  const [asking, setAsking] = useState(null);    // the round a request is being raised for
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.NEGOTIATION_WRITE);
  const canAskBudget = can(CAP.EXCEPTION_WRITE);

  /** The Offer Outside Budget request covering this round, if there is one. */
  const askFor = (r) => budgetAsks.find(
    (e) => e.request_no === r.request_no
      && (e.uk === r.uk || !e.uk)
      && e.exception_type === 'Offer Outside Budget');

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getNegotiationRounds({ ...scope, limit: 300 });
      setRows(data?.rounds || []);
      try {
        const { data: exc } = await getExceptions({ ...scope, limit: 300 });
        setBudgetAsks((exc?.exceptions || []).filter(
          (e) => e.exception_type === 'Offer Outside Budget'));
      } catch {
        // The rounds are the point of this screen; not being able to read the exception
        // log should dim the approval status, never blank the board.
        setBudgetAsks([]);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load negotiation rounds.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'candidate', label: 'Candidate',
      render: (r) => (
        <>
          <button type="button" onClick={() => setInspecting(r.uk)}
            className="font-semibold text-[var(--text-main)] hover:underline text-left">
            {r.candidate_name || r.uk}
          </button>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.uk} · {r.request_no} · round {r.round}
          </span>
        </>
      ) },
    { key: 'asked', label: 'Candidate asked',
      render: (r) => <span className="tabular-nums">{money(r.candidate_expectation)}</span> },
    { key: 'proposed', label: 'Proposed',
      render: (r) => (
        <span className="tabular-nums font-semibold text-[var(--text-main)]">
          {money(r.proposed_ctc)}
        </span>
      ) },
    { key: 'band', label: 'Approved band',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)]">
          {money(r.band_min)} – {money(r.band_max)}
        </span>
      ) },
    { key: 'recorded', label: 'Recorded',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.recorded_at)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.recorded_by_name || '—'}
          </span>
        </>
      ) },
    { key: 'verdict', label: 'Verdict', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1">
          <Chip tone={verdictTone(r.verdict)}>{verdictLabel(r.verdict)}</Chip>
          <BudgetAskCell round={r} ask={askFor(r)} canAsk={canAskBudget}
            onAsk={() => setAsking(r)} />
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
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.neg_no} · round {r.round}
          </p>
        </div>
        <Chip tone={verdictTone(r.verdict)}>{verdictLabel(r.verdict)}</Chip>
      </div>
      <Facts items={[
        { label: 'Asked', value: money(r.candidate_expectation) },
        { label: 'Proposed', value: money(r.proposed_ctc) },
        { label: 'Band', value: `${money(r.band_min)} – ${money(r.band_max)}` },
        { label: 'Recorded', value: day(r.recorded_at) },
      ]} />
      {r.notes && <p className="text-[12px] text-[var(--text-muted)]">{r.notes}</p>}
      <BudgetAskCell round={r} ask={askFor(r)} canAsk={canAskBudget}
        onAsk={() => setAsking(r)} />
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Scale}
        title="Salary negotiation"
        subtitle="Every round against the band Management approved — recording a round decides nothing; the offer gate still does"
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setAdding({})}>
            <Plus size={14} /> Record a round
          </Btn>
        )}
      />
      <HrmsScopeBar />

      <p className="text-[11.5px] text-[var(--text-muted)]">
        A proposal <b>above</b> or <b>below</b> the band is recorded, not refused — the
        conversation is allowed to happen. The <b>offer</b> is what the band gate refuses,
        until the budget is re-approved at the new figure or an <i>Offer Outside Budget</i>
        request is approved. Use <b>Request budget approval</b> on an above-band round to
        ask Finance for a specific figure; the offer is then held to whatever they grant.
      </p>

      {asking && (
        <BudgetAskModal
          round={asking}
          busy={busy}
          onClose={() => setAsking(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await raiseException({
                request_no: asking.request_no,
                uk: asking.uk,
                exception_type: 'Offer Outside Budget',
                requested_ctc: payload.requested_ctc,
                reason: payload.reason,
              }, scope);
              showSuccess(`${data.exc_no} sent to Finance — the offer stays blocked `
                + 'until they approve a figure');
              setAsking(null);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'The budget request could not be raised.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {loading && <HrmsLoading label="Loading negotiation rounds…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.neg_no}
          empty={<HrmsEmpty
            icon={Scale}
            title="No negotiation rounds recorded"
            hint="Rounds can be recorded once a candidate's requisition has an approved salary band."
          />}
        />
      )}

      {adding && (
        <RoundModal
          scope={scope}
          preset={adding}
          onClose={() => setAdding(null)}
          onDone={() => { setAdding(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
      {inspecting && (
        <CandidateDrawer
          scope={scope}
          uk={inspecting}
          canWrite={canWrite}
          onClose={() => setInspecting(null)}
          onRecord={() => { setInspecting(null); setAdding({ uk: inspecting }); }}
        />
      )}
    </div>
  );
};

const RoundModal = ({ scope, preset, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState({
    uk: preset?.uk || '', proposed_ctc: '', candidate_expectation: '', notes: '',
  });
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async () => {
    if (!form.uk.trim() || !form.proposed_ctc) {
      showError('A candidate and a proposed CTC are both required.');
      return;
    }
    setBusy(true);
    try {
      const payload = {
        uk: form.uk.trim(),
        proposed_ctc: Number(form.proposed_ctc),
        candidate_expectation: form.candidate_expectation
          ? Number(form.candidate_expectation) : null,
        notes: form.notes || null,
      };
      const { data } = await recordNegotiationRound(payload, scope);
      showSuccess(data.verdict === 'within'
        ? `${data.neg_no} recorded — round ${data.round} is within the approved band`
        : `${data.neg_no} recorded — round ${data.round} is ${data.verdict} the band; `
          + 'an offer at this figure will need fresh approval');
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the round.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Record a negotiation round" labelledBy="neg-add-title"
      subtitle="What the candidate asked for, and what was proposed back"
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
          <label className={LABEL} htmlFor="neg-uk">Candidate ID *</label>
          <input id="neg-uk" value={form.uk} onChange={set('uk')} className={FIELD}
            placeholder="CAN-001" readOnly={Boolean(preset?.uk)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="neg-asked">Candidate&rsquo;s expectation</label>
          <input id="neg-asked" type="number" min="1" step="1000"
            value={form.candidate_expectation} onChange={set('candidate_expectation')}
            className={FIELD} />
        </div>
        <div>
          <label className={LABEL} htmlFor="neg-proposed">Proposed CTC *</label>
          <input id="neg-proposed" type="number" min="1" step="1000"
            value={form.proposed_ctc} onChange={set('proposed_ctc')} className={FIELD} />
        </div>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        The verdict is computed server-side against the band stamped on the requisition at
        its budget gate — the same comparison the offer gate makes.
      </p>
      <div>
        <label className={LABEL} htmlFor="neg-notes">Notes</label>
        <textarea id="neg-notes" rows={3} value={form.notes} onChange={set('notes')}
          className={TEXTAREA} placeholder="Candidate cited a competing offer; agreed to revisit after the final interview." />
      </div>
    </Modal>
  );
};

/** The spec §16 comparison surface for one candidate. */
const CandidateDrawer = ({ scope, uk, canWrite, onClose, onRecord }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    getCandidateNegotiation(uk, scope)
      .then((r) => { if (alive) setData(r.data); })
      .catch((err) => {
        if (alive) setError(err?.response?.data?.detail || 'Could not load the comparison.');
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk]);

  return (
    <Modal
      title={data ? `${data.candidate_name || uk} — negotiation` : 'Loading…'}
      labelledBy="neg-drawer-title"
      subtitle={data?.designation_name ? `${data.designation_name} · ${data.request_no}` : ''}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          {canWrite && <Btn tone="primary" onClick={onRecord}><Plus size={14} /> New round</Btn>}
        </>
      )}
    >
      {error && <p className="text-[12px] text-[var(--text-muted)]">{error}</p>}
      {data && (
        <>
          <Facts items={[
            { label: 'Approved band',
              value: data.band.min != null
                ? `${money(data.band.min)} – ${money(data.band.max)}` : 'Not approved yet' },
            { label: 'Band approved', value: data.band.approved_at
              ? `${day(data.band.approved_at)} · ${data.band.approved_by_name || ''}` : '—' },
            { label: 'Candidate asked', value: money(data.candidate_expectation) },
            { label: 'Latest proposal',
              value: data.latest_round ? money(data.latest_round.proposed_ctc) : '—' },
          ]} />

          <div className="rounded-xl border border-[var(--border)] p-3 flex items-start
            justify-between gap-3 flex-wrap">
            <div>
              <p className="text-[12px] font-bold text-[var(--text-main)]">
                Would an offer at the latest figure pass the band gate today?
              </p>
              <p className="text-[11.5px] text-[var(--text-muted)] max-w-xl">
                {data.offer_gate_note}
              </p>
            </div>
            <Chip tone={data.offer_would_pass === true ? 'good'
              : data.offer_would_pass === false ? 'bad' : 'neutral'}>
              {data.offer_would_pass === true ? 'Yes'
                : data.offer_would_pass === false ? 'No' : 'No round yet'}
            </Chip>
          </div>

          {data.rounds.length > 0 && (
            <div>
              <p className={LABEL}>Rounds</p>
              <ol className="space-y-1.5">
                {data.rounds.map((r) => (
                  <li key={r.neg_no} className="flex items-center justify-between gap-3
                    text-[12.5px]">
                    <span className="text-[var(--text-muted)]">
                      {r.round}. {day(r.recorded_at)} — asked {money(r.candidate_expectation)},
                      proposed <b className="text-[var(--text-main)]">{money(r.proposed_ctc)}</b>
                      {' '}vs {money(r.band_min)}–{money(r.band_max)}
                    </span>
                    <Chip tone={verdictTone(r.verdict)}>{verdictLabel(r.verdict)}</Chip>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
      {!data && !error && (
        <p className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
          <Search size={13} /> Loading…
        </p>
      )}
    </Modal>
  );
};

/**
 * Where a round's budget approval stands, or the way to ask for one.
 *
 * The board used to say "an offer here needs fresh approval" and stop there, which named a
 * requirement and offered no way to meet it. Anyone reading that had to work out for
 * themselves that the answer lived in the exception log, under a type called Offer Outside
 * Budget. That is a gap between what a screen asks for and what it lets you do.
 */
const BudgetAskCell = ({ round, ask, canAsk, onAsk }) => {
  if (!round.verdict || round.verdict === 'within') return null;

  if (ask?.status === 'Approved') {
    return (
      <span className="text-[10.5px] text-[var(--accent-green,var(--text-muted))]">
        Finance approved up to {money(ask.approved_ctc ?? ask.requested_ctc)} ({ask.exc_no})
      </span>
    );
  }
  if (ask?.status === 'Pending') {
    return (
      <span className="text-[10.5px] text-[var(--text-muted)]">
        {ask.exc_no} with Finance, asking {money(ask.requested_ctc)}
      </span>
    );
  }
  if (ask?.status === 'Rejected') {
    return (
      <span className="text-[10.5px] text-[var(--accent-red,var(--accent-orange))]">
        Finance refused {ask.exc_no} — renegotiate inside the band
      </span>
    );
  }
  // Below-band needs no budget: the money is already approved. Saying "request approval"
  // there would send somebody to ask Finance for permission to spend less.
  if (round.verdict === 'below') {
    return (
      <span className="text-[10.5px] text-[var(--text-muted)]">
        below the band — the offer gate still asks for fresh approval
      </span>
    );
  }
  if (!canAsk) {
    return (
      <span className="text-[10.5px] text-[var(--text-muted)]">
        an offer here needs Finance to approve a higher figure
      </span>
    );
  }
  return <Btn onClick={onAsk}>Request budget approval</Btn>;
};

/** Ask Finance for a figure. A request for "more" is not a request anybody can decide. */
const BudgetAskModal = ({ round, busy, onClose, onSubmit }) => {
  const [amount, setAmount] = useState(String(round.proposed_ctc ?? ''));
  const [reason, setReason] = useState('');
  const asking = Number(amount);
  const overBand = asking > Number(round.band_max || 0);

  return (
    <Modal
      title="Request budget approval"
      subtitle={`${round.candidate_name || round.uk} · ${round.request_no}`}
      labelledBy="neg-budget-ask"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !(asking > 0) || !reason.trim() || !overBand}
            onClick={() => onSubmit({ requested_ctc: asking, reason: reason.trim() })}>
            {busy ? 'Sending…' : 'Send to Finance'}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Approved band', value: `${money(round.band_min)} – ${money(round.band_max)}` },
        { label: 'Proposed this round', value: money(round.proposed_ctc) },
        { label: 'Candidate asked', value: money(round.candidate_expectation) },
      ]} />

      <div>
        <label className={LABEL} htmlFor="neg-ask-ctc">CTC you are asking Finance for *</label>
        <input id="neg-ask-ctc" type="number" min="1" value={amount} className={FIELD}
          onChange={(e) => setAmount(e.target.value)} />
        {!overBand && asking > 0 && (
          <p className="mt-1 text-[11px] text-[var(--accent-orange)]">
            {money(asking)} is already inside the approved band. No request is needed —
            make the offer.
          </p>
        )}
      </div>

      <div>
        <label className={LABEL} htmlFor="neg-ask-reason">Why the deviation is needed *</label>
        <textarea id="neg-ask-reason" rows={4} value={reason} className={TEXTAREA}
          placeholder="What the candidate is holding out for, and why this hire is worth it."
          onChange={(e) => setReason(e.target.value)} />
      </div>

      <p className="text-[11.5px] text-[var(--text-muted)]">
        Finance may approve less than you ask for, never more. The offer is then held to
        whatever they grant, so an offer above that figure is refused exactly as one above
        the band is. Whoever raises this cannot approve it.
      </p>
    </Modal>
  );
};

export default NegotiationBoard;
