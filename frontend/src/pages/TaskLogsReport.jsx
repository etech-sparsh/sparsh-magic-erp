import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ScrollText, RefreshCw, Download, Search, Mail, MessageCircle, Layers,
  CheckCircle2, XCircle, MinusCircle, ChevronLeft, ChevronRight,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../features/tpms/common/dashboardKit';
import { getTaskLogs } from '../services/taskApi';
import { useNotification } from '../context/NotificationContext';

/* ─────────────────────────────────────────────────────────────
   Task & Delegation ▸ Notification Logs

   Every task email / WhatsApp that was attempted, with the delivery result. Backed by
   GET /tasks/logs (task_logs_service), which reads the shared `notifications` ledger and
   scopes it to `task_*` slugs. Admin only.

   The KPI counts and the 14-day sparkline are aggregated server-side over the WHOLE
   filtered set, so they describe every matching send — not just the page in the table.
   ───────────────────────────────────────────────────────────── */

const PAGE = 100;
const ALL = '__all__';

const CHANNELS = [
  { id: 'email', name: 'Email', icon: Mail },
  { id: 'whatsapp', name: 'WhatsApp', icon: MessageCircle },
  { id: ALL, name: 'All channels', icon: Layers },
];

// Delivery status is free text from whichever path logged the send, so it is bucketed by
// substring here exactly as the backend buckets it for the KPI counts.
const classify = (v) => {
  const s = String(v || '').toLowerCase();
  if (s.includes('sent') || s.includes('success')) return 'Sent';
  if (s.includes('fail') || s.includes('error')) return 'Failed';
  return 'Skipped';
};
const TONE = {
  Sent: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', bd: 'var(--accent-green-border)' },
  Failed: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)', bd: 'var(--accent-red-border)' },
  Skipped: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};

const StatusPill = ({ value }) => {
  const t = TONE[classify(value)] || TONE.Skipped;
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.c }} />
      {value || '—'}
    </span>
  );
};

