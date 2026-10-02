import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Gauge, RefreshCw, SlidersHorizontal, Users, Target, TrendingUp,
  AlertTriangle, ChevronDown, Percent, Info, Calculator,
  Clock, Upload, Download, X,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
  KpiTile, usePaged, Pager,
} from '../../features/tpms/common/dashboardKit';
import {
  getIrmScores, recalculateIrm, saveKpiScore,
  importIrmAttendance, exportIrmAttendance, getIrmAttendanceTemplate,
} from '../../services/irmApi';
import {
  canEditWeightages, canRecalculate, currentPeriod, errText, fmtNum, fmtPct, periodLabel,
  periodOptions, scoreColor, scoreTone, useAsync, useIrmCompany,
} from './irmUtils';

/* ─────────────────────────────────────────────────────────────
   IRM ▸ scoreboard.

   One row per person, one column per evaluation parameter. Every cell shows the
   achievement % AND what it contributed after weighting, because the whole point of
   the sheet is that those two numbers are different:

       Weighted Score = (Achievement % × Weightage) ÷ 100

   Expanding a row spells the arithmetic out per parameter. Nothing is computed here —
   the backend returns achievement, weightage, weighted_score and final_irm already
   derived from the company's saved weightages, so this page and the API can never
   disagree about a score.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

/** Achievement % as a bar + value. Muted and dashed when the parameter had no data. */
const AchievementBar = ({ value, hasData }) => {
  if (!hasData) {
    return <span className="text-[11.5px] font-bold text-[var(--text-muted)]">No data</span>;
  }
  const c = scoreColor(value);
  return (
    <div className="flex items-center gap-2 min-w-[104px]">
      <div className="h-1.5 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: c }} />
      </div>
      <span className="text-[11.5px] font-bold tabular-nums w-[52px] text-right" style={{ color: c }}>
        {fmtPct(value)}
      </span>
    </div>
  );
};

/** "20 / 25" — what the parameter contributed out of what it could have. */
const WeightedCell = ({ p }) => (
  <span className="text-[11px] font-bold tabular-nums text-[var(--text-muted)]">
    {p.has_data ? fmtNum(p.weighted_score) : '0'}
    <span className="opacity-60"> / {fmtNum(p.max_score)}</span>
  </span>
);

/** The final IRM, out of 100. */
const FinalScore = ({ value, hasData }) => {
  const c = hasData ? scoreColor(value) : 'var(--text-muted)';
  return (
    <span className="inline-flex items-baseline gap-1 justify-end">
      <span className="text-[16px] font-extrabold tabular-nums" style={{ color: c }}>
        {hasData ? fmtNum(value) : '—'}
      </span>
      {hasData && <span className="text-[10px] font-bold text-[var(--text-muted)]">/ 100</span>}
    </span>
  );
};

/** The expanded row — the calculation, parameter by parameter. */
/**
 * The achievement box on a custom KPI.
 *
 * Every other parameter is read from data the ERP already holds, so its cell is a readout. A
 * custom KPI has no such source: the number is reported by the person being scored, which is
 * the only place in IRM where the subject of a score writes to it. Their WEIGHTAGE stays
 * admin-only — what a KPI is worth is not theirs to set, only what they did against it.
 */
