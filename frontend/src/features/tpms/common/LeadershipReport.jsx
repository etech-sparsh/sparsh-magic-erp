import React, { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Award, RefreshCw, AlertTriangle, Users, Gauge, TrendingUp, ChevronDown, Lock,
  Calculator, Clock, MessageSquare,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell, KpiTile,
} from './dashboardKit';
import { getLeadershipConfig, getLeadershipCycles, getLeadershipScores } from '../../../services/leadershipApi';
import { scoreLabel, scoreHint } from '../leadership/leadershipStatus';
import {
  canManage, fmtNum, fmtPct, scoreColor, scoreTone, useAsync, useLeadershipCompany,
} from '../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ Result / RRO view.

   "All leaders should get the score as per parameters they have."
   "Their respective reporting Manager should discuss the score with each leader
    during RRO and every two months this should happen."

   Every number here is an AGGREGATE. The payload this page renders is built by the
   backend's `subject_score()`, which carries no giver id, no giver name and no individual
   response — so the leader and their manager physically cannot see who said what,
   whatever the UI does. The relation breakdown is sent to HR/staff only, and a relation
   group with fewer than two responses is withheld even from them.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

/** Achievement bar for one parameter. */
const Bar = ({ value, hasData }) => {
  if (!hasData) {
    return <span className="text-[11.5px] font-bold text-[var(--text-muted)]">No feedback yet</span>;
  }
  const c = scoreColor(value);
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="h-1.5 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: c }} />
      </div>
      <span className="text-[11.5px] font-bold tabular-nums w-[52px] text-right" style={{ color: c }}>
        {fmtPct(value)}
      </span>
    </div>
  );
};

/** The expanded row: parameter-wise result, which is what RRO discusses. */
const Breakdown = ({ row }) => (
  <div className="px-4 py-4 bg-[var(--input-bg)]/40 border-t border-[var(--border)] flex flex-col gap-3">
    <TableShell minWidth={720}>
      <thead>
        <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
          <Th>Parameter</Th><Th align="center">Avg rating</Th><Th>Achievement</Th>
          <Th align="center">Weightage</Th><Th align="right">Weighted score</Th>
        </tr>
      </thead>
      <tbody>
        {row.parameters.map((p) => (
          <tr key={p.item_id} className="border-b border-[var(--border)] last:border-0">
            <Td>
              <span className="font-bold">{p.title}</span>
              <span className="block text-[10.5px] text-[var(--text-muted)] max-w-[300px]">{p.prompt}</span>
            </Td>
            <Td align="center" className="tabular-nums font-bold">
              {p.has_data ? `${fmtNum(p.average_rating)} / 5` : '—'}
            </Td>
            <Td><Bar value={p.achievement} hasData={p.has_data} /></Td>
            <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtNum(p.weightage)}%</Td>
            <Td align="right">
              <span className="text-[13px] font-extrabold tabular-nums">{fmtNum(p.weighted_score)}</span>
              <span className="text-[10.5px] font-bold text-[var(--text-muted)]"> / {fmtNum(p.max_score)}</span>
            </Td>
          </tr>
        ))}
      </tbody>
    </TableShell>

    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
      <Calculator size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[11.5px] font-bold text-[var(--text-muted)]">Leadership Score =</span>
      <span className="text-[11.5px] font-mono tabular-nums">
        {row.parameters.map((p) => fmtNum(p.weighted_score)).join(' + ')}
      </span>
      <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(row.leadership_score) }}>
        = {fmtNum(row.leadership_score)}%
      </span>
      {row.unearned_weightage > 0 && (
        <span className="text-[10.5px] font-bold text-[var(--text-muted)] w-full sm:w-auto">
          · {fmtNum(row.unearned_weightage)}% of the weightage had no feedback
          {row.score_on_applicable !== null && (
            <> — {fmtNum(row.score_on_applicable)}% on what was answered</>
          )}
        </span>
      )}
    </div>

    {/* HR/staff only — withheld groups are shown as withheld, never as a number. */}
    {row.by_relation && (
      <div className="flex flex-wrap gap-2">
        {row.by_relation.map((g) => (
          <span key={g.relation}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <span className="text-[11.5px] font-bold">{g.relation_label}</span>
            {g.withheld ? (
              <span className="inline-flex items-center gap-1 text-[10.5px] font-bold text-[var(--text-muted)]">
                <Lock size={10} /> withheld ({g.response_count})
              </span>
            ) : (
              <span className="text-[12px] font-extrabold tabular-nums" style={{ color: scoreColor(g.leadership_score) }}>
                {fmtNum(g.leadership_score)}%
                <span className="text-[10px] font-bold text-[var(--text-muted)]"> · {g.response_count}</span>
              </span>
            )}
          </span>
        ))}
      </div>
    )}

    <p className="text-[10.5px] text-[var(--text-muted)] flex items-center gap-1.5">
      <Lock size={11} /> Individual responses and the identity of feedback givers are never
      shown — the score is a combined result.
    </p>
  </div>
);

