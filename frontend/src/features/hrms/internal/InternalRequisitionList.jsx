import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Building, Timer, Table2, ListTodo, Wallet } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import ApprovalDialog from '../recruitment/ApprovalDialog';
import InternalTracker from './InternalTracker';
import {
  getRequisitions, actOnRequisition, getRequisitionSla,
} from '../../../services/hrmsApi';
import { day, toneFor, money } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList,
} from './internalKit.jsx';
import { REQUISITION_SOP_LABEL, sopLabelFor } from './sopLabels';

/**
 * HRMS ▸ internal track — Headcount & Budget Approval.
 *
 * Raising a new requisition happens on the Overview screen now (its own "+ Raise" button);
 * this screen's job is narrower and comes after that: answer "what is this waiting on, and
 * can I clear it", with the budget figures a Management/Finance reviewer needs to answer it
 * shown plainly rather than buried in the detail page. `ApprovalDialog` is REUSED rather than
 * cloned — the chain differs in its states, not in what an approval dialog is.
 *
 * The action offered on each row is derived from the requisition's own state and the caller's
 * capabilities, never from a fixed set of buttons that 403 when pressed.
 */

/** state -> (action, who clears it, capability). One table, so the button, the label and the
 *  gate can never disagree with each other. */
const GATES = {
  'Pending HR Verification': {
    action: 'hr-verify', reject: 'hr-reject', cap: CAP.REQUISITION_REVIEW_HR,
    label: 'Verify', who: 'HR',
    blurb: 'HR checks the role and its justification are complete.',
  },
  'Pending Budget Approval': {
    action: 'budget-approve', reject: 'budget-reject',
    cap: CAP.REQUISITION_APPROVE_BUDGET, label: 'Approve budget',
    who: 'Management or Finance', band: true,
    blurb: 'Nothing may be sourced until the headcount and salary band are approved.',
  },
  'Pending Escalation': {
    action: 'escalate-approve', reject: 'escalate-reject', cap: CAP.REQUISITION_ESCALATE,
    label: 'Clear escalation', who: 'the reporting line',
    blurb: 'Raised above the sanctioned headcount, so it routes up the reporting line.',
  },
  'Pending Scorecard Approval': {
    action: 'scorecard-approve', reject: 'scorecard-reject', cap: CAP.SCORECARD_APPROVE,
    label: 'Approve', who: 'the hiring manager',
    blurb: 'Needs an approved position scorecard before it can be approved.',
  },
};

/**
 * The budget view this screen exists for: what the HOD asked for (`budget_hod_amount`) next
 * to what Management/Finance actually sanctioned (`budget_sanctioned_amount`), the derived
 * agreement status between them (Phase 11-R, Item 6 — `budget_status`/`budget_delta` are
 * never stored, always read fresh), and — once the gate clears — the approved headcount and
 * salary band that is the real answer to "what did Management approve". A requisition with
 * neither figure captured yet shows plainly as `Not Set` rather than a blank cell.
 */
const BudgetCell = ({ r }) => {
  const status = r.budget_status || 'Not Set';
  return (
    <div className="space-y-1 min-w-[150px]">
      <Chip tone={toneFor(status)}>{status}</Chip>
      {status !== 'Not Set' && (
        <div className="text-[11px] text-[var(--text-muted)] tabular-nums">
          HOD {money(r.budget_hod_amount)} · Sanctioned {money(r.budget_sanctioned_amount)}
        </div>
      )}
      {status === 'Mismatch' && r.budget_delta != null && (
        <div className="text-[11px] font-semibold text-[var(--accent-red)] tabular-nums">
          Δ {r.budget_delta > 0 ? '+' : ''}{money(r.budget_delta)}
        </div>
      )}
      {r.approved_salary_band_min != null ? (
        <div className="text-[11px] text-[var(--text-main)] tabular-nums">
          Band {money(r.approved_salary_band_min)}–{money(r.approved_salary_band_max)}
          {r.approved_headcount != null && ` · ${r.approved_headcount} approved`}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--text-muted)]">Band not approved</div>
      )}
    </div>
  );
};

