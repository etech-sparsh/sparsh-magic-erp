import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Search } from 'lucide-react';

/**
 * Styled single-select used across the app (TPMS filters, Task & Delegation filters).
 *
 * Replaces a native <select> because its option popup is drawn by the OS and cannot be
 * styled — no padding, no hover state, no rounding, no theming of the highlight, and it
 * ignores dark mode on some platforms.
 *
 * The one thing the native popup gave for free was being drawn outside the DOM, and so never
 * clipped by an ancestor's overflow. `Listbox` buys that back explicitly: it portals to
 * <body> and positions from the trigger's viewport rect, which is what keeps it clear of the
 * `overflow-x-auto` table wrappers and card clipping these filters sit inside.
 *
 * Lives in components/common (not a feature folder) because both modules consume it.
 */

export const normaliseOptions = (options = []) =>
  options.map((o) => (typeof o === 'object' && o !== null
    ? { value: String(o.id ?? o.value ?? ''), label: String(o.name ?? o.label ?? o.id ?? '') }
    : { value: String(o), label: String(o) }));

/* Width containment on both selects below is deliberate and is what keeps TPMS filter rows
   inside the viewport: one long company or member name must never stretch the control past
   its container and push the page sideways on smaller screens.

     min-w-0     — lets it shrink inside a flex row (a flex child otherwise refuses to go
                   below its content width, which is what produced the overflow)
     max-w-full  — never wider than the container it is in
     truncate    — the selected label ellipses instead of forcing the control wider

   ── Why this is a custom listbox and not a native <select> ──
   A native <select>'s popup is drawn by the OS, so CSS cannot reach it: no padding, no hover
   state, no rounding, no theming of the highlight. It also ignores dark mode on some
   platforms and renders a bare system list.

   Trading it for a custom list costs the one thing the native popup gave for free — being
   drawn outside the DOM, and therefore never clipped by an ancestor's overflow. `Listbox`
   below buys that back explicitly, by portalling to <body> and positioning from the trigger's
   viewport rect. That is what keeps it clear of the `overflow-x-auto` table wrappers and card
   clipping these filters sit inside. */

/** Portalled option list. Fixed-positioned from the trigger's rect, so no ancestor's
 *  overflow can clip it and it always resolves against the viewport, not the page. */
