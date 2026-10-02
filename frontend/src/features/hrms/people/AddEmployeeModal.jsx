import React, { useEffect, useState } from 'react';
import { X, UserPlus } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { getLinkableUsers, createEmployee } from '../../../services/hrmsApi';

/**
 * HRMS ▸ add employee.
 *
 * An employee profile EXTENDS an existing ERP user — it never creates a person. The picker
 * therefore lists only users who do not already have a profile (the server computes that
 * set), which is why there is no name/email field here: identity is owned by the user
 * record and is never duplicated into HRMS.
 *
 * The employee code is left blank by default and minted server-side from an atomic counter.
 */
const AddEmployeeModal = ({ departments, designations, onClose, onCreated }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    user_id: '', department_id: '', designation_id: '',
    employment_status: 'Active', employment_type: 'Full-time',
    joined_on: '', base_salary: '',
  });

  const canSetSalary = can(CAP.EMPLOYEE_SALARY_WRITE);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  useEffect(() => {
    getLinkableUsers(scope)
      .then(({ data }) => setUsers(data?.users || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load users.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.user_id) return showError('Select a user.');
    setSaving(true);
    try {
      const payload = { user_id: form.user_id };
      // Send only what was filled — an empty string is not "clear this field", it is
      // "untouched", and the server treats a present key as an instruction.
      ['department_id', 'designation_id', 'employment_status', 'employment_type', 'joined_on']
        .forEach((k) => { if (form[k]) payload[k] = form[k]; });
      if (canSetSalary && form.base_salary !== '') payload.base_salary = Number(form.base_salary);

      await createEmployee(payload, scope);
      showSuccess('Employee profile created');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the employee profile.');
    } finally {
      setSaving(false);
    }
  };

  const field = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
  const label = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <UserPlus size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Add employee</h2>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4 overflow-y-auto">
          <div>
            <label className={label} htmlFor="emp-user">User *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading users…</p>
            ) : users.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Every user in this company already has an employee profile.
              </p>
            ) : (
              <select id="emp-user" value={form.user_id} onChange={set('user_id')} className={field} required>
                <option value="">Select a user…</option>
                {users.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.name}{u.email ? ` — ${u.email}` : ''}
                  </option>
                ))}
              </select>
            )}
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
              Employee records extend existing company users. To add a new person, create the
              user first in User Management.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={label} htmlFor="emp-dept">Department</label>
              <select id="emp-dept" value={form.department_id} onChange={set('department_id')} className={field}>
                <option value="">—</option>
                {departments.filter((d) => d.active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-desig">Designation</label>
              <select id="emp-desig" value={form.designation_id} onChange={set('designation_id')} className={field}>
                <option value="">—</option>
                {designations.filter((d) => d.active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-status">Status</label>
              <select id="emp-status" value={form.employment_status} onChange={set('employment_status')} className={field}>
                {['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave']
                  .map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-type">Employment type</label>
              <select id="emp-type" value={form.employment_type} onChange={set('employment_type')} className={field}>
                {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant']
                  .map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-joined">Joining date</label>
              <input id="emp-joined" type="date" value={form.joined_on} onChange={set('joined_on')} className={field} />
            </div>
            {canSetSalary && (
              <div>
                <label className={label} htmlFor="emp-salary">Base salary (monthly)</label>
                <input id="emp-salary" type="number" min="0" step="1" value={form.base_salary}
                  onChange={set('base_salary')} placeholder="e.g. 30000" className={field} />
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.user_id}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Creating…' : 'Create profile'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddEmployeeModal;
