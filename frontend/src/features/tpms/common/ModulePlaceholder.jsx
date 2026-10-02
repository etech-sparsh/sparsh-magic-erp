import React from 'react';
import { Construction } from 'lucide-react';

/**
 * Temporary stand-in for TPMS sub-modules that are not built yet.
 * Swap each route's element for the real component as we build them step by step.
 */
const ModulePlaceholder = ({ title = 'Module', subtitle }) => (
  <div className="space-y-6">
    <div>
      <h2 className="text-[20px] font-extrabold tracking-tight">{title}</h2>
      {subtitle && <p className="text-[13px] text-[var(--text-muted)] mt-1">{subtitle}</p>}
    </div>

    <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--bg-card)] px-6 py-16 flex flex-col items-center justify-center text-center">
      <div className="w-14 h-14 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center mb-4">
        <Construction size={26} />
      </div>
      <p className="text-[14px] font-bold">“{title}” UI coming up next</p>
      <p className="text-[12px] text-[var(--text-muted)] mt-1 max-w-sm">
        This is where the {title} view will render. We'll design it in the next step.
      </p>
    </div>
  </div>
);

export default ModulePlaceholder;
