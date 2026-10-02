import React, { useRef, useState } from 'react';
import { Folder, CalendarDays, MoreHorizontal, ChevronUp, ChevronDown } from 'lucide-react';
import { PRIORITY_CONFIG } from './statusConfig';
import { getInitials, formatDate } from './taskDisplayUtils';

// ─── Shared table cells for the task list ───────────────────────────────────────────────
// The reference design leans on colour to make a dense table scannable: a tinted pill per
// category, a coloured avatar per person, a pill per priority. All of it is derived from the
// app's five existing accent tokens (index.css) rather than one-off hex values, so the table
// re-themes with the rest of the app in both light and dark mode.

const ACCENTS = ['indigo', 'green', 'orange', 'red', 'yellow'];

// A stable colour per label: the same category (or person) is the same colour on every row and
// every page load, without needing a colour stored against it anywhere.
const accentFor = (label, palette = ACCENTS) => {
  const text = String(label || '');
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  return palette[hash % palette.length];
};

const tone = (accent) => ({
  color: `var(--accent-${accent})`,
  bg: `var(--accent-${accent}-bg)`,
  border: `var(--accent-${accent}-border)`,
});

// A category is a LABEL, not a state — so it stays neutral and the accent lands only on the
// folder mark. A fully tinted category pill sat next to a tinted priority pill and a tinted
// status pill, three warm blocks in a row, and the one that actually matters (status) stopped
// standing out. The hashed colour still distinguishes one category from another at a glance;
// it just no longer shouts.
export const CategoryPill = ({ name }) => {
  if (!name) return <span className="text-[12px] font-bold text-[var(--text-muted)]">—</span>;
  const t = tone(accentFor(name));
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold max-w-[160px] bg-[var(--input-bg)] text-[var(--text-main)] border border-[var(--border)]">
      <Folder size={12} className="shrink-0" style={{ color: t.color }} />
      <span className="truncate">{name}</span>
    </span>
  );
};

// Yellow is left out of the avatar palette — white initials on it fail to read.
const AVATAR_ACCENTS = ['indigo', 'green', 'orange', 'red'];

// `note` is a second line under the name — used to name the person a task is waiting on
// ("Dependent on Other: Cara") without passing them off as one of its assignees.
export const AssigneeCell = ({ name, note }) => {
  const label = name || '—';
  return (
    <span className="inline-flex items-center gap-2 min-w-0">
      <span className="w-7 h-7 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0"
        style={{ background: `var(--accent-${accentFor(label, AVATAR_ACCENTS)})` }}>
        {getInitials(label)}
      </span>
      <span className="min-w-0">
        <span className="block text-[12px] font-bold text-[var(--text-main)] truncate">{label}</span>
        {note && (
          <span className="block text-[9px] font-black uppercase tracking-wider text-[var(--accent-yellow)] truncate">{note}</span>
        )}
      </span>
    </span>
  );
};

// Priority earns colour only when it is NOT the default. Almost every task is Normal, so a
// tinted Normal pill painted the whole list yellow and told the reader nothing — the eye
// should be drawn to the High ones. Normal renders neutral with a coloured dot; High and Low
// keep their full tint.
export const PriorityPill = ({ priority }) => {
  const key = PRIORITY_CONFIG[priority] ? priority : 'Normal';
  const cfg = PRIORITY_CONFIG[key];
  const Icon = cfg.icon;
  if (key === 'Normal') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold whitespace-nowrap bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]">
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: cfg.color }} />
        {cfg.label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold whitespace-nowrap"
      style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}>
      <Icon size={12} /> {cfg.label}
    </span>
  );
};

export const DateCell = ({ value, overdue }) => (
  <span className={`inline-flex items-center gap-1.5 text-[12px] font-bold whitespace-nowrap ${overdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
    <CalendarDays size={13} className="shrink-0 opacity-80" /> {formatDate(value)}
  </span>
);

// Sortable column header. `sortKey` is null for columns the list can't sort by, which then
// render as a plain label rather than a dead-looking button.
export const SortableTh = ({ label, sortKey, activeKey, dir, onSort, align = 'left' }) => {
  const isActive = sortKey && activeKey === sortKey;
  // Literal class names: Tailwind scans source text, so a `text-${align}` template would
  // never be generated.
  const base = `px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap ${align === 'right' ? 'text-right' : 'text-left'}`;
  if (!sortKey) return <th className={base}>{label}</th>;
  return (
    <th className={base}>
      <button type="button" onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 uppercase tracking-widest transition-colors ${isActive ? 'text-[var(--accent-indigo)]' : 'hover:text-[var(--text-main)]'}`}>
        {label}
        <span className="flex flex-col -space-y-1.5">
          <ChevronUp size={9} className={isActive && dir === 'asc' ? 'opacity-100' : 'opacity-40'} />
          <ChevronDown size={9} className={isActive && dir === 'desc' ? 'opacity-100' : 'opacity-40'} />
        </span>
      </button>
    </th>
  );
};

