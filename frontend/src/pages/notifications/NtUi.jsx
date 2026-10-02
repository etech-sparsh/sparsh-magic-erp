import React from 'react';
import { motion } from 'framer-motion';
import { X, RefreshCw, CheckCircle2, AlertTriangle, Info } from 'lucide-react';
import { TONE } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   Notification Templates — the small shared pieces: pills, the on/off switch, buttons and
   the modal shell. One set, so every screen in the module looks and behaves the same.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

export const Pill = ({ label, tone = 'muted', icon: Icon, title }) => {
  const s = TONE[tone] || TONE.muted;
  return (
    <span title={title}
      className="inline-flex items-center gap-1.5 text-[10.5px] font-bold px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {Icon ? <Icon size={11} /> : <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />}
      {label}
    </span>
  );
};

export const Switch = ({ on, onClick, disabled, title }) => (
  <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={onClick}
    title={title || (on ? 'On — click to turn off' : 'Off — click to turn on')}
    className="relative w-[40px] h-[22px] rounded-full transition-colors shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
    style={{ background: on ? 'var(--accent-green)' : 'var(--border)' }}>
    <span className="absolute top-[3px] w-4 h-4 rounded-full bg-white shadow transition-all"
      style={{ left: on ? '21px' : '3px' }} />
  </button>
);

const BUTTON_STYLE = {
  primary: 'bg-[var(--accent-indigo)] text-white shadow-sm enabled:hover:opacity-90',
  outline: 'border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-main)] enabled:hover:bg-[var(--input-bg)]',
  ghost: 'text-[var(--text-muted)] enabled:hover:bg-[var(--input-bg)]',
  danger: 'border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] text-[var(--accent-red)] enabled:hover:opacity-90',
  success: 'border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] text-[var(--accent-green)] enabled:hover:opacity-90',
};

export const Button = ({ variant = 'primary', size = 'md', icon: Icon, busy, className = '', children, ...rest }) => {
  const iconSize = size === 'sm' ? 12 : 14;
  return (
    <button type="button" {...rest} disabled={busy || rest.disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-bold whitespace-nowrap transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
        size === 'sm' ? 'px-2.5 py-1.5 text-[11.5px]' : 'px-4 py-2 text-[12.5px]'} ${BUTTON_STYLE[variant] || BUTTON_STYLE.primary} ${className}`}>
      {busy ? <RefreshCw size={iconSize} className="animate-spin" /> : (Icon && <Icon size={iconSize} />)}
      {children}
    </button>
  );
};

/** Backdrop + animated panel. `z` is a literal Tailwind class so a dialog opened from inside
 *  another dialog can sit above it. */
export const Modal = ({ onClose, busy, width = 'max-w-xl', z = 'z-50', children }) => (
  <MotionDiv className={`fixed inset-0 ${z} flex items-center justify-center p-3 sm:p-4`}
    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
    <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
    <MotionDiv role="dialog" aria-modal="true"
      initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
      className={`relative w-full ${width} rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[92vh] flex flex-col`}>
      {children}
    </MotionDiv>
  </MotionDiv>
);

export const ModalHeader = ({ icon: Icon, title, subtitle, onClose, busy, tone = 'indigo' }) => {
  const s = TONE[tone] || TONE.indigo;
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--border)] shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        {Icon && (
          <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: s.bg, color: s.c }}>
            <Icon size={17} />
          </span>
        )}
        <div className="min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight truncate">{title}</h3>
          {subtitle && <p className="text-[11.5px] text-[var(--text-muted)] truncate mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {onClose && (
        <button type="button" onClick={onClose} disabled={busy} aria-label="Close"
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50 shrink-0">
          <X size={16} />
        </button>
      )}
    </div>
  );
};

export const ModalFooter = ({ children }) => (
  <div className="px-5 py-3 border-t border-[var(--border)] flex flex-wrap items-center justify-end gap-2 shrink-0">
    {children}
  </div>
);

export const ConfirmDialog = ({ title, body, confirmLabel, tone = 'red', busy, onCancel, onConfirm }) => {
  const s = TONE[tone] || TONE.red;
  return (
    <Modal onClose={onCancel} busy={busy} width="max-w-md" z="z-[60]">
      <ModalHeader icon={tone === 'green' ? CheckCircle2 : AlertTriangle} tone={tone} title={title} />
      <div className="px-5 py-4 text-[13px] leading-relaxed">{body}</div>
      <ModalFooter>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
        <button type="button" onClick={onConfirm} disabled={busy}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60"
          style={{ background: s.c }}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
          {busy ? 'Working…' : confirmLabel}
        </button>
      </ModalFooter>
    </Modal>
  );
};

export const Field = ({ label, required, hint, children }) => (
  <div className="flex flex-col gap-1.5">
    <span className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
      {label}{required && <span className="text-[var(--accent-red)]"> *</span>}
    </span>
    {children}
    {hint && <span className="text-[11px] text-[var(--text-muted)] leading-relaxed">{hint}</span>}
  </div>
);

export const Notice = ({ tone = 'indigo', icon, children }) => {
  const s = TONE[tone] || TONE.indigo;
  const Icon = icon || Info;
  return (
    <div className="flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-[12px] font-semibold leading-relaxed"
      style={{ background: s.bg, borderColor: s.bd, color: 'var(--text-main)' }}>
      <Icon size={15} className="mt-[1px] shrink-0" style={{ color: s.c }} />
      <div className="min-w-0">{children}</div>
    </div>
  );
};
