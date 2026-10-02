import React, { useCallback, useEffect, useState } from 'react';
import { GraduationCap, Settings2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getOrientationPlans, createOrientationPlan, updateOrientationPlan,
  listOrientationAssignments, getOrientationAssignment, scheduleOrientationItem,
  completeOrientationItem, waiveOrientationItem, getDepartments,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, toneFor } from '../internal/internalKit';
import { Btn, Chip, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Orientation & Training (BA/Functional Design §22.3, screen SM-HR-057).
 *
 * One board, scoped by role — HR/Manager manage plan templates and every assignment; an
 * employee's own read is row-scoped server-side to just their own record, which is this
 * screen's "My Onboarding" (§22.3 step 202), not a separate page.
 *
 * A plan is a TEMPLATE; an assignment is a snapshot taken at activation. Editing a plan
 * here never changes anyone already assigned from it — the same reasoning the HR Letter
 * Generator applies to an issued letter.
 */
const ITEM_STATUS_TONE = { Pending: 'neutral', Scheduled: 'warn', Completed: 'good', Waived: 'neutral' };

const OrientationBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [managingPlans, setManagingPlans] = useState(false);
  const [openEmployeeCode, setOpenEmployeeCode] = useState(null);

  const canManage = can(CAP.INDUCTION_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listOrientationAssignments({ ...scope, limit: 100 });
      setRows(data?.assignments || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load orientation records.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <span className="font-semibold text-[var(--text-main)]">{r.employee_code}</span>
    ) },
    { key: 'items', label: 'Items', render: (r) => (
      <span className="text-[var(--text-main)]">
        {(r.items || []).filter((i) => i.status === 'Completed' || i.status === 'Waived').length}
        {' / '}{(r.items || []).length} resolved
      </span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.overall_status)}>{r.overall_status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenEmployeeCode(r.employee_code)}>Open</Btn>
      </div>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={GraduationCap}
        title="Induction & Training"
        subtitle="Onboarding plan assignment, scheduling and completion tracking (SM-HR-057)."
        actions={canManage && (
          <Btn tone="ghost" onClick={() => setManagingPlans(true)}>
            <Settings2 size={14} /> Plans
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading orientation records…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_code}</span>
                  <Chip tone={toneFor(r.overall_status)}>{r.overall_status}</Chip>
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  {(r.items || []).filter((i) => i.status === 'Completed' || i.status === 'Waived').length}
                  {' / '}{(r.items || []).length} resolved
                </p>
                <Btn tone="ghost" onClick={() => setOpenEmployeeCode(r.employee_code)}>Open</Btn>
              </div>
            )}
            keyOf={(r) => r.employee_code} />
        ) : (
          <HrmsEmpty icon={GraduationCap} title="No orientation records"
            hint="Assigned automatically when an employee is activated, from whatever plan(s) match their department." />
        )
      )}

      {managingPlans && (
        <PlansModal scope={scope} onClose={() => setManagingPlans(false)}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openEmployeeCode && (
        <AssignmentDetailModal employeeCode={openEmployeeCode} scope={scope} canManage={canManage}
          onClose={() => setOpenEmployeeCode(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const PlansModal = ({ scope, onClose, showSuccess, showError }) => {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    if (!scope.company_id) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getOrientationPlans({ ...scope, include_inactive: true });
      setPlans(data?.plans || []);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not load plans.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
    <Modal title="Orientation Plans" labelledBy="orientation-plans-title"
      subtitle="A plan applies company-wide unless a department is set." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Btn tone="primary" onClick={() => setEditing({ title: '', department_id: '', items: [], active: true })}>
            New Plan
          </Btn>
        </>
      )}
    >
      {loading ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
      ) : plans.length === 0 ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">No plans yet.</p>
      ) : (
        <div className="space-y-2">
          {plans.map((p) => (
            <button key={p.plan_no} type="button" onClick={() => setEditing(p)}
              className="w-full flex items-center justify-between rounded-lg border
                border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--input-bg)]">
              <div>
                <span className="text-[13px] font-semibold text-[var(--text-main)]">{p.title}</span>
                <span className="block text-[11px] text-[var(--text-muted)]">
                  {p.items?.length || 0} item(s){p.department_id ? ' · department-specific' : ' · company-wide'}
                </span>
              </div>
              <Chip tone={p.active ? 'good' : 'neutral'}>{p.active ? 'Active' : 'Inactive'}</Chip>
            </button>
          ))}
        </div>
      )}
    </Modal>
    {editing && (
      <PlanEditor plan={editing} scope={scope} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); load(); }}
        showSuccess={showSuccess} showError={showError} />
    )}
    </>
  );
};

