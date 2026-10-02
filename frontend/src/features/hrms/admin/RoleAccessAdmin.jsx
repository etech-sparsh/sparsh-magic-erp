import React, { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, Search, ChevronDown, ChevronRight, ChevronLeft } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getEmployees, getHrmsRoleMatrix, setGovernanceRole } from '../../../services/hrmsApi';
import rawApi from '../../../services/api';
import { Chip } from '../internal/internalKit.jsx';

const PAGE_SIZE = 50;

// Assignable via this screen — mirrors backend ASSIGNABLE_GOVERNANCE_ROLES (models/hrms.py,
// Phase ACCESS-1).
const GOVERNANCE_OPTIONS = [
  { value: '', label: '— (Employee)' },
  { value: 'HOD', label: 'HOD (Manager)' },
  { value: 'HR', label: 'HR' },
  { value: 'FINANCE', label: 'Finance' },
  { value: 'MD', label: 'MD' },
  { value: 'IMPLEMENTOR', label: 'Implementor' },
];

/**
 * HRMS ▸ User / Role / Permission Administration (SM-HR-051).
 *
 * "Assign" = governance_role, the field hrms_role() has always read to resolve a
 * client-side user's HRMS role (HOD/HR/FINANCE/MD -> MANAGER/HR/FINANCE/MD) but which,
 * until this screen, had no write path anywhere in the app.
 *
 * "Disable" is deliberately NOT reimplemented here — it reuses the base platform's own
 * PATCH /users/{id}/status (same account-status field UserDetails.jsx already toggles),
 * so there is one write path onto `is_active`, not two competing ones.
 *
 * "Review access" is the read-only role/capability matrix below the directory, served
 * from the backend's own ROLE_CAPABILITIES so it can never show something the gates do
 * not actually enforce.
 *
 * Field/tab-level permission, configurable data scope and delegation are explicitly OUT
 * of scope for this phase — see the Phase ACCESS-1 comment in models/hrms.py for why each
 * is a workshop item rather than a gap in something already there.
 */
const RoleAccessAdmin = () => {
  const { scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ employees: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [page, setPage] = useState(0);
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(0); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data: res } = await getEmployees({
        ...scope, search: debounced || undefined, limit: PAGE_SIZE, skip: page * PAGE_SIZE,
        include_inactive: true,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the user directory.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, debounced, page]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE));

  const changeGovernanceRole = async (row, value) => {
    setSavingId(row.user_id);
    try {
      await setGovernanceRole(row.user_id, value, scope);
      showSuccess(`Role updated for ${row.name}.`);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update this role.');
    } finally {
      setSavingId(null);
    }
  };

  const toggleStatus = async (row) => {
    setSavingId(row.user_id);
    try {
      await rawApi.patch(`/users/${row.user_id}/status`, { is_active: row.is_active === false });
      showSuccess(`${row.name} ${row.is_active === false ? 'activated' : 'deactivated'}.`);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not change account status.');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={ShieldCheck}
        title="User / Role / Permission Administration"
        subtitle="Assign governance roles, disable access, and review what each role can do (SM-HR-051)."
      />
      <HrmsScopeBar />

      {!companyId ? (
        <HrmsEmpty icon={ShieldCheck} title="Select a company"
          hint="Choose a company above to manage its users." />
      ) : (
        <>
          <div className="relative max-w-sm">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, email or mobile…"
              className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
          </div>

          {loading && <HrmsLoading label="Loading users…" />}
          {error && !loading && <HrmsError message={error} onRetry={load} />}
          {!loading && !error && (
            data.employees.length === 0 ? (
              <HrmsEmpty icon={ShieldCheck} title="No users match" />
            ) : (
              <>
                <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
                  <table className="w-full text-[13px] min-w-[760px]">
                    <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
                      <tr>
                        {['User', 'Account Role', 'Governance Role', 'Status', ''].map((h) => (
                          <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.employees.map((row) => {
                        const isClientUser = row.role === 'clientuser';
                        const busy = savingId === row.user_id;
                        return (
                          <tr key={row.user_id || row.employee_code} className="border-t border-[var(--border)]">
                            <td className="px-4 py-2.5">
                              <div className="font-semibold text-[var(--text-main)]">{row.name}</div>
                              <div className="text-[11.5px] text-[var(--text-muted)]">{row.email}</div>
                            </td>
                            <td className="px-4 py-2.5 text-[var(--text-main)]">{row.role || '—'}</td>
                            <td className="px-4 py-2.5">
                              {isClientUser ? (
                                <select value={row.governance_role || ''} disabled={busy}
                                  onChange={(e) => changeGovernanceRole(row, e.target.value)}
                                  className="h-8 px-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)]">
                                  {GOVERNANCE_OPTIONS.map((o) => (
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                  ))}
                                </select>
                              ) : row.role === 'clientadmin' ? (
                                <span className="text-[12px] text-[var(--text-muted)]">MD (fixed by account role)</span>
                              ) : (
                                <span className="text-[12px] text-[var(--text-muted)]">— (not applicable)</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5">
                              <Chip tone={row.is_active === false ? 'bad' : 'good'}>
                                {row.is_active === false ? 'Disabled' : 'Active'}
                              </Chip>
                            </td>
                            <td className="px-4 py-2.5 text-right">
                              <button type="button" disabled={busy} onClick={() => toggleStatus(row)}
                                className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] disabled:opacity-50">
                                {row.is_active === false ? 'Enable' : 'Disable'}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-between text-[12px] text-[var(--text-muted)]">
                    <span>Page {page + 1} of {totalPages}</span>
                    <div className="flex gap-1">
                      <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)}
                        className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] disabled:opacity-40">
                        <ChevronLeft size={15} />
                      </button>
                      <button type="button" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}
                        className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] disabled:opacity-40">
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>
                )}
              </>
            )
          )}

          <RoleMatrix />
        </>
      )}
    </div>
  );
};

const RoleMatrix = () => {
  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    getHrmsRoleMatrix()
      .then(({ data }) => setMatrix(data?.roles || {}))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the role matrix.'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      <div>
        <h3 className="text-[13.5px] font-bold text-[var(--text-main)]">Role &amp; Capability Matrix</h3>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Read-only — every capability a role holds, sourced directly from what the module's
          own gates enforce. "Review access" per SM-HR-051.
        </p>
      </div>
      {loading && <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>}
      {error && <p className="text-[12.5px] text-[var(--accent-red)] font-semibold">{error}</p>}
      {matrix && Object.entries(matrix).map(([role, caps]) => (
        <div key={role} className="rounded-lg border border-[var(--border)]">
          <button type="button" onClick={() => setExpanded(expanded === role ? null : role)}
            className="w-full flex items-center justify-between px-3 py-2 text-left">
            <span className="text-[12.5px] font-bold text-[var(--text-main)]">
              {role} <span className="text-[var(--text-muted)] font-normal">({caps.length} capabilities)</span>
            </span>
            {expanded === role ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
          {expanded === role && (
            <div className="px-3 pb-3 flex flex-wrap gap-1.5">
              {caps.map((c) => <Chip key={c} tone="neutral">{c}</Chip>)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default RoleAccessAdmin;
