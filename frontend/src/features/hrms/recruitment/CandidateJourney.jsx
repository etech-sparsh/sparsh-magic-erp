import React, { useEffect, useState } from 'react';
import { X, Check, CircleDot } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getCandidateJourney } from '../../../services/hrmsApi';
import DocumentPanel from '../documents/DocumentPanel';
import InternalCandidatePanels from '../internal/InternalCandidatePanels';

/**
 * HRMS ▸ candidate journey.
 *
 * A 7-step rail plus a colour-coded timeline, both computed **server-side** from the audit
 * trail. The colours come from the API rather than being re-derived here, so every consumer
 * of a journey agrees on what an event means — the same reason capabilities come from
 * /hrms/health rather than being inferred from a role.
 *
 * This is the payoff for auditing every write since Phase 1.
 */

const KIND_TONE = {
  applied:    'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  success:    'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  reject:     'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  warning:    'bg-[var(--input-bg)] text-[var(--text-main)]',
  interview:  'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  offer:      'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  onboarding: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  assessment: 'bg-[var(--input-bg)] text-[var(--text-main)]',
  info:       'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const fmt = (value) => {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
};

export const CandidateJourneyView = ({ uk }) => {
  const { scope } = useHrms();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showDocs, setShowDocs] = useState(false);
  // Bumped after a write from one of the internal panels, so the rail, the timeline and
  // the score re-read together rather than drifting apart.
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    getCandidateJourney(uk, scope)
      .then(({ data: d }) => { if (alive) setData(d); })
      .catch((err) => {
        if (alive) setError(err?.response?.data?.detail || 'Could not load this journey.');
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk, reloads]);

  if (error) return <HrmsError message={error} />;
  if (!data) return <HrmsLoading label="Loading journey…" />;

  return (
    <div className="space-y-5">
      <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)]">
        <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Current stage
        </p>
        <p className="mt-0.5 text-[15px] font-bold text-[var(--text-main)]">
          {data.candidate.status}
        </p>
        {data.terminal && (
          <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
            This is a final stage — the pipeline ends here.
          </p>
        )}
      </div>

      {/* ── Phase 11-R, Item 5 ── the referral block. Renders only for a referred
          candidate, so an ordinary journey looks exactly as it did before this phase. */}
      {data.candidate.is_referral && (
        <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
          <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
            Referral
          </p>
          <div className="mt-1.5 space-y-0.5 text-[12.5px] text-[var(--text-main)]">
            <p>
              Referred by <b>{data.candidate.referred_by}</b>
              {data.candidate.referral_relation && (
                <span className="text-[var(--text-muted)]"> · {data.candidate.referral_relation}</span>
              )}
            </p>
            {data.candidate.referral_source && (
              <p className="text-[var(--text-muted)]">
                Source: {data.candidate.referral_source}
              </p>
            )}
            {data.candidate.referrer_name && (
              <p className="text-[var(--text-muted)]">
                Verified employee: {data.candidate.referrer_name}
                {data.candidate.referrer_employee_code
                  && ` (${data.candidate.referrer_employee_code})`}
              </p>
            )}
          </div>
        </div>
      )}


      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {data.rail.map((step, i) => (
          <React.Fragment key={step.label}>
            <div className="flex flex-col items-center gap-1 min-w-[64px]">
              <div className={`h-6 w-6 rounded-full grid place-items-center ${
                step.current ? 'bg-[var(--accent-indigo)] text-white ring-2 ring-[var(--accent-indigo)]'
                : step.reached ? 'bg-[var(--accent-indigo)] text-white'
                : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
                {step.current ? <CircleDot size={12} /> : step.reached ? <Check size={12} /> : i + 1}
              </div>
              <span className={`text-[10px] font-bold text-center leading-tight ${
                step.reached ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}`}>
                {step.label}
              </span>
            </div>
            {i < data.rail.length - 1 && (
              <div className={`h-px flex-1 min-w-[10px] ${
                step.reached ? 'bg-[var(--accent-indigo)]' : 'bg-[var(--border)]'}`} />
            )}
          </React.Fragment>
        ))}
      </div>

      <div>
        <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
          History
        </p>
        <ol className="space-y-2">
          {data.events.map((e, i) => (
            <li key={i} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className={`h-2.5 w-2.5 rounded-full mt-1.5 shrink-0 ${
                  (KIND_TONE[e.kind] || KIND_TONE.info).split(' ')[0]}`} />
                {i < data.events.length - 1 && (
                  <span className="w-px flex-1 bg-[var(--border)] my-1" />
                )}
              </div>
              <div className="pb-2 min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
                    KIND_TONE[e.kind] || KIND_TONE.info}`}>
                    {e.title}
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)]">{fmt(e.at)}</span>
                </div>
                {e.detail && (
                  <p className="mt-0.5 text-[12.5px] text-[var(--text-main)] break-words">{e.detail}</p>
                )}
                {e.actor && (
                  <p className="text-[11px] text-[var(--text-muted)]">by {e.actor}</p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>

      {/* ── Phase INT-15 (spec §30) ── the hiring facts: position scorecard, reference
          check and probation. */}
      <InternalCandidatePanels
        candidate={data.candidate}
        onChanged={() => setReloads((n) => n + 1)}
      />

      {/* ── Phase 11-R, Item 2 ── the SAME DocumentPanel the employee profile mounts.
          Collapsed behind a toggle so the journey stays a timeline first: documents are
          reference material here, not the thing the reader came for. */}
      <div>
        <button
          type="button"
          onClick={() => setShowDocs((v) => !v)}
          className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)]"
        >
          Documents {showDocs ? '▾' : '▸'}
        </button>
        {showDocs && (
          <div className="mt-3">
            <DocumentPanel
              ownerType="candidate"
              ownerId={data.candidate.uk}
              ownerName={data.candidate.name}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export const CandidateJourneyModal = ({ uk, name, onClose }) => (
  <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4">
    <div className="w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
      <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
        <div className="min-w-0">
          <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">{name}</h2>
          <p className="font-mono text-[11.5px] text-[var(--text-muted)]">{uk}</p>
        </div>
        <button type="button" onClick={onClose}
          className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
          <X size={17} />
        </button>
      </div>
      <div className="p-5 overflow-y-auto">
        <CandidateJourneyView uk={uk} />
      </div>
    </div>
  </div>
);

export default CandidateJourneyView;