const PlanEditor = ({ plan, scope, onClose, onSaved, showSuccess, showError }) => {
  const [title, setTitle] = useState(plan.title || '');
  const [departmentId, setDepartmentId] = useState(plan.department_id || '');
  const [departments, setDepartments] = useState([]);
  const [items, setItems] = useState(
    (plan.items || []).map((i) => ({ ...i })).length
      ? (plan.items || []).map((i) => ({ ...i }))
      : [{ topic: '', mandatory: true, materials_url: '' }]);
  const [active, setActive] = useState(plan.active !== false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!scope.company_id) return;
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  const updateItem = (idx, patch) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const addItem = () => setItems((prev) => [...prev, { topic: '', mandatory: true, materials_url: '' }]);
  const removeItem = (idx) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const submit = async () => {
    const cleanItems = items.filter((i) => i.topic.trim());
    if (!title.trim() || !cleanItems.length) {
      showError('A plan needs a title and at least one item.');
      return;
    }
    setBusy(true);
    try {
      const payload = {
        title: title.trim(), department_id: departmentId || null,
        items: cleanItems.map((i, idx) => ({ ...i, sequence: idx })), active,
      };
      if (plan.plan_no) {
        await updateOrientationPlan(plan.plan_no, payload, scope);
      } else {
        await createOrientationPlan(payload, scope);
      }
      showSuccess('Plan saved.');
      onSaved();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save this plan.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={plan.plan_no ? 'Edit Plan' : 'New Plan'} labelledBy="orientation-plan-editor-title"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="orient-plan-title">Title *</label>
        <input id="orient-plan-title" value={title} className={FIELD}
          onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="orient-plan-dept">Department (optional filter)</label>
        <select id="orient-plan-dept" value={departmentId} className={FIELD}
          onChange={(e) => setDepartmentId(e.target.value)}>
          <option value="">— Company-wide —</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        <label className={LABEL}>Items</label>
        {items.map((item, idx) => (
          <div key={idx} className="rounded-lg border border-[var(--border)] p-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <input value={item.topic} className={FIELD} placeholder="Topic"
                onChange={(e) => updateItem(idx, { topic: e.target.value })} />
              <button type="button" onClick={() => removeItem(idx)}
                className="text-[11px] font-bold text-[var(--accent-red)] shrink-0">Remove</button>
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-[12px] text-[var(--text-main)]">
                <input type="checkbox" checked={item.mandatory !== false}
                  onChange={(e) => updateItem(idx, { mandatory: e.target.checked })} />
                Mandatory
              </label>
              <input value={item.materials_url || ''} className={`${FIELD} flex-1`}
                placeholder="Materials link (optional)"
                onChange={(e) => updateItem(idx, { materials_url: e.target.value })} />
            </div>
          </div>
        ))}
        <Btn onClick={addItem}>Add item</Btn>
      </div>
      <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active
      </label>
    </Modal>
  );
};

const AssignmentDetailModal = ({ employeeCode, scope, canManage, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [scheduling, setScheduling] = useState(null); // item_id being scheduled
  const [waiving, setWaiving] = useState(null); // item_id being waived
  const [trainer, setTrainer] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [waiveReason, setWaiveReason] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getOrientationAssignment(employeeCode, scope);
      setDetail(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this record.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeCode]);

  useEffect(() => { load(); }, [load]);

  const act = async (fn, successMsg) => {
    setBusy(true);
    try {
      await fn();
      showSuccess(successMsg);
      setScheduling(null); setWaiving(null);
      await load();
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={employeeCode} labelledBy="orientation-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && detail && (
        detail.items?.length ? (
          <div className="space-y-3">
            <Chip tone={toneFor(detail.overall_status)}>{detail.overall_status}</Chip>
            {detail.items.map((item) => (
              <div key={item.item_id} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-semibold text-[var(--text-main)]">
                      {item.topic} {item.mandatory && <span className="text-[var(--accent-red)]">*</span>}
                    </p>
                    {item.trainer && (
                      <p className="text-[11.5px] text-[var(--text-muted)]">
                        {item.trainer} · {item.scheduled_at}
                      </p>
                    )}
                    {item.waived_reason && (
                      <p className="text-[11.5px] text-[var(--text-muted)]">Waived: {item.waived_reason}</p>
                    )}
                  </div>
                  <Chip tone={ITEM_STATUS_TONE[item.status] || 'neutral'}>{item.status}</Chip>
                </div>
                {canManage && !['Completed', 'Waived'].includes(item.status) && (
                  <div className="flex flex-wrap gap-2">
                    <Btn onClick={() => { setScheduling(item.item_id); setTrainer(''); setScheduledAt(''); }}>
                      Schedule
                    </Btn>
                    <Btn onClick={() => act(
                      () => completeOrientationItem(employeeCode, { item_id: item.item_id }, scope),
                      'Marked complete.')} disabled={busy}>
                      Mark Complete
                    </Btn>
                    {item.mandatory && (
                      <Btn tone="danger" onClick={() => { setWaiving(item.item_id); setWaiveReason(''); }}>
                        Waive
                      </Btn>
                    )}
                  </div>
                )}
                {scheduling === item.item_id && (
                  <div className="flex flex-wrap items-end gap-2 pt-1">
                    <input value={trainer} placeholder="Trainer" className={`${FIELD} max-w-[140px]`}
                      onChange={(e) => setTrainer(e.target.value)} />
                    <input value={scheduledAt} type="date" className={`${FIELD} max-w-[160px]`}
                      onChange={(e) => setScheduledAt(e.target.value)} />
                    <Btn tone="primary" disabled={busy || !trainer.trim() || !scheduledAt} onClick={() => act(
                      () => scheduleOrientationItem(employeeCode,
                        { item_id: item.item_id, trainer: trainer.trim(), scheduled_at: scheduledAt }, scope),
                      'Session scheduled.')}>
                      Confirm
                    </Btn>
                  </div>
                )}
                {waiving === item.item_id && (
                  <div className="flex flex-wrap items-end gap-2 pt-1">
                    <textarea value={waiveReason} rows={1} className={`${TEXTAREA} flex-1 min-w-[160px]`}
                      placeholder="Reason for waiver" onChange={(e) => setWaiveReason(e.target.value)} />
                    <Btn tone="danger" disabled={busy || !waiveReason.trim()} onClick={() => act(
                      () => waiveOrientationItem(employeeCode,
                        { item_id: item.item_id, reason: waiveReason.trim() }, scope),
                      'Item waived.')}>
                      Confirm Waiver
                    </Btn>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[12.5px] text-[var(--text-muted)]">
            No plan has been assigned yet — none of the active plan templates match this
            employee's department.
          </p>
        )
      )}
    </Modal>
  );
};

export default OrientationBoard;
