// Mirrors the backend gate (auth_controller.has_task_access): internal Sparsh users
// (staff collection — tag "staff", roles superadmin/admin and any future staff-side role)
// always have the module. Client-side users (clientadmin/clientuser, tag "learner") get it
// only while their company's Delegation toggle is ON (`delegation_enabled`, surfaced on
// /users/me), or via the legacy permissions.tasks.access_task_management override.
// Super Admin is always allowed.
const INTERNAL_ROLES = new Set(['superadmin', 'admin', 'coach', 'staff']);
const CLIENT_ROLES = new Set(['clientadmin', 'clientuser']);

export const isClientSideUser = (user) => {
  if (!user) return false;
  if (user.tag === 'staff') return false;
  if (user.tag === 'learner') return true;
  return CLIENT_ROLES.has(user.role);
};

export const canAccessTaskManagement = (user) => {
  if (!user) return false;
  if (user.role === 'superadmin') return true;
  if (user.permissions?.tasks?.access_task_management) return true; // explicit client override
  if (isClientSideUser(user)) return user.delegation_enabled === true;
  if (user.tag === 'staff') return true;
  return INTERNAL_ROLES.has(user.role);
};

// Managing task settings (categories/tags/holidays) additionally requires an internal admin.
const MANAGE_ROLES = new Set(['superadmin', 'admin', 'coach', 'staff']);
export const canManageTaskSettings = (user) =>
  canAccessTaskManagement(user) && (user?.role === 'superadmin' || MANAGE_ROLES.has(user?.role));

// Only Super Admin + Sparsh Admin (or an explicit permissions.tasks.view_all_tasks grant)
// may see all tasks / the system-wide total. Mirrors backend tasks.py:_can_view_all_tasks.
// Every other internal user is scoped to their own related tasks (enforced server-side).
export const canViewAllTasks = (user) =>
  user?.role === 'superadmin' || user?.role === 'admin' || !!user?.permissions?.tasks?.view_all_tasks;

export const TASK_ACCESS_DENIED_MESSAGE = 'Task Management is only available for Sparsh internal teams.';

// Shown to a company user whose company has the Delegation module switched off.
export const DELEGATION_DISABLED_MESSAGE = 'The Delegation module is not enabled for your company. Please contact your administrator.';

// The right denial copy for whoever hit the wall — mirrors the backend's two 403 messages.
export const taskAccessDeniedMessage = (user) =>
  (isClientSideUser(user) ? DELEGATION_DISABLED_MESSAGE : TASK_ACCESS_DENIED_MESSAGE);
