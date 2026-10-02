import React from 'react';
import { motion } from 'framer-motion';

// Icon-tile + uppercase-label + big colored number card, matching the reference design.
// `cardOrder` is an array of [responseKey, config] pairs from statusConfig.js — each config
// already carries the icon/color/bg/border set, so the tile tints itself from the same tokens
// the status pills use and the two stay in sync.
const StatusSummaryCards = ({ cardOrder, summary, activeKey, onSelect, columnsClass }) => (
  <div className={columnsClass || 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9 gap-3'}>
    {cardOrder.map(([key, cfg]) => {
      const isActive = activeKey === key;
      const selectable = !!onSelect;
      const Wrapper = selectable ? motion.button : motion.div;
      const Icon = cfg.icon;
      const value = summary ? (summary[key] ?? 0) : '—';
      return (
        <Wrapper
          key={key}
          type={selectable ? 'button' : undefined}
          onClick={selectable ? () => onSelect(isActive ? null : key) : undefined}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className={`text-left bg-[var(--bg-card)] px-3.5 py-3 rounded-2xl border transition-all ${selectable ? 'hover:shadow-md hover:-translate-y-0.5 cursor-pointer' : ''}`}
          style={{
            borderColor: isActive ? cfg.color : 'var(--border)',
            borderWidth: isActive ? 2 : 1,
            background: isActive ? cfg.bg : 'var(--bg-card)',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
              style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}>
              {Icon ? <Icon size={13} /> : <span className="w-2 h-2 rounded-full" style={{ background: cfg.color }} />}
            </span>
            <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">
              {cfg.shortLabel || cfg.label}
            </span>
          </div>
          <p className="text-[26px] leading-none font-black" style={{ color: cfg.color }}>{value}</p>
        </Wrapper>
      );
    })}
  </div>
);

export default StatusSummaryCards;
