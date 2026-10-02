import React from 'react';

import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { motion } from 'framer-motion';

import { StyledSelect } from '../../../components/common/StyledSelect';

/* Shared entrance transition for cards/sections — subtle fade + rise. */
const RISE = { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.28, ease: [0.4, 0, 0.2, 1] } };

/* ─────────────────────────────────────────────────────────────
   Shared ERP-grade dashboard primitives for the TPMS dashboards.
   Clean cards, icon chips, subtle shadows, refined typography —
   all colours from Sparsh tokens (theme-aware light & dark).
   ───────────────────────────────────────────────────────────── */

/** On-brand hero gradient for dashboard headers (indigo → violet). */
// eslint-disable-next-line react-refresh/only-export-components
export const HEADER_GRADIENT = 'linear-gradient(120deg, #4f46e5 0%, #6d28d9 55%, #7c3aed 100%)';

/** Icon-chip / value tones. */
// eslint-disable-next-line react-refresh/only-export-components
export const TILE = {
  blue:   { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)', bd: 'var(--accent-indigo-border)' },
  green:  { bg: 'var(--accent-green-bg)',  fg: 'var(--accent-green)',  bd: 'var(--accent-green-border)' },
  yellow: { bg: 'var(--accent-yellow-bg)', fg: 'var(--accent-orange)', bd: 'var(--accent-yellow-border)' },
  red:    { bg: 'var(--accent-red-bg)',    fg: 'var(--accent-red)',    bd: 'var(--accent-red-border)' },
  plain:  { bg: 'var(--input-bg)',         fg: 'var(--text-main)',     bd: 'var(--border)' },
};

export const Trend = ({ dir }) => {
  const map = {
    up:   { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', I: TrendingUp,   t: 'Up' },
    down: { c: 'var(--accent-red)',   bg: 'var(--accent-red-bg)',   I: TrendingDown, t: 'Down' },
    flat: { c: 'var(--text-muted)',   bg: 'var(--input-bg)',        I: Minus,        t: 'Flat' },
  }[dir] || {};
  const { c, bg, I, t } = map;
  return (
    <span className="inline-flex items-center gap-1 text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: c, background: bg }}>
      <I size={12} /> {t}
    </span>
  );
};

export const StatusBadge = ({ value }) => {
  const risk = value === 'AT-RISK';
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border"
      style={{
        color: risk ? 'var(--accent-red)' : 'var(--accent-green)',
        background: risk ? 'var(--accent-red-bg)' : 'var(--accent-green-bg)',
        borderColor: risk ? 'var(--accent-red-border)' : 'var(--accent-green-border)',
      }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: risk ? 'var(--accent-red)' : 'var(--accent-green)' }} />
      {value}
    </span>
  );
};

export const Progress = ({ value }) => {
  const c = value >= 75 ? 'var(--accent-green)' : value >= 55 ? 'var(--accent-indigo)' : 'var(--accent-orange)';
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="h-2 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${value}%`, background: c }} />
      </div>
      <span className="text-[11px] font-bold tabular-nums" style={{ color: c }}>{value}%</span>
    </div>
  );
};

// Lifecycle-status → cell colour, matching the Admin grid (AdminView CELL_TONE) so every
// client×activity grid reads the same. A not-yet-due (pending) cell should look neutral, not
// like a failure — which is why colouring by raw done/total ratio is wrong for these grids.
const CELL_STATUS_TONE = {
  done:      { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)' },
  pending:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  overdue:   { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)' },
  cancelled: { c: 'var(--text-muted)',    bg: 'var(--input-bg)' },
};

/** Fraction cell like 1/1 or 0/1 → a compact pill. Pass `status` to colour by lifecycle
 *  status (preferred, consistent with Admin/Client grids); without it, falls back to the
 *  done/total ratio colouring for any legacy caller. */
