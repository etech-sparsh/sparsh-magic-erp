import React, { useCallback, useEffect, useState } from 'react';
import { Phone, Plus, UserRound } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getTelephonicScreenings, getScreenableCandidates, createTelephonicScreening,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — telephonic screening (SOP step 5).
 *
 * The brief call HR makes between CV screening and the panel interview. A PASSED screen is
 * what clears a candidate for an interview; the gate is enforced server-side on interview
 * creation, so this screen never has to pretend to be the control.
 *
 * Two things the screen has to keep visibly apart:
 *
 *   - FACTS the candidate stated (notice period, expectation, location, availability) from
 *     JUDGEMENTS the caller made (the four ratings). A rating is not a joining date.
 *   - RECORDED from CLEARED. "No Answer" is a real record of a real attempt and clears
 *     nothing, which is why it is a warn chip rather than a neutral one.
 *
 * The "to call" list is a work queue, not a filter of the records below — it answers "who
 * am I ringing today", which is the question HR actually opens this screen with.
 */

const OUTCOMES = ['Passed', 'Rejected', 'No Answer'];

const CRITERIA = [
  ['communication', 'Communication'],
  ['role_understanding', 'Role understanding'],
  ['motivation', 'Motivation'],
  ['suitability', 'Initial suitability'],
];

const TelephonicBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState('');
  const [adding, setAdding] = useState(null);   // null | {} | { uk, candidate_name }

  const canWrite = can(CAP.TELEPHONIC_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [list, screenable] = await Promise.all([
        getTelephonicScreenings({ ...scope, outcome: outcome || undefined, limit: 200 }),
        getScreenableCandidates(scope),
      ]);
      setRows(list?.data?.telephonic_screenings || []);
      setQueue(Array.isArray(screenable?.data) ? screenable.data : []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load telephonic screenings.');
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
            {r.uk} · {r.tel_no}
          </span>
        </>
      ) },
    { key: 'facts', label: 'What they said',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">
            {r.notice_period_days == null ? 'Notice —' : `${r.notice_period_days}d notice`}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {[r.current_location, r.availability].filter(Boolean).join(' · ') || '—'}
          </span>
        </>
      ) },
    { key: 'score', label: 'Score',
      render: (r) => (
        r.score == null
          ? <span className="text-[var(--text-muted)]">Not rated</span>
          : (
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[var(--text-main)]">
                {Number(r.score).toFixed(2)}
              </span>
              {r.band && <Chip tone={toneFor(r.band)}>{r.band}</Chip>}
            </div>
          )
      ) },
    { key: 'screened', label: 'Screened',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.screened_on)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.screened_by_name || '—'}
            {r.duration_minutes ? ` · ${r.duration_minutes} min` : ''}
          </span>
        </>
      ) },
    { key: 'outcome', label: 'Outcome', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1">
          <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
          {r.outcome !== 'Passed' && (
            <span className="text-[10.5px] text-[var(--text-muted)]">
              does not clear an interview
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
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.tel_no}</p>
        </div>
        <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
      </div>
      <Facts items={[
        { label: 'Score', value: r.score == null ? 'Not rated'
          : `${Number(r.score).toFixed(2)}${r.band ? ` · ${r.band}` : ''}` },
        { label: 'Notice',
          value: r.notice_period_days == null ? '—' : `${r.notice_period_days} days` },
        { label: 'Location', value: r.current_location || '—' },
        { label: 'Screened', value: day(r.screened_on) },
      ]} />
      {r.comments && (
        <p className="text-[12px] text-[var(--text-muted)]">{r.comments}</p>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Phone}
        title="Telephonic screening"
        subtitle="The brief call before the panel — so three people's time is only booked once somebody has spoken to the candidate"
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setAdding({})}>
            <Plus size={14} /> Record a call
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {!loading && !error && queue.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <h2 className="text-[12px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              To call ({queue.length})
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              Shortlisted on an internal vacancy, not yet cleared by a call.
            </p>
          </div>
          <ul className="mt-3 flex flex-wrap gap-2">
            {queue.map((c) => (
              <li key={c.uk}>
                <button
                  type="button"
                  disabled={!canWrite}
                  onClick={() => setAdding({ uk: c.uk, candidate_name: c.candidate_name })}
                  className="flex items-center gap-2 rounded-lg border border-[var(--border)]
                    px-3 py-2 text-left text-[12.5px] text-[var(--text-main)]
                    enabled:hover:border-[var(--accent)] disabled:opacity-60
                    disabled:cursor-not-allowed"
                >
                  <UserRound size={13} className="text-[var(--text-muted)]" />
                  <span className="font-semibold">{c.candidate_name || c.uk}</span>
                  <span className="text-[11px] text-[var(--text-muted)]">
                    {c.designation_name || c.request_no}
                  </span>
                  {c.attempts > 0 && (
                    <Chip tone="warn">
                      {c.attempts} attempt{c.attempts === 1 ? '' : 's'}
                    </Chip>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <label htmlFor="tel-outcome" className="text-[11px] font-bold uppercase
          tracking-widest text-[var(--text-muted)]">Outcome</label>
        <select id="tel-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}
          className="h-9 px-3 rounded-lg border border-[var(--border)]
            bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
          <option value="">All</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Only a <b>Passed</b> call clears a candidate for a panel interview. Skipping the
          stage needs an approved exception.
        </p>
      </div>

      {loading && <HrmsLoading label="Loading telephonic screenings…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.tel_no}
          empty={<HrmsEmpty
            icon={Phone}
            title="No telephonic screenings recorded"
            hint="On internal vacancies the panel interview cannot be scheduled until a candidate has passed a call."
          />}
        />
      )}

      {adding && (
        <RecordModal
          scope={scope}
          preset={adding}
          onClose={() => setAdding(null)}
          onDone={() => { setAdding(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

const RecordModal = ({ scope, preset, onClose, onDone, showSuccess, showError }) => {
  const [form, setForm] = useState({
    uk: preset?.uk || '',
    screened_on: new Date().toISOString().slice(0, 10),
    duration_minutes: '', notice_period_days: '', expected_ctc: '',
    current_location: '', availability: '',
    communication: '', role_understanding: '', motivation: '', suitability: '',
    outcome: 'Passed', comments: '',
  });
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async () => {
    if (!form.uk.trim()) {
      showError('A candidate is required.');
      return;
    }
    if (form.outcome === 'Rejected' && !form.comments.trim()) {
      showError('Record why the call did not pass — a rejection with no note cannot be '
        + 'explained to the candidate or reviewed later.');
      return;
    }
    // Blanks are sent as null, not as empty strings: "not rated" and "rated zero" are
    // different answers, and the server rejects a 0 rating on a 1-5 scale.
    const payload = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]),
    );
    setBusy(true);
    try {
      const { data } = await createTelephonicScreening(payload, scope);
      showSuccess(data.outcome === 'Passed'
        ? `${data.tel_no} recorded — ${form.uk} is cleared for a panel interview`
        : `${data.tel_no} recorded — this does not clear ${form.uk} for an interview`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the screening.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Record a telephonic screening" labelledBy="tel-add-title"
      subtitle={preset?.candidate_name
        ? `A brief call with ${preset.candidate_name}`
        : 'A brief call before the panel — can they communicate, do they understand the role, do they want it'}
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
          <label className={LABEL} htmlFor="tel-uk">Candidate ID *</label>
          <input id="tel-uk" value={form.uk} onChange={set('uk')} className={FIELD}
            placeholder="CAN-001" readOnly={Boolean(preset?.uk)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="tel-date">Screened on</label>
          <input id="tel-date" type="date" value={form.screened_on}
            onChange={set('screened_on')} className={FIELD} />
        </div>
      </div>

      <div>
        <p className={LABEL}>What the candidate said</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="tel-notice">Notice period (days)</label>
            <input id="tel-notice" type="number" min="0" value={form.notice_period_days}
              onChange={set('notice_period_days')} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="tel-ctc">Expected CTC</label>
            <input id="tel-ctc" type="number" min="0" step="0.01" value={form.expected_ctc}
              onChange={set('expected_ctc')} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="tel-loc">Current location</label>
            <input id="tel-loc" value={form.current_location}
              onChange={set('current_location')} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="tel-avail">Availability</label>
            <input id="tel-avail" value={form.availability} onChange={set('availability')}
              className={FIELD} placeholder="Can start from 1 Oct" />
          </div>
        </div>
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          The expectation is recorded, not checked against the approved band — that
          comparison happens at the offer, where exceeding the band has an approval path.
        </p>
      </div>

      <div>
        <p className={LABEL}>How the call went (1–5, leave blank if not assessed)</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {CRITERIA.map(([key, label]) => (
            <div key={key}>
              <label className={LABEL} htmlFor={`tel-${key}`}>{label}</label>
              <input id={`tel-${key}`} type="number" min="1" max="5" step="0.5"
                value={form[key]} onChange={set(key)} className={FIELD} />
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="tel-outcome-field">Outcome *</label>
          <select id="tel-outcome-field" value={form.outcome} onChange={set('outcome')}
            className={FIELD}>
            {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="tel-duration">Call length (minutes)</label>
          <input id="tel-duration" type="number" min="1" max="180"
            value={form.duration_minutes} onChange={set('duration_minutes')}
            className={FIELD} />
        </div>
      </div>
      <p className="-mt-1 text-[11px] text-[var(--text-muted)]">
        {form.outcome === 'Passed'
          ? 'A passed call clears this candidate for a panel interview.'
          : form.outcome === 'No Answer'
            ? 'A recorded attempt, not a verdict — the candidate does not move, and they '
              + 'stay on the list to call.'
            : 'This does not clear the candidate for an interview. They can be revived '
              + 'later if the decision changes.'}
      </p>

      <div>
        <label className={LABEL} htmlFor="tel-comments">
          Comments {form.outcome === 'Rejected' ? '*' : ''}
        </label>
        <textarea id="tel-comments" rows={3} value={form.comments}
          onChange={set('comments')} className={TEXTAREA} />
      </div>
    </Modal>
  );
};

export default TelephonicBoard;
