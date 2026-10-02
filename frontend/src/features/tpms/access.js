// TPMS has two audiences:
//   • Internal staff — mirrors Task Management (utils/taskAccess.js).
//   • Client-side users (clientadmin/clientuser) — ONLY when their company has TPMS
//     switched on. The module is opt-in per company: an Admin / Super Admin enables it
//     from the company page, and `tpms_enabled` arrives on the user from /me.
//     Enabled companies share the SMOPS submodules (Dashboard, HOD Activity, Employee
//     Task, Review Report, My Profile) plus the Forms module.
//
// Which panel a user lands on when hitting /tpms:
//   • superadmin / admin → Admin panel  (/tpms/admin)
//   • everyone else      → SMOPS panel  (/tpms/smops)  ← internal SMOPS users + clients
import { canAccessTaskManagement } from '../../utils/taskAccess';

const CLIENT_ROLES = ['clientadmin', 'clientuser'];

/** Is this a client-side user whose company has TPMS switched on?
 *  Absent flag means OFF — TPMS is opt-in, so a company stays dark until enabled. */
export const canAccessTpmsClient = (user) =>
  !!user && CLIENT_ROLES.includes(user.role) && user.tpms_enabled === true;

/** Can this user open TPMS at all? (internal staff OR any client-side user) */
export const canAccessTpms = (user) => canAccessTaskManagement(user) || canAccessTpmsClient(user);

/** Does this user get the internal Admin panel? */
export const isTpmsAdmin = (user) => user?.role === 'superadmin' || user?.role === 'admin';

/** The panel this user should land on when hitting /tpms. */
export const tpmsHome = (user) => (isTpmsAdmin(user) ? '/tpms/admin' : '/tpms/smops');
