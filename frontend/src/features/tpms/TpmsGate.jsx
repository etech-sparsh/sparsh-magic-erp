import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { canAccessTpms, isTpmsAdmin, tpmsHome } from './access';

/**
 * Single dynamic entry point for /tpms.
 * Auto-routes the user to the correct panel based on role:
 *   superadmin/admin → /tpms/admin,  everyone else → /tpms/smops (internal SMOPS + clients).
 * Users with no TPMS access are bounced back to the main app.
 */
export const TpmsGate = () => {
  const { user } = useAuth();
  if (!canAccessTpms(user)) return <Navigate to="/" replace />;
  return <Navigate to={tpmsHome(user)} replace />;
};

/**
 * Route guard for the TPMS panels.
 *  - The SMOPS submodules and the Forms module are shared by every TPMS user
 *    (internal SMOPS users and client-side users alike).
 *  - `admin` panels additionally require superadmin/admin; anyone else is sent to
 *    their own home panel.
 *  - Users with no TPMS access at all are bounced to the main app.
 */
export const RequireTpms = ({ admin = false, children }) => {
  const { user } = useAuth();
  if (!canAccessTpms(user)) return <Navigate to="/" replace />;
  if (admin && !isTpmsAdmin(user)) return <Navigate to={tpmsHome(user)} replace />;
  return children;
};

export default TpmsGate;
