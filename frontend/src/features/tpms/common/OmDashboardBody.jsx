import React, { useMemo, useState } from 'react';
import { AlertTriangle, Grid3x3, ClipboardList, CheckCircle2 } from 'lucide-react';
import { Section, Th, Td, Fraction, KpiTile, FilterSelect, TableShell, usePaged, Pager } from './dashboardKit';

/**
 * Shared body for the "OM Dashboard" (KPI tiles + activity-status matrix
 * + action-required list + open-action-items table). Used by both the Admin
 * panel's OM (SMOps) View and the SMOPS panel Dashboard — each supplies its own
 * gradient header and pre-scoped data fetched from getStaffDashboard.
 *
 * props (all default-safe, keyed to the getStaffDashboard response):
 *   kpis        [{ value, label, sub, tone, icon }]
 *   activities  [{ full, short }]                 — matrix columns (activity catalogue)
 *   matrix      clients_grid rows { company, cells:{ [full]:{done,total} }, done }
 *   actions        open_actions [{ company, activity, action, owner, employee_id,
 *                                   target, actual, status, learner_delay, staff_delay }]
 *   action_required [{ id, event_id, company, activity, action, owner, target,
 *                      overdue, days_overdue, urgency }] — the "Action Required From Me"
 *                      feed (overdue-first, de-duplicated by the backend).
 */
const stickyHead = 'sticky left-0 z-10 bg-[var(--table-header-bg)]';
const stickyCell = 'sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]';

