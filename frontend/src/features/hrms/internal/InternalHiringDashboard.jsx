import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Wallet, Target, CalendarDays, PhoneCall, FileSignature, ShieldCheck,
  ClipboardCheck, AlertTriangle, ArrowRight, Briefcase, Users2, Clock, UserCircle,
  Check, ChevronDown, GitBranch, ChevronRight, Plus,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getInternalTracker } from '../../../services/hrmsApi';
import RequisitionFormModal from '../recruitment/RequisitionFormModal';
import { CARD, day } from './internalKit';
import { Chip, Btn, Tile, FlowAccordion } from './internalKit.jsx';

/**
 * The Internal Recruitment SOP's own step sequence (Annexure B / §3-§7), one row per
 * screen this track actually uses to clear that step. Several SOP steps share a screen
 * (e.g. Probation Monitoring + Review sit on the same board, Joining + Day-1 Induction
 * are both driven from the Onboarding checklist) — this lists the SCREEN, not a
 * one-to-one restating of every SOP line, so a step here always lands somewhere real
 * rather than on a page that doesn't exist.
 *
 * Several of these screens live in the sidebar (Pre-boarding, Probation) rather than this
 * workspace's own tab strip (see HrmsWorkspaceBar.jsx and Sidebar.jsx's hrmsSubmodules) —
 * that split is deliberate (day-to-day hiring screens vs. broader lifecycle governance),
 * so this tracker exists precisely to give the SOP's own order ONE place to read
 * end-to-end regardless of which nav surface a step's screen actually sits in.
 */
const SOP_STAGES = [
  { n: '1', label: 'Requisition', to: '/hrms/internal-requisitions' },
  // Its own step, not folded into Step 1 — SOP §Step 2 makes this a mandatory gate in its
  // own right ("no internal role may be sourced without written headcount and budget
  // approval"), cleared by Management/Finance, not the HOD who raises the requisition.
  { n: '2', label: 'Headcount & Budget Approval', to: '/hrms/internal-requisitions' },
  { n: '3', label: 'Scorecard / JD', to: '/hrms/scorecards' },
  { n: '4–5', label: 'Sourcing', to: '/hrms/postings' },
  { n: '6', label: 'CV Screening', to: '/hrms/screening' },
  { n: '7', label: 'Phone Screen', to: '/hrms/telephonic-screening' },
  { n: '8', label: 'Assessment', to: '/hrms/assessments' },
  { n: '9', label: 'Panel Interview', to: '/hrms/interviews' },
  { n: '10', label: 'Shortlist Committee', to: '/hrms/shortlist-reviews' },
  { n: '11', label: 'Management Interview', to: '/hrms/interviews' },
  { n: '12', label: 'Reference Check', to: '/hrms/reference-checks' },
  { n: '13', label: 'Negotiation', to: '/hrms/negotiations' },
  // Not a numbered SOP step — a gate. The server refuses to create an offer until every
  // check has cleared and HR has signed the file off, so it belongs in the strip ahead of
  // Offer even though the SOP does not give it a number of its own.
  { n: '⚑', label: 'Verification', to: '/hrms/background-checks',
    title: 'Gate — checks must clear before an offer can be raised' },
  { n: '14–15', label: 'Offer', to: '/hrms/offers' },
  { n: '16', label: 'Pre-boarding', to: '/hrms/preboarding' },
  { n: '17', label: 'Joining & Induction', to: '/hrms/onboarding' },
  { n: '18–19', label: 'Probation', to: '/hrms/probation' },
  { n: '20–21', label: 'Closure', to: '/hrms/probation' },
];

/**
 * A connected stepper rather than a row of plain pills — the visual is doing the same job
 * "1 → 2 → 3" numbering did before, just reading as a single continuous process instead of
 * a list of unrelated buttons. Purely navigational: the number is the SOP's own step, the
 * dot is not a live progress indicator (a requisition does not move through this rail the
 * way it moves through the Kanban board below), so no state is computed here.
 */
