import React from 'react';
import { Loader2, AlertCircle, Inbox } from 'lucide-react';

/**
 * HRMS ▸ shared loading / empty / error states.
 *
 * Defined once so every HRMS screen shows the same three states in the same way. The
 * source HRMS hand-rolled these per page and drifted (FRONTEND_ANALYSIS §13 lists three
 * different empty-state treatments); one component set prevents that.
 */

export const HrmsLoading = ({ label = 'Loading…' }) => (
  <div className="py-16 flex flex-col items-center justify-center gap-3 text-[var(--text-muted)]">
    <Loader2 size={22} className="animate-spin" />
    <p className="text-[13px] font-medium">{label}</p>
  </div>
);

export const HrmsError = ({ message = 'Something went wrong.', onRetry }) => (
  <div className="py-12 px-5 rounded-xl border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)] flex flex-col items-center gap-3 text-center">
    <AlertCircle size={22} className="text-[var(--accent-red)]" />
    <p className="text-[13px] font-semibold text-[var(--accent-red)] max-w-md">{message}</p>
    {onRetry && (
      <button
        type="button"
        onClick={onRetry}
        className="h-8 px-3.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
      >
        Try again
      </button>
    )}
  </div>
);

export const HrmsEmpty = ({ icon: Icon = Inbox, title = 'Nothing here yet', hint, action }) => (
  <div className="py-16 flex flex-col items-center justify-center gap-3 text-center">
    <div className="h-11 w-11 rounded-xl bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center">
      <Icon size={20} />
    </div>
    <div>
      <p className="text-[13.5px] font-bold text-[var(--text-main)]">{title}</p>
      {hint && <p className="text-[12px] text-[var(--text-muted)] mt-1 max-w-sm">{hint}</p>}
    </div>
    {action}
  </div>
);
