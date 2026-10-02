import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Building2, Lock, Plus, BarChart3, Clock, CheckCircle2, ClipboardList, UserCircle,
  GitBranch, Inbox,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getClientRequisitions, getClientScorecards, getClientPostings,
  getClientCandidates,
  getClientAssessments, getClientInterviews, getClientOffers, getClientJoinings,
} from '../../../services/hrmsApi';
import { CARD } from '../internal/internalKit';
import { Btn, Tile, FlowAccordion } from '../internal/internalKit.jsx';
import { ClientCompanyBar, ClientScopeProvider } from './clientKit.jsx';
import ClientRequisitions from './ClientRequisitions';
import ClientScorecards from './ClientScorecards';
import ClientPostings from './ClientPostings';
import ClientCandidates from './ClientCandidates';
import ClientAssessments from './ClientAssessments';
import ClientInterviews from './ClientInterviews';
import ClientOffers from './ClientOffers';
import ClientJoinings from './ClientJoinings';
import { useClientCompanies } from './clientKit';

/**
 * HRMS ▸ Client Hiring — the entry screen for the PRO-fit track.
 *
 * A separate track from Internal Hiring with its own records, statuses and permissions.
 * Nothing on this screen reads an internal requisition, an internal candidate or an
 * internal employee; the two never meet.
 *
 * -- What this screen is for -------------------------------------------------------
 * The PRO-fit flow is a chain: each stage is opened by the one before it, and the two
 * commonest questions are "what needs me right now" and "why can I not do the next
 * thing". So the board answers them in that order:
 *
 *   1. a single line saying what is sitting with you, before any stage detail;
 *   2. the stages in sequence, each showing what is in it;
 *   3. stages that nothing has reached yet shown as LOCKED, naming what opens them,
 *      rather than as a zero that looks like a failure.
 *
 * A brand new engagement has nothing in any stage. Seven zeros is a true picture and a
 * useless one, so that case gets a "start here" panel instead of the grid.
 *
 * Counts come from each stage's own endpoint, which is also what enforces the scoping:
 * a client company's user gets their own company's numbers and nobody else's, decided by
 * the server rather than by anything here.
 */

// The eight stages. Each label is the SAME words as the matching tab in CLIENT_WORKSPACE
// (common/hrmsWorkspaces.js) — the strip and the rail name the same stage twice on one
// screen, and two spellings of it would read as two different things.
const STAGES = [
  { key: 'requisitions', label: 'Requisition',
    hint: 'Need Mapping → Manpower Requisition → feasibility',
    opens: 'the client raising a requirement',
    to: '/hrms/client-requisitions', cap: CAP.CLIENT_REQUISITION_READ,
    load: getClientRequisitions, rows: 'client_requisitions',
    waiting: 'pending_feasibility',
    mineLabel: 'awaiting your feasibility review',
    theirsLabel: 'with Sparsh for review',
    waitingSide: 'sparsh' },
  { key: 'scorecards', label: 'Position Scorecard',
    hint: 'drafted by Sparsh, approved by the client',
    opens: 'an approved requisition',
    to: '/hrms/client-scorecards', cap: CAP.CLIENT_SCORECARD_READ,
    load: getClientScorecards, rows: 'client_scorecards',
    waiting: 'awaiting_client',
    mineLabel: 'awaiting your approval',
    theirsLabel: 'with the client to approve',
    waitingSide: 'client' },
  { key: 'postings', label: 'Job Posting',
    hint: 'advertised once the client agrees the benchmark',
    opens: 'an approved scorecard',
    to: '/hrms/client-hiring?stage=postings', cap: CAP.CLIENT_POSTING_READ,
    load: getClientPostings, rows: 'client_postings',
    waiting: 'unpublished',
    mineLabel: 'still in draft',
    theirsLabel: 'not advertised yet',
    waitingSide: 'sparsh' },
  { key: 'candidates', label: 'Sourcing & CV Share',
    hint: 'screened against the scorecard, then shared',
    opens: 'an approved scorecard',
    to: '/hrms/client-candidates', cap: CAP.CLIENT_CANDIDATE_READ,
    load: getClientCandidates, rows: 'client_candidates',
    waiting: 'awaiting_client',
    mineLabel: 'awaiting your CV verdict',
    theirsLabel: 'with the client for a CV verdict',
    waitingSide: 'client' },
  { key: 'assessments', label: 'Assessment',
    hint: 'opened by the client approving the CV',
    opens: 'the client approving a CV',
    to: '/hrms/client-hiring?stage=assessments', cap: CAP.CLIENT_ASSESSMENT_READ,
    load: getClientAssessments, rows: 'client_assessments',
    waiting: 'awaiting_client',
    mineLabel: 'awaiting your review of the result',
    theirsLabel: 'with the client to review',
    waitingSide: 'client' },
  { key: 'interviews', label: 'Interview & Recording',
    hint: 'conducted by Sparsh, watched by the client',
    opens: 'a reviewed assessment',
    to: '/hrms/client-hiring?stage=interviews', cap: CAP.CLIENT_INTERVIEW_READ,
    load: getClientInterviews, rows: 'client_interviews',
    waiting: 'awaiting_client',
    mineLabel: 'awaiting your selection',
    theirsLabel: 'with the client to select',
    waitingSide: 'client' },
  { key: 'offers', label: 'Offer',
    hint: 'verified by Sparsh, issued by the client',
    opens: 'the client selecting somebody',
    to: '/hrms/client-offers', cap: CAP.CLIENT_OFFER_READ,
    load: getClientOffers, rows: 'client_offers',
    waiting: 'awaiting_client',
    mineLabel: 'awaiting your release',
    theirsLabel: 'with the client to issue',
    waitingSide: 'client' },
  { key: 'joinings', label: 'Pre-boarding & Joining',
    hint: 'handover closes the requisition',
    opens: 'an accepted offer',
    to: '/hrms/client-joinings', cap: CAP.CLIENT_JOINING_READ,
    load: getClientJoinings, rows: 'client_joinings',
    waiting: 'at_risk',
    mineLabel: 'flagged at risk',
    theirsLabel: 'flagged at risk by Sparsh',
    waitingSide: 'sparsh' },
];


