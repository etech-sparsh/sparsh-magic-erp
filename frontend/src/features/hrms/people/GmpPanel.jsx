import React, { useCallback, useEffect, useState } from 'react';
import { HeartPulse, Plus, Trash2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getGmp, saveGmp } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Group Mediclaim Policy (§22 employee profile "GMP section").
 *
 * One current enrolment per employee, HR-administered in place — mounted as one of
 * EmployeeProfile's tabs. An employee sees their own read-only; HR sees and edits.
 */
const GmpPanel = ({ employeeCode, employeeName }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [record, setRecord] = useState(undefined); // undefined = loading, null = none filed
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);

  const canWrite = can(CAP.GMP_WRITE);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await getGmp(employeeCode, scope);
      setRecord(data || null);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the GMP enrolment.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeCode, scope.company_id]);

  useEffect(() => { load(); }, [load]);

  if (record === undefined && !error) return <HrmsLoading label="Loading GMP enrolment…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  return (
    <div className="space-y-4">
      {!record ? (
        <HrmsEmpty icon={HeartPulse} title="No GMP enrolment on file"
          hint={canWrite ? 'Add this employee to the Group Mediclaim Policy.' : undefined} />
      ) : (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <Chip tone={record.status === 'Active' ? 'good' : 'neutral'}>{record.status}</Chip>
          </div>
          <Facts items={[
            { label: 'Insurer', value: record.insurer },
            { label: 'Policy number', value: record.policy_number },
            { label: 'Sum insured', value: record.sum_insured != null ? `₹${Number(record.sum_insured).toLocaleString('en-IN')}` : '—' },
            { label: 'Enrolled on', value: record.enrolled_on },
          ]} />
          <div>
            <p className={LABEL}>Dependants</p>
            {(record.dependents || []).length ? (
              <ul className="space-y-1.5">
                {record.dependents.map((d, i) => (
                  <li key={i} className="text-[12.5px] text-[var(--text-main)]">
                    {d.name} <span className="text-[var(--text-muted)]">
                      {[d.relation, d.date_of_birth].filter(Boolean).join(' · ')}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-[var(--text-muted)]">None recorded.</p>
            )}
          </div>
          {record.remarks && (
            <p className="text-[12px] text-[var(--text-muted)]">{record.remarks}</p>
          )}
        </div>
      )}
      {canWrite && (
        <Btn tone="primary" onClick={() => setEditing(true)}>
          {record ? 'Edit enrolment' : 'Add enrolment'}
        </Btn>
      )}
      {editing && (
        <GmpModal employeeCode={employeeCode} employeeName={employeeName} record={record}
          scope={scope} onClose={() => setEditing(false)}
          onDone={() => { setEditing(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const GmpModal = ({ employeeCode, employeeName, record, scope, onClose, onDone, showSuccess, showError }) => {
  const [insurer, setInsurer] = useState(record?.insurer || '');
  const [policyNumber, setPolicyNumber] = useState(record?.policy_number || '');
  const [sumInsured, setSumInsured] = useState(record?.sum_insured ?? '');
  const [enrolledOn, setEnrolledOn] = useState(record?.enrolled_on || '');
  const [status, setStatus] = useState(record?.status || 'Active');
  const [remarks, setRemarks] = useState(record?.remarks || '');
  const [dependents, setDependents] = useState(record?.dependents?.length ? record.dependents : []);
  const [busy, setBusy] = useState(false);

  const addDependent = () => setDependents((d) => [...d, { name: '', relation: '', date_of_birth: '' }]);
  const updateDependent = (i, key, value) =>
    setDependents((d) => d.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)));
  const removeDependent = (i) => setDependents((d) => d.filter((_, idx) => idx !== i));

  const submit = async () => {
    setBusy(true);
    try {
      await saveGmp(employeeCode, {
        insurer: insurer.trim() || undefined,
        policy_number: policyNumber.trim() || undefined,
        sum_insured: sumInsured === '' ? undefined : Number(sumInsured),
        enrolled_on: enrolledOn || undefined,
        status,
        remarks: remarks.trim() || undefined,
        dependents: dependents.filter((d) => d.name?.trim()),
      }, scope);
      showSuccess('GMP enrolment saved.');
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the GMP enrolment.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`GMP — ${employeeName || employeeCode}`} labelledBy="gmp-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="gmp-insurer">Insurer</label>
          <input id="gmp-insurer" value={insurer} className={FIELD} onChange={(e) => setInsurer(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="gmp-policy">Policy number</label>
          <input id="gmp-policy" value={policyNumber} className={FIELD} onChange={(e) => setPolicyNumber(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="gmp-sum">Sum insured (₹)</label>
          <input id="gmp-sum" type="number" min="0" value={sumInsured} className={FIELD}
            onChange={(e) => setSumInsured(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="gmp-enrolled">Enrolled on</label>
          <input id="gmp-enrolled" type="date" value={enrolledOn} className={FIELD}
            onChange={(e) => setEnrolledOn(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="gmp-status">Status</label>
          <select id="gmp-status" value={status} className={FIELD} onChange={(e) => setStatus(e.target.value)}>
            <option value="Active">Active</option>
            <option value="Inactive">Inactive</option>
          </select>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className={LABEL}>Dependants</label>
          <Btn onClick={addDependent}><Plus size={13} /> Add</Btn>
        </div>
        {dependents.length === 0 && (
          <p className="text-[12px] text-[var(--text-muted)]">None added.</p>
        )}
        <div className="space-y-2">
          {dependents.map((d, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-center">
              <input placeholder="Name" value={d.name} className={FIELD}
                onChange={(e) => updateDependent(i, 'name', e.target.value)} />
              <input placeholder="Relation" value={d.relation || ''} className={FIELD}
                onChange={(e) => updateDependent(i, 'relation', e.target.value)} />
              <input type="date" value={d.date_of_birth || ''} className={FIELD}
                onChange={(e) => updateDependent(i, 'date_of_birth', e.target.value)} />
              <button type="button" onClick={() => removeDependent(i)}
                className="h-9 w-9 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="gmp-remarks">Remarks</label>
        <textarea id="gmp-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default GmpPanel;
