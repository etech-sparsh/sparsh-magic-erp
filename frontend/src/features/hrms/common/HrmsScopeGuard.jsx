import React from 'react';
import { Link } from 'react-router-dom';
import { PowerOff, ArrowRight } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useHrms } from '../HrmsContext';
import { canToggleHrms } from '../access';

/**
 * HRMS ▸ the module-off states, for internal staff.
 *
 * HRMS is opt-in per company (`companies.hrms_enabled`), and `company_id` is the tenant
 * boundary every endpoint scopes by. Internal staff are deliberately NOT gated by that
 * toggle — they administer the module and support it across clients, so
 * `ensure_hrms_enabled` returns early for them.
 *
 * The company SELECTOR used to be filtered by the toggle anyway, which meant switching
 * HRMS off everywhere put internal staff inside a module with an empty dropdown, and every
 * screen answered `400 — Select a company to work with`. An error telling you to pick from
 * a list that had nothing in it.
 *
 * The server now hands internal staff the companies that actually hold HRMS records when
 * none is enabled, so Sparsh Magic's own hiring keeps working with the module switched off.
 * This component handles the one state that leaves: no company at all — nothing enabled AND
 * no HRMS records anywhere. A genuinely empty module, which needs explaining rather than
 * 400ing on every screen.
 *
 * There is deliberately NO "every company is switched off" banner. Internal staff are not
 * gated by the toggle, so every screen works regardless and the notice was a statement of
 * fact nobody needed on every page. The toggle's real effect — that a company's own users
 * cannot reach HRMS — is visible where it is set, in Companies.
 */

const HrmsScopeGuard = ({ children }) => {
  const { user } = useAuth();
  const { loading, error, isInternal, companyId, companies } = useHrms();

  // While the answer is still arriving, let the screens render their own loading states —
  // flashing a banner and then removing it would be worse than a moment of nothing.
  if (loading) return children;

  // A hard failure (403, network) is the provider's to report; it already sets `error` and
  // the route guard handles a revoked toggle. This component is only about the module-off
  // states, which are not errors.
  if (error) return children;

  // Client-side users are pinned to their own company by the server and never see a
  // selector. If their tenant has the module off they are refused at the door with a 403 —
  // a different message, in a different place, and correctly so.
  if (!isInternal) return children;

  const mayToggle = canToggleHrms(user);

  if (!companyId && companies.length === 0) {
    return (
      <div className="py-14 px-4 flex flex-col items-center text-center">
        <div className="h-12 w-12 rounded-2xl bg-[var(--accent-orange-bg)]
                        text-[var(--accent-orange)] grid place-items-center">
          <PowerOff size={22} />
        </div>
        <h1 className="mt-4 text-[17px] font-bold tracking-tight text-[var(--text-main)]">
          There is no company to work in yet
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-[var(--text-muted)]">
          No company has HRMS switched on, and none holds any HRMS records — so there is
          nothing for these screens to open. Switch the module on for the company that will
          run your recruitment, and both hiring tracks become available in it.
        </p>
        {mayToggle ? (
          <Link
            to="/companies"
            className="mt-5 inline-flex items-center gap-1.5 h-9 px-4 rounded-lg
                       bg-[var(--accent-indigo)] text-white text-[12px] font-bold"
          >
            Open Companies <ArrowRight size={14} />
          </Link>
        ) : (
          <p className="mt-5 text-[12px] text-[var(--text-muted)]">
            Only an Admin or Super Admin can switch the module on.
          </p>
        )}
      </div>
    );
  }

  return children;
};

export default HrmsScopeGuard;
