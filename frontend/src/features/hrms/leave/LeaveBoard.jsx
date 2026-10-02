import React, { useCallback, useEffect, useState } from 'react';
import { CalendarDays, Search } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import BoardTabs from '../common/BoardTabs';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees,
  applyLeave, getLeaves, actOnLeave, cancelLeave,
  getLeaveBalances, getLeaveTypes, saveLeaveType,
  requestCoffEarn, getCoffLedger, actOnCoffEarn,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Leave & Compensatory Off (BA/Functional Design §7.10, §7.11, §22.8).
 *
 * Same tabbed shape as AttendanceBoard, for the same reason: none of these is a single case
 * with its own URL, they are views over rolling operational data plus one policy register.
 */

const TABS = ['Leave Requests', 'Balances', 'Compensatory Off', 'Leave Policy'];

const EmployeePicker = ({ scope, value, onChange }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    // No early setOptions([]) here: once `value` is set the component returns the
    // selected-chip view below and never reaches the dropdown, so stale options are
    // unreachable rather than merely hidden — nothing to clear.
    if (!debounced.trim() || value) return;
    let live = true;
    // Deferred a microtask, not called synchronously in the effect body: the react-hooks
    // set-state-in-effect rule flags a bare synchronous setState here, the same way it
    // already tolerates the setOptions/setSearching calls below inside the promise chain.
    Promise.resolve().then(() => { if (live) setSearching(true); });
    getEmployees({ ...scope, search: debounced, limit: 8 })
      .then(({ data }) => { if (live) setOptions(data?.employees || []); })
      .catch(() => { if (live) setOptions([]); })
      .finally(() => { if (live) setSearching(false); });
    return () => { live = false; };
  }, [debounced, value, scope]);

  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border
        border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
        <span className="text-[13px] text-[var(--text-main)] truncate">
          {value.name} <span className="text-[var(--text-muted)]">({value.employee_code})</span>
        </span>
        <button type="button" onClick={() => { onChange(null); setSearch(''); }}
          className="text-[11px] font-bold text-[var(--accent-indigo)] shrink-0">
          Change
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
      <input value={search} placeholder="Search by name or employee code…"
        className={`${FIELD} pl-8`} onChange={(e) => setSearch(e.target.value)} />
      {(searching || options.length > 0) && (
        <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg
          border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
          {searching && <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Searching…</p>}
          {!searching && options.map((o) => (
            <button key={o.user_id} type="button"
              onClick={() => { onChange(o); setOptions([]); }}
              className="block w-full text-left px-3 py-2 text-[12.5px] hover:bg-[var(--input-bg)]">
              <span className="text-[var(--text-main)]">{o.name}</span>
              <span className="block text-[11px] text-[var(--text-muted)]">
                {o.employee_code} · {o.designation || '—'} · {o.employment_status}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      const res = await fn();
      if (successMsg) showSuccess(successMsg);
      onDone(res);
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const LeaveBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState('Leave Requests');

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={CalendarDays}
        title="Leave & Compensatory Off"
        subtitle="Apply, approve, track balances and configure the leave-type register."
      />
      <HrmsScopeBar />

      <BoardTabs tabs={TABS} value={tab} onChange={setTab} label="Leave sections" />

      {tab === 'Leave Requests' && (
        <LeaveTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Balances' && <BalancesTab scope={scope} />}
      {tab === 'Compensatory Off' && (
        <CoffTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Leave Policy' && (
        <PolicyTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ── Leave Requests tab ──
const LeaveTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [applying, setApplying] = useState(false);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getLeaves({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load leave requests.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.leave_no}</span>
      </>
    ) },
    { key: 'type', label: 'Type', render: (r) => (
      <span className="text-[var(--text-main)]">{r.leave_type}</span>
    ) },
    { key: 'dates', label: 'Dates', render: (r) => (
      <span className="text-[var(--text-main)]">
        {day(r.start_date)} – {day(r.end_date)} ({r.days_count}d)
      </span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        <div className="flex gap-1.5">
          {can(CAP.LEAVE_APPROVE) && ['Pending', 'Manager Approved'].includes(r.status) && (
            <Btn tone="ghost" onClick={() => setActing({ row: r, mode: 'act' })}>Act</Btn>
          )}
          {can(CAP.LEAVE_APPLY) && ['Pending', 'Manager Approved', 'Approved'].includes(r.status) && (
            <Btn tone="ghost" onClick={() => setActing({ row: r, mode: 'cancel' })}>Cancel</Btn>
          )}
        </div>
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.leave_no}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Type', value: r.leave_type },
        { label: 'Dates', value: `${day(r.start_date)} – ${day(r.end_date)} (${r.days_count}d)` },
        { label: 'Reason', value: r.reason },
      ]} />
      <div className="flex gap-1.5">
        {can(CAP.LEAVE_APPROVE) && ['Pending', 'Manager Approved'].includes(r.status) && (
          <Btn tone="ghost" onClick={() => setActing({ row: r, mode: 'act' })}>Act</Btn>
        )}
        {can(CAP.LEAVE_APPLY) && ['Pending', 'Manager Approved', 'Approved'].includes(r.status) && (
          <Btn tone="ghost" onClick={() => setActing({ row: r, mode: 'cancel' })}>Cancel</Btn>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.LEAVE_APPLY) && (
          <Btn tone="primary" onClick={() => setApplying(true)}>
            <CalendarDays size={14} /> Apply Leave
          </Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading leave requests…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.leave_no} />
        ) : (
          <HrmsEmpty icon={CalendarDays} title="No leave requests yet" />
        )
      )}
      {applying && (
        <ApplyModal scope={scope} onClose={() => setApplying(false)}
          onDone={() => { setApplying(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting?.mode === 'act' && (
        <LeaveActionModal row={acting.row} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting?.mode === 'cancel' && (
        <CancelModal row={acting.row} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const ApplyModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [types, setTypes] = useState([]);
  const [leaveType, setLeaveType] = useState('');
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [halfDay, setHalfDay] = useState(false);
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    getLeaveTypes(scope).then(({ data }) => {
      setTypes(data || []);
      if (data?.length) setLeaveType(data[0].code);
    }).catch(() => setTypes([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = () => {
    if (!employee || !leaveType) { showError('Select the employee and a leave type.'); return; }
    run(() => applyLeave({
      employee_code: employee.employee_code, leave_type: leaveType,
      start_date: startDate, end_date: halfDay ? startDate : endDate, half_day: halfDay,
      reason: reason.trim() || undefined,
    }, scope), 'Leave applied.');
  };

  return (
    <Modal title="Apply Leave" labelledBy="leave-apply-title"
      subtitle="Balance is validated before the request is even raised (§7.10)."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Apply'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="leave-type">Leave Type *</label>
        <select id="leave-type" value={leaveType} className={FIELD}
          onChange={(e) => setLeaveType(e.target.value)}>
          {types.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
        </select>
      </div>
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <input type="checkbox" checked={halfDay} onChange={(e) => setHalfDay(e.target.checked)} />
        Half day
      </label>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="leave-start">Start Date *</label>
          <input id="leave-start" type="date" value={startDate} className={FIELD}
            onChange={(e) => setStartDate(e.target.value)} />
        </div>
        {!halfDay && (
          <div>
            <label className={LABEL} htmlFor="leave-end">End Date *</label>
            <input id="leave-end" type="date" value={endDate} className={FIELD}
              onChange={(e) => setEndDate(e.target.value)} />
          </div>
        )}
      </div>
      <div>
        <label className={LABEL} htmlFor="leave-reason">Reason</label>
        <textarea id="leave-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

const LeaveActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const nextStep = row.status === 'Pending' ? 'Manager Approved' : 'Approved';

  const act = (decision) => run(
    () => actOnLeave(row.leave_no, { decision, remarks: remarks.trim() || undefined }, scope),
    `${row.leave_no} ${decision.toLowerCase()}.`);

  return (
    <Modal title={`Act on ${row.leave_no}`} labelledBy="leave-act-title"
      subtitle={row.status === 'Pending'
        ? 'Manager step — HR still gives the final sign-off after this.'
        : 'HR-final step — approving now debits the balance and updates the calendar.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => act('Rejected')} disabled={busy}>Reject</Btn>
          <Btn onClick={() => act('Returned')} disabled={busy}>Return</Btn>
          <Btn tone="primary" onClick={() => act(nextStep)} disabled={busy}>
            {busy ? 'Working…' : nextStep}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Employee', value: row.employee_name || row.employee_code },
        { label: 'Type', value: row.leave_type },
        { label: 'Dates', value: `${day(row.start_date)} – ${day(row.end_date)} (${row.days_count}d)` },
        { label: 'Reason', value: row.reason },
      ]} />
      <div>
        <label className={LABEL} htmlFor="leave-act-remarks">Remarks</label>
        <textarea id="leave-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const CancelModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const submit = () => {
    if (!reason.trim()) { showError('A reason is required to cancel.'); return; }
    run(() => cancelLeave(row.leave_no, reason.trim(), scope), `${row.leave_no} cancelled.`);
  };
  return (
    <Modal title={`Cancel ${row.leave_no}`} labelledBy="leave-cancel-title"
      subtitle="Restores whatever balance (or C-Off batch) it consumed, if already approved."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Back</Btn>
          <Btn tone="danger" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Cancel Leave'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="leave-cancel-reason">Reason *</label>
        <textarea id="leave-cancel-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Balances tab ──
const BalancesTab = ({ scope }) => {
  const [employee, setEmployee] = useState(null);
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!employee) { setBalances([]); return; }
    setLoading(true); setError(null);
    getLeaveBalances(employee.employee_code, new Date().getFullYear(), scope)
      .then(({ data }) => setBalances(data || []))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load balances.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee]);

  return (
    <div className="space-y-4">
      <div className="max-w-sm">
        <label className={LABEL}>Employee</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      {!employee && <HrmsEmpty icon={CalendarDays} title="Search for an employee to see their balances" />}
      {loading && <HrmsLoading label="Loading balances…" />}
      {error && !loading && <HrmsError message={error} />}
      {!loading && !error && employee && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {balances.map((b) => (
            <div key={b.leave_type} className="rounded-xl border border-[var(--border)]
              bg-[var(--bg-card)] p-3.5">
              <p className="text-[10.5px] font-bold uppercase tracking-widest
                text-[var(--text-muted)]">{b.leave_type}</p>
              <p className="mt-1 text-[20px] font-bold text-[var(--text-main)]">{b.closing}</p>
              <p className="text-[11px] text-[var(--text-muted)]">days available</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Compensatory Off tab ──
const CoffTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [earning, setEarning] = useState(false);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getCoffLedger({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the C-Off ledger.');
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
    { key: 'earned', label: 'Worked On', render: (r) => (
      <span className="text-[var(--text-main)]">{day(r.earned_for_date)}</span>
    ) },
    { key: 'expiry', label: 'Expires', render: (r) => (
      <span className="text-[var(--text-main)]">{r.expiry_date ? day(r.expiry_date) : '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.COFF_APPROVE) && r.status === 'Pending Approval' && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_code}</p>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Worked On', value: day(r.earned_for_date) },
        { label: 'Expires', value: r.expiry_date ? day(r.expiry_date) : '—' },
        { label: 'Note', value: r.note },
      ]} />
      {can(CAP.COFF_APPROVE) && r.status === 'Pending Approval' && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.COFF_EARN_REQUEST) && (
          <Btn tone="primary" onClick={() => setEarning(true)}>Log Worked Holiday</Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading C-Off ledger…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.id} />
        ) : (
          <HrmsEmpty icon={CalendarDays} title="No Compensatory Off history"
            hint="Log an approved weekly-off/holiday worked to earn a credit." />
        )
      )}
      {earning && (
        <CoffEarnModal scope={scope} onClose={() => setEarning(false)}
          onDone={() => { setEarning(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <CoffActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const CoffEarnModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [earnedFor, setEarnedFor] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee) { showError('Select the employee.'); return; }
    run(() => requestCoffEarn({
      employee_code: employee.employee_code, earned_for_date: earnedFor,
      note: note.trim() || undefined,
    }, scope), 'C-Off earn logged, awaiting approval.');
  };

  return (
    <Modal title="Log Worked Holiday" labelledBy="coff-earn-title"
      subtitle="Approved work on a weekly off/holiday earns a Compensatory Off credit (§7.11)."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Submit'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="coff-date">Date Worked *</label>
        <input id="coff-date" type="date" value={earnedFor} className={FIELD}
          onChange={(e) => setEarnedFor(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="coff-note">Note</label>
        <textarea id="coff-note" rows={2} value={note} className={TEXTAREA}
          onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  );
};

const CoffActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const act = (approved) => run(
    () => actOnCoffEarn(row.id, { approved, remarks: remarks.trim() || undefined }, scope),
    approved ? 'C-Off credit approved.' : 'C-Off earn request rejected.');

  return (
    <Modal title="Act on C-Off Earn Request" labelledBy="coff-act-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => act(false)} disabled={busy}>Reject</Btn>
          <Btn tone="primary" onClick={() => act(true)} disabled={busy}>
            {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Employee', value: row.employee_code },
        { label: 'Worked On', value: day(row.earned_for_date) },
        { label: 'Note', value: row.note },
      ]} />
      <div>
        <label className={LABEL} htmlFor="coff-act-remarks">Remarks</label>
        <textarea id="coff-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Leave Policy tab ──
const PolicyTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getLeaveTypes(scope);
      setTypes(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the leave-type register.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  if (!can(CAP.LEAVE_POLICY_MANAGE)) {
    return <HrmsEmpty icon={CalendarDays} title="Leave policy is managed by HR" />;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--accent-orange-bg)] bg-[var(--accent-orange-bg)]
        p-3.5 text-[12px] text-[var(--accent-orange)]">
        These policy numbers are adjustable DEFAULTS, not the client's confirmed policy —
        §22.8 leaves CL/SL/EL/C-Off entitlement, accrual, carry-forward and expiry explicitly
        unconfirmed. Edit them once the client's HR policy is frozen.
      </div>
      {loading && <HrmsLoading label="Loading leave types…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        <div className="space-y-3">
          {types.map((t) => (
            <div key={t.code} className="rounded-xl border border-[var(--border)]
              bg-[var(--bg-card)] p-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[13px] font-bold text-[var(--text-main)]">
                  {t.name} <span className="text-[var(--text-muted)] font-normal">({t.code})</span>
                </p>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Entitlement {t.annual_entitlement}d · Carry-forward {t.carry_forward_ceiling}d
                  {t.coff_expiry_days ? ` · Expires ${t.coff_expiry_days}d after earning` : ''}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Chip tone={t.policy_confirmed ? 'good' : 'warn'}>
                  {t.policy_confirmed ? 'Policy Confirmed' : 'Not Confirmed'}
                </Chip>
                <Btn tone="ghost" onClick={() => setEditing(t)}>Edit</Btn>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing && (
        <PolicyEditModal type={editing} scope={scope} onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const PolicyEditModal = ({ type, scope, onClose, onDone, showSuccess, showError }) => {
  const [entitlement, setEntitlement] = useState(type.annual_entitlement ?? 0);
  const [carryForward, setCarryForward] = useState(type.carry_forward_ceiling ?? 0);
  const [allowEncashment, setAllowEncashment] = useState(!!type.allow_encashment);
  const [coffExpiry, setCoffExpiry] = useState(type.coff_expiry_days ?? 60);
  const [confirmed, setConfirmed] = useState(!!type.policy_confirmed);
  const [active, setActive] = useState(type.active !== false);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => run(() => saveLeaveType(type.code, {
    code: type.code, name: type.name, annual_entitlement: Number(entitlement) || 0,
    accrual_frequency: type.accrual_frequency || 'Annual',
    carry_forward_ceiling: Number(carryForward) || 0, allow_encashment: allowEncashment,
    requires_attachment_after_days: type.requires_attachment_after_days,
    notice_period_restricted: !!type.notice_period_restricted,
    coff_expiry_days: type.code === 'C-Off' ? Number(coffExpiry) || 60 : undefined,
    policy_confirmed: confirmed, active,
  }, scope), `${type.code} policy saved.`);

  return (
    <Modal title={`Edit ${type.name}`} labelledBy="policy-edit-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="pol-entitlement">Annual Entitlement (days)</label>
          <input id="pol-entitlement" type="number" min="0" value={entitlement} className={FIELD}
            onChange={(e) => setEntitlement(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="pol-carry">Carry-Forward Ceiling (days)</label>
          <input id="pol-carry" type="number" min="0" value={carryForward} className={FIELD}
            onChange={(e) => setCarryForward(e.target.value)} />
        </div>
      </div>
      {type.code === 'C-Off' && (
        <div>
          <label className={LABEL} htmlFor="pol-coff-expiry">C-Off Expiry (days after earning)</label>
          <input id="pol-coff-expiry" type="number" min="1" value={coffExpiry} className={FIELD}
            onChange={(e) => setCoffExpiry(e.target.value)} />
        </div>
      )}
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <input type="checkbox" checked={allowEncashment}
          onChange={(e) => setAllowEncashment(e.target.checked)} />
        Allow encashment
      </label>
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active (selectable when applying for leave)
      </label>
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        Client has confirmed this policy (§22.8)
      </label>
    </Modal>
  );
};

export default LeaveBoard;
