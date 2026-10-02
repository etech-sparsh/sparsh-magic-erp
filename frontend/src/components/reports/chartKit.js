// Shared chart helpers for the Report module (layout/rendering only — no data logic).

// Truncate long axis labels with an ellipsis so they never clip; the chart Tooltip
// still shows the full value on hover.
export const truncate = (v, n = 14) =>
  (typeof v === 'string' && v.length > n ? `${v.slice(0, n - 1)}…` : v);

// Consistent themed tooltip used by every chart.
export const CHART_TOOLTIP = {
  borderRadius: '16px',
  border: '1px solid var(--border)',
  background: 'var(--bg-card)',
  boxShadow: '0 20px 50px rgba(0,0,0,0.12)',
  padding: '10px 16px',
};

// Legend spacing that keeps it clear of the plot area and wraps on small widths.
export const LEGEND_STYLE = {
  fontSize: '10px',
  fontWeight: 900,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  paddingTop: '8px',
  lineHeight: '1.6',
};

// Responsive grids used across the Report dashboards:
//  - THREE: 1 (mobile) → 2 (tablet, md) → 3 (desktop, xl)
//  - TWO:   1 (mobile) → 2 (tablet+, md)
export const GRID_THREE = 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5';
export const GRID_TWO = 'grid grid-cols-1 md:grid-cols-2 gap-5';
// A wide/feature chart spans the full row on tablet and 2/3 on desktop.
export const SPAN_WIDE = 'md:col-span-2 xl:col-span-2';
