import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, GitBranch, CheckCircle2, CircleDashed, XCircle, Gauge, Target,
  Info, Grid3x3, MousePointerClick, AlertTriangle, Pencil, Save, Paperclip,
  Download, UserCog, Inbox, Lock,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, FilterSelect, Section, Th, Td, Progress,
  TableShell, KpiTile, usePaged, Pager,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { useNotification } from '../../../../context/NotificationContext';
import { isTpmsAdmin, canAccessTpmsClient } from '../../access';
import {
  getImplementationTracker, saveManualScore, currentPeriod, periodLabel,
} from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Implementation Tracker — per-client Success-Measure
   scorecard, manual-score entry, proof uploads and the client ×
   activity score matrix.

   Wired to /tpms/dashboards/implementation (get_implementation_tracker).
   The per-client panels (scorecard / manual scores / uploads) only
   populate when a single company is in scope, so they surface once a
   client is picked; "All Clients" shows the matrix only.

   Scoring model (server-supplied fields):
     • impl_target / impl_actual  — occurrence cadence expectation vs actual
     • score_target / score_actual — success-measure score vs target
     • achievement — Actual Score ÷ Score Target × 100
     • Status — Met ≥100% · Partial 1–99% · Not Met 0/none

   MANUAL SCORES
   -------------
   Ten catalogue activities are scored by hand rather than derived. They split
   by the scope they're entered at:
     • company-wise — one figure for the client (Org Structure, MMR, TEI, CSI, ORM)
     • HOD-wise     — one figure per HOD, which the Success-Measure sync averages
                      back onto the client's row (DRM/KPI, WRM, 1-Pager,
                      Action Closure, RRO)
   Saving posts to /tpms/manual-scores, which re-runs the sync — so the scorecard
   above refreshes with the new achievement in the same round-trip.
   ───────────────────────────────────────────────────────────── */

// Spec §7 achievement band — ≥100 Met · 50–99 Partial · <50 Not Met. Anything under half
// of target is Not Met, not a partial success. Mirrors achievement_status() in
// backend/app/models/tpms.py; keep the two in step.
const statusOf = (a) => (a >= 100 ? 'Met' : a >= 50 ? 'Partial' : 'Not Met');
const STATUS = {
  'Met':     { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Partial': { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Not Met': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};
const Pill = ({ label }) => {
  const s = STATUS[label] || STATUS['Not Met'];
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');
const pctOrDash = (v) => (v == null ? '—' : `${v}%`);

// Last 12 months as { value: 'YYYY-MM', label: 'Jul26' }.
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const label = `${d.toLocaleString('en-US', { month: 'short' })}${String(d.getFullYear()).slice(-2)}`;
    out.push({ value, label });
  }
  return out;
};

const fmtDate = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? String(v).slice(0, 10)
    : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
};

const fmtBytes = (n) => {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
};

/** Segmented pill toggle — company-wise / HOD-wise. */
const Segmented = ({ value, onChange, options }) => (
  <div className="inline-flex p-0.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
    {options.map((o) => {
      const on = value === o.id;
      const Icon = o.icon;
      return (
        <button key={o.id} onClick={() => onChange(o.id)} type="button"
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11.5px] font-bold transition-all ${
            on ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
          {Icon && <Icon size={13} />}{o.label}
        </button>
      );
    })}
  </div>
);

/** 0–100 score input for the manual-score grid. */
const ScoreInput = ({ value, onChange, disabled }) => (
  <input
    type="number" min={0} max={100} inputMode="numeric"
    value={value ?? ''} disabled={disabled} placeholder="—"
    onChange={(e) => onChange(e.target.value)}
    className="w-[96px] px-2.5 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-bold text-center tabular-nums outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-55 disabled:cursor-not-allowed"
  />
);

const EmptyState = ({ icon: Icon, title, hint }) => (
  <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
    <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">{Icon && <Icon size={22} />}</span>
    <p className="text-[13px] font-bold">{title}</p>
    {hint && <p className="text-[12px] text-[var(--text-muted)] max-w-md">{hint}</p>}
  </div>
);

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const MANUAL_TABS = [
  { id: 'company', label: 'Company-wise', icon: GitBranch },
  { id: 'hod',     label: 'HOD-wise',     icon: UserCog },
];

