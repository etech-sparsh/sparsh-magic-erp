import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Clock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getHrmsDashboard, getHrmsFunnel, getHrmsBreakdown, getHrmsPositions,
  getInternalKpis, getDepartments, getDesignations,
} from '../../../services/hrmsApi';
import { CARD, GRID_TWO, SECTION_TITLE, nf } from './analyticsKit';
import {
  BarList, CvFunnel, FunnelChart, KpiGrid, KpiGroup, MiniStat, RangePicker, ScopeNotice,
} from './analyticsKit.jsx';

/**
 * HRMS ▸ recruitment dashboard.
 *
 * Every figure is computed and scoped server-side. This component fetches and lays out —
 * it never totals, filters or re-derives anything, so the screen and the API cannot
 * disagree. That is the specific failure this phase exists to fix (FRONTEND_ANALYSIS §6.1:
 * the source computed everything in the browser, per screen, inconsistently).
 */

// "Job postings by platform" is deliberately absent: a posting has no platform now — one
// posting, one link, shared anywhere — so the channel is `source`, which the applicant
// names on the form. Grouping by a field nothing writes would draw an empty chart.
const BREAKDOWNS = [
  { by: 'source', title: 'Where candidates come from' },
  { by: 'department', title: 'Requisitions by department' },
  { by: 'designation', title: 'Requisitions by role' },
  // ── Phase 11-R, Item 4 ──
  { by: 'referral_source', title: 'Referral sources' },
];

/**
 * How the KPI tiles are banded, in render order.
 *
 * The server returns fifteen KPIs as one flat list. Rendered as one flat grid they are a
 * wall of identical boxes with no entry point, so they are banded by the question they
 * answer: who applied, what we are hiring for, and how far they got.
 *
 * The grouping is presentation only — no figure is computed, combined or filtered here.
 * Anything the server sends whose key is absent from this map falls into the trailing
 * band, so a KPI added to the API appears on the screen instead of vanishing.
 */
const KPI_BANDS = [
  { title: 'Candidates', keys: ['candidates', 'in_pipeline', 'cvs_reviewed',
                                'cvs_shortlisted', 'cvs_selected', 'cvs_rejected'] },
  { title: 'Positions', keys: ['open_requisitions', 'awaiting_approval'] },
  { title: 'Progress to hire', keys: ['interviews', 'offers_sent', 'onboarding',
                                      'hired', 'joinings'] },
];

const bandKpis = (kpis) => {
  const byKey = new Map((kpis || []).map((k) => [k.key, k]));
  const bands = KPI_BANDS.map(({ title, keys }) => {
    const picked = keys.map((key) => byKey.get(key)).filter(Boolean);
    picked.forEach((k) => byKey.delete(k.key));
    return { title, kpis: picked };
  });
  const rest = [...byKey.values()];
  return rest.length ? [...bands, { title: 'Other', kpis: rest }] : bands;
};

