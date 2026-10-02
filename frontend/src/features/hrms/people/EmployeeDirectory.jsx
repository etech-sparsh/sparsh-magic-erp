import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Users2, Search, Plus, ChevronLeft, ChevronRight, ShieldAlert } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getEmployees, getDepartments, getDesignations, getLinkableUsers, linkEmployeeUser,
} from '../../../services/hrmsApi';
import AddEmployeeModal from './AddEmployeeModal';

const STATUSES = ['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave'];
const PAGE_SIZE = 50;

const StatusPill = ({ value }) => {
  if (!value) return <span className="text-[var(--text-muted)]">—</span>;
  const tone = value === 'Active'
    ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
    : value === 'Resigned' || value === 'Terminated'
    ? 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
    : 'bg-[var(--input-bg)] text-[var(--text-muted)]';
  return <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${tone}`}>{value}</span>;
};

const inr = (n) =>
  typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '—';

/**
 * Attach an onboarding-created employee record to a real login account.
 *
 * HRMS does not create logins — identity belongs to the ERP. So an employee minted at
 * onboarding waits here until their account exists, at which point this joins the two and
 * the user document becomes the single source of their name and email.
 */
const LinkAccountModal = ({ employee, onClose, onLinked }) => {
  const { scope } = useHrms();
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getLinkableUsers(scope)
      .then(({ data }) => setUsers(data?.users || []))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load accounts.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (!userId) { setError('Choose an account.'); return; }
    setSaving(true);
    setError('');
    try {
      await linkEmployeeUser(employee.employee_code, { user_id: userId }, scope);
      onLinked();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not link that account.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Link a login account</h2>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            {employee.name} · {employee.employee_code}
          </p>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-[12.5px] text-[var(--text-muted)]">
            This employee was created during onboarding and has no login yet. Once their ERP
            account exists, link it here — their name and email will then come from the
            account.
          </p>
          {loading ? (
            <p className="text-[12.5px] text-[var(--text-muted)]">Loading accounts…</p>
          ) : users.length === 0 ? (
            <p className="text-[12.5px] text-[var(--text-muted)]">
              No unlinked accounts are available. Create their ERP user first.
            </p>
          ) : (
            <select value={userId} onChange={(e) => setUserId(e.target.value)}
              aria-label="Account to link"
              className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
              <option value="">Select an account…</option>
              {users.map((u) => (
                <option key={u.user_id} value={u.user_id}>{u.name} — {u.email}</option>
              ))}
            </select>
          )}
          {error && <p className="text-[12px] font-semibold text-[var(--accent-red)]">{error}</p>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12.5px] font-bold text-[var(--text-muted)]">
            Cancel
          </button>
          <button type="button" onClick={submit} disabled={saving || users.length === 0}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold disabled:opacity-50">
            {saving ? 'Linking…' : 'Link account'}
          </button>
        </div>
      </div>
    </div>
  );
};

/**
 * HRMS ▸ employee directory.
 *
 * Lists the scoped company's people, composed from the ERP user record + the HRMS profile.
 * Row scoping is enforced server-side (a HOD sees only their department and direct reports),
 * so this component renders whatever it is given rather than filtering by role itself.
 *
 * The salary column appears only when the server says the caller may see it — the response
 * carries `salary_visible`, and salary is OMITTED from the payload otherwise, so it is never
 * merely hidden in the DOM.
 */
const EmployeeDirectory = () => {
  const navigate = useNavigate();
  const { can, scope, companyId } = useHrms();

  const [data, setData] = useState({ employees: [], total: 0, salary_visible: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [departmentId, setDepartmentId] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  // The employee whose login account is being attached (onboarding-created, no user yet).
  const [linking, setLinking] = useState(null);

  const canWrite = can(CAP.EMPLOYEE_WRITE);

  // Debounce so typing does not fire a request per keystroke against a 500-row directory.
  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(0); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getEmployees({
        ...scope,
        search: debounced || undefined,
        department_id: departmentId || undefined,
        status: status || undefined,
        limit: PAGE_SIZE,
        skip: page * PAGE_SIZE,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the employee directory.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, debounced, departmentId, status, page]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!companyId) return;
    // Filter options. Failure here is non-fatal — the directory still works without them.
    getDepartments(scope).then(({ data: d }) => setDepartments(d?.departments || [])).catch(() => {});
    getDesignations(scope).then(({ data: d }) => setDesignations(d?.designations || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE));

  if (!companyId) {
    return (
      <div className="space-y-6">
        <HrmsPageHeader icon={Users2} title="Employees" actions={<HrmsScopeBar />} />
        <HrmsEmpty icon={ShieldAlert} title="Select a company"
          hint="Choose a company above to view its employees." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Users2}
        title="Employees"
        subtitle={`${data.total || 0} ${data.total === 1 ? 'person' : 'people'} in this company`}
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canWrite && (
              <button
                type="button" onClick={() => setShowAdd(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5"
              >
                <Plus size={14} /> Add employee
              </button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, email or mobile…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
          />
        </div>
        <select
          value={departmentId} onChange={(e) => { setDepartmentId(e.target.value); setPage(0); }}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]"
        >
          <option value="">All departments</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select
          value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading employees…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.employees.length === 0 ? (
        <HrmsEmpty
          icon={Users2}
          title="No employees match"
          hint={search || departmentId || status
            ? 'Try clearing the filters.'
            : 'Add your first employee to get started.'}
        />
      ) : (
        <>
          <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
            <table className="w-full text-[13px] min-w-[720px]">
              <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
                <tr>
                  {['Employee', 'Code', 'Department', 'Designation', 'Status'].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                  ))}
                  {data.salary_visible && (
                    <th className="text-right px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">Base salary</th>
                  )}
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {data.employees.map((e, idx) => (
                  // Onboarding creates an employee BEFORE they have a login, so `user_id`
                  // may be null. Those rows key on the employee code and open the linking
                  // dialog instead of a profile route that does not exist yet. A row whose
                  // link is broken has neither a usable `user_id` nor necessarily an
                  // employee_code, so it opens nothing -- there is no profile route or
                  // linking dialog that applies to it; fixing the underlying data is a
                  // separate, deliberate action, not a click on the row.
                  <tr
                    key={e.user_id || e.employee_code || e.email || idx}
                    onClick={() => {
                      if (e.pending_user_link) setLinking(e);
                      else if (e.user_id) navigate(`/hrms/employees/${e.user_id}`);
                    }}
                    className={`border-t border-[var(--border)] transition-colors ${
                      e.link_broken
                        ? 'cursor-default'
                        : 'cursor-pointer hover:bg-[var(--input-bg)]'
                    }`}
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-semibold text-[var(--text-main)] flex items-center gap-2">
                        {e.name}
                        {e.pending_user_link && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[var(--input-bg)] text-[var(--text-muted)]">
                            No login yet
                          </span>
                        )}
                        {e.link_broken && (
                          <span title="This employee's linked login account could not be found — it may have moved to another company."
                            className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[var(--accent-red-bg)] text-[var(--accent-red)]">
                            Account link broken
                          </span>
                        )}
                      </div>
                      <div className="text-[11.5px] text-[var(--text-muted)]">{e.email}</div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[12px] text-[var(--text-muted)]">
                      {e.employee_code || <span className="italic">not set</span>}
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-main)]">
                      {e.department || <span className="text-[var(--text-muted)]">{e.legacy_department || '—'}</span>}
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-main)]">
                      {e.designation || <span className="text-[var(--text-muted)]">{e.legacy_designation || '—'}</span>}
                    </td>
                    <td className="px-4 py-2.5"><StatusPill value={e.employment_status} /></td>
                    {data.salary_visible && (
                      <td className="px-4 py-2.5 text-right font-semibold text-[var(--text-main)]">
                        {inr(e.base_salary)}
                      </td>
                    )}
                    {/* §7.5 Stage 9 — the 360° workspace, which carries the recruitment
                        history a converted candidate keeps. Addressed by employee code so
                        a joiner with no login yet can still be opened; clicking the row
                        itself still offers to link their account, which is the more
                        common thing to want for those people. */}
                    <td className="px-4 py-2.5 text-right">
                      {e.employee_code && (
                        <button type="button"
                          onClick={(ev) => {
                            ev.stopPropagation();
                            navigate(`/hrms/employees/${e.user_id || e.employee_code}/360`);
                          }}
                          className="h-7 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] whitespace-nowrap">
                          360°
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
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
      )}

      {showAdd && (
        <AddEmployeeModal
          departments={departments}
          designations={designations}
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }}
        />
      )}

      {linking && (
        <LinkAccountModal
          employee={linking}
          onClose={() => setLinking(null)}
          onLinked={() => { setLinking(null); load(); }}
        />
      )}
    </div>
  );
};

export default EmployeeDirectory;
