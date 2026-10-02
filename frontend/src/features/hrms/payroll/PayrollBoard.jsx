import React, { useCallback, useEffect, useState } from 'react';
import { Wallet, Search, Landmark, HandCoins, TrendingUp, X } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import BoardTabs from '../common/BoardTabs';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees,
  listSalaryComponents, saveSalaryComponent, saveSalaryStructure, getSalaryStructureHistory,
  createPayrollRun, listPayrollRuns, getPayrollRun, calculatePayroll, listPayrollRecords,
  adjustPayrollRecord, decidePayrollRun,
  getAdvancePolicy, saveAdvancePolicy, checkAdvanceEligibility, requestAdvance, listAdvances,
  actOnAdvance, actOnAdvanceEmergency,
  getVariablePayPolicy, saveVariablePayPolicy, createVariablePayQuarter, listVariablePayQuarters,
  saveVariablePayRecord, listVariablePayRecords, calculateVariablePay, decideVariablePayQuarter,
  listVariablePayHoldLedger, actOnVariablePayHold,
  getPayslipTemplate, savePayslipTemplate, listPayslips, setPayrollAdjustments,
} from '../../../services/hrmsApi';
import Payslip, { PayslipDocument } from './Payslip';
import { FIELD, LABEL, TEXTAREA, day, money, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Payroll, Salary Advance & Variable Pay (BA/Functional Design §7.13-7.15, §22.7).
 *
 * Four tabs, the same shape every Phase-N board in this module uses. Payroll is
 * component-driven (§22.7): a small configurable component master plus a per-employee
 * structure, not a fixed set of fields. No statutory engine exists (§7.13 BR: "requires
 * payroll workshop"), so PF/ESI/PT/TDS are always hand-entered per run, the same honesty
 * FnfInput already models for the missing payroll engine elsewhere in this module.
 */

const TABS = ['Payroll Runs', 'Salary Structure', 'Salary Advance', 'Variable Pay',
  'My Payslip', 'Payslip Template'];

const EmployeePicker = ({ scope, value, onChange, placeholder }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!debounced.trim() || value) return;
    let live = true;
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
      <input value={search} placeholder={placeholder || 'Search by name or employee code…'}
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
      await fn();
      if (successMsg) showSuccess(successMsg);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const PayrollBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState('Payroll Runs');

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Wallet}
        title="Payroll"
        subtitle="Component-driven payroll, salary advance and the quarterly variable-pay hold ledger."
      />
      <HrmsScopeBar />

      <BoardTabs tabs={TABS} value={tab} onChange={setTab} label="Payroll sections" />

      {tab === 'Payroll Runs' && (
        <PayrollRunsTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Salary Structure' && (
        <SalaryStructureTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Salary Advance' && (
        <SalaryAdvanceTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Variable Pay' && (
        <VariablePayTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'My Payslip' && <Payslip embedded />}
      {tab === 'Payslip Template' && (
        <PayslipTemplateTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ── Payroll Runs tab ──
const PayrollRunsTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [openPeriod, setOpenPeriod] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listPayrollRuns(scope);
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load payroll runs.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'period', label: 'Period', render: (r) => (
      <span className="font-semibold text-[var(--text-main)]">{r.period}</span>
    ) },
    { key: 'eligible', label: 'Eligible', render: (r) => <span>{r.eligible_count}</span> },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenPeriod(r.period)}>Open</Btn>
      </div>
    ) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.PAYROLL_PROCESS) && (
          <Btn tone="primary" onClick={() => setCreating(true)}><Landmark size={14} /> Create Run</Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading payroll runs…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">{r.period}</p>
                  <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
                </div>
                <Facts items={[{ label: 'Eligible', value: r.eligible_count }]} />
                <Btn tone="ghost" onClick={() => setOpenPeriod(r.period)}>Open</Btn>
              </div>
            )}
            keyOf={(r) => r.period} />
        ) : (
          <HrmsEmpty icon={Landmark} title="No payroll runs yet" />
        )
      )}
      {creating && (
        <CreateRunModal scope={scope} onClose={() => setCreating(false)}
          onDone={() => { setCreating(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openPeriod && (
        <RunDetailModal period={openPeriod} scope={scope} can={can}
          onClose={() => setOpenPeriod(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const CreateRunModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  return (
    <Modal title="Create Payroll Run" labelledBy="run-create-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" disabled={busy} onClick={() => run(
            () => createPayrollRun({ period }, scope), `${period} run created.`)}>
            {busy ? 'Working…' : 'Create'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="run-period">Period</label>
        <input id="run-period" type="month" value={period} className={FIELD}
          onChange={(e) => setPeriod(e.target.value)} />
      </div>
    </Modal>
  );
};

const RunDetailModal = ({ period, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [runInfo, setRunInfo] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adjusting, setAdjusting] = useState(null);
  const [viewingPayslip, setViewingPayslip] = useState(null);
  const [allPayslips, setAllPayslips] = useState(null);
  const [loadingAll, setLoadingAll] = useState(false);
  const [decisionRemarks, setDecisionRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const openAllPayslips = async () => {
    setLoadingAll(true);
    try {
      const { data } = await listPayslips(period, scope);
      setAllPayslips(data || []);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not load payslips for this run.');
    } finally {
      setLoadingAll(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [{ data: ri }, { data: recs }] = await Promise.all([
        getPayrollRun(period, scope), listPayrollRecords(period, scope),
      ]);
      setRunInfo(ri);
      setRecords(recs || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this run.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal title={`Payroll Run · ${period}`} labelledBy="run-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading run…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && runInfo && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Chip tone={attLeaveToneFor(runInfo.status)}>{runInfo.status}</Chip>
            <div className="flex gap-2">
              {records.length > 0 && (
                <Btn disabled={loadingAll} onClick={openAllPayslips}>
                  {loadingAll ? 'Loading…' : 'All Payslips'}
                </Btn>
              )}
              {can(CAP.PAYROLL_PROCESS) && runInfo.status !== 'Locked' && (
                <Btn disabled={busy} onClick={() => run(
                  () => calculatePayroll(period, scope), 'Payroll calculated.')}>
                  {busy ? 'Working…' : 'Calculate'}
                </Btn>
              )}
            </div>
          </div>

          {records.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr className="text-left text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    <th className="py-1.5 pr-2">Employee</th>
                    <th className="py-1.5 pr-2">Payable/LOP</th>
                    <th className="py-1.5 pr-2">Gross</th>
                    <th className="py-1.5 pr-2">Deductions</th>
                    <th className="py-1.5 pr-2">Net Pay</th>
                    <th className="py-1.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => (
                    <tr key={r.employee_code} className="border-t border-[var(--border)]">
                      <td className="py-1.5 pr-2">
                        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
                        {r.exceptions?.length > 0 && (
                          <span className="block text-[10px] text-[var(--accent-orange)]">
                            {r.exceptions.join('; ')}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-2">{r.payable_days}/{r.lop_days}</td>
                      <td className="py-1.5 pr-2">{money(r.gross_earnings)}</td>
                      <td className="py-1.5 pr-2">{money(r.total_deductions)}</td>
                      <td className="py-1.5 pr-2 font-bold">{money(r.net_pay)}</td>
                      <td className="py-1.5">
                        <div className="flex justify-end gap-1.5">
                          <Btn tone="ghost" onClick={() => setViewingPayslip(r)}>Payslip</Btn>
                          {can(CAP.PAYROLL_PROCESS) && runInfo.status !== 'Locked' && (
                            <Btn tone="ghost" onClick={() => setAdjusting(r)}>Adjust</Btn>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!records.length && (
            <p className="text-[12px] text-[var(--text-muted)] py-2">
              No records yet — click Calculate to import the eligible population.
            </p>
          )}

          {can(CAP.PAYROLL_APPROVE) && runInfo.status === 'Calculated' && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Decision</p>
              <textarea rows={2} value={decisionRemarks} className={TEXTAREA} placeholder="Remarks"
                onChange={(e) => setDecisionRemarks(e.target.value)} />
              <div className="flex gap-2">
                <Btn tone="danger" disabled={busy} onClick={() => run(
                  () => decidePayrollRun(period, { approved: false, remarks: decisionRemarks.trim() || undefined }, scope),
                  'Payroll sent back to the maker.')}>
                  Reject
                </Btn>
                <Btn tone="primary" disabled={busy} onClick={() => run(
                  () => decidePayrollRun(period, { approved: true, remarks: decisionRemarks.trim() || undefined }, scope),
                  'Payroll approved and locked.')}>
                  {busy ? 'Working…' : 'Approve & Lock'}
                </Btn>
              </div>
            </div>
          )}
        </div>
      )}
      {adjusting && (
        <AdjustRecordModal period={period} record={adjusting} scope={scope}
          onClose={() => setAdjusting(null)} onDone={() => { setAdjusting(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {viewingPayslip && (
        <Modal title={`Payslip · ${viewingPayslip.employee_name || viewingPayslip.employee_code}`}
          labelledBy="hr-payslip-title" onClose={() => setViewingPayslip(null)}
          footer={<Btn onClick={() => setViewingPayslip(null)}>Close</Btn>}
        >
          <Payslip embedded employeeCode={viewingPayslip.employee_code} initialPeriod={period} />
        </Modal>
      )}
      {allPayslips && (
        <div className="fixed inset-0 z-50 bg-black/60 overflow-y-auto py-8 px-4">
          <div className="max-w-3xl mx-auto space-y-6 print:space-y-0">
            <div className="flex justify-end gap-2 print:hidden">
              <button type="button" onClick={() => window.print()}
                className="h-9 px-3.5 rounded-lg bg-white text-[12px] font-bold text-slate-900">
                Print / Save all as PDF
              </button>
              <button type="button" onClick={() => setAllPayslips(null)}
                className="h-9 w-9 rounded-lg bg-white text-slate-900 flex items-center justify-center">
                <X size={16} />
              </button>
            </div>
            {allPayslips.length === 0 && (
              <p className="text-center text-[13px] text-white">No payslips in this run yet.</p>
            )}
            {allPayslips.map((slip, i) => (
              <div key={slip.employee_code}
                style={i > 0 ? { breakBefore: 'page' } : undefined}>
                <PayslipDocument slip={slip} />
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
};

const AdjustRecordModal = ({ period, record, scope, onClose, onDone, showSuccess, showError }) => {
  const [pf, setPf] = useState(record.pf ?? 0);
  const [esi, setEsi] = useState(record.esi ?? 0);
  const [pt, setPt] = useState(record.pt ?? 0);
  const [tds, setTds] = useState(record.tds ?? 0);
  const [arrears, setArrears] = useState(record.arrears ?? 0);
  const [reimbursements, setReimbursements] = useState(record.reimbursements ?? 0);
  const [otherEarnings, setOtherEarnings] = useState(record.other_earnings ?? 0);
  const [otherDeductions, setOtherDeductions] = useState(record.other_deductions ?? 0);
  const [noticeRecovery, setNoticeRecovery] = useState(record.notice_recovery ?? 0);
  const [remarks, setRemarks] = useState(record.remarks || '');
  const [components, setComponents] = useState([]);
  const [adjustments, setAdjustments] = useState(
    (record.adjustments || []).map((a) => ({ code: a.code, amount: a.amount })));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    listSalaryComponents(scope).then(({ data }) => setComponents(data || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addAdjustment = () => setAdjustments((a) => [
    ...a, { code: components[0]?.code || '', amount: 0 },
  ]);
  const updateAdjustment = (i, key, value) =>
    setAdjustments((a) => a.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)));
  const removeAdjustment = (i) => setAdjustments((a) => a.filter((_, idx) => idx !== i));

  const submit = () => run(async () => {
    await adjustPayrollRecord(period, record.employee_code, {
      pf: Number(pf), esi: Number(esi), pt: Number(pt), tds: Number(tds),
      arrears: Number(arrears), reimbursements: Number(reimbursements),
      other_earnings: Number(otherEarnings), other_deductions: Number(otherDeductions),
      notice_recovery: Number(noticeRecovery), remarks: remarks.trim() || undefined,
    }, scope);
    await setPayrollAdjustments(period, record.employee_code,
      adjustments.filter((a) => a.code).map((a) => ({ code: a.code, amount: Number(a.amount) })),
      scope);
  }, 'Record adjusted.');

  const field = (label, value, setter) => (
    <div>
      <label className={LABEL}>{label}</label>
      <input type="number" value={value} className={FIELD} onChange={(e) => setter(e.target.value)} />
    </div>
  );

  return (
    <Modal title={`Adjust ${record.employee_code}`} labelledBy="adjust-title"
      subtitle="No statutory engine exists yet — enter every statutory/one-off figure by hand (§7.13 BR)."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        {field('PF', pf, setPf)}
        {field('ESI', esi, setEsi)}
        {field('PT', pt, setPt)}
        {field('TDS', tds, setTds)}
        {field('Arrears', arrears, setArrears)}
        {field('Reimbursements', reimbursements, setReimbursements)}
        {field('Other Earnings', otherEarnings, setOtherEarnings)}
        {field('Other Deductions', otherDeductions, setOtherDeductions)}
        {field('Notice Recovery', noticeRecovery, setNoticeRecovery)}
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className={LABEL}>Ad-hoc components (§22.7)</label>
          <Btn onClick={addAdjustment} disabled={!components.length}>Add line</Btn>
        </div>
        {!adjustments.length && (
          <p className="text-[12px] text-[var(--text-muted)]">
            Any earning/deduction beyond the fields above — against the same component
            master the salary structure uses.
          </p>
        )}
        <div className="space-y-2">
          {adjustments.map((row, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_auto] gap-2 items-center">
              <select className={FIELD} value={row.code}
                onChange={(e) => updateAdjustment(i, 'code', e.target.value)}>
                {components.map((c) => (
                  <option key={c.code} value={c.code}>{c.name} ({c.component_type})</option>
                ))}
              </select>
              <input type="number" className={FIELD} value={row.amount}
                onChange={(e) => updateAdjustment(i, 'amount', e.target.value)} />
              <button type="button" onClick={() => removeAdjustment(i)}
                className="h-9 w-9 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]">
                ×
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="adjust-remarks">Remarks</label>
        <textarea id="adjust-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Salary Structure tab ──
const SalaryStructureTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [components, setComponents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [addingComponent, setAddingComponent] = useState(false);
  const [employee, setEmployee] = useState(null);
  const [history, setHistory] = useState([]);
  const [assigning, setAssigning] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listSalaryComponents(scope);
      setComponents(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load salary components.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!employee) { setHistory([]); return; }
    getSalaryStructureHistory(employee.employee_code, scope)
      .then(({ data }) => setHistory(data || [])).catch(() => setHistory([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee]);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[12.5px] font-bold text-[var(--text-main)]">Component Master (§22.7)</p>
          {can(CAP.SALARY_STRUCTURE_MANAGE) && (
            <Btn tone="ghost" onClick={() => setAddingComponent(true)}>Add Component</Btn>
          )}
        </div>
        {loading && <HrmsLoading label="Loading components…" />}
        {error && !loading && <HrmsError message={error} onRetry={load} />}
        {!loading && !error && (
          components.length ? (
            <div className="flex flex-wrap gap-2">
              {components.map((c) => (
                <Chip key={c.code} tone={c.component_type === 'Earning' ? 'good' : 'warn'}>
                  {c.name} ({c.code})
                </Chip>
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-[var(--text-muted)]">No components configured yet.</p>
          )
        )}
      </div>

      <div>
        <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-2">Employee Structure</p>
        <div className="max-w-sm mb-3">
          <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
        </div>
        {employee && (
          <div className="space-y-3">
            {can(CAP.SALARY_STRUCTURE_MANAGE) && (
              <Btn tone="primary" onClick={() => setAssigning(true)}>New Structure</Btn>
            )}
            {history.length ? history.map((h) => (
              <div key={h.id || h.effective_from} className="rounded-xl border border-[var(--border)]
                bg-[var(--bg-card)] p-3.5">
                <p className="text-[11px] font-bold text-[var(--text-muted)]">
                  Effective {day(h.effective_from)}
                </p>
                <div className="flex flex-wrap gap-2 mt-1.5">
                  {(h.components || []).map((c) => (
                    <Chip key={c.code}>{c.code}: {money(c.amount)}</Chip>
                  ))}
                </div>
              </div>
            )) : (
              <p className="text-[12px] text-[var(--text-muted)]">No structure on file yet.</p>
            )}
          </div>
        )}
      </div>

      {addingComponent && (
        <ComponentModal scope={scope} onClose={() => setAddingComponent(false)}
          onDone={() => { setAddingComponent(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {assigning && (
        <StructureModal employee={employee} components={components} scope={scope}
          onClose={() => setAssigning(false)}
          onDone={() => {
            setAssigning(false);
            getSalaryStructureHistory(employee.employee_code, scope)
              .then(({ data }) => setHistory(data || [])).catch(() => {});
          }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const ComponentModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [componentType, setComponentType] = useState('Earning');
  const [statutory, setStatutory] = useState(false);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!code.trim() || !name.trim()) { showError('Code and name are required.'); return; }
    const upperCode = code.trim().toUpperCase();
    // The route overrides `code` from the URL anyway, but SalaryComponentIn still requires
    // it in the body — the same shape LeaveTypeConfigIn/saveLeaveType already use.
    run(() => saveSalaryComponent(upperCode, {
      code: upperCode, name: name.trim(), component_type: componentType, statutory, active: true,
    }, scope), 'Component saved.');
  };

  return (
    <Modal title="Add Salary Component" labelledBy="component-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="comp-code">Code</label>
          <input id="comp-code" value={code} className={FIELD} placeholder="e.g. BASIC"
            onChange={(e) => setCode(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="comp-type">Type</label>
          <select id="comp-type" value={componentType} className={FIELD}
            onChange={(e) => setComponentType(e.target.value)}>
            <option value="Earning">Earning</option>
            <option value="Deduction">Deduction</option>
          </select>
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="comp-name">Name</label>
        <input id="comp-name" value={name} className={FIELD}
          onChange={(e) => setName(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <input type="checkbox" checked={statutory} onChange={(e) => setStatutory(e.target.checked)} />
        Statutory component
      </label>
    </Modal>
  );
};

const StructureModal = ({ employee, components, scope, onClose, onDone, showSuccess, showError }) => {
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().slice(0, 10));
  const [amounts, setAmounts] = useState({});
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    const rows = Object.entries(amounts)
      .filter(([, v]) => Number(v) > 0)
      .map(([code, amount]) => ({ code, amount: Number(amount) }));
    if (!rows.length) { showError('Enter at least one component amount.'); return; }
    run(() => saveSalaryStructure({
      employee_code: employee.employee_code, effective_from: effectiveFrom, components: rows,
    }, scope), 'Structure saved.');
  };

  return (
    <Modal title={`New Structure · ${employee.employee_code}`} labelledBy="structure-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="structure-date">Effective From</label>
        <input id="structure-date" type="date" value={effectiveFrom} className={FIELD}
          onChange={(e) => setEffectiveFrom(e.target.value)} />
      </div>
      {components.map((c) => (
        <div key={c.code}>
          <label className={LABEL}>{c.name} ({c.component_type})</label>
          <input type="number" className={FIELD} value={amounts[c.code] || ''}
            onChange={(e) => setAmounts({ ...amounts, [c.code]: e.target.value })} />
        </div>
      ))}
      {!components.length && (
        <p className="text-[12px] text-[var(--text-muted)]">
          Add at least one component on the master before assigning a structure.
        </p>
      )}
    </Modal>
  );
};

// ── Salary Advance tab ──
const SalaryAdvanceTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requesting, setRequesting] = useState(false);
  const [acting, setActing] = useState(null);
  const [editingPolicy, setEditingPolicy] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [{ data }, { data: pol }] = await Promise.all([
        listAdvances(scope), getAdvancePolicy(scope),
      ]);
      setRows(data || []);
      setPolicy(pol);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load salary advances.');
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
        <span className="block text-[11px] text-[var(--text-muted)]">{r.adv_no}</span>
      </>
    ) },
    { key: 'amount', label: 'Amount', render: (r) => <span>{money(r.amount)}</span> },
    { key: 'recovered', label: 'Recovered', render: (r) => <span>{money(r.recovered_amount)}</span> },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {r.status === 'Pending' && (
          <div className="flex gap-1.5">
            {can(CAP.ADVANCE_APPROVE) && (
              <Btn tone="ghost" onClick={() => setActing({ row: r, emergency: false })}>Act</Btn>
            )}
            {can(CAP.ADVANCE_APPROVE_EMERGENCY) && (
              <Btn tone="ghost" onClick={() => setActing({ row: r, emergency: true })}>Act (Emergency)</Btn>
            )}
          </div>
        )}
      </div>
    ) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-[var(--text-muted)]">
          {policy ? `Up to ${policy.max_percent_of_gross}% of gross · requests accepted day
          ${policy.window_start_day}-${policy.window_end_day} · once per quarter.` : ''}
        </p>
        <div className="flex gap-2">
          {can(CAP.ADVANCE_APPROVE) && (
            <Btn tone="ghost" onClick={() => setEditingPolicy(true)}>Edit Policy</Btn>
          )}
          {can(CAP.ADVANCE_REQUEST) && (
            <Btn tone="primary" onClick={() => setRequesting(true)}>
              <HandCoins size={14} /> Request Advance
            </Btn>
          )}
        </div>
      </div>
      {loading && <HrmsLoading label="Loading salary advances…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">{r.adv_no}</p>
                  </div>
                  <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
                </div>
                <Facts items={[
                  { label: 'Amount', value: money(r.amount) },
                  { label: 'Recovered', value: money(r.recovered_amount) },
                ]} />
              </div>
            )}
            keyOf={(r) => r.adv_no} />
        ) : (
          <HrmsEmpty icon={HandCoins} title="No salary advances yet" />
        )
      )}
      {requesting && (
        <RequestAdvanceModal scope={scope} onClose={() => setRequesting(false)}
          onDone={() => { setRequesting(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <AdvanceActionModal row={acting.row} emergency={acting.emergency} scope={scope}
          onClose={() => setActing(null)} onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingPolicy && (
        <AdvancePolicyModal policy={policy} scope={scope} onClose={() => setEditingPolicy(false)}
          onDone={() => { setEditingPolicy(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const RequestAdvanceModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [eligibility, setEligibility] = useState(null);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    if (!employee) { setEligibility(null); return; }
    checkAdvanceEligibility(employee.employee_code, scope)
      .then(({ data }) => setEligibility(data)).catch(() => setEligibility(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee]);

  const submit = () => {
    if (!employee || !amount) { showError('Select the employee and enter an amount.'); return; }
    run(() => requestAdvance({
      employee_code: employee.employee_code, amount: Number(amount), reason: reason.trim() || undefined,
    }, scope), 'Salary advance requested.');
  };

  return (
    <Modal title="Request Salary Advance" labelledBy="advance-title" onClose={onClose}
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
      {eligibility && (
        <div className={`rounded-lg p-3 text-[11.5px] ${eligibility.eligible
          ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]'
          : 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]'}`}>
          Max eligible: {money(eligibility.max_eligible_amount)}
          {!eligibility.confirmed && ' · Not confirmed (still on probation)'}
          {!eligibility.in_window && ' · Outside the request window'}
          {eligibility.already_availed_this_quarter && ' · Already availed this quarter'}
        </div>
      )}
      <div>
        <label className={LABEL} htmlFor="advance-amount">Amount *</label>
        <input id="advance-amount" type="number" value={amount} className={FIELD}
          onChange={(e) => setAmount(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="advance-reason">Reason</label>
        <textarea id="advance-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

const AdvanceActionModal = ({ row, emergency, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const act = (approved) => run(
    () => (emergency ? actOnAdvanceEmergency : actOnAdvance)(
      row.adv_no, { approved, remarks: remarks.trim() || undefined }, scope),
    approved ? `${row.adv_no} approved.` : `${row.adv_no} rejected.`);

  return (
    <Modal title={`Act on ${row.adv_no}${emergency ? ' (Emergency)' : ''}`}
      labelledBy="advance-act-title" onClose={onClose}
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
        { label: 'Amount', value: money(row.amount) },
        { label: 'Reason', value: row.reason },
      ]} />
      <div>
        <label className={LABEL} htmlFor="advance-act-remarks">Remarks</label>
        <textarea id="advance-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

const AdvancePolicyModal = ({ policy, scope, onClose, onDone, showSuccess, showError }) => {
  const [maxPercent, setMaxPercent] = useState(policy?.max_percent_of_gross ?? 40);
  const [start, setStart] = useState(policy?.window_start_day ?? 20);
  const [end, setEnd] = useState(policy?.window_end_day ?? 25);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => run(() => saveAdvancePolicy({
    max_percent_of_gross: Number(maxPercent), window_start_day: Number(start), window_end_day: Number(end),
  }, scope), 'Advance policy saved.');

  return (
    <Modal title="Salary Advance Policy" labelledBy="advance-policy-title"
      subtitle="§7.14 — adjustable defaults, not a frozen rule." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="policy-max">Max % of Gross</label>
        <input id="policy-max" type="number" value={maxPercent} className={FIELD}
          onChange={(e) => setMaxPercent(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="policy-start">Window Start Day</label>
          <input id="policy-start" type="number" min="1" max="31" value={start} className={FIELD}
            onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="policy-end">Window End Day</label>
          <input id="policy-end" type="number" min="1" max="31" value={end} className={FIELD}
            onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

// ── Variable Pay tab ──
const VariablePayTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [quarters, setQuarters] = useState([]);
  const [holdLedger, setHoldLedger] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [openQuarter, setOpenQuarter] = useState(null);
  const [editingPolicy, setEditingPolicy] = useState(false);
  const [policy, setPolicy] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [{ data: qs }, { data: hl }, { data: pol }] = await Promise.all([
        listVariablePayQuarters(scope), listVariablePayHoldLedger(scope), getVariablePayPolicy(scope),
      ]);
      setQuarters(qs || []);
      setHoldLedger(hl || []);
      setPolicy(pol);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load variable pay.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-[var(--text-muted)]">
          {policy ? `ORM ≥${policy.orm_threshold}% · IRM ≥${policy.irm_threshold}% ·
          ${policy.payable_percent}% payable / ${policy.held_percent}% held.` : ''}
        </p>
        <div className="flex gap-2">
          {can(CAP.VARIABLE_PAY_APPROVE) && (
            <Btn tone="ghost" onClick={() => setEditingPolicy(true)}>Edit Policy</Btn>
          )}
          {can(CAP.VARIABLE_PAY_PROCESS) && (
            <Btn tone="primary" onClick={() => setCreating(true)}>
              <TrendingUp size={14} /> Create Quarter
            </Btn>
          )}
        </div>
      </div>
      {loading && <HrmsLoading label="Loading variable pay…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        <>
          <div>
            <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-2">Quarters</p>
            {quarters.length ? (
              <RecordList
                rows={quarters}
                columns={[
                  { key: 'quarter', label: 'Quarter', render: (r) => (
                    <span className="font-semibold text-[var(--text-main)]">{r.quarter}</span>
                  ) },
                  { key: 'orm', label: 'ORM Score', render: (r) => <span>{r.orm_score}%</span> },
                  { key: 'status', label: 'Status', align: 'right', render: (r) => (
                    <div className="flex flex-col items-end gap-1.5">
                      <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
                      <Btn tone="ghost" onClick={() => setOpenQuarter(r.quarter)}>Open</Btn>
                    </div>
                  ) },
                ]}
                renderCard={(r) => (
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">{r.quarter}</p>
                      <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
                    </div>
                    <Facts items={[{ label: 'ORM Score', value: `${r.orm_score}%` }]} />
                    <Btn tone="ghost" onClick={() => setOpenQuarter(r.quarter)}>Open</Btn>
                  </div>
                )}
                keyOf={(r) => r.quarter}
              />
            ) : (
              <HrmsEmpty icon={TrendingUp} title="No variable pay quarters yet" />
            )}
          </div>

          <div>
            <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-2">Hold Ledger</p>
            {holdLedger.length ? (
              <RecordList
                rows={holdLedger}
                columns={[
                  { key: 'who', label: 'Employee', render: (r) => (
                    <>
                      <span className="font-semibold text-[var(--text-main)]">{r.employee_code}</span>
                      <span className="block text-[11px] text-[var(--text-muted)]">{r.quarter}</span>
                    </>
                  ) },
                  { key: 'amount', label: 'Held Amount', render: (r) => <span>{money(r.held_amount)}</span> },
                  { key: 'status', label: 'Status', align: 'right', render: (r) => (
                    <div className="flex flex-col items-end gap-1.5">
                      <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
                      {can(CAP.VARIABLE_PAY_HOLD_MANAGE) && r.status === 'Held' && (
                        <div className="flex gap-1.5">
                          <Btn tone="ghost" onClick={() => run_release(r)}>Release</Btn>
                          <Btn tone="ghost" onClick={() => run_forfeit(r)}>Forfeit</Btn>
                        </div>
                      )}
                    </div>
                  ) },
                ]}
                renderCard={(r) => (
                  <Facts items={[
                    { label: 'Employee', value: r.employee_code },
                    { label: 'Quarter', value: r.quarter },
                    { label: 'Held Amount', value: money(r.held_amount) },
                  ]} />
                )}
                keyOf={(r) => r.id}
              />
            ) : (
              <p className="text-[12px] text-[var(--text-muted)]">No held amounts.</p>
            )}
          </div>
        </>
      )}
      {creating && (
        <CreateQuarterModal scope={scope} onClose={() => setCreating(false)}
          onDone={() => { setCreating(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openQuarter && (
        <QuarterDetailModal quarter={openQuarter} scope={scope} can={can}
          onClose={() => setOpenQuarter(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingPolicy && (
        <VariablePayPolicyModal policy={policy} scope={scope} onClose={() => setEditingPolicy(false)}
          onDone={() => { setEditingPolicy(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );

  function run_release(r) {
    actOnVariablePayHold(r.id, { action: 'Release' }, scope)
      .then(() => { showSuccess('Held amount released.'); load(); })
      .catch((err) => showError(err?.response?.data?.detail || 'Could not release this hold.'));
  }
  function run_forfeit(r) {
    actOnVariablePayHold(r.id, { action: 'Forfeit' }, scope)
      .then(() => { showSuccess('Held amount forfeited.'); load(); })
      .catch((err) => showError(err?.response?.data?.detail || 'Could not forfeit this hold.'));
  }
};

const CreateQuarterModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [quarter, setQuarter] = useState('');
  const [ormScore, setOrmScore] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!quarter.trim() || !ormScore) { showError('Enter the quarter and the ORM score.'); return; }
    run(() => createVariablePayQuarter({ quarter: quarter.trim(), orm_score: Number(ormScore) }, scope),
      'Quarter created.');
  };

  return (
    <Modal title="Create Variable Pay Quarter" labelledBy="vp-create-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Create'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="vp-quarter">Quarter</label>
        <input id="vp-quarter" value={quarter} className={FIELD} placeholder="e.g. 2026-Q1"
          onChange={(e) => setQuarter(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="vp-orm">Company ORM Score (%)</label>
        <input id="vp-orm" type="number" value={ormScore} className={FIELD}
          onChange={(e) => setOrmScore(e.target.value)} />
      </div>
    </Modal>
  );
};

const QuarterDetailModal = ({ quarter, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [info, setInfo] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [addingRecord, setAddingRecord] = useState(false);
  const [decisionRemarks, setDecisionRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [{ data: qi }, { data: recs }] = await Promise.all([
        listVariablePayQuarters(scope).then(({ data }) => ({ data: (data || []).find((q) => q.quarter === quarter) })),
        listVariablePayRecords(quarter, scope),
      ]);
      setInfo(qi);
      setRecords(recs || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this quarter.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quarter]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal title={`Variable Pay · ${quarter}`} labelledBy="vp-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading quarter…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && info && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Chip tone={attLeaveToneFor(info.status)}>{info.status}</Chip>
            <div className="flex gap-2">
              {can(CAP.VARIABLE_PAY_PROCESS) && (
                <Btn onClick={() => setAddingRecord(true)}>Add Score</Btn>
              )}
              {can(CAP.VARIABLE_PAY_PROCESS) && info.status === 'Draft' && (
                <Btn disabled={busy} onClick={() => run(
                  () => calculateVariablePay(quarter, scope), 'Quarter calculated.')}>
                  {busy ? 'Working…' : 'Calculate'}
                </Btn>
              )}
            </div>
          </div>

          {records.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr className="text-left text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    <th className="py-1.5 pr-2">Employee</th>
                    <th className="py-1.5 pr-2">IRM</th>
                    <th className="py-1.5 pr-2">Eligible</th>
                    <th className="py-1.5 pr-2">Payable</th>
                    <th className="py-1.5">Held</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => (
                    <tr key={r.employee_code} className="border-t border-[var(--border)]">
                      <td className="py-1.5 pr-2 font-semibold text-[var(--text-main)]">
                        {r.employee_name || r.employee_code}
                      </td>
                      <td className="py-1.5 pr-2">{r.irm_score}%</td>
                      <td className="py-1.5 pr-2">
                        {r.eligible == null ? '—' : (
                          <Chip tone={r.eligible ? 'good' : 'bad'}>{r.eligible ? 'Yes' : 'No'}</Chip>
                        )}
                        {r.ineligible_reason && (
                          <span className="block text-[10px] text-[var(--text-muted)]">{r.ineligible_reason}</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-2">{money(r.payable_portion)}</td>
                      <td className="py-1.5">{money(r.held_portion)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!records.length && (
            <p className="text-[12px] text-[var(--text-muted)]">No scores entered yet.</p>
          )}

          {can(CAP.VARIABLE_PAY_APPROVE) && info.status === 'Calculated' && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Decision</p>
              <textarea rows={2} value={decisionRemarks} className={TEXTAREA} placeholder="Remarks"
                onChange={(e) => setDecisionRemarks(e.target.value)} />
              <Btn tone="primary" disabled={busy} onClick={() => run(
                () => decideVariablePayQuarter(quarter,
                  { approved: true, remarks: decisionRemarks.trim() || undefined }, scope),
                'Quarter approved.')}>
                {busy ? 'Working…' : 'Approve Batch'}
              </Btn>
            </div>
          )}
        </div>
      )}
      {addingRecord && (
        <AddScoreModal quarter={quarter} scope={scope} onClose={() => setAddingRecord(false)}
          onDone={() => { setAddingRecord(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </Modal>
  );
};

const AddScoreModal = ({ quarter, scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [irmScore, setIrmScore] = useState('');
  const [targetAmount, setTargetAmount] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !irmScore || !targetAmount) {
      showError('Select the employee and enter both figures.');
      return;
    }
    run(() => saveVariablePayRecord(quarter, {
      employee_code: employee.employee_code, irm_score: Number(irmScore),
      quarterly_target_amount: Number(targetAmount),
    }, scope), 'Score saved.');
  };

  return (
    <Modal title="Add IRM Score" labelledBy="vp-score-title"
      subtitle="Entered by hand — this module does not yet import from the separate IRM tool."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Save'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="vp-irm">IRM Score (%)</label>
        <input id="vp-irm" type="number" value={irmScore} className={FIELD}
          onChange={(e) => setIrmScore(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="vp-target">Quarterly Target Amount</label>
        <input id="vp-target" type="number" value={targetAmount} className={FIELD}
          onChange={(e) => setTargetAmount(e.target.value)} />
      </div>
    </Modal>
  );
};

const VariablePayPolicyModal = ({ policy, scope, onClose, onDone, showSuccess, showError }) => {
  const [ormThreshold, setOrmThreshold] = useState(policy?.orm_threshold ?? 80);
  const [irmThreshold, setIrmThreshold] = useState(policy?.irm_threshold ?? 70);
  const [payablePercent, setPayablePercent] = useState(policy?.payable_percent ?? 75);
  const [heldPercent, setHeldPercent] = useState(policy?.held_percent ?? 25);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => run(() => saveVariablePayPolicy({
    orm_threshold: Number(ormThreshold), irm_threshold: Number(irmThreshold),
    payable_percent: Number(payablePercent), held_percent: Number(heldPercent),
  }, scope), 'Variable pay policy saved.');

  return (
    <Modal title="Variable Pay Policy" labelledBy="vp-policy-title"
      subtitle="§7.15 — adjustable defaults, not a frozen rule." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="vp-orm-threshold">ORM Threshold (%)</label>
          <input id="vp-orm-threshold" type="number" value={ormThreshold} className={FIELD}
            onChange={(e) => setOrmThreshold(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="vp-irm-threshold">IRM Threshold (%)</label>
          <input id="vp-irm-threshold" type="number" value={irmThreshold} className={FIELD}
            onChange={(e) => setIrmThreshold(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="vp-payable">Payable %</label>
          <input id="vp-payable" type="number" value={payablePercent} className={FIELD}
            onChange={(e) => setPayablePercent(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="vp-held">Held %</label>
          <input id="vp-held" type="number" value={heldPercent} className={FIELD}
            onChange={(e) => setHeldPercent(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

// ── Payslip Template tab (SM-HR-064) ──
const PayslipTemplateTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [companyName, setCompanyName] = useState('');
  const [headerNote, setHeaderNote] = useState('');
  const [footerNote, setFooterNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const canWrite = can(CAP.PAYROLL_PROCESS);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getPayslipTemplate(scope);
      setCompanyName(data?.company_name || '');
      setHeaderNote(data?.header_note || '');
      setFooterNote(data?.footer_note || '');
    } catch {
      // A never-configured template is a 200 with nulls, not an error — nothing to show here.
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await savePayslipTemplate({
        company_name: companyName.trim() || undefined,
        header_note: headerNote.trim() || undefined,
        footer_note: footerNote.trim() || undefined,
      }, scope);
      showSuccess('Payslip template saved.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the template.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading the payslip template…" />;

  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-[12.5px] text-[var(--text-muted)]">
        Full statutory/component layout waits on a payroll workshop (§7.13). What every
        issued payslip can carry today is a header and footer note.
      </p>
      <div>
        <label className={LABEL} htmlFor="pt-name">Company name on payslip</label>
        <input id="pt-name" value={companyName} className={FIELD} disabled={!canWrite}
          onChange={(e) => setCompanyName(e.target.value)} placeholder="Sparsh Magic LLP" />
      </div>
      <div>
        <label className={LABEL} htmlFor="pt-header">Header note</label>
        <textarea id="pt-header" rows={2} value={headerNote} className={TEXTAREA} disabled={!canWrite}
          onChange={(e) => setHeaderNote(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="pt-footer">Footer note</label>
        <textarea id="pt-footer" rows={2} value={footerNote} className={TEXTAREA} disabled={!canWrite}
          onChange={(e) => setFooterNote(e.target.value)}
          placeholder="This is a system-generated payslip and does not require a signature." />
      </div>
      {canWrite && (
        <Btn tone="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Btn>
      )}
    </div>
  );
};

export default PayrollBoard;
