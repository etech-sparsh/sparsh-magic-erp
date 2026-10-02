import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Briefcase, Users, CalendarClock, CheckCircle2, Clock,
  AlertOctagon, Target, Timer, ClipboardCheck, AlertTriangle,
} from 'lucide-react';
import { DashboardHero, HeaderSelect, HeroButton } from '../../common/dashboardKit';
import OmDashboardBody from '../../common/OmDashboardBody';
import { getStaffDashboard, currentPeriod, periodLabel } from '../../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ OM (SMOps) View — the admin's window into SMOps
   operations, wired to getStaffDashboard. The header lets the admin
   scope by OM + client + period; all scoping is enforced server-side.
   ───────────────────────────────────────────────────────────── */

const buildKpis = (cards = {}) => [
  { value: cards.clients ?? 0,             label: 'Total Clients',      sub: 'Assigned',        tone: 'blue',   icon: Users },
  { value: cards.planned ?? 0,             label: 'Planned',            sub: 'This period',     tone: 'yellow', icon: CalendarClock },
  { value: cards.completed ?? 0,           label: 'Completed',          sub: 'Activities done', tone: 'green',  icon: CheckCircle2 },
  { value: cards.pending ?? 0,             label: 'Pending',            sub: 'Upcoming',        tone: 'yellow', icon: Clock },
  { value: cards.overdue ?? 0,             label: 'Overdue',            sub: 'Past deadline',   tone: 'red',    icon: AlertOctagon },
  { value: `${cards.completion ?? 0}%`,    label: 'Completion',         sub: 'Done ÷ planned',  tone: 'green',  icon: Target },
  { value: cards.avg_delay ?? 0,           label: 'Avg Delay Days',     sub: 'On completed',    tone: 'yellow', icon: Timer },
  { value: `${cards.action_closure ?? 0}%`, label: 'Action Closure',    sub: 'vs 95% target',   tone: 'green',  icon: ClipboardCheck },
  { value: cards.escalations ?? 0,         label: 'Active Escalations', sub: 'Need action',     tone: 'red',    icon: AlertTriangle },
];

const OmSmopsView = () => {
  const [om, setOm] = useState('');
  const [client, setClient] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getStaffDashboard({
        period: period || undefined,
        om_id: om || undefined,
        company_id: client || undefined,
      });
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [period, om, client]);

  useEffect(() => { load(); }, [load]);

  const kpis = useMemo(() => buildKpis(data?.cards || {}), [data]);

  const omOpts = useMemo(
    () => [{ id: '', name: 'All OMs' }, ...(data?.filters?.oms || [])], [data]);
  const clientOpts = useMemo(
    () => [{ id: '', name: 'All Clients' }, ...(data?.filters?.companies || [])], [data]);
  const periodOpts = useMemo(() => {
    const list = data?.filters?.periods || [];
    if (period && !list.some((p) => p.id === period)) {
      return [{ id: period, name: periodLabel(period) || period }, ...list];
    }
    return list.length ? list : [{ id: period, name: periodLabel(period) || period }];
  }, [data, period]);

  const highlight = data?.filters?.oms?.find((o) => o.id === om)?.name
    || (client ? data?.filters?.companies?.find((c) => c.id === client)?.name : 'All OMs');

  return (
    <div className="space-y-5">
      <DashboardHero icon={Briefcase} title="OM Dashboard" highlight={highlight} subtitle="SMOps operational performance across clients">
        <HeaderSelect value={om} onChange={setOm} options={omOpts} />
        <HeaderSelect value={client} onChange={setClient} options={clientOpts} />
        <HeaderSelect value={period} onChange={setPeriod} options={periodOpts} searchable={false} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading dashboard…</p>
        </div>
      ) : (
        <OmDashboardBody
          kpis={kpis}
          activities={data?.activities || []}
          matrix={data?.clients_grid || []}
          actions={data?.open_actions || []}
          action_required={data?.action_required || []}
        />
      )}
    </div>
  );
};

export default OmSmopsView;
