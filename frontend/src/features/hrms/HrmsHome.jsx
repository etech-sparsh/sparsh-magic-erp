import React from 'react';
import { Users2, ShieldCheck, Building2, KeyRound } from 'lucide-react';
import { useHrms } from './HrmsContext';
import HrmsPageHeader from './common/HrmsPageHeader';
import { HrmsLoading, HrmsError } from './common/HrmsStates';

/**
 * HRMS ▸ module home.
 *
 * Phase 1 deliverable: proves the whole access chain end to end — company toggle →
 * /users/me → route guard → GET /hrms/health → resolved role + capabilities. It renders
 * exactly what the SERVER says the caller may do, which is the contract every later phase
 * gates on.
 *
 * Phases 2+ replace this with the real module landing (directory, recruitment workspace or
 * self-service, by role).
 */

const InfoTile = ({ icon: Icon, label, value }) => (
  <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
    <div className="flex items-center gap-2 text-[var(--text-muted)]">
      <Icon size={14} />
      <span className="text-[10.5px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <p className="mt-2 text-[15px] font-bold text-[var(--text-main)] break-all">
      {value || '—'}
    </p>
  </div>
);

const HrmsHome = () => {
  const { loading, error, role, capabilities, companyId, isInternal, reload } = useHrms();

  if (loading) return <HrmsLoading label="Loading HRMS…" />;
  if (error) return <HrmsError message={error} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Users2}
        title="HRMS"
        subtitle="Human Resource Management — recruitment, people and payroll."
      />

      <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--input-bg)]">
        <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
          <span className="font-bold text-[var(--text-main)]">Module foundation is live.</span>{' '}
          Access control, the audit trail and the collection registry are in place. Employee
          management, recruitment, leave and payroll arrive in the phases that follow.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <InfoTile icon={ShieldCheck} label="Your HRMS role" value={role} />
        <InfoTile
          icon={Building2}
          label="Scope"
          value={isInternal ? 'All companies (internal)' : companyId}
        />
        <InfoTile icon={KeyRound} label="Capabilities" value={capabilities.length} />
      </div>

      <div>
        <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
          Granted capabilities
        </p>
        <div className="flex flex-wrap gap-2">
          {capabilities.map((c) => (
            <span
              key={c}
              className="px-2.5 py-1 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[11.5px] font-bold font-mono"
            >
              {c}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

export default HrmsHome;
