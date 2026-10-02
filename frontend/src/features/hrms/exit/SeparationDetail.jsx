import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft, UserMinus, ClipboardList, ShieldCheck, Laptop, KeyRound, MessageSquareText,
  Wallet, Plus, HeartHandshake,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getSeparation, decideSeparation, approveSeparation, withdrawSeparation, closeSeparation,
  getHandoverTasks, createHandoverTask, updateHandoverTask, acceptHandoverTask,
  getClearanceTasks, createClearanceTask, actOnClearanceTask,
  getAssetReturns, createAssetReturn, updateAssetReturn,
  getAccessClearances, createAccessClearance, updateAccessClearance,
  getExitInterview, saveExitInterview,
  getFnf, saveFnf, approveFnf, markFnfPaid,
  saveNomineeDetails,
} from '../../../services/hrmsApi';
import { CARD, FIELD, LABEL, TEXTAREA, SECTION_TITLE, day, money, toneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Exit Management ▸ one case, end to end (§7.18, §22.2, §7.21).
 *
 * Composed from SEVEN existing endpoints rather than a single "everything" call — the same
 * choice InternalRequisitionDetail makes and for the same reason: each of handover,
 * clearance, asset returns, access clearance, the exit interview and F&F is already the
 * authority on its own part, so a combined endpoint would be a second thing to keep in step.
 * The separation record itself carries a `progress` summary (counts only) so this page does
 * not need all seven before it can render something useful.
 *
 * -- No payroll engine behind F&F ----------------------------------------------------------
 * §7.13 is unbuilt, so the F&F section shows and edits figures entered by hand rather than
 * anything computed from attendance or a salary structure. Asset/clearance recoveries ARE
 * rolled up automatically — those numbers already live in this module's own records.
 */

const A_LITTLE = 'text-[11px] text-[var(--text-muted)]';

const Section = ({ icon: Icon, title, subtitle, actions, children }) => (
  <section className={CARD}>
    <div className="flex items-start justify-between gap-3 mb-3.5">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className="h-8 w-8 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]
          flex items-center justify-center shrink-0">
          <Icon size={15} />
        </div>
        <div className="min-w-0">
          <h2 className="text-[13.5px] font-bold text-[var(--text-main)]">{title}</h2>
          {subtitle && <p className={`${A_LITTLE} mt-0.5`}>{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
    {children}
  </section>
);

const SeparationDetail = () => {
  const { sepNo } = useParams();
  const navigate = useNavigate();
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [sep, setSep] = useState(null);
  const [handover, setHandover] = useState([]);
  const [clearance, setClearance] = useState([]);
  const [assets, setAssets] = useState([]);
  const [access, setAccess] = useState([]);
  const [interview, setInterview] = useState(null);
  const [fnf, setFnf] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Every modal this page can open, named by what it does. One flag each keeps the JSX at
  // the bottom flat instead of a nested ternary tree.
  const [deciding, setDeciding] = useState(false);
  const [approving, setApproving] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [closing, setClosing] = useState(false);
  const [addingHandover, setAddingHandover] = useState(false);
  const [acceptingHandover, setAcceptingHandover] = useState(null);
  const [addingClearance, setAddingClearance] = useState(false);
  const [actingClearance, setActingClearance] = useState(null);
  const [addingAsset, setAddingAsset] = useState(false);
  const [updatingAsset, setUpdatingAsset] = useState(null);
  const [addingAccess, setAddingAccess] = useState(false);
  const [updatingAccess, setUpdatingAccess] = useState(null);
  const [editingInterview, setEditingInterview] = useState(false);
  const [editingFnf, setEditingFnf] = useState(false);
  const [decidingFnf, setDecidingFnf] = useState(false);
  const [markingPaid, setMarkingPaid] = useState(false);
  const [editingNominee, setEditingNominee] = useState(false);

  const canManage = can(CAP.SEPARATION_MANAGE);
  const canApproveSep = can(CAP.SEPARATION_APPROVE);
  const canHandoverWrite = can(CAP.HANDOVER_WRITE);
  const canHandoverApprove = can(CAP.HANDOVER_APPROVE);
  const canClearanceManage = can(CAP.CLEARANCE_MANAGE);
  const canClearanceAct = can(CAP.CLEARANCE_ACT);
  const canInterviewWrite = can(CAP.EXIT_INTERVIEW_WRITE);

  // Built here rather than inline so the Exit Interview section can tell "no record" from
  // "a record with nothing this screen can show" -- see that section for why that matters.
  const interviewFacts = !interview ? [] : [
    { label: 'Reason', value: interview.reason },
    { label: 'Manager Rating', value: interview.manager_rating },
    { label: 'Team Rating', value: interview.team_rating },
    { label: 'Work Rating', value: interview.work_rating },
    { label: 'Compensation Rating', value: interview.compensation_rating },
    { label: 'Rehire Recommended', value: interview.rehire_recommendation == null ? null
      : (interview.rehire_recommendation ? 'Yes' : 'No') },
    interview.comments ? { label: 'Comments', value: interview.comments } : null,
  ].filter((i) => i && i.value != null && i.value !== '');
  const canFnfPrepare = can(CAP.FNF_PREPARE);
  const canFnfApprove = can(CAP.FNF_APPROVE);

  const load = useCallback(async () => {
    if (!companyId || !sepNo) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await getSeparation(sepNo, scope);
      setSep(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load this separation.');
      setLoading(false);
      return;
    }
    // Supporting sections are optional: a caller missing one capability still sees the page,
    // minus the section they may not read — same pattern InternalRequisitionDetail uses.
    const optional = [
      [() => getHandoverTasks(sepNo, scope), setHandover, []],
      [() => getClearanceTasks(sepNo, scope), setClearance, []],
      [() => getAssetReturns(sepNo, scope), setAssets, []],
      [() => getAccessClearances(sepNo, scope), setAccess, []],
      [() => getExitInterview(sepNo, scope), setInterview, null],
      [() => getFnf(sepNo, scope), setFnf, null],
    ];
    await Promise.all(optional.map(async ([call, set, fallback]) => {
      try { const { data } = await call(); set(data); } catch { set(fallback); }
    }));
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, sepNo]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <HrmsLoading label="Loading separation…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;
  if (!sep) return null;

  const isClosed = sep.stage === 'Closed' || sep.stage === 'Withdrawn';
  const needsDecision = !sep.final_lwd && !sep.recommended_lwd;
  const pendingApproval = !!sep.recommended_lwd && !sep.final_lwd;

  const handoverColumns = [
    { key: 'task', label: 'Task', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-medium">{r.task}</span>
        {r.assigned_to && <span className={`block ${A_LITTLE}`}>→ {r.assigned_to}</span>}
      </>
    ) },
    { key: 'due', label: 'Due', render: (r) => <span className={A_LITTLE}>{day(r.due_date)}</span> },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        {r.status === 'Pending' && canHandoverWrite && (
          <Btn tone="ghost" onClick={() => updateHandoverTask(sepNo, r.id, { status: 'Submitted' }, scope)
            .then(() => { showSuccess('Marked submitted.'); load(); })
            .catch((e) => showError(e?.response?.data?.detail || 'Could not update.'))}>
            Mark Submitted
          </Btn>
        )}
        {r.status === 'Submitted' && canHandoverApprove && (
          <Btn tone="ghost" onClick={() => setAcceptingHandover(r)}>Review</Btn>
        )}
      </div>
    ) },
  ];

  const clearanceColumns = [
    { key: 'owner', label: 'Owner', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-medium">{r.owner_type}</span>
        <span className={`block ${A_LITTLE}`}>{r.task}</span>
      </>
    ) },
    { key: 'recovery', label: 'Recovery', render: (r) => (
      <span className={A_LITTLE}>{r.recovery_amount ? money(r.recovery_amount) : '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        {r.status === 'Pending' && canClearanceAct && (
          <Btn tone="ghost" onClick={() => setActingClearance(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const assetColumns = [
    { key: 'asset', label: 'Asset', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-medium">{r.description}</span>
        <span className={`block ${A_LITTLE}`}>{r.ast_no}{r.category ? ` · ${r.category}` : ''}</span>
      </>
    ) },
    { key: 'recovery', label: 'Recovery', render: (r) => (
      <span className={A_LITTLE}>{r.recovery_amount ? money(r.recovery_amount) : '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        {r.status === 'Pending' && canClearanceAct && (
          <Btn tone="ghost" onClick={() => setUpdatingAsset(r)}>Confirm</Btn>
        )}
      </div>
    ) },
  ];

  const accessColumns = [
    { key: 'system', label: 'System', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-medium">{r.system_type}</span>
        {r.description && <span className={`block ${A_LITTLE}`}>{r.description}</span>}
      </>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        {r.status === 'Pending' && canClearanceAct && (
          <Btn tone="ghost" onClick={() => setUpdatingAccess(r)}>Update</Btn>
        )}
      </div>
    ) },
  ];

  return (
    <div className="space-y-5">
      <Link to="/hrms/separations"
        className="inline-flex items-center gap-1.5 text-[12px] font-bold text-[var(--text-muted)]
          hover:text-[var(--text-main)]">
        <ArrowLeft size={14} /> Exit Management
      </Link>

      {/* ── Case header ── */}
      <div className={CARD}>
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3.5">
            <div className="h-10 w-10 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]
              flex items-center justify-center shrink-0">
              <UserMinus size={19} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-[var(--text-main)]">
                {sep.employee_name || sep.employee_code}
              </h1>
              <p className={A_LITTLE}>{sep.employee_code} · {sep.sep_no} · {sep.exit_type}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Chip tone={toneFor(sep.stage)}>{sep.stage}</Chip>
            {!isClosed && canManage && (
              <Btn tone="ghost" onClick={() => setWithdrawing(true)}>Withdraw</Btn>
            )}
            {!isClosed && canManage && (
              <Btn tone="primary" onClick={() => setClosing(true)}>Close Case</Btn>
            )}
          </div>
        </div>

        <div className="mt-4 pt-4 border-t border-[var(--border)]">
          <Facts items={[
            { label: 'Resignation Date', value: day(sep.resignation_date) },
            { label: 'Calculated Notice', value: `${sep.calculated_notice_days} day${sep.calculated_notice_days === 1 ? '' : 's'}` },
            { label: 'Calculated LWD', value: day(sep.calculated_lwd) },
            { label: 'Notice Basis', value: sep.notice_basis },
            sep.recommended_lwd && { label: 'Recommended LWD', value: day(sep.recommended_lwd) },
            sep.final_lwd && { label: 'Final LWD', value: day(sep.final_lwd) },
            sep.waiver_days ? { label: 'Waiver', value: `${sep.waiver_days} day(s)` } : null,
          ]} />
        </div>

        {needsDecision && canManage && !isClosed && (
          <div className="mt-4 pt-4 border-t border-[var(--border)] flex items-center justify-between gap-3">
            <p className="text-[12px] text-[var(--text-muted)]">
              No decision recorded yet — the case shows only the calculated notice.
            </p>
            <Btn tone="primary" onClick={() => setDeciding(true)}>Record Decision</Btn>
          </div>
        )}
        {pendingApproval && (
          <div className="mt-4 pt-4 border-t border-[var(--border)] flex items-center justify-between gap-3
            rounded-lg bg-[var(--accent-orange-bg)] px-3 py-2.5">
            <p className="text-[12px] text-[var(--accent-orange)] font-semibold">
              A revised LWD / notice waiver is awaiting approval (BR-016).
            </p>
            {canApproveSep && (
              <Btn tone="primary" onClick={() => setApproving(true)}>Review</Btn>
            )}
          </div>
        )}

        {sep.progress && (
          <div className="mt-4 pt-4 border-t border-[var(--border)]">
            <Facts items={[
              { label: 'Handover', value: `${sep.progress.handover.done}/${sep.progress.handover.total}` },
              { label: 'Clearance', value: `${sep.progress.clearance.done}/${sep.progress.clearance.total}` },
              { label: 'Asset Returns', value: `${sep.progress.asset_returns.pending} pending of ${sep.progress.asset_returns.total}` },
              { label: 'Access Clearance', value: `${sep.progress.access_clearances.pending} pending of ${sep.progress.access_clearances.total}` },
              { label: 'Exit Interview', value: sep.progress.exit_interview_done ? 'Recorded' : 'Not yet' },
              { label: 'F&F', value: sep.progress.fnf_status || 'Not prepared' },
            ]} />
          </div>
        )}
      </div>

      {/* ── Handover Plan ── */}
      <Section icon={ClipboardList} title="Handover Plan" subtitle="§22.2 — knowledge/task transfer to a successor."
        actions={canHandoverWrite && !isClosed && (
          <Btn tone="ghost" onClick={() => setAddingHandover(true)}><Plus size={13} /> Add Task</Btn>
        )}>
        {handover.length ? (
          <RecordList rows={handover} columns={handoverColumns}
            keyOf={(r) => r.id}
            renderCard={(r) => (
              <div className="space-y-1.5">
                <p className="text-[13px] font-semibold text-[var(--text-main)]">{r.task}</p>
                <Chip tone={toneFor(r.status)}>{r.status}</Chip>
              </div>
            )} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">No handover tasks yet.</p>
        )}
      </Section>

      {/* ── Departmental Clearance ── */}
      <Section icon={ShieldCheck} title="Departmental Clearance"
        subtitle="Manager, HR, IT, Admin and Finance clearance — opened automatically once notice is accepted."
        actions={canClearanceManage && !isClosed && (
          <Btn tone="ghost" onClick={() => setAddingClearance(true)}><Plus size={13} /> Add Task</Btn>
        )}>
        {clearance.length ? (
          <RecordList rows={clearance} columns={clearanceColumns}
            keyOf={(r) => r.id}
            renderCard={(r) => (
              <div className="space-y-1.5">
                <p className="text-[13px] font-semibold text-[var(--text-main)]">{r.owner_type}</p>
                <p className="text-[12px] text-[var(--text-muted)]">{r.task}</p>
                <Chip tone={toneFor(r.status)}>{r.status}</Chip>
              </div>
            )} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">
            No clearance tasks yet — they open once HR records the notice decision.
          </p>
        )}
      </Section>

      {/* ── Asset Returns ── */}
      <Section icon={Laptop} title="Asset Return Requests" subtitle="§22.2 — company/client assets issued to this employee."
        actions={canClearanceManage && !isClosed && (
          <Btn tone="ghost" onClick={() => setAddingAsset(true)}><Plus size={13} /> Request Return</Btn>
        )}>
        {assets.length ? (
          <RecordList rows={assets} columns={assetColumns}
            keyOf={(r) => r.ast_no}
            renderCard={(r) => (
              <div className="space-y-1.5">
                <p className="text-[13px] font-semibold text-[var(--text-main)]">{r.description}</p>
                <Chip tone={toneFor(r.status)}>{r.status}</Chip>
              </div>
            )} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">No assets to return.</p>
        )}
      </Section>

      {/* ── Access Clearance ── */}
      <Section icon={KeyRound} title="Access Clearance" subtitle="Email, applications, VPN, physical access, cards/keys."
        actions={canClearanceManage && !isClosed && (
          <Btn tone="ghost" onClick={() => setAddingAccess(true)}><Plus size={13} /> Add Item</Btn>
        )}>
        {access.length ? (
          <RecordList rows={access} columns={accessColumns}
            keyOf={(r) => r.id}
            renderCard={(r) => (
              <div className="space-y-1.5">
                <p className="text-[13px] font-semibold text-[var(--text-main)]">{r.system_type}</p>
                <Chip tone={toneFor(r.status)}>{r.status}</Chip>
              </div>
            )} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">No access items recorded.</p>
        )}
      </Section>

      {/* ── Exit Interview ── */}
      <Section icon={MessageSquareText} title="Exit Interview" subtitle="§22.2 step 195."
        actions={canInterviewWrite && !isClosed && (
          <Btn tone="ghost" onClick={() => setEditingInterview(true)}>
            {interview ? 'Edit' : 'Record'}
          </Btn>
        )}>
        {/* Three states, not two. A record can EXIST and still carry none of the fields
            this screen knows how to show -- there are exit interviews in the database
            written to an older shape (primary_reason / overall_experience / would_rejoin
            rather than reason / *_rating / rehire_recommendation). `Facts` drops every
            null, so those rendered as an empty box directly under a summary tile
            announcing "Recorded", which reads as a broken page rather than an old record.
            Say what is actually true instead. */}
        {!interview ? (
          <p className="text-[12px] text-[var(--text-muted)] py-3">Not recorded yet.</p>
        ) : interviewFacts.length ? (
          <Facts items={interviewFacts} />
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">
            An interview is on record for this case, but none of its answers are in the
            fields this screen reads &mdash; it was saved in an earlier format. Re-record
            it to bring it up to date.
          </p>
        )}
      </Section>

      {/* ── Full & Final Settlement ── */}
      <Section icon={Wallet} title="Full & Final Settlement" subtitle="§7.21 — no payroll engine behind this yet; figures are entered by hand."
        actions={(
          <div className="flex items-center gap-2">
            {canFnfPrepare && !isClosed && (!fnf || fnf.status === 'Draft' || fnf.status === 'Rejected') && (
              <Btn tone="ghost" onClick={() => setEditingFnf(true)}>{fnf ? 'Edit' : 'Prepare'}</Btn>
            )}
            {canFnfApprove && fnf?.status === 'Prepared' && (
              <Btn tone="primary" onClick={() => setDecidingFnf(true)}>Approve / Reject</Btn>
            )}
            {canFnfPrepare && fnf?.status === 'Approved' && (
              <Btn tone="primary" onClick={() => setMarkingPaid(true)}>Mark Paid</Btn>
            )}
          </div>
        )}>
        {fnf ? (
          <div className="space-y-3">
            <Chip tone={toneFor(fnf.status)}>{fnf.status}</Chip>
            <Facts items={[
              { label: 'Payable Days', value: money(fnf.payable_days) },
              { label: 'Leave Encashment', value: money(fnf.leave_encashment) },
              { label: 'Notice Pay/Shortfall', value: money(fnf.notice_pay_or_shortfall) },
              { label: 'Advance Recovery', value: money(fnf.advance_recovery) },
              { label: 'Variable Pay Release', value: money(fnf.variable_pay_hold_release) },
              { label: 'Other Earnings', value: money(fnf.other_earnings) },
              { label: 'Other Deductions', value: money(fnf.other_deductions) },
              { label: 'Rolled-up Recovery', value: money(fnf.rolled_up_recovery) },
              { label: 'Total Settlement', value: money(fnf.total_settlement) },
              fnf.payment_reference ? { label: 'Payment Reference', value: fnf.payment_reference } : null,
              fnf.paid_on ? { label: 'Paid On', value: day(fnf.paid_on) } : null,
            ]} />
            <p className={A_LITTLE}>
              Rolled-up recovery is the sum of every asset-return and clearance-task recovery
              amount on this case — it is added automatically and cannot be edited here.
            </p>
          </div>
        ) : (
          <p className="text-[12px] text-[var(--text-muted)] py-3">Not prepared yet.</p>
        )}
      </Section>

      {/* ── Nominee & legal documentation (§7.20 step 157) — Demise/Missing cases ── */}
      {(sep.exit_type === 'Demise' || sep.exit_type === 'Missing') && (
        <Section icon={HeartHandshake} title="Nominee & Legal Documentation"
          subtitle="§7.20 — recorded sensitively for a demise/missing case."
          actions={canManage && (
            <Btn tone="ghost" onClick={() => setEditingNominee(true)}>
              {sep.nominee_details ? 'Edit' : 'Record'}
            </Btn>
          )}>
          {sep.nominee_details ? (
            <Facts items={[
              { label: 'Nominee Name', value: sep.nominee_details.nominee_name },
              { label: 'Relation', value: sep.nominee_details.nominee_relation },
              { label: 'Contact', value: sep.nominee_details.nominee_contact },
              { label: 'Legal Document Ref', value: sep.nominee_details.legal_document_ref },
              sep.nominee_details.notes ? { label: 'Notes', value: sep.nominee_details.notes } : null,
            ]} />
          ) : (
            <p className="text-[12px] text-[var(--text-muted)] py-3">Not recorded yet.</p>
          )}
        </Section>
      )}

      {/* ── Modals ── */}
      {deciding && (
        <DecisionModal sep={sep} scope={scope} onClose={() => setDeciding(false)}
          onDone={() => { setDeciding(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {approving && (
        <ApprovalModal sep={sep} scope={scope} onClose={() => setApproving(false)}
          onDone={() => { setApproving(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {withdrawing && (
        <WithdrawModal sep={sep} scope={scope} onClose={() => setWithdrawing(false)}
          onDone={() => { setWithdrawing(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {closing && (
        <CloseModal sep={sep} scope={scope} onClose={() => setClosing(false)}
          onDone={() => { setClosing(false); load(); }}
          showSuccess={showSuccess} showError={showError}
          onClosed={() => navigate('/hrms/separations')} />
      )}
      {addingHandover && (
        <AddHandoverModal sepNo={sepNo} scope={scope} onClose={() => setAddingHandover(false)}
          onDone={() => { setAddingHandover(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acceptingHandover && (
        <AcceptHandoverModal sepNo={sepNo} task={acceptingHandover} scope={scope}
          onClose={() => setAcceptingHandover(null)}
          onDone={() => { setAcceptingHandover(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {addingClearance && (
        <AddClearanceModal sepNo={sepNo} scope={scope} onClose={() => setAddingClearance(false)}
          onDone={() => { setAddingClearance(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {actingClearance && (
        <ActClearanceModal sepNo={sepNo} task={actingClearance} scope={scope}
          onClose={() => setActingClearance(null)}
          onDone={() => { setActingClearance(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {addingAsset && (
        <AddAssetModal sepNo={sepNo} scope={scope} onClose={() => setAddingAsset(false)}
          onDone={() => { setAddingAsset(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {updatingAsset && (
        <UpdateAssetModal sepNo={sepNo} asset={updatingAsset} scope={scope}
          onClose={() => setUpdatingAsset(null)}
          onDone={() => { setUpdatingAsset(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {addingAccess && (
        <AddAccessModal sepNo={sepNo} scope={scope} onClose={() => setAddingAccess(false)}
          onDone={() => { setAddingAccess(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {updatingAccess && (
        <UpdateAccessModal sepNo={sepNo} item={updatingAccess} scope={scope}
          onClose={() => setUpdatingAccess(null)}
          onDone={() => { setUpdatingAccess(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingInterview && (
        <InterviewModal sepNo={sepNo} interview={interview} scope={scope}
          onClose={() => setEditingInterview(false)}
          onDone={() => { setEditingInterview(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingFnf && (
        <FnfModal sepNo={sepNo} fnf={fnf} scope={scope} onClose={() => setEditingFnf(false)}
          onDone={() => { setEditingFnf(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {decidingFnf && (
        <FnfDecisionModal sepNo={sepNo} scope={scope} onClose={() => setDecidingFnf(false)}
          onDone={() => { setDecidingFnf(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {markingPaid && (
        <FnfPaidModal sepNo={sepNo} scope={scope} onClose={() => setMarkingPaid(false)}
          onDone={() => { setMarkingPaid(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingNominee && (
        <NomineeModal sep={sep} scope={scope} onClose={() => setEditingNominee(false)}
          onDone={() => { setEditingNominee(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
// Modals — each does exactly one API call. `run` is the shared submit wrapper: busy state,
// success toast, error toast, and closing only on success.
// ─────────────────────────────────────────────────────────────
const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg, errorFallback) => {
    setBusy(true);
    try {
      const res = await fn();
      if (successMsg) showSuccess(successMsg);
      onDone();
      return res;
    } catch (err) {
      showError(err?.response?.data?.detail || errorFallback || 'That did not work.');
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const DecisionModal = ({ sep, scope, onClose, onDone, showSuccess, showError }) => {
  const [revisedLwd, setRevisedLwd] = useState('');
  const [waiverDays, setWaiverDays] = useState('');
  const [shortfallDays, setShortfallDays] = useState('');
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  return (
    <Modal title="Record Decision" labelledBy="sep-decide-title"
      subtitle={`${sep.sep_no} · calculated LWD ${day(sep.calculated_lwd)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => decideSeparation(sep.sep_no, {
              revised_lwd: revisedLwd || undefined,
              waiver_days: waiverDays ? Number(waiverDays) : undefined,
              shortfall_days: shortfallDays ? Number(shortfallDays) : undefined,
              remarks: remarks.trim() || undefined,
            }, scope),
            'Decision recorded.', 'Could not record the decision.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <p className="text-[12px] text-[var(--text-muted)]">
        Leave everything blank to accept the calculated notice as-is — it becomes final
        immediately. Any revision here needs approval before it takes effect (BR-016).
      </p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="dec-lwd">Revised LWD</label>
          <input id="dec-lwd" type="date" value={revisedLwd} className={FIELD}
            onChange={(e) => setRevisedLwd(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="dec-waiver">Waiver (days)</label>
          <input id="dec-waiver" type="number" min="0" value={waiverDays} className={FIELD}
            onChange={(e) => setWaiverDays(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="dec-shortfall">Shortfall (days, for recovery)</label>
        <input id="dec-shortfall" type="number" min="0" value={shortfallDays} className={FIELD}
          onChange={(e) => setShortfallDays(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="dec-remarks">Remarks</label>
        <textarea id="dec-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const ApprovalModal = ({ sep, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const decide = (approved) => run(
    () => approveSeparation(sep.sep_no, { approved, remarks: remarks.trim() || undefined }, scope),
    approved ? 'Waiver approved.' : 'Waiver rejected — the calculated notice stands.',
    'Could not record the approval.',
  );
  return (
    <Modal title="Approve or Reject" labelledBy="sep-approve-title"
      subtitle={`${sep.sep_no} · recommended LWD ${day(sep.recommended_lwd)}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" disabled={busy} onClick={() => decide(false)}>Reject</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => decide(true)}>
            {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}>
      <Facts items={[
        { label: 'Calculated LWD', value: day(sep.calculated_lwd) },
        { label: 'Recommended LWD', value: day(sep.recommended_lwd) },
        sep.waiver_days ? { label: 'Waiver', value: `${sep.waiver_days} day(s)` } : null,
        sep.shortfall_days ? { label: 'Shortfall', value: `${sep.shortfall_days} day(s)` } : null,
      ]} />
      <div>
        <label className={LABEL} htmlFor="app-remarks">Remarks</label>
        <textarea id="app-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const WithdrawModal = ({ sep, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Withdraw This Separation" labelledBy="sep-withdraw-title"
      subtitle={sep.sep_no}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" disabled={busy} onClick={() => run(
            () => withdrawSeparation(sep.sep_no, remarks.trim() || undefined, scope),
            'Separation withdrawn — the employee is Active again.',
            'Could not withdraw this separation.',
          )}>{busy ? 'Working…' : 'Withdraw'}</Btn>
        </>
      )}>
      <p className="text-[12px] text-[var(--text-muted)]">
        Reverts the employee to Active. Use this for a resignation raised in error or one the
        employee has taken back.
      </p>
      <div>
        <label className={LABEL} htmlFor="wd-remarks">Remarks</label>
        <textarea id="wd-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const CloseModal = ({ sep, scope, onClose, onDone, onClosed, showSuccess, showError }) => {
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(null);

  const submit = async () => {
    setBusy(true);
    setBlocked(null);
    try {
      await closeSeparation(sep.sep_no, force || undefined, scope);
      showSuccess(`${sep.sep_no} closed.`);
      onDone();
      onClosed();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 409 && detail?.startsWith('Cannot close')) {
        setBlocked(detail);
      } else {
        showError(detail || 'Could not close this case.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Close This Case" labelledBy="sep-close-title" subtitle={sep.sep_no}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={submit}>{busy ? 'Working…' : 'Close Case'}</Btn>
        </>
      )}>
      <p className="text-[12px] text-[var(--text-muted)]">
        BR-025: closure needs every handover and clearance task accepted/cleared and F&F paid.
        The employee is deactivated and moved to Resigned/Terminated on close.
      </p>
      {blocked && (
        <div className="rounded-lg bg-[var(--accent-orange-bg)] px-3 py-2.5 text-[12px] text-[var(--accent-orange)]">
          {blocked}
        </div>
      )}
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-main)]">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
        Override incomplete items (recorded as a forced close)
      </label>
    </Modal>
  );
};

const AddHandoverModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [task, setTask] = useState('');
  const [description, setDescription] = useState('');
  const [assignedTo, setAssignedTo] = useState('');
  const [dueDate, setDueDate] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Add Handover Task" labelledBy="hnd-add-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !task.trim()} onClick={() => run(
            () => createHandoverTask(sepNo, {
              task: task.trim(), description: description.trim() || undefined,
              assigned_to: assignedTo.trim() || undefined, due_date: dueDate || undefined,
            }, scope),
            'Handover task added.', 'Could not add this task.',
          )}>{busy ? 'Saving…' : 'Add'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="hnd-task">Task / Knowledge Item *</label>
        <input id="hnd-task" value={task} className={FIELD} onChange={(e) => setTask(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="hnd-desc">Description</label>
        <textarea id="hnd-desc" rows={2} value={description} className={TEXTAREA}
          onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="hnd-assigned">Successor (name/id)</label>
          <input id="hnd-assigned" value={assignedTo} className={FIELD}
            onChange={(e) => setAssignedTo(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="hnd-due">Due Date</label>
          <input id="hnd-due" type="date" value={dueDate} className={FIELD}
            onChange={(e) => setDueDate(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

const AcceptHandoverModal = ({ sepNo, task, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const decide = (accepted) => run(
    () => acceptHandoverTask(sepNo, task.id, { accepted, remarks: remarks.trim() || undefined }, scope),
    accepted ? 'Handover accepted.' : 'Handover rejected.',
    'Could not record the decision.',
  );
  return (
    <Modal title="Review Handover" labelledBy="hnd-accept-title" subtitle={task.task}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" disabled={busy} onClick={() => decide(false)}>Reject</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => decide(true)}>Accept</Btn>
        </>
      )}>
      {task.completion_evidence && (
        <Facts items={[{ label: 'Completion Evidence', value: task.completion_evidence }]} />
      )}
      <div>
        <label className={LABEL} htmlFor="hnd-acc-remarks">Remarks</label>
        <textarea id="hnd-acc-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const OWNER_TYPES = ['Manager', 'HR', 'IT', 'Admin', 'Finance', 'Other'];

const AddClearanceModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [ownerType, setOwnerType] = useState('Other');
  const [task, setTask] = useState('');
  const [dueDate, setDueDate] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Add Clearance Task" labelledBy="clr-add-title"
      subtitle="For a function beyond the standard Manager/HR/IT/Admin/Finance set."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !task.trim()} onClick={() => run(
            () => createClearanceTask(sepNo, { owner_type: ownerType, task: task.trim(),
              due_date: dueDate || undefined }, scope),
            'Clearance task added.', 'Could not add this task.',
          )}>{busy ? 'Saving…' : 'Add'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="clr-owner">Owner *</label>
        <select id="clr-owner" value={ownerType} className={FIELD}
          onChange={(e) => setOwnerType(e.target.value)}>
          {OWNER_TYPES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="clr-task">Task *</label>
        <input id="clr-task" value={task} className={FIELD} onChange={(e) => setTask(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="clr-due">Due Date</label>
        <input id="clr-due" type="date" value={dueDate} className={FIELD}
          onChange={(e) => setDueDate(e.target.value)} />
      </div>
    </Modal>
  );
};

const ActClearanceModal = ({ sepNo, task, scope, onClose, onDone, showSuccess, showError }) => {
  const [status, setStatus] = useState('Cleared');
  const [recoveryAmount, setRecoveryAmount] = useState('');
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title={`${task.owner_type} Clearance`} labelledBy="clr-act-title" subtitle={task.task}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => actOnClearanceTask(sepNo, task.id, {
              status, recovery_amount: recoveryAmount ? Number(recoveryAmount) : undefined,
              remarks: remarks.trim() || undefined,
            }, scope),
            `Clearance ${status.toLowerCase()}.`, 'Could not update this task.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="clr-status">Status *</label>
        <select id="clr-status" value={status} className={FIELD}
          onChange={(e) => setStatus(e.target.value)}>
          {['Cleared', 'Rejected', 'Waived'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="clr-recovery">Recovery Amount</label>
        <input id="clr-recovery" type="number" min="0" step="0.01" value={recoveryAmount}
          className={FIELD} onChange={(e) => setRecoveryAmount(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Flows automatically into the F&F settlement if set.
        </p>
      </div>
      <div>
        <label className={LABEL} htmlFor="clr-remarks">Remarks</label>
        <textarea id="clr-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const AddAssetModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [issuedDate, setIssuedDate] = useState('');
  const [expectedReturnDate, setExpectedReturnDate] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Request Asset Return" labelledBy="ast-add-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !description.trim()} onClick={() => run(
            () => createAssetReturn(sepNo, {
              description: description.trim(), category: category.trim() || undefined,
              issued_date: issuedDate || undefined,
              expected_return_date: expectedReturnDate || undefined,
            }, scope),
            'Asset return request created.', 'Could not create this request.',
          )}>{busy ? 'Saving…' : 'Request'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="ast-desc">Asset *</label>
        <input id="ast-desc" value={description} className={FIELD}
          placeholder="e.g. Company laptop" onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="ast-cat">Category</label>
        <input id="ast-cat" value={category} className={FIELD} onChange={(e) => setCategory(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="ast-issued">Issued Date</label>
          <input id="ast-issued" type="date" value={issuedDate} className={FIELD}
            onChange={(e) => setIssuedDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ast-expected">Expected Return</label>
          <input id="ast-expected" type="date" value={expectedReturnDate} className={FIELD}
            onChange={(e) => setExpectedReturnDate(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

const UpdateAssetModal = ({ sepNo, asset, scope, onClose, onDone, showSuccess, showError }) => {
  const [status, setStatus] = useState('Returned');
  const [returnedDate, setReturnedDate] = useState(new Date().toISOString().slice(0, 10));
  const [condition, setCondition] = useState('');
  const [recoveryAmount, setRecoveryAmount] = useState('');
  const [receivedBy, setReceivedBy] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Confirm Asset Return" labelledBy="ast-upd-title" subtitle={asset.description}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => updateAssetReturn(sepNo, asset.ast_no, {
              status, returned_date: returnedDate || undefined, condition: condition.trim() || undefined,
              missing_or_damaged: status === 'Lost' || status === 'Damaged',
              recovery_amount: recoveryAmount ? Number(recoveryAmount) : undefined,
              received_by: receivedBy.trim() || undefined,
            }, scope),
            'Asset return updated.', 'Could not update this record.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="ast-status">Status *</label>
        <select id="ast-status" value={status} className={FIELD}
          onChange={(e) => setStatus(e.target.value)}>
          {['Returned', 'Partially Returned', 'Lost', 'Damaged', 'Waived'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="ast-returned">Returned Date</label>
          <input id="ast-returned" type="date" value={returnedDate} className={FIELD}
            onChange={(e) => setReturnedDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="ast-received">Received By</label>
          <input id="ast-received" value={receivedBy} className={FIELD}
            onChange={(e) => setReceivedBy(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="ast-condition">Condition</label>
        <input id="ast-condition" value={condition} className={FIELD}
          onChange={(e) => setCondition(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="ast-recovery">Recovery Amount</label>
        <input id="ast-recovery" type="number" min="0" step="0.01" value={recoveryAmount}
          className={FIELD} onChange={(e) => setRecoveryAmount(e.target.value)} />
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          Flows automatically into the F&F settlement if set.
        </p>
      </div>
    </Modal>
  );
};

const ACCESS_SYSTEM_TYPES = ['Email', 'Applications', 'VPN', 'Client Systems',
  'Physical Access', 'Cards / Keys', 'Other'];

const AddAccessModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [systemType, setSystemType] = useState('Email');
  const [description, setDescription] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Add Access Clearance Item" labelledBy="acc-add-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => createAccessClearance(sepNo, {
              system_type: systemType, description: description.trim() || undefined,
            }, scope),
            'Access clearance item added.', 'Could not add this item.',
          )}>{busy ? 'Saving…' : 'Add'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="acc-type">System / Access Type *</label>
        <select id="acc-type" value={systemType} className={FIELD}
          onChange={(e) => setSystemType(e.target.value)}>
          {ACCESS_SYSTEM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="acc-desc">Description</label>
        <input id="acc-desc" value={description} className={FIELD}
          onChange={(e) => setDescription(e.target.value)} />
      </div>
    </Modal>
  );
};

const UpdateAccessModal = ({ sepNo, item, scope, onClose, onDone, showSuccess, showError }) => {
  const [status, setStatus] = useState('Disabled');
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Update Access Clearance" labelledBy="acc-upd-title" subtitle={item.system_type}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => updateAccessClearance(sepNo, item.id, { status, remarks: remarks.trim() || undefined }, scope),
            'Access clearance updated.', 'Could not update this item.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="acc-status">Status *</label>
        <select id="acc-status" value={status} className={FIELD}
          onChange={(e) => setStatus(e.target.value)}>
          {['Disabled', 'Not Applicable'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="acc-remarks">Remarks</label>
        <textarea id="acc-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const RATING_FIELDS = [
  ['manager_rating', 'Manager'], ['team_rating', 'Team'],
  ['work_rating', 'Work'], ['compensation_rating', 'Compensation'],
];

const InterviewModal = ({ sepNo, interview, scope, onClose, onDone, showSuccess, showError }) => {
  const [reason, setReason] = useState(interview?.reason || '');
  const [ratings, setRatings] = useState(Object.fromEntries(
    RATING_FIELDS.map(([key]) => [key, interview?.[key] ?? ''])));
  const [comments, setComments] = useState(interview?.comments || '');
  const [rehire, setRehire] = useState(
    interview?.rehire_recommendation == null ? '' : String(interview.rehire_recommendation));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Exit Interview" labelledBy="int-title" subtitle={sepNo} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => saveExitInterview(sepNo, {
              reason: reason.trim() || undefined,
              ...Object.fromEntries(RATING_FIELDS.map(([key]) => [
                key, ratings[key] === '' ? undefined : Number(ratings[key])])),
              comments: comments.trim() || undefined,
              rehire_recommendation: rehire === '' ? undefined : rehire === 'true',
            }, scope),
            'Exit interview saved.', 'Could not save the exit interview.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="int-reason">Reason for Leaving</label>
        <textarea id="int-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        {RATING_FIELDS.map(([key, label]) => (
          <div key={key}>
            <label className={LABEL} htmlFor={`int-${key}`}>{label} Rating (1–5)</label>
            <input id={`int-${key}`} type="number" min="1" max="5" value={ratings[key]}
              className={FIELD}
              onChange={(e) => setRatings((r) => ({ ...r, [key]: e.target.value }))} />
          </div>
        ))}
      </div>
      <div>
        <label className={LABEL} htmlFor="int-rehire">Rehire Recommended?</label>
        <select id="int-rehire" value={rehire} className={FIELD}
          onChange={(e) => setRehire(e.target.value)}>
          <option value="">Not specified</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="int-comments">Comments</label>
        <textarea id="int-comments" rows={2} value={comments} className={TEXTAREA}
          onChange={(e) => setComments(e.target.value)} />
      </div>
    </Modal>
  );
};

const FNF_FIELDS = [
  ['payable_days', 'Payable Days (amount)'], ['leave_encashment', 'Leave Encashment'],
  ['notice_pay_or_shortfall', 'Notice Pay / Shortfall (− for recovery)'],
  ['advance_recovery', 'Advance Recovery'], ['variable_pay_hold_release', 'Variable Pay Release'],
  ['other_earnings', 'Other Earnings'], ['other_deductions', 'Other Deductions'],
];

const FnfModal = ({ sepNo, fnf, scope, onClose, onDone, showSuccess, showError }) => {
  const [values, setValues] = useState(Object.fromEntries(
    FNF_FIELDS.map(([key]) => [key, fnf?.[key] ?? ''])));
  const [remarks, setRemarks] = useState(fnf?.remarks || '');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Prepare F&F Settlement" labelledBy="fnf-title" subtitle={sepNo} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => saveFnf(sepNo, {
              ...Object.fromEntries(FNF_FIELDS.map(([key]) => [
                key, values[key] === '' ? undefined : Number(values[key])])),
              remarks: remarks.trim() || undefined,
            }, scope),
            'F&F prepared — awaiting approval.', 'Could not save the settlement.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <p className="text-[12px] text-[var(--text-muted)]">
        Asset and clearance recoveries are added automatically — enter every other figure by
        hand, since no payroll engine feeds this yet.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {FNF_FIELDS.map(([key, label]) => (
          <div key={key}>
            <label className={LABEL} htmlFor={`fnf-${key}`}>{label}</label>
            <input id={`fnf-${key}`} type="number" step="0.01" value={values[key]} className={FIELD}
              onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))} />
          </div>
        ))}
      </div>
      <div>
        <label className={LABEL} htmlFor="fnf-remarks">Remarks</label>
        <textarea id="fnf-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const FnfDecisionModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const decide = (approved) => run(
    () => approveFnf(sepNo, { approved, remarks: remarks.trim() || undefined }, scope),
    approved ? 'F&F approved.' : 'F&F sent back to the maker.',
    'Could not record the decision.',
  );
  return (
    <Modal title="Approve F&F Settlement" labelledBy="fnf-dec-title" subtitle={sepNo} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" disabled={busy} onClick={() => decide(false)}>Reject</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => decide(true)}>Approve</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="fnf-dec-remarks">Remarks</label>
        <textarea id="fnf-dec-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const FnfPaidModal = ({ sepNo, scope, onClose, onDone, showSuccess, showError }) => {
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [reference, setReference] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Mark F&F Paid" labelledBy="fnf-paid-title" subtitle={sepNo} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => markFnfPaid(sepNo, { paid_on: paidOn || undefined, reference: reference.trim() || undefined }, scope),
            'F&F marked paid.', 'Could not record the payment.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="fnf-paid-date">Paid On</label>
        <input id="fnf-paid-date" type="date" value={paidOn} className={FIELD}
          onChange={(e) => setPaidOn(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="fnf-ref">Payment Reference</label>
        <input id="fnf-ref" value={reference} className={FIELD}
          placeholder="e.g. NEFT/UTR number" onChange={(e) => setReference(e.target.value)} />
      </div>
    </Modal>
  );
};

const NomineeModal = ({ sep, scope, onClose, onDone, showSuccess, showError }) => {
  const existing = sep.nominee_details || {};
  const [nomineeName, setNomineeName] = useState(existing.nominee_name || '');
  const [relation, setRelation] = useState(existing.nominee_relation || '');
  const [contact, setContact] = useState(existing.nominee_contact || '');
  const [legalRef, setLegalRef] = useState(existing.legal_document_ref || '');
  const [notes, setNotes] = useState(existing.notes || '');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  return (
    <Modal title="Nominee & Legal Documentation" labelledBy="nominee-title"
      subtitle={`${sep.sep_no} · §7.20 step 157`} onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => saveNomineeDetails(sep.sep_no, {
              nominee_name: nomineeName.trim() || undefined,
              nominee_relation: relation.trim() || undefined,
              nominee_contact: contact.trim() || undefined,
              legal_document_ref: legalRef.trim() || undefined,
              notes: notes.trim() || undefined,
            }, scope),
            'Nominee details saved.', 'Could not save these details.',
          )}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}>
      <div>
        <label className={LABEL} htmlFor="nominee-name">Nominee Name</label>
        <input id="nominee-name" value={nomineeName} className={FIELD}
          onChange={(e) => setNomineeName(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="nominee-relation">Relation</label>
        <input id="nominee-relation" value={relation} className={FIELD}
          onChange={(e) => setRelation(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="nominee-contact">Contact</label>
        <input id="nominee-contact" value={contact} className={FIELD}
          onChange={(e) => setContact(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="nominee-legal">Legal Document Reference</label>
        <input id="nominee-legal" value={legalRef} className={FIELD}
          placeholder="e.g. death certificate / succession certificate number"
          onChange={(e) => setLegalRef(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="nominee-notes">Notes</label>
        <textarea id="nominee-notes" rows={2} value={notes} className={TEXTAREA}
          onChange={(e) => setNotes(e.target.value)} />
      </div>
    </Modal>
  );
};

export default SeparationDetail;
