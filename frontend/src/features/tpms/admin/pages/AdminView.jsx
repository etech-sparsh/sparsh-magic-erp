import React, { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, LayoutDashboard, CalendarDays, Medal, Building2, CalendarClock, CalendarX,
  Users, ClipboardList, CheckCircle2, Target, Timer, ClipboardCheck, AlertTriangle,
  Star, Sparkles, FileCheck, Trophy, Activity, Clock, Grid3x3,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, Trend, StatusBadge, Progress,
  KpiTile, HeaderSelect, FilterSelect, TableShell, usePaged, Pager,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { getAnalyticsDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import ClientActivityCalendar from './ClientActivityCalendar';

/* ─────────────────────────────────────────────────────────────
   Admin View — high-level operational dashboard (ERP-grade).
   Wired to GET /tpms/dashboards/analytics (getAnalyticsDashboard).
   Filters (period / OM / company) are applied server-side.
   ───────────────────────────────────────────────────────────── */

// Last 12 months as { value: 'YYYY-MM', label: 'Jul26' } — the canonical token the backend expects.
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ id: value, name: periodLabel(value) || value });
  }
  return out;
};

// Backend trend is 'Up' / 'Down' / 'Flat'; the Trend component expects lowercase.
const trendDir = (t) => String(t || '').toLowerCase();
const pctCell = (v) => (v === '' || v == null ? '—' : `${v}%`);
const pctColor = (p) => (p >= 75 ? 'var(--accent-green)' : p >= 40 ? 'var(--accent-orange)' : 'var(--accent-red)');

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

// Spec §9.1 grid/action filters. "Scheduled by" maps to the stored scheduled_by_side.
const SCHEDULED_BY_OPTIONS = [
  { id: '', name: 'Anyone' },
  { id: 'internal', name: 'OM / SMOps' },
  { id: 'client', name: 'Client' },
];
// Spec §8 — the third delay display state (numeric "Nd") needs closed rows visible.
const ACTION_STATUS_OPTIONS = [
  { id: 'open', name: 'Open' },
  { id: 'closed', name: 'Closed' },
  { id: '', name: 'All' },
];

const PENDING_SIDE_OPTIONS = [
  { id: '', name: 'Either side' },
  { id: 'client', name: 'Client side' },
  { id: 'staff', name: 'OM side' },
];

// Ratio-cell colour by the cell's dominant status (done > pending > overdue > cancelled).
const CELL_TONE = {
  done:      { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)' },
  pending:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  overdue:   { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)' },
  cancelled: { c: 'var(--text-muted)',    bg: 'var(--input-bg)' },
};

/** Open action items carry a side label, not a number, until they close (spec §8). */
const DelayChip = ({ value, active }) => {
  if (!value) return <span className="text-[var(--text-muted)] opacity-40">—</span>;
  const tone = active
    ? { color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }
    : { color: 'var(--text-muted)', background: 'var(--input-bg)' };
  return (
    <span className="inline-flex items-center gap-1.5 text-[10.5px] font-black px-2.5 py-1 rounded-full whitespace-nowrap" style={tone}>
      {active && <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--accent-orange)' }} />}
      {value}
    </span>
  );
};

/** ['', ...distinct sorted values] as {id,name} options for a client-side filter. */
const optionsFrom = (rows, key, allLabel) => [
  { id: '', name: allLabel },
  ...[...new Set(rows.map((r) => r[key]).filter(Boolean))]
    .sort((a, b) => String(a).localeCompare(String(b)))
    .map((v) => ({ id: v, name: v })),
];

