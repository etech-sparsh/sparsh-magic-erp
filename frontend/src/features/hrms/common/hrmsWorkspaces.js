import {
  ClipboardList, ScrollText, Megaphone, UserCircle,
  ClipboardCheck, ListChecks, CalendarDays, FileSignature, UserPlus, PieChart,
  BadgeCheck, Target, PhoneCall, Users2, Phone, Scale,
  ShieldCheck, Briefcase, LayoutDashboard, Star,
  HeartHandshake, GraduationCap, HeartPulse, CalendarClock,
  Building2,
} from 'lucide-react';
import { CAP } from '../access';

/**
 * HRMS ▸ the module's workspaces, as data.
 *
 * A WORKSPACE is a job somebody sits down to do: hiring one person, onboarding them. Each
 * owns a set of screens, grouped into PHASES, and renders as one tab strip
 * (common/HrmsWorkspaceBar) so the whole job is reachable without returning to the sidebar.
 *
 * -- Why onboarding is its own workspace ---------------------------------------------
 * It used to be the last phase of the hiring strip, which made it look like the tail of
 * Internal Hiring. It is not: onboarding runs for a client-track joiner exactly as it does
 * for a Sparsh Magic one, and a screen that serves both tracks cannot live inside one of
 * them. Lifting it out is also what lets the sidebar carry ONE Onboarding entry instead of
 * six, which is the point of a workspace in the first place.
 *
 * -- Why exit is NOT a workspace -----------------------------------------------------
 * Resignation, notice, handover, clearance and Full & Final Settlement are STAGES OF ONE
 * CASE, not separate screens — Exit Management already shows them as one record's
 * lifecycle. A strip whose tabs all opened the same record from different angles would be
 * the "five doors into one room" this module rejects elsewhere. Exit stays a single page.
 *
 * Every tab names the capability its own route requires, mirroring `_require(...)` in
 * backend/app/routes/hrms.py. A tab the caller cannot use is hidden, and a phase left with
 * no visible tabs disappears rather than showing an empty heading. This is a UX kindness on
 * top of a check the API already enforces, never a new security boundary.
 *
 * Each tab's label is the same words as the page title it opens (Pre-Joiners, Onboarding
 * Cases, Appointment & Agreements, Induction & Training, 30/90-Day Surveys, Probation).
 * Clicking "Pre-Joiners" and landing on a screen headed "Pre-boarding" makes somebody
 * wonder whether they arrived where they meant to.
 *
 * Data only, no JSX — so this module can be imported by components without breaking fast
 * refresh, the same split `internalKit.js` / `internalKit.jsx` uses.
 */

