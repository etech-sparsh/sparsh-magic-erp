import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';

// Reusable donut + legend card for the dashboard's summary breakdowns (Overdue/Pending/
// In-Progress, Completed/Not Completed, In-Time/Delayed). `slices` is [{ label, value, color }].
// Percentages are computed off the panel's own total so each donut reads as a self-contained
// 100%, matching the reference design's "Label - value (pct%)" legend rows.
const TaskDonutPanel = ({ title, slices }) => {
  const total = useMemo(() => slices.reduce((sum, s) => sum + (s.value || 0), 0), [slices]);
  const pct = (v) => (total > 0 ? Math.round((v / total) * 100) : 0);
  const data = slices.filter(s => s.value > 0);

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6">
      <h3 className="text-[13px] font-black text-[var(--text-main)] mb-4">{title}</h3>

      <div className="flex items-center gap-4">
        <div className="w-[130px] h-[130px] shrink-0">
          {total === 0 ? (
            <div className="w-full h-full rounded-full border-[10px] border-[var(--input-bg)]" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data} dataKey="value" nameKey="label" innerRadius={42} outerRadius={62}
                  paddingAngle={2} stroke="none" startAngle={90} endAngle={-270}>
                  {data.map(s => <Cell key={s.label} fill={s.color} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          {slices.map(s => (
            <div key={s.label} className="flex items-center gap-2 text-[12px] font-bold text-[var(--text-main)]">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: s.color }} />
              <span className="truncate">{s.label} - {s.value} ({pct(s.value)}%)</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default TaskDonutPanel;
