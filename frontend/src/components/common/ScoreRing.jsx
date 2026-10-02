import React from 'react';

// Circular percentage indicator: shows a score percentage inside a colored circular
// border. Colour bands follow the completion convention — red at 0%, orange for any
// partial progress (1–99%), green at a full 100%. Purely presentational: it renders
// whatever percentage it is handed and computes nothing about the underlying data.
const bandColor = (v) => {
  if (v >= 100) return 'var(--accent-green)';
  if (v >= 1) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const ScoreRing = ({ value = 0, size = 42, stroke = 3, decimals = 1, title }) => {
  const pct = Math.max(0, Math.min(100, parseFloat(value) || 0));
  const color = bandColor(pct);
  const r = (size - stroke) / 2;
  const label = `${pct.toFixed(decimals)}%`;
  const font = Math.round(size * 0.22);

  return (
    <span
      className="inline-flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
      title={title ?? label}
      role="img"
      aria-label={`Score ${label}`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="block">
        {/* Colored circular border — solid, encodes the band (red / orange / green) */}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} />
        <text
          x="50%"
          y="50%"
          dominantBaseline="central"
          textAnchor="middle"
          fontSize={font}
          fontWeight={900}
          fill={color}
        >
          {label}
        </text>
      </svg>
    </span>
  );
};

export default ScoreRing;