export const Fraction = ({ v, status }) => {
  if (!v) return <span className="text-[var(--text-muted)]">—</span>;
  const tone = status && CELL_STATUS_TONE[status];
  let c, bg;
  if (tone) {
    ({ c, bg } = tone);
  } else {
    const [a, b] = v.split('/').map(Number);
    const ok = a >= b;
    const zero = a === 0;
    c = zero ? 'var(--accent-red)' : ok ? 'var(--accent-green)' : 'var(--accent-orange)';
    bg = zero ? 'var(--accent-red-bg)' : ok ? 'var(--accent-green-bg)' : 'var(--accent-orange-bg)';
  }
  return (
    <span className="inline-flex items-center justify-center min-w-[34px] text-[11px] font-bold px-1.5 py-0.5 rounded-md tabular-nums" style={{ color: c, background: bg }}>{v}</span>
  );
};

/** ERP KPI stat card — icon chip + value + label + sub, with a tone accent bar. */
export const KpiTile = ({ value, label, sub, tone = 'blue', icon: Icon }) => {
  const t = TILE[tone] || TILE.plain;
  const accent = tone === 'plain' ? 'var(--text-muted)' : t.fg;
  return (
    <motion.div {...RISE} whileHover={{ y: -3 }}
      className="group relative overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4 transition-shadow hover:shadow-md">
      {/* tone accent bar */}
      <span className="absolute inset-x-0 top-0 h-1 opacity-60 group-hover:opacity-100 transition-opacity" style={{ background: accent }} />
      <div className="flex items-start justify-between">
        {Icon && (
          <span className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: t.bg, color: t.fg }}>
            <Icon size={17} />
          </span>
        )}
      </div>
      <p className="text-[26px] font-extrabold tracking-tight leading-none tabular-nums mt-3" style={{ color: t.fg }}>{value}</p>
      <p className="text-[12.5px] font-bold mt-1.5 leading-tight">{label}</p>
      {sub && <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </motion.div>
  );
};

/** ERP section card with a clean header (icon chip + title + optional action). */
export const Section = ({ title, subtitle, icon: Icon, tone = 'navy', action, children }) => {
  const chip = {
    navy:  { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)' },
    red:   { bg: 'var(--accent-red-bg)',    fg: 'var(--accent-red)' },
    green: { bg: 'var(--accent-green-bg)',  fg: 'var(--accent-green)' },
  }[tone] || { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)' };
  return (
    <motion.div {...RISE} className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5 min-w-0">
          {Icon && (
            <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: chip.bg, color: chip.fg }}>
              <Icon size={16} />
            </span>
          )}
          <div className="min-w-0">
            <h3 className="text-[14px] font-extrabold tracking-tight truncate">{title}</h3>
            {subtitle && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5 truncate">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </motion.div>
  );
};

export const Th = ({ children, align, className = '' }) => (
  <th className={`px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} whitespace-nowrap ${className}`}>{children}</th>
);

export const Td = ({ children, align, className = '' }) => (
  <td className={`px-4 py-3.5 text-[12.5px] ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} ${className}`}>{children}</td>
);

/* The dropdown itself lives in components/common/StyledSelect.jsx — Task & Delegation uses
   the same control, so it cannot live inside a TPMS feature folder. HeaderSelect and
   FilterSelect stay here as the TPMS-flavoured pills around it.

   Options accept either plain strings (`['All OMs', 'A. Nair']`) or `{id, name}` objects, so
   a select can submit an id while displaying a label. Mixing is fine — pages backed by the
   API pass objects, static ones keep passing strings. */

/** White pill for the gradient hero header. */
export const HeaderSelect = (props) => (
  <StyledSelect {...props}
    className="min-w-0 max-w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-[var(--bg-card)] text-[var(--text-main)] text-[12.5px] font-bold outline-none border border-[var(--border)] shadow-sm hover:opacity-90 transition-opacity cursor-pointer" />
);

/** Plain pill for in-card filter rows. */
export const FilterSelect = (props) => (
  <StyledSelect {...props}
    className="min-w-0 max-w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[var(--text-main)] text-[12.5px] font-bold outline-none focus:border-[var(--accent-indigo)] cursor-pointer" />
);