export const HIRING_WORKSPACE = {
  key: 'hiring',
  title: 'Internal Hiring',
  icon: Briefcase,
  home: '/hrms/internal-hiring',
  phases: [
    {
      key: 'requisition',
      label: 'Requisition & Planning',
      hint: 'Raise the role, get headcount and budget approved, define the position.',
      tabs: [
        // The way in: what is waiting on whom, across every open position.
        { label: 'Overview', to: '/hrms/internal-hiring', icon: LayoutDashboard, cap: CAP.REQUISITION_READ },
        { label: 'Headcount & Budget Approval', to: '/hrms/internal-requisitions', icon: ClipboardList, cap: CAP.REQUISITION_READ },
        { label: 'Job Descriptions', to: '/hrms/jd', icon: ScrollText, cap: CAP.JD_READ },
        { label: 'Scorecards', to: '/hrms/scorecards', icon: Target, cap: CAP.SCORECARD_READ },
      ],
    },
    {
      key: 'sourcing',
      label: 'Sourcing & Screening',
      hint: 'Publish the role, collect candidates, and screen them against the scorecard.',
      tabs: [
        { label: 'Job Postings', to: '/hrms/postings', icon: Megaphone, cap: CAP.POSTING_READ },
        { label: 'Candidates', to: '/hrms/candidates', icon: UserCircle, cap: CAP.CANDIDATE_READ },
        { label: 'HR Screening', to: '/hrms/screening', icon: ClipboardCheck, cap: CAP.CANDIDATE_SCREEN },
        // The telephonic screen (SOP step 7) sits between CV screening and the assessment,
        // and gates interview scheduling.
        { label: 'Phone Screen', to: '/hrms/telephonic-screening', icon: Phone, cap: CAP.TELEPHONIC_READ },
        { label: 'Assessments', to: '/hrms/assessments', icon: ListChecks, cap: CAP.ASSESSMENT_READ },
      ],
    },
    {
      key: 'interview',
      label: 'Interview & Selection',
      hint: 'Panel rounds, the shortlisting committee, and the checks before an offer.',
      tabs: [
        // No cap: GET /interviews is deliberately ungated on the API — "seeing the interview
        // you were booked for is an inherent right ... that must not be revocable by a
        // permission edit" (routes/hrms.py list_interviews docstring).
        { label: 'Interviews', to: '/hrms/interviews', icon: CalendarDays, cap: null },
        // Every requisition's Shortlisted-tier candidates on one screen instead of a column
        // buried in the Kanban board. Distinct from "Shortlist Committee": this is a VIEW,
        // that is the DECISION.
        { label: 'Shortlisted', to: '/hrms/shortlisted', icon: Star, cap: CAP.CANDIDATE_READ },
        // The shortlisting committee (SOP step 10) sits between the panel and the final
        // interview, and gates `Selected`.
        { label: 'Shortlist Committee', to: '/hrms/shortlist-reviews', icon: Users2, cap: CAP.SHORTLIST_READ },
        { label: 'References', to: '/hrms/reference-checks', icon: PhoneCall, cap: CAP.REFERENCE_READ },
        // Salary negotiation (SOP step 14) sits between the final interview and the offer.
        { label: 'Negotiation', to: '/hrms/negotiations', icon: Scale, cap: CAP.NEGOTIATION_READ },
      ],
    },
    {
      key: 'offer',
      label: 'Offer',
      hint: 'Verify the candidate, then approve and release the offer.',
      tabs: [
        // Verification comes FIRST because it gates the offer: `assert_background_cleared`
        // refuses to create one until every check has cleared and HR has signed the file off
        // (hrms_offer_service.create_offer). Listing Offers first read as though the offer
        // came first, which is the opposite of what the server allows.
        { label: 'Verification', to: '/hrms/background-checks', icon: ShieldCheck, cap: CAP.BACKGROUND_READ },
        { label: 'Offers', to: '/hrms/offers', icon: FileSignature, cap: CAP.OFFER_READ },
      ],
    },
    {
      key: 'reports',
      label: 'Reports',
      hint: 'How hiring is going, across every open position.',
      tabs: [
        { label: 'Reports', to: '/hrms/reports', icon: PieChart, cap: CAP.ANALYTICS_READ },
      ],
    },
  ],
};

export const ONBOARDING_WORKSPACE = {
  key: 'onboarding',
  title: 'Onboarding',
  icon: UserPlus,
  home: '/hrms/onboarding',
  phases: [
    {
      key: 'before',
      label: 'Before Day One',
      hint: 'From an accepted offer to somebody who turns up ready.',
      tabs: [
        // Document collection, verification, the joining checklist, the task groups and the
        // joining confirmation are deliberately NOT tabs: they are sections of ONE
        // onboarding case, and five tabs opening the same record from different angles
        // would be five doors into one room.
        { label: 'Pre-Joiners', to: '/hrms/preboarding', icon: HeartHandshake, cap: CAP.PREBOARDING_READ },
        { label: 'Onboarding Cases', to: '/hrms/onboarding', icon: UserPlus, cap: CAP.ONBOARDING_READ },
        // The letter is issued after the offer is accepted and before joining, and it is
        // where the NDA, Code of Conduct and policies are signed (§7.5 Stage 7).
        { label: 'Appointment & Agreements', to: '/hrms/appointments', icon: BadgeCheck, cap: CAP.APPOINTMENT_READ },
      ],
    },
    {
      key: 'after',
      label: 'After Joining',
      hint: 'Settling in, and the checks that decide whether it worked.',
      tabs: [
        { label: 'Induction & Training', to: '/hrms/orientation', icon: GraduationCap, cap: CAP.INDUCTION_READ },
        { label: '30/90-Day Surveys', to: '/hrms/pulse-surveys', icon: HeartPulse, cap: CAP.PULSE_READ },
        { label: 'Probation', to: '/hrms/probation', icon: CalendarClock, cap: CAP.PROBATION_READ },
      ],
    },
  ],
};


