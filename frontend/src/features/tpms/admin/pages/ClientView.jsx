import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  RefreshCw, Building2, Target, Gauge, CheckCircle2, ClipboardList, Star,
  ListChecks, AlertTriangle, CalendarClock, Download,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, Progress, TableShell, KpiTile,
  usePaged, Pager, Fraction,
} from '../../common/dashboardKit';
import { getClientDashboard, exportClientReport, currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import api from '../../../../services/api';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Client View — the "Client Dashboard" for a single
   client: an activity scorecard (success measures) + pending actions.
   Staff/admin pick which client company to view; data is company-scoped
   server-side (getClientDashboard → tpms_dashboard_service.get_learner_dashboard).
   ───────────────────────────────────────────────────────────── */

/* Last 12 months as { value: 'YYYY-MM', label: 'Jul26' }. */
const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ value, label: periodLabel(value) || value });
  }
  return out;
};

const pct = (v) => (v == null || v === '' ? '—' : `${v}%`);

/* Backend row status → pill styling (rows[].status = Met | Partial | Not Met). */
const STATUS_STYLE = {
  'Met':     { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'Partial': { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'Not Met': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};

/* Company-level health band (spec §7): STRONG ≥95 · GOOD ≥85 · WATCH ≥70 · AT-RISK below. */
const BAND_TONE = {
  'STRONG':  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  'GOOD':    { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  'WATCH':   { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  'AT-RISK': { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};

const Pill = ({ label }) => {
  const s = STATUS_STYLE[label] || STATUS_STYLE.Partial;
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{label}
    </span>
  );
};

/* Delay labels come from _delay_label: "On time" | "—" | "<n>d" (overdue). */
const delayColor = (v) => {
  if (v === 'On time') return 'var(--accent-green)';
  if (!v || v === '—') return 'var(--text-muted)';
  if (/pending/i.test(v)) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const ClientView = () => {
  const months = useMemo(() => monthOptions(), []);
  const [companies, setCompanies] = useState([]);
  const [company, setCompany] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  // Download window. 'month' follows the picker above; 'range' takes explicit dates (set both
  // the same for a single day); 'all' exports the client's whole history.
  const [dlOpen, setDlOpen] = useState(false);
  // Anchored with position:fixed off the button's own rect. DashboardHero is `overflow-hidden`
  // (its gradient bloom depends on that), so an absolutely-positioned panel inside it gets
  // clipped to the header band and only a sliver shows.
  const dlBtnRef = useRef(null);
  const [dlPos, setDlPos] = useState(null);
  const [dlMode, setDlMode] = useState('month');
  const [dlFrom, setDlFrom] = useState('');
  const [dlTo, setDlTo] = useState('');

  // Company roster for the picker.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get('/companies');
        if (!alive) return;
        const list = (res.data || []).map((c) => ({ id: String(c._id || c.id || ''), name: c.name || c._id || c.id }));
        setCompanies(list);
        if (list.length) setCompany((prev) => prev || list[0].id);
      } catch {
        if (alive) setError('Failed to load companies');
      }
    })();
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    if (!company) { setData(null); setError('Select a client to view their dashboard.'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await getClientDashboard({ period, company_id: company });
      if (res.data?.error) { setData(null); setError(res.data.error); }
      else setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [company, period]);

  useEffect(() => { load(); }, [load]);

  // Download the selected client's whole TPMS record as .xlsx. The workbook is built
  // server-side (tpms_client_export_service) so the export carries the client's full history,
  // not just the rows this screen happens to have fetched for one month.
  const download = useCallback(async () => {
    if (!company || downloading) return;
    setDownloading(true);
    try {
      const params = { company_id: company, period };
      if (dlMode === 'all') params.all_time = true;
      else if (dlMode === 'range') {
        // Either bound may be left open — the backend treats a missing side as unbounded.
        if (dlFrom) params.from = dlFrom;
        if (dlTo) params.to = dlTo;
      }
      const res = await exportClientReport(params);
      // Prefer the filename the server chose — it carries the client name and period.
      const disp = res.headers?.['content-disposition'] || '';
      const match = /filename="?([^"]+)"?/.exec(disp);
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = match ? match[1] : `TPMS report ${period}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not download the report. Please try again.');
    } finally {
      setDownloading(false);
      setDlOpen(false);
    }
  }, [company, period, downloading, dlMode, dlFrom, dlTo]);

  const rows = data?.rows || [];
  const pending = data?.pending_actions || [];
  const cards = data?.cards || {};
  const opCards = data?.op_cards || {};
  const clientName = data?.company || companies.find((c) => c.id === company)?.name || 'client';
  const pPending = usePaged(pending || [], 10);

  const kpis = [
    { value: opCards.planned ?? 0,          label: 'Total Planned',   sub: 'Scheduled this period', tone: 'blue', icon: CalendarClock },
    { value: cards.total ?? 0,              label: 'Activities',      sub: 'Tracked',          tone: 'blue',   icon: ListChecks },
    { value: `${cards.avg_score ?? 0}%`,    label: 'Avg Achievement', sub: 'Success measure',  tone: (cards.avg_score ?? 0) >= 80 ? 'green' : 'yellow', icon: Target },
    { value: cards.met ?? 0,               label: 'On Track',        sub: 'Met (≥ 100%)',     tone: 'green',  icon: CheckCircle2 },
    { value: `${opCards.completion ?? 0}%`, label: 'Completion',      sub: 'Done ÷ planned',   tone: 'green',  icon: Star },
    { value: pending.length,               label: 'Pending Actions', sub: 'Open items',       tone: pending.length ? 'red' : 'plain', icon: ClipboardList },
    { value: periodLabel(period) || period, label: 'Period',         sub: 'Reporting window', tone: 'plain',  icon: Gauge },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Building2} title="Client Dashboard" highlight={data?.company || undefined} subtitle="Activity scorecard & success measures for the selected client">
        <HeaderSelect value={company} onChange={setCompany} options={companies} />
        <HeaderSelect value={period} onChange={setPeriod} options={months} searchable={false} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        {/* Only meaningful once a client is picked — the report IS the client's record. */}
        {company && (
          <div className="relative">
            <span ref={dlBtnRef}>
              <HeroButton icon={Download} onClick={() => {
                const r = dlBtnRef.current?.getBoundingClientRect();
                if (r) setDlPos({ top: r.bottom + 8, right: Math.max(8, window.innerWidth - r.right) });
                setDlOpen((o) => !o);
              }}>
                {downloading ? 'Preparing…' : 'Download Report'}
              </HeroButton>
            </span>
            {dlOpen && dlPos && (
              <>
                {/* Click-away closes without downloading. */}
                <div className="fixed inset-0 z-[65]" onClick={() => setDlOpen(false)} />
                <div className="fixed z-[70] w-[300px] p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-xl text-left"
                  style={{ top: dlPos.top, right: dlPos.right }}>
                  <p className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mb-2.5">
                    What should the report cover?
                  </p>
                  <div className="space-y-1.5">
                    {[
                      ['month', `Selected month — ${periodLabel(period) || period}`],
                      ['range', 'Specific dates'],
                      ['all', "All time — the client's full history"],
                    ].map(([id, label]) => (
                      <label key={id}
                        className={`flex items-start gap-2 px-2.5 py-2 rounded-xl cursor-pointer border transition-colors ${
                          dlMode === id
                            ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                            : 'border-[var(--border)] hover:bg-[var(--input-bg)]'}`}>
                        <input type="radio" name="dl-window" className="mt-0.5 shrink-0"
                          checked={dlMode === id} onChange={() => setDlMode(id)} />
                        <span className={`text-[12px] font-bold ${dlMode === id ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>
                          {label}
                        </span>
                      </label>
                    ))}
                  </div>

                  {dlMode === 'range' && (
                    <div className="mt-2.5 grid grid-cols-2 gap-2">
                      <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        From
                        <input type="date" value={dlFrom} onChange={(e) => setDlFrom(e.target.value)}
                          className="mt-1 w-full px-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                      </label>
                      <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        To
                        <input type="date" value={dlTo} onChange={(e) => setDlTo(e.target.value)}
                          className="mt-1 w-full px-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                      </label>
                      <p className="col-span-2 text-[10.5px] font-medium text-[var(--text-muted)] leading-relaxed">
                        Set both to the same date for a single day. Leave one empty to leave that
                        end open.
                      </p>
                    </div>
                  )}

                  <button type="button" onClick={download} disabled={downloading}
                    className="mt-3 w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--accent-indigo)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-60 disabled:cursor-wait">
                    <Download size={13} /> {downloading ? 'Preparing…' : 'Download'}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </DashboardHero>

      {loading && !data && (
        <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading dashboard…</div>
      )}

      {!loading && error && (
        <div className="rounded-2xl border border-[var(--accent-orange-border)] bg-[var(--accent-orange-bg)] px-4 py-3 flex items-center gap-2.5 text-[12px] font-bold text-[var(--accent-orange)]">
          <AlertTriangle size={15} />
          <span>{error} {!company && 'Pick a client company above.'}</span>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Health banner — spec §7 status band (STRONG / GOOD / WATCH / AT-RISK) */}
          {data.status && (() => {
            const b = BAND_TONE[data.status] || BAND_TONE.WATCH;
            return (
              <div className="rounded-2xl border px-5 py-4 flex items-center justify-between" style={{ background: b.bg, borderColor: b.bd }}>
                <div className="flex items-center gap-3">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: b.c }} />
                  <span className="text-[13px] font-black uppercase tracking-widest" style={{ color: b.c }}>{data.status}</span>
                  <span className="text-[12px] font-bold text-[var(--text-muted)]">{clientName} · {periodLabel(period) || period}</span>
                </div>
                <div className="text-right">
                  <div className="text-[22px] font-black leading-none" style={{ color: b.c }}>{data.completion ?? 0}%</div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Completion</div>
                </div>
              </div>
            );
          })()}

          {/* Summary tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-7 gap-3">
            {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
          </div>

          {/* Single-row activity status grid for the selected client */}
          {data.activities?.length > 0 && (
            <Section title="Activity Status" subtitle="Completion per activity for the selected client & period" icon={ListChecks}>
              <TableShell minWidth={720}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    {data.activities.map((a) => <Th key={a.full} align="center">{a.short}</Th>)}
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-[var(--border)] last:border-0">
                    {data.activities.map((a) => {
                      const cell = (data.clients_grid?.[0]?.cells || {})[a.full];
                      return (
                        <Td key={a.full} align="center">
                          <Fraction v={cell && cell.total ? `${cell.done}/${cell.total}` : ''} status={cell?.status} />
                        </Td>
                      );
                    })}
                  </tr>
                </tbody>
              </TableShell>
            </Section>
          )}

          {/* Activity Scorecard — Success Measures */}
          <Section title="Activity Scorecard — Success Measures" subtitle="Implementation vs. score performance per activity" icon={Target}
            action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{rows.length} activities</span>}>
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
                {rows.map((r, i) => {
                  const ach = r.achievement ?? 0;
                  return (
                    <tr key={`${r.activity}-${i}`} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className="text-[var(--text-muted)] font-bold">{i + 1}</Td>
                      <Td className="font-bold">{r.activity}</Td>
                      <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pct(r.impl_target)}</Td>
                      <Td align="center" className="tabular-nums font-bold">{pct(r.impl_actual)}</Td>
                      <Td align="center" className="tabular-nums text-[var(--text-muted)]">{pct(r.target)}</Td>
                      <Td align="center" className="tabular-nums font-bold">{pct(r.actual)}</Td>
                      <Td align="center" className="font-extrabold">{ach}%</Td>
                      <Td><Progress value={ach} /></Td>
                      <Td align="center"><Pill label={r.status} /></Td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr><td colSpan={9} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activities for this client.</td></tr>
                )}
              </tbody>
            </TableShell>
          </Section>

          {/* Pending Actions */}
          <Section title="Pending Actions" subtitle={pending.length ? `${pending.length} open item${pending.length > 1 ? 's' : ''}` : 'Nothing pending'} icon={AlertTriangle} tone="red">
            {pending.length === 0 ? (
              <div className="flex items-center gap-2.5 px-5 py-6">
                <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
                <p className="text-[13px] font-bold text-[var(--accent-green)]">No pending actions for {clientName}.</p>
              </div>
            ) : (
              <>
              <TableShell minWidth={820}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th className={stickyHead}>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Target Date</Th>
                    <Th align="center">Status</Th><Th>Learner Delay</Th><Th>Staff Delay</Th>
                  </tr>
                </thead>
                <tbody>
                  {pPending.pageRows.map((r, i) => (
                    <tr key={r.id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <Td className={`font-bold ${stickyCell}`}>{r.activity}</Td>
                      <Td>{r.action}</Td>
                      <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                      <Td className="tabular-nums">{r.target || '—'}</Td>
                      <Td align="center">
                        <span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{
                          color: r.status === 'Overdue' ? 'var(--accent-red)' : 'var(--accent-orange)',
                          background: r.status === 'Overdue' ? 'var(--accent-red-bg)' : 'var(--accent-orange-bg)',
                        }}>{r.status}</span>
                      </Td>
                      <Td className="font-bold" style={{ color: delayColor(r.learner_delay) }}>{r.learner_delay || '—'}</Td>
                      <Td className="font-bold" style={{ color: delayColor(r.staff_delay) }}>{r.staff_delay || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              <Pager {...pPending} label="actions" />
              </>
            )}
          </Section>
        </>
      )}
    </div>
  );
};

export default ClientView;
