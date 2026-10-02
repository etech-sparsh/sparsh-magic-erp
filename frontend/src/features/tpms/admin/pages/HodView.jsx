import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, UserCog, ListChecks, CheckCircle2, XCircle, Clock, Target,
  ClipboardList, ClipboardCheck, AlertTriangle, Mail, IdCard, Building2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
  usePaged, Pager,
} from '../../common/dashboardKit';
import { getHodDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import api from '../../../../services/api';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ HOD View — per-HOD activity dashboard: identity,
   activity scoring (per activity × month), occurrence tracker,
   needs-attention and open action items.

   Wired to GET /tpms/dashboards/hod (getHodDashboard) — data is
   scoped server-side by { period, company_id, member_id }.
   ───────────────────────────────────────────────────────────── */

// Last 12 months as { id: 'YYYY-MM', name: 'July26' } for the period picker.
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

// Previous calendar month as 'YYYY-MM', computed client-side.
const previousPeriod = () => {
  const d = new Date();
  const p = new Date(d.getFullYear(), d.getMonth() - 1, 1);
  return `${p.getFullYear()}-${String(p.getMonth() + 1).padStart(2, '0')}`;
};

// Local-date ISO (yyyy-mm-dd). NOT toISOString(), which converts to UTC and can land on
// the previous day for anyone east of Greenwich — shifting the quarter boundary.
const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Current calendar quarter as an explicit {from,to} range (spec §17 "This Quarter").
// The endpoint takes from/to and overrides the single-month window with it, grouping
// per-month — so a quarter renders as three monthly columns.
const quarterRange = () => {
  const d = new Date();
  const q = Math.floor(d.getMonth() / 3);
  return {
    from: isoDay(new Date(d.getFullYear(), q * 3, 1)),
    to: isoDay(new Date(d.getFullYear(), q * 3 + 3, 0)),   // day 0 of next quarter = last day of this one
  };
};

// Small white-pill preset chip for the gradient hero, with an active state.
const PresetChip = ({ active, onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className={`px-3 py-2 rounded-lg text-[12.5px] font-bold border shadow-sm transition-all ${
      active
        ? 'bg-white text-[var(--accent-indigo)] border-white'
        : 'bg-white/15 text-white border-white/30 hover:bg-white/25'
    }`}
  >
    {children}
  </button>
);

const OCC = {
  Completed: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Done:      { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Missed:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Pending:   { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};
const OccPill = ({ v }) => {
  const s = OCC[v] || OCC.Pending;
  return <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}><span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{v || '—'}</span>;
};
const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)');
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const HodView = () => {
  const { user } = useAuth();
  const role = user?.role || '';
  // Only elevated roles may switch company scope; others stay pinned server-side.
  const canPickCompany = ['admin', 'superadmin', 'om'].includes(role);

  const months = useMemo(() => monthOptions(), []);
  // Preset target months (stable for the session) — the dropdown stays as "Custom".
  const thisMonth = useMemo(() => currentPeriod(), []);
  const lastMonth = useMemo(() => previousPeriod(), []);
  // Stable identity so it can sit in `load`'s dependency list without refetch loops.
  const quarter = useMemo(() => quarterRange(), []);
  // null = single-month mode (`period` drives the query); set = explicit from/to range.
  const [range, setRange] = useState(null);
  const [company, setCompany] = useState('');
  const [member, setMember] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [companies, setCompanies] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Company list for the admin picker.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get('/companies');
        if (alive) setCompanies(Array.isArray(res.data) ? res.data : []);
      } catch {
        if (alive) setCompanies([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getHodDashboard({
        period: period || undefined,
        company_id: company || undefined,
        member_id: member || undefined,
        // from/to override `period` server-side; `period` still goes along as the fallback.
        from: range?.from,
        to: range?.to,
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load HOD dashboard');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, company, member, range]);

  useEffect(() => { load(); }, [load]);

  const hod = data?.hod || {};
  const cards = data?.cards || {};
  const scoreRows = data?.score_rows || [];
  const tracker = data?.tracker || [];
  const alerts = (data?.alerts || []).filter((a) => a?.level !== 'ok');
  const actions = data?.open_actions || [];

  // Keep the selected member in sync with the server's resolved default.
  useEffect(() => {
    if (data?.selected_hod && data.selected_hod !== member) setMember(data.selected_hod);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Companies' }, ...companies.map((c) => ({ id: c._id, name: c.name }))],
    [companies],
  );
  const hodOpts = useMemo(
    () => (data?.hod_options || []).map((h) => ({ id: h.id, name: h.name })),
    [data],
  );

  // Client-side pagination for the two big grids (occurrences & action items).
  const pTracker = usePaged(tracker || [], 12);
  const pActions = usePaged(actions || [], 10);

  const kpis = [
    { value: cards.activities ?? 0,             label: 'Activities',    sub: 'This period',   tone: 'blue',   icon: ListChecks },
    { value: cards.completed ?? 0,              label: 'Completed',     sub: 'Done',          tone: 'green',  icon: CheckCircle2 },
    { value: cards.missed ?? 0,                 label: 'Missed',        sub: 'Not done',      tone: cards.missed ? 'red' : 'plain', icon: XCircle },
    { value: cards.pending ?? 0,                label: 'Pending',       sub: 'Upcoming',      tone: 'yellow', icon: Clock },
    { value: `${cards.completion ?? 0}%`,       label: 'Completion',    sub: 'Done ÷ total',  tone: (cards.completion ?? 0) >= 80 ? 'green' : 'yellow', icon: Target },
    { value: cards.open_actions ?? 0,           label: 'Open Actions',  sub: 'To close',      tone: cards.open_actions ? 'red' : 'plain', icon: ClipboardList },
    { value: `${cards.action_closure ?? 0}%`,   label: 'Action Closure', sub: 'vs 95% target', tone: (cards.action_closure ?? 0) >= 95 ? 'green' : 'yellow', icon: ClipboardCheck },
  ];

  const hodName = hod.name || '—';

  if (loading && !data) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading HOD dashboard…</div>;
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero
        icon={UserCog}
        title="HOD Activity"
        highlight={hodName}
        /* Spell out the active window when it isn't a single month — otherwise the month
           dropdown still reads "July 2026" while the table covers a whole quarter. */
        subtitle={range
          ? `Quarter · ${range.from} → ${range.to}`
          : 'Per-HOD activity scoring & accountability'}
      >
        {canPickCompany && <HeaderSelect value={company} onChange={(v) => { setCompany(v); setMember(''); }} options={companyOpts} />}
        <HeaderSelect value={member} onChange={setMember} options={hodOpts.length ? hodOpts : [{ id: '', name: 'No HODs' }]} />
        {/* Period presets (spec §17: This Month / Last Month / Quarter / Custom).
            The month chips and the dropdown clear `range`, so the two modes can never
            both look active — whatever is highlighted is what the data reflects. */}
        <div className="inline-flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-white/70">Period</span>
          <PresetChip active={!range && period === thisMonth} onClick={() => { setRange(null); setPeriod(thisMonth); }}>This Month</PresetChip>
          <PresetChip active={!range && period === lastMonth} onClick={() => { setRange(null); setPeriod(lastMonth); }}>Last Month</PresetChip>
          <PresetChip active={!!range} onClick={() => setRange(quarter)}>This Quarter</PresetChip>
          <HeaderSelect value={period} onChange={(v) => { setRange(null); setPeriod(v); }} options={months} searchable={false} />
        </div>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* Identity bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-xl text-white font-bold text-[12px] flex items-center justify-center" style={{ background: 'var(--avatar-bg)' }}>
            {hodName.split(' ').map((x) => x[0]).join('').slice(0, 2) || '—'}
          </span>
          <span className="text-[14px] font-extrabold tracking-tight">{hodName}</span>
        </div>
        {hod.id && <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-muted)]"><IdCard size={14} /> {hod.id}</span>}
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
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Month</Th><Th>Activity</Th><Th align="center">Completed</Th><Th align="center">Total</Th>
                <Th align="center">Missed</Th><Th align="center">Pending</Th><Th align="center">Score</Th><Th align="center">%</Th>
              </tr>
            </thead>
            <tbody>
              {scoreRows.map((r, i) => {
                const pct = r.total ? Math.round((r.completed / r.total) * 100) : 0;
                return (
                  <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className={`font-bold ${stickyCell}`}>{r.period_label || r.period || '—'}</Td>
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

      {/* Activity Tracker — Occurrences */}
      <Section title="Activity Tracker — Occurrences" subtitle="Every scheduled occurrence and its outcome" icon={ListChecks}>
        {tracker.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No tracked occurrences this period.</div>
        ) : (
          <>
          <TableShell minWidth={640}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Date</Th><Th>Month</Th><Th>Activity</Th><Th align="center">Status</Th>
              </tr>
            </thead>
            <tbody>
              {pTracker.pageRows.map((r, i) => (
                <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`tabular-nums font-bold ${stickyCell}`}>{r.date}</Td>
                  <Td className="text-[var(--text-muted)]">{periodLabel(r.period) || r.period || '—'}</Td>
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
      <Section title="Needs Attention" subtitle={alerts.length ? `${alerts.length} item${alerts.length > 1 ? 's' : ''}` : 'On track'} icon={AlertTriangle} tone="red">
        {alerts.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-6">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">Nothing urgent. On track.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {alerts.map((t, i) => (
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
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th><Th>Target Date</Th>
                <Th align="center">Status</Th><Th>Learner Delay</Th><Th>Staff Delay</Th><Th>Follow-up</Th>
              </tr>
            </thead>
            <tbody>
              {pActions.pageRows.map((r, i) => (
                <tr key={r.id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                  <Td>{r.action}</Td>
                  <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                  <Td className="tabular-nums text-[var(--text-muted)]">{r.employee_id || '—'}</Td>
                  <Td className="tabular-nums">{r.target || '—'}</Td>
                  <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)', background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)' }}>{r.status}</span></Td>
                  <Td className="font-bold" style={{ color: r.learner_delay === 'On-track' ? 'var(--accent-green)' : r.learner_delay === 'Delayed' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>{r.learner_delay || '—'}</Td>
                  <Td className="font-bold" style={{ color: r.staff_delay === 'On-track' ? 'var(--accent-green)' : r.staff_delay === 'Delayed' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>{r.staff_delay || '—'}</Td>
                  <Td className="text-[var(--text-muted)]">{r.follow_up || '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
          <Pager {...pActions} label="action items" />
          </>
        )}
      </Section>
    </div>
  );
};

export default HodView;
