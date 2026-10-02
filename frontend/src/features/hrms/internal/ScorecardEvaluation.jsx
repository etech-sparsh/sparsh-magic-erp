import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Target, Info, PenLine } from 'lucide-react';
import { CAP } from '../access';
import { useHrms } from '../HrmsContext';
import { useNotification } from '../../../context/NotificationContext';
import { getScorecards, evaluateAgainstScorecard } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import { Btn, Chip, SignatureField } from './internalKit.jsx';

/**
 * HRMS ▸ internal track ▸ score a candidate against the POSITION scorecard (SOP §5).
 *
 * The client track scores every candidate on the same four fixed competencies, because a
 * client requisition has no scorecard of its own. An internal one does: HR wrote the
 * criteria and their weights before sourcing began, and had them approved. Scoring an
 * internal candidate on anything else would make that approval decorative.
 *
 * So this screen renders the criteria that were actually approved for THIS position —
 * their labels, their weights and their own ceilings — and nothing else.
 *
 * -- On the total shown here ---------------------------------------------------------------
 * The weighted score is computed twice: here, so the panel can show it moving as scores are
 * entered, and again on the server, which is the one that gets stored. The mirror is a
 * convenience and is never sent — `compute_weighted` in hrms_scorecard_service.py is the
 * only definition that counts. Both normalise each criterion to the 1-5 scale before
 * weighting, so a criterion marked out of 10 does not quietly count double.
 *
 * -- Why the band is NOT previewed ----------------------------------------------------------
 * The number is arithmetic and safe to mirror. The BAND is not: its floors are per-company
 * configuration (CONFIG_SCORE_BANDS), and a company may switch the middle band off entirely
 * — the SOP signed four bands and the implementation brief describes three, so which reading
 * applies is that company's call. Guessing here would mean the panel could say "Moderate"
 * while the record said "Hold", and a screen that disagrees with the thing it just wrote is
 * worse than a screen that waits.
 *
 * So the total updates live and the band arrives with the saved record. Either way a band is
 * advice to the person reading it, never an instruction to the pipeline: a low score rejects
 * nobody and moves no one. The panel says so in as many words, because a number in a box
 * invites being treated as a verdict.
 */

const SCORE_MIN = 1;

/** Mirror of `compute_weighted`. Preview only — the server recomputes and stores. */
const previewScore = (criteria, scores) => {
  let accumulated = 0;
  let totalWeight = 0;
  for (const c of criteria) {
    const raw = scores[c.label];
    if (raw === '' || raw == null) return null;      // partial totals flatter; show none
    const value = Number(raw);
    if (Number.isNaN(value)) return null;
    const ceiling = Number(c.max_score) || 5;
    const weight = Number(c.weight) || 1;
    accumulated += (value / ceiling) * 5 * weight;
    totalWeight += weight;
  }
  return totalWeight ? Math.round((accumulated / totalWeight) * 100) / 100 : null;
};

const CATEGORY_LABEL = {
  skill: 'Skill', experience: 'Experience', culture_fit: 'Culture fit',
};

