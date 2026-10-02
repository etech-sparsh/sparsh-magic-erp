import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Users, ListChecks, CheckCircle2, XCircle, Clock, Gauge, Eye,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile, usePaged, Pager,
} from '../../common/dashboardKit';
import { useAuth } from '../../../../context/AuthContext';
import { getEmployeeActivityDashboard, currentPeriod } from '../../../../services/tpmsApi';
import api from '../../../../services/api';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Employee Tasks — "Company Employees — Task Activity".
   Per-employee task-activity summary, wired to the employee-activity
   dashboard endpoint (getEmployeeActivity in tpms_dashboard_service.py).
   Filters (company / period / employee / designation) are applied
   SERVER-side, so the KPI cards always reflect the current selection.
   ───────────────────────────────────────────────────────────── */

const scoreColor = (v) => (v >= 80 ? 'var(--accent-green)' : v >= 60 ? 'var(--accent-orange)' : v > 0 ? 'var(--accent-red)' : 'var(--text-muted)');

const ScoreBar = ({ v }) => (
  <div className="flex items-center gap-2 min-w-[130px]">
    <div className="h-2 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${v}%`, background: v ? scoreColor(v) : 'transparent' }} />
    </div>
    <span className="text-[11px] font-bold tabular-nums" style={{ color: scoreColor(v) }}>{v}%</span>
  </div>
);

// Last 12 months as { id: 'YYYY-MM', name: 'Jul26' } so the current period is always pickable.
const periodOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const id = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const name = `${d.toLocaleString('en-US', { month: 'short' })}${String(d.getFullYear()).slice(-2)}`;
    out.push({ id, name });
  }
  return out;
};

const initials = (name = '') => name.split(' ').filter(Boolean).map((x) => x[0]).join('').slice(0, 3) || '?';
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

