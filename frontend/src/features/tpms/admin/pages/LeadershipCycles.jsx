import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CalendarRange, Plus, RefreshCw, AlertTriangle, CheckCircle2, X, ShieldAlert,
  Users, Lock, Unlock, ArrowRight, Layers, Calculator, Send, Undo2, Trash2, Mail,
  CalendarClock,
  FolderOpen, Upload, ExternalLink,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import {
  getLeadershipConfig, getLeadershipCycles, createLeadershipCycle, updateLeadershipCycle,
  getLeadershipQuorum, computeLeadershipCycle, publishLeadershipCycle,
  deleteLeadershipCycle,
  getLeadershipDocuments, uploadLeadershipDocument, deleteLeadershipDocument,
} from '../../../../services/leadershipApi';
import { cycleLabel, cycleHint, isScoreReady } from '../../leadership/leadershipStatus';
import {
  canManage, errText, fmtNum, parseUtc, useAsync, useLeadershipCompany,
} from '../../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ Assessment Cycles.

   "By giving feedback to leaders once in every 2 months."

   A cycle spans two calendar months and owns the degree (180°/360°) and the response
   threshold for every leader enrolled in it. Closing a cycle freezes its scores into
   history, which is why it is a deliberate action rather than a date passing.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const STATUS_TONE = {
  draft:     { c: 'var(--text-muted)',    bg: 'var(--input-bg)',          bd: 'var(--border)' },
  open:      { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
  closed:    { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)',  bd: 'var(--accent-yellow-border)' },
  computed:  { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)',  bd: 'var(--accent-indigo-border)' },
  published: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
};

/** "Opens 5 Sep · Closes 19 Sep", or just whichever half was set. */
const windowLabel = (row) => {
  const when = (v) => {
    const d = parseUtc(v);
    return d ? d.toLocaleString(undefined,
      { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;
  };
  return [
    when(row.opens_at) && `Opens ${when(row.opens_at)}`,
    when(row.closes_at) && `Closes ${when(row.closes_at)}`,
  ].filter(Boolean).join(' · ');
};

const Pill = ({ label, tone = 'draft' }) => {
  const s = STATUS_TONE[tone] || STATUS_TONE.draft;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide uppercase px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, hint, children }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}</span>
    {children}
    {hint && <span className="text-[10.5px] text-[var(--text-muted)] font-medium">{hint}</span>}
  </label>
);

/** Open a new 2-month cycle. Mounted only while open, so state seeds cleanly. */
const CycleModal = ({ config, existing, onClose, onSubmit }) => {
  const taken = new Set((existing || []).map((c) => c.cycle));
  const available = (config?.cycles || []).filter((c) => !taken.has(c.code));

  // RECOMMENDED_PER_RELATION givers for every relation the degree collects: four at
  // 180° (superiors + same-department peers), eight at 360°. Read from /config so the panel
  // composition stays owned by the server; the literal is only the moment before it lands.
  const panelSizeOf = (code) => {
    const d = (config?.degrees || []).find((x) => String(x.code) === String(code));
    return d?.panel_size || (String(code) === '180' ? 4 : 8);
  };

  const [cycle, setCycle] = useState(available[0]?.code || '');
  const [degree, setDegree] = useState('360');
  const [minResponses, setMinResponses] = useState('3');
  const [opensAt, setOpensAt] = useState('');
  const [closesAt, setClosesAt] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!cycle) { setErr('Choose a cycle.'); return; }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({
        cycle,
        degree,
        // Mirrors both server bounds: MIN_RESPONSES_FLOOR, which raises anything lower
        // to 3, and the degree's panel size, which is the most replies that can ever
        // arrive. Asking 8 of a 180° panel of four is a threshold nobody could reach.
        min_responses: Math.min(Math.max(3, Number(minResponses) || 3), panelSizeOf(degree)),
        // Sent as UTC instants. A <input type="datetime-local"> value has no zone, so it is
        // read in the browser's own timezone — which is the one HR is thinking in when they
        // pick "closes 5pm Friday".
        opens_at: opensAt ? new Date(opensAt).toISOString() : null,
        closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        notes: notes.trim(),
      });
    } catch (ex) {
      setErr(errText(ex, 'Could not create the cycle.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <Plus size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Open an Assessment Cycle</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          <Field label="Cycle" hint="Leadership feedback runs once every 2 months.">
            <FilterSelect value={cycle} onChange={setCycle}
              options={available.length
                ? available.map((c) => ({
                    id: c.code,
                    // A past window's feedback links are already expired, so such a cycle
                    // can be created but never dispatched. Say so in the option rather
                    // than letting HR find out at the dispatch step.
                    name: c.expired ? `${c.label} — window closed, cannot collect` : c.label,
                  }))
                : [{ id: '', name: 'Every recent cycle already exists' }]} />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Feedback degree"
              hint={`360° adds other-department peers and juniors — ${panelSizeOf('360')} givers against ${panelSizeOf('180')}.`}>
              <FilterSelect value={degree}
                onChange={(v) => {
                  setDegree(v);
                  // Narrowing to 180° halves the panel, so a threshold picked under 360°
                  // can be left asking for more replies than the cycle now collects.
                  // Bring it down with the degree rather than failing on submit.
                  setMinResponses((m) => String(Math.min(Number(m) || 3, panelSizeOf(v))));
                }}
                options={[{ id: '360', name: `360° — all relations (${panelSizeOf('360')} givers)` },
                          { id: '180', name: `180° — superiors & peers (${panelSizeOf('180')} givers)` }]} />
            </Field>
            <Field label="Minimum responses"
              hint={`3 is the anonymity floor and cannot go lower. A ${degree}° panel is ${panelSizeOf(degree)} givers, so it cannot go higher than that either.`}>
              <input type="number" min={3} max={panelSizeOf(degree)} value={minResponses}
                onChange={(e) => setMinResponses(e.target.value)} className={inputCls} />
            </Field>
          </div>

          {/* The collection window. Both optional: leaving them empty keeps the behaviour
              every existing cycle has, where the cycle's own two calendar months decide when
              feedback can arrive. Setting them narrows that to the days HR actually wants. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Opens" hint="Optional. Before this, a giver's link says to come back.">
              <input type="datetime-local" value={opensAt}
                onChange={(e) => setOpensAt(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Closes"
              hint="Optional. After this, no further feedback is accepted — even on a page left open.">
              <input type="datetime-local" value={closesAt} min={opensAt || undefined}
                onChange={(e) => setClosesAt(e.target.value)} className={inputCls} />
            </Field>
          </div>

          {opensAt && closesAt && new Date(closesAt) <= new Date(opensAt) && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} /> The close date is not after the open date, so the
              window would never be open.
            </div>
          )}

          <Field label="Notes">
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              placeholder="Optional note for HR…" className={`${inputCls} resize-y`} />
          </Field>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving || !cycle}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Creating…' : 'Open Cycle'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Destructive confirm for a cycle. Mounted only while a row is pending, so it seeds from
    that row and needs no reset. The server refuses a cycle holding feedback or one already
    published — that failure is shown in here rather than behind the overlay. */
const ConfirmDeleteModal = ({ row, onClose, onConfirm }) => {
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const enrolled = row.subject_count || 0;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  const go = async () => {
    setSaving(true);
    setErr('');
    try {
      await onConfirm(row);
    } catch (e) {
      setErr(errText(e, 'Could not delete this cycle.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-red-bg)] text-[var(--accent-red)]">
              <Trash2 size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Delete this cycle?</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-2.5">
            <span className="block text-[13.5px] font-bold">{row.label || row.cycle}</span>
            <span className="block text-[10.5px] font-mono text-[var(--text-muted)]">{row.cycle}</span>
          </div>

          {enrolled > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>
                This also un-enrols <b>{enrolled}</b> leader{enrolled === 1 ? '' : 's'} and invalidates
                any feedback links already sent to their panels.
              </span>
            </div>
          )}

          <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
            The cycle and everything set up under it are removed. This cannot be undone.
          </p>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={go} disabled={saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {saving ? 'Deleting…' : 'Delete Cycle'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Quorum shortfall, raised before a freeze. A warning rather than a block — the document
    sets no threshold, so HR is the one who decides whether a thin result is still worth
    freezing. What the browser confirm could not do is offer the remedy it described:
    re-opening the cycle to extend the window is a button here, not a sentence. Mounted only
    while a shortfall is pending, so it seeds from that report and needs no reset. */
const QuorumConfirmModal = ({ report, onClose, onExtend, onConfirm }) => {
  const [saving, setSaving] = useState('');   // '' | 'reopen' | 'freeze'
  const [err, setErr] = useState('');

  const rows = report.rows || [];
  const floor = report.minResponses || 3;
  // Two thresholds sit behind one warning. Below `quorum` a score is still computed, just
  // thin; below the anonymity floor the server computes nothing at all, so "freeze anyway"
  // leaves those leaders with no number rather than a weak one. Worth saying apart.
  const noScore = rows.filter((r) => (r.responses || 0) < floor).length;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  // Both actions belong to the caller and either may throw. A failure is reported in here
  // rather than behind the overlay, so the dialog stays put and the choice can be retried.
  const run = (kind, fn, fallback) => async () => {
    setSaving(kind);
    setErr('');
    try {
      await fn(report);
    } catch (e) {
      setErr(errText(e, fallback));
      setSaving('');
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)] shrink-0">
              <AlertTriangle size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Quorum not met</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">
                {report.label || report.cycle}
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            <b className="text-[var(--text-main)]">
              {rows.length} of {report.subjects || rows.length} leader{(report.subjects || rows.length) === 1 ? '' : 's'}
            </b>{' '}
            {rows.length === 1 ? 'is' : 'are'} under this cycle&rsquo;s quorum of {report.quorum} responses.
          </p>

          <div className="rounded-xl border border-[var(--border)] overflow-hidden max-h-56 overflow-y-auto">
            {rows.map((r, i) => {
              const thin = (r.responses || 0) < floor;
              return (
                <div key={r.subject_id || `${r.subject_name}-${i}`}
                  className="flex items-center justify-between gap-3 bg-[var(--input-bg)] px-3.5 py-2.5 border-b border-[var(--border)] last:border-0">
                  <div className="min-w-0">
                    <span className="block text-[13px] font-bold truncate">{r.subject_name}</span>
                    <span className="block text-[10.5px] font-semibold text-[var(--text-muted)] tabular-nums">
                      {r.responses} of {r.panel_size} panel member{r.panel_size === 1 ? '' : 's'} replied
                    </span>
                  </div>
                  <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full border whitespace-nowrap"
                    style={thin
                      ? { color: 'var(--accent-red)', background: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }
                      : { color: 'var(--accent-yellow)', background: 'var(--accent-yellow-bg)', borderColor: 'var(--accent-yellow-border)' }}>
                    {thin ? 'no score' : `${r.short_by ?? Math.max(0, report.quorum - r.responses)} more needed`}
                  </span>
                </div>
              );
            })}
          </div>

          {noScore > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>
                <b>{noScore}</b> of them {noScore === 1 ? 'is' : 'are'} also below the {floor}-response
                anonymity floor, so freezing leaves {noScore === 1 ? 'that leader' : 'them'} with no
                score at all &mdash; not a thin one.
              </span>
            </div>
          )}

          <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
            Re-open the cycle to extend the window and chase the missing responses, or freeze
            these scores as they stand. A freeze can still be undone until you publish.
          </p>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={!!saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          {/* Moving the Close date is what re-opens a cycle now: the status follows the
              window, so pushing the deadline back puts this cycle straight back into
              `open` and its links live again. */}
          <button type="button" onClick={onExtend} disabled={!!saving}
            title="Push the Close date back so the missing panel members can still reply"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <CalendarClock size={14} /> Extend the window
          </button>
          <button type="button" onClick={run('freeze', onConfirm, 'Could not compute this cycle.')} disabled={!!saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving === 'freeze' ? <RefreshCw size={14} className="animate-spin" /> : <Calculator size={14} />}
            {saving === 'freeze' ? 'Freezing…' : 'Freeze Anyway'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Named rather than counted. "3 leaders are missing a panel" sends HR hunting; the names
    are what they act on, and the list is short by construction. */
const BlockedNames = ({ title, rows, render }) => !rows.length ? null : (
  <div className="space-y-1.5">
    <span className="block text-[10.5px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
      {title}
    </span>
    <div className="rounded-xl border border-[var(--border)] overflow-hidden max-h-40 overflow-y-auto">
      {rows.map((r) => (
        <div key={r.subject_id}
          className="flex items-center justify-between gap-3 bg-[var(--input-bg)] px-3.5 py-2 border-b border-[var(--border)] last:border-0">
          <span className="text-[12.5px] font-bold truncate">{r.subject_name}</span>
          <span className="shrink-0 text-[10.5px] font-semibold text-[var(--text-muted)] tabular-nums">
            {render(r)}
          </span>
        </div>
      ))}
    </div>
  </div>
);

/** Why a draft cycle cannot be opened yet.
    A greyed-out button would be a dead end here: enrolment and dispatch both happen on the
    Leaders screen, which is not visible from this page, so the reason has to name the step
    and offer the way to it. The three steps are the module's actual order of work, shown as
    a checklist so it is obvious which one is outstanding rather than only that something is.
    Mounted only while a row is blocked, so it seeds from that row's readiness report. */
/** A datetime-local input wants the viewer's OWN wall clock, so the stored UTC instant is
    converted rather than sliced — `toISOString().slice(0,16)` would show UTC and silently
    shift every date HR looked at. */
const toLocalInput = (value) => {
  const d = parseUtc(value);
  if (!d) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    + `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** Change when a cycle collects.
 *
 *  This is the only control over draft/open/closed. Moving the Open date earlier starts a
 *  cycle; moving the Close date later extends one, which is what Re-open used to do for a
 *  quorum shortfall. Nothing else about the cycle is editable here — degree, quorum and
 *  weightages freeze once collection starts, and this dialog must not look like a way
 *  around that. The server refuses both dates outright once a cycle is computed or
 *  published, so a frozen cycle can never be made collectible again. */
const RescheduleModal = ({ row, onClose, onSaved }) => {
  const [opensAt, setOpensAt] = useState(toLocalInput(row?.opens_at));
  const [closesAt, setClosesAt] = useState(toLocalInput(row?.closes_at));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const bad = opensAt && closesAt && new Date(closesAt) <= new Date(opensAt);

  const save = async () => {
    if (bad) return;
    setSaving(true);
    setErr('');
    try {
      await onSaved({
        opens_at: opensAt ? new Date(opensAt).toISOString() : null,
        closes_at: closesAt ? new Date(closesAt).toISOString() : null,
      });
    } catch (e) {
      setErr(errText(e, 'Could not change these dates.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
            <CalendarClock size={16} />
          </span>
          <div className="min-w-0">
            <h3 className="text-[15px] font-extrabold tracking-tight">Feedback window</h3>
            <span className="block text-[10.5px] font-bold text-[var(--text-muted)]">
              {row?.label || row?.cycle} · the cycle opens and closes on these dates
            </span>
          </div>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="flex flex-col gap-1.5">
              <span className={labelCls}>Opens</span>
              <input type="datetime-local" value={opensAt} disabled={saving}
                onChange={(e) => setOpensAt(e.target.value)} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={labelCls}>Closes</span>
              <input type="datetime-local" value={closesAt} disabled={saving} min={opensAt || undefined}
                onChange={(e) => setClosesAt(e.target.value)} className={inputCls} />
            </label>
          </div>

          <p className="text-[11.5px] font-semibold text-[var(--text-muted)]">
            The cycle becomes <b>open</b> on the first date and <b>closed</b> on the second,
            on its own. Leaving one empty falls back to the cycle&rsquo;s own two calendar
            months. These are the same dates the invitation quotes and the feedback form
            enforces.
          </p>

          {bad && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} /> The close date is not after the open date, so the
              window would never be open.
            </div>
          )}
          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={save} disabled={saving || bad}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <CalendarClock size={14} />}
            {saving ? 'Saving…' : 'Save dates'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const PublishConfirmModal = ({ row, onClose, onConfirm }) => {
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const leaders = row.subject_count || 0;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  const go = async () => {
    setSaving(true);
    setErr('');
    try {
      await onConfirm(row);
    } catch (e) {
      setErr(errText(e, 'Could not publish this cycle.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-green-bg)] text-[var(--accent-green)] shrink-0">
              <Send size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Publish these scores?</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">
                {row.label || row.cycle}
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            Each of <b className="text-[var(--text-main)]">{leaders} leader{leaders === 1 ? '' : 's'}</b> and
            their reporting manager is notified, and the score becomes visible on the leader&rsquo;s
            own Leadership Report.
          </p>

          <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
            <AlertTriangle size={14} className="mt-[1px] shrink-0" />
            <span>
              A published cycle <b>cannot be re-opened</b>. Once people have been shown a
              number, changing the inputs behind it would rewrite a conversation that has
              already happened. Un-compute first if anything still needs checking.
            </span>
          </div>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Not yet
          </button>
          <button type="button" onClick={go} disabled={saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-green)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
            {saving ? 'Publishing…' : 'Publish & Notify'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** A cycle's documents — upload, open, remove — without leaving the cycle list.
    Files belong to the cycle they were gathered for (a rubric, a signed-off sheet, an
    approval note), so they live on the row rather than on a page of their own where the
    first job would be choosing which cycle you meant again. Mounted only while a row is
    open, so it seeds from that cycle and needs no reset. */
const DocumentsModal = ({ companyId, row, onClose }) => {
  const [file, setFile] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(
    async () => (await getLeadershipDocuments(companyId, row.cycle)).data, [companyId, row.cycle]);
  const { data, loading, reload } = useAsync(load, [companyId, row.cycle]);
  const documents = data?.documents || [];

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const upload = async () => {
    if (!file) { setErr('Choose a file first.'); return; }
    setBusy('upload');
    setErr('');
    try {
      await uploadLeadershipDocument(companyId, file, { cycle: row.cycle, note });
      setFile(null);
      setNote('');
      // The native input keeps its own value and would still show the last filename.
      const input = document.getElementById('ls-cycle-doc');
      if (input) input.value = '';
      await reload();
    } catch (e) {
      setErr(errText(e, 'Could not upload that file.'));
    } finally { setBusy(''); }
  };

  const remove = async (doc) => {
    setBusy(doc.id);
    setErr('');
    try {
      await deleteLeadershipDocument(companyId, doc.id);
      await reload();
    } catch (e) {
      setErr(errText(e, 'Could not delete that document.'));
    } finally { setBusy(''); }
  };

  const prettySize = (bytes) => {
    if (!bytes && bytes !== 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[88vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <FolderOpen size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Documents</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">
                {row.label || row.cycle}
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!busy}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3.5 overflow-y-auto">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3 space-y-2.5">
            <input id="ls-cycle-doc" type="file" disabled={!!busy}
              onChange={(e) => { setFile(e.target.files?.[0] || null); setErr(''); }}
              className="w-full text-[12px] font-semibold file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-[var(--accent-indigo-bg)] file:text-[var(--accent-indigo)] file:font-bold" />
            <input value={note} disabled={!!busy} onChange={(e) => setNote(e.target.value)}
              placeholder="What is this file? (optional)" className={inputCls} />
            <div className="flex justify-end">
              <button type="button" onClick={upload} disabled={!!busy || !file}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
                {busy === 'upload' ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
                {busy === 'upload' ? 'Uploading…' : 'Upload'}
              </button>
            </div>
          </div>

          {loading ? (
            <p className="text-[12.5px] font-bold text-[var(--text-muted)] text-center py-6">
              Loading documents…
            </p>
          ) : documents.length === 0 ? (
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)] text-center py-6">
              Nothing stored against this cycle yet.
            </p>
          ) : (
            <div className="rounded-xl border border-[var(--border)] overflow-hidden">
              {documents.map((d) => (
                <div key={d.id}
                  className="flex items-center justify-between gap-3 px-3.5 py-2.5 border-b border-[var(--border)] last:border-0">
                  <div className="min-w-0">
                    <span className="block text-[12.5px] font-bold truncate">{d.name}</span>
                    <span className="block text-[10.5px] font-semibold text-[var(--text-muted)] truncate">
                      {[prettySize(d.size), d.uploaded_by, d.note].filter(Boolean).join(' · ')}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {/* `noreferrer` because the URL is signed and must not travel in a
                        Referer header to whatever the file links on to. */}
                    <a href={d.url} target="_blank" rel="noreferrer" title="Open or download"
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                      <ExternalLink size={12} />
                    </a>
                    <button type="button" onClick={() => remove(d)} disabled={!!busy}
                      title="Delete this document"
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                      {busy === d.id ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end px-5 py-4 border-t border-[var(--border)] shrink-0">
          <button type="button" onClick={onClose} disabled={!!busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Done
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const LeadershipCycles = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  const manage = canManage(user);
  // This page is mounted on BOTH panels — /tpms/admin/leadership for internal staff and
  // /tpms/smops/leadership/cycles for HR and the client admin — so "Leaders →" must stay on
  // whichever panel the visitor is already in. Hardcoding /tpms/admin sent a client-side user
  // into a route guarded by `RequireTpms admin`, which bounced them to their dashboard.
  const panelBase = useLocation().pathname.startsWith('/tpms/admin') ? '/tpms/admin' : '/tpms/smops';
  const [adding, setAdding] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [quorumWarn, setQuorumWarn] = useState(null);
  const [rescheduling, setRescheduling] = useState(null);
  const [pendingPublish, setPendingPublish] = useState(null);
  const [docsFor, setDocsFor] = useState(null);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');

  const waiting = staff && !companyId;

  const cfg = useAsync(async () => (await getLeadershipConfig()).data, [], { skip: !manage });
  const load = useMemo(
    () => async () => (await getLeadershipCycles(companyId)).data,
    [companyId],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId],
    { skip: waiting || !manage });

  const cycles = data?.cycles || [];

  const create = async (payload) => {
    await createLeadershipCycle(companyId, payload);
    setAdding(false);
    setNotice(`Cycle opened. Enrol leaders next.`);
    await reload();
  };

  const setStatus = async (cycle, status) => {
    setBusy(cycle);
    setError('');
    setNotice('');
    try {
      await updateLeadershipCycle(companyId, cycle, { status });
      setNotice({
        open: 'Cycle is open — feedback links can be sent.',
        closed: 'Window closed. No further feedback is accepted; compute when you are ready.',
      }[status] || 'Cycle updated.');
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not update the cycle.'));
    } finally {
      setBusy('');
    }
  };

  // Delete a cycle opened by mistake. The server refuses once any feedback exists, or
  // once the cycle is published, so the dialog is about intent rather than safety — the
  // panel links it invalidates are the part worth naming before it happens. Failures are
  // left to throw: ConfirmDeleteModal reports them without dismissing itself.
  const removeCycle = async (row) => {
    setBusy(row.cycle);
    setError('');
    setNotice('');
    try {
      const res = await deleteLeadershipCycle(companyId, row.cycle);
      const r = res.data?.removed || {};
      setNotice(`${res.data?.label || row.cycle} deleted`
        + (r.subjects || r.links
          ? ` — ${r.subjects || 0} leader(s) and ${r.links || 0} feedback link(s) removed.`
          : '.'));
      setPendingDelete(null);
      await reload();
    } finally {
      setBusy('');
    }
  };

  // Freeze the scores. Refused until every level this cycle scores has been signed off by
  // HR + MD — a frozen number is what a leader is shown and a manager discusses at RRO, so
  // it must not come from a rubric nobody has approved.
  //
  // Quorum is a warning, not a block: the document sets no threshold, so HR decides
  // whether a thin result is still worth freezing. They just should not do it unknowingly,
  // which is why a shortfall opens QuorumConfirmModal instead of freezing straight away.
  const compute = async (row) => {
    setBusy(row.cycle); setError(''); setNotice('');
    try {
      const q = await getLeadershipQuorum(companyId, row.cycle);
      const short = q.data?.below_quorum || [];
      if (short.length) {
        setQuorumWarn({
          cycle: row.cycle,
          label: row.label,
          quorum: q.data?.quorum,
          subjects: q.data?.subjects,
          // The quorum and the anonymity floor say different things about what a freeze
          // produces, so both travel with the report. Preferred over the row's stored
          // value, which the degree may have capped: a 180° cycle holding 6 collects
          // from four people and is scored against 4.
          minResponses: q.data?.min_responses || row.min_responses,
          rows: short,
        });
        return;
      }
      await freeze(row.cycle);
    } catch (e) {
      setError(errText(e, 'Could not compute this cycle.'));
    } finally { setBusy(''); }
  };

  // The freeze itself, split out so QuorumConfirmModal can invoke it after HR has seen who
  // is short. Left to throw: the modal reports the failure without dismissing itself.
  const freeze = async (cycle) => {
    await computeLeadershipCycle(companyId, cycle);
    setQuorumWarn(null);
    setNotice('Scores frozen. Review them, then publish to release them to leaders.');
    await reload();
  };

  // The other way out of a quorum shortfall — extend the window rather than freeze a thin
  // result. Same transition as the Re-open button on a closed row, offered where the
  // shortfall is actually being read.
  // The moment a leader can first see their own score. Irreversible for collection: once
  // people have been shown a number, changing the inputs behind it would rewrite a
  // conversation that has already happened.
  // Left to throw: PublishConfirmModal reports the failure in place rather than dismissing
  // itself, so a cycle that could not be released does not look released.
  const publish = async (row) => {
    setBusy(row.cycle); setError(''); setNotice('');
    try {
      await publishLeadershipCycle(companyId, row.cycle);
      setPendingPublish(null);
      setNotice('Published. Leaders and their managers have been notified.');
      await reload();
    } finally { setBusy(''); }
  };

  if (!manage) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">HR and administrators only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Leadership Score cycles are managed by HR. If you have received feedback, your own
          result is on the Leadership Report page.
        </p>
      </div>
    );
  }

  const open = cycles.filter((c) => c.status === 'open').length;
  // Closed cycles whose scores are frozen. Surfaced as a count, not as a fifth status.
  const ready = cycles.filter((c) => isScoreReady(c.status)).length;
  const leaders = cycles.reduce((s, c) => s + (c.subject_count || 0), 0);
  const responses = cycles.reduce((s, c) => s + (c.response_count || 0), 0);

  return (
    <div className="space-y-5">
      <DashboardHero icon={CalendarRange} title="Leadership Score — Cycles"
        subtitle="Two-month assessment windows for anonymous leadership feedback">
        {staff && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />}
        <HeroButton icon={Plus} onClick={() => setAdding(true)}>Open Cycle</HeroButton>
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {notice}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <KpiTile value={cycles.length} label="Cycles" sub="All time" tone="blue" icon={Layers} />
        <KpiTile value={open} label="Open" sub="Collecting feedback" tone={open ? 'green' : 'plain'} icon={Unlock} />
        <KpiTile value={ready} label="Ready to publish" sub="Closed, scores calculated"
          tone={ready ? 'indigo' : 'plain'} icon={Calculator} />
        <KpiTile value={leaders} label="Leaders" sub="Enrolled across cycles" tone="blue" icon={Users} />
        <KpiTile value={responses} label="Responses" sub="Feedback received" tone={responses ? 'green' : 'plain'} icon={CheckCircle2} />
      </div>

      <Section title="Assessment Cycles" icon={CalendarRange}
        subtitle={waiting ? 'Select a company' : `${cycles.length} cycle${cycles.length === 1 ? '' : 's'}`}>
        {waiting ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to manage its cycles.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading cycles…
          </div>
        ) : cycles.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <CalendarRange size={20} />
            </span>
            <p className="text-[13px] font-bold">No cycles yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-sm">
              Open a two-month cycle, enrol the leaders (L4 and above), then assign each of
              them a panel of feedback givers.
            </p>
          </div>
        ) : (
          <TableShell minWidth={940}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Cycle</Th><Th align="center">Degree</Th><Th align="center">Min. responses</Th>
                <Th align="center">Leaders</Th><Th align="center">Responses</Th>
                <Th align="center">Status</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((c) => (
                <tr key={c.cycle} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td>
                    <span className="font-bold">{c.label}</span>
                    <span className="block text-[10.5px] text-[var(--text-muted)] font-mono">{c.cycle}</span>
                    {/* Only shown when HR set one. An empty window is not a gap — it means
                        the cycle's own calendar months apply, which is what the code label
                        above already says. */}
                    {(c.opens_at || c.closes_at) && (
                      <span className="block text-[10.5px] font-semibold text-[var(--text-muted)] mt-0.5">
                        {windowLabel(c)}
                      </span>
                    )}
                  </Td>
                  <Td align="center" className="font-bold tabular-nums">{c.degree}°</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtNum(c.min_responses)}</Td>
                  <Td align="center" className="tabular-nums font-bold">{c.subject_count ?? 0}</Td>
                  <Td align="center" className="tabular-nums font-bold">{c.response_count ?? 0}</Td>
                  {/* `computed` is not a user-facing state — it reads as Closed, and the
                      action column is what says the scores are ready to release. */}
                  <Td align="center" title={cycleHint(c.status)}>
                    <Pill label={cycleLabel(c.status)} tone={c.status} />
                    {isScoreReady(c.status) && (
                      <span className="block text-[9.5px] font-bold text-[var(--accent-indigo)] mt-1 whitespace-nowrap">
                        scores ready
                      </span>
                    )}
                  </Td>
                  <Td align="right">
                    <div className="inline-flex items-center gap-1.5 justify-end flex-wrap">
                      <Link to={`${panelBase}/leadership/subjects?cycle=${c.cycle}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        Leaders <ArrowRight size={12} />
                      </Link>
                      {/* Files belong to the cycle they were gathered for, so they hang off
                          the row rather than a page whose first job would be asking which
                          cycle you meant. Available at every status — a rubric goes up
                          before collection, a signed-off sheet long after. */}
                      <button type="button" onClick={() => setDocsFor(c)}
                        title="Documents for this cycle"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors">
                        <FolderOpen size={12} />
                      </button>
                      {/* draft / open / closed are the CLOCK's, not HR's — there is
                          deliberately no Open, Close or Re-open control any more. A cycle
                          moves when its own Open and Close dates say so, and the remedy
                          for every case those buttons used to serve (start early, stop
                          early, extend for a late responder) is to edit those dates. The
                          row shows the date it is waiting on so the state is never a
                          mystery. */}
                      {c.status === 'draft' && (
                        <button type="button" onClick={() => setRescheduling(c)} disabled={busy === c.cycle}
                          title={c.can_open === false
                            ? (c.open_blocked_reason || 'Enrol leaders and send their invitations before it opens')
                            : 'Opens automatically on its Open date — edit the dates to change when'}
                          className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold border hover:opacity-90 transition-opacity disabled:opacity-50 ${
                            c.can_open === false
                              ? 'text-[var(--accent-yellow)] bg-[var(--accent-yellow-bg)] border-[var(--accent-yellow-border)]'
                              : 'text-[var(--text-muted)] border-[var(--border)]'}`}>
                          {c.can_open === false ? <Lock size={12} /> : <CalendarClock size={12} />}
                          {c.can_open === false ? 'Set-up incomplete' : 'Opens on schedule'}
                        </button>
                      )}
                      {c.status === 'open' && (
                        <button type="button" onClick={() => setRescheduling(c)} disabled={busy === c.cycle}
                          title="Closes automatically on its Close date — edit the dates to change when"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                          <CalendarClock size={12} /> Closes on schedule
                        </button>
                      )}
                      {/* closed → computed → published. Splitting these is what stops a
                          leader watching their own score move during collection. Both are
                          still HR's decision — only the collection window went automatic. */}
                      {c.status === 'closed' && (
                        <button type="button" onClick={() => compute(c)} disabled={busy === c.cycle}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                          <Calculator size={12} /> Compute
                        </button>
                      )}
                      {c.status === 'computed' && (
                        <>
                          {/* Back to closed. The backend has always allowed this, but no
                              control offered it — so a cycle computed too early could only
                              go forward to Publish, which is terminal. */}
                          <button type="button" onClick={() => setStatus(c.cycle, 'closed')} disabled={busy === c.cycle}
                            title="Undo the freeze — reopen collection or recompute before releasing"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                            <Undo2 size={12} /> Un-compute
                          </button>
                          <button type="button" onClick={() => setPendingPublish(c)} disabled={busy === c.cycle}
                            title="Release the scores to leaders and their reporting managers. This cannot be undone."
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                            <Send size={12} /> Publish
                          </button>
                        </>
                      )}
                      {/* Offered only while it can actually succeed: the server refuses a
                          cycle holding feedback or one already published, and a button
                          that always errors is worse than no button. */}
                      {!c.response_count && c.status !== 'published' && (
                        <button type="button" onClick={() => setPendingDelete(c)} disabled={busy === c.cycle}
                          title="Delete this cycle and anything set up under it"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      <AnimatePresence>
        {adding && (
          <CycleModal key="add-cycle" config={cfg.data} existing={cycles}
            onClose={() => setAdding(false)} onSubmit={create} />
        )}
        {pendingDelete && (
          <ConfirmDeleteModal key="delete-cycle" row={pendingDelete}
            onClose={() => setPendingDelete(null)} onConfirm={removeCycle} />
        )}
        {quorumWarn && (
          <QuorumConfirmModal key="quorum-warning" report={quorumWarn}
            onClose={() => setQuorumWarn(null)}
            onExtend={() => { const c = cycles.find((x) => x.cycle === quorumWarn.cycle);
              setQuorumWarn(null); setRescheduling(c || { cycle: quorumWarn.cycle }); }}
            onConfirm={({ cycle }) => freeze(cycle)} />
        )}
        {rescheduling && (
          <RescheduleModal key={`reschedule-${rescheduling.cycle}`} row={rescheduling}
            onClose={() => setRescheduling(null)}
            onSaved={async (dates) => {
              await updateLeadershipCycle(companyId, rescheduling.cycle, dates);
              setRescheduling(null);
              setNotice('Window updated. The cycle will open and close on these dates.');
              await reload();
            }} />
        )}
        {pendingPublish && (
          <PublishConfirmModal key="publish-cycle" row={pendingPublish}
            onClose={() => setPendingPublish(null)} onConfirm={publish} />
        )}
        {docsFor && (
          <DocumentsModal key={`docs-${docsFor.cycle}`} companyId={companyId} row={docsFor}
            onClose={() => setDocsFor(null)} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipCycles;
