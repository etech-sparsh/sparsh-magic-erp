import React, { useCallback, useEffect, useState } from 'react';
import { FileText, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientRequisitions, createClientRequisition, updateClientRequisition,
  actOnClientRequisition,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, money } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { PanelHeader } from './clientKit.jsx';
import { useClientScope } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ Need Mapping → Manpower Requisition → feasibility.
 *
 * PRO-fit SOP section 7. The client states the need and the budget; Sparsh assesses
 * whether the engagement is deliverable before a single CV is sourced.
 *
 * -- The screen mirrors who acts, not what the record looks like ------------------
 * A client sees "raise a requirement" and their own two forms. Sparsh sees a review
 * queue. Both read the same endpoint, which decides what each may see and do — this
 * screen only renders the consequence. Every control is capability-gated so nothing
 * offers an action the API will refuse.
 */

const STATUS_TONE = {
  'Need Mapping': 'warn',
  'Manpower Requisition': 'warn',
  'Pending Feasibility': 'warn',
  Approved: 'good',
  Rejected: 'bad',
  Closed: 'neutral',
};

const FEASIBILITY = [
  ['role_clarity', 'Role clarity'],
  ['compensation_competitive', 'Compensation competitiveness'],
  ['timeline_realistic', 'Realistic timeline'],
];

