import React from 'react';
import { SelectField } from '../common/StyledSelect';

// Matches the `period` values accepted by GET /api/tasks/dashboard (backend/app/routes/tasks.py::_period_to_range)
// eslint-disable-next-line react-refresh/only-export-components
export const PERIODS = [
  { key: 'today', label: 'Today' },
  { key: 'yesterday', label: 'Yesterday' },
  { key: 'this_week', label: 'This Week' },
  { key: 'last_week', label: 'Last Week' },
  { key: 'this_month', label: 'This Month' },
  { key: 'last_month', label: 'Last Month' },
  { key: 'this_year', label: 'This Year' },
  { key: 'all_time', label: 'All Time' },
  { key: 'custom', label: 'Custom' },
];

const DateRangeFilter = ({ period, onPeriodChange, startDate, endDate, onCustomChange, variant = 'buttons' }) => {
  if (variant === 'dropdown') {
    return (
      <div className="flex items-center gap-2">
        <SelectField value={period} onChange={onPeriodChange} searchable={false}
          options={PERIODS.map(p => ({ id: p.key, name: p.label }))} />
        {period === 'custom' && (
          <>
            <input type="date" value={startDate} onChange={e => onCustomChange('startDate', e.target.value)}
              className="px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
            <input type="date" value={endDate} onChange={e => onCustomChange('endDate', e.target.value)}
              className="px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
          </>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {PERIODS.map(p => (
          <button key={p.key} onClick={() => onPeriodChange(p.key)}
            className={`px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all border ${
              period === p.key
                ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-sm'
                : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)]'
            }`}>
            {p.label}
          </button>
        ))}
      </div>
      {period === 'custom' && (
        <div className="flex items-center gap-3">
          <input type="date" value={startDate} onChange={e => onCustomChange('startDate', e.target.value)}
            className="px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
          <span className="text-[var(--text-muted)] text-[11px] font-black">to</span>
          <input type="date" value={endDate} onChange={e => onCustomChange('endDate', e.target.value)}
            className="px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
        </div>
      )}
    </div>
  );
};

export default DateRangeFilter;