const AdminView = () => {
  const { user } = useAuth();
  const months = useMemo(() => monthOptions(), []);

  const [tab, setTab] = useState('dashboard');
  const [period, setPeriod] = useState(currentPeriod());
  const [om, setOm] = useState('');
  const [client, setClient] = useState('');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  // §9.1 section filters. `schedBy` is applied server-side (it re-scopes the grid);
  // the action-item filters are client-side over the already-fetched feed.
  const [schedBy, setSchedBy] = useState('');
  const [actActivity, setActActivity] = useState('');
  const [actClient, setActClient] = useState('');
  const [actOwner, setActOwner] = useState('');
  const [actSide, setActSide] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await getAnalyticsDashboard({
          period: period || undefined,
          om_id: om || undefined,
          company_id: client || undefined,
          scheduled_by: schedBy || undefined,
        });
        if (alive) setData(res.data);
      } catch (e) {
        if (alive) { setData(null); setError(e.response?.data?.detail || 'Failed to load dashboard'); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [period, om, client, schedBy, refreshKey]);

  const reload = () => setRefreshKey((k) => k + 1);

  const cards = data?.cards || {};
  const clients = data?.clients || [];
  const pClients = usePaged(clients || [], 10);
  const oms = data?.oms || [];
  const pOms = usePaged(oms || [], 10);
  const topDelayed = data?.top_delayed || [];
  const gridActivities = useMemo(() => data?.activities || [], [data]);
  const gridRows = useMemo(() => data?.clients_grid || [], [data]);
  const pGrid = usePaged(gridRows || [], 10);
  const [actStatus, setActStatus] = useState('open');
  const openActions = useMemo(() => data?.open_actions || [], [data]);

  const activityOpts = useMemo(() => optionsFrom(openActions, 'activity', 'All activities'), [openActions]);
  const actionClientOpts = useMemo(() => optionsFrom(openActions, 'company', 'All clients'), [openActions]);
  const ownerOpts = useMemo(() => optionsFrom(openActions, 'owner', 'All owners'), [openActions]);

  const actionRows = useMemo(() => openActions.filter((a) => (
    (!actActivity || a.activity === actActivity)
    && (!actClient || a.company === actClient)
    && (!actOwner || a.owner === actOwner)
    && (!actSide || a.pending_side === actSide)
    // Spec §8 — Open (default) / Closed / All; closed rows carry the numeric delay split.
    && (!actStatus || (actStatus === 'closed' ? !!a.closed : !a.closed))
  )), [openActions, actActivity, actClient, actOwner, actSide, actStatus]);
  const pActions = usePaged(actionRows || [], 10);

  const omOpts = useMemo(
    () => [{ id: '', name: 'All OMs' }, ...(data?.filters?.oms || [])], [data]);
  const clientOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(data?.filters?.companies || [])], [data]);

  const kpis = [
    { value: cards.total_clients ?? 0,      label: 'Total Clients',      sub: 'In scope',              tone: 'blue',   icon: Building2 },
    { value: cards.planned_clients ?? 0,    label: 'Planned Clients',    sub: 'Have activity',         tone: 'green',  icon: CalendarClock },
    { value: cards.unplanned_clients ?? 0,  label: 'Unplanned Clients',  sub: 'No activity scheduled', tone: 'plain',  icon: CalendarX },
    { value: cards.total_oms ?? 0,          label: 'Total OMs',          sub: 'Across teams',          tone: 'blue',   icon: Users },
    { value: cards.planned ?? 0,            label: 'Planned Activities', sub: 'This period',           tone: 'yellow', icon: ClipboardList },
    { value: cards.completed ?? 0,          label: 'Completed',          sub: 'Activities done',       tone: 'green',  icon: CheckCircle2 },
    { value: `${cards.completion ?? 0}%`,   label: 'Overall Completion', sub: 'Done ÷ planned',        tone: 'green',  icon: Target },
    { value: cards.avg_delay ?? 0,          label: 'Avg Delay Days',     sub: 'Days past deadline',    tone: 'yellow', icon: Timer },
    { value: `${cards.action_closure ?? 0}%`, label: 'Action Closure',   sub: 'Closed ÷ total',        tone: 'yellow', icon: ClipboardCheck },
    { value: cards.escalations ?? 0,        label: 'Active Escalations', sub: 'Need OM action',        tone: cards.escalations ? 'red' : 'plain', icon: AlertTriangle },
    { value: `${cards.oa_rating ?? 0}%`,    label: 'O&A Rating',         sub: 'HODs accountability',   tone: 'green',  icon: Star },
    { value: `${cards.culture_score ?? 0}%`, label: 'Culture Score',     sub: 'Overall score',         tone: 'green',  icon: Sparkles },
    { value: `${cards.drm_completion ?? 0}%`, label: 'DRM Completion',   sub: 'HODs signed-off',       tone: 'green',  icon: FileCheck },
    { value: `${cards.success_score ?? 0}%`, label: 'Success Score',     sub: 'Overall avg',           tone: 'green',  icon: Trophy },
  ];

  return (
    <div className="space-y-5">
      {/* Hero header */}
      <DashboardHero icon={LayoutDashboard} title="Admin Dashboard"
        subtitle={`Operational command centre${user?.full_name ? ` · ${user.full_name}` : ''}`}>
        <HeaderSelect value={period} onChange={setPeriod} options={months} searchable={false} />
        <HeaderSelect value={om} onChange={setOm} options={omOpts} />
        <HeaderSelect value={client} onChange={setClient} options={clientOpts} />
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {/* Tabs */}
      <div className="flex items-center gap-2">
        {[
          { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
          { key: 'calendar',  label: 'Client-wise Calendar', icon: CalendarDays },
        ].map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-bold transition-all border
              ${tab === t.key ? 'text-white border-transparent shadow-sm' : 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--bg-card)] hover:bg-[var(--input-bg)]'}`}
            style={tab === t.key ? { background: 'var(--btn-primary)' } : undefined}>
            <t.icon size={15} /> {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {tab === 'calendar' ? (
        <ClientActivityCalendar />
      ) : loading && !data ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading dashboard…</p>
        </div>
      ) : !data ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)] rounded-2xl border border-dashed border-[var(--border)]">
          <AlertTriangle size={30} className="mb-3 opacity-40" />
          <p className="text-[13px] font-bold">Could not load dashboard data.</p>
        </div>
      ) : (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
            {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
          </div>

          {/* Client Health Matrix */}
          <Section title="Client Health Matrix" subtitle="Delivery health per client with trend & risk" icon={Activity}>
            <TableShell minWidth={980}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th>OM</Th><Th align="center">Planned</Th><Th align="center">Done</Th><Th align="center">Pending</Th>
                  <Th align="center">Overdue</Th><Th align="center">Completion</Th><Th>Progress</Th>
                  <Th align="center">Action Cls</Th><Th align="center">Avg Delay</Th><Th align="center">Esc</Th><Th align="center">Trend</Th><Th align="center">Status</Th>
                </tr>
              </thead>
              <tbody>
                {clients.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No clients for this selection.</span></Td></tr>
                ) : pClients.pageRows.map((r) => (
                  <tr key={r.company_id || r.company} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                    <Td align="center" className="font-bold tabular-nums">{r.planned ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.done ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-orange)]">{r.pending ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td><Progress value={r.completion ?? 0} /></Td>
                    <Td align="center" className="font-bold">{pctCell(r.action_closure)}</Td>
                    <Td align="center" className="tabular-nums">{r.avg_delay ?? 0}</Td>
                    <Td align="center" className="tabular-nums">{r.escalations ?? 0}</Td>
                    <Td align="center"><Trend dir={trendDir(r.trend)} /></Td>
                    <Td align="center"><StatusBadge value={r.status} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <Pager {...pClients} label="clients" />
          </Section>

          {/* OM Performance Comparison */}
          <Section title="OM Performance Comparison" subtitle="Ranked by completion this period" icon={Trophy}>
            <TableShell minWidth={860}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th align="center">Rank</Th><Th className={stickyHead}>OM</Th><Th align="center">Clients</Th><Th align="center">Planned</Th>
                  <Th align="center">Completed</Th><Th align="center">Completion</Th><Th>Progress</Th>
                  <Th align="center">Avg Delay</Th><Th align="center">Action Cls</Th><Th align="center">Esc</Th><Th align="center">Trend</Th>
                </tr>
              </thead>
              <tbody>
                {oms.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No OM data for this selection.</span></Td></tr>
                ) : pOms.pageRows.map((r, i) => (
                  <tr key={r.om_id || r.om} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td align="center">
                      {i <= 2
                        ? <Medal size={18} className="inline" style={{ color: ['#f59e0b', '#9ca3af', '#b45309'][i] }} />
                        : <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--input-bg)] text-[var(--text-muted)] font-bold text-[11px]">{i + 1}</span>}
                    </Td>
                    <Td className={`font-bold ${stickyCell}`}>{r.om || '—'}</Td>
                    <Td align="center" className="tabular-nums">{r.clients ?? 0}</Td>
                    <Td align="center" className="tabular-nums">{r.planned ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-green)]">{r.done ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td><Progress value={r.completion ?? 0} /></Td>
                    <Td align="center" className="tabular-nums">{r.avg_delay ?? 0}d</Td>
                    <Td align="center" className="font-bold">{pctCell(r.action_closure)}</Td>
                    <Td align="center" className="tabular-nums">{r.escalations ?? 0}</Td>
                    <Td align="center"><Trend dir={trendDir(r.trend)} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <Pager {...pOms} label="OMs" />
          </Section>

          {/* Top Delayed Clients */}
          <Section title="Top Delayed Clients" subtitle="Clients needing immediate attention" icon={Clock} tone="red">
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Client</Th><Th>OM</Th><Th align="center">Avg Delay (days)</Th><Th align="center">Overdue</Th><Th align="center">Completion</Th><Th align="center">Status</Th>
                </tr>
              </thead>
              <tbody>
                {topDelayed.length === 0 ? (
                  <tr><Td className="text-center text-[var(--text-muted)]" align="center"><span className="block py-8">No delayed clients 🎉</span></Td></tr>
                ) : topDelayed.map((r) => (
                  <tr key={r.company_id || r.company} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                    <Td className="text-[var(--text-muted)]">{r.om || '—'}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.avg_delay ?? 0}</Td>
                    <Td align="center" className="font-bold text-[var(--accent-red)]">{r.overdue ?? 0}</Td>
                    <Td align="center" className="font-extrabold">{r.completion ?? 0}%</Td>
                    <Td align="center"><StatusBadge value={r.status} /></Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {/* Spec §9.1 — OM Clients · Activity Status grid. Ratio cells ("done/total")
              per client × activity, narrowable to who raised the occurrence. */}
          <Section title="OM Clients — Activity Status" icon={Grid3x3}
            subtitle="Completed / scheduled per activity, for every client in scope"
            action={(
              <div className="flex items-center gap-2">
                <span className="hidden sm:inline text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Scheduled by</span>
                <FilterSelect value={schedBy} onChange={setSchedBy} options={SCHEDULED_BY_OPTIONS} />
              </div>
            )}>
            {gridRows.length === 0 ? (
              <div className="py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">No activity for this period.</div>
            ) : (
              <>
              <TableShell minWidth={Math.max(720, 240 + gridActivities.length * 66 + 220)}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th className={stickyHead}>Client</Th>
                    {gridActivities.map((a) => <Th key={a.full} align="center">{a.short}</Th>)}
                    <Th align="center">Planned</Th><Th align="center">Done</Th><Th align="center">Pct</Th>
                  </tr>
                </thead>
                <tbody>
                  {pGrid.pageRows.map((r) => (
                    <tr key={r.company_id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                      {gridActivities.map((a) => {
                        const cell = r.cells?.[a.full];
                        if (!cell || !cell.total) {
                          return <Td key={a.full} align="center" className="text-[var(--text-muted)] opacity-40">—</Td>;
                        }
                        const tone = CELL_TONE[cell.status] || CELL_TONE.pending;
                        return (
                          <Td key={a.full} align="center">
                            <span className="inline-flex items-center justify-center min-w-[44px] text-[11px] font-black px-2 py-0.5 rounded-md tabular-nums"
                              style={{ color: tone.c, background: tone.bg }}>
                              {cell.done}/{cell.total}
                            </span>
                          </Td>
                        );
                      })}
                      <Td align="center" className="font-bold tabular-nums">{r.total ?? 0}</Td>
                      <Td align="center" className="font-extrabold tabular-nums text-[var(--accent-green)]">{r.done ?? 0}</Td>
                      <Td align="center" className="font-extrabold tabular-nums" style={{ color: pctColor(r.total ? Math.round((r.done / r.total) * 100) : 0) }}>{r.total ? Math.round((r.done / r.total) * 100) : 0}%</Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              <Pager {...pGrid} label="clients" />
              </>
            )}
          </Section>

          {/* Spec §9.1 — Open Action Items, with the Client/OM delay split. */}
          <Section title="Open Action Items" icon={ClipboardCheck} tone="red"
            subtitle="Follow-ups awaiting closure across your clients"
            action={openActions.length > 0 && (
              <span className="text-[10.5px] font-black px-2.5 py-1 rounded-full whitespace-nowrap"
                style={{ color: 'var(--accent-red)', background: 'var(--accent-red-bg)' }}>
                {actionRows.length} of {openActions.length}
              </span>
            )}>
            <div className="px-5 py-3.5 border-b border-[var(--border)] flex flex-wrap items-end gap-3">
              {[
                { label: 'Activity', value: actActivity, set: setActActivity, opts: activityOpts },
                { label: 'Client', value: actClient, set: setActClient, opts: actionClientOpts },
                { label: 'Owner', value: actOwner, set: setActOwner, opts: ownerOpts },
                { label: 'Pending from', value: actSide, set: setActSide, opts: PENDING_SIDE_OPTIONS },
                { label: 'Status', value: actStatus, set: setActStatus, opts: ACTION_STATUS_OPTIONS },
              ].map((f) => (
                <label key={f.label} className="flex flex-col gap-1">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{f.label}</span>
                  <FilterSelect value={f.value} onChange={f.set} options={f.opts} />
                </label>
              ))}
            </div>
            {actionRows.length === 0 ? (
              <div className="py-12 flex flex-col items-center gap-2 text-center">
                <CheckCircle2 size={22} className="text-[var(--accent-green)]" />
                <p className="text-[13px] font-bold">No open action items.</p>
              </div>
            ) : (
              <>
              <TableShell minWidth={900}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th className={stickyHead}>Client</Th><Th>Activity</Th><Th>Action</Th><Th>Owner</Th>
                    <Th align="center">Target</Th><Th align="center">Client Delay</Th><Th align="center">OM Delay</Th>
                  </tr>
                </thead>
                <tbody>
                  {pActions.pageRows.map((a) => {
                    const waitingStaff = a.pending_side === 'staff';
                    return (
                      <tr key={a.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td className={`font-bold ${stickyCell}`}>{a.company || '—'}</Td>
                        <Td className="whitespace-nowrap">{a.activity || '—'}</Td>
                        <Td className="text-[var(--text-muted)]">{a.action || '—'}</Td>
                        <Td className="whitespace-nowrap">{a.owner || '—'}</Td>
                        <Td align="center" className="tabular-nums whitespace-nowrap">{a.target || '—'}</Td>
                        <Td align="center"><DelayChip value={a.learner_delay} active={!waitingStaff} /></Td>
                        <Td align="center"><DelayChip value={a.staff_delay} active={waitingStaff} /></Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
              <Pager {...pActions} label="action items" />
              </>
            )}
          </Section>
        </>
      )}
    </div>
  );
};

export default AdminView;
