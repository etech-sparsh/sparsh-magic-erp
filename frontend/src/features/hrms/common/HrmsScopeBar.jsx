import React from 'react';
import { Building2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';

/**
 * HRMS ▸ company scope selector.
 *
 * Internal Sparsh staff administer HRMS across clients, so every employee screen needs to
 * know which company it is looking at. Client-side users are pinned server-side and see a
 * static label instead of a control — showing them a disabled dropdown would imply a choice
 * they do not have.
 *
 * -- The single-company case renders NOTHING ----------------------------------------------
 * HRMS is an in-house system: it recruits this company's own staff. When there is one
 * company there is no scope to choose and no ambiguity to resolve, so the bar stays out of
 * the way entirely. It used to render the name as a chip, which on an in-house system just
 * repeated the obvious on every screen.
 *
 * The selector below still exists for an operator who genuinely administers more than one
 * company in this ERP — that is a real choice, and it is shown.
 */
const HrmsScopeBar = () => {
  const { companies, companyId, setCompanyId, canSwitchCompany, isInternal } = useHrms();

  if (!isInternal || companies.length === 0) return null;

  // One company means no decision to make, so the bar shows nothing at all rather than
  // restating the obvious on every screen.
  if (!canSwitchCompany) return null;

  return (
    <label className="flex items-center gap-2">
      <Building2 size={14} className="text-[var(--text-muted)]" />
      <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        Company
      </span>
      <select
        value={companyId || ''}
        onChange={(e) => setCompanyId(e.target.value)}
        className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)] max-w-[220px]"
      >
        {companies.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>
    </label>
  );
};

export default HrmsScopeBar;
