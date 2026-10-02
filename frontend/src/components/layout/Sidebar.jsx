import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  Archive,
  LayoutDashboard, Users, Briefcase, CheckSquare,
  Settings, Building2,
  MessageSquare, LogOut, Layers, Copy, Calendar, Sparkles, PlayCircle, Target, BarChart3, Library, X,
  Forward, Bell, Trash2, ChevronDown, Activity, CalendarDays, Database, LayoutGrid,
  Gauge, GitBranch, AlertTriangle, UserCog, ListChecks, ScrollText, UserCircle, ClipboardList, ClipboardCheck, Link2,
  Award, SlidersHorizontal, FolderOpen, FileCog, CalendarClock, ShieldAlert,
  // ── Phase INT-2 ── the remaining Internal Recruitment SOP surfaces.
  HeartHandshake, Bookmark, Scale, Mail,
  // ── Phase EXIT-1 ── Exit Management. Not LogOut — that icon is already the literal
  // sign-out control further down this file, and reusing it here for "someone else is
  // leaving the company" would read as the wrong action entirely.
  UserMinus,
  // ── Phase ATT-1 ── Attendance & Leave. Clock (daily capture) and CalendarCheck (leave
  // approval) rather than CalendarDays/CalendarClock, which already mean "a calendar of
  // events" and "Probation" respectively elsewhere in this file.
  Clock, CalendarCheck,
  // ── Phase MOVE-1 ── Employee Movements & Discipline. GitBranch is already imported above
  // (used for TPMS's Implementation Tracker) and is reused here — a movement literally is a
  // person's record forking into a new state with the old one kept as history.
  // ── Phase PAY-1 ── Payroll, Salary Advance & Variable Pay. Wallet is not yet imported
  // elsewhere in this file.
  Wallet,
  // ── Phase PIP-1 ── Performance Improvement Plan.
  TrendingDown,
  // The Onboarding workspace. UserPlus is "a new person joining", which is the
  // whole of what that workspace covers.
  UserPlus,
  // Notification Templates.
  BellRing,
  // ── Phase ORIENT-1 ── Orientation & Training.
  GraduationCap,
  // ── Phase PULSE-1 ── 30/90-Day Pulse Survey.
  HeartPulse,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { canAccessTaskManagement } from '../../utils/taskAccess';
import { canAccessTpms } from '../../features/tpms/access';
import { canAccessHrms, isClientTrackUser } from '../../features/hrms/access';

/**
 * The submodules a given viewer actually sees, headings included.
 *
 * A `{ section: 'Time & Pay' }` marker is a heading, not a link. HRMS is 22 entries long
 * and a flat run of 22 reads as one undifferentiated list you have to scan end to end;
 * broken into named groups it reads as six short ones you can skip past.
 *
 * Headings are dropped when nothing under them survives the role and track filters —
 * otherwise a non-admin would see a "Setup" heading with nothing beneath it, which
 * advertises screens they cannot open. That means filtering the LINKS first and pruning
 * the headings afterwards, never the other way round.
 */
const visibleSubmodules = (submodules, user, clientTrackOnly) => {
  // The client-track rule belongs to the module that DECLARES it, not to the sidebar at
  // large. `clientTrackOnly` is one flag for the whole viewer, so applying it everywhere
  // filtered every module's submodules down to the ones marked `clientTrack` — a mark that
  // exists on a single HRMS entry. Other modules therefore lost their entire drawer and
  // rendered a parent that opens onto nothing (IRM, for one, which client roles may use).
  // Honouring it only where a group actually uses it keeps HRMS exactly as it was.
  const groupUsesClientTrack = submodules.some((sub) => sub.clientTrack);
  const restrictToClientTrack = clientTrackOnly && groupUsesClientTrack;
  const kept = submodules.filter((sub) => (
    sub.section
      || ((!sub.roles || sub.roles.includes(user?.role))
        // A client company's user holds CLIENT_TRACK_CAPS and nothing else, so every
        // entry but Client Hiring leads to a screen the API answers 403. Offering them a
        // full HRMS menu would be a list of doors that do not open.
        && (!restrictToClientTrack || sub.clientTrack))
  ));
  return kept.filter((sub, i) => {
    if (!sub.section) return true;
    const next = kept[i + 1];
    return !!next && !next.section;   // a heading with no link under it is not a heading
  });
};
import { HIRING_WORKSPACE, ONBOARDING_WORKSPACE, workspacePaths }
  from '../../features/hrms/common/hrmsWorkspaces';
