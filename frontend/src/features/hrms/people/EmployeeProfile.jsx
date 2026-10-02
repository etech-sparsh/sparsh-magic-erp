import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, UserCircle, Save, Network, LayoutGrid, FileText, X } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getEmployee, updateEmployee, getEmployeeHierarchy, getDepartments, getDesignations,
  getAppointments,
} from '../../../services/hrmsApi';
import DocumentPanel from '../documents/DocumentPanel';
import AppointmentPaper from '../recruitment/AppointmentPaper';
import GmpPanel from './GmpPanel';

/**
 * HRMS ▸ employee profile.
 *
 * Four tabs: Job · Personal · Statutory & Bank · Reporting. Salary lives on Job and appears
 * only when the server included it — the field is absent from the payload without
 * `employee.salary.read`, so an unauthorised viewer cannot recover it from the DOM.
 *
 * Identity (name, email, mobile) is READ-ONLY here by design: it is owned by the ERP user
 * record and edited in User Management. HRMS never writes to staff/learners.
 */

const TABS = [
  { key: 'job', label: 'Job' },
  { key: 'personal', label: 'Personal' },
  { key: 'statutory', label: 'Statutory & Bank' },
  { key: 'reporting', label: 'Reporting' },
  // Phase 11-R, Item 2 — one of the shared DocumentPanel's two mount points.
  { key: 'documents', label: 'Documents' },
  // §22.1 — Group Mediclaim Policy: dependants, coverage and enrolment, restricted to HR
  // write with employee-self read (see GmpPanel).
  { key: 'gmp', label: 'GMP' },
];

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const Row = ({ children }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
);

const ReadOnly = ({ label, value }) => (
  <div>
    <span className={LABEL}>{label}</span>
    <p className="text-[13.5px] font-semibold text-[var(--text-main)] break-words">{value || '—'}</p>
  </div>
);

