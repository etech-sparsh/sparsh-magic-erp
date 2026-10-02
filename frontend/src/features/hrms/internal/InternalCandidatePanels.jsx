import React, { useCallback, useEffect, useState } from 'react';
import { Target, PhoneCall, ShieldCheck, ChevronDown } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { getReferenceChecks, getProbations } from '../../../services/hrmsApi';
import { day } from './internalKit';
import { Chip, Facts } from './internalKit.jsx';
import ScorecardEvaluation from './ScorecardEvaluation';

/**
 * HRMS ▸ the internal track's own sections of a candidate page (spec §30).
 *
 * Everything the internal SOP adds after the interview — how the candidate scored against
 * the approved position scorecard, what their referees said, and how probation went — in
 * the place a reader is already looking, rather than three screens away.
 *
 * Rendered ONLY for an internal-track candidate. The client track has no position
 * scorecard, no mandatory reference check and no probation, so on that track these
 * sections do not exist rather than sitting there permanently empty.
 *
 * Each panel is collapsible and starts closed except the scorecard, which is the one people
 * come here to fill in. Collapsed sections still say what they hold, so the reader can tell
 * "nothing recorded" from "not loaded".
 */

const Section = ({ icon: Icon, title, hint, count, defaultOpen = false, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
      <button
        type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="w-full flex items-center gap-2 px-3.5 py-3 text-left"
      >
        <Icon size={14} className="text-[var(--text-muted)] shrink-0" />
        <span className="text-[12.5px] font-bold text-[var(--text-main)]">{title}</span>
        {count != null && <Chip tone={count ? 'accent' : 'neutral'}>{count}</Chip>}
        <span className="ml-auto flex items-center gap-2">
          {hint && (
            <span className="hidden sm:inline text-[11px] text-[var(--text-muted)]">
              {hint}
            </span>
          )}
          <ChevronDown size={15}
            className={`text-[var(--text-muted)] transition-transform
              ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>
      {open && (
        <div className="px-3.5 pb-3.5 pt-1 border-t border-[var(--border)]">{children}</div>
      )}
    </div>
  );
};

const OUTCOME_TONE = {
  Positive: 'good', Negative: 'bad', 'Unable to Verify': 'warn',
  Confirmed: 'good', Terminated: 'bad', Extended: 'warn', Pending: 'neutral',
};

const InternalCandidatePanels = ({ candidate, onChanged }) => {
  const { scope, can } = useHrms();
  const [refs, setRefs] = useState(null);
  const [probations, setProbations] = useState(null);

  const uk = candidate?.uk;
  const canReadRefs = can(CAP.REFERENCE_READ);
  const canReadProbation = can(CAP.PROBATION_READ);

  const load = useCallback(async () => {
    if (!uk) return;
    // Each read is independent: a caller who may see references but not probation gets the
    // half they are entitled to rather than an empty page.
    if (canReadRefs) {
      try {
        const { data } = await getReferenceChecks({ ...scope, uk });
        setRefs(data?.reference_checks || []);
      } catch { setRefs([]); }
    }
    if (canReadProbation) {
      try {
        const { data } = await getProbations({ ...scope, uk });
        setProbations(data?.probation_reviews || []);
      } catch { setProbations([]); }
    }
    // `scope` is a fresh object literal on every HrmsContext render, so depending on it
    // here would rebuild `load` every render and re-run the effect for ever. Keyed on
    // the primitives instead, exactly as every other HRMS screen is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk, canReadRefs, canReadProbation]);

  useEffect(() => { load(); }, [load]);

  if (!uk) return null;

  return (
    <div className="space-y-2.5">
      <p className="text-[10.5px] font-bold uppercase tracking-widest
                    text-[var(--text-muted)]">
        Internal hiring
      </p>

      {can(CAP.SCORECARD_READ) && (
        <Section icon={Target} title="Scorecard evaluation" defaultOpen
                 hint={candidate.scorecard_score != null
                   ? `${candidate.scorecard_score} / 5` : 'not scored'}>
          <ScorecardEvaluation candidate={candidate} onSaved={onChanged} />
        </Section>
      )}

      {canReadRefs && (
        <Section icon={PhoneCall} title="Reference checks" count={refs?.length ?? null}
                 hint="mandatory before an internal offer">
          {refs === null && (
            <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>
          )}
          {refs?.length === 0 && (
            <p className="text-[12px] text-[var(--text-muted)]">
              None recorded. An internal offer cannot be sent until at least one reference
              is completed, or an approved exception waives it.
            </p>
          )}
          {refs?.map((r) => (
            <div key={r.ref_no}
                 className="py-2.5 border-b border-[var(--border)] last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[12.5px] font-semibold text-[var(--text-main)]">
                  {r.referee_name}
                </span>
                <Chip tone={OUTCOME_TONE[r.outcome] || 'neutral'}>
                  {r.outcome || 'Pending'}
                </Chip>
                <span className="font-mono text-[11px] text-[var(--text-muted)]">
                  {r.ref_no}
                </span>
              </div>
              <div className="mt-1.5">
                <Facts items={[
                  { label: 'Organisation', value: r.organisation },
                  { label: 'Designation', value: r.designation },
                  { label: 'Relationship', value: r.relationship },
                  { label: 'Mode', value: r.mode },
                  { label: 'Date', value: r.date ? day(r.date) : null },
                  { label: 'By', value: r.conducted_by_name },
                ]} />
              </div>
              {r.remarks && (
                <p className="mt-1.5 text-[12px] text-[var(--text-muted)]">{r.remarks}</p>
              )}
            </div>
          ))}
        </Section>
      )}

      {canReadProbation && (
        <Section icon={ShieldCheck} title="Probation" count={probations?.length ?? null}
                 hint="after joining">
          {probations === null && (
            <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>
          )}
          {probations?.length === 0 && (
            <p className="text-[12px] text-[var(--text-muted)]">
              No probation review yet. One opens automatically when the employee ID is
              issued at joining.
            </p>
          )}
          {probations?.map((p) => (
            <div key={p.prb_no}
                 className="py-2.5 border-b border-[var(--border)] last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={OUTCOME_TONE[p.outcome] || 'neutral'}>{p.outcome}</Chip>
                <span className="font-mono text-[11px] text-[var(--text-muted)]">
                  {p.prb_no}
                </span>
              </div>
              <div className="mt-1.5">
                <Facts items={[
                  { label: 'Started', value: p.started_on ? day(p.started_on) : null },
                  { label: 'Ends', value: p.ends_on ? day(p.ends_on) : null },
                  { label: 'Extended to',
                    value: p.extended_to ? day(p.extended_to) : null },
                  { label: 'Rating', value: p.rating != null ? `${p.rating} / 5` : null },
                  { label: 'Decided by', value: p.confirmed_by_name },
                  { label: 'Decided on',
                    value: p.confirmed_at ? day(p.confirmed_at) : null },
                ]} />
              </div>
              {p.remarks && (
                <p className="mt-1.5 text-[12px] text-[var(--text-muted)]">{p.remarks}</p>
              )}
            </div>
          ))}
        </Section>
      )}
    </div>
  );
};

export default InternalCandidatePanels;