const InternalRequisitionList = () => {
  const { scope, companyId, companyName, can } = useHrms();
  const navigate = useNavigate();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Two views of one screen. The QUEUE offers actions (verify, approve budget, clear
  // escalation); the TRACKER answers "where has everything got to, and what is late"
  // (Phase INT-7, Annexure C). Same route, so neither navigation list changes.
  const [view, setView] = useState('queue');
  const [deciding, setDeciding] = useState(null);
  const [busy, setBusy] = useState(false);
  const [slaFor, setSlaFor] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getRequisitions({ ...scope, limit: 200 });
      setRows(data?.requisitions || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load internal requisitions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const gateFor = (row) => {
    const gate = GATES[row.approval_status];
    return gate && can(gate.cap) ? gate : null;
  };

  const act = async (row, action, remarks, _salary, budget) => {
    setBusy(true);
    try {
      await actOnRequisition(row.request_no, { action, remarks, ...(budget || {}) }, scope);
      showSuccess(`${row.request_no} — ${action.replace('-', ' ')}d`);
      setDeciding(null);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'req', label: 'Requisition',
      // A link rather than a clickable row: the row already carries approve/reject buttons,
      // and a row that both navigates and acts is a row that navigates by accident.
      render: (r) => (
        <>
          <Link to={`/hrms/internal-requisitions/${r.request_no}`}
                className="font-semibold text-[var(--text-main)]
                           hover:text-[var(--accent-indigo)] hover:underline">
            {r.designation_name}
          </Link>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.request_no} · {r.department_name || '—'}
          </span>
        </>
      ) },
    { key: 'requested', label: 'Requested', align: 'right',
      // What the HOD actually asked for when they raised it — seats and the CTC they
      // proposed — kept separate from the Budget column so a reviewer can see the ask
      // and the sanctioned figure side by side rather than one overwriting the other.
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.vacancy} seat{r.vacancy === 1 ? '' : 's'}</span>
          {r.offering_ctc != null && (
            <span className="block text-[11px] text-[var(--text-muted)] tabular-nums">
              {money(r.offering_ctc)} CTC
            </span>
          )}
        </>
      ) },
    { key: 'budget', label: 'Budget', render: (r) => <BudgetCell r={r} /> },
    { key: 'stage', label: 'Waiting on',
      render: (r) => {
        const gate = GATES[r.approval_status];
        const sop = sopLabelFor(r.approval_status, REQUISITION_SOP_LABEL);
        return (
          <>
            <Chip tone={toneFor(r.approval_status)}>{r.approval_status}</Chip>
            {sop && (
              <span className="block text-[10.5px] text-[var(--text-muted)] italic mt-0.5">
                SOP: {sop}
              </span>
            )}
            {gate && (
              <span className="block text-[11px] text-[var(--text-muted)] mt-1">
                {gate.who}
              </span>
            )}
          </>
        );
      } },
    { key: 'actions', label: '', align: 'right',
      render: (r) => {
        const gate = gateFor(r);
        return (
          <div className="flex flex-col items-end gap-1.5">
            {gate && (
              <Btn tone="primary" onClick={() => setDeciding({ row: r, gate })}>
                {gate.label}
              </Btn>
            )}
            <Btn tone="ghost" onClick={() => setSlaFor(r)}>
              <Timer size={13} /> SLA
            </Btn>
          </div>
        );
      } },
  ];

  const renderCard = (r) => {
    const gate = gateFor(r);
    return (
      <div className="space-y-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[13px] font-bold text-[var(--text-main)]">
              {r.designation_name}
            </p>
            <p className="text-[11.5px] text-[var(--text-muted)]">{r.request_no}</p>
          </div>
          <div className="text-right">
            <Chip tone={toneFor(r.approval_status)}>{r.approval_status}</Chip>
            {sopLabelFor(r.approval_status, REQUISITION_SOP_LABEL) && (
              <span className="block text-[10.5px] text-[var(--text-muted)] italic mt-0.5">
                SOP: {sopLabelFor(r.approval_status, REQUISITION_SOP_LABEL)}
              </span>
            )}
          </div>
        </div>
        <Facts items={[
          { label: 'Requested', value: `${r.vacancy} seat${r.vacancy === 1 ? '' : 's'}`
            + (r.offering_ctc != null ? ` · ${money(r.offering_ctc)} CTC` : '') },
          { label: 'Budget', value: r.budget_status || 'Not Set' },
          { label: 'Band',
            value: r.approved_salary_band_min != null
              ? `${money(r.approved_salary_band_min)}–${money(r.approved_salary_band_max)}`
              : 'not approved' },
          { label: 'Raised', value: day(r.created_at) },
        ]} />
        <div className="flex gap-2 flex-wrap">
          {gate && (
            <Btn tone="primary" onClick={() => setDeciding({ row: r, gate })}>
              {gate.label}
            </Btn>
          )}
          <Btn tone="ghost" onClick={() => setSlaFor(r)}>SLA</Btn>
          <Btn tone="ghost"
               onClick={() => navigate(`/hrms/internal-requisitions/${r.request_no}`)}>
            Open
          </Btn>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Wallet}
        title="Headcount & Budget Approval"
        subtitle={`${companyName || 'This company'}'s open requisitions — what was `
          + 'requested against what Management or Finance has sanctioned. Raise a new '
          + 'request from the Overview screen.'}
      />
      <HrmsScopeBar />

      <div className="flex items-center gap-2" role="tablist" aria-label="View">
        {[
          { key: 'queue', label: 'Action queue', icon: <ListTodo size={14} /> },
          { key: 'tracker', label: 'Tracker', icon: <Table2 size={14} /> },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={view === tab.key}
            onClick={() => setView(tab.key)}
            className={`flex items-center gap-1.5 h-9 px-3 rounded-lg border
              text-[12.5px] ${view === tab.key
              ? 'border-[var(--accent)] text-[var(--text-main)] font-semibold'
              : 'border-[var(--border)] text-[var(--text-muted)]'}`}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {view === 'tracker' && <InternalTracker />}

      {view === 'queue' && loading && <HrmsLoading label="Loading internal requisitions…" />}
      {view === 'queue' && error && !loading && <HrmsError message={error} onRetry={load} />}

      {view === 'queue' && !loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.request_no}
          empty={<HrmsEmpty
            icon={Building}
            title="No internal requisitions"
            hint="Raise one from the Overview screen — it's created on the internal track."
          />}
        />
      )}

      {deciding && (
        <ApprovalDialog
          title={`${deciding.gate.label} — ${deciding.row.request_no}`}
          subtitle={deciding.gate.blurb}
          approveLabel={deciding.gate.label}
          requisition={deciding.row}
          showBudgetBand={!!deciding.gate.band}
          busy={busy}
          onApprove={(remarks, salary, budget) =>
            act(deciding.row, deciding.gate.action, remarks, salary, budget)}
          onReject={(remarks) => act(deciding.row, deciding.gate.reject, remarks)}
          onClose={() => setDeciding(null)}
        />
      )}

      {slaFor && (
        <SlaModal row={slaFor} scope={scope} onClose={() => setSlaFor(null)} />
      )}
    </div>
  );
};

