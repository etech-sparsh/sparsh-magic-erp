import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Download, ScrollText, Search, CheckCircle2, XCircle, MinusCircle, Layers,
  MessageCircle, Mail,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import { getLogsReport } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Logs Report — WhatsApp / Email notification delivery
   logs with status KPIs plus date + status + quick filters and
   full-text search. Data comes from the admin-only
   GET /tpms/reports/logs endpoint (tpms_dashboard_service.get_logs_report):
   { type, columns[], rows[][], counts{total,sent,failed,skipped},
     spark[], truncated, total, skip, limit }.
   Rows are positional arrays keyed to `columns`.
   ───────────────────────────────────────────────────────────── */

const PAGE = 200;

const classifyStatus = (v) => {
  const s = String(v || '').toLowerCase();
  if (s.includes('sent') || s.includes('success')) return 'Sent';
  if (s.includes('fail')) return 'Failed';
  return 'Skipped';
};
const STATUS = {
  Sent:    { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Failed:  { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Skipped: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};
const StatusPill = ({ v }) => {
  const s = STATUS[classifyStatus(v)] || STATUS.Skipped;
  return <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border" style={{ color: s.c, background: s.bg, borderColor: s.bd }}>{v || '—'}</span>;
};

const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

// Compact 14-day message-volume sparkline (inline SVG, no extra deps).
// `points` is [{ key: 'yyyy-mm-dd', count }]. Bars stretch to fill width.
const SPARK_DAYS = 14;
const Sparkline = ({ points }) => {
  const pts = Array.isArray(points) ? points : [];
  const n = pts.length || 1;
  const max = Math.max(1, ...pts.map((p) => p?.count || 0));
  const bw = 8;
  const gap = 4;
  const H = 40;
  const W = n * (bw + gap) - gap;
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${Math.max(W, 1)} ${H}`} preserveAspectRatio="none" role="img" aria-label="Message volume, last 14 days">
      {pts.map((p, i) => {
        const c = p?.count || 0;
        const h = c > 0 ? Math.max(2, Math.round((c / max) * (H - 2))) : 1;
        return (
          <rect key={p?.key || i} x={i * (bw + gap)} y={H - h} width={bw} height={h} rx={2}
            fill={c > 0 ? 'var(--accent-indigo)' : 'var(--border)'}>
            <title>{`${p?.key || ''}: ${c}`}</title>
          </rect>
        );
      })}
    </svg>
  );
};

// Quick presets set the from/to date range that is sent to the server.
const iso = (d) => d.toISOString().slice(0, 10);
const rangeFor = (k) => {
  const now = new Date();
  const to = iso(now);
  if (k === 'today') return { from: to, to };
  if (k === '7d')  { const f = new Date(now); f.setDate(f.getDate() - 7);  return { from: iso(f), to }; }
  if (k === '30d') { const f = new Date(now); f.setDate(f.getDate() - 30); return { from: iso(f), to }; }
  return { from: '', to: '' };
};
const QUICK = [{ k: 'today', label: 'Today' }, { k: '7d', label: '7d' }, { k: '30d', label: '30d' }, { k: 'all', label: 'All' }];

const LogsReport = () => {
  useAuth(); // endpoint is admin-only; a non-admin receives 403 (handled below).

  const [channel, setChannel] = useState('email');
  const [status, setStatus] = useState('All');
  const [side, setSide] = useState('All');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [quick, setQuick] = useState('all');
  const [skip, setSkip] = useState(0);
  const [q, setQ] = useState('');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getLogsReport({
        channel,
        status: status !== 'All' ? status : undefined,
        side: side !== 'All' ? side.toLowerCase() : undefined,
        from: from || undefined,
        to: to || undefined,
        skip,
        limit: PAGE,
      });
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(
        e.response?.status === 403
          ? 'You do not have permission to view delivery logs (admin only).'
          : (e.response?.data?.detail || 'Failed to load logs report'),
      );
    } finally {
      setLoading(false);
    }
  }, [channel, status, side, from, to, skip]);

  useEffect(() => { load(); }, [load]);

  // Reset paging whenever the query changes.
  const resetPaging = () => setSkip(0);
  const pickChannel = (k) => { setChannel(k); resetPaging(); };
  const pickStatus = (v) => { setStatus(v); resetPaging(); };
  const pickSide = (v) => { setSide(v); resetPaging(); };
  const pickFrom = (v) => { setFrom(v); setQuick('all'); resetPaging(); };
  const pickTo = (v) => { setTo(v); setQuick('all'); resetPaging(); };
  const pickQuick = (k) => { const r = rangeFor(k); setQuick(k); setFrom(r.from); setTo(r.to); resetPaging(); };

  const columns = useMemo(() => data?.columns || [], [data]);
  const allRows = useMemo(() => data?.rows || [], [data]);
  const counts = data?.counts || {};
  const total = data?.total ?? 0;
  const truncated = !!data?.truncated;

  const statusIdx = columns.indexOf('Log Status');
  const errorIdx = columns.indexOf('Error');

  // Client-side text search over the returned page (server has no search param).
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return allRows;
    return allRows.filter((r) => (r || []).join(' ').toLowerCase().includes(needle));
  }, [allRows, q]);

  const pageClassified = allRows.length || 1;
  const pct = pageClassified ? Math.round(((counts.sent || 0) / pageClassified) * 100) : 0;
  const kpis = [
    { value: total,               label: 'Total',   sub: channel === 'whatsapp' ? 'WhatsApp' : 'Email', tone: 'blue',   icon: Layers },
    { value: counts.sent ?? 0,    label: 'Sent',    sub: `${pct}% of page`,   tone: 'green',  icon: CheckCircle2 },
    { value: counts.failed ?? 0,  label: 'Failed',  sub: 'needs review',      tone: 'red',    icon: XCircle },
    { value: counts.skipped ?? 0, label: 'Skipped', sub: 'no phone / no tpl', tone: 'yellow', icon: MinusCircle },
  ];

  // 14-day volume sparkline: prefer a backend `spark[]` daily series; otherwise
  // derive it client-side by grouping the loaded rows' timestamps by calendar day.
  const spark = useMemo(() => {
    const today = new Date();
    const buckets = [];
    const idxByKey = {};
    for (let i = SPARK_DAYS - 1; i >= 0; i -= 1) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const key = iso(d);
      idxByKey[key] = buckets.length;
      buckets.push({ key, count: 0 });
    }
    const series = Array.isArray(data?.spark) ? data.spark : null;
    if (series && series.length) {
      if (series.every((p) => typeof p === 'number')) {
        const tail = series.slice(-SPARK_DAYS);
        tail.forEach((v, i) => {
          const b = buckets[buckets.length - tail.length + i];
          if (b) b.count = Number(v) || 0;
        });
      } else {
        series.forEach((p) => {
          const key = String(p?.date ?? p?.day ?? p?.key ?? '').slice(0, 10);
          const v = Number(p?.count ?? p?.value ?? 0);
          if (key in idxByKey && Number.isFinite(v)) buckets[idxByKey[key]].count = v;
        });
      }
      return buckets;
    }
    const dateIdx = columns.findIndex((c) => /date|time|created|sent|timestamp/i.test(c));
    if (dateIdx >= 0) {
      allRows.forEach((r) => {
        const raw = (r || [])[dateIdx];
        if (!raw) return;
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return;
        const key = iso(d);
        if (key in idxByKey) buckets[idxByKey[key]].count += 1;
      });
    }
    return buckets;
  }, [data, columns, allRows]);
  const sparkTotal = useMemo(() => spark.reduce((a, b) => a + b.count, 0), [spark]);

  // Export the currently loaded page as CSV, entirely client-side (no new API call).
  // Quotes any field containing a comma, quote or newline per RFC-4180.
  const exportCsv = () => {
    if (!columns.length || !allRows.length) return;
    const esc = (c) => {
      const s = String(c ?? '');
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [columns.map(esc).join(','), ...allRows.map((r) => (r || []).map(esc).join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `tpms-logs-${channel}-${iso(new Date())}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const labelCls = 'text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]';
  const inputCls = 'px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]';

  const pageStart = total ? skip + 1 : 0;
  const pageEnd = skip + allRows.length;

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={ScrollText} title="Logs Report" subtitle="Notification delivery logs across channels">
        {/* channel toggle */}
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {[{ k: 'whatsapp', label: 'WhatsApp', icon: MessageCircle }, { k: 'email', label: 'Email', icon: Mail }].map((c) => (
            <button key={c.k} onClick={() => pickChannel(c.k)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${channel === c.k ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <c.icon size={13} /> {c.label}
            </button>
          ))}
        </div>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        <HeroButton icon={Download} onClick={exportCsv}>Export CSV</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* 14-day message volume sparkline */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="flex items-center justify-between mb-2">
          <span className={labelCls}>Volume · last 14 days</span>
          <span className="text-[11px] font-bold text-[var(--text-muted)] tabular-nums">{sparkTotal} msg{sparkTotal === 1 ? '' : 's'}</span>
        </div>
        <Sparkline points={spark} />
      </div>

      {/* Filter bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 items-end">
          <label className="flex flex-col gap-1"><span className={labelCls}>From</span><input type="date" value={from} onChange={(e) => pickFrom(e.target.value)} className={inputCls} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>To</span><input type="date" value={to} onChange={(e) => pickTo(e.target.value)} className={inputCls} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>Status</span><FilterSelect value={status} onChange={pickStatus} options={['All', 'Sent', 'Failed', 'Skipped']} /></label>
          <label className="flex flex-col gap-1"><span className={labelCls}>Side</span><FilterSelect value={side} onChange={pickSide} options={['All', 'Staff', 'Company']} /></label>
          <div className="flex flex-col gap-1">
            <span className={labelCls}>Quick</span>
            <div className="flex items-center gap-1">
              {QUICK.map((qb) => (
                <button key={qb.k} onClick={() => pickQuick(qb.k)}
                  className={`px-2.5 py-2 rounded-lg text-[12px] font-bold transition-all border ${quick === qb.k ? 'text-white border-transparent' : 'text-[var(--text-muted)] border-[var(--border)] hover:bg-[var(--input-bg)]'}`}
                  style={quick === qb.k ? { background: 'var(--btn-primary)' } : undefined}>{qb.label}</button>
              ))}
            </div>
          </div>
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1">
            <span className={labelCls}>Search</span>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search this page…" className={`${inputCls} w-full pl-9`} />
            </div>
          </label>
        </div>
      </div>

      {/* Logs table */}
      <Section title={`${channel === 'whatsapp' ? 'WhatsApp' : 'Email'} Logs`} subtitle={`${rows.length} row${rows.length === 1 ? '' : 's'}${truncated ? ` of ${total}` : ''}`} icon={channel === 'whatsapp' ? MessageCircle : Mail}>
        <TableShell minWidth={1000}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              {columns.map((c, ci) => (
                <Th key={c} className={ci === 0 ? stickyHead : undefined} align={c === 'Log Status' ? 'center' : undefined}>{c}</Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                {columns.map((c, ci) => {
                  const val = (r || [])[ci];
                  if (ci === statusIdx) return <Td key={ci} align="center"><StatusPill v={val} /></Td>;
                  if (ci === errorIdx) return <Td key={ci} className="max-w-[240px] truncate" style={{ color: classifyStatus((r || [])[statusIdx]) === 'Failed' ? 'var(--accent-red)' : 'var(--text-muted)' }}>{val || '—'}</Td>;
                  return <Td key={ci} className={`whitespace-nowrap ${ci === 0 ? `tabular-nums font-bold ${stickyCell}` : 'font-medium'}`}>{val || '—'}</Td>;
                })}
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={Math.max(columns.length, 1)} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">No logs match your filters.</td></tr>
            )}
            {loading && (
              <tr><td colSpan={Math.max(columns.length, 1)} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading logs…</td></tr>
            )}
          </tbody>
        </TableShell>

        {/* Server-side paging */}
        {total > PAGE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)]">
            <span className="text-[12px] font-bold text-[var(--text-muted)] tabular-nums">{pageStart}–{pageEnd} of {total}</span>
            <div className="flex items-center gap-2">
              <button onClick={() => setSkip((s) => Math.max(0, s - PAGE))} disabled={skip === 0 || loading}
                className="px-3 py-1.5 rounded-lg text-[12px] font-bold border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--input-bg)] disabled:opacity-40 disabled:cursor-not-allowed">Prev</button>
              <button onClick={() => setSkip((s) => s + PAGE)} disabled={pageEnd >= total || loading}
                className="px-3 py-1.5 rounded-lg text-[12px] font-bold border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--input-bg)] disabled:opacity-40 disabled:cursor-not-allowed">Next</button>
            </div>
          </div>
        )}
      </Section>
    </div>
  );
};

export default LogsReport;