/** 14-day send-volume sparkline. Inline SVG — no extra dependency. */
const Sparkline = ({ points }) => {
  const pts = Array.isArray(points) ? points : [];
  if (!pts.length) return null;
  const max = Math.max(1, ...pts.map(p => p?.count || 0));
  const bw = 10;
  const gap = 5;
  const H = 44;
  const W = pts.length * (bw + gap) - gap;
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${Math.max(W, 1)} ${H}`} preserveAspectRatio="none"
      role="img" aria-label="Notification volume, last 14 days">
      {pts.map((p, i) => {
        const h = Math.max(2, Math.round(((p?.count || 0) / max) * (H - 4)));
        return (
          <rect key={p?.key || i} x={i * (bw + gap)} y={H - h} width={bw} height={h} rx={2}
            fill="var(--accent-indigo)" opacity={p?.count ? 0.85 : 0.18}>
            <title>{`${p?.key || ''}: ${p?.count || 0}`}</title>
          </rect>
        );
      })}
    </svg>
  );
};

const TaskLogsReport = () => {
  const { showError } = useNotification();
  const [channel, setChannel] = useState('email');
  const [status, setStatus] = useState(ALL);
  const [event, setEvent] = useState(ALL);
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [skip, setSkip] = useState(0);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  // `search` is debounced so typing doesn't fire a request per keystroke.
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  const params = useMemo(() => ({
    channel: channel === ALL ? '' : channel,
    status: status === ALL ? undefined : status,
    event: event === ALL ? undefined : event,
    search: debounced || undefined,
    from: dateFrom || undefined,
    to: dateTo || undefined,
    skip,
    limit: PAGE,
  }), [channel, status, event, debounced, dateFrom, dateTo, skip]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getTaskLogs(params);
      setData(res.data || null);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load notification logs.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [params, showError]);

  useEffect(() => { load(); }, [load]);
  // Any change to what is being filtered restarts the paging.
  useEffect(() => { setSkip(0); }, [channel, status, event, debounced, dateFrom, dateTo]);

  const counts = data?.counts || {};
  const rows = data?.rows || [];
  const columns = data?.columns || [];
  const total = counts.total || 0;
  const pageEnd = Math.min(skip + PAGE, total);

  const exportCsv = () => {
    if (!rows.length) return;
    const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [columns, ...rows].map(r => r.map(escape).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `task-notification-logs-${channel === ALL ? 'all' : channel}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5 pb-24">
      <DashboardHero
        icon={ScrollText}
        title="Notification Logs"
        highlight={CHANNELS.find(c => c.id === channel)?.name}
        subtitle="Every task email and WhatsApp that was attempted, and what happened to it"
      >
        <HeaderSelect value={channel} onChange={setChannel} options={CHANNELS} searchable={false} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        <HeroButton icon={Download} onClick={exportCsv}>Export CSV</HeroButton>
      </DashboardHero>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiTile value={total} label="Total Sends" sub="Matching the filters" tone="blue" icon={Layers} />
        <KpiTile value={counts.sent ?? 0} label="Delivered" sub="Sent successfully" tone="green" icon={CheckCircle2} />
        <KpiTile value={counts.failed ?? 0} label="Failed" sub="Delivery error" tone={counts.failed ? 'red' : 'plain'} icon={XCircle} />
        <KpiTile value={counts.skipped ?? 0} label="Other" sub="Neither sent nor failed" tone="plain" icon={MinusCircle} />
      </div>

      <Section title="Last 14 days" subtitle="Send volume per day, across everything the filters match" icon={Layers}>
        <div className="px-5 py-4"><Sparkline points={data?.spark} /></div>
      </Section>

      <Section
        title="Delivery log"
        subtitle={total ? `${skip + 1}–${pageEnd} of ${total}` : 'No sends match these filters'}
        icon={ScrollText}
      >
        <div className="px-5 py-3 flex flex-wrap items-center gap-2.5 border-b border-[var(--border)]">
          <FilterSelect value={event} onChange={setEvent}
            options={[{ id: ALL, name: 'All actions' }, ...(data?.events || [])]} />
          <FilterSelect value={status} onChange={setStatus} searchable={false}
            options={[{ id: ALL, name: 'Any status' }, { id: 'sent', name: 'Sent' }, { id: 'failed', name: 'Failed' }]} />
          <label className="flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
            From
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="px-2.5 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </label>
          <label className="flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
            To
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="px-2.5 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </label>
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search recipient address or error…"
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>

        {loading && !data ? (
          <div className="px-5 py-16 text-center text-[12.5px] font-bold text-[var(--text-muted)]">Loading logs…</div>
        ) : !rows.length ? (
          <div className="px-5 py-16 text-center text-[12.5px] font-bold text-[var(--text-muted)]">
            No notifications match these filters.
          </div>
        ) : (
          <>
            <TableShell minWidth={1000}>
              <thead className="bg-[var(--table-header-bg)]">
                <tr>{columns.map((c, i) => <Th key={`${c}-${i}`}>{c}</Th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri} className="group border-t border-[var(--border)] hover:bg-[var(--table-hover)]">
                    {row.map((cell, ci) => (
                      <Td key={ci} className={ci === 0 ? 'whitespace-nowrap font-bold' : ''}>
                        {/* Column 5 is Log Status — the one cell worth colouring. */}
                        {ci === 5 ? <StatusPill value={cell} />
                          : (cell === '' || cell === null || cell === undefined ? '—' : String(cell))}
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </TableShell>

            <div className="px-5 py-3 flex items-center justify-between border-t border-[var(--border)]">
              <span className="text-[11px] font-bold text-[var(--text-muted)]">
                Showing {skip + 1}–{pageEnd} of {total}
              </span>
              <div className="flex items-center gap-1.5">
                <button onClick={() => setSkip(Math.max(0, skip - PAGE))} disabled={skip === 0} title="Previous page"
                  className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] enabled:hover:text-[var(--accent-indigo)] disabled:opacity-35 disabled:cursor-not-allowed transition-all">
                  <ChevronLeft size={14} />
                </button>
                <button onClick={() => setSkip(skip + PAGE)} disabled={pageEnd >= total} title="Next page"
                  className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] enabled:hover:text-[var(--accent-indigo)] disabled:opacity-35 disabled:cursor-not-allowed transition-all">
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </Section>
    </div>
  );
};

export default TaskLogsReport;