const EmployeeTasks = () => {
  const { user } = useAuth();

  const [company, setCompany] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [member, setMember] = useState('');
  const [designation, setDesignation] = useState('');
  const [scheduledBy, setScheduledBy] = useState('');

  const [companies, setCompanies] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [drill, setDrill] = useState(null);   // employee whose per-activity breakdown is open

  // "All Months" (empty id) lets the backend aggregate across every month.
  const months = useMemo(() => [{ id: '', name: 'All Months' }, ...periodOptions()], []);

  // Company list for the picker (role-scoped server-side by the endpoint too).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get('/companies');
        if (alive) setCompanies(Array.isArray(res.data) ? res.data : (res.data?.companies || []));
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
      const res = await getEmployeeActivityDashboard({
        period: period || undefined,
        company_id: company || undefined,
        member_id: member || undefined,
        designation: designation || undefined,
        scheduled_by: scheduledBy || undefined,
      });
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load employee activity');
    } finally {
      setLoading(false);
    }
  }, [period, company, member, designation, scheduledBy]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows || [];
  const cards = data?.cards || {};
  const canPick = data?.can_pick_company ?? ((user?.role || '').toLowerCase() !== 'client');
  const pRows = usePaged(rows || [], 12);

  const companyOpts = useMemo(() => {
    const src = data?.company_options?.length
      ? data.company_options
      : companies.map((c) => ({ id: String(c._id ?? c.id ?? ''), name: c.name ?? c.company_name ?? '' }));
    return [{ id: '', name: 'All Companies' }, ...src];
  }, [data, companies]);

  const memberOpts = useMemo(
    () => [{ id: '', name: 'All Employees' }, ...(data?.member_options || [])], [data]);
  const designationOpts = useMemo(
    () => ['', ...(data?.designation_options || [])].map((d) => ({ id: d, name: d || 'All Designations' })), [data]);
  const scheduledByOpts = useMemo(
    () => [{ id: '', name: 'All Scheduled by' }, { id: 'internal', name: 'OM/SMOps' }, { id: 'client', name: 'Client' }], []);

  const clearFilters = () => { setCompany(''); setPeriod(currentPeriod()); setMember(''); setDesignation(''); setScheduledBy(''); };

  const kpis = [
    { value: cards.total_employees ?? 0,   label: 'Employees',   sub: 'In scope',          tone: 'blue',   icon: Users },
    { value: cards.total_activities ?? 0,  label: 'Total Tasks', sub: 'This period',       tone: 'yellow', icon: ListChecks },
    { value: cards.completed ?? 0,         label: 'Completed',   sub: 'Done',              tone: 'green',  icon: CheckCircle2 },
    { value: cards.missed ?? 0,            label: 'Missed',      sub: 'Overdue/not done',  tone: cards.missed ? 'red' : 'plain', icon: XCircle },
    { value: cards.pending ?? 0,           label: 'Pending',     sub: 'Upcoming',          tone: 'yellow', icon: Clock },
    { value: `${cards.avg_score ?? 0}%`,   label: 'Avg Score',   sub: 'Across employees',  tone: (cards.avg_score ?? 0) >= 60 ? 'green' : 'yellow', icon: Gauge },
  ];

  if (loading && !data) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading employee activity…</div>;
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={Users} title="Company Employees — Task Activity" subtitle="Per-employee task completion & scoring">
        {canPick && <HeaderSelect value={company} onChange={setCompany} options={companyOpts} />}
        <HeaderSelect value={period} onChange={setPeriod} options={months} searchable={false} />
        <HeaderSelect value={member} onChange={setMember} options={memberOpts} />
        <HeaderSelect value={designation} onChange={setDesignation} options={designationOpts} />
        <HeaderSelect value={scheduledBy} onChange={setScheduledBy} options={scheduledByOpts} />
        <button onClick={clearFilters} className="inline-flex items-center px-3.5 py-2 rounded-lg bg-white/15 text-white text-[12.5px] font-bold ring-1 ring-white/25 hover:bg-white/25 transition-all">Clear</button>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((t) => <KpiTile key={t.label} {...t} />)}
      </div>

      {/* Employee Activity Summary */}
      <Section title="Employee Activity Summary" subtitle={`${rows.length} employee${rows.length === 1 ? '' : 's'} in scope`} icon={ListChecks}>
        <TableShell minWidth={1040}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Employee</Th><Th>Designation</Th><Th>Department</Th>
              <Th align="center">Total</Th><Th align="center">Completed</Th><Th align="center">Missed</Th><Th align="center">Pending</Th>
              <Th align="center">Score</Th><Th>Progress</Th><Th align="right">Action</Th>
            </tr>
          </thead>
          <tbody>
            {pRows.pageRows.map((e, i) => {
              const sc = e.score ?? 0;
              return (
                <tr key={e.id ?? i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>
                    <div className="flex items-center gap-2.5">
                      <span className="w-7 h-7 rounded-full text-white text-[9px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {initials(e.name)}
                      </span>
                      {e.name}
                    </div>
                  </Td>
                  <Td className="text-[var(--accent-indigo)] font-bold uppercase text-[11px] tracking-wide">{e.designation || '—'}</Td>
                  <Td className="text-[var(--text-muted)] uppercase text-[11px] tracking-wide">{e.department || '—'}</Td>
                  <Td align="center" className="tabular-nums font-bold">{e.total ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-green)]">{e.completed ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-red)]">{e.missed ?? 0}</Td>
                  <Td align="center" className="font-bold text-[var(--accent-orange)]">{e.pending ?? 0}</Td>
                  <Td align="center" className="font-extrabold" style={{ color: scoreColor(sc) }}>{sc}%</Td>
                  <Td><ScoreBar v={sc} /></Td>
                  <Td align="right">
                    <button onClick={() => setDrill(e)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] hover:border-[var(--accent-indigo-border)] transition-all">
                      <Eye size={13} /> View
                    </button>
                  </Td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={10} className="px-5 py-12 text-center text-[13px] font-bold text-[var(--text-muted)]">No employees match your filters.</td></tr>
            )}
          </tbody>
        </TableShell>
        <Pager {...pRows} label="employees" />
      </Section>

      {/* Per-employee drill-down: the activity-by-activity breakdown behind the row totals. */}
      {drill && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={() => setDrill(null)}>
          <div onClick={(ev) => ev.stopPropagation()} className="w-full max-w-lg rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <div>
                <h3 className="text-[15px] font-black text-[var(--text-main)]">{drill.name}</h3>
                <p className="text-[11.5px] font-bold text-[var(--text-muted)] uppercase tracking-wide">{drill.designation || '—'} · {drill.department || '—'}</p>
              </div>
              <button onClick={() => setDrill(null)} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-all"><XCircle size={18} /></button>
            </div>
            <div className="px-5 py-3 grid grid-cols-4 gap-2 text-center border-b border-[var(--border)]">
              <div><div className="text-[16px] font-black text-[var(--text-main)] tabular-nums">{drill.total ?? 0}</div><div className="text-[9.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">Total</div></div>
              <div><div className="text-[16px] font-black text-[var(--accent-green)] tabular-nums">{drill.completed ?? 0}</div><div className="text-[9.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">Done</div></div>
              <div><div className="text-[16px] font-black text-[var(--accent-red)] tabular-nums">{drill.missed ?? 0}</div><div className="text-[9.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">Missed</div></div>
              <div><div className="text-[16px] font-black text-[var(--accent-orange)] tabular-nums">{drill.pending ?? 0}</div><div className="text-[9.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">Pending</div></div>
            </div>
            <div className="max-h-[52vh] overflow-y-auto">
              {(drill.activities || []).length === 0 ? (
                <p className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No activity breakdown for this period.</p>
              ) : (
                <table className="w-full text-[13px]">
                  <thead><tr className="text-[9.5px] uppercase tracking-wide text-[var(--text-muted)] bg-[var(--table-header-bg)]">
                    <th className="text-left px-5 py-2.5 font-black">Activity</th>
                    <th className="text-center px-3 py-2.5 font-black">Done / Total</th>
                    <th className="text-right px-5 py-2.5 font-black">Score</th>
                  </tr></thead>
                  <tbody>
                    {(drill.activities || []).map((a, i) => (
                      <tr key={i} className="border-t border-[var(--border)]">
                        <td className="px-5 py-2.5 font-bold text-[var(--text-main)]">{a.activity}</td>
                        <td className="px-3 py-2.5 text-center tabular-nums font-bold text-[var(--text-muted)]">{a.completed}/{a.total}</td>
                        <td className="px-5 py-2.5 text-right font-black tabular-nums" style={{ color: scoreColor(a.pct) }}>{a.pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default EmployeeTasks;