/**
 * Who owns each handoff on the PRO-fit chain, in order.
 *
 * Two wordings of ONE flow, not two flows: the steps and their owners are identical, and
 * only the second person changes ("you" is the client on their own board, and the client
 * is a third party on Sparsh's). Writing it once in the neutral voice would make the five
 * client-owned decisions read as somebody else's problem on the very board whose whole
 * point is that they are not.
 *
 * The five decisions marked CLIENT below are enforced server-side and are refused to every
 * Sparsh role including Superadmin — see CLIENT_DECISION_CAPS in app/models/hrms.py. This
 * list is a description of that rule, never the rule itself.
 */
const flowSteps = (you, them) => [
  { actor: you.client, action: 'Raises the requirement — Need Mapping, then the Manpower Requisition with the salary range.' },
  { actor: 'Sparsh', action: 'Reviews feasibility: role clarity, whether the pay is competitive, whether the timeline is real. Nothing is sourced before this clears.' },
  { actor: 'Sparsh', action: 'Drafts the Position Scorecard — the benchmark every later score is measured against.' },
  { actor: `${you.client} — decision`, action: `Approves the scorecard. Sourcing waits for it, and ${them} cannot approve it.` },
  { actor: 'Sparsh', action: 'Advertises the role, sources, and screens candidates against the scorecard.' },
  { actor: 'Sparsh', action: 'Shares the shortlisted CVs.' },
  { actor: `${you.client} — decision`, action: 'Approves or rejects each CV. A rejected candidate is kept and can be offered to another client, never deleted.' },
  { actor: 'Sparsh', action: 'Runs the assessment, then the interview, and shares the recording and scores.' },
  { actor: `${you.client} — decision`, action: 'Selects or rejects after the interview.' },
  { actor: 'Sparsh', action: 'Completes verification and prepares the offer.' },
  { actor: `${you.client} — decision`, action: 'Releases the offer.' },
  { actor: 'Sparsh', action: 'Runs pre-boarding and keeps the joining on track.' },
  { actor: `${you.client} — decision`, action: 'Confirms joining. Handover closes the requisition.' },
];

/** Sparsh staff are looking at somebody else's engagement. */
const CLIENT_FLOW_SPARSH = flowSteps({ client: 'The client' }, 'Sparsh');
/** The client is looking at their own. */
const CLIENT_FLOW_CLIENT = flowSteps({ client: 'You' }, 'Sparsh');

/** Which stage panel a key renders. Assessment and Interview live inside a candidate's
 *  own record rather than as lists of their own, so they open the candidate panel — the
 *  rail still names them because they are stages of the flow and carry their own counts. */
