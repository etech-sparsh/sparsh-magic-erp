import React, { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

// Fixed 4-bucket legend for the stacked "X Wise" report panels (Bar Chart view of the
// dashboard). This is a simplified view distinct from the 7-state STATUS_CONFIG used
// elsewhere (badges/cards) — every task falls into exactly one of these four buckets
// (see bucketOf() in TaskDashboard.jsx) so the stacked segments never double-count.
// eslint-disable-next-line react-refresh/only-export-components
export const REPORT_LEGEND = [
  { key: 'pending', label: 'Pending', color: 'var(--accent-orange)' },
  { key: 'overdue', label: 'Overdue', color: 'var(--accent-red)' },
  { key: 'inProgress', label: 'In Progress', color: 'var(--accent-yellow)' },
  { key: 'completed', label: 'Completed', color: 'var(--accent-green)' },
];

const PAGE_SIZE = 6;

const truncate = (str, n) => (str && str.length > n ? `${str.slice(0, n - 1)}…` : str);

const StackedReportPanel = ({ title, axisLabel, rows }) => {
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = useMemo(() => rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE), [rows, page]);

  // When rows carry a `sub` (e.g. an employee's designation) draw a two-line tick — bold
  // name over a small role subtitle — matching the reference bar design. Look the subtitle
  // up by label since recharts only hands the tick renderer the axis value.
  const hasSub = pageRows.some(r => r.sub);
  const subByLabel = useMemo(() => Object.fromEntries(pageRows.map(r => [r.label, r.sub])), [pageRows]);
  const renderTwoLineTick = ({ x, y, payload }) => (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={11} textAnchor="middle" fontSize={9} fontWeight={800} fill="var(--text-main)">
        {truncate(payload.value, 14)}
      </text>
      {subByLabel[payload.value] ? (
        <text x={0} y={0} dy={23} textAnchor="middle" fontSize={8} fill="var(--accent-indigo)">
          {truncate(subByLabel[payload.value], 16)}
        </text>
      ) : null}
    </g>
  );

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h3 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">{title}</h3>
        <div className="flex items-center gap-3 flex-wrap">
          {REPORT_LEGEND.map(l => (
            <span key={l.key} className="flex items-center gap-1.5 text-[10px] font-bold text-[var(--text-muted)]">
              <span className="w-2 h-2 rounded-full" style={{ background: l.color }} /> {l.label}
            </span>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="h-[220px] flex items-center justify-center text-[11px] font-bold text-[var(--text-muted)]">No data</div>
      ) : (
        <div className="h-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={pageRows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="45%">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" interval={0} height={hasSub ? 40 : 20}
                tick={hasSub ? renderTwoLineTick : { fontSize: 9, fill: 'var(--text-muted)' }} />
              <YAxis tick={{ fontSize: 9, fill: 'var(--text-muted)' }} allowDecimals={false} />
              <Tooltip />
              {REPORT_LEGEND.map((l, i) => (
                <Bar key={l.key} dataKey={l.key} stackId="a" fill={l.color} maxBarSize={28} radius={i === REPORT_LEGEND.length - 1 ? [4, 4, 0, 0] : undefined} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className="text-center text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest mt-2">{axisLabel}</p>

      {rows.length > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 mt-2">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="p-1 rounded-lg text-[var(--text-muted)] disabled:opacity-30 hover:bg-[var(--input-bg)]">
            <ChevronLeft size={16} />
          </button>
          <span className="text-[10px] font-black text-[var(--text-muted)]">{page + 1} of {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
            className="p-1 rounded-lg text-[var(--text-muted)] disabled:opacity-30 hover:bg-[var(--input-bg)]">
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
};

export default StackedReportPanel;
