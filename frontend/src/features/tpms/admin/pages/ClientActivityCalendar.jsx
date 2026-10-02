import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarRange, RefreshCw, RotateCcw, AlertTriangle, X, Clock, Tag, Building2,
  Users2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import { getSchedules, getCalendarFilters } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Client-wise Activity Calendar (H6).

   A full MONTH-GRID calendar (SUN–SAT) of every client's scheduled
   activities for the chosen month — a faithful port of the AppScript
   AdminDashboard `cwc` section. Each day cell shows the day number, a
   count badge, and up to two "Company: Activity" pills coloured by
   status. Clicking a day opens a read-only day-detail modal.

   The whole month is fetched via getSchedules (company_id omitted → all
   clients in the acting admin's scope); every filter runs client-side.
   ───────────────────────────────────────────────────────────── */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const STATUSES = ['Scheduled', 'Rescheduled', 'Completed', 'Cancelled', 'Lapsed'];

/* "Scheduled by" filter — value matches the event's scheduled_by field. */
const SIDE_OPTIONS = [
  { id: '', name: 'Scheduled by: Any' },
  { id: 'internal', name: 'Scheduled by: OM' },
  { id: 'client', name: 'Scheduled by: Client' },
];

/* TPMS status → ERP accent tokens. No hex literals: dark mode comes free. */
const TONE = {
  Scheduled:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  Rescheduled: { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  Completed:   { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Cancelled:   { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
  Lapsed:      { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
};
const toneOf = (s) => TONE[s] || TONE.Scheduled;

/* "Scheduled by" → readable side label (OM / Client) for badges + day modal. */
const sideLabel = (by) => (by === 'internal' ? 'OM' : by === 'client' ? 'Client' : '');
const SIDE_TONE = {
  internal: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  client:   { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
};

const ymd = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

const Badge = ({ status }) => {
  const t = toneOf(status);
  return (
    <span className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      {status}
    </span>
  );
};

const SideBadge = ({ by }) => {
  const t = SIDE_TONE[by];
  if (!t) return null;
  return (
    <span className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      {sideLabel(by)}
    </span>
  );
};

const StatusLegend = () => (
  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5 border-t border-[var(--border)]">
    <span className="text-[10.5px] font-black text-[var(--text-muted)] uppercase tracking-wide">Legend</span>
    {STATUSES.map((s) => {
      const t = toneOf(s);
      return (
        <span key={s} className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
          <span className="w-2.5 h-2.5 rounded-full border" style={{ background: t.c, borderColor: t.bd }} />
          {s}
        </span>
      );
    })}
  </div>
);

/* Read-only day-detail modal (mirrors TpmsCalendar's day drawer, no actions). */
const DayOverlay = ({ title, events, onClose }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()}
      className="w-full max-w-2xl rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border)]">
        <h3 className="text-[14px] font-black text-[var(--text-main)]">{title}</h3>
        <button onClick={onClose} className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)]"><X size={17} /></button>
      </div>
      <div className="px-5 py-4 max-h-[65vh] overflow-y-auto">
        {events.length === 0 ? (
          <p className="text-[12.5px] font-bold text-[var(--text-muted)]">No activities on this day.</p>
        ) : events.map((e) => (
          <div key={e.id} className="rounded-xl border border-[var(--border)] p-3 mb-2.5">
            <div className="flex items-start justify-between gap-2 mb-1.5">
              <h4 className="text-[13.5px] font-black text-[var(--text-main)] inline-flex items-center gap-1.5">
                <Building2 size={13} /> {e.company || 'Unknown client'}
              </h4>
              <div className="flex items-center gap-1.5">
                <SideBadge by={e.scheduled_by} />
                <Badge status={e.status} />
              </div>
            </div>
            <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-1">{e.title || e.activity}</p>
            <div className="text-[11.5px] text-[var(--text-muted)] font-semibold space-y-0.5">
              {e.time && <div className="flex items-center gap-1.5"><Clock size={11} /> {e.time}</div>}
              {e.activity && <div className="flex items-center gap-1.5"><Tag size={11} /> {e.activity}</div>}
              {!!e.departments?.length && <div className="flex items-center gap-1.5"><Users2 size={11} /> {e.departments.join(', ')}</div>}
              {e.scheduled_by_name && (
                <div className="flex items-center gap-1.5">
                  <Users2 size={11} /> Scheduled by {e.scheduled_by_name}{sideLabel(e.scheduled_by) ? ` (${sideLabel(e.scheduled_by)})` : ''}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

const navBtn = 'px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]';

const ClientActivityCalendar = () => {
  // Admin scope: mounted under the admin panel; useAuth supplies the acting user
  // so the month feed is pulled with their org-wide visibility.
  const { user } = useAuth();

  // Stable "now" so month-list memos don't re-run every render.
  const today = useMemo(() => new Date(), []);
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);   // 1-12
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [fCompany, setFCompany] = useState('');  // company_id (as string) or ''
  const [fHod, setFHod] = useState('');           // HOD id (as string) or ''
  const [fOm, setFOm] = useState('');             // OM id (as string) or ''
  const [fSide, setFSide] = useState('');          // 'internal' | 'client' | ''
  const [openDay, setOpenDay] = useState(null);

  // Master filter lists (full company / HOD / OM rosters), fetched once on mount
  // so the dropdowns stay complete even when the month's events are sparse.
  const [masters, setMasters] = useState({ companies: [], hods: [], oms: [] });
  const [mastersLoading, setMastersLoading] = useState(true);
  const [mastersError, setMastersError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      setMastersLoading(true);
      setMastersError('');
      try {
        const { data } = await getCalendarFilters();
        if (!alive) return;
        setMasters({
          companies: data?.companies ?? [],
          hods: data?.hods ?? [],
          oms: data?.oms ?? [],
        });
      } catch (e) {
        if (!alive) return;
        setMastersError(e.response?.data?.detail || 'Failed to load filter options');
        setMasters({ companies: [], hods: [], oms: [] });
      } finally {
        if (alive) setMastersLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Month feed — omit company_id to pull every client in scope.
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await getSchedules({ year, month });
      setEvents(data?.events || []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load the activity calendar');
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => { load(); }, [load]);

  const changeMonth = (delta) => {
    let m = month + delta;
    let y = year;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    setMonth(m); setYear(y);
  };

  const clearFilters = () => { setFCompany(''); setFHod(''); setFOm(''); setFSide(''); };
  const hasFilters = fCompany || fHod || fOm || fSide;

  // If the selected client narrows the HOD list past the current HOD pick, drop it.
  useEffect(() => {
    if (!fCompany || !fHod) return;
    const stillValid = (masters.hods ?? [])
      .some((h) => String(h.id) === fHod && String(h.company_id) === fCompany);
    if (!stillValid) setFHod('');
  }, [fCompany, fHod, masters.hods]);

  // Period select — recent months (12 back incl. current) driving year/month.
  const periodValue = `${year}-${String(month).padStart(2, '0')}`;
  const periodOptions = useMemo(() => {
    const out = [];
    const base = new Date(today.getFullYear(), today.getMonth(), 1);
    for (let i = 0; i < 12; i += 1) {
      const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
      const id = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      out.push({ id, name: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` });
    }
    // Keep the active period selectable even if it's outside the recent window.
    if (!out.some((o) => o.id === periodValue)) {
      out.unshift({ id: periodValue, name: `${MONTHS[month - 1]} ${year}` });
    }
    return out;
  }, [today, periodValue, month, year]);

  const onPeriodChange = (val) => {
    const [y, m] = val.split('-').map(Number);
    if (y && m) { setYear(y); setMonth(m); }
  };

  // Filter option lists come from the master rosters (full company / HOD / OM
  // lists) so a dropdown is never limited to whatever the sparse month happens
  // to contain.
  const companyOptions = useMemo(() => (masters.companies ?? [])
    .map((c) => ({ id: String(c.id), name: c.name || String(c.id) }))
    .sort((a, b) => a.name.localeCompare(b.name)),
  [masters.companies]);

  // "All HODs": full HOD roster. When a client is selected, narrow to that
  // company's HODs via `company_id`.
  const hodOptions = useMemo(() => (masters.hods ?? [])
    .filter((h) => !fCompany || String(h.company_id) === fCompany)
    .map((h) => ({ id: String(h.id), name: h.name || String(h.id) }))
    .sort((a, b) => a.name.localeCompare(b.name)),
  [masters.hods, fCompany]);

  // "All OMs": full OM roster.
  const omOptions = useMemo(() => (masters.oms ?? [])
    .map((o) => ({ id: String(o.id), name: o.name || String(o.id) }))
    .sort((a, b) => a.name.localeCompare(b.name)),
  [masters.oms]);

  // Selected OM's name — used as a fallback match when an event carries no
  // staff_ids but records the scheduler by name.
  const selectedOmName = useMemo(() => {
    if (!fOm) return '';
    const hit = (masters.oms ?? []).find((o) => String(o.id) === fOm);
    return hit?.name || '';
  }, [masters.oms, fOm]);

  const filtered = useMemo(() => events.filter((e) => {
    if (fCompany && String(e.company_id) !== fCompany) return false;
    if (fHod && !(e.member_ids ?? []).map(String).includes(fHod)) return false;
    if (fOm) {
      const staff = (e.staff_ids ?? []).map(String);
      const byId = staff.includes(fOm);
      const byName = staff.length === 0 && selectedOmName
        && e.scheduled_by_name === selectedOmName;
      if (!byId && !byName) return false;
    }
    if (fSide && e.scheduled_by !== fSide) return false;
    return true;
  }), [events, fCompany, fHod, fOm, fSide, selectedOmName]);

  const byDate = useMemo(() => {
    const map = {};
    filtered.forEach((e) => { (map[e.date] ||= []).push(e); });
    return map;
  }, [filtered]);

  const todayStr = ymd(today.getFullYear(), today.getMonth() + 1, today.getDate());

  // KPI counts (client-side, matching AppScript cwc):
  //  Planned   = all events except Cancelled
  //  Completed = status Completed · Lapsed = status Lapsed
  //  of the still-open (Scheduled/Rescheduled): Delayed = past-due, Pending = upcoming
  const stats = useMemo(() => {
    const s = { planned: 0, completed: 0, pending: 0, delayed: 0, lapsed: 0 };
    filtered.forEach((e) => {
      const st = e.status || 'Scheduled';
      if (st === 'Cancelled') return;
      s.planned += 1;
      if (st === 'Completed') { s.completed += 1; return; }
      if (st === 'Lapsed') { s.lapsed += 1; return; }
      if (e.date && e.date < todayStr) s.delayed += 1;
      else s.pending += 1;
    });
    return s;
  }, [filtered, todayStr]);

  const kpis = [
    { value: stats.planned,   label: 'Planned',   sub: 'Total scheduled', tone: 'yellow', icon: CalendarRange },
    { value: stats.completed, label: 'Completed', sub: 'Activities done', tone: 'green',  icon: CalendarRange },
    { value: stats.pending,   label: 'Pending',   sub: 'Upcoming',        tone: 'blue',   icon: Clock },
    { value: stats.delayed,   label: 'Delayed',   sub: 'Past due',        tone: 'red',    icon: AlertTriangle },
    { value: stats.lapsed,    label: 'Lapsed',    sub: 'Auto-lapsed',     tone: 'red',    icon: AlertTriangle },
  ];

  // Grid geometry.
  const firstDow = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={CalendarRange}
        title="Client-wise Activity Calendar"
        highlight={`${MONTHS[month - 1]} ${year}`}
        subtitle="Month grid of every client's scheduled activities"
      >
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {(error || mastersError) && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 flex items-center gap-2.5 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /><span>{error || mastersError}</span>
        </div>
      )}

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden">
        {/* ── Filter row ── */}
        <div className="flex flex-wrap items-center gap-2.5 px-4 py-3 border-b border-[var(--border)]">
          <FilterSelect value={periodValue} onChange={onPeriodChange} options={periodOptions} searchable={false} />
          <FilterSelect value={fCompany} onChange={setFCompany}
            options={[{ id: '', name: mastersLoading ? 'Loading clients…' : 'All Clients' }, ...companyOptions]} />
          <FilterSelect value={fHod} onChange={setFHod}
            options={[{ id: '', name: mastersLoading ? 'Loading HODs…' : 'All HODs' }, ...hodOptions]} />
          <FilterSelect value={fOm} onChange={setFOm}
            options={[{ id: '', name: mastersLoading ? 'Loading OMs…' : 'All OMs' }, ...omOptions]} />
          <FilterSelect value={fSide} onChange={setFSide} options={SIDE_OPTIONS} />
          <button onClick={load} className={`inline-flex items-center gap-1.5 ${navBtn} py-2`}>
            <RefreshCw size={13} /> Refresh
          </button>
          {hasFilters && (
            <button onClick={clearFilters} className={`inline-flex items-center gap-1.5 ${navBtn} py-2`}>
              <RotateCcw size={13} /> Clear
            </button>
          )}
        </div>

        {/* ── KPI tiles ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3 p-4 border-b border-[var(--border)]">
          {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
        </div>

        {/* ── Month nav ── */}
        <div className="flex items-center justify-center gap-4 px-4 py-3">
          <button onClick={() => changeMonth(-1)} className={navBtn} aria-label="Previous month">‹ Prev</button>
          <span className="text-[14px] font-black text-[var(--text-main)] min-w-[160px] text-center">
            {MONTHS[month - 1]} {year}
          </span>
          <button onClick={() => changeMonth(1)} className={navBtn} aria-label="Next month">Next ›</button>
        </div>

        {/* ── Month grid ── */}
        <div className="grid grid-cols-7 gap-px bg-[var(--border)]">
          {DOW.map((d) => (
            <div key={d} className="bg-[var(--table-header-bg)] px-2 py-2 text-center text-[11px] font-black text-[var(--text-muted)]">{d}</div>
          ))}
          {Array.from({ length: firstDow }).map((_, i) => (
            <div key={`e${i}`} className="bg-[var(--bg-card)] min-h-[108px]" />
          ))}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const ds = ymd(year, month, day);
            const evs = byDate[ds] || [];
            const isToday = ds === todayStr;
            return (
              <button key={ds} onClick={() => evs.length && setOpenDay(ds)}
                className={`bg-[var(--bg-card)] min-h-[108px] p-1.5 text-left align-top hover:bg-[var(--table-hover)] transition-colors ${evs.length ? 'cursor-pointer' : 'cursor-default'}`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className={`text-[11.5px] font-black ${isToday
                    ? 'inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--accent-indigo)] text-white'
                    : 'text-[var(--text-muted)]'}`}>{day}</span>
                  {evs.length > 0 && (
                    <span className="inline-flex items-center justify-center text-[10px] font-bold text-white rounded-full px-1.5 py-[1px]"
                      style={{ background: 'var(--accent-indigo)' }}>{evs.length}</span>
                  )}
                </div>
                <div className="space-y-1">
                  {evs.slice(0, 2).map((e) => {
                    const t = toneOf(e.status);
                    return (
                      <div key={e.id} title={`${e.company || ''} — ${e.title || e.activity} · ${e.status}`}
                        className="truncate text-[10px] font-bold px-1.5 py-0.5 rounded border"
                        style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
                        {e.company ? `${e.company}: ` : ''}{e.title || e.activity}
                      </div>
                    );
                  })}
                  {evs.length > 2 && (
                    <div className="text-[10px] font-bold text-[var(--text-muted)] px-1.5">+{evs.length - 2} more</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        <StatusLegend />
        {loading && <div className="px-5 py-3 text-[12px] font-bold text-[var(--text-muted)]">Loading calendar…</div>}
        {!loading && filtered.length === 0 && (
          <div className="px-5 py-8 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Nothing scheduled for {MONTHS[month - 1]} {year}{hasFilters ? ' with these filters' : ''}.
          </div>
        )}
      </div>

      {openDay && (
        <DayOverlay title={`Activities on ${openDay}`} events={byDate[openDay] || []} onClose={() => setOpenDay(null)} />
      )}

      <p className="text-[11px] text-[var(--text-muted)] font-medium px-1">
        Scope: {user?.name || user?.username || 'admin'} · Click a day to see its activities.
      </p>
    </div>
  );
};

export default ClientActivityCalendar;