/** Milestone targets against actuals. Everything except the actual timestamps is computed
 *  server-side on read, so this renders the answer rather than working one out. */
const SlaModal = ({ row, scope, onClose }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getRequisitionSla(row.request_no, scope)
      .then(({ data: d }) => setData(d))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the SLA.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Modal
      title={`SLA — ${row.request_no}`} labelledBy="sla-title"
      subtitle={data?.basis} onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {error && <HrmsError message={error} />}
      {!data && !error && <HrmsLoading label="Reading milestones…" />}
      {data && (
        <ul className="space-y-2">
          {data.milestones.map((m) => (
            <li key={m.key}
              className="flex items-start justify-between gap-3 rounded-lg
                border border-[var(--border)] px-3 py-2.5">
              <div className="min-w-0">
                <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                  {m.label}
                </p>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {m.target_working_days != null
                    ? `${m.target_working_days} working days from ${m.measured_from}`
                    : `Due ${day(m.due_on)}`}
                  {m.working_days_taken != null && ` · took ${m.working_days_taken}`}
                </p>
              </div>
              <Chip tone={toneFor(m.status)}>{m.status.replace('_', ' ')}</Chip>
            </li>
          ))}
          {!data.milestones.length && (
            <p className="text-[12.5px] text-[var(--text-muted)]">
              {data.reason || 'No milestones apply.'}
            </p>
          )}
        </ul>
      )}
    </Modal>
  );
};

export default InternalRequisitionList;
