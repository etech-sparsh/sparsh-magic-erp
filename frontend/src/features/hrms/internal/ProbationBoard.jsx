import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, FileCheck2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getProbations, getProbationsDue, reviewProbation, hrReviewProbation, confirmProbation,
  closePersonnelFile,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList, SignatureField,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — probation reviews.
 *
 * Probation is an EMPLOYEE event, not a recruitment stage: the candidate pipeline ends at
 * joining. That is why this screen lives in the sidebar with the other governance surfaces
 * rather than in the hiring tab strip.
 *
 * OVERDUE and DUE SOON are shown as two separate groups because they are two different
 * conversations — a missed commitment and a diary entry. One date-sorted list leaves the
 * reader to work out which is which, which is exactly the work a screen should do for them.
 */

const OUTCOMES = ['Confirmed', 'Extended', 'Terminated'];
const RECOMMENDATIONS = ['Confirm', 'Extend', 'Separate'];
// Mirrors PROBATION_REVIEW_CRITERIA in app/models/hrms.py exactly -- same five criteria,
// same order, so the form, the stored record and the letter all read the same list.
const PROBATION_REVIEW_CRITERIA = [
  ['performance', 'Performance against the role'],
  ['conduct', 'Conduct and professionalism'],
  ['attendance', 'Attendance and punctuality'],
  ['competence', 'Competence and skill'],
  ['suitability', 'Overall suitability for the role'],
];

/** The stage a Pending review is actually at, within §7.5 Stage 12's three-step chain:
 *  manager recommends -> HR endorses -> the authorised decision. The board reads this
 *  off the two sub-records rather than a status field, because the server does not keep
 *  one -- `review` and `hr_review` presence IS the state. */
const chainStage = (r) => {
  if (!r.review?.recommendation) return 'manager';
  if (r.hr_review?.decision !== 'Endorsed') return 'hr';
  return 'confirm';
};

/** Which single action a Pending review currently offers, per `chainStage`. Manager
 *  review and HR endorsement both sit behind PROBATION_REVIEW -- the same capability
 *  covers both steps on the backend -- while the final decision needs PROBATION_CONFIRM,
 *  which is why the two checks stay separate here rather than collapsing into one. */
const PendingAction = ({ r, canReview, canDecide, onReview, onHrReview, onConfirm }) => {
  const stage = chainStage(r);
  if (stage === 'manager') {
    return canReview
      ? <Btn tone="ghost" onClick={onReview}>Manager review</Btn>
      : null;
  }
  if (stage === 'hr') {
    return canReview
      ? <Btn tone="ghost" onClick={onHrReview}>HR review</Btn>
      : null;
  }
  return canDecide
    ? <Btn tone="ghost" onClick={onConfirm}>Confirm</Btn>
    : null;
};

const ProbationBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [due, setDue] = useState(null);
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reviewing, setReviewing] = useState(null);
  const [hrReviewing, setHrReviewing] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [closing, setClosing] = useState(null);

  const canReview = can(CAP.PROBATION_REVIEW);
  const canDecide = can(CAP.PROBATION_CONFIRM);
  const canCloseFile = can(CAP.PERSONNEL_FILE_CLOSE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [dueRes, allRes] = await Promise.all([
        getProbationsDue({ ...scope, within_days: 30 }),
        getProbations({ ...scope, limit: 200 }),
      ]);
      setDue(dueRes.data);
      setAll(allRes.data?.probation_reviews || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load probation reviews.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.employee_code} · {r.prb_no}
          </span>
        </>
      ) },
    { key: 'period', label: 'Period',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{day(r.started_on)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.duration_months} month{r.duration_months === 1 ? '' : 's'}
            {r.extension_count ? ` · extended ${r.extension_count}×` : ''}
          </span>
        </>
      ) },
    { key: 'ends', label: 'Ends',
      render: (r) => <span className="text-[var(--text-main)]">{day(r.ends_on)}</span> },
    { key: 'rating', label: 'Rating', align: 'right',
      render: (r) => (
        <span className="text-[var(--text-muted)]">{r.rating ?? '—'}</span>
      ) },
    { key: 'outcome', label: 'Outcome', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
          {r.outcome === 'Pending' && (
            <PendingAction r={r} canReview={canReview} canDecide={canDecide}
              onReview={() => setReviewing(r)} onHrReview={() => setHrReviewing(r)}
              onConfirm={() => setConfirming(r)} />
          )}
          {r.outcome === 'Confirmed' && canCloseFile && (
            <Btn tone="ghost" onClick={() => setClosing(r)}>
              <FileCheck2 size={13} /> Close file
            </Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.employee_code} · {r.prb_no}
          </p>
        </div>
        <Chip tone={toneFor(r.outcome)}>{r.outcome}</Chip>
      </div>
      <Facts items={[
        { label: 'Started', value: day(r.started_on) },
        { label: 'Ends', value: day(r.ends_on) },
        { label: 'Rating', value: r.rating ?? '—' },
      ]} />
      <div className="flex gap-2">
        {r.outcome === 'Pending' && (
          <PendingAction r={r} canReview={canReview} canDecide={canDecide}
            onReview={() => setReviewing(r)} onHrReview={() => setHrReviewing(r)}
            onConfirm={() => setConfirming(r)} />
        )}
        {r.outcome === 'Confirmed' && canCloseFile && (
          <Btn tone="ghost" onClick={() => setClosing(r)}>Close file</Btn>
        )}
      </div>
    </div>
  );

  const Group = ({ title, hint, rows, tone }) => (
    rows?.length ? (
      <section className="space-y-2.5">
        <div>
          <h2 className="text-[13.5px] font-bold text-[var(--text-main)] flex items-center gap-2">
            {title} <Chip tone={tone}>{rows.length}</Chip>
          </h2>
          {hint && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
        </div>
        <RecordList rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.prb_no} />
      </section>
    ) : null
  );

  // Split by outcome rather than lumped into one "Decided" pile: the onboarding module
  // structure names Confirmed, Extended and Separation as distinct things to look at, and
  // they mean entirely different things to whoever is reading the board.
  const confirmed = all.filter((r) => r.outcome === 'Confirmed');
  const extended = all.filter((r) => r.outcome === 'Extended');
  const separated = all.filter((r) => r.outcome === 'Terminated');
  const decided = all.filter((r) => r.outcome !== 'Pending');
  // `due` only ever returns Pending rows that are already overdue or within the 30-day
  // horizon — a Pending review whose end date is further out than that (the normal case for
  // someone who just joined) matched neither group and, since it is not Decided either,
  // vanished from the screen entirely despite being a real, live probation. This is that
  // remainder: still Pending, just not due yet.
  const overdueNos = new Set((due?.overdue || []).map((r) => r.prb_no));
  const dueSoonNos = new Set((due?.due_soon || []).map((r) => r.prb_no));
  const notYetDue = all.filter((r) => r.outcome === 'Pending'
    && !overdueNos.has(r.prb_no) && !dueSoonNos.has(r.prb_no));

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={CalendarClock}
        title="Probation"
        subtitle="Manager review, HR endorsement and the confirmation decision. Opened automatically when somebody joins."
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading probation reviews…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <Group
            title="Overdue" tone="bad" rows={due?.overdue}
            hint="Past the probation end date with no decision recorded."
          />
          <Group
            title="Due soon" tone="warn" rows={due?.due_soon}
            hint="Falling due in the next 30 days."
          />
          <Group
            title="On probation" tone="neutral" rows={notYetDue}
            hint="Review not due for more than 30 days yet."
          />
          <Group
            title="Confirmed" tone="good" rows={confirmed}
            hint="Probation completed and confirmed through the approval process."
          />
          <Group
            title="Extended" tone="warn" rows={extended}
            hint="More time granted. These return above as their new end date nears."
          />
          <Group
            title="Separation" tone="bad" rows={separated}
            hint="Probation ended without confirmation."
          />

          {!due?.overdue?.length && !due?.due_soon?.length && !notYetDue.length && !decided.length && (
            <HrmsEmpty
              icon={CalendarClock}
              title="No probation reviews yet"
              hint="One opens automatically when a joiner is issued an Employee ID."
            />
          )}
        </>
      )}

      {reviewing && (
        <ManagerReviewModal
          row={reviewing} scope={scope}
          onClose={() => setReviewing(null)}
          onDone={() => { setReviewing(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {hrReviewing && (
        <HrReviewModal
          row={hrReviewing} scope={scope}
          onClose={() => setHrReviewing(null)}
          onDone={() => { setHrReviewing(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {confirming && (
        <ConfirmModal
          row={confirming} scope={scope}
          onClose={() => setConfirming(null)}
          onDone={() => { setConfirming(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}

      {closing && (
        <CloseFileModal
          row={closing} scope={scope}
          onClose={() => setClosing(null)}
          onDone={() => { setClosing(null); load(); }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** The reporting manager's scored recommendation (§7.5 Stage 12) -- step one of three.
 *  A RECOMMENDATION, not a decision: HR reviews it next, and only an endorsed one can be
 *  confirmed. Re-submittable while still Pending, so a wrong score or an HR return is
 *  corrected here rather than needing a second review opened. */
const ManagerReviewModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [scores, setScores] = useState(
    Object.fromEntries(PROBATION_REVIEW_CRITERIA.map(([key]) => [key, ''])));
  const [recommendation, setRecommendation] = useState('Confirm');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [busy, setBusy] = useState(false);

  const setScore = (key, value) => setScores((s) => ({ ...s, [key]: value }));

  const submit = async () => {
    if (!signature.trim()) {
      showError('Type your name to sign this review. It decides somebody’s employment.');
      return;
    }
    for (const [key, label] of PROBATION_REVIEW_CRITERIA) {
      const v = Number(scores[key]);
      if (!scores[key] || Number.isNaN(v) || v < 1 || v > 5) {
        showError(`Score "${label}" from 1 to 5.`);
        return;
      }
    }
    if (recommendation !== 'Confirm' && !remarks.trim()) {
      showError(`Say why you are recommending they be ${recommendation.toLowerCase()}d.`);
      return;
    }
    setBusy(true);
    try {
      await reviewProbation(row.prb_no, {
        ...Object.fromEntries(
          PROBATION_REVIEW_CRITERIA.map(([key]) => [key, Number(scores[key])])),
        recommendation,
        remarks: remarks.trim(),
        signature: signature.trim(),
      }, scope);
      showSuccess(`${row.prb_no} — recommendation recorded, now waiting on HR`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the review.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Manager review — ${row.employee_name || row.employee_code}`}
      labelledBy="prb-review-title"
      subtitle={`${row.prb_no} · ends ${day(row.ends_on)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Working…' : 'Submit recommendation'}
          </Btn>
        </>
      )}
    >
      <p className="text-[12.5px] text-[var(--text-muted)]">
        Score each of the five criteria 1–5, then recommend Confirm, Extend or Separate.
        HR reviews this next; the authorised decision comes after that.
      </p>
      {PROBATION_REVIEW_CRITERIA.map(([key, label]) => (
        <div key={key}>
          <label className={LABEL} htmlFor={`prb-score-${key}`}>{label} *</label>
          <input id={`prb-score-${key}`} type="number" min="1" max="5" step="0.1"
            value={scores[key]} className={FIELD}
            onChange={(e) => setScore(key, e.target.value)} />
        </div>
      ))}
      <div>
        <label className={LABEL} htmlFor="prb-recommend">Recommendation *</label>
        <select id="prb-recommend" value={recommendation} className={FIELD}
          onChange={(e) => setRecommendation(e.target.value)}>
          {RECOMMENDATIONS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="prb-review-remarks">
          Remarks {recommendation === 'Confirm' ? '' : '*'}
        </label>
        <textarea id="prb-review-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
      <SignatureField id="prb-review-sign" value={signature} onChange={setSignature}
        hint="This recommendation decides somebody's employment." />
    </Modal>
  );
};

/** HR's step between the manager's recommendation and the authorised decision (§7.5 Stage
 *  12) -- step two of three. Endorsing lets the decision proceed; returning sends it back
 *  to the manager with a reason, which is why the recommendation itself is shown here
 *  read-only rather than re-entered. */
const HrReviewModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [decision, setDecision] = useState('Endorsed');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [busy, setBusy] = useState(false);
  const rec = row.review || {};

  const submit = async () => {
    if (!signature.trim()) {
      showError('Type your name to sign this review.');
      return;
    }
    if (decision === 'Returned' && !remarks.trim()) {
      showError('Say what needs to change. A review returned with no reason cannot be acted on.');
      return;
    }
    setBusy(true);
    try {
      await hrReviewProbation(row.prb_no, {
        decision, remarks: remarks.trim(), signature: signature.trim(),
      }, scope);
      showSuccess(decision === 'Endorsed'
        ? `${row.prb_no} endorsed — ready for the authorised decision`
        : `${row.prb_no} sent back to the reporting manager`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the HR review.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`HR review — ${row.employee_name || row.employee_code}`}
      labelledBy="prb-hr-review-title"
      subtitle={`${row.prb_no} · ends ${day(row.ends_on)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Working…' : 'Record HR review'}
          </Btn>
        </>
      )}
    >
      <div className="rounded-lg border border-[var(--border)] p-3 space-y-1.5">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          The manager's recommendation
        </p>
        <p className="text-[13px] text-[var(--text-main)]">
          <strong>{rec.recommendation}</strong> — average {rec.average ?? '—'} / 5,
          signed by {rec.by_name || '—'}
        </p>
        {rec.remarks && (
          <p className="text-[12px] text-[var(--text-muted)]">"{rec.remarks}"</p>
        )}
      </div>
      <div>
        <label className={LABEL} htmlFor="prb-hr-decision">Decision *</label>
        <select id="prb-hr-decision" value={decision} className={FIELD}
          onChange={(e) => setDecision(e.target.value)}>
          <option value="Endorsed">Endorsed — send forward for decision</option>
          <option value="Returned">Returned — send back to the manager</option>
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="prb-hr-remarks">
          Remarks {decision === 'Returned' ? '*' : ''}
        </label>
        <textarea id="prb-hr-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
      <SignatureField id="prb-hr-sign" value={signature} onChange={setSignature} />
    </Modal>
  );
};

/** Confirm, extend or end. An extension is more time, not a verdict — the review returns to
 *  Pending with a later date, which the copy says outright so nobody expects it to close. */
const ConfirmModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [outcome, setOutcome] = useState('Confirmed');
  const [rating, setRating] = useState(row.rating ?? '');
  const [extendedTo, setExtendedTo] = useState('');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!signature.trim()) {
      showError('Type your name to sign this decision.');
      return;
    }
    if (outcome === 'Extended' && !extendedTo) {
      showError('An extension needs a new end date.');
      return;
    }
    if (outcome !== 'Confirmed' && !remarks.trim()) {
      showError(`Record why the probation is being ${outcome.toLowerCase()}.`);
      return;
    }
    setBusy(true);
    try {
      await confirmProbation(row.prb_no, {
        outcome,
        rating: rating === '' ? null : Number(rating),
        extended_to: outcome === 'Extended' ? extendedTo : null,
        remarks: remarks.trim(),
        signature: signature.trim(),
      }, scope);
      showSuccess(outcome === 'Extended'
        ? `${row.prb_no} extended to ${extendedTo} — it returns to the due list`
        : `${row.prb_no} ${outcome.toLowerCase()}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Probation review — ${row.employee_name || row.employee_code}`}
      labelledBy="prb-confirm-title"
      subtitle={`${row.prb_no} · ends ${day(row.ends_on)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Working…' : 'Record decision'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="prb-outcome">Outcome *</label>
        <select id="prb-outcome" value={outcome} className={FIELD}
          onChange={(e) => setOutcome(e.target.value)}>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {outcome === 'Extended' && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            An extension is more time, not a verdict — the review reopens with the new date
            and appears in the due list again.
          </p>
        )}
        {outcome === 'Confirmed' && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Confirming also closes the requisition as Hired. There is no client handover on
            this track.
          </p>
        )}
      </div>

      {outcome === 'Extended' && (
        <div>
          <label className={LABEL} htmlFor="prb-extended">New end date *</label>
          <input id="prb-extended" type="date" value={extendedTo} className={FIELD}
            onChange={(e) => setExtendedTo(e.target.value)} />
        </div>
      )}

      <div>
        <label className={LABEL} htmlFor="prb-rating">Rating (1–5, optional)</label>
        <input id="prb-rating" type="number" min="1" max="5" step="0.1" value={rating}
          className={FIELD} onChange={(e) => setRating(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          The same 1–5 scale as the position scorecard.
        </p>
      </div>

      <div>
        <label className={LABEL} htmlFor="prb-remarks">
          Remarks {outcome === 'Confirmed' ? '' : '*'}
        </label>
        <textarea id="prb-remarks" rows={3} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>

      <SignatureField id="prb-sign" value={signature} onChange={setSignature}
        hint="This decision ends or extends somebody's employment." />
    </Modal>
  );
};

/** Personnel-file closure. Only offered once probation is confirmed, which the server also
 *  enforces — the file is closed when the confirmation is on record, not before. */
const CloseFileModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!note.trim()) {
      showError('Record what was checked. An empty closure note closes nothing.');
      return;
    }
    setBusy(true);
    try {
      await closePersonnelFile(
        { employee_code: row.employee_code, closure_note: note.trim() }, scope);
      showSuccess(`Personnel file closed for ${row.employee_code}`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not close the personnel file.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Close the personnel file" labelledBy="prb-close-title"
      subtitle={`${row.employee_name || row.employee_code} · ${row.employee_code}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Close file'}
          </Btn>
        </>
      )}
    >
      <p className="text-[12.5px] text-[var(--text-muted)]">
        The file is the offer, joining documents, verification reports and the probation
        confirmation. What is recorded here is that somebody checked the set is complete.
      </p>
      <div>
        <label className={LABEL} htmlFor="prb-note">Closure note *</label>
        <textarea id="prb-note" rows={4} value={note} className={TEXTAREA}
          placeholder="Offer, joining documents, BGV and confirmation all filed."
          onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ProbationBoard;
