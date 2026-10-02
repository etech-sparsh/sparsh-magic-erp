import React, { useCallback, useEffect, useState } from 'react';
import { Wallet, Printer } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getPayslip } from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';

/**
 * HRMS ▸ the employee payslip (§22.7, SM-HR-031).
 *
 * Reads hrms_payslip_service.get_payslip — every figure is the payroll run's own, this
 * component only lays it out. Printed via the browser (Print / Save as PDF), the same
 * pattern Offer/Appointment letters already use — see hrms_payslip_service.py's docstring
 * for why there is no server-side PDF generation here.
 *
 * `embedded`: true when mounted inside PayrollBoard's "My Payslip" tab (which already has
 * its own page header/scope bar); false when routed on its own.
 *
 * `employeeCode`: set when HR opens a SPECIFIC employee's payslip (e.g. from the Payroll
 * Runs records table) rather than the caller's own — the backend already accepts this for
 * any role but EMPLOYEE (see hrms_payslip_service._resolve_employee_code, which ignores it
 * for a self-service caller and resolves their own code instead regardless).
 */
const money = (n) => (typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '—');

const currentPeriod = () => new Date().toISOString().slice(0, 7);

const Payslip = ({ embedded = false, employeeCode = null, initialPeriod = null }) => {
  const { scope } = useHrms();
  const [period, setPeriod] = useState(initialPeriod || currentPeriod());
  const [slip, setSlip] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getPayslip(
        period, employeeCode ? { ...scope, employee_code: employeeCode } : scope);
      setSlip(data);
    } catch (err) {
      setSlip(null);
      setError(err?.response?.data?.detail || 'No payslip is available for this period.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, scope.company_id, employeeCode]);

  useEffect(() => { load(); }, [load]);

  const body = (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <label className={LABEL} htmlFor="payslip-period">Period</label>
          <input id="payslip-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
            onChange={(e) => setPeriod(e.target.value)} />
        </div>
        {slip && (
          <button type="button" onClick={() => window.print()}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
            <Printer size={14} /> Print / Save as PDF
          </button>
        )}
      </div>

      {loading && <HrmsLoading label="Loading payslip…" />}
      {!loading && error && <HrmsEmpty icon={Wallet} title="No payslip for this period" hint={error} />}
      {!loading && !error && slip && <PayslipDocument slip={slip} />}
    </div>
  );

  if (embedded) return body;

  return (
    <div className="space-y-6">
      <HrmsPageHeader icon={Wallet} title="My Payslip"
        subtitle="Your itemised earnings and deductions for a payroll period." />
      {body}
    </div>
  );
};

export const PayslipDocument = ({ slip }) => (
  <div className="bg-white text-slate-900 mx-auto rounded-xl overflow-hidden border border-slate-200"
    style={{ maxWidth: 720, printColorAdjust: 'exact', WebkitPrintColorAdjust: 'exact' }}>
    <div className="p-8" style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}>
      <div style={{ height: 4, background: '#0f172a', marginBottom: 20 }} />
      <div className="flex items-start justify-between mb-6">
        <div>
          <p className="text-[17px] font-bold">{slip.template?.company_name || 'Sparsh Magic LLP'}</p>
          <p className="text-[11.5px] text-slate-500 mt-0.5">Payslip for {slip.period}</p>
          {slip.template?.header_note && (
            <p className="text-[11px] text-slate-500 mt-1">{slip.template.header_note}</p>
          )}
        </div>
        {slip.run_status && (
          <span className="text-[10.5px] font-bold uppercase tracking-wide px-2 py-1 rounded"
            style={{ background: slip.run_status === 'Locked' ? '#dcfce7' : '#fef3c7',
                     color: slip.run_status === 'Locked' ? '#166534' : '#92400e' }}>
            {slip.run_status === 'Locked' ? 'Final' : 'Provisional'}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 text-[12.5px] mb-6 pb-6 border-b border-slate-200">
        <div><span className="text-slate-500">Employee</span><br />
          <span className="font-semibold">{slip.employee_name} ({slip.employee_code})</span></div>
        <div><span className="text-slate-500">Designation</span><br />
          <span className="font-semibold">{slip.designation || '—'}</span></div>
        <div><span className="text-slate-500">Department</span><br />
          <span className="font-semibold">{slip.department || '—'}</span></div>
        <div><span className="text-slate-500">Payable days</span><br />
          <span className="font-semibold">{slip.payable_days} / {slip.days_in_period}</span></div>
      </div>
      {slip.proration_note && (
        <p className="text-[11px] text-amber-700 mb-4 -mt-3">{slip.proration_note}</p>
      )}

      <div className="grid grid-cols-2 gap-8">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-2">Earnings</p>
          {[...slip.earnings, ...slip.other_earnings].map((r) => (
            <div key={r.label} className="flex justify-between text-[12.5px] py-1">
              <span>{r.label}</span><span>{money(r.amount)}</span>
            </div>
          ))}
          {!slip.earnings.length && !slip.other_earnings.length && (
            <p className="text-[12px] text-slate-400">No earnings on file.</p>
          )}
          <div className="flex justify-between text-[12.5px] font-bold pt-2 mt-2 border-t border-slate-200">
            <span>Gross Earnings</span><span>{money(slip.gross_earnings)}</span>
          </div>
        </div>
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-2">Deductions</p>
          {slip.deductions.map((r) => (
            <div key={r.label} className="flex justify-between text-[12.5px] py-1">
              <span>{r.label}</span><span>{money(r.amount)}</span>
            </div>
          ))}
          {!slip.deductions.length && (
            <p className="text-[12px] text-slate-400">No deductions on file.</p>
          )}
          <div className="flex justify-between text-[12.5px] font-bold pt-2 mt-2 border-t border-slate-200">
            <span>Total Deductions</span><span>{money(slip.total_deductions)}</span>
          </div>
        </div>
      </div>

      <div className="mt-6 pt-4 border-t-2 border-slate-800 flex justify-between items-center">
        <span className="text-[14px] font-bold">Net Pay</span>
        <span className="text-[18px] font-bold">{money(slip.net_pay)}</span>
      </div>

      <p className="mt-8 text-[10.5px] text-slate-400">
        {slip.template?.footer_note || 'This is a system-generated payslip.'}
      </p>
    </div>
  </div>
);

export default Payslip;
