import React, { useCallback, useEffect, useState } from 'react';
import { Clock, Search, Lock, Unlock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import BoardTabs from '../common/BoardTabs';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getAttendance, markAttendance, getEmployees,
  requestRegularization, getRegularizations, actOnRegularization,
  requestOd, getOdRequests, actOnOd,
  getClosureDashboard, lockPeriod, unlockPeriod,
  getLateComingSummary,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Attendance (BA/Functional Design §7.8, §7.9, §7.12, §22.9).
 *
 * Four tabs over the same underlying case: the day's raw capture, the regularisation queue
 * it feeds, Outdoor Duty as its own small workflow (§7.8 step 59), and the monthly-closure
 * dashboard HR uses to lock a payroll-ready period. One page rather than four routes because
 * none of these is a "case" with its own detail URL the way a separation is — they are all
 * views onto the same rolling operational data.
 */

const TABS = ['Attendance', 'Regularizations', 'Outdoor Duty', 'Late Coming', 'Monthly Closure'];

const EXCEPTION_TYPES = ['Missing Punch', 'Wrong Time', 'Forgot to Mark', 'System Error', 'Other'];

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

const AttendanceBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState('Attendance');

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Clock}
        title="Attendance"
        subtitle="Daily capture, regularisation, Outdoor Duty and monthly closure."
      />
      <HrmsScopeBar />

      <BoardTabs tabs={TABS} value={tab} onChange={setTab} label="Attendance sections" />

      {tab === 'Attendance' && (
        <AttendanceTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Regularizations' && (
        <RegularizationsTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Outdoor Duty' && (
        <OdTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Late Coming' && (
        <LateComingTab scope={scope} companyId={companyId} />
      )}
      {tab === 'Monthly Closure' && (
        <ClosureTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ── Late Coming tab (§22.9) ──
const LateComingTab = ({ scope, companyId }) => {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focusEmployee, setFocusEmployee] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [year, month] = period.split('-').map(Number);
      const lastDay = new Date(year, month, 0).getDate();
      const { data } = await getLateComingSummary({
        ...scope, start_date: `${period}-01`, end_date: `${period}-${String(lastDay).padStart(2, '0')}`,
      });
      setSummary(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the late-coming summary.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, period]);

  useEffect(() => { load(); setFocusEmployee(null); }, [load]);

  const dates = summary?.dates || [];
  const shown = focusEmployee ? dates.filter((d) => d.employee_code === focusEmployee) : dates;
  const lateByDate = shown.reduce((acc, d) => {
    (acc[d.work_date] = acc[d.work_date] || []).push(d);
    return acc;
  }, {});
  const byEmployee = dates.reduce((acc, d) => {
    acc[d.employee_code] = (acc[d.employee_code] || 0) + 1;
    return acc;
  }, {});
  const employeeRows = Object.entries(byEmployee).sort((a, b) => b[1] - a[1]);
  const byDepartment = dates.reduce((acc, d) => {
    const key = d.department || 'Unassigned';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const departmentRows = Object.entries(byDepartment).sort((a, b) => b[1] - a[1]);

  const [year, month] = period.split('-').map(Number);
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = [...Array(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 justify-between">
        <div>
          <label className={LABEL} htmlFor="late-period">Period</label>
          <input id="late-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
            onChange={(e) => setPeriod(e.target.value)} />
        </div>
        {focusEmployee && (
          <Btn onClick={() => setFocusEmployee(null)}>Clear filter ({focusEmployee})</Btn>
        )}
      </div>

      {loading && <HrmsLoading label="Loading late-coming data…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && summary && (
        <div className="space-y-4">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              Total Late-Coming Days{focusEmployee ? ` · ${focusEmployee}` : ''}
            </p>
            <p className="mt-1 text-[24px] font-bold text-[var(--text-main)]">
              {focusEmployee ? shown.length : summary.total_late_days}
            </p>
          </div>

          {/* Calendar grid — each late date highlighted, clickable for the day's detail. */}
          <div>
            <p className={LABEL}>Calendar</p>
            <div className="grid grid-cols-7 gap-1.5 text-center">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
                <div key={d} className="text-[10.5px] font-bold text-[var(--text-muted)] pb-1">{d}</div>
              ))}
              {cells.map((day, i) => {
                if (!day) return <div key={`blank-${i}`} />;
                const dateStr = `${period}-${String(day).padStart(2, '0')}`;
                const hits = lateByDate[dateStr];
                return (
                  <div key={dateStr} title={hits ? hits.map((h) => `${h.employee_code}: ${h.late_minutes}m`).join(', ') : undefined}
                    className={`h-14 rounded-lg border text-[11.5px] flex flex-col items-center justify-center gap-0.5
                      ${hits
                        ? 'border-[var(--accent-red)]/40 bg-[var(--accent-red-bg)] text-[var(--accent-red)] font-bold'
                        : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                    <span>{day}</span>
                    {hits && <span className="text-[10px]">{hits.length} late</span>}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Late Coming Analytics — by department and by employee, for whoever can see
              more than their own record. */}
          {departmentRows.length > 1 && (
            <div>
              <p className={LABEL}>By Department</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {departmentRows.map(([dept, count]) => (
                  <div key={dept} className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
                    <p className="text-[11.5px] font-semibold text-[var(--text-main)] truncate">{dept}</p>
                    <p className="text-[10.5px] text-[var(--text-muted)]">{count} late day(s)</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {employeeRows.length > 0 && (
            <div>
              <p className={LABEL}>By Employee</p>
              <div className="space-y-1.5">
                {employeeRows.map(([code, count]) => (
                  <button key={code} type="button" onClick={() => setFocusEmployee(code)}
                    className="w-full flex items-center justify-between rounded-lg border border-[var(--border)]
                      bg-[var(--bg-card)] px-3 py-2 text-left hover:border-[var(--accent-indigo)]">
                    <span className="text-[12.5px] font-semibold text-[var(--text-main)]">{code}</span>
                    <Chip tone={count >= 5 ? 'bad' : count >= 2 ? 'warn' : 'neutral'}>{count} day(s)</Chip>
                  </button>
                ))}
              </div>
            </div>
          )}

          {!dates.length && (
            <HrmsEmpty icon={Clock} title="No late-coming days in this period" />
          )}
        </div>
      )}
    </div>
  );
};

// ── Attendance tab ──
const AttendanceTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [marking, setMarking] = useState(false);
  const [regularizing, setRegularizing] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getAttendance({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load attendance.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{day(r.work_date)}</span>
      </>
    ) },
    { key: 'time', label: 'In / Out', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.actual_in || '—'} – {r.actual_out || '—'}
      </span>
    ) },
    { key: 'late', label: 'Late', render: (r) => (
      <span className="text-[var(--text-main)]">{r.late_minutes ? `${r.late_minutes}m` : '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <Chip tone={attLeaveToneFor(r.status)}>{r.status}{r.locked ? ' · Locked' : ''}</Chip>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{day(r.work_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'In / Out', value: `${r.actual_in || '—'} – ${r.actual_out || '—'}` },
        { label: 'Late', value: r.late_minutes ? `${r.late_minutes}m` : '—' },
        { label: 'Locked', value: r.locked ? 'Yes' : 'No' },
      ]} />
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 justify-end">
        {can(CAP.ATTENDANCE_REGULARIZE_REQUEST) && (
          <Btn onClick={() => setRegularizing(true)}>Request Regularisation</Btn>
        )}
        {can(CAP.ATTENDANCE_MARK) && (
          <Btn tone="primary" onClick={() => setMarking(true)}>
            <Clock size={14} /> Mark Attendance
          </Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading attendance…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard}
            keyOf={(r) => `${r.employee_code}:${r.work_date}`} />
        ) : (
          <HrmsEmpty icon={Clock} title="No attendance captured yet"
            hint="Mark a day's attendance to get started." />
        )
      )}
      {marking && (
        <MarkModal scope={scope} onClose={() => setMarking(false)}
          onDone={() => { setMarking(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {regularizing && (
        <RegularizeModal scope={scope} onClose={() => setRegularizing(false)}
          onDone={() => { setRegularizing(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const MarkModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [workDate, setWorkDate] = useState(new Date().toISOString().slice(0, 10));
  const [actualIn, setActualIn] = useState('');
  const [actualOut, setActualOut] = useState('');
  const [overrideStatus, setOverrideStatus] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee) { showError('Select an employee.'); return; }
    run(() => markAttendance({
      employee_code: employee.employee_code, work_date: workDate,
      actual_in: actualIn || undefined, actual_out: actualOut || undefined,
      override_status: overrideStatus || undefined,
    }, scope), 'Attendance marked.');
  };

  return (
    <Modal title="Mark Attendance" labelledBy="att-mark-title"
      subtitle="The daily engine derives status/late-minutes from the company's shift policy."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Mark'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="att-date">Work Date *</label>
          <input id="att-date" type="date" value={workDate} className={FIELD}
            onChange={(e) => setWorkDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="att-override">Override Status</label>
          <select id="att-override" value={overrideStatus} className={FIELD}
            onChange={(e) => setOverrideStatus(e.target.value)}>
            <option value="">— derive from punches —</option>
            <option value="Weekly Off">Weekly Off</option>
            <option value="Holiday">Holiday</option>
          </select>
        </div>
      </div>
      {!overrideStatus && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="att-in">Actual In</label>
            <input id="att-in" type="time" value={actualIn} className={FIELD}
              onChange={(e) => setActualIn(e.target.value)} />
          </div>
          <div>
            <label className={LABEL} htmlFor="att-out">Actual Out</label>
            <input id="att-out" type="time" value={actualOut} className={FIELD}
              onChange={(e) => setActualOut(e.target.value)} />
          </div>
        </div>
      )}
    </Modal>
  );
};

const RegularizeModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [workDate, setWorkDate] = useState(new Date().toISOString().slice(0, 10));
  const [exceptionType, setExceptionType] = useState(EXCEPTION_TYPES[0]);
  const [proposedIn, setProposedIn] = useState('');
  const [proposedOut, setProposedOut] = useState('');
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !reason.trim()) {
      showError('Select the employee and describe the reason.');
      return;
    }
    run(() => requestRegularization({
      employee_code: employee.employee_code, work_date: workDate,
      exception_type: exceptionType, proposed_in: proposedIn || undefined,
      proposed_out: proposedOut || undefined, reason: reason.trim(),
    }, scope), 'Regularisation requested.');
  };

  return (
    <Modal title="Request Regularisation" labelledBy="att-reg-title"
      subtitle="Routes to the reporting manager, then HR for final sign-off (§7.9)."
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
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="reg-date">Work Date *</label>
          <input id="reg-date" type="date" value={workDate} className={FIELD}
            onChange={(e) => setWorkDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="reg-type">Exception Type *</label>
          <select id="reg-type" value={exceptionType} className={FIELD}
            onChange={(e) => setExceptionType(e.target.value)}>
            {EXCEPTION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="reg-in">Proposed In</label>
          <input id="reg-in" type="time" value={proposedIn} className={FIELD}
            onChange={(e) => setProposedIn(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="reg-out">Proposed Out</label>
          <input id="reg-out" type="time" value={proposedOut} className={FIELD}
            onChange={(e) => setProposedOut(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="reg-reason">Reason *</label>
        <textarea id="reg-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Regularizations tab ──
const RegularizationsTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getRegularizations({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load regularisations.');
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
        <span className="block text-[11px] text-[var(--text-muted)]">{r.req_no} · {day(r.work_date)}</span>
      </>
    ) },
    { key: 'type', label: 'Exception', render: (r) => (
      <span className="text-[var(--text-main)]">{r.exception_type}</span>
    ) },
    { key: 'proposed', label: 'Proposed', render: (r) => (
      <span className="text-[var(--text-main)]">{r.proposed_in || '—'} – {r.proposed_out || '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.ATTENDANCE_REGULARIZE_APPROVE) &&
          (r.status === 'Pending' || r.status === 'Manager Approved') && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.req_no} · {day(r.work_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Exception', value: r.exception_type },
        { label: 'Proposed', value: `${r.proposed_in || '—'} – ${r.proposed_out || '—'}` },
        { label: 'Reason', value: r.reason },
      ]} />
      {can(CAP.ATTENDANCE_REGULARIZE_APPROVE) &&
        (r.status === 'Pending' || r.status === 'Manager Approved') && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {loading && <HrmsLoading label="Loading regularisations…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.req_no} />
        ) : (
          <HrmsEmpty icon={Clock} title="No regularisation requests"
            hint="Requests raised from the Attendance tab appear here." />
        )
      )}
      {acting && (
        <RegularizeActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const RegularizeActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const nextStep = row.status === 'Pending' ? 'Manager Approved' : 'Approved';

  const act = (decision) => run(
    () => actOnRegularization(row.req_no, { decision, remarks: remarks.trim() || undefined }, scope),
    `${row.req_no} ${decision.toLowerCase()}.`);

  return (
    <Modal title={`Act on ${row.req_no}`} labelledBy="reg-act-title"
      subtitle={row.status === 'Pending'
        ? 'Manager step — HR still gives the final sign-off after this.'
        : 'HR-final step — approving now recalculates the attendance record.'}
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
        { label: 'Work Date', value: day(row.work_date) },
        { label: 'Exception', value: row.exception_type },
        { label: 'Reason', value: row.reason },
      ]} />
      <div>
        <label className={LABEL} htmlFor="reg-act-remarks">Remarks</label>
        <textarea id="reg-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Outdoor Duty tab ──
const OdTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requesting, setRequesting] = useState(false);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getOdRequests({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load OD requests.');
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
        <span className="block text-[11px] text-[var(--text-muted)]">{r.od_no} · {day(r.od_date)}</span>
      </>
    ) },
    { key: 'purpose', label: 'Purpose', render: (r) => (
      <span className="text-[var(--text-main)]">{r.purpose}{r.location ? ` · ${r.location}` : ''}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.OD_APPROVE) && r.status === 'Pending' && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.od_no} · {day(r.od_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[{ label: 'Purpose', value: r.purpose }, { label: 'Location', value: r.location }]} />
      {can(CAP.OD_APPROVE) && r.status === 'Pending' && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.OD_REQUEST) && <Btn tone="primary" onClick={() => setRequesting(true)}>Request OD</Btn>}
      </div>
      {loading && <HrmsLoading label="Loading OD requests…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.od_no} />
        ) : (
          <HrmsEmpty icon={Clock} title="No Outdoor Duty requests" />
        )
      )}
      {requesting && (
        <OdModal scope={scope} onClose={() => setRequesting(false)}
          onDone={() => { setRequesting(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <OdActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const OdModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [odDate, setOdDate] = useState(new Date().toISOString().slice(0, 10));
  const [purpose, setPurpose] = useState('');
  const [location, setLocation] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !purpose.trim()) { showError('Select the employee and describe the purpose.'); return; }
    run(() => requestOd({
      employee_code: employee.employee_code, od_date: odDate,
      purpose: purpose.trim(), location: location.trim() || undefined,
    }, scope), 'Outdoor Duty requested.');
  };

  return (
    <Modal title="Request Outdoor Duty" labelledBy="od-title" onClose={onClose}
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
        <label className={LABEL} htmlFor="od-date">OD Date *</label>
        <input id="od-date" type="date" value={odDate} className={FIELD}
          onChange={(e) => setOdDate(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="od-purpose">Purpose *</label>
        <input id="od-purpose" value={purpose} className={FIELD}
          onChange={(e) => setPurpose(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="od-location">Location</label>
        <input id="od-location" value={location} className={FIELD}
          onChange={(e) => setLocation(e.target.value)} />
      </div>
    </Modal>
  );
};

const OdActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const act = (approved) => run(
    () => actOnOd(row.od_no, { approved, remarks: remarks.trim() || undefined }, scope),
    `${row.od_no} ${approved ? 'approved' : 'rejected'}.`);

  return (
    <Modal title={`Act on ${row.od_no}`} labelledBy="od-act-title" onClose={onClose}
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
        { label: 'Employee', value: row.employee_name || row.employee_code },
        { label: 'OD Date', value: day(row.od_date) },
        { label: 'Purpose', value: row.purpose },
      ]} />
      <div>
        <label className={LABEL} htmlFor="od-act-remarks">Remarks</label>
        <textarea id="od-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Monthly Closure tab ──
const ClosureTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [unlocking, setUnlocking] = useState(false);
  const { busy, run } = useSubmit(showSuccess, showError, () => load());

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getClosureDashboard(period, scope);
      setDash(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the closure dashboard.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, period]);

  useEffect(() => { load(); }, [load]);

  if (!can(CAP.ATTENDANCE_LOCK)) {
    return <HrmsEmpty icon={Lock} title="Monthly closure is managed by HR" />;
  }

  return (
    <div className="space-y-4">
      <div>
        <label className={LABEL} htmlFor="closure-period">Period</label>
        <input id="closure-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
          onChange={(e) => setPeriod(e.target.value)} />
      </div>
      {loading && <HrmsLoading label="Loading closure dashboard…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && dash && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              ['Missing Punches', dash.missing_punches],
              ['Pending Regularisations', dash.pending_regularizations],
              ['Pending OD', dash.pending_od],
              ['Unexplained Absence', dash.unexplained_absence],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-[var(--border)]
                bg-[var(--bg-card)] p-3.5">
                <p className="text-[10.5px] font-bold uppercase tracking-widest
                  text-[var(--text-muted)]">{label}</p>
                <p className="mt-1 text-[20px] font-bold text-[var(--text-main)]">{value}</p>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between rounded-xl border
            border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div>
              <Chip tone={attLeaveToneFor(dash.status)}>{dash.status}</Chip>
              {dash.status === 'Locked' && (
                <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                  Locked {day(dash.locked_at)}
                </p>
              )}
            </div>
            {dash.status === 'Locked' ? (
              <Btn onClick={() => setUnlocking(true)}><Unlock size={14} /> Unlock</Btn>
            ) : (
              <Btn tone="primary" disabled={busy || !dash.ready_to_lock}
                onClick={() => run(() => lockPeriod(period, scope), `${period} locked.`)}>
                <Lock size={14} /> {busy ? 'Working…' : 'Lock Period'}
              </Btn>
            )}
          </div>
          {!dash.ready_to_lock && dash.status !== 'Locked' && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              Resolve every exception above before this period can be locked.
            </p>
          )}
        </div>
      )}
      {unlocking && (
        <UnlockModal period={period} scope={scope} onClose={() => setUnlocking(false)}
          onDone={() => { setUnlocking(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const UnlockModal = ({ period, scope, onClose, onDone, showSuccess, showError }) => {
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const submit = () => {
    if (!reason.trim()) { showError('A reason is required to reopen a locked period.'); return; }
    run(() => unlockPeriod(period, reason.trim(), scope), `${period} reopened.`);
  };
  return (
    <Modal title={`Unlock ${period}`} labelledBy="unlock-title"
      subtitle="Post-lock changes require an authorised, reasoned reopen (§7.12)."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Unlock'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="unlock-reason">Reason *</label>
        <textarea id="unlock-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

export default AttendanceBoard;
