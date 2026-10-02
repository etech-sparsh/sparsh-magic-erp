import React, { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, UserCog, ListChecks, CheckCircle2, XCircle, Clock, Target,
  ClipboardList, ClipboardCheck, AlertTriangle, Mail, IdCard, Building2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
  usePaged, Pager,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { getHodDashboard, periodLabel } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   SMOPS ▸ HOD Activity — per-HOD activity dashboard.
   Data comes from GET /tpms/dashboards/hod (getHodDashboard). The
   backend scopes companies to the signed-in user (staff → their
   companies, a client HOD → themselves) and returns the HOD roster,
   so the selectors below are driven entirely by the server response.
   ───────────────────────────────────────────────────────────── */

// Range presets for the dashboard filter (mirrors the AppScript doc).
const RANGE_OPTIONS = [
  { id: 'this_month', name: 'This Month' },
  { id: 'last_month', name: 'Last Month' },
  { id: 'quarter', name: 'This Quarter' },
  { id: 'custom', name: 'Custom' },
];

// Manual YYYY-MM-DD formatting (no external date lib in this codebase).
const fmtDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Resolve a preset → { from, to } as YYYY-MM-DD. Grouping stays per-month on the
// backend, so a multi-month range simply yields one column per month. A custom
// range returns nulls until both endpoints are set (so we don't fetch early).
const rangeFor = (preset, customFrom, customTo, now) => {
  const base = now || new Date();
  const y = base.getFullYear();
  const m = base.getMonth();
  if (preset === 'last_month') {
    return { from: fmtDate(new Date(y, m - 1, 1)), to: fmtDate(new Date(y, m, 0)) };
  }
  if (preset === 'quarter') {
    const qStart = Math.floor(m / 3) * 3;
    return { from: fmtDate(new Date(y, qStart, 1)), to: fmtDate(base) };
  }
  if (preset === 'custom') {
    return { from: customFrom || null, to: customTo || null };
  }
  // this_month (default): first day of the current month → today.
  return { from: fmtDate(new Date(y, m, 1)), to: fmtDate(base) };
};

const OCC = {
  Completed: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Missed:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Pending:   { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};
const OccPill = ({ v }) => {
  const s = OCC[v] || OCC.Pending;
  return <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}><span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{v || '—'}</span>;
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');
const delayColor = (v) => (v === 'On time' ? 'var(--accent-green)' : (/pending/i.test(v || '') ? 'var(--accent-orange)' : (v && v !== '—' ? 'var(--accent-red)' : 'var(--text-muted)')));
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const HodActivity = () => {
  const { user } = useAuth();
  const [rangePreset, setRangePreset] = useState('this_month');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const { from, to } = useMemo(
    () => rangeFor(rangePreset, customFrom, customTo),
    [rangePreset, customFrom, customTo],
  );
  const [hodId, setHodId] = useState(''); // '' → let the backend pick the default HOD
  const [tick, setTick] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await getHodDashboard({
          member_id: hodId || undefined,
          from: from || undefined,
          to: to || undefined,
        });
        if (alive) setData(res.data);
      } catch (e) {
        if (alive) { setData(null); setError(e.response?.data?.detail || 'Failed to load HOD activity'); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [from, to, hodId, tick]);

  const hod = data?.hod || null;
  const cards = data?.cards || {};
  const scoreRows = data?.score_rows || [];
  const tracker = data?.tracker || [];
  const actions = data?.open_actions || [];
  const hodOptions = data?.hod_options || [];
  // The backend flags "on track" with a single {level:'ok'} alert — drop it here.
  const needs = (data?.alerts || []).filter((a) => a.level !== 'ok');
  const hasHod = !!(hod && hod.id);

  // Client-side pagination for the two big grids (occurrences & action items).
  const pTracker = usePaged(tracker || [], 12);
  const pActions = usePaged(actions || [], 10);

  const kpis = [
    { value: cards.activities ?? 0, label: 'Activities', sub: 'This period', tone: 'blue', icon: ListChecks },
    { value: cards.completed ?? 0, label: 'Completed', sub: 'Done', tone: 'green', icon: CheckCircle2 },
    { value: cards.missed ?? 0, label: 'Missed', sub: 'Not done', tone: cards.missed ? 'red' : 'plain', icon: XCircle },
    { value: cards.pending ?? 0, label: 'Pending', sub: 'Upcoming', tone: 'yellow', icon: Clock },
    { value: `${cards.completion ?? 0}%`, label: 'Completion', sub: 'Done ÷ total', tone: (cards.completion ?? 0) >= 80 ? 'green' : 'yellow', icon: Target },
    { value: cards.open_actions ?? 0, label: 'Open Actions', sub: 'To close', tone: cards.open_actions ? 'red' : 'plain', icon: ClipboardList },
    { value: `${cards.action_closure ?? 0}%`, label: 'Action Closure', sub: 'vs 95% target', tone: (cards.action_closure ?? 0) >= 95 ? 'green' : 'yellow', icon: ClipboardCheck },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={UserCog} title="HOD Activity" highlight={hod?.name || user?.full_name || 'HOD'} subtitle="Monitor what client HODs are doing across your companies">
        {hodOptions.length > 0 && (
          <HeaderSelect value={data?.selected_hod || ''} onChange={setHodId} options={hodOptions} />
        )}
        <HeaderSelect value={rangePreset} onChange={setRangePreset} options={RANGE_OPTIONS} />
        {rangePreset === 'custom' && (
          <>
            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
              className="px-3 py-2 rounded-lg bg-[var(--bg-card)] text-[var(--text-main)] text-[12.5px] font-bold outline-none border border-[var(--border)] shadow-sm hover:opacity-90 transition-opacity cursor-pointer" />
            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
              className="px-3 py-2 rounded-lg bg-[var(--bg-card)] text-[var(--text-main)] text-[12.5px] font-bold outline-none border border-[var(--border)] shadow-sm hover:opacity-90 transition-opacity cursor-pointer" />
          </>
        )}
        <HeroButton icon={RefreshCw} onClick={() => setTick((t) => t + 1)}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm py-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={24} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading HOD activity…</p>
        </div>
      ) : !hasHod ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm py-16 text-center">
          <UserCog size={26} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">No HODs to show</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">No HOD activity is available for your companies this period.</p>
        </div>
      ) : (
        <>
          {/* Identity bar */}
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-2">
            <div className="flex items-center gap-2.5">
              <span className="w-9 h-9 rounded-xl text-white font-bold text-[12px] flex items-center justify-center" style={{ background: 'var(--avatar-bg)' }}>{(hod.name || '?').split(' ').map((x) => x[0]).join('')}</span>
              <span className="text-[14px] font-extrabold tracking-tight">{hod.name}</span>
            </div>
            <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><IdCard size={14} /> {hod.id}</span>
            {hod.company && <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><Building2 size={14} /> {hod.company}</span>}
            {hod.department && <span className="inline-flex items-center text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">{hod.department}</span>}
            {hod.email && <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><Mail size={14} /> {hod.email}</span>}
          </div>

          {/* KPI tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
            {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
          </div>

          {/* Activity Scoring */}
          <Section title="Activity Scoring — Per Activity × Month" subtitle="Completion & score per governance ritual" icon={Target}>
            {scoreRows.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activities tracked this period.</div>
            ) : (
              <TableShell minWidth={860}>
                <thead><tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Month</Th><Th>Activity</Th><Th align="center">Completed</Th><Th align="center">Total</Th>
                  <Th align="center">Missed</Th><Th align="center">Pending</Th><Th align="center">Score</Th><Th align="center">%</Th>
                </tr></thead>
                <tbody>
                  {scoreRows.map((r, i) => {
                    const pct = r.total ? Math.round((r.completed / r.total) * 100) : 0;
                    return (
                      <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                        <Td className={`font-bold ${stickyCell}`}>{r.period_label || r.period}</Td>
                        <Td className="font-medium">{r.activity}</Td>
                        <Td align="center" className="font-bold text-[var(--accent-green)]">{r.completed}</Td>
                        <Td align="center" className="tabular-nums">{r.total}</Td>
                        <Td align="center" className="font-bold text-[var(--accent-red)]">{r.missed}</Td>
                        <Td align="center" className="font-bold text-[var(--accent-orange)]">{r.pending}</Td>
                        <Td align="center" className="font-extrabold" style={{ color: scoreColor(r.score) }}>{r.score}</Td>
                        <Td align="center" className="font-extrabold tabular-nums">{pct}%</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
            )}
          </Section>

          {/* Occurrences */}
          <Section title="Activity Tracker — Occurrences" subtitle="Every scheduled occurrence and its outcome" icon={ListChecks}>
            {tracker.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No tracked occurrences this period.</div>
            ) : (
              <>
              <TableShell minWidth={640}>
                <thead><tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Date</Th><Th>Month</Th><Th>Activity</Th><Th align="center">Status</Th>
                </tr></thead>
                <tbody>
                  {pTracker.pageRows.map((r, i) => (
                    <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className={`tabular-nums font-bold ${stickyCell}`}>{r.date}</Td>
                      <Td className="text-[var(--text-muted)]">{periodLabel(r.period) || r.period}</Td>
                      <Td className="font-medium">{r.activity}</Td>
                      <Td align="center"><OccPill v={r.status} /></Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              <Pager {...pTracker} label="occurrences" />
              </>
            )}
          </Section>

          {/* Needs Attention */}
          <Section title="Needs Attention" subtitle={needs.length ? `${needs.length} item${needs.length > 1 ? 's' : ''}` : 'On track'} icon={AlertTriangle} tone="red">
            {needs.length === 0 ? (
              <div className="flex items-center gap-2.5 px-5 py-6">
                <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
                <p className="text-[13px] font-bold text-[var(--accent-green)]">Nothing urgent. On track.</p>
              </div>
            ) : (
              <div className="divide-y divide-[var(--border)]">
                {needs.map((t, i) => (
                  <div key={i} className="flex items-start gap-3 px-5 py-3.5 hover:bg-[var(--table-hover)] transition-colors">
                    <span className="w-6 h-6 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center mt-0.5 shrink-0"><AlertTriangle size={13} /></span>
                    <span className="text-[12.5px] font-medium">{t.text}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Open Action Items */}
          <Section title="Open Action Items" subtitle={actions.length ? `${actions.length} open` : 'Nothing open'} icon={ClipboardList}>
            {actions.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No open action items.</div>
            ) : (
              <>
              <TableShell minWidth={980}>
                <thead><tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th><Th>Target Date</Th>
                  <Th align="center">Status</Th><Th>Client Delay</Th><Th>OM Delay</Th><Th>Follow-up</Th>
                </tr></thead>
                <tbody>
                  {pActions.pageRows.map((r, i) => (
                    <tr key={r.id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                      <Td>{r.action}</Td>
                      <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                      <Td className="tabular-nums text-[var(--text-muted)]">{r.employee_id || '—'}</Td>
                      <Td className="tabular-nums">{r.target || '—'}</Td>
                      <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)', background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)' }}>{r.status}</span></Td>
                      <Td className="font-bold" style={{ color: delayColor(r.learner_delay) }}>{r.learner_delay || '—'}</Td>
                      <Td className="font-bold" style={{ color: delayColor(r.staff_delay) }}>{r.staff_delay || '—'}</Td>
                      <Td className="text-[var(--text-muted)]">{r.follow_up || '—'}</Td>
                    </tr>
                  ))}
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

export default HodActivity;