const Listbox = ({ anchorRef, options, value, onPick, onClose, searchable }) => {
  const listRef = useRef(null);
  const inputRef = useRef(null);
  const [pos, setPos] = useState(null);
  const [query, setQuery] = useState('');

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const [active, setActive] = useState(() =>
    Math.max(0, options.findIndex((o) => o.value === value)));

  // Typing changes what is on screen, so the cursor has to be re-resolved — otherwise it
  // points past the end of a shortened list and Enter picks nothing. Aim for the current
  // selection when it survived the filter (which is also what happens on open, so the list
  // still lands on the selected row), and fall back to the first match when it did not.
  useEffect(() => {
    const i = shown.findIndex((o) => o.value === value);
    setActive(i >= 0 ? i : 0);
    // Intentionally keyed on `query` only: `shown` is a fresh array every render, and `value`
    // cannot change while the list is open (picking one closes it).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  useEffect(() => { if (searchable) inputRef.current?.focus(); }, [searchable]);

  // Measure before paint so the list never renders in the wrong spot for a frame.
  const place = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const GAP = 6;
    const MAX_H = 288;                                 // ~8 rows before it scrolls
    const MAX_W = 420;                                 // wide enough for a full person's name
    const EDGE = 8;

    const below = window.innerHeight - r.bottom - GAP;
    const above = r.top - GAP;
    // Flip above only when there is genuinely more room there — a long list near the bottom
    // of the screen would otherwise be squeezed into a few pixels.
    const flipUp = below < Math.min(MAX_H, 160) && above > below;

    // The list is NOT locked to the trigger's width: these filters are narrow pills, and
    // pinning the popup to them truncated every option to "Abhish…". It shrink-wraps its
    // content instead, with the trigger width as the FLOOR (never narrower than the control)
    // and the free space beside it as the ceiling (never off-screen).
    const roomRight = window.innerWidth - r.left - EDGE;
    const roomLeft = r.right - EDGE;
    // Anchor to the trigger's right edge instead when the space to its right is too cramped
    // to be useful — otherwise a control near the window edge gets a sliver of a list.
    const anchorRight = roomRight < Math.min(MAX_W, 240) && roomLeft > roomRight;

    setPos({
      // A search box needs room to be usable, so a searchable list gets a wider floor than the
      // trigger alone would give it. maxWidth still wins, so this can never push it off-screen.
      minWidth: Math.max(r.width, searchable ? 220 : 0),
      maxWidth: Math.min(MAX_W, anchorRight ? roomLeft : roomRight),
      maxHeight: Math.max(120, Math.min(MAX_H, flipUp ? above : below)),
      ...(anchorRight
        ? { right: Math.max(EDGE, window.innerWidth - r.right) }
        : { left: Math.max(EDGE, r.left) }),
      ...(flipUp ? { bottom: window.innerHeight - r.top + GAP } : { top: r.bottom + GAP }),
    });
  }, [anchorRef, searchable]);

  useLayoutEffect(() => { place(); }, [place]);

  useEffect(() => {
    // `true` = capture, so scrolling ANY ancestor repositions it, not just the window.
    const onScroll = () => place();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [place]);

  useEffect(() => {
    const onDown = (e) => {
      if (listRef.current?.contains(e.target) || anchorRef.current?.contains(e.target)) return;
      onClose();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [anchorRef, onClose]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(shown.length - 1, i + 1)); }
      if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
      if (e.key === 'Home') { e.preventDefault(); setActive(0); }
      if (e.key === 'End') { e.preventDefault(); setActive(shown.length - 1); }
      // Space selects ONLY on a non-searchable list. With a search box open a space is part of
      // what the user is typing ("Abhigyan Jain"), so swallowing it would make most names
      // impossible to search for.
      if (e.key === 'Enter' || (e.key === ' ' && !searchable)) {
        e.preventDefault();
        if (shown[active]) onPick(shown[active].value);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [active, shown, onPick, onClose, searchable]);

  // Keep the keyboard cursor in view within the scrolling list.
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  if (!pos) return null;

  return createPortal(
    // Column layout: the search box is fixed and only the option list scrolls, so the input
    // never scrolls out of reach on a long roster.
    <div ref={listRef} style={{ position: 'fixed', zIndex: 1000, ...pos }}
      className="flex flex-col overflow-hidden rounded-xl bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl">
      {searchable && (
        <div className="shrink-0 p-1.5 border-b border-[var(--border)]">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…" aria-label="Search options"
              className="w-full pl-7 pr-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
      )}
      <div role="listbox" className="flex-1 overflow-y-auto p-1">
      {shown.length === 0 && (
        <div className="px-3 py-2.5 text-[12px] font-semibold text-[var(--text-muted)]">
          {query ? 'No matches' : 'No options'}
        </div>
      )}
      {shown.map((o, i) => {
        const selected = o.value === value;
        return (
          <button key={o.value} type="button" role="option" aria-selected={selected}
            data-active={i === active}
            title={o.label}
            onMouseEnter={() => setActive(i)}
            onClick={() => onPick(o.value)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-[12.5px] font-bold transition-colors
              ${i === active ? 'bg-[var(--input-bg)]' : ''}
              ${selected ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>
            {/* Check marks the selection so it is never conveyed by colour alone. */}
            <Check size={14} className={selected ? 'opacity-100 shrink-0' : 'opacity-0 shrink-0'} />
            {/* nowrap (not truncate) so the row asks for its full width — that is what the
                shrink-wrapping container measures against. Names only ellipsis once they
                exceed the max width, and the title attribute covers those. */}
            <span className="whitespace-nowrap overflow-hidden text-ellipsis">{o.label}</span>
          </button>
        );
      })}
      </div>
    </div>,
    document.body,
  );
};

/** Shared trigger + listbox. `className` carries the per-variant pill styling.
 *
 *  `searchable` is ON by default — these filters list people and companies, which is exactly
 *  where scanning by eye breaks down. Month pickers opt out (`searchable={false}`): twelve
 *  ordered, familiar values are faster to point at than to type. */
export const StyledSelect = ({ value, onChange, options, className, searchable = true }) => {
  const anchorRef = useRef(null);
  const [open, setOpen] = useState(false);
  const items = normaliseOptions(options);
  const current = items.find((o) => o.value === String(value ?? '')) || items[0];

  const pick = useCallback((v) => { onChange(v); setOpen(false); }, [onChange]);

  return (
    <>
      <button ref={anchorRef} type="button" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className={className}>
        <span className="truncate">{current?.label ?? ''}</span>
        <ChevronDown size={14} className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <Listbox anchorRef={anchorRef} options={items} value={String(value ?? '')}
          onPick={pick} onClose={() => setOpen(false)} searchable={searchable} />
      )}
    </>
  );
};

/**
 * Standard filter pill — the app's usual input-styled control, so a filter row keeps the same
 * shape it had as a native <select>. Used by the Task & Delegation filter bars.
 *
 * A placeholder entry (`{ id: '', name: 'Category' }`) works exactly as the old
 * `<option value="">Category</option>` did: it is simply the first option, and is what shows
 * while nothing is chosen.
 */
export const SelectField = ({ className = '', ...props }) => (
  <StyledSelect {...props}
    className={`min-w-0 max-w-full flex items-center justify-between gap-2 px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] cursor-pointer ${className}`} />
);