const KpiScoreEntry = ({ companyId, personId, period, param, canEdit, onSaved }) => {
  const [value, setValue] = useState(param.achievement == null ? '' : String(param.achievement));
  const [note, setNote] = useState(param.note || '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const dirty = String(param.achievement ?? '') !== value.trim() || (param.note || '') !== note;

  const save = async () => {
    const num = Number(value);
    if (value.trim() === '' || Number.isNaN(num) || num < 0 || num > 100) {
      setErr('Enter a number from 0 to 100.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      await saveKpiScore(companyId, personId, param.code, period, num, note);
      onSaved?.();
    } catch (e) {
      setErr(errText(e, 'Could not save that score.'));
    } finally {
      setSaving(false);
    }
  };

  if (!canEdit) {
    return (
      <p className="mt-2 text-[11px] text-[var(--text-muted)]">
        {param.achievement == null
          ? 'Waiting to be filled in by this person.'
          : `Filled in by ${param.filed_by || 'them'}.`}
        {param.note ? ` "${param.note}"` : ''}
      </p>
    );
  }

  return (
    <div className="mt-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <input type="number" min={0} max={100} step={1} value={value} disabled={saving}
          onChange={(e) => setValue(e.target.value)} placeholder="0-100"
          aria-label={`${param.name} achievement percent`}
          className="w-20 px-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-bold text-right tabular-nums outline-none focus:border-[var(--accent-indigo)]" />
        <span className="text-[11px] font-bold text-[var(--text-muted)]">%</span>
        <input type="text" value={note} disabled={saving} maxLength={300}
          onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)"
          aria-label={`${param.name} note`}
          className="flex-1 min-w-0 px-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[11.5px] font-semibold outline-none focus:border-[var(--accent-indigo)]" />
        <button type="button" onClick={save} disabled={saving || !dirty}
          className="shrink-0 px-2.5 py-1.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold disabled:opacity-40 transition-opacity">
          {saving ? '…' : 'Save'}
        </button>
      </div>
      {err && <p className="text-[10.5px] font-bold text-[var(--accent-red)]">{err}</p>}
      {!err && param.filed_by && (
        <p className="text-[10.5px] text-[var(--text-muted)]">Last filled by {param.filed_by}.</p>
      )}
    </div>
  );
};

const Breakdown = ({ row, columns, companyId, period, canFillFor, onScoreSaved }) => (
  <div className="px-4 py-4 bg-[var(--input-bg)]/40 border-t border-[var(--border)]">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {row.parameters.map((p) => (
        <div key={p.code}
          className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-extrabold tracking-tight">{p.name}</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {fmtNum(p.weightage)}%
            </span>
          </div>

          <dl className="mt-2.5 space-y-1 text-[11.5px]">
            {/* TASKS FIRST, AS A HEADCOUNT. `achieved`/`assigned` are sums of per-task
                WEIGHTS (irm_weight), not tasks: one task set to weight 5 makes three tasks
                read as "6 / 7". That line was labelled "Achieved / Assigned", so a person
                with 3 delegated tasks saw 7 and had no way to reconcile it. The real count
                leads now, and the weighted pair is shown underneath, named for what it is —
                and only when the weights actually differ from 1 (`p.weighted`). */}
            {p.source === 'task' && (
              <div className="flex items-center justify-between gap-2">
                <dt className="text-[var(--text-muted)]">Tasks</dt>
                <dd className="font-bold tabular-nums">
                  {fmtNum(p.completed, '0')} / {fmtNum(p.count, '0')}
                  {p.partial > 0 && (
                    <span className="text-[10px] font-medium text-[var(--text-muted)]">
                      {' '}(+{p.partial} part-done)
                    </span>
                  )}
                </dd>
              </div>
            )}
            {(p.source !== 'task' || p.weighted) && (
              <div className="flex items-center justify-between gap-2">
                {/* Name the pair for what it actually counts. "Weighted credit" is true of the
                    task parameters, where `achieved` is a sum of per-task weights — but on
                    attendance it is days, and on a rating form it is points. */}
                <dt className="text-[var(--text-muted)]">
                  {p.source === 'form' ? 'Rating points'
                    : p.source === 'attendance' ? 'Punctual days'
                    : p.source === 'manual' ? 'Reported'
                    : 'Weighted credit'}
                </dt>
                <dd className="font-bold tabular-nums">
                  {fmtNum(p.achieved, '0')} / {fmtNum(p.assigned, '0')}
                  {p.source === 'form' && p.ratings > 0 && (
                    <span className="text-[10px] font-medium text-[var(--text-muted)]">
                      {' '}({p.ratings} × {p.scale_max})
                    </span>
                  )}
                </dd>
              </div>
            )}
            {/* Why the rest of the days were not punctual. Without it "4 / 7" states a
                shortfall and explains nothing, and the three counts are already on the payload. */}
            {p.source === 'attendance' && p.assigned > 0 && p.achieved < p.assigned && (
              <div className="flex items-center justify-between gap-2">
                <dt className="text-[var(--text-muted)]">Missed on</dt>
                <dd className="font-bold tabular-nums text-right">
                  {[
                    p.late_in ? `${p.late_in} late in` : null,
                    p.early_out ? `${p.early_out} early out` : null,
                    p.missing_out ? `${p.missing_out} no out punch` : null,
                  ].filter(Boolean).join(', ')}
                </dd>
              </div>
            )}
            <div className="flex items-center justify-between gap-2">
              <dt className="text-[var(--text-muted)]">Achievement %</dt>
              <dd className="font-bold tabular-nums" style={{ color: scoreColor(p.achievement) }}>
                {fmtPct(p.achievement, p.source === 'manual' ? 'Not filled in' : 'No data')}
              </dd>
            </div>
          </dl>

          {p.source === 'manual' && (
            <KpiScoreEntry
              companyId={companyId}
              personId={row.person_id}
              period={period}
              param={p}
              canEdit={canFillFor?.(row.person_id)}
              onSaved={onScoreSaved}
            />
          )}

          {/* The formula, with this person's numbers substituted in. */}
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)]">
            <p className="text-[10.5px] font-mono text-[var(--text-muted)] leading-relaxed break-words">
              {p.has_data
                ? `(${fmtNum(p.achievement)} × ${fmtNum(p.weightage)}) ÷ 100`
                : 'no data → contributes 0'}
            </p>
            <p className="text-[13px] font-extrabold tabular-nums mt-1">
              = {fmtNum(p.weighted_score)}
              <span className="text-[10.5px] font-bold text-[var(--text-muted)]"> of {fmtNum(p.max_score)}</span>
            </p>
          </div>
        </div>
      ))}
    </div>

    {/* The sum, written out. */}
    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
      <Calculator size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[11.5px] font-bold text-[var(--text-muted)]">Final IRM =</span>
      <span className="text-[11.5px] font-mono tabular-nums">
        {row.parameters.map((p) => fmtNum(p.weighted_score)).join(' + ')}
      </span>
      <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(row.final_irm) }}>
        = {fmtNum(row.final_irm)}%
      </span>
      {row.applicable_weightage < row.total_weightage && row.has_data && (
        <span className="text-[10.5px] font-bold text-[var(--text-muted)] w-full sm:w-auto">
          · only {fmtNum(row.applicable_weightage)}% of the weightage had data
          {row.final_irm_applicable !== null && (
            <> — {fmtNum(row.final_irm_applicable)}% on what was scored</>
          )}
        </span>
      )}
    </div>

    {/* Column key for the collapsed row, so the header abbreviations stay readable. */}
    <p className="mt-2 text-[10.5px] text-[var(--text-muted)]">
      {columns.map((c) => `${c.name} ${fmtNum(c.weightage)}%`).join(' · ')}
    </p>
  </div>
);

