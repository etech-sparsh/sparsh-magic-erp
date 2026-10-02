import React from 'react';

/**
 * HRMS ▸ shared page header.
 *
 * Every HRMS screen from Phase 2 onward uses this, so the module reads as one surface and
 * a spacing/typography change lands in one place. Styled entirely with the ERP's CSS
 * variables (--text-main, --text-muted, --border …) so it inherits light/dark theming
 * rather than carrying its own palette.
 */
const HrmsPageHeader = ({ icon: Icon, title, subtitle, actions }) => (
  <div className="flex items-start justify-between flex-wrap gap-4 pb-5 border-b border-[var(--border)]">
    <div className="flex items-center gap-3.5">
      {Icon && (
        <div className="h-10 w-10 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0">
          <Icon size={19} />
        </div>
      )}
      <div className="min-w-0">
        <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight truncate">
          {title}
        </h1>
        {subtitle && (
          <p className="text-[12px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>
        )}
      </div>
    </div>
    {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
  </div>
);

export default HrmsPageHeader;
