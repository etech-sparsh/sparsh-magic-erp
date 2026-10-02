import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { NotificationProvider } from './context/NotificationContext';
import NotificationModal from './components/common/NotificationModal';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import CompanyManagement from './pages/CompanyManagement';
import CompanyDetails from './pages/CompanyDetails';
import MemberPortal from './pages/MemberDashboard';
import TeamManagement from './pages/TeamManagement';
import MemberDetails from './pages/MemberDetails';
import BatchManagement from './pages/BatchManagement';
import BatchDetails from './pages/BatchDetails';
import QuarterDetails from './pages/QuarterDetails';
import SessionTemplateManagement from './pages/SessionTemplateManagement';
import SessionTemplateDetails from './pages/SessionTemplateDetails';
import SessionDetails from './pages/SessionDetails';
import ContentViewer from './pages/ContentViewer';
import CalendarPage from './pages/CalendarPage';
import UserManagement from './pages/UserManagement';
import UserDetails from './pages/UserDetails';
import SettingsPage from './pages/SettingsPage';
import ProfilePage from './pages/ProfilePage';
import GptProjects from './pages/GptProjects';
import GptEditor from './pages/GptEditor';
import GptChat from './pages/GptChat';
import GptAccessControl from './pages/GptAccessControl';
import LearnerSessions from './pages/LearnerSessions';
import CompanyPortal from './pages/CompanyPortal';
import AssessmentPlayer from './pages/AssessmentPlayer';
import MyReports from './pages/MyReports';
import ORMPage from './pages/ORM/ORMPage';
import ORMSetup from './pages/ORM/ORMSetup';
import ORMSheet from './pages/ORM/ORMSheet';
import IRMPage from './pages/IRM/IRMPage';
import IRMSetup from './pages/IRM/IRMSetup';
import MediaLibrary from './pages/MediaLibrary';
import TaskDashboard from './pages/TaskDashboard';
import MyTasks from './pages/MyTasks';
import DelegatedTasks from './pages/DelegatedTasks';
import SubscribedTasks from './pages/SubscribedTasks';
import AllTasks from './pages/AllTasks';
import TaskActivity from './pages/TaskActivity';
import TaskLogsReport from './pages/TaskLogsReport';
import Holiday from './pages/Holiday';
import DeletedTasks from './pages/DeletedTasks';
import NotificationTemplates from './pages/notifications/NotificationTemplates';
import ForgotPassword from './pages/ForgotPassword';
import PrivateRoute from './components/common/PrivateRoute';
import RequireTaskAccess from './components/common/RequireTaskAccess';
import ModulePlaceholder from './features/tpms/common/ModulePlaceholder';
import AdminView from './features/tpms/admin/pages/AdminView';
import OmSmopsView from './features/tpms/admin/pages/OmSmopsView';
import ImplementationTracker from './features/tpms/admin/pages/ImplementationTracker';
import ClientView from './features/tpms/admin/pages/ClientView';
import Escalations from './features/tpms/admin/pages/Escalations';
import LogsReport from './features/tpms/admin/pages/LogsReport';
import HodView from './features/tpms/admin/pages/HodView';
import EmployeeTasks from './features/tpms/admin/pages/EmployeeTasks';
import ActivityManagement from './features/tpms/admin/pages/ActivityManagement';
import DepartmentManagement from './features/tpms/admin/pages/DepartmentManagement';
import ClientActivityCalendar from './features/tpms/admin/pages/ClientActivityCalendar';
import ReminderRuleAdmin from './features/tpms/admin/pages/ReminderRuleAdmin';
import FormQuestionAdmin from './features/tpms/admin/pages/FormQuestionAdmin';
import FormLinks from './features/tpms/admin/pages/FormLinks';
import ReviewReport from './features/tpms/common/ReviewReport';
// TPMS ▸ Leadership Score (additive — no existing TPMS route is changed).
import LeadershipCycles from './features/tpms/admin/pages/LeadershipCycles';
import LeadershipSubjects from './features/tpms/admin/pages/LeadershipSubjects';
import LeadershipQuestions from './features/tpms/admin/pages/LeadershipQuestions';
import LeadershipReport from './features/tpms/common/LeadershipReport';
import LeadershipFormPage from './features/tpms/leadership/LeadershipFormPage';
import { CompanyProvider } from './features/tpms/smops/CompanyContext';
import SmopsDashboard from './features/tpms/smops/pages/SmopsDashboard';
import HodActivity from './features/tpms/smops/pages/HodActivity';
import SmopsEmployeeTask from './features/tpms/smops/pages/SmopsEmployeeTask';
import TpmsGate, { RequireTpms } from './features/tpms/TpmsGate';
import HrmsGate, { RequireHrms } from './features/hrms/HrmsGate';
import HrmsHome from './features/hrms/HrmsHome';
import HrmsWorkspace from './features/hrms/HrmsWorkspace';
import EmployeeDirectory from './features/hrms/people/EmployeeDirectory';
import EmployeeProfile from './features/hrms/people/EmployeeProfile';
// ── Phase 360-1 — Employee 360° (§6) ──
import Employee360 from './features/hrms/people/Employee360';
import MasterManager from './features/hrms/people/MasterManager';
import JdLibrary from './features/hrms/recruitment/JdLibrary';
import PostingList from './features/hrms/recruitment/PostingList';
import CandidatePipeline from './features/hrms/recruitment/CandidatePipeline';
import ShortlistedCandidates from './features/hrms/recruitment/ShortlistedCandidates';
import ScreeningBoard from './features/hrms/recruitment/ScreeningBoard';
import AssessmentBoard from './features/hrms/recruitment/AssessmentBoard';
import InterviewBoard from './features/hrms/recruitment/InterviewBoard';
import OfferBoard from './features/hrms/recruitment/OfferBoard';
import OnboardingBoard from './features/hrms/recruitment/OnboardingBoard';
// Eagerly imported, unlike ReportsDashboard below. These pages share almost every
// dependency with the other (eager) HRMS routes and use NO chart library, so lazy-loading
// them bought ~15 kB of deferral while forcing the bundler to re-draw its shared-chunk
// boundaries -- which moved ~111 kB of existing code INTO the main chunk. Measured, see
// PHASE_10_REPORT section 7.
import RecruitmentDashboard from './features/hrms/analytics/RecruitmentDashboard';
import RecruitmentReports from './features/hrms/analytics/RecruitmentReports';
import ApplyPage from './pages/hrms/public/ApplyPage';
import ClientApplyPage from './pages/hrms/public/ClientApplyPage';
import AssessPage from './pages/hrms/public/AssessPage';
import OfferPage from './pages/hrms/public/OfferPage';
import OnboardPage from './pages/hrms/public/OnboardPage';
// ── Phase 11-R — recruitment review enhancements ──
import DocumentCenter from './features/hrms/documents/DocumentCenter';
import DocumentTypeManager from './features/hrms/documents/DocumentTypeManager';
import AppointmentBoard from './features/hrms/recruitment/AppointmentBoard';
import SanctionedStrength from './features/hrms/people/SanctionedStrength';
// ── Internal (in-house) recruitment track ──
import InternalRequisitionList from './features/hrms/internal/InternalRequisitionList';
import InternalRequisitionDetail from './features/hrms/internal/InternalRequisitionDetail';
import InternalHiringDashboard from './features/hrms/internal/InternalHiringDashboard';
import ClientHiringDashboard from './features/hrms/client/ClientHiringDashboard';
import ClientRecruitmentAnalytics from './features/hrms/client/ClientRecruitmentAnalytics';
import ClientCandidatePool from './features/hrms/client/ClientCandidatePool';
import ScorecardLibrary from './features/hrms/internal/ScorecardLibrary';
import ReferenceCheckBoard from './features/hrms/internal/ReferenceCheckBoard';
import TelephonicBoard from './features/hrms/internal/TelephonicBoard';
import NegotiationBoard from './features/hrms/internal/NegotiationBoard';
// Phase 12 - the client hiring track.
import BackgroundCheckBoard from './features/hrms/recruitment/BackgroundCheckBoard';
import HrmsSettings from './features/hrms/internal/HrmsSettings';
import ProbationBoard from './features/hrms/internal/ProbationBoard';
import ExceptionLog from './features/hrms/internal/ExceptionLog';
import AppointmentPage from './pages/hrms/public/AppointmentPage';
// ── Phase INT-2 — the remaining Internal Recruitment SOP controls ──
import ShortlistCommittee from './features/hrms/internal/ShortlistCommittee';
import PreboardingBoard from './features/hrms/internal/PreboardingBoard';
import TalentPool from './features/hrms/internal/TalentPool';
import PolicyRegister from './features/hrms/internal/PolicyRegister';
import PolicyLibrary from './features/hrms/policy/PolicyLibrary';
import SalaryBandManager from './features/hrms/people/SalaryBandManager';
import SurveyPage from './pages/hrms/public/SurveyPage';
// ── Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21) ──
import SeparationBoard from './features/hrms/exit/SeparationBoard';
import SeparationDetail from './features/hrms/exit/SeparationDetail';
// ── Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9) ──
import AttendanceBoard from './features/hrms/attendance/AttendanceBoard';
import LeaveBoard from './features/hrms/leave/LeaveBoard';
// ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
import MovementsBoard from './features/hrms/movements/MovementsBoard';
// ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
import PayrollBoard from './features/hrms/payroll/PayrollBoard';
// ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
import PipBoard from './features/hrms/pip/PipBoard';
// ── SM-HR-052 — Audit Viewer ──
import AuditViewer from './features/hrms/admin/AuditViewer';
// ── SM-HR-051 — User / Role / Permission Administration ──
import RoleAccessAdmin from './features/hrms/admin/RoleAccessAdmin';
// ── Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041) ──
import LetterBoard from './features/hrms/letters/LetterBoard';
// ── Phase ORIENT-1 — Orientation & Training (§22.3) ──
import OrientationBoard from './features/hrms/orientation/OrientationBoard';
// ── Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4) ──
import PulseSurveyBoard from './features/hrms/pulse/PulseSurveyBoard';
import TpmsCalendar from './features/tpms/calendar/TpmsCalendar';
import AssignedFormPage from './features/tpms/forms/AssignedFormPage';
import ClientDashboard from './features/tpms/client/ClientDashboard';
import AssistantWidget from './features/assistant';
import './index.css';
import { useAuth } from './context/AuthContext';
import { UploadProvider } from './context/UploadContext';