const EmployeeProfile = () => {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [employee, setEmployee] = useState(null);
  const [form, setForm] = useState({});
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [hierarchy, setHierarchy] = useState(null);
  const [tab, setTab] = useState('job');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [appointmentLetter, setAppointmentLetter] = useState(undefined); // undefined = not checked yet
  const [showLetter, setShowLetter] = useState(false);

  const canWrite = can(CAP.EMPLOYEE_WRITE);
  const canSeeSalary = employee && 'base_salary' in employee;
  const canSetSalary = can(CAP.EMPLOYEE_SALARY_WRITE);
  const canSeeAppointment = can(CAP.APPOINTMENT_READ);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getEmployee(userId, scope);
      setEmployee(data);
      setForm({
        department_id: data.department_id || '',
        designation_id: data.designation_id || '',
        employment_status: data.employment_status || 'Active',
        employment_type: data.employment_type || 'Full-time',
        employee_code: data.employee_code || '',
        joined_on: data.joined_on || '',
        resigned_on: data.resigned_on || '',
        base_salary: data.base_salary ?? '',
        gender: data.gender || '',
        date_of_birth: data.date_of_birth || '',
        blood_group: data.blood_group || '',
        address: data.address || '',
        emergency_contact_name: data.emergency_contact_name || '',
        emergency_contact_phone: data.emergency_contact_phone || '',
        emergency_contact_relation: data.emergency_contact_relation || '',
        pan: data.pan || '', aadhaar: data.aadhaar || '', uan: data.uan || '',
        pf_number: data.pf_number || '', esi_number: data.esi_number || '',
        bank_name: data.bank_name || '', bank_account: data.bank_account || '',
        bank_ifsc: data.bank_ifsc || '',
      });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this employee.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    // Depend on the COMPANY ID specifically, not the whole `scope` object: on a cold page
    // load `companyId` resolves asynchronously (HrmsContext fetches it after mount), and an
    // empty-array effect fired before that captured `scope={}` forever, 400ing both calls
    // silently and leaving these dropdowns permanently empty. `company_id` is a stable
    // primitive, so this re-fires exactly once when it actually resolves, not on every render.
    if (!scope.company_id) return;
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    getDesignations(scope).then(({ data }) => setDesignations(data?.designations || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  useEffect(() => {
    if (tab !== 'reporting' || hierarchy) return;
    getEmployeeHierarchy(userId, scope)
      .then(({ data }) => setHierarchy(data))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load the reporting chain.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // BR-028 — the Appointment Letter, if one was ever raised for this person, downloadable
  // from their profile. `uk` narrows the company-wide list to this one employee; an
  // EMPLOYEE-role viewer is additionally self-scoped server-side, so this same call is safe
  // whether HR opened someone else's profile or the employee opened their own.
  useEffect(() => {
    if (!canSeeAppointment || !employee?.source_uk) { setAppointmentLetter(null); return; }
    getAppointments({ ...scope, uk: employee.source_uk })
      .then(({ data }) => setAppointmentLetter(data?.appointments?.[0] || null))
      .catch(() => setAppointmentLetter(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee?.source_uk, canSeeAppointment]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const payload = {};
      Object.entries(form).forEach(([k, v]) => {
        if (k === 'base_salary') return;   // handled below, and only when permitted
        payload[k] = v === '' ? null : v;
      });
      if (canSetSalary && form.base_salary !== '') payload.base_salary = Number(form.base_salary);

      const { data } = await updateEmployee(userId, payload, scope);
      setEmployee(data);
      showSuccess('Profile saved');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the profile.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading employee…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;
  if (!employee) return null;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={UserCircle}
        title={employee.name}
        subtitle={[employee.designation || employee.legacy_designation,
                   employee.department || employee.legacy_department]
                   .filter(Boolean).join(' · ') || employee.email}
        actions={
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => navigate('/hrms/employees')}
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <ArrowLeft size={14} /> Directory
            </button>
            <button type="button" onClick={() => navigate(`/hrms/employees/${userId}/360`)}
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <LayoutGrid size={14} /> 360° View
            </button>
            {canWrite && (
              <button type="button" onClick={save} disabled={saving}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                <Save size={14} /> {saving ? 'Saving…' : 'Save'}
              </button>
            )}
          </div>
        }
      />

      {!employee.has_profile && (
        <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-muted)]">
          This person has no HR profile yet. Fill in the details below and save to create one.
        </div>
      )}

      <div className="flex gap-1 border-b border-[var(--border)] overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key} type="button" onClick={() => setTab(t.key)}
            className={`px-3.5 py-2 text-[12.5px] font-bold whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'job' && (
        <div className="space-y-4">
          <Row>
            <ReadOnly label="Email" value={employee.email} />
            <ReadOnly label="Mobile" value={employee.mobile} />
          </Row>
          <Row>
            <div>
              <label className={LABEL} htmlFor="p-code">Employee code</label>
              <input id="p-code" value={form.employee_code} onChange={set('employee_code')} disabled={!canWrite} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="p-status">Status</label>
              <select id="p-status" value={form.employment_status} onChange={set('employment_status')} disabled={!canWrite} className={FIELD}>
                {['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave'].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="p-dept">Department</label>
              <select id="p-dept" value={form.department_id} onChange={set('department_id')} disabled={!canWrite} className={FIELD}>
                <option value="">—</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="p-desig">Designation</label>
              <select id="p-desig" value={form.designation_id} onChange={set('designation_id')} disabled={!canWrite} className={FIELD}>
                <option value="">—</option>
                {designations.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="p-type">Employment type</label>
              <select id="p-type" value={form.employment_type} onChange={set('employment_type')} disabled={!canWrite} className={FIELD}>
                {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            {canSeeSalary && (
              <div>
                <label className={LABEL} htmlFor="p-salary">Base salary (monthly)</label>
                <input id="p-salary" type="number" min="0" value={form.base_salary}
                  onChange={set('base_salary')} disabled={!canSetSalary} className={FIELD} />
                {!canSetSalary && (
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">You can view but not change salary.</p>
                )}
              </div>
            )}
            <div>
              <label className={LABEL} htmlFor="p-joined">Joining date</label>
              <input id="p-joined" type="date" value={form.joined_on} onChange={set('joined_on')} disabled={!canWrite} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="p-resigned">Resignation date</label>
              <input id="p-resigned" type="date" value={form.resigned_on} onChange={set('resigned_on')} disabled={!canWrite} className={FIELD} />
            </div>
          </Row>

          {/* BR-028 — downloadable Appointment Letter, surfaced from the employee's own
              profile rather than only the HR-side Appointments board. */}
          {appointmentLetter && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <FileText size={16} className="text-[var(--accent-indigo)] shrink-0" />
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)] truncate">
                    Appointment Letter — {appointmentLetter.appointment_no}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">{appointmentLetter.status}</p>
                </div>
              </div>
              <button type="button" onClick={() => setShowLetter(true)}
                className="h-8 px-3 shrink-0 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)]">
                View / Print
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'personal' && (
        <Row>
          <div>
            <label className={LABEL} htmlFor="p-gender">Gender</label>
            <select id="p-gender" value={form.gender} onChange={set('gender')} disabled={!canWrite} className={FIELD}>
              <option value="">—</option>
              {['Male', 'Female', 'Other'].map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="p-dob">Date of birth</label>
            <input id="p-dob" type="date" value={form.date_of_birth} onChange={set('date_of_birth')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-blood">Blood group</label>
            <input id="p-blood" value={form.blood_group} onChange={set('blood_group')} disabled={!canWrite} className={FIELD} placeholder="e.g. O+" />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-addr">Address</label>
            <input id="p-addr" value={form.address} onChange={set('address')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-ecn">Emergency contact</label>
            <input id="p-ecn" value={form.emergency_contact_name} onChange={set('emergency_contact_name')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-ecp">Emergency phone</label>
            <input id="p-ecp" value={form.emergency_contact_phone} onChange={set('emergency_contact_phone')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-ecr">Relationship</label>
            <input id="p-ecr" value={form.emergency_contact_relation} onChange={set('emergency_contact_relation')} disabled={!canWrite} className={FIELD} />
          </div>
        </Row>
      )}

      {tab === 'statutory' && (
        <Row>
          <div>
            <label className={LABEL} htmlFor="p-pan">PAN</label>
            <input id="p-pan" value={form.pan} onChange={set('pan')} disabled={!canWrite} className={FIELD} placeholder="ABCDE1234F" />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-aadhaar">Aadhaar</label>
            <input id="p-aadhaar" value={form.aadhaar} onChange={set('aadhaar')} disabled={!canWrite} className={FIELD} placeholder="12 digits" />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-uan">UAN</label>
            <input id="p-uan" value={form.uan} onChange={set('uan')} disabled={!canWrite} className={FIELD} placeholder="12 digits" />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-pf">PF number</label>
            <input id="p-pf" value={form.pf_number} onChange={set('pf_number')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-esi">ESI number</label>
            <input id="p-esi" value={form.esi_number} onChange={set('esi_number')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-bank">Bank name</label>
            <input id="p-bank" value={form.bank_name} onChange={set('bank_name')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-acct">Account number</label>
            <input id="p-acct" value={form.bank_account} onChange={set('bank_account')} disabled={!canWrite} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="p-ifsc">IFSC</label>
            <input id="p-ifsc" value={form.bank_ifsc} onChange={set('bank_ifsc')} disabled={!canWrite} className={FIELD} placeholder="HDFC0001234" />
          </div>
        </Row>
      )}

      {/* ── Phase 11-R, Item 2 ── the SAME panel the candidate journey mounts. One
          component, two mount points: two near-identical panels would drift, and the one
          that drifts is the one showing a stale verification status.

          Keyed on `employee_code`, which is what hrms_documents stores as `owner_id` for an
          employee — not the user_id in the URL. */}
      {tab === 'documents' && (
        employee?.employee_code ? (
          <DocumentPanel
            ownerType="employee"
            ownerId={employee.employee_code}
            ownerName={employee.name}
          />
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">
            This employee has no employee code yet, so documents cannot be filed against
            them. One is issued when their onboarding completes.
          </p>
        )
      )}

      {tab === 'gmp' && (
        employee?.employee_code ? (
          <GmpPanel employeeCode={employee.employee_code} employeeName={employee.name} />
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">
            This employee has no employee code yet, so a GMP enrolment cannot be filed
            against them.
          </p>
        )
      )}

      {showLetter && appointmentLetter && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-y-auto py-8 px-4">
          <div className="w-full max-w-3xl">
            <div className="flex justify-end mb-2 gap-2">
              <button type="button" onClick={() => window.print()}
                className="h-9 px-3.5 rounded-lg bg-white text-[12px] font-bold text-slate-900">
                Print / Save as PDF
              </button>
              <button type="button" onClick={() => setShowLetter(false)}
                className="h-9 w-9 rounded-lg bg-white text-slate-900 flex items-center justify-center">
                <X size={16} />
              </button>
            </div>
            <AppointmentPaper appointment={appointmentLetter} showAcknowledgement={false} />
          </div>
        </div>
      )}

      {tab === 'reporting' && (
        <div className="space-y-5">
          {!hierarchy ? (
            <HrmsLoading label="Loading reporting chain…" />
          ) : (
            <>
              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Reports up to
                </p>
                {hierarchy.manager_chain.length === 0 ? (
                  <p className="text-[13px] text-[var(--text-muted)]">No reporting manager set.</p>
                ) : (
                  <ol className="space-y-1.5">
                    {hierarchy.manager_chain.map((m, i) => (
                      <li key={m.user_id} className="flex items-center gap-2 text-[13px]">
                        <span className="text-[var(--text-muted)]" style={{ paddingLeft: i * 14 }}>↳</span>
                        <span className={`font-semibold ${m.circular ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
                          {m.name}
                        </span>
                        {m.governance_role && (
                          <span className="text-[11px] text-[var(--text-muted)]">{m.governance_role}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Direct reports ({hierarchy.report_count})
                </p>
                {hierarchy.direct_reports.length === 0 ? (
                  <p className="text-[13px] text-[var(--text-muted)]">No direct reports.</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {hierarchy.direct_reports.map((r) => (
                      <button
                        key={r.user_id} type="button"
                        onClick={() => navigate(`/hrms/employees/${r.user_id}`)}
                        className="text-left p-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)] transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <Network size={13} className="text-[var(--text-muted)] shrink-0" />
                          <span className="text-[13px] font-semibold text-[var(--text-main)] truncate">{r.name}</span>
                        </div>
                        <p className="mt-0.5 text-[11.5px] text-[var(--text-muted)] truncate">{r.email}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default EmployeeProfile;