const LeadershipReport = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  const manage = canManage(user);
  const [cycle, setCycle] = useState('');
  const [expanded, setExpanded] = useState(null);

  const waiting = staff && !companyId;

  useAsync(async () => (await getLeadershipConfig()).data, []);
  const cyc = useAsync(
    async () => (await getLeadershipCycles(companyId)).data,
    [companyId], { skip: waiting },
  );
  const cycles = useMemo(() => cyc.data?.cycles || [], [cyc.data]);
  // Derived rather than stored: the newest cycle is the default until the user picks one,
  // so there is no effect writing state back on every load.
  const activeCycle = cycle || cycles[0]?.cycle || '';

  const load = useMemo(
    () => async () => (await getLeadershipScores(companyId, activeCycle)).data,
    [companyId, activeCycle],
  );
  const { data, loading, error, reload } = useAsync(load, [companyId, activeCycle],
    { skip: waiting || !activeCycle });

  const rows = data?.rows || [];
  const summary = data?.summary || {};

  return (
    <div className="space-y-5">
      <DashboardHero icon={Award} title="Leadership Score"
        subtitle="Confidential 360° feedback result — discussed at RRO every two months">
        {staff && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />}
        <HeaderSelect value={activeCycle} onChange={setCycle}
          options={cycles.length ? cycles.map((c) => ({ id: c.cycle, name: c.label }))
            : [{ id: '', name: 'No cycles yet' }]} />
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <KpiTile value={summary.leaders ?? 0} label="Leaders" sub="In this cycle" tone="blue" icon={Users} />
        <KpiTile value={summary.scored ?? 0} label="Scored" sub="Enough feedback received"
          tone={summary.scored ? 'green' : 'plain'} icon={Gauge} />
        <KpiTile value={fmtNum(summary.average_score)} label="Average score" sub="Out of 100"
          tone={scoreTone(summary.average_score)} icon={Gauge} />
        <KpiTile value={fmtNum(summary.highest)} label="Highest" sub="This cycle"
          tone={scoreTone(summary.highest)} icon={TrendingUp} />
      </div>

      <Section title="Leadership Scores" icon={Award}
        subtitle={activeCycle ? `${data?.cycle_label || activeCycle} · ${data?.degree || '360'}° feedback`
          : 'Select a cycle'}>
        {waiting ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company.
          </div>
        ) : !activeCycle ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            No assessment cycle has been opened yet.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Calculating scores…
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <Award size={20} />
            </span>
            <p className="text-[13px] font-bold">No results to show</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-sm">
              {manage
                ? 'No leaders are enrolled in this cycle yet.'
                : 'You will see your own Leadership Score here once your feedback cycle completes.'}
            </p>
          </div>
        ) : (
          <TableShell minWidth={880}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Leader</Th><Th>Level</Th><Th align="center">Responses</Th>
                <Th>Result</Th><Th align="right">Leadership Score</Th><Th align="center"> </Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const open = expanded === row.subject_id;
                const scored = row.state === 'scored';
                return (
                  <React.Fragment key={row.subject_id}>
                    <tr
                      className="border-b border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors cursor-pointer"
                      onClick={() => scored && setExpanded(open ? null : row.subject_id)}>
                      <Td>
                        <span className="font-bold">{row.subject_name}</span>
                        {(row.designation || row.department) && (
                          <span className="block text-[10.5px] text-[var(--text-muted)]">
                            {[row.designation, row.department].filter(Boolean).join(' · ')}
                          </span>
                        )}
                      </Td>
                      <Td>
                        <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border"
                          style={{ color: 'var(--accent-indigo)', background: 'var(--accent-indigo-bg)', borderColor: 'var(--accent-indigo-border)' }}>
                          {row.level}
                        </span>
                      </Td>
                      <Td align="center" className="tabular-nums font-bold">
                        {row.response_count}
                        <span className="text-[10px] text-[var(--text-muted)]"> / {row.panel_size}</span>
                      </Td>
                      <Td>
                        {scored
                          ? <Bar value={row.leadership_score} hasData />
                          : (
                            /* Three outcomes only, and the right one: a leader looking
                               before publish is not short of responses. */
                            <span className="inline-flex items-center gap-1.5 text-[11.5px] font-bold text-[var(--text-muted)]"
                              title={scoreHint(row, row.min_responses ?? 3)}>
                              <Clock size={12} /> {scoreLabel(row)}
                            </span>
                          )}
                      </Td>
                      <Td align="right">
                        {scored ? (
                          <span className="inline-flex items-baseline gap-1 justify-end">
                            <span className="text-[16px] font-extrabold tabular-nums"
                              style={{ color: scoreColor(row.leadership_score) }}>
                              {fmtNum(row.leadership_score)}
                            </span>
                            <span className="text-[10px] font-bold text-[var(--text-muted)]">/ 100</span>
                          </span>
                        ) : <span className="text-[var(--text-muted)]">—</span>}
                      </Td>
                      <Td align="center">
                        {scored && (
                          <ChevronDown size={15}
                            className={`inline text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
                        )}
                      </Td>
                    </tr>
                    <AnimatePresence initial={false}>
                      {open && (
                        <tr>
                          <td colSpan={6} className="p-0">
                            <MotionDiv initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                              <Breakdown row={row} />
                            </MotionDiv>
                          </td>
                        </tr>
                      )}
                    </AnimatePresence>
                  </React.Fragment>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Section>

      <div className="flex items-start gap-2 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
        <MessageSquare size={15} className="text-[var(--accent-indigo)] mt-0.5 shrink-0" />
        <p className="text-[12px] font-medium text-[var(--text-muted)]">
          <span className="font-bold text-[var(--text-main)]">RRO discussion.</span> The reporting
          manager discusses this score with each leader during RRO, every two months. Discuss
          parameter-wise if needed — expand a row for the full breakdown. The point is
          improvement, not who gave the feedback.
        </p>
      </div>
    </div>
  );
};

export default LeadershipReport;