/** Import punch times, then say exactly what landed.
    A bulk load that half-worked is the worst outcome, so unmatched identifiers are named
    rather than counted — a file whose employee codes are wrong has to fail visibly, not
    score the wrong people. */
const AttendanceModal = ({ companyId, period, onClose, onImported }) => {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [result, setResult] = useState(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const doImport = async () => {
    if (!file) { setErr('Choose a file first.'); return; }
    setBusy('import'); setErr(''); setResult(null);
    try {
      const res = await importIrmAttendance(companyId, file);
      setResult(res.data);
      onImported?.();
    } catch (e) {
      setErr(errText(e, 'Could not import that file.'));
    } finally { setBusy(''); }
  };

  // The blob is turned into a click here rather than a plain link: the request needs the
  // auth header the axios instance carries, which an <a href> would not send.
  const download = async (kind, request, filename, failure) => {
    setBusy(kind); setErr('');
    try {
      const res = await request();
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(errText(e, failure));
    } finally { setBusy(''); }
  };

  const doTemplate = () => download(
    'template',
    () => getIrmAttendanceTemplate(companyId),
    'irm-attendance-template.xlsx',
    'Could not download the template.',
  );

  const doExport = () => download(
    'export',
    () => exportIrmAttendance(companyId, period),
    `irm-attendance-${period || 'all'}.xlsx`,
    'Could not export attendance.',
  );

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <Clock size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Attendance</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)]">
                {periodLabel(period)} · punch times feed Punctuality
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!busy}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            The file needs a <b className="text-[var(--text-main)]">Date</b> column, an{' '}
            <b className="text-[var(--text-main)]">In Time</b> column, and one of Employee ID,
            Email or Name to match people. Out Time is optional but a day without it cannot
            count as punctual. Re-importing a day replaces it.
          </p>

          {/* Offered before the file picker on purpose: the template carries the roster's
              own Employee IDs, which are exactly what the importer matches on. Starting
              from it is what stops a whole file landing in `unmatched`. */}
          <button type="button" onClick={doTemplate} disabled={!!busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[12.5px] font-bold hover:opacity-90 transition-opacity disabled:opacity-50">
            {busy === 'template' ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
            {busy === 'template' ? 'Preparing…' : 'Download template (with your roster)'}
          </button>

          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
              Attendance file (.xlsx / .csv)
            </span>
            <input type="file" accept=".xlsx,.xls,.csv" disabled={!!busy}
              onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null); setErr(''); }}
              className="w-full text-[12px] font-semibold file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-[var(--accent-indigo-bg)] file:text-[var(--accent-indigo)] file:font-bold" />
          </label>

          {result && (
            <div className="rounded-xl border border-[var(--border)] overflow-hidden">
              <div className="grid grid-cols-3 divide-x divide-[var(--border)]">
                {[
                  { label: 'New', value: result.imported, tone: 'var(--accent-green)' },
                  { label: 'Updated', value: result.updated, tone: 'var(--accent-indigo)' },
                  { label: 'Skipped', value: result.skipped, tone: 'var(--text-muted)' },
                ].map((s) => (
                  <div key={s.label} className="px-3 py-2.5 text-center bg-[var(--input-bg)]">
                    <div className="text-[17px] font-black tabular-nums" style={{ color: s.tone }}>{s.value ?? 0}</div>
                    <div className="text-[10px] font-black uppercase tracking-wide text-[var(--text-muted)]">{s.label}</div>
                  </div>
                ))}
              </div>
              {!!result.unmatched_count && (
                <div className="flex items-start gap-2 px-3.5 py-2.5 border-t border-[var(--border)] bg-[var(--accent-yellow-bg)] text-[11.5px] font-semibold text-[var(--accent-yellow)]">
                  <AlertTriangle size={14} className="mt-[1px] shrink-0" />
                  <span>
                    {result.unmatched_count} identifier{result.unmatched_count === 1 ? '' : 's'} matched
                    nobody on the roster: {(result.unmatched || []).map((u) => u.identifier).join(', ')}
                    {result.unmatched_count > (result.unmatched || []).length ? '…' : ''}
                  </span>
                </div>
              )}
            </div>
          )}

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={doExport} disabled={!!busy}
            title="Download what is stored — same columns the importer reads, so it can be corrected and re-loaded"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {busy === 'export' ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
            {busy === 'export' ? 'Exporting…' : 'Export'}
          </button>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={!!busy}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Close
            </button>
            <button type="button" onClick={doImport} disabled={!!busy || !file}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {busy === 'import' ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
              {busy === 'import' ? 'Importing…' : 'Import'}
            </button>
          </div>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};


const IRMPage = () => {
  const { user, staff, companies, companyId, setCompanyId } = useIrmCompany();
  const [period, setPeriod] = useState(currentPeriod());
  const [expanded, setExpanded] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [showAttendance, setShowAttendance] = useState(false);

  // Editing weightages is Super Admin only; refreshing the snapshot is not an edit.
  const canEdit = canEditWeightages(user);
  const canRefresh = canRecalculate(user);
  const periods = useMemo(() => periodOptions(12), []);
  const waitingForCompany = staff && !companyId;
  // A placeholder entry is how StyledSelect shows "nothing chosen yet" (see SelectField).
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  const load = useCallback(
    async () => (await getIrmScores(companyId, period)).data,
    [companyId, period],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId, period], {
    skip: waitingForCompany,
  });

  const rows = data?.rows || [];
  const columns = data?.parameters || [];
  const paged = usePaged(rows, 12);

  // Who may type a KPI achievement: the person it is about, or an administrator correcting
  // it. Deliberately the same rule the backend enforces in routes/irm.file_kpi_score — this
  // only decides whether the box is rendered, never whether the write is allowed.
  const selfId = String(user?._id || user?.id || '');
  const canFillKpi = useCallback(
    (personId) => String(personId) === selfId || canEdit,
    [selfId, canEdit],
  );

  const recalc = async () => {
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const res = await recalculateIrm(companyId, period);
      setNotice(`Snapshot refreshed for ${res.data?.recalculated ?? 0} people.`);
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not recalculate IRM.'));
    } finally {
      setBusy(false);
    }
  };

  const summary = data?.summary || {};
  const kpis = [
    { value: summary.people ?? 0, label: 'People', sub: 'On the roster', tone: 'blue', icon: Users },
    { value: summary.scored ?? 0, label: 'Scored', sub: 'With data this period', tone: summary.scored ? 'green' : 'plain', icon: Target },
    { value: fmtNum(summary.average_irm), label: 'Average IRM', sub: 'Out of 100', tone: scoreTone(summary.average_irm), icon: Gauge },
    { value: fmtNum(summary.highest), label: 'Highest IRM', sub: 'Top performer', tone: scoreTone(summary.highest), icon: TrendingUp },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={Gauge}
        title="Individual Result Matrix (IRM)"
        subtitle={`Weighted performance score per person · ${periodLabel(period)}`}
      >
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        <HeaderSelect value={period} onChange={setPeriod} options={periods} />
        {/* Attendance is the Punctuality parameter's only input, and a task is what the
            Task parameter counts — both belong beside the scoreboard they move. */}
        {canRefresh && !waitingForCompany && (
          <HeroButton icon={Clock} onClick={() => setShowAttendance(true)}>Attendance</HeroButton>
        )}
        {canRefresh && <HeroButton icon={RefreshCw} onClick={recalc}>{busy ? 'Working…' : 'Recalculate'}</HeroButton>}
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <Info size={15} /> {notice}
        </div>
      )}

      {/* The weightage column from the sheet, read-only here — editable in Setup. */}
      {columns.length > 0 && (
        <Section
          title="Weightage"
          subtitle={canEdit
            ? "Each parameter's share of the 100-point score"
            : "Each parameter's share of the 100-point score · set by your Sparsh administrator"}
          icon={Percent}
          action={canEdit && (
            <Link to="/irm/setup"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
              <SlidersHorizontal size={13} /> Edit Weightages
            </Link>
          )}
        >
          <div className="flex flex-wrap items-center gap-2.5 px-5 py-4">
            {columns.map((c) => (
              <span key={c.code}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                <span className="text-[12px] font-bold">{c.name}</span>
                <span className="text-[12px] font-extrabold tabular-nums text-[var(--accent-indigo)]">
                  {fmtNum(c.weightage)}%
                </span>
              </span>
            ))}
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border"
              style={{
                background: data?.is_valid_weightage ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                borderColor: data?.is_valid_weightage ? 'var(--accent-green-border)' : 'var(--accent-red-border)',
                color: data?.is_valid_weightage ? 'var(--accent-green)' : 'var(--accent-red)',
              }}>
              <span className="text-[11px] font-bold uppercase tracking-wide">Grand Total</span>
              <span className="text-[12px] font-extrabold tabular-nums">{fmtNum(data?.total_weightage)}%</span>
            </span>
          </div>
          {data && !data.is_valid_weightage && (
            <p className="px-5 pb-4 -mt-1 text-[11.5px] font-bold text-[var(--accent-red)]">
              Weightages total {fmtNum(data.total_weightage)}%, not 100% — scores are not out of 100
              until an administrator corrects this in Setup.
            </p>
          )}
        </Section>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <Section
        title="Individual Scores"
        subtitle={waitingForCompany ? 'Select a company' : `${rows.length} ${rows.length === 1 ? 'person' : 'people'} · ${periodLabel(period)}`}
        icon={Users}
      >
        {waitingForCompany ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to view its IRM.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Calculating IRM…
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <Users size={20} />
            </span>
            <p className="text-[13px] font-bold">No people to score</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              This company has no active members on its roster.
            </p>
          </div>
        ) : (
          <>
            <TableShell minWidth={1080}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Person</Th>
                  {columns.map((c) => (
                    <Th key={c.code}>
                      {c.name}
                      <span className="ml-1 opacity-70">({fmtNum(c.weightage)}%)</span>
                    </Th>
                  ))}
                  <Th align="right">Final IRM</Th>
                  <Th align="center"> </Th>
                </tr>
              </thead>
              <tbody>
                {paged.pageRows.map((row) => {
                  const open = expanded === row.person_id;
                  return (
                    <React.Fragment key={row.person_id}>
                      <tr
                        className="border-b border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors cursor-pointer"
                        onClick={() => setExpanded(open ? null : row.person_id)}
                      >
                        <Td>
                          <span className="font-bold">{row.name}</span>
                          {(row.designation || row.department) && (
                            <span className="block text-[10.5px] text-[var(--text-muted)]">
                              {[row.designation, row.department].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </Td>
                        {columns.map((c) => {
                          const p = row.parameters.find((x) => x.code === c.code) || {};
                          return (
                            <Td key={c.code}>
                              <AchievementBar value={p.achievement} hasData={p.has_data} />
                              <span className="block mt-1"><WeightedCell p={p} /></span>
                            </Td>
                          );
                        })}
                        <Td align="right">
                          <FinalScore value={row.final_irm} hasData={row.has_data} />
                        </Td>
                        <Td align="center">
                          <ChevronDown size={15}
                            className={`inline text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
                        </Td>
                      </tr>
                      <AnimatePresence initial={false}>
                        {open && (
                          <tr>
                            <td colSpan={columns.length + 3} className="p-0">
                              <MotionDiv
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                              >
                                <Breakdown row={row} columns={columns}
                                  companyId={companyId} period={period}
                                  canFillFor={canFillKpi} onScoreSaved={reload} />
                              </MotionDiv>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </TableShell>
            <Pager {...paged} label="people" />
          </>
        )}
      </Section>

      <AnimatePresence>
        {showAttendance && (
          <AttendanceModal key="attendance" companyId={companyId} period={period}
            onClose={() => setShowAttendance(false)}
            onImported={() => { setNotice('Attendance imported. Punctuality is recomputed on the next read.'); reload(); }} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default IRMPage;
