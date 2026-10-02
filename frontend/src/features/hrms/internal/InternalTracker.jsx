import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, Clock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getInternalTracker } from '../../../services/hrmsApi';
import { day, toneFor } from './internalKit';
import { Chip, Facts, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ the internal requisition tracker (Phase INT-7, Annexure C).
 *
 * One row per internal requisition, every stage rolled up: budget, scorecard, pipeline
 * counts, shortlist, offer, joining, probation, SLA health and exceptions. Everything is
 * computed server-side — this component fetches and lays out, nothing more.
 *
 * The row's job is to answer the two questions a tracker is opened with: WHERE has this
 * got to, and IS IT LATE. So the SLA cell leads with the breach (or the next thing owed),
 * and every other cell is a status, not a narrative.
 */

const SLA_FILTERS = [
  ['', 'All'],
  ['breached', 'Breached'],
  ['on_track', 'On track'],
  ['met', 'Met'],
  ['not_started', 'Not started'],
];

const slaTone = (status) => ({
  breached: 'bad', on_track: 'warn', met: 'good', not_started: 'neutral',
}[status] || 'neutral');

const SlaIcon = ({ status }) => {
  const Icon = { breached: AlertTriangle, on_track: Clock, met: CheckCircle2 }[status]
    || CircleDashed;
  return <Icon size={13} />;
};

/** "3 / 2 / 1" pipeline counts read left to right as the funnel narrows. */
const Funnel = ({ c }) => (
  <span className="tabular-nums text-[var(--text-main)]">
    {c.total}
    <span className="text-[var(--text-muted)]"> &rsaquo; </span>{c.shortlisted}
    <span className="text-[var(--text-muted)]"> &rsaquo; </span>{c.interviewed}
    <span className="text-[var(--text-muted)]"> &rsaquo; </span>{c.selected}
    <span className="text-[var(--text-muted)]"> &rsaquo; </span>{c.joined}
  </span>
);

const money = (v) => (v == null ? null
  : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));

