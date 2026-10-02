import React, { useCallback, useEffect, useState } from 'react';
import { HeartHandshake, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getPreboarding, getPreboardingDue, recordPreboardingTouchpoint,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ internal track — pre-boarding engagement (SOP §6).
 *
 * The window between "they accepted" and "they walked in" is where an offer is lost to a
 * counter-offer. This screen is what makes that window visible.
 *
 * -- NOTHING HERE IS A GATE ------------------------------------------------------------
 * Worth saying plainly, because every other internal-track screen in this module is a
 * control. A candidate with no touchpoint onboards exactly as they always did; no status is
 * blocked and no offer is refused. What this does is put people on a worklist and raise a
 * flag when somebody says out loud that they might not come.
 *
 * -- Two lists, not one ------------------------------------------------------------------
 * "Nobody has spoken to them at all" and "we have let it slip" are different conversations,
 * so they are different lists — the same split `/probation/due` draws. One date-sorted list
 * would leave the reader to work out which is which.
 */

const MODES = ['Call', 'Email', 'WhatsApp', 'Meeting'];
const SENTIMENTS = ['Positive', 'Neutral', 'At Risk'];

const sentimentTone = (value) => ({
  Positive: 'good', Neutral: 'neutral', 'At Risk': 'bad',
}[value] || 'neutral');

const PreboardingBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [due, setDue] = useState({ never_contacted: [], gone_quiet: [] });
  const [rows, setRows] = useState([]);
  const [atRisk, setAtRisk] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [logging, setLogging] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.PREBOARDING_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [dueRes, logRes] = await Promise.all([
        getPreboardingDue(scope),
        getPreboarding(scope),
      ]);
      setDue(dueRes.data || { never_contacted: [], gone_quiet: [] });
      setRows(logRes.data?.touchpoints || []);
      setAtRisk(logRes.data?.at_risk ?? 0);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load pre-boarding.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const dueColumns = [
    {
      key: 'who',
      label: 'Joining',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.candidate_name}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.designation_name || r.request_no}
          </span>
        </>
      ),
    },
    { key: 'stage', label: 'Stage', render: (r) => <Chip>{r.application_status}</Chip> },
    {
      key: 'last',
      label: 'Last contact',
      render: (r) => (r.last_contacted_at ? (
        <>
          {day(r.last_contacted_at)}
          {r.last_sentiment && (
            <Chip tone={sentimentTone(r.last_sentiment)}>{r.last_sentiment}</Chip>
          )}
        </>
      ) : <span className="text-[var(--text-muted)]">never</span>),
    },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (canWrite
        ? <Btn onClick={() => setLogging(r)}>Log contact</Btn>
        : null),
    },
  ];

  const dueCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-[13px] text-[var(--text-main)]">
            {r.candidate_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.designation_name || r.request_no}
          </p>
        </div>
        <Chip>{r.application_status}</Chip>
      </div>
      <Facts items={[
        { label: 'Last contact', value: r.last_contacted_at ? day(r.last_contacted_at) : 'never' },
        { label: 'Recruiter', value: r.assigned_recruiter_name },
      ]} />
      {canWrite && <Btn onClick={() => setLogging(r)}>Log contact</Btn>}
    </div>
  );

  const totalDue = (due.never_contacted?.length || 0) + (due.gone_quiet?.length || 0);

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={HeartHandshake}
        title="Pre-Joiners"
        subtitle="Staying in touch between the accepted offer and the first day (SOP section 6). Tracking, not a gate — nothing is blocked by it."
      />
      <HrmsScopeBar />

      {atRisk > 0 && (
        <div className="rounded-xl border border-[var(--accent-red)]/30
          bg-[var(--accent-red-bg)] px-4 py-3">
          <p className="text-[12.5px] font-semibold text-[var(--accent-red)]">
            {atRisk} touchpoint{atRisk === 1 ? '' : 's'} flagged At Risk.
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            The recruiter and the HOD were notified when each was recorded.
          </p>
        </div>
      )}

      {loading && <HrmsLoading label="Loading pre-boarding…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <section className="space-y-3">
            <h2 className="text-[11px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Nobody has contacted them yet ({due.never_contacted?.length || 0})
            </h2>
            {due.never_contacted?.length ? (
              <RecordList rows={due.never_contacted} columns={dueColumns}
                keyOf={(r) => r.uk} renderCard={dueCard} />
            ) : (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Everyone who has accepted has been spoken to at least once.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-[11px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Gone quiet — no contact in {due.within_days ?? 7} days
              {' '}({due.gone_quiet?.length || 0})
            </h2>
            {due.gone_quiet?.length ? (
              <RecordList rows={due.gone_quiet} columns={dueColumns}
                keyOf={(r) => r.uk} renderCard={dueCard} />
            ) : (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Nobody has slipped past the {due.within_days ?? 7}-day mark.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-[11px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Recent touchpoints
            </h2>
            {rows.length ? (
              <RecordList
                rows={rows}
                keyOf={(r) => r.pbt_no}
                columns={[
                  {
                    key: 'who',
                    label: 'Candidate',
                    render: (r) => (
                      <>
                        <span className="font-semibold text-[var(--text-main)]">
                          {r.candidate_name}
                        </span>
                        <span className="block text-[11px] text-[var(--text-muted)]">
                          {r.pbt_no}
                        </span>
                      </>
                    ),
                  },
                  { key: 'mode', label: 'Mode', render: (r) => r.mode },
                  { key: 'when', label: 'When', render: (r) => day(r.contacted_at) },
                  {
                    key: 'sentiment',
                    label: 'Sentiment',
                    render: (r) => (
                      <>
                        <Chip tone={sentimentTone(r.sentiment)}>{r.sentiment}</Chip>
                        {r.counter_offer_disclosed && (
                          <Chip tone="warn" title="They told us about another offer.">
                            counter-offer
                          </Chip>
                        )}
                      </>
                    ),
                  },
                  { key: 'by', label: 'By', render: (r) => r.contacted_by_name },
                ]}
                renderCard={(r) => (
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-semibold text-[13px] text-[var(--text-main)]">
                        {r.candidate_name}
                      </p>
                      <Chip tone={sentimentTone(r.sentiment)}>{r.sentiment}</Chip>
                    </div>
                    <Facts items={[
                      { label: 'Mode', value: r.mode },
                      { label: 'When', value: day(r.contacted_at) },
                      { label: 'By', value: r.contacted_by_name },
                    ]} />
                    {r.notes && (
                      <p className="text-[12px] text-[var(--text-muted)]">{r.notes}</p>
                    )}
                  </div>
                )}
              />
            ) : (
              <HrmsEmpty
                icon={HeartHandshake}
                title="No touchpoints recorded yet"
                hint="Log a call or an email against anybody who has accepted and not yet joined."
              />
            )}
          </section>
        </>
      )}

      {logging && (
        <LogModal
          candidate={logging}
          busy={busy}
          onClose={() => setLogging(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await recordPreboardingTouchpoint(
                { ...payload, candidate_uk: logging.uk }, scope);
              showSuccess('Touchpoint recorded.');
              setLogging(null);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'The touchpoint could not be recorded.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {!loading && !error && totalDue === 0 && !rows.length && null}
    </div>
  );
};

const LogModal = ({ candidate, busy, onClose, onSubmit }) => {
  const [mode, setMode] = useState('Call');
  const [sentiment, setSentiment] = useState('Positive');
  const [counterOffer, setCounterOffer] = useState(false);
  const [notes, setNotes] = useState('');
  const atRisk = sentiment === 'At Risk';

  return (
    <Modal
      title={`Contact with ${candidate.candidate_name}`}
      subtitle="What they said, and how it felt. Nothing here changes their stage."
      labelledBy="pbt-log"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || (atRisk && !notes.trim())}
            onClick={() => onSubmit({
              mode, sentiment, counter_offer_disclosed: counterOffer, notes,
            })}>
            Record
          </Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="pbt-mode">How</label>
          <select id="pbt-mode" className={FIELD} value={mode}
            onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="pbt-sentiment">How it felt</label>
          <select id="pbt-sentiment" className={FIELD} value={sentiment}
            onChange={(e) => setSentiment(e.target.value)}>
            {SENTIMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <label className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={counterOffer}
          onChange={(e) => setCounterOffer(e.target.checked)} />
        They mentioned another offer
      </label>

      <div>
        <label className={LABEL} htmlFor="pbt-notes">
          Notes {atRisk && <span className="text-[var(--accent-red)]">*</span>}
        </label>
        <textarea id="pbt-notes" rows={4} className={TEXTAREA} value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What they actually said." />
        {atRisk && (
          <p className="mt-1 text-[11px] text-[var(--accent-orange)]">
            An At Risk flag notifies the recruiter and the HOD. Say what they told you — a
            flag with no story behind it tells them to worry and nothing else.
          </p>
        )}
      </div>
    </Modal>
  );
};

export default PreboardingBoard;