// Delay labels from the backend are '—' | 'On time' | 'Nd' (n days overdue).
const delayColor = (v) => {
  if (!v || v === '—') return 'var(--text-muted)';
  if (v === 'On time') return 'var(--accent-green)';
  if (/pending/i.test(v)) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

// Completion-% colour for the client matrix's Pct column.
const pctColor = (p) => (p >= 75 ? 'var(--accent-green)' : p >= 40 ? 'var(--accent-orange)' : 'var(--accent-red)');

// Spec §9.2 / §17 — "Action pending-side". Values match `pending_side` from _open_actions.
const PENDING_SIDE_OPTIONS = [
  { id: '', name: 'Either side' },
  { id: 'client', name: 'Pending: Client' },
  { id: 'staff', name: 'Pending: OM' },
];

// Spec §8 — the delay columns have three display states, and the third (closed, showing the
// numeric "Nd" split) only appears once closed rows are visible. Defaults to Open so the
// table stays a work queue.
const ACTION_STATUS_OPTIONS = [
  { id: 'open', name: 'Open' },
  { id: 'closed', name: 'Closed' },
  { id: '', name: 'All' },
];

const OmDashboardBody = ({ kpis = [], activities = [], matrix = [], actions = [], action_required: actionRequired = [] }) => {
  const [fActivity, setFActivity] = useState('All Activities');
  const [fClient, setFClient] = useState('All Clients');
  const [fOwner, setFOwner] = useState('All Owners');
  // Spec §9.2 / §17 — "Action pending-side": whose court the follow-up is sitting in.
  const [fSide, setFSide] = useState('');
  // Spec §8 — Open (default) / Closed / All. Closed rows carry the numeric delay split.
  const [fStatus, setFStatus] = useState('open');

  const activityOpts = useMemo(
    () => ['All Activities', ...Array.from(new Set(actions.map((a) => a?.activity).filter(Boolean)))],
    [actions],
  );
  const clientOpts = useMemo(
    () => ['All Clients', ...Array.from(new Set(actions.map((a) => a?.company).filter(Boolean)))],
    [actions],
  );
  const ownerOpts = useMemo(
    () => ['All Owners', ...Array.from(new Set(actions.map((a) => a?.owner).filter(Boolean)))],
    [actions],
  );

  const filteredActions = actions.filter((a) =>
    (fActivity === 'All Activities' || a?.activity === fActivity) &&
    (fClient === 'All Clients' || a?.company === fClient) &&
    (fOwner === 'All Owners' || a?.owner === fOwner) &&
    (!fSide || a?.pending_side === fSide) &&
    (!fStatus || (fStatus === 'closed' ? !!a?.closed : !a?.closed)));

  // Client-side pagination (pure presentation — slices already-fetched rows).
  const pRequired = usePaged(actionRequired || [], 10);
  const pActions = usePaged(filteredActions || [], 10);

  const clearFilters = () => {
    setFActivity('All Activities'); setFClient('All Clients');
    setFOwner('All Owners'); setFSide(''); setFStatus('open');
  };

  const matrixCols = activities.length + 4; // Client + activities + Planned + Done + Pct

  return (
    <>
      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Activity Status matrix */}
      <Section
        title="My Clients — Activity Status"
        subtitle="Cadence completion across every governance ritual"
        icon={Grid3x3}
        action={<span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{matrix.length} clients</span>}
      >
        <TableShell minWidth={960}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Client</Th>
              {activities.map((a) => <Th key={a.full} align="center">{a.short}</Th>)}
              <Th align="center">Planned</Th><Th align="center">Done</Th><Th align="center">Pct</Th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((r) => (
              <tr key={r.company_id || r.company} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                {activities.map((a) => {
                  const cell = r.cells?.[a.full];
                  return (
                    <Td key={a.full} align="center">
                      <Fraction v={cell && cell.total ? `${cell.done}/${cell.total}` : ''} status={cell?.status} />
                    </Td>
                  );
                })}
                <Td align="center" className="font-bold tabular-nums">{r.total ?? 0}</Td>
                <Td align="center" className="font-extrabold text-[var(--accent-green)]">{r.done ?? 0}</Td>
                <Td align="center" className="font-extrabold tabular-nums" style={{ color: pctColor(r.total ? Math.round((r.done / r.total) * 100) : 0) }}>{r.total ? Math.round((r.done / r.total) * 100) : 0}%</Td>
              </tr>
            ))}
            {matrix.length === 0 && (
              <tr><td colSpan={matrixCols} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No clients for this selection.</td></tr>
            )}
          </tbody>
        </TableShell>
      </Section>

      {/* Action Required From Me */}
      <Section
        title="Action Required From Me"
        subtitle={actionRequired.length ? `${actionRequired.length} item${actionRequired.length > 1 ? 's' : ''} need your attention` : 'Nothing overdue'}
        icon={AlertTriangle}
        tone="red"
        action={actionRequired.length ? <span className="hidden sm:inline text-[11px] font-bold text-[var(--text-muted)]">{actionRequired.length} open</span> : undefined}
      >
        {actionRequired.length === 0 ? (
          <div className="flex items-center gap-2.5 px-5 py-6">
            <span className="w-8 h-8 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] flex items-center justify-center"><CheckCircle2 size={16} /></span>
            <p className="text-[13px] font-bold text-[var(--accent-green)]">All clear — no actions overdue.</p>
          </div>
        ) : (
          <TableShell minWidth={820}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th className={stickyHead}>Company</Th>
                <Th>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Due</Th><Th align="center">Status</Th>
              </tr>
            </thead>
            <tbody>
              {pRequired.pageRows.map((r) => (
                <tr key={r.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                  <Td className="text-[var(--text-muted)]">{r.activity}</Td>
                  <Td>{r.action}</Td>
                  <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                  <Td className="tabular-nums">{r.target || '—'}</Td>
                  <Td align="center">
                    {r.overdue ? (
                      <span className="text-[10.5px] font-bold px-2 py-1 rounded-full whitespace-nowrap" style={{ color: 'var(--accent-red)', background: 'var(--accent-red-bg)' }}>{r.days_overdue}d overdue</span>
                    ) : (
                      <span className="text-[10.5px] font-bold px-2 py-1 rounded-full whitespace-nowrap" style={{ color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }}>Due soon</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
        <Pager {...pRequired} label="actions" />
      </Section>

      {/* Open Action Items */}
      <Section
        title="Open Action Items — My Clients"
        subtitle="Track pending follow-ups and closures"
        icon={ClipboardList}
        action={
          <div className="hidden md:flex items-center gap-2">
            <FilterSelect value={fActivity} onChange={setFActivity} options={activityOpts} />
            <FilterSelect value={fClient} onChange={setFClient} options={clientOpts} />
            <FilterSelect value={fOwner} onChange={setFOwner} options={ownerOpts} />
            <FilterSelect value={fSide} onChange={setFSide} options={PENDING_SIDE_OPTIONS} />
            <FilterSelect value={fStatus} onChange={setFStatus} options={ACTION_STATUS_OPTIONS} />
            <button onClick={clearFilters} className="px-3 py-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] text-[12.5px] font-bold hover:bg-[var(--input-bg)] transition-all">Clear</button>
          </div>
        }
      >
        {/* Mobile filter row */}
        <div className="md:hidden flex flex-wrap items-center gap-2 px-4 py-3 border-b border-[var(--border)]">
          <FilterSelect value={fActivity} onChange={setFActivity} options={activityOpts} />
          <FilterSelect value={fClient} onChange={setFClient} options={clientOpts} />
          <FilterSelect value={fOwner} onChange={setFOwner} options={ownerOpts} />
          <button onClick={clearFilters} className="px-3 py-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] text-[12.5px] font-bold hover:bg-[var(--input-bg)] transition-all">Clear</button>
        </div>

        <TableShell minWidth={940}>
          <thead>
            <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
              <Th className={stickyHead}>Client</Th>
              <Th>Activity</Th><Th>Action</Th><Th>Owner</Th><Th>Emp ID</Th>
              <Th>Target Date</Th><Th>Actual Date</Th><Th align="center">Status</Th><Th>Client Delay</Th><Th>OM Delay</Th>
            </tr>
          </thead>
          <tbody>
            {pActions.pageRows.map((r) => (
              <tr key={r.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                <Td className={`font-bold ${stickyCell}`}>{r.company}</Td>
                <Td className="text-[var(--text-muted)]">{r.activity}</Td>
                <Td>{r.action}</Td>
                <Td className="text-[var(--text-muted)]">{r.owner || '—'}</Td>
                <Td className="tabular-nums text-[var(--text-muted)]">{r.employee_id || '—'}</Td>
                <Td className="tabular-nums">{r.target || '—'}</Td>
                <Td className="text-[var(--text-muted)]">{r.actual || '—'}</Td>
                <Td align="center"><span className="text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: 'var(--accent-orange)', background: 'var(--accent-orange-bg)' }}>{r.status || 'Pending'}</span></Td>
                <Td className="font-bold" style={{ color: delayColor(r.learner_delay) }}>{r.learner_delay || '—'}</Td>
                <Td className="font-bold" style={{ color: delayColor(r.staff_delay) }}>{r.staff_delay || '—'}</Td>
              </tr>
            ))}
            {filteredActions.length === 0 && (
              <tr><td colSpan={10} className="px-5 py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">No open action items.</td></tr>
            )}
          </tbody>
        </TableShell>
        <Pager {...pActions} label="action items" />
      </Section>
    </>
  );
};

export default OmDashboardBody;