const ClientRequisitions = ({ embedded, onChanged }) => {
  // Every mutation already reloads this screen's own list. The workspace's stage rail
  // counts the same records independently, so it has to be told as well -- otherwise
  // acting inside a panel leaves the rail above it showing figures from before the
  // action, which reads as the action not having worked.
  const refresh = () => { load(); onChanged?.(); };
  const { companyId, can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [raising, setRaising] = useState(false);
  const [editing, setEditing] = useState(null);
  const [reviewing, setReviewing] = useState(null);
  const [busy, setBusy] = useState(false);

  const canRaise = can(CAP.CLIENT_REQUISITION_WRITE);
  const canReview = can(CAP.CLIENT_REQUISITION_REVIEW);

  const load = useCallback(async () => {
    if (!companyId && !isInternal) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getClientRequisitions({ ...scope, limit: 200 });
      setRows(data?.client_requisitions || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load requisitions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, isInternal, JSON.stringify(scope)]);

  useEffect(() => { load(); }, [load]);

  const act = async (crNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientRequisition(crNo, { action, ...payload }, scope);
      showSuccess(`${crNo} updated`);
      setEditing(null);
      setReviewing(null);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'cr', label: 'Requisition',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.cr_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.role_title || r.role_need?.slice(0, 60) || '—'}
          </span>
        </>
      ) },
    { key: 'dept', label: 'Department',
      render: (r) => <span className="text-[var(--text-muted)]">{r.department_name || '—'}</span> },
    { key: 'band', label: 'Salary range',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)]">
          {r.salary_range_min != null
            ? `${money(r.salary_range_min)} – ${money(r.salary_range_max)}`
            : '—'}
        </span>
      ) },
    { key: 'urgency', label: 'Urgency',
      render: (r) => <span className="text-[var(--text-muted)]">{r.urgency || '—'}</span> },
    { key: 'raised', label: 'Raised',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.created_at)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.raised_by_name || '—'}
          </span>
        </>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <Chip tone={STATUS_TONE[r.status] || 'neutral'}>{r.status}</Chip> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canRaise && ['Need Mapping', 'Manpower Requisition'].includes(r.status) && (
            <Btn onClick={() => setEditing(r)}>Continue</Btn>
          )}
          {canReview && r.status === 'Pending Feasibility' && (
            <Btn tone="primary" onClick={() => setReviewing(r)}>Review</Btn>
          )}
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.cr_no}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.role_title || 'Need Mapping in progress'}
          </p>
        </div>
        <Chip tone={STATUS_TONE[r.status] || 'neutral'}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Department', value: r.department_name || '—' },
        { label: 'Urgency', value: r.urgency || '—' },
        { label: 'Range', value: r.salary_range_min != null
          ? `${money(r.salary_range_min)} – ${money(r.salary_range_max)}` : '—' },
        { label: 'Raised', value: day(r.created_at) },
      ]} />
      <div className="flex items-center gap-1.5">
        {canRaise && ['Need Mapping', 'Manpower Requisition'].includes(r.status) && (
          <Btn onClick={() => setEditing(r)}>Continue</Btn>
        )}
        {canReview && r.status === 'Pending Feasibility' && (
          <Btn tone="primary" onClick={() => setReviewing(r)}>Review</Btn>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader
          title="Client requisitions"
          subtitle="Need Mapping, then the Manpower Requisition, then Sparsh's feasibility and budget review (SOP section 7)"
          actions={canRaise && (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise a requirement
          </Btn>
        )}
        />
      ) : (
        <>
          <HrmsPageHeader
            icon={FileText}
            title="Client requisitions"
            subtitle="Need Mapping, then the Manpower Requisition, then Sparsh's feasibility and budget review (SOP section 7)"
            actions={canRaise && (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise a requirement
          </Btn>
        )}
          />
          <HrmsScopeBar />
        </>
      )}

      <p className="text-[11.5px] text-[var(--text-muted)]">
        No sourcing begins until both forms are complete and Sparsh has assessed role
        clarity, pay competitiveness and the timeline. A rejected requisition cannot
        progress — raise a new one if the need still stands.
      </p>

      {loading && <HrmsLoading label="Loading requisitions…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.cr_no}
          empty={<HrmsEmpty
            icon={FileText}
            title="No client requisitions yet"
            hint={canRaise
              ? 'Raise a requirement to start the Need Mapping Form.'
              : 'Nothing has been raised by a client yet.'}
          />}
        />
      )}

      {raising && (
        <NeedMappingModal
          busy={busy}
          onClose={() => setRaising(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await createClientRequisition(payload, scope);
              showSuccess(`${data.cr_no} raised — complete the requisition form next`);
              setRaising(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be raised.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editing && (
        <RequisitionFormModal
          row={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSave={async (payload) => {
            setBusy(true);
            try {
              await updateClientRequisition(editing.cr_no, payload, scope);
              showSuccess(`${editing.cr_no} saved`);
              refresh();
              setEditing(null);
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be saved.');
            } finally {
              setBusy(false);
            }
          }}
          onAdvance={(action) => act(editing.cr_no, action)}
        />
      )}

      {reviewing && (
        <FeasibilityModal
          row={reviewing}
          busy={busy}
          onClose={() => setReviewing(null)}
          onDecide={(action, payload) => act(reviewing.cr_no, action, payload)}
        />
      )}
    </div>
  );
};

/** SOP section 7 step 1 — the client says why they need somebody. */
const NeedMappingModal = ({ busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    business_context: '', role_need: '', urgency: 'Normal',
    engagement_expectations: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const ready = form.business_context.trim() && form.role_need.trim();

  return (
    <Modal
      title="Need Mapping Form"
      subtitle="Why the role is needed. The formal requisition comes next."
      labelledBy="cr-nmf"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready} onClick={() => onSubmit(form)}>
            {busy ? 'Raising…' : 'Raise'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="cr-context">Business context *</label>
        <textarea id="cr-context" rows={3} className={TEXTAREA}
          placeholder="What is happening in the business that creates this need?"
          value={form.business_context} onChange={set('business_context')} />
      </div>
      <div>
        <label className={LABEL} htmlFor="cr-need">Role need *</label>
        <textarea id="cr-need" rows={3} className={TEXTAREA}
          placeholder="Who you need, and what they will do."
          value={form.role_need} onChange={set('role_need')} />
      </div>
      <div>
        <label className={LABEL} htmlFor="cr-urgency">Urgency</label>
        <select id="cr-urgency" className={FIELD} value={form.urgency}
          onChange={set('urgency')}>
          {['Immediate', 'High', 'Normal'].map((u) => <option key={u}>{u}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="cr-expect">What you expect from the engagement</label>
        <textarea id="cr-expect" rows={2} className={TEXTAREA}
          placeholder="Timelines, shortlist size, anything else."
          value={form.engagement_expectations} onChange={set('engagement_expectations')} />
      </div>
    </Modal>
  );
};

/** SOP section 7 step 2 — the client formalises the role and the budget. */
const RequisitionFormModal = ({ row, busy, onClose, onSave, onAdvance }) => {
  const [form, setForm] = useState({
    role_title: row.role_title || '', department_name: row.department_name || '',
    reporting_line: row.reporting_line || '',
    salary_range_min: row.salary_range_min ?? '', salary_range_max: row.salary_range_max ?? '',
    employment_type: row.employment_type || 'Permanent',
    role_level: row.role_level || '', vacancies: row.vacancies ?? 1,
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const atNeedMapping = row.status === 'Need Mapping';

  const payload = () => ({
    ...form,
    role_level: form.role_level || null,
    salary_range_min: form.salary_range_min === '' ? null : Number(form.salary_range_min),
    salary_range_max: form.salary_range_max === '' ? null : Number(form.salary_range_max),
    vacancies: Number(form.vacancies) || 1,
  });

  return (
    <Modal
      title={`Manpower Requisition — ${row.cr_no}`}
      subtitle="Role, reporting line and the budget you are approving for it"
      labelledBy="cr-mrf"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Close</Btn>
          {atNeedMapping ? (
            <Btn tone="primary" disabled={busy}
              onClick={() => onAdvance('submit-need-mapping')}>
              Continue to the requisition form
            </Btn>
          ) : (
            <>
              <Btn disabled={busy} onClick={() => onSave(payload())}>Save</Btn>
              <Btn tone="primary" disabled={busy}
                onClick={() => onAdvance('submit-requisition')}>
                Send to Sparsh
              </Btn>
            </>
          )}
        </>
      )}
    >
      <Facts items={[
        { label: 'Status', value: row.status },
        { label: 'Urgency', value: row.urgency || '—' },
      ]} />
      <p className="text-[12px] text-[var(--text-muted)]">{row.role_need}</p>

      {atNeedMapping ? (
        <p className="text-[12px] text-[var(--accent-orange)] font-semibold">
          The Need Mapping Form is done. Continue to fill in the role details and the
          budget, which is what Sparsh reviews.
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="cr-title">Role title *</label>
              <input id="cr-title" className={FIELD} value={form.role_title}
                onChange={set('role_title')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-dept">Department *</label>
              <input id="cr-dept" className={FIELD} value={form.department_name}
                onChange={set('department_name')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-report">Reporting line *</label>
              <input id="cr-report" className={FIELD} value={form.reporting_line}
                onChange={set('reporting_line')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-type">Employment type</label>
              <select id="cr-type" className={FIELD} value={form.employment_type}
                onChange={set('employment_type')}>
                {['Permanent', 'Contractual', 'Replacement', 'Volume Hiring']
                  .map((v) => <option key={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-min">Salary range, from *</label>
              <input id="cr-min" type="number" min="1" className={FIELD}
                value={form.salary_range_min} onChange={set('salary_range_min')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-max">Salary range, to *</label>
              <input id="cr-max" type="number" min="1" className={FIELD}
                value={form.salary_range_max} onChange={set('salary_range_max')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-level">Role level</label>
              <select id="cr-level" className={FIELD} value={form.role_level}
                onChange={set('role_level')}>
                <option value="">Not set</option>
                {['Junior / Executive', 'Mid-level / Specialist', 'Managerial',
                  'Senior Leadership'].map((v) => <option key={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="cr-vac">Vacancies</label>
              <input id="cr-vac" type="number" min="1" className={FIELD}
                value={form.vacancies} onChange={set('vacancies')} />
            </div>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Managerial and Senior Leadership roles need a reference check before the offer
            is released, so the level is worth setting.
          </p>
        </>
      )}
    </Modal>
  );
};

/** SOP section 7 step 3 — Sparsh's feasibility and budget review. */
const FeasibilityModal = ({ row, busy, onClose, onDecide }) => {
  const [checks, setChecks] = useState({
    role_clarity: true, compensation_competitive: true, timeline_realistic: true,
  });
  const [remarks, setRemarks] = useState('');
  const allPass = FEASIBILITY.every(([k]) => checks[k]);

  return (
    <Modal
      title={`Feasibility review — ${row.cr_no}`}
      subtitle="Assess the role before any sourcing begins (SOP section 7 step 3)"
      labelledBy="cr-feas"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" disabled={busy || !remarks.trim()}
            onClick={() => onDecide('feasibility-reject', { remarks })}>
            Reject
          </Btn>
          <Btn disabled={busy || !remarks.trim()}
            onClick={() => onDecide('feasibility-return', { remarks })}>
            Return to client
          </Btn>
          <Btn tone="primary" disabled={busy || !allPass}
            onClick={() => onDecide('feasibility-approve', { ...checks, remarks })}>
            Approve
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Role', value: row.role_title || '—' },
        { label: 'Department', value: row.department_name || '—' },
        { label: 'Reporting to', value: row.reporting_line || '—' },
        { label: 'Range', value: row.salary_range_min != null
          ? `${money(row.salary_range_min)} – ${money(row.salary_range_max)}` : '—' },
        { label: 'Level', value: row.role_level || 'Not set' },
        { label: 'Vacancies', value: row.vacancies ?? '—' },
      ]} />
      <p className="text-[12px] text-[var(--text-muted)]">{row.business_context}</p>

      <div>
        <p className={LABEL}>Assessment</p>
        <div className="mt-1.5 space-y-1.5">
          {FEASIBILITY.map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-[12.5px]
              text-[var(--text-main)]">
              <input type="checkbox" checked={!!checks[key]}
                onChange={(e) => setChecks((c) => ({ ...c, [key]: e.target.checked }))} />
              {label}
            </label>
          ))}
        </div>
        {!allPass && (
          <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
            An approval cannot record a failed check. Return it to the client or reject it.
          </p>
        )}
      </div>

      <div>
        <label className={LABEL} htmlFor="cr-remarks">Remarks</label>
        <textarea id="cr-remarks" rows={3} className={TEXTAREA}
          placeholder="Required when returning or rejecting."
          value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default ClientRequisitions;