const ImplementationTracker = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  // Client-side users are auto-scoped server-side; only internal users pick a client/OM.
  const canPickCompany = !canAccessTpmsClient(user);
  // Entering scores is a governance-authority action — Admin / Super Admin only (H12).
  const canEditScores = isTpmsAdmin(user);

  const periods = useMemo(() => monthOptions(), []);
  const [period, setPeriod] = useState(currentPeriod());
  const [company, setCompany] = useState('');
  const [om, setOm] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Manual-score entry state.
  const [manualTab, setManualTab] = useState('company');
  const [hodId, setHodId] = useState('');
  const [drafts, setDrafts] = useState({});   // "<tab>:<hodId>:<activity>" → {target, actual}
  const [savingKey, setSavingKey] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getImplementationTracker({
        period: period || undefined,
        company_id: company || undefined,
        om_id: om || undefined,
      });
      setData(res.data);
      setDrafts({});           // server values are the new baseline
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load implementation tracker');
    } finally {
      setLoading(false);
    }
  }, [period, company, om]);

  useEffect(() => { load(); }, [load]);

  // Changing the client invalidates the HOD picker — HODs are per-company.
  useEffect(() => { setHodId(''); setDrafts({}); }, [company, period]);

  const cards = data?.cards || {};
  const scorecard = useMemo(() => data?.scorecard || [], [data]);
  const matrixActivities = data?.matrix_activities || [];
  const clients = data?.clients || [];
  const uploads = useMemo(() => data?.uploads || [], [data]);
  const pUploads = usePaged(uploads || [], 10);
  const filters = useMemo(() => data?.filters || {}, [data]);
  const manualActivities = useMemo(() => data?.manual_activities || [], [data]);
  const manualScores = useMemo(() => data?.manual_scores || {}, [data]);
  const manualHodScores = useMemo(() => data?.manual_hod_scores || {}, [data]);
  const hods = useMemo(() => data?.hods || [], [data]);
  const selectedCompanyId = data?.selected_company || '';

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(filters.companies || [])], [filters]);
  const omOpts = useMemo(
    () => [{ id: '', name: 'All OMs' }, ...(filters.oms || [])], [filters]);
  const hodOpts = useMemo(
    () => [{ id: '', name: '— Select HOD —' }, ...hods], [hods]);
  const selectedName = useMemo(
    () => companyOpts.find((c) => String(c.id) === String(company))?.name || 'All Clients',
    [companyOpts, company]);

  const total = cards.total ?? scorecard.length;
  const avgScore = useMemo(() => {
    if (!scorecard.length) return 0;
    const sum = scorecard.reduce((a, r) => a + (r.score_actual || 0), 0);
    return Math.round(sum / scorecard.length);
  }, [scorecard]);

  const kpis = [
    { value: `${cards.met ?? 0}/${total}`,     label: 'Activity Done',  sub: 'Met ≥100%',         tone: 'green',  icon: CheckCircle2 },
    { value: `${cards.partial ?? 0}/${total}`, label: 'Partially Done', sub: 'Partial 1–99%',     tone: 'yellow', icon: CircleDashed },
    { value: `${cards.not_met ?? 0}/${total}`, label: 'Not Done',       sub: 'Not Met 0%',        tone: 'red',    icon: XCircle },
    { value: `${avgScore}%`,                   label: 'Avg Score',      sub: 'Across activities', tone: 'blue',   icon: Gauge },
    { value: '100%',                           label: 'Target',         sub: 'Default cadence',   tone: 'blue',   icon: Target },
  ];

  const hasScorecard = scorecard.length > 0;
  const hasCompany = Boolean(selectedCompanyId);
  const matrixMinWidth = Math.max(860, 360 + matrixActivities.length * 64);

  // ── Manual scores ─────────────────────────────────────────────
  const manualRows = useMemo(
    () => manualActivities.filter((m) => (m.scope || 'company') === manualTab),
    [manualActivities, manualTab]);

  const draftKey = useCallback(
    (activity) => `${manualTab}:${manualTab === 'hod' ? hodId : ''}:${activity}`,
    [manualTab, hodId]);

  /** Saved server value for a row, honouring the active tab + HOD selection. */
  const savedCell = useCallback((activity) => (
    manualTab === 'hod'
      ? (manualHodScores[hodId] || {})[activity]
      : manualScores[activity]
  ), [manualTab, hodId, manualHodScores, manualScores]);

  /** Mean of every HOD's figure for an activity — the read-only "all HODs" view. */
  const hodAverage = useCallback((activity, field) => {
    const vals = Object.values(manualHodScores)
      .map((byActivity) => byActivity?.[activity]?.[field])
      .filter((v) => v != null);
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
  }, [manualHodScores]);

  const fieldValue = useCallback((activity, field) => {
    const d = drafts[draftKey(activity)];
    if (d && d[field] !== undefined) return d[field];
    const saved = savedCell(activity);
    const v = saved?.[field === 'target' ? 'score_target' : 'score_actual'];
    if (v != null) return String(v);
    // Company rows are seeded at 100; HOD rows are created on first save and have no seed,
    // so fall back to the same default rather than posting a null target (which would leave
    // Achievement % uncomputable).
    return field === 'target' ? '100' : '';
  }, [drafts, draftKey, savedCell]);

  const setField = (activity, field, v) => setDrafts((p) => ({
    ...p, [draftKey(activity)]: { ...(p[draftKey(activity)] || {}), [field]: v },
  }));

  // HOD-wise rows are only editable once a specific HOD is picked — an average is a
  // derived figure and has nowhere to be written back to.
  const hodLocked = manualTab === 'hod' && !hodId;
  const manualDisabled = !canEditScores || !hasCompany || hodLocked;

  const saveRow = async (activity) => {
    const key = draftKey(activity);
    setSavingKey(key);
    try {
      await saveManualScore({
        company_id: selectedCompanyId,
        activity,
        period,
        scope: manualTab,
        hod_id: manualTab === 'hod' ? hodId : undefined,
        hod_name: manualTab === 'hod'
          ? (hods.find((h) => String(h.id) === String(hodId))?.name || undefined)
          : undefined,
        target: fieldValue(activity, 'target'),
        actual: fieldValue(activity, 'actual'),
      });
      showSuccess(`${activity} — score saved`);
      await load();            // the save re-syncs success measures; pull the new achievement
    } catch (e) {
      showError(e.response?.data?.detail || 'Failed to save score');
    } finally {
      setSavingKey('');
    }
  };

  if (loading && !data) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading implementation tracker…</div>;
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={GitBranch} title="Implementation Tracker" highlight={selectedName} subtitle="Deployment scoring across success measures">
        <HeaderSelect value={period} onChange={setPeriod} options={periods} searchable={false} />
        {/* Picking an OM narrows the client list, so drop a now-possibly-invalid client. */}
        {canPickCompany && <HeaderSelect value={om} onChange={(v) => { setOm(v); setCompany(''); }} options={omOpts} />}
        {canPickCompany && <HeaderSelect value={company} onChange={setCompany} options={companyOpts} />}
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* Scoring legend */}
      <div className="rounded-2xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-orange)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          <b>Impl. Target</b> = default cadence · <b>Actual Impl. %</b> = occurrence completion this period ·
          <b> Actual Score %</b> = auto (completed ÷ total), or entered by hand for the activities in <b>Manual Scores</b> ·
          <b> Calendar Discipline</b> = completion across all other activities (excluding Action Closure Review) ·
          <b> Achievement %</b> = Actual Score ÷ Score Target × 100 —
          <span className="text-[var(--accent-green)] font-bold"> Met ≥100%</span> ·
          <span className="text-[var(--accent-orange)] font-bold"> Partial 50–99%</span> ·
          <span className="text-[var(--accent-red)] font-bold"> Not Met &lt;50%</span>.
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Scorecard */}
      <Section title="Activity Scorecard" subtitle={hasScorecard ? `Success measures for ${selectedName}` : 'Detailed success measures & uploads'} icon={Target}
        action={hasScorecard && <span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{scorecard.length} activities</span>}>
        {!hasScorecard ? (
          <EmptyState icon={MousePointerClick} title="Select a client to view its scorecard"
            hint={`Pick a client from the header to see detailed success measures for ${periodLabel(period) || period}.`} />
        ) : (
          <TableShell minWidth={980}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>#</Th><Th>Activity Name</Th>
                <Th align="center">Impl. Target %</Th><Th align="center">Actual Impl. %</Th>
                <Th align="center">Score Target %</Th><Th align="center">Actual Score %</Th>
                <Th align="center">Achievement %</Th><Th>Progress</Th><Th align="center">Status</Th>
              </tr>
            </thead>
            <tbody>
              {scorecard.map((r, i) => {
                const achievement = r.achievement || 0;
                return (
                  <tr key={r.activity || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                    <Td className="font-bold">{r.activity || '—'}</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pctOrDash(r.impl_target)}</Td>
                    <Td align="center" className="tabular-nums font-bold" style={{ color: r.impl_actual ? 'var(--accent-green)' : 'var(--accent-red)' }}>{pctOrDash(r.impl_actual)}</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pctOrDash(r.score_target)}</Td>
                    <Td align="center" className="tabular-nums font-bold">{pctOrDash(r.score_actual)}</Td>
                    <Td align="center" className="font-extrabold">{achievement}%</Td>
                    <Td><Progress value={Math.min(achievement, 100)} /></Td>
                    <Td align="center"><Pill label={statusOf(achievement)} /></Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Section>

      {/* Manual Scores — company-wise / HOD-wise entry */}
      <Section title="Manual Scores" icon={Pencil}
        subtitle={hasCompany ? `${selectedName} · ${periodLabel(period) || period}` : 'Hand-entered success measures'}
        action={hasCompany && <Segmented value={manualTab} onChange={setManualTab} options={MANUAL_TABS} />}>
        {!hasCompany ? (
          <EmptyState icon={MousePointerClick} title="Select a client to enter scores"
            hint="Manual scores are recorded per client and month. Pick a client from the header to start." />
        ) : (
          <>
            {manualTab === 'hod' && (
              <div className="px-5 py-3.5 border-b border-[var(--border)] flex flex-wrap items-center gap-3">
                <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">HOD</span>
                <FilterSelect value={hodId} onChange={setHodId} options={hodOpts} />
                {hodLocked && (
                  <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--text-muted)]">
                    <Lock size={12} /> Showing the average across all HODs — pick one to edit.
                  </span>
                )}
              </div>
            )}

            {!canEditScores && (
              <div className="px-5 py-3 border-b border-[var(--border)] text-[11.5px] font-semibold text-[var(--text-muted)] flex items-center gap-1.5">
                <Lock size={12} /> Read-only — only Admin / Super Admin can enter scores.
              </div>
            )}

            {manualRows.length === 0 ? (
              <EmptyState icon={Inbox} title="No manually-scored activities in this scope"
                hint="Activities are marked manual in the activity catalogue." />
            ) : (
              <TableShell minWidth={720}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th>Activity</Th>
                    <Th align="center">Score Target %</Th>
                    <Th align="center">Actual Score %</Th>
                    <Th align="right"> </Th>
                  </tr>
                </thead>
                <tbody>
                  {manualRows.map((m) => {
                    const key = draftKey(m.activity);
                    const busy = savingKey === key;
                    const avgTarget = hodLocked ? hodAverage(m.activity, 'score_target') : null;
                    const avgActual = hodLocked ? hodAverage(m.activity, 'score_actual') : null;
                    return (
                      <tr key={m.activity} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td className="font-bold">{m.activity}</Td>
                        {hodLocked ? (
                          <>
                            <Td align="center" className="tabular-nums text-[var(--text-muted)] font-semibold">
                              {avgTarget == null ? '—' : `${avgTarget}%`}
                            </Td>
                            <Td align="center" className="tabular-nums font-bold" style={{ color: avgActual == null ? 'var(--text-muted)' : scoreColor(avgActual) }}>
                              {avgActual == null ? '—' : `${avgActual}%`}
                              <span className="ml-1.5 text-[10.5px] font-semibold text-[var(--text-muted)]">avg of HODs</span>
                            </Td>
                          </>
                        ) : (
                          <>
                            <Td align="center">
                              <ScoreInput value={fieldValue(m.activity, 'target')} disabled={manualDisabled}
                                onChange={(v) => setField(m.activity, 'target', v)} />
                            </Td>
                            <Td align="center">
                              <ScoreInput value={fieldValue(m.activity, 'actual')} disabled={manualDisabled}
                                onChange={(v) => setField(m.activity, 'actual', v)} />
                            </Td>
                          </>
                        )}
                        <Td align="right">
                          <button type="button" onClick={() => saveRow(m.activity)} disabled={manualDisabled || busy}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[11.5px] font-bold hover:bg-[var(--accent-indigo)] hover:text-white transition-all disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-[var(--accent-indigo-bg)] disabled:hover:text-[var(--accent-indigo)]">
                            {busy ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
                            {busy ? 'Saving…' : 'Save'}
                          </button>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
            )}
          </>
        )}
      </Section>

      {/* Uploaded proof files */}
      <Section title="Uploaded Files" icon={Paperclip}
        subtitle={hasCompany ? `Proof of work for ${selectedName} · ${periodLabel(period) || period}` : 'Proof-of-work attachments'}
        action={hasCompany && uploads.length > 0 && <span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{uploads.length} file{uploads.length === 1 ? '' : 's'}</span>}>
        {!hasCompany ? (
          <EmptyState icon={MousePointerClick} title="Select a client to view its uploads"
            hint="Files attached to that client's activities for the selected month appear here." />
        ) : uploads.length === 0 ? (
          <EmptyState icon={Inbox} title="No files uploaded for this client this month."
            hint="Proof files are attached from the activity itself, on activities that require an upload." />
        ) : (
          <div className="space-y-6">
            {Object.entries((uploads || []).reduce((acc, u) => {
              const k = u.activity || 'Unspecified';
              (acc[k] = acc[k] || []).push(u);
              return acc;
            }, {})).map(([activity, files]) => (
              <div key={activity}>
                <div className="flex items-center gap-2 mb-2 px-1">
                  <Grid3x3 size={13} className="text-[var(--text-muted)]" />
                  <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-main)]">{activity}</span>
                  <span className="text-[10px] font-bold text-[var(--text-muted)]">· {files.length} file{files.length === 1 ? '' : 's'}</span>
                </div>
                <TableShell minWidth={820}>
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      <Th>File</Th><Th align="center">Scope</Th><Th>Uploaded By</Th>
                      <Th align="center">Date</Th><Th align="right"> </Th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((u) => (
                      <tr key={u._id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td>
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span className="w-8 h-8 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0">
                              <Paperclip size={14} />
                            </span>
                            <div className="min-w-0">
                              <div className="font-bold truncate max-w-[280px]">{u.file_name || 'Untitled'}</div>
                              {u.size != null && <div className="text-[11px] text-[var(--text-muted)]">{fmtBytes(u.size)}</div>}
                            </div>
                          </div>
                        </Td>
                        <Td align="center">
                          <span className={`inline-block text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded-md ${u.scope === 'hod' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]'}`}>
                            {u.scope === 'hod' ? 'HOD-wise' : 'Company-wise'}
                          </span>
                        </Td>
                        <Td>{u.uploaded_by_name || u.member_name || '—'}</Td>
                        <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtDate(u.uploaded_at)}</Td>
                        <Td align="right">
                          {u.url ? (
                            <a href={u.url} target="_blank" rel="noreferrer"
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[11.5px] font-bold hover:bg-[var(--accent-indigo)] hover:text-white transition-all">
                              <Download size={13} /> Open
                            </a>
                          ) : (
                            <span className="text-[11.5px] font-semibold text-[var(--text-muted)]">Link unavailable</span>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </TableShell>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Client × Activity Score Matrix */}
      <Section title="Client × Activity Score Matrix" subtitle="Completion % per activity, all clients in scope" icon={Grid3x3}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{clients.length} clients</span>}>
        {clients.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <span className="w-10 h-10 rounded-2xl bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><AlertTriangle size={20} /></span>
            <p className="text-[13px] font-bold">No activity for this period.</p>
          </div>
        ) : (
          <TableShell minWidth={matrixMinWidth}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Client</Th>
                <Th>OM</Th>
                {matrixActivities.map((a) => <Th key={a.full} align="center">{a.short}</Th>)}
                <Th align="center">AVG</Th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.company_id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{c.company}</Td>
                  <Td className="text-[var(--text-muted)] whitespace-nowrap">{c.om || '—'}</Td>
                  {matrixActivities.map((a) => {
                    const cell = c.cells?.[a.full];
                    const val = cell && cell.total ? Math.round((cell.done / cell.total) * 100) : null;
                    return (
                      <Td key={a.full} align="center" className="tabular-nums font-bold" style={{ color: val == null ? 'var(--text-muted)' : scoreColor(val) }}>
                        {val == null ? '—' : `${val}%`}
                      </Td>
                    );
                  })}
                  {(() => {
                    // Per-client average across the activities that have any scheduled work.
                    const vals = matrixActivities
                      .map((a) => { const cell = c.cells?.[a.full]; return cell && cell.total ? (cell.done / cell.total) * 100 : null; })
                      .filter((x) => x != null);
                    const avg = vals.length ? Math.round(vals.reduce((s, x) => s + x, 0) / vals.length) : null;
                    return (
                      <Td align="center" className="tabular-nums font-extrabold" style={{ color: avg == null ? 'var(--text-muted)' : scoreColor(avg) }}>
                        {avg == null ? '—' : `${avg}%`}
                      </Td>
                    );
                  })()}
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>
    </div>
  );
};

export default ImplementationTracker;