import { canManage as canManageLeadershipCycle } from '../../features/tpms/leadership/leadershipUtils';
import { canOpenNotificationTemplates } from '../../utils/notifyTemplateAccess';

import logo1 from '../../assets/Sparsh Magic  Logo PNG1.png';
import logo2 from '../../assets/Sparsh Magic  Logo PNG2.png';
import logo3 from '../../assets/Sparsh Magic white  Logo PNG3.png';
import { useTheme } from '../../context/ThemeContext';

// `onWidthChange` lets the page layout reserve exactly as much room as the sidebar currently
// occupies. Without it the rail reserved a fixed 72px while the sidebar expanded to 240px on
// hover, so the expanded panel sat on top of the page content (see PrivateRoute).
const Sidebar = ({ isMobileOpen, setIsMobileOpen, onWidthChange }) => {
  const { user, logout } = useAuth();
  const { theme } = useTheme();
  const location = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [isMobile, setIsMobile] = useState(false);
  // Tracks which dropdown groups (Task Management, TPMS, …) are expanded, keyed by link name.
  const [openMenus, setOpenMenus] = useState({});
  const toggleMenu = (name) => setOpenMenus((m) => ({ ...m, [name]: !m[name] }));

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // TPMS submodules mirror the panel navs (features/tpms/*Layout.jsx). Role decides which
  // panel a user lands on: superadmin/admin → Admin panel, every other internal → SMOPS.
  const isTpmsAdminUser = ['superadmin', 'admin'].includes(user?.role);
  const isTpmsClientUser = ['clientadmin', 'clientuser'].includes(user?.role);
  // Who may run a Leadership Score cycle from the client side — HR or the client admin.
  // Reuses the same predicate the Leadership pages use, so the menu can never offer a page
  // the page itself will refuse.
  const canManageLeadership = canManageLeadershipCycle(user);
  // Client-side users share the SMOPS submodules (Dashboard, HOD Activity, Employee Task,
  // Review Report, My Profile).
  //
  // There is deliberately NO Forms group here any more. A form is not something a user browses
  // to: when a form-scored activity is scheduled, each respondent is mailed their own unique,
  // expiring link and fills it on a public page (/f/<token>) without signing in. Delivery and
  // completion are tracked in TPMS ▸ Form Mail Logs.
  const tpmsClientForms = [
    { name: 'Dashboard', path: '/tpms/smops', icon: LayoutDashboard, end: true },
    { name: 'Calendar', path: '/tpms/smops/calendar', icon: CalendarDays },
    { name: 'HOD Activity', path: '/tpms/smops/hod-activity', icon: Activity },
    { name: 'Employee Task', path: '/tpms/smops/tasks', icon: ClipboardList },
    { name: 'Review Report', path: '/tpms/smops/reviews', icon: BarChart3 },
    // Leadership Score — every client-side user gets the result view; the page itself
    // scopes what they see (HR: all leaders, manager: direct reports, leader: their own).
    //
    // HR and the client admin also RUN the cycle, and those pages had no entry here at all —
    // the routes existed and the API allowed them, so the work was reachable only by typing
    // the URL. They are listed for whoever `canManage` admits (mirrors _can_manage on the
    // server: HR + clientadmin), and no wider: choosing the feedback panel is HR-only, which
    // the Leaders & Givers page and the API both still enforce on their own.
    canManageLeadership
      ? {
        name: 'Leadership Score', path: '/tpms/smops/leadership', icon: Award,
        children: [
          { name: 'Results', path: '/tpms/smops/leadership', icon: BarChart3, end: true },
          { name: 'Cycles', path: '/tpms/smops/leadership/cycles', icon: CalendarDays },
          { name: 'Leaders & Givers', path: '/tpms/smops/leadership/subjects', icon: UserCog },
          // The WhatsApp invitation template lives in Notification Templates.
        ],
      }
      : { name: 'Leadership Score', path: '/tpms/smops/leadership', icon: Award, end: true },
  ];
  const tpmsSubmodules = isTpmsClientUser
    ? tpmsClientForms
    : isTpmsAdminUser
    ? [
        { name: 'Admin View', path: '/tpms/admin', icon: LayoutDashboard, end: true },
        { name: 'Calendar', path: '/tpms/admin/calendar', icon: CalendarDays },
        { name: 'OM (SMOps) View', path: '/tpms/admin/om', icon: Gauge },
        { name: 'Client View', path: '/tpms/admin/clients', icon: Building2 },
        { name: 'Implementation Tracker', path: '/tpms/admin/implementation', icon: GitBranch },
        { name: 'Escalations', path: '/tpms/admin/escalations', icon: AlertTriangle },
        { name: 'HOD View', path: '/tpms/admin/hod', icon: UserCog },
        { name: 'Employee Tasks', path: '/tpms/admin/employee-tasks', icon: ListChecks },
        { name: 'Activities', path: '/tpms/admin/activities', icon: ClipboardList },
        { name: 'Departments', path: '/tpms/admin/departments', icon: Building2 },
        { name: 'Reminder Rules', path: '/tpms/admin/reminder-rules', icon: AlertTriangle },
        { name: 'Form Questions', path: '/tpms/admin/form-questions', icon: ClipboardCheck },
        { name: 'Form Links', path: '/tpms/admin/form-links', icon: Link2 },
        // Leadership Score (additive group — the entries above are unchanged).
        {
          name: 'Leadership Score', path: '/tpms/admin/leadership', icon: Award,
          children: [
            { name: 'Cycles', path: '/tpms/admin/leadership', icon: CalendarDays, end: true },
            { name: 'Leaders & Givers', path: '/tpms/admin/leadership/subjects', icon: UserCog },
            { name: 'Questions', path: '/tpms/admin/leadership/questions', icon: ClipboardCheck },
            { name: 'Results', path: '/tpms/admin/leadership/report', icon: BarChart3 },
          ],
        },
        { name: 'Logs Report', path: '/tpms/admin/logs', icon: ScrollText },
        { name: 'Review Report', path: '/tpms/admin/reviews', icon: BarChart3 },
      ]
    : [
        { name: 'Dashboard', path: '/tpms/smops', icon: LayoutDashboard, end: true },
        { name: 'Calendar', path: '/tpms/smops/calendar', icon: CalendarDays },
        { name: 'HOD Activity', path: '/tpms/smops/hod-activity', icon: Activity },
        { name: 'Employee Task', path: '/tpms/smops/tasks', icon: ClipboardList },
        { name: 'Review Report', path: '/tpms/smops/reviews', icon: BarChart3 },
        { name: 'Leadership Score', path: '/tpms/smops/leadership', icon: Award, end: true },
      ];

  // HRMS submodules. The masters (Departments / Designations) are only meaningful to users
  // who can administer them, so they are hidden from an Implementor-level client user —
  // the API would refuse those screens anyway (see utils/hrms_access.ROLE_CAPABILITIES).
  const isHrmsAdminUser = ['superadmin', 'admin', 'clientadmin'].includes(user?.role)
    || ['MD', 'HR'].includes((user?.governance_role || '').trim().toUpperCase());
  // The hiring pipeline's ten stages are deliberately ABSENT here — they live in the
  // workspace tab strip (features/hrms/common/HrmsWorkspaceBar). Listing them in both
  // places put the same links twice and made HRMS the longest group in the sidebar.
  //
  // '/hrms' (Overview) is in neither nav by request. The route still resolves — HrmsGate
  // redirects there — it simply has no menu entry pointing at it.
  //
  // What is left is the way IN plus the screens the strip does not carry. `Recruitment`
  // stays highlighted anywhere in the workspace (see `match`), so the sidebar still shows
  // which part of HRMS you are in after the tabs have moved you off the requisition screen.
  // Paths a workspace TAB STRIP already carries (features/hrms/common/hrmsWorkspaces.js).
  // Anything in one of these lists must NOT also be a sidebar submodule -- a screen
  // reachable from both is two doors into one room, and the two navigations then disagree
  // about where it lives.
  //
  // These are DERIVED from the strips rather than retyped. The hand-kept copy that used to
  // sit here had drifted four paths behind the real strip, which is exactly how Pre-Joiners,
  // Induction, 30/90-Day Surveys and Probation ended up in both navigations at once. A list
  // maintained in two places is a list that will disagree with itself.
  const HIRING_PATHS = workspacePaths(HIRING_WORKSPACE);
  const ONBOARDING_PATHS = workspacePaths(ONBOARDING_WORKSPACE);
  // `/hrms/requisitions` is the retired "both tracks" list; App.jsx redirects it to the
  // internal board, so the entry has to stay lit while that redirect is in flight.
  const inHiring = (p) => p === '/hrms/requisitions'
    || HIRING_PATHS.some((r) => p === r || p.startsWith(`${r}/`));
  const inOnboarding = (p) => ONBOARDING_PATHS.some((r) => p === r || p.startsWith(`${r}/`));

  // Ordered to follow the BA doc's own Employee Lifecycle (§5: Workforce Need -> MRF ->
  // Recruitment -> Offer -> Pre-boarding -> Joining -> Probation -> Active Employment ->
  // Growth -> Conduct -> Exit Initiation -> Notice/Handover -> F&F -> Closure), not by
  // build phase. Previously this list was ordered roughly by the phase that added each
  // entry, which put Probation and Exit Management ahead of Attendance/Payroll and
  // Orientation near the very end — the opposite of the order a lifecycle reads in.
  // True for a client company's own user: they reach Client Hiring and nothing else.
  const clientTrackOnly = isClientTrackUser(user);

  const hrmsSubmodules = [
    { section: 'Overview' },
    { name: 'Dashboard', path: '/hrms/dashboard', icon: BarChart3 },
    { name: 'Employees', path: '/hrms/employees', icon: Users },

    // ── Stages 02-05: MRF -> Recruitment -> Offer ──
    // Recruitment is visible to everyone: any HRMS user may raise a requisition, and whoever
    // raises one becomes its hiring manager (the module's documented design intent). Opens
    // the workspace tab strip, which carries every pipeline stage from requisition through
    // Appointments (see HrmsWorkspaceBar.jsx) — Talent Pool below is a sourcing surface that
    // feeds the same pipeline without being a stage in it.
    { section: 'Hiring' },
    // ── Internal Hiring ── ONE entry for the whole internal process. It opens the
    // hiring board, whose tab strip carries every stage from requisition through
    // probation, so the stages do not each need a sidebar line of their own. Named to
    // match Client Hiring below: two tracks, two entries, the same shape.
    {
      name: 'Internal Hiring', path: '/hrms/internal-hiring', icon: ClipboardList,
      match: inHiring,
    },
    // ── Client Hiring (PRO-fit) ── the OTHER hiring track, deliberately its own entry
    // rather than a filter inside Recruitment. Sparsh hiring its own staff and Sparsh
    // recruiting for a client are different processes with different approvers, and one
    // menu item covering both would invite exactly the mixing this track exists to avoid.
    {
      name: 'Client Hiring', path: '/hrms/client-hiring', icon: Building2,
      // Everything under /hrms/client- EXCEPT the pool, which is its own entry below.
      // Two entries claiming one path would light up together.
      match: (p) => p.startsWith('/hrms/client-') && p !== '/hrms/client-candidate-pool',
      // The one HRMS surface a client company's own people may reach. See clientTrack
      // below for why that matters to this list.
      clientTrack: true,
    },
    // ── Rejected & available candidates ── people a client passed on, kept for the next
    // role that suits them. Its own entry because it is not part of any one client's
    // flow; Sparsh-side only, and the endpoint refuses a client-side caller anyway.
    {
      name: 'Available Candidates', path: '/hrms/client-candidate-pool', icon: Archive,
      roles: ['superadmin', 'admin', 'coach', 'staff'],
    },
    // ── Phase INT-2 ── a search across candidates rather than a step in one hire, so it
    // is not a tab on the hiring strip and keeps its own entry.
    { name: 'Talent Pool', path: '/hrms/talent-pool', icon: Bookmark },

    { section: 'Joining' },
    // ── Onboarding ── ONE entry for the whole joining journey, the same shape as the two
    // hiring entries above. It opens the onboarding board, whose tab strip carries
    // Pre-Joiners, Appointment & Agreements, Induction, the 30/90-Day Surveys and
    // Probation, so none of those needs a sidebar line of its own.
    //
    // Its own workspace rather than the tail of Internal Hiring because onboarding runs
    // identically for a client-track joiner and a Sparsh Magic one — a screen serving both
    // tracks cannot sit inside one of them. (Exit is NOT a workspace: resignation, notice,
    // handover, clearance and F&F are stages of one case, and Exit below already shows
    // them as one record's lifecycle.)
    {
      name: 'Onboarding', path: '/hrms/onboarding', icon: UserPlus,
      match: inOnboarding,
    },

    // Phase 11-R, Item 2 — the document register has ONE home, and it is the sidebar (not a
    // hiring stage, so deliberately absent from the workspace strip). KYC/joining documents
    // are verified here during onboarding, and every document type stays reachable from the
    // same place afterward.
    { name: 'Documents', path: '/hrms/documents', icon: FolderOpen },


    // ── Stage 09: Active Employment ──
    // ── Phase ATT-1 ── daily capture, regularisation, Outdoor Duty and monthly closure.
    { section: 'Time & Pay' },
    { name: 'Attendance', path: '/hrms/attendance', icon: Clock },
    { name: 'Leave & C-Off', path: '/hrms/leave', icon: CalendarCheck },
    // ── Phase PAY-1 ── component-driven payroll, salary advance and variable pay.
    { name: 'Payroll', path: '/hrms/payroll', icon: Wallet },

    // ── Stages 10-11: Growth / Conduct ──
    // ── Phase PIP-1 ── objectives, support, reviews and outcome for a Performance
    // Improvement Plan.
    { section: 'Performance & Conduct' },
    { name: 'PIP', path: '/hrms/pip', icon: TrendingDown },
    // ── Phase MOVE-1 ── promotions/transfers (Growth) and discipline/absconding/retirement
    // alerts (Conduct) — one screen covers both stages.
    { name: 'Movements & Discipline', path: '/hrms/movements', icon: GitBranch },

    // ── Cross-cutting reference, used throughout Active Employment/Growth ──
    // ── Phase LETTER-1 ── controlled correspondence (confirmation, revision, warning, etc.)
    // — HR manages the template register and issues letters, an employee reads their own.
    { name: 'Letters', path: '/hrms/letters', icon: FileCog },

    // ── Stages 12-15: Exit Initiation -> Notice/Handover -> F&F -> Closure ──
    { section: 'Exit & Exceptions' },
    // ── Phase EXIT-1 ── `match` also lights this up on the detail route.
    {
      name: 'Exit Management', path: '/hrms/separations', icon: UserMinus,
      match: (p) => p === '/hrms/separations' || p.startsWith('/hrms/separations/'),
    },

    // ── Governance, not a lifecycle stage: an internal-hiring control surface. ──
    { name: 'Exceptions', path: '/hrms/exceptions', icon: ShieldAlert },
    ...(isHrmsAdminUser ? [
      { section: 'Setup' },
      { name: 'Departments', path: '/hrms/departments', icon: Building2 },
      { name: 'Designations', path: '/hrms/designations', icon: Briefcase },
      // No 'Clients' entry: a recruitment client IS a company, so it is maintained in the
      // Companies section. A second master here is the duplication this replaced.
      { name: 'Document Types', path: '/hrms/document-types', icon: FileCog },
      { name: 'Sanctioned Strength', path: '/hrms/sanctioned-strength', icon: Gauge },
      // ── Phase INT-2 ── admin-only masters. Salary bands are agreed annually with
      // Finance; the policy register records which version of the SOP governs (candidate
      // communications are managed in Notification Templates). The
      // capability checks are the real control -- this list only decides visibility.
      { name: 'Salary Bands', path: '/hrms/salary-bands', icon: Scale },
      // ── Phase INT-5 ── the per-company rule set: SLA targets, retention periods,
      // probation duration, reminder tiers and score bands. Governance, not a hiring
      // stage, so it stays out of the workspace tab strip. The `settings.write`
      // capability is the real control -- this list only decides visibility.
      { name: 'HRMS Settings', path: '/hrms/settings', icon: SlidersHorizontal },
      // Policy Register, HR Policy Library, Audit Viewer and Role & Access were removed
      // from this list on 2026-09-23 at the user's request. Their ROUTES are untouched
      // (/hrms/policies, /hrms/policy-library, /hrms/audit, /hrms/access) and their
      // capability gates are unchanged -- they are simply not advertised in the nav.
      // Re-add an entry here if one of them needs a door again.
    ] : []),
  ];

  const links = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'] },
    { name: 'Companies', path: '/companies', icon: Building2, roles: ['superadmin'], permissionKey: 'companies' },
    { name: 'Batches', path: '/batches', icon: Layers, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'batches' },
    { name: 'Session Templates', path: '/session-templates', icon: Copy, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'templates' },
    { name: 'User Management', path: '/admin/users', icon: Users, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'users' },
    { name: 'Training Roadmap', path: '/company-portal', icon: Target, roles: ['clientadmin', 'clientuser'] },
    { name: 'Live Sessions', path: '/sessions', icon: PlayCircle, roles: ['clientadmin', 'clientuser'] },
    { name: 'My Progress', path: '/my-reports', icon: BarChart3, roles: ['clientadmin', 'clientuser'] },
    { name: 'Organization Result Matrix (ORM)', path: '/orm', icon: Database, roles: ['clientadmin'], requiresOrm: true },
    { name: 'ORM Sheet', path: '/orm/sheet', icon: CheckSquare, roles: ['clientadmin', 'clientuser'], requiresOrm: true },
    {
      // IRM — Individual Result Matrix. Internal staff pick a company; a clientadmin sees
      // their own roster, a clientuser only their own score. Setup (the weightage column)
      // is internal staff only — client-side users read the weightages on the scoreboard.
      name: 'Individual Result Matrix (IRM)', path: '/irm', icon: Gauge,
      roles: ['superadmin', 'admin', 'clientadmin', 'clientuser'],
      submodules: [
        { name: 'Scores', path: '/irm', icon: Gauge, end: true },
        { name: 'Setup', path: '/irm/setup', icon: SlidersHorizontal, roles: ['superadmin', 'admin'] },
      ],
    },
    { name: 'Team', path: '/team', icon: Users, roles: ['clientadmin'] },
    { name: 'Calendar', path: '/calendar', icon: Calendar, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'], permissionKey: 'calendar' },
    {
      // Internal-Sparsh-only module — visibility governed by canAccessTaskManagement (not a
      // plain role list) so client-side users never see it. See utils/taskAccess.js.
      name: 'Task Management', path: '/tasks', icon: CheckSquare,
      roles: [], visibleFn: canAccessTaskManagement,
      submodules: [
        { name: 'Dashboard', path: '/tasks', icon: LayoutDashboard, end: true },
        { name: 'My Tasks', path: '/tasks/my', icon: CheckSquare },
        { name: 'Delegated Tasks', path: '/tasks/delegated', icon: Forward },
        { name: 'Subscribed Tasks', path: '/tasks/subscribed', icon: Bell },
        { name: 'All Tasks', path: '/tasks/all', icon: Layers },
        { name: 'Holiday', path: '/tasks/holiday', icon: CalendarDays, roles: ['superadmin', 'admin'] },
        { name: 'Activity', path: '/tasks/activity', icon: Activity },
        { name: 'Deleted Tasks', path: '/tasks/deleted', icon: Trash2 },
        // Delivery ledger for task notifications (templates live in Notification Templates) —
        // admin-only, matching the endpoint's own gate.
        { name: 'Notification Logs', path: '/tasks/logs', icon: Mail, roles: ['superadmin', 'admin'] },
      ],
    },
    {
      // TPMS — internal-Sparsh-only. Renders as a dropdown (like Task Management); the
      // submodules deep-link into the role-appropriate panel (admin vs SMOPS).
      name: 'TPMS', path: '/tpms', icon: LayoutGrid,
      roles: [], visibleFn: canAccessTpms,
      submodules: tpmsSubmodules,
    },
    {
      // HRMS — opt-in per company (like TPMS). Visibility is governed by canAccessHrms
      // rather than a role list: internal Sparsh staff always, client-side users only
      // while their company's HRMS toggle is ON. See features/hrms/access.js.
      name: 'HRMS', path: '/hrms', icon: UserCog,
      roles: [], visibleFn: canAccessHrms,
      submodules: hrmsSubmodules,
    },
    {
      // Notification Templates — every Email and WhatsApp template in the application, in one
      // module. Shown to whoever could manage any of the template screens it replaced.
      name: 'Notification Templates', path: '/notification-templates', icon: BellRing,
      roles: [], visibleFn: canOpenNotificationTemplates,
      submodules: [
        { name: 'Email', path: '/notification-templates/email', icon: Mail },
        { name: 'WhatsApp', path: '/notification-templates/whatsapp', icon: MessageSquare },
      ],
    },
    { name: 'Reports', path: '/admin/reports', icon: BarChart3, roles: ['superadmin', 'admin'] },
    { name: 'Company Settings', path: '/settings', icon: Settings, roles: ['clientadmin'] },
    { name: 'Support Engine', path: '/gpt', icon: Sparkles, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'] },
    { name: 'Media Library', path: '/media', icon: Library, roles: ['superadmin', 'admin', 'coach', 'staff'] },
  ];

  const filteredLinks = links.filter(link => {
    // Links with a custom visibility predicate (e.g. Task Management) are gated solely by it.
    if (link.visibleFn) return link.visibleFn(user);

    const isClientRole = ['clientadmin', 'clientuser'].includes(user?.role);
    const isAdminLink = ['Companies', 'Batches', 'Session Templates', 'User Management'].includes(link.name);

    // If it's a client role, strictly hide admin links regardless of permissions
    if (isClientRole && isAdminLink) return false;

    // Hide ORM links when the company's ORM module is disabled (staff-controlled)
    if (link.requiresOrm && user?.orm_enabled === false) return false;

    // Default filtering logic
    const hasRole = link.roles.includes(user?.role);
    const hasPermission = link.permissionKey && user?.permissions?.[link.permissionKey]?.read;

    return hasRole || hasPermission;
  });

  const sidebarWidth = isMobile ? 240 : (isCollapsed ? 72 : 240);

  // Report the rail width the layout should reserve. On mobile the sidebar is an off-canvas
  // overlay with its own backdrop, so it reserves nothing.
  useEffect(() => {
    onWidthChange?.(isMobile ? 0 : sidebarWidth);
  }, [sidebarWidth, isMobile, onWidthChange]);

  // Auto-expand whichever dropdown group owns the current route.
  useEffect(() => {
    setOpenMenus((m) => {
      const next = { ...m };
      links.forEach((link) => {
        if (link.submodules && location.pathname.startsWith(link.path)) next[link.name] = true;
        // Auto-open any nested submodule group (e.g. TPMS ▸ Forms) that owns the route.
        (link.submodules || []).forEach((sub) => {
          if (sub.children && location.pathname.startsWith(sub.path)) next[`${link.name}::${sub.name}`] = true;
        });
      });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  return (
    <motion.aside
      initial={false}
      animate={{ width: sidebarWidth }}
      transition={{ type: 'spring', stiffness: 400, damping: 40 }}
      onMouseEnter={() => !isMobile && setIsCollapsed(false)}
      onMouseLeave={() => !isMobile && setIsCollapsed(true)}
      className={`h-screen fixed left-0 top-0 bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] flex flex-col z-50 overflow-hidden transform transition-transform duration-300 md:transition-none md:translate-x-0 ${isMobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
    >
      {/* Logo Header */}
      <div className={`p-5 py-6 flex items-center ${isCollapsed && !isMobile ? 'justify-center' : 'justify-between'}`}>
        <AnimatePresence mode="wait">
          {(!isCollapsed || isMobile) ? (
            <motion.div
              key="full-logo"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex items-center gap-3 w-full"
            >
              <div className="flex items-center gap-3">
                <img src={logo1} alt="Logo" className="w-8 h-8 object-contain" />
                <div className="flex flex-col">
                  <img src={theme === 'dark' ? logo3 : logo2} alt="Sparsh ERP" className="h-9 object-contain" />
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="icon-logo"
              className="w-10 h-10 flex items-center justify-center p-1"
            >
              <img src={logo1} alt="Logo" className="w-full h-full object-contain" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Main Links */}
      <nav className="flex-1 px-3 space-y-1 overflow-y-auto no-scrollbar">
        {filteredLinks.map((link) => {
          if (link.submodules) {
            const groupActive = location.pathname.startsWith(link.path);
            const isOpen = !!openMenus[link.name];
            return (
              <div key={link.path}>
                <button
                  type="button"
                  onClick={() => toggleMenu(link.name)}
                  className={`
                    group w-full flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
                    ${groupActive
                      ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                      : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                    ${(isCollapsed && !isMobile) ? 'justify-center' : ''}
                  `}
                >
                  <link.icon size={18} className="transition-transform group-hover:scale-105" />
                  {(!isCollapsed || isMobile) && (
                    <>
                      <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[13px] tracking-tight font-medium flex-1 text-left">
                        {link.name}
                      </motion.span>
                      <ChevronDown size={14} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    </>
                  )}
                  {(isCollapsed && !isMobile) && (
                    <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg">
                      {link.name}
                    </div>
                  )}
                </button>

                <AnimatePresence initial={false}>
                  {isOpen && (!isCollapsed || isMobile) && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden pl-4 space-y-1 mt-1"
                    >
                      {visibleSubmodules(link.submodules, user, clientTrackOnly)
                        .map((sub, subIndex) => {
                        // A heading, not a link.
                        if (sub.section) {
                          return (
                            <p key={`section-${sub.section}`}
                              className={`px-3 text-[10px] font-bold uppercase tracking-widest
                                text-[var(--text-muted)]/70 select-none
                                ${subIndex === 0 ? 'pt-0.5 pb-1' : 'pt-3 pb-1'}`}>
                              {sub.section}
                            </p>
                          );
                        }

                        const subLinkClass = ({ isActive }) => `
                          group flex items-center gap-3 pl-3 pr-2.5 py-2 rounded-lg transition-colors text-[12.5px]
                          ${isActive
                            ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                            : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                        `;

                        // Nested group (e.g. TPMS ▸ Forms ▸ Ownership/Culture/…)
                        if (sub.children) {
                          const nestedKey = `${link.name}::${sub.name}`;
                          const nestedOpen = !!openMenus[nestedKey];
                          const nestedActive = location.pathname.startsWith(sub.path);
                          return (
                            <div key={sub.path}>
                              <button
                                type="button"
                                onClick={() => toggleMenu(nestedKey)}
                                className={`
                                  group w-full flex items-center gap-3 pl-3 pr-2.5 py-2 rounded-lg transition-colors text-[12.5px]
                                  ${nestedActive
                                    ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                                    : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                                `}
                              >
                                <sub.icon size={15} />
                                <span className="tracking-tight font-medium flex-1 text-left">{sub.name}</span>
                                <ChevronDown size={13} className={`transition-transform ${nestedOpen ? 'rotate-180' : ''}`} />
                              </button>
                              <AnimatePresence initial={false}>
                                {nestedOpen && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="overflow-hidden pl-4 space-y-1 mt-1"
                                  >
                                    {sub.children.filter((c) => !c.roles || c.roles.includes(user?.role)).map((child) => (
                                      <NavLink
                                        key={child.path}
                                        to={child.path}
                                        end={child.end}
                                        onClick={() => { if (isMobile) setIsMobileOpen(false); }}
                                        className={subLinkClass}
                                      >
                                        <child.icon size={14} />
                                        <span className="tracking-tight font-medium">{child.name}</span>
                                      </NavLink>
                                    ))}
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </div>
                          );
                        }

                        return (
                          <NavLink
                            key={sub.path}
                            to={sub.path}
                            end={sub.end}
                            onClick={() => { if (isMobile) setIsMobileOpen(false); }}
                            // `match` lets one entry own a whole set of routes (HRMS ▸
                            // Recruitment covers the pipeline its tab strip navigates).
                            // Items without one keep NavLink's own matching exactly.
                            className={(state) => subLinkClass({
                              isActive: state.isActive
                                || (sub.match ? sub.match(location.pathname) : false),
                            })}
                          >
                            <sub.icon size={15} />
                            <span className="tracking-tight font-medium">{sub.name}</span>
                          </NavLink>
                        );
                      })}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          }

          return (
            <NavLink
              key={link.path}
              to={link.path}
              onClick={() => {
                if (isMobile) {
                  setIsMobileOpen(false);
                }
              }}
              className={({ isActive }) => `
                group flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
                ${isActive
                  ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                  : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                ${(isCollapsed && !isMobile) ? 'justify-center' : ''}
              `}
            >
              <link.icon size={18} className="transition-transform group-hover:scale-105" />
              {(!isCollapsed || isMobile) && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-[13px] tracking-tight font-medium"
                >
                  {link.name}
                </motion.span>
              )}
              {(isCollapsed && !isMobile) && (
                <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg">
                  {link.name}
                </div>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-[var(--sidebar-border)]">
        <button
          onClick={() => {
            logout();
            if (isMobile) {
              setIsMobileOpen(false);
            }
          }}
          className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)] transition-all ${(isCollapsed && !isMobile) ? 'justify-center' : ''}`}
        >
          <LogOut size={18} />
          {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Logout</span>}
        </button>

        <div className={`mt-4 p-2.5 rounded-xl bg-white shadow-sm flex items-center justify-center transition-all ${(isCollapsed && !isMobile) ? 'mx-1' : 'px-3'}`}>
          <a
            href="https://www.dtableanalytics.com/"
            target="_blank"
            rel="noopener noreferrer"
            className={`font-black text-blue-600 text-center leading-tight hover:underline ${(isCollapsed && !isMobile) ? 'text-[10px]' : 'text-[11px]'}`}
          >
            {(isCollapsed && !isMobile) ? 'DTA' : 'Powered by D Table Analytics'}
          </a>
        </div>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