// Row "⋯" menu. Positioned `fixed` from the button's own rect: the table body is a horizontal
// scroll container, so an absolutely-positioned menu would be clipped on the last rows.
//
// A ONE-ITEM menu is rendered as that item's button instead. Most viewers can only view a
// task — delete is limited to its creator and admins — so the dropdown was costing everyone
// else a click to reveal a single "View Details" entry. A menu that holds one option is just
// a button wearing a disguise.
export const RowActionsMenu = ({ open, onToggle, onClose, items }) => {
  const btnRef = useRef(null);
  const [pos, setPos] = useState(null);

  const list = items || [];
  if (list.length === 1) {
    const only = list[0];
    const OnlyIcon = only.icon;
    return (
      <button type="button" title={only.label}
        onClick={(e) => { e.stopPropagation(); only.onClick(); }}
        className={`p-1.5 rounded-lg transition-colors ${only.danger
          ? 'text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]'
          : 'text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]'}`}>
        <OnlyIcon size={16} />
      </button>
    );
  }

  // Height of one menu row (py-2 + 12px text) plus the list's own vertical padding. Used to
  // decide whether the menu still fits below the button — measuring the real node would need
  // it mounted first, which is a frame too late to place it.
  const ITEM_H = 34;
  const PAD_V = 12;
  const GAP = 6;

  const handleToggle = (e) => {
    e.stopPropagation();
    const r = btnRef.current?.getBoundingClientRect();
    if (r) {
      const height = list.length * ITEM_H + PAD_V;
      // Flip ABOVE the button when the space beneath it can't hold the menu. The last rows of
      // a long table sit near the bottom of the viewport, where a downward menu would open
      // off-screen — and that is also exactly where the floating chat button lives.
      const roomBelow = window.innerHeight - r.bottom;
      const top = roomBelow >= height + GAP + 8
        ? r.bottom + GAP
        : Math.max(8, r.top - height - GAP);
      setPos({ top, right: Math.max(8, window.innerWidth - r.right) });
    }
    onToggle();
  };

  return (
    <>
      <button ref={btnRef} type="button" onClick={handleToggle} title="Actions"
        className={`p-1.5 rounded-lg transition-colors ${open ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)]'}`}>
        <MoreHorizontal size={16} />
      </button>
      {open && pos && (
        <div onClick={e => e.stopPropagation()}
          className="fixed z-[70] min-w-[164px] py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl"
          style={{ top: pos.top, right: pos.right }}>
          {list.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.label} type="button"
                onClick={() => { onClose(); item.onClick(); }}
                className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-[12px] font-bold text-left transition-colors hover:bg-[var(--input-bg)] ${item.danger ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
                <Icon size={14} /> {item.label}
              </button>
            );
          })}
        </div>
      )}
    </>
  );
};

// Status renders as the same icon+label pill as priority, but stays a real <select> when the
// viewer may act on it: the native control is laid transparently over the pill, so the design
// keeps its icon and colour while dropdown behaviour, keyboard access and mobile pickers are
// unchanged. `options` is a list of [value, label] pairs; omit `onChange` for a read-only pill.
export const StatusControl = ({ cfg, value, options, onChange, disabled, title, frozen }) => {
  const Icon = cfg.icon;
  const pill = (
    <>
      {Icon && <Icon size={12} className="shrink-0" />}
      <span className="truncate">{cfg.label}</span>
      {onChange && <ChevronDown size={11} className="shrink-0 opacity-60" />}
    </>
  );
  const style = { background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` };
  const base = 'relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold whitespace-nowrap max-w-[190px]';

  if (!onChange) {
    return <span title={title} className={`${base} ${frozen ? 'opacity-60' : ''}`} style={style}>{pill}</span>;
  }
  return (
    <span title={title} className={`${base} ${disabled ? 'opacity-60 cursor-wait' : 'cursor-pointer'}`} style={style}>
      {pill}
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        onClick={e => e.stopPropagation()}
        disabled={disabled}
        aria-label="Task status"
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-wait"
      >
        {options.map(([val, label, isDisabled]) => (
          <option key={val} value={val} disabled={isDisabled}>{label}</option>
        ))}
      </select>
    </span>
  );
};
