import React, { useState } from 'react';
import { X, CheckCircle2, XCircle, AlertTriangle, Gauge } from 'lucide-react';

/**
 * HRMS ▸ approval dialog.
 *
 * Shared by both stages of the requisition chain, and reused by assessments, interviews and
 * offers in later phases — which is why the copy, the capability and the action strings are
 * all props rather than baked in.
 *
 * A remark is mandatory to reject and optional to approve: a rejection that does not say why
 * is not actionable by the person who has to fix it. The server enforces the same rule, so
 * this is an affordance, not the control.
 */
const ApprovalDialog = ({
  title,
  subtitle,
  approveLabel = 'Approve',
  rejectLabel = 'Reject',
  showSalary = false,
  salaryLabel = 'Revised CTC (optional)',
  salaryDefault = '',
  busy = false,
  // ── Phase 11-R ── the requisition being decided, so the approver sees the figures the
  // decision rests on WITHOUT leaving the dialog. Optional, because this component is also
  // reused by assessments, interviews and offers, which have no such context.
  requisition = null,
  // Item 6: a mismatched budget makes remarks mandatory on APPROVAL too. Passed in rather
  // than re-derived here, so the dialog and the server read the same rule.
  requireRemarksToApprove = false,
  // ── Internal track ── the budget gate collects the approved headcount and salary band.
  // The band is what every later offer on this requisition is validated against, so the
  // server refuses an approval without it; asking here avoids a round trip to be told so.
  showBudgetBand = false,
  onApprove,
  onReject,
  onClose,
}) => {
  const [remarks, setRemarks] = useState('');
  const [salary, setSalary] = useState(salaryDefault ?? '');
  const [headcount, setHeadcount] = useState(requisition?.vacancy ?? 1);
  const [bandMin, setBandMin] = useState('');
  const [bandMax, setBandMax] = useState('');
  const [error, setError] = useState('');

  const snapshot = requisition?.sanction_snapshot;
  const budgetStatus = requisition?.budget_status;
  const budgetDelta = requisition?.budget_delta;
  const chain = requisition?.escalation_chain || [];
  const level = requisition?.escalation_level || 0;

  const reject = () => {
    if (!remarks.trim()) {
      setError('A reason is required when rejecting.');
      return;
    }
    onReject(remarks.trim());
  };

  const approve = () => {
    // Mirrors the server's REQ_CONDITIONAL_REMARKS rule, so the approver is told before a
    // round trip rather than after a 422. The server still enforces it.
    if (requireRemarksToApprove && !remarks.trim()) {
      setError('The budgets do not match. Record a remark explaining the approval.');
      return;
    }
    if (showBudgetBand) {
      const min = Number(bandMin);
      const max = Number(bandMax);
      if (bandMin === '' || bandMax === '' || Number.isNaN(min) || Number.isNaN(max)) {
        setError('Record the salary band. Every offer on this requisition is checked '
          + 'against it.');
        return;
      }
      if (min > max) {
        setError('The minimum of the band cannot exceed its maximum.');
        return;
      }
      if (!Number(headcount) || Number(headcount) < 1) {
        setError('Approved headcount must be at least 1.');
        return;
      }
      onApprove(remarks.trim(), null, {
        approved_headcount: Number(headcount),
        approved_salary_band_min: min,
        approved_salary_band_max: max,
      });
      return;
    }
    onApprove(remarks.trim(), salary === '' ? null : Number(salary));
  };

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-3">
          {/* ── Phase 11-R, Item 7 — the sanction snapshot the decision rests on ──
              The STORED snapshot, not a fresh reading: the approver must see the figures
              the requisition was evaluated against, and re-deriving them here would show a
              different world from the one the routing decision was made in. */}
          {snapshot && (
            <div className={`rounded-lg border px-3.5 py-3 ${
              snapshot.is_over_sanction
                ? 'border-[var(--accent-amber,var(--accent-red))] bg-[var(--accent-amber-bg,var(--accent-red-bg))]'
                : 'border-[var(--border)] bg-[var(--input-bg)]'
            }`}>
              <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <Gauge size={12} /> Sanctioned strength
              </p>
              <div className="flex flex-wrap gap-x-5 gap-y-1 mt-1.5 text-[12.5px] text-[var(--text-muted)]">
                <span>Sanctioned: <b className="text-[var(--text-main)]">
                  {snapshot.sanctioned ?? 'not set'}</b></span>
                <span>Filled: <b className="text-[var(--text-main)]">{snapshot.actual}</b></span>
                <span>Committed: <b className="text-[var(--text-main)]">
                  {snapshot.open_requisitions}</b></span>
                <span>This request: <b className="text-[var(--text-main)]">
                  {snapshot.requested}</b></span>
              </div>
              {snapshot.is_over_sanction && (
                <p className="flex items-start gap-1.5 mt-2 text-[12px] font-semibold text-[var(--accent-amber,var(--accent-red))]">
                  <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                  Over sanctioned strength. MD approval remains mandatory whatever the
                  escalation chain decides.
                </p>
              )}
            </div>
          )}

          {/* Where this requisition sits in the escalation ladder, if it is in one. */}
          {chain.length > 0 && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                Escalation chain
              </p>
              <ol className="mt-2 space-y-1.5">
                {chain.map((step) => (
                  <li key={step.level} className="flex items-center gap-2 text-[12.5px]">
                    <span className={`h-4 w-4 rounded-full grid place-items-center text-[9px] font-bold ${
                      step.status === 'Approved'
                        ? 'bg-[var(--accent-green,var(--accent-indigo))] text-white'
                        : step.status === 'Rejected'
                          ? 'bg-[var(--accent-red)] text-white'
                          : step.level === level
                            ? 'bg-[var(--accent-indigo)] text-white'
                            : 'bg-[var(--border)] text-[var(--text-muted)]'
                    }`}>
                      {step.level}
                    </span>
                    <span className="text-[var(--text-main)]">{step.name}</span>
                    <span className="text-[var(--text-muted)] ml-auto">{step.status}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* ── Phase 11-R, Item 6 — sanctioned vs approved, side by side ── */}
          {budgetStatus && budgetStatus !== 'Not Set' && (
            <div className={`rounded-lg border px-3.5 py-3 ${
              budgetStatus === 'Mismatch'
                ? 'border-[var(--accent-red)] bg-[var(--accent-red-bg)]'
                : 'border-[var(--border)] bg-[var(--input-bg)]'
            }`}>
              <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                Budget — {budgetStatus}
              </p>
              <div className="flex flex-wrap gap-x-5 gap-y-1 mt-1.5 text-[12.5px] text-[var(--text-muted)]">
                <span>Management sanctioned: <b className="text-[var(--text-main)]">
                  {requisition?.budget_sanctioned_amount ?? '—'}</b></span>
                <span>HOD approved: <b className="text-[var(--text-main)]">
                  {requisition?.budget_hod_amount ?? '—'}</b></span>
                {budgetDelta != null && budgetDelta !== 0 && (
                  <span className="text-[var(--accent-red)] font-bold">
                    Difference: {budgetDelta > 0 ? '+' : ''}
                    {Number(budgetDelta).toLocaleString('en-IN')}
                  </span>
                )}
              </div>
              {budgetStatus === 'Mismatch' && (
                <p className="mt-2 text-[12px] font-semibold text-[var(--accent-red)]">
                  A mismatch does not block approval, but a remark is required.
                </p>
              )}
            </div>
          )}

          {/* ── Internal track ── the mandatory budget gate.
              Headcount and band are collected together because they are one decision: how
              many seats, at what cost. The band is stored on the requisition and every
              later offer is validated against it, which is why it cannot be skipped. */}
          {showBudgetBand && (
            <fieldset className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
              <legend className="px-1 text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                Approved headcount &amp; salary band
              </legend>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mt-1">
                <div>
                  <label htmlFor="ap-headcount" className="block text-[11px] text-[var(--text-muted)] mb-1">
                    Headcount
                  </label>
                  <input
                    id="ap-headcount" type="number" min="1" value={headcount}
                    onChange={(e) => { setHeadcount(e.target.value); setError(''); }}
                    className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)]"
                  />
                </div>
                <div>
                  <label htmlFor="ap-band-min" className="block text-[11px] text-[var(--text-muted)] mb-1">
                    Band minimum
                  </label>
                  <input
                    id="ap-band-min" type="number" min="0" value={bandMin}
                    onChange={(e) => { setBandMin(e.target.value); setError(''); }}
                    className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)]"
                  />
                </div>
                <div>
                  <label htmlFor="ap-band-max" className="block text-[11px] text-[var(--text-muted)] mb-1">
                    Band maximum
                  </label>
                  <input
                    id="ap-band-max" type="number" min="0" value={bandMax}
                    onChange={(e) => { setBandMax(e.target.value); setError(''); }}
                    className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)]"
                  />
                </div>
              </div>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                No internal role may be sourced until this is approved, and every offer is
                checked against the band.
              </p>
            </fieldset>
          )}

          {showSalary && (
            <div>
              <label htmlFor="ap-salary" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
                {salaryLabel}
              </label>
              <input
                id="ap-salary" type="number" min="0" value={salary}
                onChange={(e) => setSalary(e.target.value)}
                className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
              />
            </div>
          )}

          <div>
            <label htmlFor="ap-remarks" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
              Remarks
            </label>
            <textarea
              id="ap-remarks" rows={3} value={remarks}
              onChange={(e) => { setRemarks(e.target.value); setError(''); }}
              placeholder="Add a note — required if you reject…"
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none"
            />
            {error && <p className="mt-1 text-[11.5px] font-semibold text-[var(--accent-red)]">{error}</p>}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={busy}
            className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
            Cancel
          </button>
          <button type="button" onClick={reject} disabled={busy}
            className="h-9 px-4 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
            <XCircle size={14} /> {rejectLabel}
          </button>
          <button type="button" onClick={approve} disabled={busy}
            className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
            <CheckCircle2 size={14} /> {busy ? 'Working…' : approveLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ApprovalDialog;