// Admin Reports & Analytics module (superadmin only) — lazy-loaded to keep it out
// of the main bundle since it pulls in extra recharts chart types.
const ReportsDashboard = lazy(() => import('./pages/ReportsDashboard'));
const DoerReportDetails = lazy(() => import('./pages/DoerReportDetails'));
const EmployeeReport = lazy(() => import('./pages/EmployeeReport'));

const RouteFallback = () => (
  <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading…</div>
);

// Blocks client-side users from ORM pages when their company's ORM module is off.
const OrmGuard = ({ children }) => {
  const { user } = useAuth();
  const isStaff = ['superadmin', 'admin'].includes(user?.role);
  if (user && !isStaff && user.orm_enabled === false) {
    return <Navigate to="/" />;
  }
  return children;
};

// The /tpms/smops Dashboard is shared: client-side users get the real ClientDashboard
// (their own company's Success-Measure scorecard); internal users keep the SMOPS view.
const TpmsDashboardIndex = () => {
  const { user } = useAuth();
  const isClient = ['clientadmin', 'clientuser'].includes(user?.role);
  return isClient ? <ClientDashboard /> : <SmopsDashboard />;
};

const AppRoutes = () => {
  const { user } = useAuth();

  return (
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      {/* Login owns the post-auth redirect. It must NOT be short-circuited with a Navigate to
          "/" here: the moment auth succeeds this element would re-render and send the user to
          the dashboard, discarding the deep link PrivateRoute stored (e.g. an assigned form at
          /f/<token>). Login redirects an already-signed-in visitor itself, so the behaviour for
          an ordinary /login visit is unchanged. */}
      <Route path="/login" element={<Login />} />

      {/* TPMS assigned form. Authenticated like every other page: an unauthenticated visitor is
          sent to /login and returned here afterwards (PrivateRoute stores the URL, Login reads
          it back). The token selects WHICH of the four forms renders — the backend also checks
          the signed-in user is the assignment's respondent, so a forwarded link opens nothing. */}
      <Route path="/f/:token" element={<PrivateRoute><AssignedFormPage /></PrivateRoute>} />

      {/* TPMS Leadership Score feedback form. Its own route so the existing /f/:token flow
          for the four original forms is untouched. Same two-check security model: the
          token must resolve to a live assignment AND the signed-in user must be its
          feedback giver, so a forwarded link opens nothing. */}
      <Route path="/lf/:token" element={<PrivateRoute><LeadershipFormPage /></PrivateRoute>} />
      <Route path="/forgot-password" element={<ForgotPassword />} />

      {/* ===========  PUBLIC HRMS (NO AUTHENTICATION)  ===========
          Candidate-facing. Mounted OUTSIDE PrivateRoute deliberately — wrapping these would
          redirect every applicant to /login. They render their own standalone chrome: an
          applicant is not a user of this ERP and must never see its navigation or modules. */}
      <Route path="/apply/:code" element={<ApplyPage />} />
      {/* A CLIENT company's vacancy. Separate from /apply above, which is Sparsh
          Magic's own recruitment — different tenant, different collection. */}
      <Route path="/hrms/client-apply/:code" element={<ClientApplyPage />} />
      <Route path="/assess/:code" element={<AssessPage />} />
      <Route path="/offer/:code" element={<OfferPage />} />
      <Route path="/onboard/:code" element={<OnboardPage />} />
      {/* Phase 11-R: the appointment letter a candidate acknowledges. Same anonymous
          treatment as the four above — an applicant is not a user of this ERP. */}
      <Route path="/appointment/:code" element={<AppointmentPage />} />
      {/* Phase INT-2: the new-hire experience survey. Anonymous in a stronger sense than
          the five above — the page is not told who the respondent is, because a survey that
          greets you by name is one you can screenshot beside your answers. */}
      <Route path="/survey/:code" element={<SurveyPage />} />

      <Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/dashboard" element={<Navigate to="/" />} />

      <Route path="/companies" element={<PrivateRoute><CompanyManagement /></PrivateRoute>} />
      <Route path="/companies/:companyId" element={<PrivateRoute><CompanyDetails /></PrivateRoute>} />
      <Route path="/members/:userId" element={<PrivateRoute><MemberPortal /></PrivateRoute>} />
      <Route path="/team" element={<PrivateRoute><TeamManagement /></PrivateRoute>} />
      <Route path="/batches" element={<PrivateRoute><BatchManagement /></PrivateRoute>} />
      <Route path="/batches/:batchId" element={<PrivateRoute><BatchDetails /></PrivateRoute>} />
      <Route path="/quarters/:quarterId" element={<PrivateRoute><QuarterDetails /></PrivateRoute>} />
      <Route path="/session-templates" element={<PrivateRoute><SessionTemplateManagement /></PrivateRoute>} />
      <Route path="/session-templates/:templateId" element={<PrivateRoute><SessionTemplateDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId" element={<PrivateRoute><SessionDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId/resource/:resourceId" element={<PrivateRoute><ContentViewer /></PrivateRoute>} />
      <Route path="/calendar" element={<PrivateRoute><CalendarPage /></PrivateRoute>} />

      {/* Task Management Module — internal-Sparsh-only (RequireTaskAccess) */}
      <Route path="/tasks" element={<PrivateRoute><RequireTaskAccess><TaskDashboard /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/my" element={<PrivateRoute><RequireTaskAccess><MyTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/delegated" element={<PrivateRoute><RequireTaskAccess><DelegatedTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/subscribed" element={<PrivateRoute><RequireTaskAccess><SubscribedTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/all" element={<PrivateRoute><RequireTaskAccess><AllTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/activity" element={<PrivateRoute><RequireTaskAccess><TaskActivity /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/holiday" element={<PrivateRoute><RequireTaskAccess><Holiday /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/deleted" element={<PrivateRoute><RequireTaskAccess><DeletedTasks /></RequireTaskAccess></PrivateRoute>} />
      {/* Templates are managed in Notification Templates now; the old address still lands there. */}
      <Route path="/tasks/templates" element={<Navigate to="/notification-templates/email?module=delegation" replace />} />
      {/* Email / WhatsApp delivery log for task notifications. The page itself is admin-only
          server-side; the sidebar entry is role-gated to match. */}
      <Route path="/tasks/logs" element={<PrivateRoute><RequireTaskAccess><TaskLogsReport /></RequireTaskAccess></PrivateRoute>} />

      {/* ===========  NOTIFICATION TEMPLATES  ===========
          Every Email and WhatsApp template in the application, in one module. Who sees which
          part is decided inside the page (utils/notifyTemplateAccess), mirroring the template
          screens it replaced. */}
      <Route path="/notification-templates" element={<Navigate to="/notification-templates/email" replace />} />
      <Route path="/notification-templates/email" element={<PrivateRoute><NotificationTemplates view="email" /></PrivateRoute>} />
      <Route path="/notification-templates/whatsapp" element={<PrivateRoute><NotificationTemplates view="whatsapp" /></PrivateRoute>} />
      {/* The Meta library and the Trigger picker open on the Email / WhatsApp pages themselves;
          these addresses from earlier builds land there. */}
      <Route path="/notification-templates/meta-templates" element={<Navigate to="/notification-templates/whatsapp" replace />} />
      <Route path="/notification-templates/triggers" element={<Navigate to="/notification-templates/email" replace />} />
      <Route path="/sessions" element={<PrivateRoute><LearnerSessions /></PrivateRoute>} />
      <Route path="/company-portal" element={<PrivateRoute><CompanyPortal /></PrivateRoute>} />
      <Route path="/my-reports" element={<PrivateRoute><MyReports /></PrivateRoute>} />
      <Route path="/orm" element={<PrivateRoute><OrmGuard><ORMPage /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/setup" element={<PrivateRoute><OrmGuard><ORMSetup /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/sheet" element={<PrivateRoute><OrmGuard><ORMSheet /></OrmGuard></PrivateRoute>} />

      {/* IRM — Individual Result Matrix. Scores are per person; the weightage setup is
          role-guarded inside the page (staff + clientadmin). */}
      <Route path="/irm" element={<PrivateRoute><IRMPage /></PrivateRoute>} />
      <Route path="/irm/setup" element={<PrivateRoute><IRMSetup /></PrivateRoute>} />


      <Route path="/media" element={<PrivateRoute><MediaLibrary /></PrivateRoute>} />

      {/* Admin Side: Staff Management */}
      <Route path="/admin/users" element={<PrivateRoute><UserManagement /></PrivateRoute>} />
      <Route path="/admin/users/:userId" element={<PrivateRoute><UserDetails /></PrivateRoute>} />

      {/* Admin Reports & Analytics (superadmin only; guarded inside the pages too) */}
      <Route path="/admin/reports" element={<PrivateRoute><ReportsDashboard /></PrivateRoute>} />
      <Route path="/admin/reports/employee/:userId" element={<PrivateRoute><EmployeeReport /></PrivateRoute>} />
      <Route path="/admin/reports/:doerId" element={<PrivateRoute><DoerReportDetails /></PrivateRoute>} />
      {/* ===================  TPMS  ===================
          Dynamic entry: /tpms auto-routes by role (admin → admin panel,
          everyone else → SMOPS). Panels are role-guarded via RequireTpms. */}
      <Route path="/tpms" element={<PrivateRoute><TpmsGate /></PrivateRoute>} />

      {/* TPMS ▸ ADMIN PANEL (superadmin / admin only) — rendered inside the main app
          layout; navigation is driven by the main Sidebar's TPMS dropdown. */}
      <Route path="/tpms/admin" element={<PrivateRoute><RequireTpms admin><Outlet /></RequireTpms></PrivateRoute>}>
        <Route index                 element={<AdminView />} />
        <Route path="om"             element={<OmSmopsView />} />
        <Route path="implementation" element={<ImplementationTracker />} />
        <Route path="clients"        element={<ClientView />} />
        <Route path="escalations"    element={<Escalations />} />
        <Route path="logs"           element={<LogsReport />} />
        <Route path="hod"            element={<HodView />} />
        <Route path="employee-tasks" element={<EmployeeTasks />} />
        <Route path="calendar"       element={<TpmsCalendar />} />
        <Route path="client-calendar" element={<ClientActivityCalendar />} />
        <Route path="activities"     element={<ActivityManagement />} />
        <Route path="departments"    element={<DepartmentManagement />} />
        {/* TPMS templates are managed in Notification Templates now. */}
        <Route path="mail-templates" element={<Navigate to="/notification-templates/email?module=tpms" replace />} />
        <Route path="reminder-rules" element={<ReminderRuleAdmin />} />
        <Route path="form-questions" element={<FormQuestionAdmin />} />
        <Route path="form-links"     element={<FormLinks />} />
        <Route path="reviews"        element={<ReviewReport />} />
        {/* Leadership Score — additive; the routes above are unchanged. */}
        <Route path="leadership"           element={<LeadershipCycles />} />
        <Route path="leadership/subjects"  element={<LeadershipSubjects />} />
        <Route path="leadership/questions" element={<LeadershipQuestions />} />
        {/* The invitation template (with its send log) is managed in Notification Templates. */}
        <Route path="leadership/whatsapp"  element={<Navigate to="/notification-templates/whatsapp?module=leadership" replace />} />
        <Route path="leadership/report"    element={<LeadershipReport />} />
      </Route>

      {/* TPMS ▸ SMOPS PANEL (any internal user) — rendered inside the main app layout.
          CompanyProvider supplies the shared company selection the SMOPS pages consume. */}
      <Route path="/tpms/smops" element={<PrivateRoute><RequireTpms><CompanyProvider><Outlet /></CompanyProvider></RequireTpms></PrivateRoute>}>
        <Route index                element={<TpmsDashboardIndex />} />
        {/* Calendar is shared by every TPMS audience — internal SMOPS users and
            client-side doers alike; the page itself gates the lifecycle actions by role. */}
        <Route path="calendar"      element={<TpmsCalendar />} />
        <Route path="hod-activity"  element={<HodActivity />} />
        <Route path="tasks"         element={<SmopsEmployeeTask />} />
        <Route path="reviews"       element={<ReviewReport title="Review Report" subtitle="Detailed evaluation and feedback for your companies." />} />
        {/* Leadership Score for the client/SMOPS side. The report is self-scoping: HR sees
            every enrolled leader, a manager their direct reports, a leader only their own. */}
        <Route path="leadership"           element={<LeadershipReport />} />
        <Route path="leadership/cycles"    element={<LeadershipCycles />} />
        <Route path="leadership/subjects"  element={<LeadershipSubjects />} />
        {/* HR and the MD reach the question bank to REVIEW and sign off a level — the
            page itself keeps the wording and weightages editable by staff only. A cycle
            cannot be closed until every level it scores has been signed off. */}
        <Route path="leadership/questions" element={<LeadershipQuestions />} />
        {/* The invitation template is managed in Notification Templates. */}
        <Route path="leadership/whatsapp"  element={<Navigate to="/notification-templates/whatsapp?module=leadership" replace />} />
      </Route>


      {/* ===================  HRMS  ===================
          Opt-in per company. `/hrms/entry` is the dynamic gate (role-routing lands in a
          later phase); the panel routes are guarded by RequireHrms, which also supplies
          the module's capability context to everything inside. */}
      <Route path="/hrms/entry" element={<PrivateRoute><HrmsGate /></PrivateRoute>} />
      <Route path="/hrms" element={<PrivateRoute><RequireHrms><HrmsWorkspace /></RequireHrms></PrivateRoute>}>
        <Route index element={<HrmsHome />} />
        {/* People — employee master, departments and designations (Phase 2). */}
        <Route path="employees"          element={<EmployeeDirectory />} />
        <Route path="employees/:userId"  element={<EmployeeProfile />} />
        {/* Phase 360-1 — Employee 360° (§6): nested under the same profile route so the
            workspace's own nav stays lit. */}
        <Route path="employees/:userId/360" element={<Employee360 />} />
        <Route path="departments"        element={<MasterManager kind="department" />} />
        <Route path="designations"       element={<MasterManager kind="designation" />} />
        {/* Recruitment — requisitions + their co-approved job descriptions (Phase 3). */}
        {/* The generic "both tracks" requisition list is superseded by the internal
            requisition experience (gates, SLA, escalation) now that every requisition runs
            on that one process — redirect rather than leave a stale screen reachable by an
            old bookmark or notification link. */}
        <Route path="requisitions"       element={<Navigate to="/hrms/internal-requisitions" replace />} />
        <Route path="jd"                 element={<JdLibrary />} />
        <Route path="postings"           element={<PostingList />} />
        {/* Pipeline — candidates, triage and the audit-trail journey (Phase 5). */}
        <Route path="candidates"         element={<CandidatePipeline />} />
        <Route path="shortlisted"        element={<ShortlistedCandidates />} />
        <Route path="screening"          element={<ScreeningBoard />} />
        <Route path="assessments"        element={<AssessmentBoard />} />
        <Route path="interviews"         element={<InterviewBoard />} />
        <Route path="offers"             element={<OfferBoard />} />
        <Route path="onboarding"         element={<OnboardingBoard />} />
        <Route path="dashboard"          element={<RecruitmentDashboard />} />
        <Route path="reports"            element={<RecruitmentReports />} />
        {/* Phase 11-R — recruitment review enhancements (Items 2-4, 7). */}
        <Route path="documents"          element={<DocumentCenter />} />
        <Route path="document-types"     element={<DocumentTypeManager />} />
        <Route path="appointments"       element={<AppointmentBoard />} />
        <Route path="sanctioned-strength" element={<SanctionedStrength />} />
        {/* ── Internal track ── Sparsh Magic's own hiring, governed by the Internal
            Recruitment SOP. The pipeline screens sit in the workspace tab strip; the
            governance ones (probation, exceptions) sit in the sidebar. */}
        <Route path="internal-hiring"      element={<InternalHiringDashboard />} />
        {/* Client Hiring (PRO-fit). A separate track: its own screens, its own
            records and its own capabilities. Every endpoint behind these
            refuses a caller who does not hold the client capability, so the
            route is a convenience rather than the control. */}
        <Route path="client-hiring"        element={<ClientHiringDashboard />} />
        {/* The seven stages are ONE page. These paths predate that and are kept as
            redirects: bookmarks and older links still resolve, and the sidebar's
            `/hrms/client-` match keeps working, but nothing navigates away from the
            workspace any more. */}
        <Route path="client-requisitions"
          element={<Navigate to="/hrms/client-hiring?stage=requisitions" replace />} />
        <Route path="client-scorecards"
          element={<Navigate to="/hrms/client-hiring?stage=scorecards" replace />} />
        <Route path="client-candidates"
          element={<Navigate to="/hrms/client-hiring?stage=candidates" replace />} />
        <Route path="client-offers"
          element={<Navigate to="/hrms/client-hiring?stage=offers" replace />} />
        <Route path="client-joinings"
          element={<Navigate to="/hrms/client-hiring?stage=joinings" replace />} />
        <Route path="client-analytics"     element={<ClientRecruitmentAnalytics />} />
        {/* Its own page, and its ONLY home: the pool spans every engagement rather than
            sitting inside one client's flow, so it is not a stage on the workspace rail
            and is not duplicated there. */}
        <Route path="client-candidate-pool" element={<ClientCandidatePool />} />
        <Route path="internal-requisitions" element={<InternalRequisitionList />} />
        {/* Phase INT-15 (spec 29) -- one position, end to end. Nested under the list so
            the workspace tab stays lit on the detail page. */}
        <Route path="internal-requisitions/:requestNo"
               element={<InternalRequisitionDetail />} />
        <Route path="scorecards"           element={<ScorecardLibrary />} />
        <Route path="reference-checks"     element={<ReferenceCheckBoard />} />
        {/* Phase INT-4 — the SOP's step 5 telephonic screen, between CV screening and
            the panel. A hiring stage, so it lives in the workspace tab strip. */}
        <Route path="telephonic-screening" element={<TelephonicBoard />} />
        {/* Phase INT-10 — the SOP's step 9 salary negotiation record. A hiring stage, so
            it lives in the workspace tab strip. */}
        <Route path="negotiations"         element={<NegotiationBoard />} />
        {/* Client-track hiring (job requests, CV sharing, the client's own shared-candidates
            view) has been discontinued — the backend refuses those endpoints outright (see
            `_client_hiring_disabled` in routes/hrms.py). Background verification stays: it
            is a mandatory gate on offers for BOTH tracks (Phase 12), not a client-only
            screen. */}
        <Route path="background-checks"    element={<BackgroundCheckBoard />} />
        <Route path="probation"            element={<ProbationBoard />} />
        <Route path="exceptions"           element={<ExceptionLog />} />
        {/* Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21). Post-hire employment
            events, like Probation above, so it sits in the sidebar rather than the
            workspace tab strip. */}
        <Route path="separations"          element={<SeparationBoard />} />
        <Route path="separations/:sepNo"   element={<SeparationDetail />} />
        {/* Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9). Post-hire operational
            data, like Exit Management above, so it sits in the sidebar. */}
        <Route path="attendance"           element={<AttendanceBoard />} />
        <Route path="leave"                element={<LeaveBoard />} />
        {/* Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20). */}
        <Route path="movements"            element={<MovementsBoard />} />
        {/* Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7). */}
        <Route path="payroll"              element={<PayrollBoard />} />
        {/* Phase PIP-1 — Performance Improvement Plan (§22.5). */}
        <Route path="pip"                  element={<PipBoard />} />
        {/* Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041). */}
        <Route path="letters"              element={<LetterBoard />} />
        {/* Phase ORIENT-1 — Orientation & Training (§22.3). */}
        <Route path="orientation"          element={<OrientationBoard />} />
        {/* Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4). */}
        <Route path="pulse-surveys"        element={<PulseSurveyBoard />} />
        {/* SM-HR-052 — Audit Viewer. The read API and Cap.AUDIT_READ gate already existed;
            this is the first screen to call it. */}
        <Route path="audit"                element={<AuditViewer />} />
        {/* SM-HR-051 — User / Role / Permission Administration. */}
        <Route path="access"               element={<RoleAccessAdmin />} />
        {/* ── Phase INT-2 ── the remaining SOP controls. `shortlist-reviews` is a hiring
            stage and lives in the workspace tab strip; the rest are governance and live in
            the sidebar. The two navigations stay disjoint. */}
        <Route path="shortlist-reviews"    element={<ShortlistCommittee />} />
        <Route path="preboarding"          element={<PreboardingBoard />} />
        <Route path="talent-pool"          element={<TalentPool />} />
        <Route path="salary-bands"         element={<SalaryBandManager />} />
        {/* Candidate communications are managed in Notification Templates. */}
        <Route path="communications"       element={<Navigate to="/notification-templates/email?module=hrms" replace />} />
        <Route path="policies"             element={<PolicyRegister />} />
        <Route path="policy-library"       element={<PolicyLibrary />} />
        {/* Phase INT-5 — the per-company rule set. Governance, not a hiring stage, so
            it lives in the sidebar and NOT in the workspace tab strip. */}
        <Route path="settings"             element={<HrmsSettings />} />
      </Route>

      <Route path="/admin/settings" element={<Navigate to="/settings" />} />
      <Route path="/settings" element={<PrivateRoute><SettingsPage /></PrivateRoute>} />
      <Route path="/profile" element={<PrivateRoute><ProfilePage /></PrivateRoute>} />

      {/* GPT Module */}
      <Route path="/gpt" element={<PrivateRoute><GptProjects /></PrivateRoute>} />
      <Route path="/gpt/new" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/edit/:id" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/chat/:id" element={<PrivateRoute><GptChat /></PrivateRoute>} />
      <Route path="/gpt/chat/:id/:sessionId" element={<PrivateRoute><GptChat /></PrivateRoute>} />
      <Route path="/gpt/permissions" element={<PrivateRoute><GptAccessControl /></PrivateRoute>} />

      {/* Assessment Player (Locked/Blank Mode) */}
      <Route path="/assessment/:sessionId/:quizIndex" element={<PrivateRoute hideLayout={true}><AssessmentPlayer /></PrivateRoute>} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to={user ? "/" : "/login"} />} />
    </Routes>
    </Suspense>
  );
};

const App = () => {
  return (
    <ThemeProvider>
      <AuthProvider>
        <NotificationProvider>
          <UploadProvider>
            <Router>
              <AppRoutes />
            </Router>
            <AssistantWidget />
          </UploadProvider>
          <NotificationModal />
        </NotificationProvider>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;