export const CLIENT_WORKSPACE = {
  key: 'client',
  title: 'Client Hiring',
  icon: Building2,
  home: '/hrms/client-hiring',
  /**
   * The PRO-fit track gets the SAME strip as Internal Hiring, with one difference that
   * matters: its tabs carry a `stage` instead of a route of their own.
   *
   * Client Hiring is deliberately ONE page — the eight stages swap a panel via `?stage=`
   * and the old per-stage routes redirect into it (see App.jsx). Eight separate pages made
   * one flow read as eight unrelated screens and threw the counts away on every click. So
   * the strip drives the query string: identical chrome, no re-split.
   *
   * A `stage` tab is matched on the query string rather than by path prefix, and the FIRST
   * visible one also owns the bare `/hrms/client-hiring` — which is what the board itself
   * falls back to when `?stage=` is absent. The two defaults have to agree or the strip
   * would highlight a tab the panel below is not showing.
   */
  phases: [
    {
      key: 'requirement',
      label: 'Requirement & Benchmark',
      hint: 'The client states the need; Sparsh checks it is fillable and agrees the bar.',
      tabs: [
        { label: 'Requisition', stage: 'requisitions', to: '/hrms/client-hiring?stage=requisitions', icon: ClipboardList, cap: CAP.CLIENT_REQUISITION_READ },
        { label: 'Position Scorecard', stage: 'scorecards', to: '/hrms/client-hiring?stage=scorecards', icon: Target, cap: CAP.CLIENT_SCORECARD_READ },
      ],
    },
    {
      key: 'sourcing',
      label: 'Sourcing & Screening',
      hint: 'Advertise, screen against the scorecard, share CVs, then assess.',
      tabs: [
        { label: 'Job Posting', stage: 'postings', to: '/hrms/client-hiring?stage=postings', icon: Megaphone, cap: CAP.CLIENT_POSTING_READ },
        { label: 'Sourcing & CV Share', stage: 'candidates', to: '/hrms/client-hiring?stage=candidates', icon: UserCircle, cap: CAP.CLIENT_CANDIDATE_READ },
        { label: 'Assessment', stage: 'assessments', to: '/hrms/client-hiring?stage=assessments', icon: ListChecks, cap: CAP.CLIENT_ASSESSMENT_READ },
      ],
    },
    {
      key: 'selection',
      label: 'Interview & Selection',
      hint: 'Sparsh runs the interview; the client watches the recording and selects.',
      tabs: [
        { label: 'Interview & Recording', stage: 'interviews', to: '/hrms/client-hiring?stage=interviews', icon: CalendarDays, cap: CAP.CLIENT_INTERVIEW_READ },
      ],
    },
    {
      key: 'close',
      label: 'Offer & Joining',
      hint: 'The client releases the offer and confirms joining; handover closes the role.',
      tabs: [
        { label: 'Offer', stage: 'offers', to: '/hrms/client-hiring?stage=offers', icon: FileSignature, cap: CAP.CLIENT_OFFER_READ },
        { label: 'Pre-boarding & Joining', stage: 'joinings', to: '/hrms/client-hiring?stage=joinings', icon: UserPlus, cap: CAP.CLIENT_JOINING_READ },
      ],
    },
  ],
};

export const WORKSPACES = [HIRING_WORKSPACE, CLIENT_WORKSPACE, ONBOARDING_WORKSPACE];

/** Every path any workspace strip carries. The sidebar uses this to avoid offering a
 *  second door to a screen a strip already owns. */
export const workspacePaths = (workspace) =>
  workspace.phases.flatMap((p) => p.tabs.map((t) => t.to));