const StageTracker = () => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <section aria-labelledby="stages-heading" className={`${CARD} !p-4`}>
      <h2 id="stages-heading"
          className="text-[10.5px] font-bold uppercase tracking-widest
                     text-[var(--text-muted)] mb-3">
        Recruitment stages — Internal Recruitment SOP
      </h2>
      <div className="flex items-start overflow-x-auto no-scrollbar pb-1 -mx-1 px-1">
        {SOP_STAGES.map((s, i) => {
          const isHere = pathname === s.to || pathname.startsWith(`${s.to}/`);
          return (
            <React.Fragment key={s.label}>
              <button
                type="button"
                onClick={() => navigate(s.to)}
                title={s.title || `Step ${s.n}`}
                className="group shrink-0 flex flex-col items-center gap-1.5 w-[92px] text-center"
              >
                <span className={`h-8 w-8 rounded-full grid place-items-center text-[11px]
                  font-bold border-2 transition-colors ${
                  isHere
                    ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)] text-white'
                    : 'border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-muted)] '
                      + 'group-hover:border-[var(--accent-indigo)] group-hover:text-[var(--accent-indigo)]'
                }`}>
                  {s.n}
                </span>
                <span className={`text-[10.5px] font-bold leading-tight transition-colors ${
                  isHere ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] group-hover:text-[var(--text-main)]'
                }`}>
                  {s.label}
                </span>
              </button>
              {i < SOP_STAGES.length - 1 && (
                <span aria-hidden="true"
                  className="shrink-0 w-6 h-[2px] mt-4 bg-[var(--border)]" />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </section>
  );
};

/**
 * Who hands off to whom, restated as a compact flow rather than the SOP's own prose — the
 * same twelve handoffs, collapsed by default so it reads as a reference to open when needed
 * rather than something to scroll past on every visit.
 */
const APPROVAL_FLOW = [
  { actor: 'HOD', action: 'Raises the internal requisition — role, reporting line, business justification.' },
  { actor: 'Management / Finance', action: 'Approves headcount and budget. Mandatory — nothing is sourced before this.' },
  { actor: 'HR', action: 'Drafts the JD and position scorecard, sends it to the HOD.' },
  { actor: 'HOD', action: 'Approves the scorecard — and Management too, for managerial+ roles.' },
  { actor: 'HR', action: 'Sources, screens, assesses, and coordinates the panel interview.' },
  { actor: 'HR + HOD', action: 'Act as the shortlisting committee and finalise the candidate.' },
  { actor: 'Management', action: 'Final interview — managerial and above roles only.' },
  { actor: 'HR', action: 'Completes the reference check — mandatory for every role.' },
  { actor: 'Management / Finance', action: 'Approves the offer. Outside the approved budget, this step repeats.' },
  { actor: 'HR', action: 'Releases the offer letter.' },
  { actor: 'Candidate', action: 'Accepts, pre-boards, and joins.' },
  { actor: 'HR → HOD → Management', action: 'Induction, then probation review and confirmation.' },
];

const ApprovalFlow = () => (
  <FlowAccordion
    icon={GitBranch}
    title="Who approves what — the request flow"
    subtitle="Every handoff, HOD to close-out, in order."
    steps={APPROVAL_FLOW}
  />
);

/** One pending-action definition: how to count it, where it goes, who clears it. */
const ACTIONS = [
  {
    key: 'budget',
    label: 'Budget approval required',
    icon: Wallet,
    who: 'Management or Finance',
    detail: 'Nothing can be sourced until the headcount and salary band are approved.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending Budget Approval',
  },
  {
    key: 'hr',
    label: 'HR verification required',
    icon: ClipboardCheck,
    who: 'HR',
    detail: 'The role and its justification need checking before it goes for budget.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending HR Verification',
  },
  {
    key: 'escalation',
    label: 'Escalation to clear',
    icon: AlertTriangle,
    who: 'the reporting line',
    detail: 'Raised above the sanctioned headcount, so it routes up the reporting line.',
    to: '/hrms/internal-requisitions',
    match: (r) => r.approval_status === 'Pending Escalation',
  },
  {
    key: 'scorecard',
    label: 'Scorecard approval required',
    icon: Target,
    who: 'the hiring manager',
    detail: 'The position scorecard is written and waiting for review.',
    to: '/hrms/scorecards',
    match: (r) => r.approval_status === 'Pending Scorecard Approval',
  },
  {
    key: 'interviews',
    label: 'Interviews pending',
    icon: CalendarDays,
    who: 'the panel',
    detail: 'Scheduled but not yet completed.',
    to: '/hrms/interviews',
    match: (r) => (r.interviews?.total || 0) > (r.interviews?.completed || 0),
    countOf: (r) => (r.interviews.total - r.interviews.completed),
  },
  {
    key: 'references',
    label: 'Reference checks pending',
    icon: PhoneCall,
    who: 'HR',
    detail: 'Somebody has been selected but no reference is on file. An internal offer is '
          + 'blocked until one is completed.',
    to: '/hrms/reference-checks',
    // Selected, but no offer has been raised yet -- the window in which the reference
    // check is the thing standing in the way.
    match: (r) => (r.candidates?.selected || 0) > 0 && !r.offer?.status,
  },
  {
    key: 'offers',
    label: 'Offers pending',
    icon: FileSignature,
    who: 'HR and the approver',
    detail: 'Raised but not yet accepted.',
    to: '/hrms/offers',
    match: (r) => r.offer?.status && !['Accepted', 'Declined', 'Withdrawn']
      .includes(r.offer.status),
  },
  {
    key: 'probation',
    label: 'Probation reviews due',
    icon: ShieldCheck,
    who: 'the hiring manager',
    detail: 'The probation period ends within 30 days and no decision is recorded.',
    to: '/hrms/probation',
    match: (r) => {
      if (!r.probation?.ends_on || r.probation.outcome !== 'Pending') return false;
      const ends = new Date(r.probation.ends_on);
      const in30 = new Date();
      in30.setDate(in30.getDate() + 30);
      return ends <= in30;
    },
  },
];

/** The tracker's own SLA vocabulary, rendered in words a reader recognises. There is no
 *  "at risk" state -- a milestone is running, met, or late -- so the chip does not invent one. */
const SLA_TONE = {
  breached: 'bad', on_track: 'good', met: 'good', not_started: 'neutral', unknown: 'neutral',
};
const SLA_LABEL = {
  breached: 'Overdue', on_track: 'On track', met: 'Met',
  not_started: 'Not started', unknown: 'Unknown',
};

const InternalHiringDashboard = () => {
  const { scope, companyId, companyName, can } = useHrms();
  const navigate = useNavigate();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [raising, setRaising] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await getInternalTracker({ ...scope, limit: 200 });
      setRows(data?.rows || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load internal hiring.');
    } finally {
      setLoading(false);
    }
    // `scope` is a fresh object literal on every HrmsContext render, so depending on it
    // here would rebuild `load` every render and re-run the effect for ever. Keyed on
    // the primitives instead, exactly as every other HRMS screen is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const pending = useMemo(
    () => ACTIONS.map((a) => {
      const hits = rows.filter(a.match);
      const count = a.countOf
        ? hits.reduce((sum, r) => sum + a.countOf(r), 0)
        : hits.length;
      return { ...a, count };
    }),
    [rows],
  );

  const headline = useMemo(() => {
    const open = rows.filter((r) => r.closing_status === 'Open');
    return {
      openPositions: open.length,
      seats: open.reduce((n, r) => n + (r.budget?.approved_headcount || r.vacancy || 1), 0),
      candidates: rows.reduce((n, r) => n + (r.candidates?.total || 0), 0),
      awaiting: rows.filter((r) => (r.approval_status || '').startsWith('Pending')).length,
      overdue: rows.filter((r) => r.sla?.status === 'breached').length,
    };
  }, [rows]);

  if (loading) return <HrmsLoading label="Loading internal hiring…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  const outstanding = pending.filter((p) => p.count > 0);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <span className="h-11 w-11 rounded-xl bg-[var(--accent-indigo)] text-white
                           grid place-items-center shrink-0">
            <Briefcase size={20} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[20px] font-bold tracking-tight text-[var(--text-main)]">
              Internal hiring
            </h1>
            <p className="text-[12.5px] text-[var(--text-muted)]">
              {companyName || 'This company'}&rsquo;s own vacancies, start to close.
            </p>
          </div>
        </div>
        {can(CAP.REQUISITION_CREATE) && (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise
          </Btn>
        )}
      </div>

      {/* The two hiring tracks. A switch, not a filter: everything below belongs to
          Internal Hiring, and Client Hiring is a different set of screens entirely. */}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Tile label="Open positions" value={headline.openPositions} icon={Briefcase} tone="indigo" />
        <Tile label="Seats to fill" value={headline.seats} icon={Users2} tone="indigo" />
        <Tile label="Awaiting approval" value={headline.awaiting} icon={Clock} tone="orange" />
        <Tile label="Candidates" value={headline.candidates} icon={UserCircle} tone="green" />
        <Tile label="SLA overdue" value={headline.overdue} icon={AlertTriangle}
              tone={headline.overdue ? 'red' : 'indigo'} />
      </div>

      <StageTracker />

      <ApprovalFlow />

      <section aria-labelledby="pending-heading">
        <h2 id="pending-heading"
            className="text-[10.5px] font-bold uppercase tracking-widest
                       text-[var(--text-muted)] mb-2">
          Pending actions
        </h2>
        {outstanding.length === 0 ? (
          <HrmsEmpty
            icon={Check}
            title="Nothing is waiting on anybody"
            hint="Every internal position is either approved and running, or closed."
          />
        ) : (
          <div className="grid gap-2.5 sm:grid-cols-2">
            {outstanding.map((a) => (
              <button
                key={a.key} type="button" onClick={() => navigate(a.to)}
                className={`${CARD} !p-3.5 text-left flex items-start gap-3 border-l-4
                  border-l-[var(--accent-orange)]
                  hover:border-[var(--accent-indigo)] hover:shadow-sm transition-all`}
              >
                <span className="mt-0.5 h-9 w-9 shrink-0 rounded-lg bg-[var(--accent-orange-bg)]
                                 grid place-items-center">
                  <a.icon size={16} className="text-[var(--accent-orange)]" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="text-[13px] font-bold text-[var(--text-main)]">
                      {a.label}
                    </span>
                    <Chip tone="accent">{a.count}</Chip>
                  </span>
                  <span className="block mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                    {a.detail}
                  </span>
                  <span className="block mt-1 text-[11px] text-[var(--text-muted)]">
                    Cleared by {a.who}
                  </span>
                </span>
                <ChevronRight size={16} className="text-[var(--text-muted)] mt-1 shrink-0" />
              </button>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="recent-heading">
        <h2 id="recent-heading"
            className="text-[10.5px] font-bold uppercase tracking-widest
                       text-[var(--text-muted)] mb-2">
          Internal positions
        </h2>
        {rows.length === 0 ? (
          <HrmsEmpty
            title="No internal requisitions yet"
            hint={`Raise one on the Requisitions screen. ${companyName || 'This company'}'s `
              + 'own vacancies run through HR verification, budget approval and a position '
              + 'scorecard before sourcing begins.'}
          />
        ) : (
          <>
            {/* Cards on a phone, a table above it -- eight columns at 375px is unreadable
                however it is scrolled, and the fields that matter differ between the two. */}
            <ul className="md:hidden space-y-2">
              {rows.map((r) => (
                <li key={r.request_no}>
                  <button type="button"
                          onClick={() => navigate(`/hrms/internal-requisitions/${r.request_no}`)}
                          className={`${CARD} !p-3.5 w-full text-left`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[13px] font-bold text-[var(--text-main)] truncate">
                          {r.designation_name || r.request_no}
                        </p>
                        <p className="text-[11px] text-[var(--text-muted)] truncate">
                          {r.department_name} · {r.request_no}
                        </p>
                      </div>
                      <Chip tone={r.sla?.status === 'breached' ? 'bad' : 'neutral'}>
                        {r.approval_status}
                      </Chip>
                    </div>
                    <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)]">
                      {r.candidates?.total || 0} candidates ·
                      {' '}{r.budget?.approved ? 'budget approved' : 'budget pending'}
                      {r.required_date ? ` · needed ${day(r.required_date)}` : ''}
                    </p>
                  </button>
                </li>
              ))}
            </ul>

            <div className={`${CARD} !p-0 hidden md:block overflow-hidden`}>
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-[10.5px] font-bold uppercase tracking-widest
                                 text-[var(--text-muted)] bg-[var(--input-bg)] border-b border-[var(--border)]">
                    <th className="text-left px-3.5 py-2.5">Position</th>
                    <th className="text-left px-3.5 py-2.5">Department</th>
                    <th className="text-right px-3.5 py-2.5">Seats</th>
                    <th className="text-left px-3.5 py-2.5">Salary band</th>
                    <th className="text-left px-3.5 py-2.5">Stage</th>
                    <th className="text-right px-3.5 py-2.5">Candidates</th>
                    <th className="text-left px-3.5 py-2.5">SLA</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.request_no}
                        onClick={() => navigate(`/hrms/internal-requisitions/${r.request_no}`)}
                        className="border-b border-[var(--border)] last:border-0
                                   hover:bg-[var(--input-bg)] cursor-pointer transition-colors">
                      <td className="px-3.5 py-2.5">
                        <span className="font-semibold text-[var(--text-main)]">
                          {r.designation_name || '—'}
                        </span>
                        <span className="block font-mono text-[11px] text-[var(--text-muted)]">
                          {r.request_no}
                        </span>
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-muted)]">
                        {r.department_name || '—'}
                      </td>
                      <td className="px-3.5 py-2.5 text-right tabular-nums">
                        {r.budget?.approved_headcount ?? r.vacancy ?? '—'}
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-muted)]">
                        {r.budget?.band_min != null
                          ? `${r.budget.band_min} – ${r.budget.band_max}`
                          : 'not approved'}
                      </td>
                      <td className="px-3.5 py-2.5">
                        <Chip tone={r.approval_status === 'Approved' ? 'good' : 'warn'}>
                          {r.approval_status}
                        </Chip>
                      </td>
                      <td className="px-3.5 py-2.5 text-right tabular-nums">
                        {r.candidates?.total || 0}
                      </td>
                      <td className="px-3.5 py-2.5">
                        <Chip tone={SLA_TONE[r.sla?.status] || 'neutral'}
                              title={r.sla?.status === 'breached'
                                ? (r.sla.breached_labels || []).join(', ')
                                : r.sla?.next_label
                                  ? `Next: ${r.sla.next_label}`
                                  : undefined}>
                          {SLA_LABEL[r.sla?.status] || 'Not started'}
                        </Chip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {raising && (
        <RequisitionFormModal
          onClose={() => setRaising(false)}
          onSaved={() => { setRaising(false); load(); }}
        />
      )}
    </div>
  );
};

export default InternalHiringDashboard;
