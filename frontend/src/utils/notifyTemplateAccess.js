// Who may open Notification Templates.
//
// Notification templates — Email, WhatsApp, the Meta template library, and the TPMS, Leadership
// Score and HRMS templates shown inside the module — are managed by Super Admin and Admin only.
// On the server, /notify-templates, /settings/templates, /meta-templates and the TPMS template
// endpoints apply the same rule; this file only decides what is shown.
import { canAccessHrms } from '../features/hrms/access';
import { canAccessTaskManagement } from './taskAccess';

const ADMIN_ROLES = ['superadmin', 'admin'];

export const isNotifyAdmin = (user) => ADMIN_ROLES.includes(user?.role);

export const canOpenNotificationTemplates = (user) => isNotifyAdmin(user);

export const canManageGeneralTemplates = (user) => isNotifyAdmin(user);

export const canManageTpmsTemplates = (user) => isNotifyAdmin(user);

export const canManageLeadershipInvite = (user) => isNotifyAdmin(user);

export const canManageHrmsComms = (user) => isNotifyAdmin(user) && canAccessHrms(user);

/** Presentation only: hide a module whose feature this admin cannot reach. */
export const canSeeGeneralModule = (user, key) => {
  if (key === 'delegation' || key === 'checklist') return canAccessTaskManagement(user);
  return true;
};