const PANEL = {
  requisitions: ClientRequisitions,
  scorecards: ClientScorecards,
  postings: ClientPostings,
  candidates: ClientCandidates,
  // Their own boards now, not the candidate list with a note. "Where is this person up
  // to" and "what is sitting at this stage" are different questions; the internal track
  // answers both, and this one only answered the first.
  assessments: ClientAssessments,
  interviews: ClientInterviews,
  offers: ClientOffers,
  joinings: ClientJoinings,
};

const ClientHiringDashboard = () => {
  const { companyId, can, isInternal } = useHrms();
  const { clients, anyEnabled, picked, setPicked, pickedName } = useClientCompanies();
  const [params, setParams] = useSearchParams();
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const visible = STAGES.filter((s) => can(s.cap));
  const canRaise = can(CAP.CLIENT_REQUISITION_WRITE);

  // The open stage lives in the URL, so a deep link, a refresh and the back button all
  // behave. Falling back to the first stage the viewer may see rather than a fixed key:
  // a role without CLIENT_REQUISITION_READ would otherwise open on a panel it cannot load.
  const requested = params.get('stage');
  const active = visible.some((s) => s.key === requested)
    ? requested
    : (visible[0]?.key ?? null);

  const openStage = (key) => {
    const next = new URLSearchParams(params);
    next.set('stage', key);
    setParams(next, { replace: true });
  };

  // Sparsh staff look at one client at a time; a client-side user is pinned server-side
  // and the id they send is ignored, so it is simply not sent.
  const query = isInternal && picked ? { company_id: picked } : {};

  const load = useCallback(async () => {
    if (!companyId && !isInternal) { setLoading(false); return; }
    if (isInternal && !picked && clients.length) return;   // wait for the picker
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.all(visible.map(async (stage) => {
        try {
          const { data } = await stage.load({ ...query, limit: 200 });
          return [stage.key, {
            total: data?.total ?? (data?.[stage.rows] || []).length,
            waiting: data?.[stage.waiting] ?? 0,
          }];
        } catch {
          // One stage failing must not blank the board. A dash is honest; zero is not.
          return [stage.key, null];
        }
      }));
      setCounts(Object.fromEntries(results));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the client hiring board.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, isInternal, picked, clients.length]);

  useEffect(() => { load(); }, [load]);

  // A stage is LOCKED when nothing has reached it and nothing has reached the stage
  // before it either. Stage 1 is never locked -- it is where the chain starts.
  const lockedFrom = (() => {
    const totals = visible.map((s) => counts[s.key]?.total ?? 0);
    return visible.map((_s, i) => i > 0 && totals[i] === 0 && totals[i - 1] === 0);
  })();

  const nothingYet = visible.length > 0
    && visible.every((s) => (counts[s.key]?.total ?? 0) === 0)
    && Object.keys(counts).length > 0;

  // "Needs you" is a different pile depending on which side of the engagement you are on.
  const mySide = isInternal ? 'sparsh' : 'client';
  const needsMe = visible.reduce((n, s) =>
    n + (s.waitingSide === mySide ? (counts[s.key]?.waiting ?? 0) : 0), 0);
  const needsThem = visible.reduce((n, s) =>
    n + (s.waitingSide !== mySide ? (counts[s.key]?.waiting ?? 0) : 0), 0);

  const activeStage = visible.find((s) => s.key === active);
  const Panel = active ? PANEL[active] : null;

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Building2}
        title="Client Hiring"
        subtitle={isInternal
          ? "Recruiting on behalf of client companies (PRO-fit). Separate from Sparsh Magic's own internal hiring."
          : 'Your hiring with Sparsh, from the requirement through to the day they join (PRO-fit).'}
        actions={can(CAP.CLIENT_ANALYTICS_READ) && (
          <Link to="/hrms/client-analytics">
            <Btn><BarChart3 size={14} /> Analytics</Btn>
          </Link>
        )}
      />
      <ClientCompanyBar
        clients={clients} picked={picked} onPick={setPicked}
        isInternal={isInternal} anyEnabled={anyEnabled}
      />

      {loading && <HrmsLoading label="Loading the client hiring board…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && !!visible.length && (
        <>
          {/* Before anything scoped to one client: has anything arrived from ANY of them.
              Renders nothing when the queue is empty, so it never becomes furniture. */}
          {isInternal && (
            <ClientRequestInbox
              clients={clients}
              onOpen={(companyId) => { setPicked(companyId); openStage('requisitions'); }}
            />
          )}

          {/* The same headline row Internal Hiring opens with, built from the same
              `Tile`. Whose move it is comes first: it is the question the PRO-fit chain
              raises at every step, and a number that is zero is as useful as one that is
              not. A stage this role cannot read shows a dash, never a zero. */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Tile
              icon={ClipboardList}
              label={isInternal ? 'Open requirements' : 'Your requirements'}
              value={counts.requisitions?.total ?? '—'}
              hint={isInternal ? 'Raised by this client' : 'Raised with Sparsh'}
            />
            <Tile
              icon={UserCircle}
              label="Candidates in play"
              value={counts.candidates?.total ?? '—'}
              tone="green"
              hint="Sourced and screened by Sparsh"
            />
            <Tile
              icon={Clock}
              label={isInternal ? 'Waiting on Sparsh' : 'Waiting on you'}
              value={needsMe}
              tone={needsMe ? 'orange' : 'green'}
              hint={needsMe
                ? 'Your move — the orange steps below'
                : 'Nothing is sitting with you'}
            />
            <Tile
              icon={CheckCircle2}
              label={isInternal ? 'Waiting on the client' : 'Waiting on Sparsh'}
              value={needsThem}
              hint={needsThem
                ? 'Chase these if they have sat a while'
                : 'Nothing is sitting with them'}
            />
          </div>

          {nothingYet ? (
            <StartHere canRaise={canRaise} isInternal={isInternal}
              who={isInternal ? (pickedName || 'this client') : 'you'} />
          ) : (
            <>
              {/* THE RAIL — the same connected stepper Internal Hiring draws, so the
                  two tracks read as one module. It carries more than internal's does
                  (a count, and what is waiting on whom) because on this track those are
                  the questions the chain keeps raising; the geometry is identical.

                  Every stage is on this page: picking one swaps the panel below rather
                  than navigating away. Eight separate pages made one flow feel like eight
                  unrelated screens, and losing the counts on every click made "where are
                  we" a question you had to go back for. */}
              <section aria-labelledby="client-stages-heading" className={`${CARD} !p-4`}>
                <h2 id="client-stages-heading"
                  className="text-[10.5px] font-bold uppercase tracking-widest
                    text-[var(--text-muted)] mb-3">
                  PRO-fit stages — client hiring
                </h2>
                <div className="flex items-start overflow-x-auto no-scrollbar pb-1 -mx-1 px-1">
                  {visible.map((stage, i) => (
                    <StageStep
                      key={stage.key}
                      stage={stage}
                      index={i}
                      count={counts[stage.key]}
                      locked={lockedFrom[i]}
                      mine={stage.waitingSide === mySide}
                      waitingLabel={stage.waitingSide === mySide
                        ? stage.mineLabel : stage.theirsLabel}
                      active={stage.key === active}
                      onOpen={() => openStage(stage.key)}
                      last={i === visible.length - 1}
                    />
                  ))}
                </div>
              </section>

              {/* Who owns which stage — the same collapsed reference Internal Hiring
                  carries for its own SOP handoffs, in the same place on the page. */}
              <FlowAccordion
                icon={GitBranch}
                title="Who decides what — the PRO-fit flow"
                subtitle={`${visible.length} stages, each opened by the one before it.`}
                steps={isInternal ? CLIENT_FLOW_SPARSH : CLIENT_FLOW_CLIENT}
              />

              {/* THE PANEL. The stage screens are the same components the standalone
                  routes render; `embedded` swaps their page header for a compact one so
                  the page has a single title. */}
              {Panel && (
                <div className={`${CARD} space-y-4`}>
                  {lockedFrom[visible.findIndex((s) => s.key === active)] ? (
                    <div className="py-8 text-center">
                      <Lock size={20} className="mx-auto text-[var(--text-muted)]" />
                      <p className="mt-2 text-[13px] font-bold text-[var(--text-main)]">
                        {activeStage?.label} has not opened yet
                      </p>
                      <p className="text-[11.5px] text-[var(--text-muted)]">
                        Opens on {activeStage?.opens}.
                      </p>
                    </div>
                  ) : (
                    <ClientScopeProvider companyId={isInternal ? picked : null}>
                      <Panel embedded onChanged={load} />
                    </ClientScopeProvider>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}

      {!loading && !error && !visible.length && (
        <p className="text-[12.5px] text-[var(--text-muted)]">
          Your role holds no Client Hiring permissions, so there is nothing to show here.
        </p>
      )}
    </div>
  );
};

/**
 * THE INBOX — every client's new job requests, in one place.
 *
 * The rest of this board is scoped to ONE client at a time, which is right for working a
 * single engagement and wrong for the question "has anything come in". Sparsh runs 20-odd
 * client companies; without this, noticing a new request means opening the picker and
 * flipping through every one of them, and a request nobody opens is a request nobody
 * answers.
 *
 * `Pending Feasibility` is exactly "the client has sent it and it is now Sparsh's move" —
 * the two states before it are the client still filling their own forms, which are theirs
 * and not yet a request at all.
 *
 * Deliberately READ-AND-JUMP, not read-and-act. Reviewing a requisition needs that
 * client's scope (their scorecards, their candidates, their history), so clicking a row
 * switches the board to that client rather than trying to act across tenants from a shared
 * list. One request is answered inside one engagement, which is also the only reading that
 * keeps tenant isolation obvious.
 *
 * Internal only. A client-side caller sees their own requisitions on the stage panel
 * below; a cross-client inbox would be a list of other people's companies.
 */
const ClientRequestInbox = ({ clients, onOpen }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    // No company_id: for Sparsh staff the server reads that as "every client"
    // (list_client_requisitions). A client-side caller is pinned by the route and could
    // not widen it even by asking, which is why this component is internal-only.
    getClientRequisitions({ status: 'Pending Feasibility', limit: 200 })
      .then(({ data }) => { if (live) setRows(data?.client_requisitions || []); })
      .catch(() => { if (live) setRows([]); })
      .finally(() => { if (live) setLoading(false); });
  }, []);

  const nameOf = (id) =>
    (clients.find((c) => c.id === id) || {}).name || 'Unknown client';

  if (loading || !rows.length) return null;

  return (
    <section className={`${CARD} !p-4`}>
      <div className="flex items-center gap-2.5">
        <span className="h-8 w-8 rounded-lg bg-[var(--accent-orange-bg)]
          grid place-items-center shrink-0">
          <Inbox size={15} className="text-[var(--accent-orange)]" />
        </span>
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            New job requests from clients
            <span className="ml-1.5 text-[var(--accent-orange)] tabular-nums">
              {rows.length}
            </span>
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Sent to Sparsh and waiting on your feasibility review — across every client.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        {rows.map((r) => (
          <button
            key={`${r.company_id}:${r.cr_no}`}
            type="button"
            onClick={() => onOpen(r.company_id)}
            className="w-full text-left rounded-xl border border-[var(--border)]
              hover:border-[var(--accent-orange)] px-3 py-2.5 transition-colors
              flex items-center justify-between gap-3"
          >
            <div className="min-w-0">
              <p className="text-[12.5px] font-bold text-[var(--text-main)] truncate">
                {r.role_title || r.cr_no}
              </p>
              <p className="text-[11px] text-[var(--text-muted)] truncate">
                {nameOf(r.company_id)} · {r.cr_no}
                {r.department_name ? ` · ${r.department_name}` : ''}
                {r.vacancies ? ` · ${r.vacancies} vacancies` : ''}
              </p>
            </div>
            <div className="shrink-0 flex items-center gap-2.5">
              {r.urgency && (
                <span className={`text-[10.5px] font-bold uppercase tracking-wide ${
                  r.urgency === 'Immediate' ? 'text-[var(--accent-red)]'
                    : r.urgency === 'High' ? 'text-[var(--accent-orange)]'
                      : 'text-[var(--text-muted)]'}`}>
                  {r.urgency}
                </span>
              )}
              <span className="text-[11.5px] font-bold text-[var(--accent-indigo)]">
                Review
              </span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
};


/**
 * One step on the rail — Internal Hiring's stepper, with this track's numbers on it.
 *
 * Same geometry as InternalHiringDashboard's StageTracker: a numbered circle, its label
 * beneath, a connector bar to the next one. What differs is that this rail is live —
 * internal's is a picture of the SOP, whereas here each step carries how much is sitting
 * at it and whether any of it is waiting on the person reading.
 *
 * Deliberately a button, not a link: the whole flow is one page, so picking a stage is a
 * selection rather than a journey. A locked step stays visible and stays clickable — it
 * explains itself in the panel, which is more use than a control that ignores you.
 */
const StageStep = ({ stage, index, count, locked, mine, waitingLabel, active, onOpen,
  last }) => {
  const waiting = count?.waiting ?? 0;
  const needsYou = mine && waiting > 0;

  // Two independent signals, so they must not share a channel. "Needs you" owns the
  // orange; "open right now" owns the indigo fill. Letting active win outright lost the
  // orange on exactly the step you were most likely to be looking at — the one that
  // wanted something from you. So a step that needs you keeps its orange ring even while
  // it is the open one.
  const ring = needsYou
    ? 'border-[var(--accent-orange)] ' + (active
      ? 'bg-[var(--accent-orange)] text-white'
      : 'bg-[var(--bg-card)] text-[var(--accent-orange)]')
    : active
      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)] text-white'
      : 'border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-muted)] '
        + 'group-hover:border-[var(--accent-indigo)] group-hover:text-[var(--accent-indigo)]';

  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        aria-current={active ? 'step' : undefined}
        title={locked ? `Opens on ${stage.opens}` : stage.hint}
        className={`group shrink-0 flex flex-col items-center gap-1.5 w-[108px]
          text-center ${locked && !active ? 'opacity-60' : ''}`}
      >
        <span className={`h-8 w-8 rounded-full grid place-items-center text-[11px]
          font-bold border-2 transition-colors ${ring}`}>
          {locked && !active ? <Lock size={13} /> : index + 1}
        </span>

        <span className={`text-[10.5px] font-bold leading-tight transition-colors ${
          needsYou ? 'text-[var(--accent-orange)]'
            : active ? 'text-[var(--accent-indigo)]'
              : 'text-[var(--text-muted)] group-hover:text-[var(--text-main)]'}`}>
          {stage.label}
        </span>

        {/* The live half. A dash, not a zero, when the stage failed to load: zero is a
            claim about the data and a dash is a claim about the request. */}
        <span className="text-[10px] text-[var(--text-muted)] leading-tight">
          <span className="font-bold tabular-nums text-[var(--text-main)]">
            {count ? count.total : '—'}
          </span>{' '}
          on record
        </span>

        {!!waiting && (
          <span className={`text-[10px] font-bold leading-tight line-clamp-2 ${
            needsYou ? 'text-[var(--accent-orange)]' : 'text-[var(--text-muted)]'}`}
            title={`${waiting} ${waitingLabel}`}>
            {waiting} {waitingLabel}
          </span>
        )}
      </button>

      {!last && (
        <span aria-hidden="true"
          className="shrink-0 w-6 h-[2px] mt-4 bg-[var(--border)]" />
      )}
    </>
  );
};

/**
 * What a brand new engagement sees instead of seven zeros.
 *
 * Seven empty stages is an accurate picture of nothing having happened and a useless one:
 * it looks like a broken screen rather than an empty one, and says nothing about where to
 * begin. The chain has exactly one entry point, so this names it.
 */
const StartHere = ({ canRaise, who, isInternal }) => (
  <div className={`${CARD} space-y-3`}>
    <div>
      <p className="text-[15px] font-bold text-[var(--text-main)]">
        {isInternal ? `Nothing has started for ${who} yet` : 'Nothing has started yet'}
      </p>
      <p className="text-[12px] text-[var(--text-muted)] mt-0.5">
        PRO-fit is a chain with one way in. The first three steps are:
      </p>
    </div>

    <ol className="space-y-2">
      {[
        [isInternal ? 'The client raises a requirement' : 'You raise a requirement',
          'A Need Mapping Form, then the Manpower Requisition with the salary range.'],
        ['Sparsh reviews feasibility',
          'Role clarity, whether the pay is competitive, whether the timeline is real. '
          + 'Nothing is sourced until this clears.'],
        ['The Position Scorecard is agreed',
          isInternal
            ? 'Sparsh drafts the benchmark, the client approves it. Every later score is '
              + 'measured against it, so sourcing waits for it.'
            : 'Sparsh drafts the benchmark and you approve it. Every later score is '
              + 'measured against it, so sourcing waits for your approval.'],
      ].map(([title, body], i) => (
        <li key={title} className="flex gap-2.5">
          <span className="shrink-0 mt-0.5 w-5 h-5 rounded-full grid place-items-center
            text-[10.5px] font-bold tabular-nums bg-[var(--input-bg)]
            text-[var(--text-muted)]">
            {i + 1}
          </span>
          <div>
            <p className="text-[12.5px] font-semibold text-[var(--text-main)]">{title}</p>
            <p className="text-[11.5px] text-[var(--text-muted)]">{body}</p>
          </div>
        </li>
      ))}
    </ol>

    {canRaise && (
      <Link to="/hrms/client-hiring?stage=requisitions" className="inline-block">
        <Btn tone="primary"><Plus size={14} /> Raise the first requirement</Btn>
      </Link>
    )}
  </div>
);

export default ClientHiringDashboard;