/** Reusable table shell so every table shares the same header/zebra/hover styling. */
export const TableShell = ({ minWidth = 900, children }) => (
  <div className="overflow-x-auto no-scrollbar">
    <table className="w-full" style={{ minWidth }}>{children}</table>
  </div>
);

/**
 * Client-side pagination over an already-fetched array. Pure presentation — it
 * only slices the rows the page already holds (no refetch, no backend change).
 * Call it at the TOP of a component (Rules of Hooks), passing the array you would
 * otherwise `.map()` over:
 *
 *   const p = usePaged(rows, 10);
 *   … p.pageRows.map(…) …
 *   <Pager {...p} label="employees" />
 *
 * `page` auto-clamps when the source shrinks (e.g. after a filter), so a stale
 * high page never renders an empty table.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const usePaged = (rows = [], pageSize = 10) => {
  const [page, setPage] = React.useState(1);
  const total = rows.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  React.useEffect(() => { setPage((p) => Math.min(Math.max(1, p), pageCount)); }, [pageCount]);
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  return { page: safePage, setPage, pageCount, total, pageSize, pageRows: rows.slice(start, start + pageSize) };
};

/**
 * Footer pager bar matching the table styling. AUTO-HIDES when everything fits on
 * one page, so it's safe to drop under any table. Spread a usePaged() result in:
 *   <Pager {...p} label="rows" />
 */
export const Pager = ({ page, pageCount, total, pageSize, setPage, label = 'rows' }) => {
  if (!total || total <= pageSize) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const btn = 'px-2.5 py-1.5 rounded-lg text-[12px] font-bold border border-[var(--border)] text-[var(--text-main)] transition-all disabled:opacity-40 disabled:cursor-not-allowed enabled:hover:bg-[var(--input-bg)]';
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-[var(--border)]">
      <span className="text-[12px] font-bold text-[var(--text-muted)] tabular-nums">
        Showing {start}–{end} of {total} {label}
      </span>
      <div className="flex items-center gap-1.5">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => setPage(1)}>«</button>
        <button type="button" className={btn} disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
        <span className="px-2 text-[12px] font-bold text-[var(--text-muted)] tabular-nums">Page {page} / {pageCount}</span>
        <button type="button" className={btn} disabled={page >= pageCount} onClick={() => setPage(page + 1)}>Next</button>
        <button type="button" className={btn} disabled={page >= pageCount} onClick={() => setPage(pageCount)}>»</button>
      </div>
    </div>
  );
};

/** Polished gradient hero header for dashboards. `children` = filter controls. */
export const DashboardHero = ({ icon: Icon, title, highlight, subtitle, children }) => (
  <div className="rounded-2xl px-5 py-4 sm:px-6 sm:py-5 flex flex-wrap items-center justify-between gap-4 shadow-md relative overflow-hidden" style={{ background: HEADER_GRADIENT }}>
    {/* subtle light bloom */}
    <div className="absolute inset-0 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 88% -30%, rgba(255,255,255,0.35), transparent 45%)' }} />
    <div className="flex items-center gap-3 relative min-w-0">
      {Icon && (
        <span className="w-11 h-11 rounded-2xl bg-white/15 flex items-center justify-center text-white shrink-0 ring-1 ring-white/20">
          <Icon size={20} />
        </span>
      )}
      <div className="min-w-0">
        <h2 className="text-[18px] sm:text-[20px] font-extrabold tracking-tight text-white leading-tight truncate">
          {title}{highlight && <span className="font-medium text-white/75"> — {highlight}</span>}
        </h2>
        {subtitle && <p className="text-[12px] text-white/70 font-medium mt-0.5 truncate">{subtitle}</p>}
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2 relative">{children}</div>
  </div>
);

/** White pill action button for the hero header. */
export const HeroButton = ({ icon: Icon, children, onClick }) => (
  <button onClick={onClick} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all">
    {Icon && <Icon size={14} />} {children}
  </button>
);
