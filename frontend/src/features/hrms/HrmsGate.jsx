import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { hrmsAccessState, hrmsHome, isClientTrackUser } from './access';
import { HrmsProvider } from './HrmsContext';
import HrmsScopeGuard from './common/HrmsScopeGuard';

/** Shown while the profile (and with it the module flags) is still arriving. */
const Resolving = () => (
  <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">
    Loading…
  </div>
);

/**
 * Single dynamic entry point for /hrms.
 * Users with no HRMS access are bounced back to the main app; everyone else lands on the
 * module home. Mirrors TpmsGate.jsx.
 *
 * Phase 1 has one shell, so `hrmsHome()` is constant. Later phases route by role here
 * (recruitment workspace vs. employee self-service) without touching App.jsx.
 */
export const HrmsGate = () => {
  const { user } = useAuth();
  const state = hrmsAccessState(user);
  if (state === 'unknown') return <Resolving />;
  if (state === 'denied') return <Navigate to="/" replace />;
  return <Navigate to={hrmsHome(user)} replace />;
};

/**
 * Route guard for the HRMS panels.
 *
 * Three layers, deliberately:
 *   1. `hrmsAccessState` — a synchronous check on the company toggle, so a user without
 *      access never mounts the module or fires its requests.
 *   2. `HrmsProvider` — fetches the server's authoritative capability list for everything
 *      inside. Feature-level gating uses `useHrms().can(...)`, never a raw role check.
 *   3. `HrmsScopeGuard` — an internal user passes layer 1 unconditionally (they administer
 *      the toggle), so they can reach a module in which NO company has it enabled. That is
 *      a real state with no way out from inside, and it needs explaining rather than 400ing
 *      on every screen.
 *
 * The 'unknown' branch matters: AuthProvider seeds `user` from the JWT and merges the full
 * profile asynchronously, and the module flags live only on the profile. Redirecting on a
 * merely-absent flag would eject an entitled user from HRMS on every hard refresh or deep
 * link. We wait for the answer instead of guessing at it. (See hrmsAccessState.)
 *
 * The backend enforces the same rules independently (routes/hrms.py router guard +
 * utils/hrms_access.py), so this is a UX affordance, not the security boundary.
 */
export const RequireHrms = ({ children }) => {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const state = hrmsAccessState(user);

  if (state === 'unknown') return <Resolving />;
  if (state === 'denied') return <Navigate to="/" replace />;

  // A client company's user holds CLIENT_TRACK_CAPS and nothing else, so every HRMS screen
  // outside Client Hiring would load, fire its requests and answer 403 — including the
  // module home at /hrms. Sending them to the one track they are entitled to is kinder
  // than letting them watch a dashboard fail, and it is the same answer the server gives.
  if (isClientTrackUser(user) && !pathname.startsWith('/hrms/client-')) {
    return <Navigate to={hrmsHome(user)} replace />;
  }

  // `HrmsScopeGuard` sits INSIDE the provider because it needs the resolved company list.
  // It catches the one state the two layers above cannot see: an internal user who is
  // entitled to the module but has no HRMS-enabled company to work in, which otherwise
  // shows up as a technical 400 on every screen. See the component for why.
  return (
    <HrmsProvider>
      <HrmsScopeGuard>{children}</HrmsScopeGuard>
    </HrmsProvider>
  );
};

export default HrmsGate;