const InternalTracker = () => {
  const { scope, companyId } = useHrms();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sla, setSla] = useState('');

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: payload } = await getInternalTracker({
        ...scope, sla: sla || undefined, limit: 200,
      });
      setData(payload);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the tracker.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, sla]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows || [];

  const columns = [
    { key: 'req', label: 'Requisition',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.designation_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.request_no} · {r.department_name || '—'} · {r.vacancy} seat
            {r.vacancy === 1 ? '' : 's'}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            HOD {r.raised_by_name || '—'} · HR {r.hr_owner_name || '—'}
          </span>
        </>
      ) },
    { key: 'stage', label: 'Stage',
      render: (r) => (
        <div className="flex flex-col items-start gap-1">
          <Chip tone={toneFor(r.approval_status)}>{r.approval_status}</Chip>
          <span className="text-[11px] text-[var(--text-muted)]">
            {r.closing_status}
          </span>
        </div>
      ) },
    { key: 'budget', label: 'Budget',
      render: (r) => (
        r.budget.approved ? (
          <>
            <Chip tone="good">Approved</Chip>
            <span className="block mt-1 text-[11px] text-[var(--text-muted)]">
              {day(r.budget.approved_at)}
              {r.budget.band_min != null
                && ` · ${money(r.budget.band_min)}–${money(r.budget.band_max)}`}
            </span>
          </>
        ) : <Chip tone="warn">Pending</Chip>
      ) },
    { key: 'scorecard', label: 'Scorecard',
      render: (r) => (
        r.scorecard.approved
          ? <Chip tone="good">Approved</Chip>
          : r.scorecard.status
            ? <Chip tone={toneFor(r.scorecard.status)}>{r.scorecard.status}</Chip>
            : <span className="text-[11px] text-[var(--text-muted)]">—</span>
      ) },
    { key: 'pipeline', label: 'CVs › short › int › sel › joined',
      render: (r) => (
        r.candidates.total
          ? <Funnel c={r.candidates} />
          : (
            <span className="text-[11px] text-[var(--text-muted)]">
              {r.sourcing.postings ? 'Posted, no CVs yet' : 'Not sourced'}
            </span>
          )
      ) },
    { key: 'decision', label: 'Shortlist · Offer',
      render: (r) => (
        <div className="flex flex-col items-start gap-1">
          {r.shortlist.status
            ? <Chip tone={toneFor(r.shortlist.status)}>{r.shortlist.status}</Chip>
            : <span className="text-[11px] text-[var(--text-muted)]">No committee yet</span>}
          {r.offer.status && (
            <span className="text-[11px] text-[var(--text-muted)]">
              Offer {r.offer.status}
              {r.offer.candidate_name && ` — ${r.offer.candidate_name}`}
            </span>
          )}
        </div>
      ) },
    { key: 'after', label: 'Joining · Probation',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)] text-[12px]">
            {r.joining_date ? day(r.joining_date) : '—'}
          </span>
          {r.probation.ends_on && (
            <span className="block text-[11px] text-[var(--text-muted)]">
              Probation {r.probation.outcome} · ends {day(r.probation.ends_on)}
            </span>
          )}
        </>
      ) },
    { key: 'sla', label: 'SLA', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1">
          <Chip tone={slaTone(r.sla.status)}>
            <SlaIcon status={r.sla.status} />
            {r.sla.status === 'breached'
              ? `${r.sla.days_over} wd over`
              : r.sla.status.replace('_', ' ')}
          </Chip>
          <span className="text-[10.5px] text-[var(--text-muted)] text-right max-w-[11rem]">
            {r.sla.status === 'breached'
              ? (r.sla.breached_labels || []).join('; ')
              : r.sla.next_label
                ? `Next: ${r.sla.next_label}${r.sla.next_due_on
                  ? ` by ${day(r.sla.next_due_on)}` : ''}`
                : '—'}
          </span>
          {r.exceptions.open > 0 && (
            <Chip tone="warn">{r.exceptions.open} exception(s) pending</Chip>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.designation_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.request_no} · {r.department_name || '—'}
          </p>
        </div>
        <Chip tone={slaTone(r.sla.status)}>
          <SlaIcon status={r.sla.status} /> {r.sla.status.replace('_', ' ')}
        </Chip>
      </div>
      <Facts items={[
        { label: 'Stage', value: r.approval_status },
        { label: 'Budget', value: r.budget.approved ? day(r.budget.approved_at) : 'Pending' },
        { label: 'Pipeline',
          value: `${r.candidates.total} CVs · ${r.candidates.selected} selected · `
            + `${r.candidates.joined} joined` },
        { label: 'Offer', value: r.offer.status || '—' },
        { label: 'Joining', value: r.joining_date ? day(r.joining_date) : '—' },
        { label: 'Probation ends',
          value: r.probation.ends_on ? day(r.probation.ends_on) : '—' },
      ]} />
      {r.sla.status === 'breached' && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Late: {(r.sla.breached_labels || []).join('; ')}
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-bold uppercase tracking-widest
          text-[var(--text-muted)]">SLA</span>
        {SLA_FILTERS.map(([value, label]) => (
          <button
            key={value || 'all'}
            type="button"
            onClick={() => setSla(value)}
            className={`h-8 px-3 rounded-lg border text-[12.5px] ${sla === value
              ? 'border-[var(--accent)] text-[var(--text-main)] font-semibold'
              : 'border-[var(--border)] text-[var(--text-muted)]'}`}
          >
            {label}
          </button>
        ))}
        {data?.sla_basis && (
          <p className="basis-full text-[11px] text-[var(--text-muted)]">
            {data.sla_basis}
          </p>
        )}
      </div>

      {loading && <HrmsLoading label="Loading the tracker…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.request_no}
          empty={<HrmsEmpty
            icon={CircleDashed}
            title={sla ? 'Nothing in that SLA state' : 'No internal requisitions yet'}
            hint={sla ? 'Try another filter.'
              : 'The tracker fills in as internal vacancies are raised.'}
          />}
        />
      )}
    </div>
  );
};

export default InternalTracker;