const RecruitmentDashboard = () => {
  const { scope, companyId, isInternal } = useHrms();

  const [range, setRange] = useState({ from: '', to: '' });
  const [data, setData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [breakdowns, setBreakdowns] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [positions, setPositions] = useState(null);
  // ── Internal track ── the SOP §10 KPI block is opt-in: asking for it changes what the
  // dashboard IS about, so it is a deliberate switch rather than something always on.
  const [track, setTrack] = useState('');
  // Phase INT-8: filters on the internal KPI block (spec S29). They narrow ONLY that
  // block: the rest of the dashboard keeps its own scope, so a department filter on the
  // SOP KPIs cannot silently reshape the hiring funnel below it. `kpiBlock` overrides
  // `data.internal_kpis` whenever a filter is active; the server echoes `filters` back.
  const [kpiFilters, setKpiFilters] = useState({});
  const [kpiBlock, setKpiBlock] = useState(null);
  const [masters, setMasters] = useState({ departments: [], designations: [] });



  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    const params = {
      ...scope,
      date_from: range.from || undefined,
      date_to: range.to || undefined,
      track: track || undefined,
    };
    try {
      // One await for the headline calls so the page paints complete rather than in
      // several visible steps.
      const [dash, fun, pos] = await Promise.all([
        getHrmsDashboard(params),
        getHrmsFunnel(params),
        // The matrix is supporting detail — a failure there must not blank the KPIs above
        // it, which are the reason the reader opened the page.
        getHrmsPositions(params).catch(() => ({ data: null })),
      ]);
      setData(dash.data);
      setFunnel(fun.data);
      setPositions(pos.data);

      const results = await Promise.all(
        BREAKDOWNS.map((b) => getHrmsBreakdown({ ...params, by: b.by })
          .then((r) => [b.by, r.data])
          // A failed breakdown must not blank the dashboard — the KPIs above it are the
          // reason the reader opened the page.
          .catch(() => [b.by, null])),
      );
      setBreakdowns(Object.fromEntries(results));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the dashboard.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, range.from, range.to, track]);

  useEffect(() => { load(); }, [load]);

  // The masters feed the KPI filter dropdowns. Fetched once, only when the internal view
  // is opened -- nobody else pays for them.
  useEffect(() => {
    if (track !== 'internal' || !companyId) return;
    Promise.all([getDepartments(scope), getDesignations(scope)])
      .then(([dep, des]) => setMasters({
        departments: dep.data?.departments || [],
        designations: des.data?.designations || [],
      }))
      .catch(() => setMasters({ departments: [], designations: [] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track, companyId]);

  // Re-fetch ONLY the KPI block when its filters change. With no filters the dashboard's
  // own copy is rendered untouched, so the no-filter answer stays byte-for-byte the same.
  useEffect(() => {
    const active = Object.values(kpiFilters).some(Boolean);
    if (track !== 'internal' || !companyId || !active) { setKpiBlock(null); return; }
    getInternalKpis({
      ...scope,
      date_from: range.from || undefined,
      date_to: range.to || undefined,
      department_id: kpiFilters.department_id || undefined,
      designation_id: kpiFilters.designation_id || undefined,
      designation_level: kpiFilters.designation_level || undefined,
      status: kpiFilters.status || undefined,
    })
      .then((r) => setKpiBlock(r.data))
      .catch(() => setKpiBlock(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track, companyId, kpiFilters, range.from, range.to]);

  const tth = data?.time_to_hire;

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BarChart3}
        title="Recruitment analytics"
        // In-house hiring, so the only scope worth stating is the period.
        subtitle={data?.range
          ? `${data.range.from} to ${data.range.to}`
          : 'Hiring at a glance'}
        actions={<RangePicker value={range} onChange={setRange} />}
      />
      <HrmsScopeBar />

      {/* ── Internal track ── the SOP §10 KPI block.
          A toggle rather than a permanent block because it answers a narrower question
          than the tiles above: not "how is hiring going" but "is our own
          recruitment policy being followed".

          Sparsh staff only: the Internal Recruitment SOP is Sparsh Magic's own governance
          document (position scorecards, phone screen, shortlisting committee). With one
          option left there is nothing to toggle, so the selector itself is dropped rather
          than shown disabled. */}
      {isInternal && (
        <div className="flex items-center gap-2 flex-wrap">
          <label htmlFor="d-track" className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
            View
          </label>
          <select
            id="d-track"
            value={track}
            onChange={(e) => setTrack(e.target.value)}
            className="h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
          >
            <option value="">Recruitment overview</option>
            <option value="internal">Internal policy compliance (SOP KPIs)</option>
          </select>
        </div>
      )}

      {data?.scoped_to_own_requisitions && <ScopeNotice />}

      {loading && <HrmsLoading label="Crunching the numbers…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {data && !loading && !error && (
        <>
          {/* Shown FIRST when asked for: if the reader switched to policy compliance, that
              is what they came to see, and burying it under fifteen hiring tiles would
              answer a question they did not ask. */}
          {data.internal_kpis && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-1`}>Internal recruitment KPIs</p>
              <p className="mb-4 text-[11.5px] text-[var(--text-muted)]">
                Against the Internal Recruitment SOP&rsquo;s own targets. Each figure shows
                the ratio behind it — a percentage with no denominator is not a score.
              </p>
              <KpiFilterBar
                filters={kpiFilters}
                onChange={setKpiFilters}
                masters={masters}
              />
              {(kpiBlock || data.internal_kpis).applicable === false ? (
                <p className="text-[12px] text-[var(--text-muted)]">
                  {(kpiBlock || data.internal_kpis).reason}
                </p>
              ) : (
                <KpiGrid block={kpiBlock || data.internal_kpis} />
              )}
            </section>
          )}

          <div className="space-y-5">
            {bandKpis(data.kpis).map((band) => (
              <KpiGroup key={band.title} title={band.title} kpis={band.kpis} />
            ))}
          </div>

          {/* ── The CV funnel ──
              CV review → shortlist → selection → joining. It sits ABOVE the hiring funnel
              because it is this screen's subject; the hiring funnel below answers the
              different question of how far candidates got in the pipeline. */}
          {data.cv_funnel?.length > 0 && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-1`}>Recruitment funnel</p>
              <p className="mb-4 text-[11.5px] text-[var(--text-muted)]">
                Every CV raised against our own requisitions.
              </p>
              <CvFunnel stages={data.cv_funnel} />
            </section>
          )}

          <div className={GRID_TWO}>
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-3`}>Hiring funnel</p>
              {funnel?.total ? (
                <>
                  <FunnelChart stages={funnel.stages} />
                  {funnel.unranked > 0 && (
                    <p className="mt-3 text-[11px] text-[var(--text-muted)]">
                      {nf(funnel.unranked)} candidate(s) have a stage this dashboard
                      cannot interpret and are excluded from the bars.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[12.5px] text-[var(--text-muted)]">
                  No applications in this period.
                </p>
              )}
            </section>

            <div className="space-y-4">
              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>Positions</p>
                <div className="grid grid-cols-3 gap-3">
                  <MiniStat label="Open" value={nf(data.positions.open)} />
                  <MiniStat label="Vacancies" value={nf(data.positions.vacancies)} />
                  <MiniStat label="Filled" value={nf(data.positions.filled)} tone="good" />
                  <MiniStat label="On hold" value={nf(data.positions.on_hold)} />
                  <MiniStat label="Cancelled" value={nf(data.positions.cancelled)} />
                </div>
              </section>

              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>Offer outcomes</p>
                <div className="grid grid-cols-3 gap-3">
                  <MiniStat label="Sent" value={nf(data.offer_outcomes.sent)} />
                  <MiniStat label="Accepted" value={nf(data.offer_outcomes.accepted)} tone="good" />
                  <MiniStat label="Declined" value={nf(data.offer_outcomes.declined)} tone="danger" />
                  <MiniStat label="Revoked" value={nf(data.offer_outcomes.revoked)} />
                  <MiniStat label="Acceptance" value={`${data.offer_outcomes.acceptance_rate}%`} />
                </div>
              </section>

              <section className={CARD}>
                <p className={`${SECTION_TITLE} mb-3 flex items-center gap-1.5`}>
                  <Clock size={12} /> Time to hire
                </p>
                {tth?.sample ? (
                  <div className="grid grid-cols-3 gap-3">
                    <MiniStat label="Median" value={`${tth.median_days} d`} />
                    <MiniStat label="Mean" value={`${tth.mean_days} d`} />
                    <MiniStat label="Hires measured" value={nf(tth.sample)} />
                  </div>
                ) : (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    No offers were accepted in this period, so there is nothing to measure.
                  </p>
                )}
                <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                  Application to offer acceptance. Median and mean are both shown — one slow
                  senior hire skews a mean badly.
                </p>
              </section>
            </div>
          </div>

          {/* ── Phase 11-R, Item 4 — position-wise CV status matrix ──
              Horizontally scrolling with a sticky first column: there is one column per
              application status and that will always be wider than a screen. Only statuses
              with a non-zero count anywhere are shown, so the table stays readable rather
              than being mostly zeros. */}
          {positions && !positions.rows?.length && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-2`}>Position-wise CV status</p>
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No requisitions in this period.
              </p>
            </section>
          )}

          {positions?.rows?.length > 0 && (
            <section className={CARD}>
              <p className={`${SECTION_TITLE} mb-3`}>Position-wise CV status</p>
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px] border-collapse">
                  <thead>
                    <tr className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                      <th className="text-left py-2 pr-3 sticky left-0 bg-[var(--bg-card)] z-10 min-w-[190px]">
                        Position
                      </th>
                      <th className="text-right py-2 px-2">Vac</th>
                      <th className="text-right py-2 px-2">CVs</th>
                      {positions.statuses
                        .filter((s) => positions.rows.some((r) => r.counts[s] > 0))
                        .map((s) => (
                          <th key={s} className="text-right py-2 px-2 whitespace-nowrap">{s}</th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.rows.map((row) => (
                      <tr key={row.request_no} className="border-b border-[var(--border)] last:border-0">
                        <td className="py-2 pr-3 sticky left-0 bg-[var(--bg-card)] z-10">
                          <span className="font-semibold text-[var(--text-main)]">
                            {row.designation || row.request_no}
                          </span>
                          <span className="block text-[11px] text-[var(--text-muted)]">
                            {[row.request_no, row.department]
                              .filter(Boolean).join(' · ')}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-right">{nf(row.vacancy)}</td>
                        <td className="py-2 px-2 text-right font-bold text-[var(--text-main)]">
                          {nf(row.totals.candidates)}
                        </td>
                        {positions.statuses
                          .filter((s) => positions.rows.some((r) => r.counts[s] > 0))
                          .map((s) => (
                            <td key={s} className="py-2 px-2 text-right">
                              {row.counts[s] ? nf(row.counts[s])
                                : <span className="text-[var(--text-muted)]">—</span>}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <div className={GRID_TWO}>
            {BREAKDOWNS.map(({ by, title }) => (
              <section key={by} className={CARD}>
                <p className={`${SECTION_TITLE} mb-3`}>{title}</p>
                <BarList rows={breakdowns[by]?.rows} />
                {breakdowns[by]?.truncated && (
                  <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                    Showing the top {breakdowns[by].rows.length} only.
                  </p>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

/**
 * Filters on the SOP KPI block (Phase INT-8). Selects only — every option list is a master
 * the module already owns, and the server validates whatever is sent, so this bar is a
 * convenience over the API rather than a gatekeeper.
 *
 * HR-owner and HOD filters exist on the API (`hr_user_id` / `hod_user_id`) but have no
 * dropdown here yet: the module has no light "users by governance role" listing to feed
 * one, and a free-text id field is a worse UI than none.
 */
const LEVELS = ['junior', 'mid', 'senior', 'managerial'];
const KPI_STATUSES = [
  'Pending HR Verification', 'Pending Budget Approval', 'Pending Escalation',
  'Pending Scorecard Approval', 'Approved', 'Rejected',
];

const KpiFilterBar = ({ filters, onChange, masters }) => {
  const set = (key) => (e) => onChange({ ...filters, [key]: e.target.value });
  const active = Object.values(filters).some(Boolean);
  const select = 'h-9 px-2 rounded-lg border border-[var(--border)] '
    + 'bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)]';
  return (
    <div className="mb-4 flex items-center gap-2 flex-wrap">
      <select aria-label="Department" className={select}
        value={filters.department_id || ''} onChange={set('department_id')}>
        <option value="">All departments</option>
        {masters.departments.map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>
      <select aria-label="Position" className={select}
        value={filters.designation_id || ''} onChange={set('designation_id')}>
        <option value="">All positions</option>
        {masters.designations.map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>
      <select aria-label="Level" className={select}
        value={filters.designation_level || ''} onChange={set('designation_level')}>
        <option value="">All levels</option>
        {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
      <select aria-label="Status" className={select}
        value={filters.status || ''} onChange={set('status')}>
        <option value="">All statuses</option>
        {KPI_STATUSES.map((st) => <option key={st} value={st}>{st}</option>)}
      </select>
      {active && (
        <button
          type="button"
          onClick={() => onChange({})}
          className="h-9 px-3 rounded-lg border border-[var(--border)] text-[12.5px]
            text-[var(--text-muted)]"
        >
          Clear
        </button>
      )}
      {active && (
        <p className="basis-full text-[11px] text-[var(--text-muted)]">
          Filters apply to this KPI block only — the rest of the dashboard keeps its own
          scope.
        </p>
      )}
    </div>
  );
};

export default RecruitmentDashboard;
