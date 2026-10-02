import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
// Constants and pure helpers live in the .js sibling, imported from there by both this
// module and every screen. Re-exporting them here would break Fast Refresh again, which
// is the whole reason for the split -- same pairing as analytics/analyticsKit.
import { CARD, FIELD, LABEL, tint } from './internalKit';

/**
 * HRMS ▸ internal recruitment track — shared presentation pieces.
 *
 * Five screens land in this phase and they all show the same three things: a list that has
 * to work at 375px, a status chip, and a signature field on every decision. Defining those
 * once keeps the track reading as one surface, and keeps a spacing change to one file — the
 * same reason common/HrmsStates and analytics/analyticsKit exist.
 *
 * Styled entirely with the ERP's CSS variables, so light/dark theming is inherited rather
 * than re-implemented.
 */

const TONES = {
  good: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  bad: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  warn: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  neutral: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  accent: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
};

export const Chip = ({ children, tone = 'neutral', title }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]
      font-bold whitespace-nowrap ${TONES[tone] || TONES.neutral}`}
  >
    {children}
  </span>
);

/**
 * A responsive record list.
 *
 * Cards below `md`, a real table above it. Not a table squeezed into a phone with horizontal
 * scroll: at 375px a row of eight columns is unreadable however it is scrolled, and the
 * fields that matter differ between the two shapes anyway.
 *
 * `columns` drives the table; `renderCard` draws the small-screen version. Both read the
 * same row object, so the two can show different fields without disagreeing about the data.
 */
export const RecordList = ({ rows, columns, renderCard, keyOf, empty }) => {
  if (!rows?.length) return empty || null;
  return (
    <>
      <div className="md:hidden space-y-2.5">
        {rows.map((row) => (
          <div key={keyOf(row)}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
            {renderCard(row)}
          </div>
        ))}
      </div>

      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="text-[10.5px] font-bold uppercase tracking-widest
              text-[var(--text-muted)] border-b border-[var(--border)]">
              {columns.map((col) => (
                <th key={col.key}
                  scope="col"
                  className={`py-2 px-2 ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={keyOf(row)}
                className="border-b border-[var(--border)] last:border-0
                  hover:bg-[var(--input-bg)]">
                {columns.map((col) => (
                  <td key={col.key}
                    className={`py-2.5 px-2 align-top
                      ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
};

/**
 * The signature field every decision on this track carries.
 *
 * Server-required on scorecard approval, offer approval, probation confirmation and
 * exception decisions — an unsigned sign-off is not one. Asking here rather than after a 422
 * is an affordance; the server is still the control.
 */
export const SignatureField = ({ value, onChange, id, hint }) => (
  <div>
    <label className={LABEL} htmlFor={id}>Your name (signature) *</label>
    <input id={id} required value={value} onChange={(e) => onChange(e.target.value)}
      className={FIELD} placeholder="Type your full name" autoComplete="name" />
    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
      {hint || 'This decision is recorded against your name.'}
    </p>
  </div>
);

/** A short definition list — label above value, wrapping cleanly on a phone. */
export const Facts = ({ items }) => (
  <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2.5">
    {items.filter((i) => i && i.value != null && i.value !== '').map((item) => (
      <div key={item.label} className="min-w-0">
        <dt className="text-[10.5px] font-bold uppercase tracking-widest
          text-[var(--text-muted)]">{item.label}</dt>
        <dd className="mt-0.5 text-[13px] text-[var(--text-main)] break-words">
          {item.value}
        </dd>
      </div>
    ))}
  </dl>
);

/** A modal shell. Labelled for screen readers and closable on Escape. */
export const Modal = ({ title, subtitle, onClose, children, footer, labelledBy }) => (
  <div
    className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4"
    role="dialog" aria-modal="true" aria-labelledby={labelledBy}
    onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
  >
    <div className="w-full max-w-lg max-h-[90vh] flex flex-col rounded-2xl
      border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
      <div className="px-5 py-4 border-b border-[var(--border)]">
        <h2 id={labelledBy} className="text-[15px] font-bold text-[var(--text-main)]">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">{subtitle}</p>
        )}
      </div>
      <div className="p-5 space-y-3.5 overflow-y-auto">{children}</div>
      {footer && (
        <div className="flex items-center justify-end gap-2 px-5 py-4
          border-t border-[var(--border)]">
          {footer}
        </div>
      )}
    </div>
  </div>
);

export const Btn = ({ tone = 'ghost', children, ...rest }) => {
  const tones = {
    primary: 'bg-[var(--accent-indigo)] text-white',
    danger: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
    ghost: 'border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)]',
  };
  return (
    <button type="button" {...rest}
      className={`h-9 px-4 rounded-lg text-[12px] font-bold inline-flex items-center gap-1.5
        disabled:opacity-50 transition-colors ${tones[tone]}`}>
      {children}
    </button>
  );
};

/**
 * A headline number with its own tinted icon.
 *
 * Lives in the kit rather than on one dashboard because both hiring tracks show a row of
 * these above the stage rail, and two hand-built copies would drift apart — which is the
 * whole reason the two boards stopped looking like one module in the first place.
 */
export const Tile = ({ label, value, icon: Icon, tone = 'indigo', hint }) => (
  <div className={`${CARD} !p-4 flex items-center gap-3`}>
    <span className={`h-10 w-10 rounded-xl grid place-items-center shrink-0 ${tint(tone).bg}`}>
      <Icon size={18} className={tint(tone).text} />
    </span>
    <div className="min-w-0">
      <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] truncate">
        {label}
      </p>
      <p className={`text-[22px] font-bold tabular-nums leading-tight ${
        tone === 'red' ? 'text-[var(--accent-red)]'
          : tone === 'orange' ? 'text-[var(--accent-orange)]' : 'text-[var(--text-main)]'}`}>
        {value}
      </p>
      {hint && (
        <p className="text-[11px] text-[var(--text-muted)] truncate" title={hint}>{hint}</p>
      )}
    </div>
  </div>
);

/**
 * A collapsed-by-default "who hands off to whom" reference.
 *
 * Both hiring tracks answer the same question — internal hiring lists its twelve SOP
 * handoffs, PRO-fit lists who owns each of its eight stages — and they answer it in the
 * same place on the page, so they answer it with the same component. Collapsed because it
 * is a reference to open when something is unclear, not something to scroll past on every
 * visit.
 */
export const FlowAccordion = ({ icon: Icon, title, subtitle, steps }) => {
  const [open, setOpen] = useState(false);
  return (
    <section className={`${CARD} !p-0 overflow-hidden`}>
      <button type="button" onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 p-4 text-left">
        <span className="flex items-center gap-2.5">
          <span className="h-8 w-8 rounded-lg bg-[var(--accent-indigo-bg)] grid place-items-center shrink-0">
            <Icon size={15} className="text-[var(--accent-indigo)]" />
          </span>
          <span>
            <span className="block text-[13px] font-bold text-[var(--text-main)]">{title}</span>
            <span className="block text-[11.5px] text-[var(--text-muted)]">{subtitle}</span>
          </span>
        </span>
        <ChevronDown size={16}
          className={`text-[var(--text-muted)] shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <ol className="px-4 pb-4 space-y-0">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className="h-6 w-6 rounded-full bg-[var(--accent-indigo-bg)]
                                 text-[var(--accent-indigo)] text-[10.5px] font-bold
                                 grid place-items-center shrink-0">
                  {i + 1}
                </span>
                {i < steps.length - 1 && (
                  <span aria-hidden="true" className="w-px flex-1 bg-[var(--border)] my-0.5" />
                )}
              </div>
              <div className="pb-4 min-w-0">
                <p className="text-[12px] font-bold uppercase tracking-wide text-[var(--accent-indigo)]">
                  {step.actor}
                </p>
                <p className="text-[13px] text-[var(--text-main)] mt-0.5">{step.action}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
};