const ScorecardEvaluation = ({ candidate, onSaved }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [scorecard, setScorecard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scores, setScores] = useState({});
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [saving, setSaving] = useState(false);

  const uk = candidate?.uk;
  const requestNo = candidate?.request_no;
  const existing = candidate?.scorecard_evaluation;
  const canWrite = can(CAP.SCORECARD_WRITE);

  const load = useCallback(async () => {
    if (!requestNo) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getScorecards({ ...scope, request_no: requestNo });
      const card = (data?.scorecards || [])[0] || null;
      setScorecard(card);
      // Pre-fill from the previous evaluation so a correction starts from what was scored
      // last time rather than from an empty form.
      const prior = {};
      for (const row of existing?.breakdown || []) prior[row.label] = String(row.score);
      setScores(prior);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the position scorecard.');
    } finally {
      setLoading(false);
    }
    // `scope` is a fresh object literal on every HrmsContext render, so depending on it
    // here would rebuild `load` every render and re-run the effect for ever. Keyed on
    // the primitives instead, exactly as every other HRMS screen is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestNo]);

  useEffect(() => { load(); }, [load]);

  const criteria = useMemo(() => scorecard?.criteria || [], [scorecard]);
  const preview = useMemo(() => previewScore(criteria, scores), [criteria, scores]);
  const complete = criteria.length > 0 && preview != null;

  const submit = async () => {
    setSaving(true);
    try {
      const numeric = {};
      for (const [k, v] of Object.entries(scores)) numeric[k] = Number(v);
      const { data } = await evaluateAgainstScorecard(
        uk, { scores: numeric, remarks: remarks.trim() || null, signature: signature.trim() },
        scope,
      );
      showSuccess(`Scored ${data?.weighted_score ?? ''} / 5 — recorded, not applied`);
      setSignature('');
      setRemarks('');
      if (onSaved) await onSaved();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not save that evaluation.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-[12px] text-[var(--text-muted)]">Loading the scorecard…</p>;
  }

  if (!requestNo) {
    return (
      <p className="text-[12px] text-[var(--text-muted)]">
        This candidate is not attached to a requisition, so there is no position scorecard
        to measure them against.
      </p>
    );
  }

  if (!scorecard) {
    return (
      <p className="text-[12px] text-[var(--text-muted)]">
        {requestNo} has no position scorecard yet. HR writes the criteria and their weights
        on the Scorecards screen, and the hiring manager approves them, before candidates
        are scored against the role.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-[var(--text-main)] flex items-center
                        gap-1.5">
            <Target size={14} className="text-[var(--text-muted)]" />
            {scorecard.title || scorecard.designation_name || scorecard.scr_no}
          </p>
          <p className="text-[11px] text-[var(--text-muted)] font-mono">
            {scorecard.scr_no} · {criteria.length} criteria
          </p>
        </div>
        <Chip tone={scorecard.status === 'Approved' ? 'good' : 'warn'}>
          {scorecard.status}
        </Chip>
      </div>

      {existing && (
        <div className="rounded-lg border border-[var(--border)] p-3">
          <p className="text-[11px] font-bold uppercase tracking-widest
                        text-[var(--text-muted)]">Last scored</p>
          <p className="mt-1 text-[13px] text-[var(--text-main)]">
            <strong>{existing.weighted_score} / 5</strong> · {existing.band}
            {existing.evaluated_by_name ? ` · ${existing.evaluated_by_name}` : ''}
            {existing.evaluated_at ? ` · ${day(existing.evaluated_at)}` : ''}
          </p>
          {existing.remarks && (
            <p className="mt-1 text-[12px] text-[var(--text-muted)]">{existing.remarks}</p>
          )}
        </div>
      )}

      {!canWrite ? (
        <p className="text-[12px] text-[var(--text-muted)]">
          You can see this evaluation but not change it.
        </p>
      ) : (
        <>
          <div className="space-y-2.5">
            {criteria.map((c) => {
              const ceiling = Number(c.max_score) || 5;
              const value = scores[c.label] ?? '';
              return (
                <div key={c.label}
                     className="rounded-lg border border-[var(--border)] p-3 space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3
                                  gap-y-1">
                    <label className="text-[12.5px] font-semibold text-[var(--text-main)]"
                           htmlFor={`crit-${c.label}`}>
                      {c.label}
                    </label>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      {CATEGORY_LABEL[c.category] || c.category} · weight {c.weight}
                      {ceiling !== 5 ? ` · out of ${ceiling}` : ''}
                    </span>
                  </div>
                  {/* The bar and how to measure it, as agreed on the approved scorecard --
                      scoring against criteria the panel cannot see is guesswork. */}
                  {c.expected_level && (
                    <p className="text-[11.5px] text-[var(--text-main)]">
                      Expected: {c.expected_level}
                    </p>
                  )}
                  {c.evaluation_criteria && (
                    <p className="text-[11px] text-[var(--text-muted)]">
                      {c.evaluation_criteria}
                    </p>
                  )}
                  <div className="flex items-center gap-3">
                    <input
                      id={`crit-${c.label}`} type="range"
                      min={SCORE_MIN} max={ceiling} step={1}
                      value={value === '' ? SCORE_MIN : value}
                      onChange={(e) => setScores(
                        (s) => ({ ...s, [c.label]: e.target.value }))}
                      className="flex-1 accent-[var(--accent-indigo)]"
                      aria-describedby={`crit-val-${c.label}`}
                    />
                    <span id={`crit-val-${c.label}`}
                          className={`w-14 text-right text-[13px] font-bold tabular-nums
                            ${value === '' ? 'text-[var(--text-muted)]'
                                           : 'text-[var(--text-main)]'}`}>
                      {value === '' ? `– / ${ceiling}` : `${value} / ${ceiling}`}
                    </span>
                  </div>
                  {value === '' && (
                    <p className="text-[11px] text-[var(--text-muted)]">
                      Not scored yet — drag to set, every criterion is required.
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="rounded-lg border border-[var(--border)] p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11px] font-bold uppercase tracking-widest
                               text-[var(--text-muted)]">Weighted score</span>
              {preview == null ? (
                <span className="text-[13px] text-[var(--text-muted)]">
                  Score every criterion to see the total
                </span>
              ) : (
                <span className="flex items-baseline gap-2">
                  <strong className="text-[20px] font-bold tabular-nums
                                     text-[var(--text-main)]">{preview}</strong>
                  <span className="text-[13px] text-[var(--text-muted)]">/ 5</span>
                </span>
              )}
            </div>
            <p className="mt-2 text-[11.5px] text-[var(--text-muted)] flex gap-1.5">
              <Info size={13} className="shrink-0 mt-px" />
              <span>
                The band — Strong, Consider, Hold or Reject — is set when this is saved,
                against your company&rsquo;s own floors in HRMS settings. It is a reading of
                the number for whoever sees it next, never an instruction: a low score
                rejects nobody and moves no one. The hiring decision stays with the people
                accountable for it.
              </span>
            </p>
          </div>

          <div>
            <label className={LABEL} htmlFor="sc-remarks">Remarks</label>
            <textarea id="sc-remarks" rows={2} className={TEXTAREA} value={remarks}
                      onChange={(e) => setRemarks(e.target.value)}
                      placeholder="What the number does not capture." />
          </div>

          <SignatureField
            id="sc-signature" value={signature} onChange={setSignature}
            hint="This evaluation is recorded against your name. It does not move the
                  candidate — their stage is changed on the pipeline, by a person."
          />

          <div className="flex justify-end">
            <Btn tone="primary" onClick={submit}
                 disabled={saving || !complete || !signature.trim()}>
              <PenLine size={13} />
              {saving ? 'Saving…' : existing ? 'Re-score' : 'Save evaluation'}
            </Btn>
          </div>
        </>
      )}
    </div>
  );
};

export default ScorecardEvaluation;
