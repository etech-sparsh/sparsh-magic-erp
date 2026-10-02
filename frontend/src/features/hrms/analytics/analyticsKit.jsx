import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowUpRight, BadgeCheck, CalendarCheck, ClipboardList, Clock3, DoorOpen,
  FileText, Share2, ThumbsDown, ThumbsUp, TrendingDown, UserCheck, UserPlus,
  Users, UserX, Workflow,
} from 'lucide-react';
import { GRID_KPI, SECTION_TITLE, nf } from './analyticsKit';

/**
 * HRMS ▸ shared analytics presentation pieces.
 *
 * Layout and rendering only — every number arrives already computed and already
 * role-scoped from the server. Nothing here derives, filters or totals anything, which is
 * the whole point of Phase 10: the source HRMS computed its figures in the browser, so no
 * two screens agreed and none of them could be role-scoped
 * (FRONTEND_ANALYSIS §6.1).
 *
 * Styled with the ERP's CSS variables so it inherits light/dark theming, matching
 * components/reports/chartKit.js rather than carrying its own palette.
 */

/**
 * Per-KPI icon and tone, keyed on the server's own `key`.
 *
 * TONE IS MEANING, NOT DECORATION. Green is used only where the number is good news,
 * red only where it is a loss and amber only where something is waiting on a person —
 * everything else stays the neutral accent. Colour is never the only signal: every tile
 * carries its icon and its label, so the meaning survives colour-blindness and greyscale.
 *
 * A key absent from this map still renders, with the neutral default. The dashboard must
 * never silently drop a KPI the server decides to add.
 */
const KPI_META = {
  candidates:         { icon: Users,         tone: 'accent' },
  in_pipeline:        { icon: Workflow,      tone: 'accent' },
  cvs_reviewed:       { icon: ClipboardList, tone: 'accent' },
  cvs_shortlisted:    { icon: UserCheck,     tone: 'accent' },
  cvs_selected:       { icon: UserCheck,     tone: 'good' },
  cvs_rejected:       { icon: UserX,         tone: 'bad' },
  open_requisitions:  { icon: FileText,      tone: 'accent' },
  awaiting_approval:  { icon: Clock3,        tone: 'warn' },
  interviews:         { icon: CalendarCheck, tone: 'accent' },
  offers_sent:        { icon: FileText,      tone: 'accent' },
  onboarding:         { icon: UserPlus,      tone: 'accent' },
  hired:              { icon: BadgeCheck,    tone: 'good' },
  joinings:           { icon: DoorOpen,      tone: 'good' },
  shared_with_client: { icon: Share2,        tone: 'accent' },
  client_shortlisted: { icon: ThumbsUp,      tone: 'good' },
  client_rejected:    { icon: ThumbsDown,    tone: 'bad' },
};

const TONES = {
  accent: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  good:   'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  warn:   'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  bad:    'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

/**
 * A headline number.
 *
 * Clickable when the server supplied a deep link — a KPI you cannot click through to is a
 * number the reader has to take on trust — and the arrow appears on hover so the
 * affordance is visible rather than discovered.
 *
 * The value deliberately does NOT use `tabular-nums`: equal-width digits are for columns
 * that must align vertically, and at this size they make a number like 121 read loose.
 * Nor does it wear the tone colour — text stays in the ink tokens and the icon chip beside
 * it carries the meaning, so a wall of tiles does not become a wall of coloured numbers.
 */
export const KpiCard = ({ kpi }) => {
  const navigate = useNavigate();
  const clickable = !!kpi.link;
  const { icon: Icon = Users, tone = 'accent' } = KPI_META[kpi.key] || {};
  const empty = kpi.value === 0;

  return (
    <button
      type="button"
      disabled={!clickable}
      onClick={() => clickable && navigate(kpi.link)}
      title={clickable ? `${kpi.label} — open the records behind this` : undefined}
      className={`group relative flex flex-col rounded-xl border border-[var(--border)]
        bg-[var(--bg-card)] p-4 text-left transition-all duration-150
        focus-visible:outline-2 focus-visible:outline-offset-2
        focus-visible:outline-[var(--accent-indigo)] ${
        clickable
          ? 'cursor-pointer hover:-translate-y-0.5 hover:border-[var(--accent-indigo-border)] hover:shadow-md'
          : 'cursor-default'
      }`}
    >
      <div className="flex items-center gap-2.5">
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TONES[tone]}`}>
          <Icon size={15} strokeWidth={2.2} />
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-[var(--text-main)]">
          {kpi.label}
        </span>
        {clickable && (
          <ArrowUpRight
            size={14}
            className="shrink-0 text-[var(--text-muted)] opacity-0 transition-opacity
              group-hover:opacity-100"
          />
        )}
      </div>

      <p className={`mt-3 text-[30px] font-bold leading-none tracking-tight ${
        empty ? 'text-[var(--text-muted)]' : 'text-[var(--text-main)]'}`}>
        {nf(kpi.value)}
      </p>

      {kpi.hint && (
        <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-muted)]">
          {kpi.hint}
        </p>
      )}
    </button>
  );
};

/**
 * A titled band of KPI tiles.
 *
 * Fifteen identical tiles in one flat grid is a wall, not a dashboard: nothing is more
 * important than anything else and the eye has no entry point. Grouping them under their
 * own headings gives the reader four short lists to scan instead of one long one.
 */
export const KpiGroup = ({ title, kpis }) => {
  if (!kpis?.length) return null;
  return (
    <section>
      <p className={`${SECTION_TITLE} mb-2.5`}>{title}</p>
      <div className={GRID_KPI}>
        {kpis.map((k) => <KpiCard key={k.key} kpi={k} />)}
      </div>
    </section>
  );
};

/**
 * The hiring funnel.
 *
 * Deliberately CSS bars rather than a recharts FunnelChart: the shape is eight horizontal
 * bars with two labels each, and recharts adds no interaction worth ~100 kB here.
 * Percentages come from the server, so the chart and the API can never disagree.
 */
export const FunnelChart = ({ stages }) => {
  const top = stages?.[0]?.count || 0;
  return (
    <div className="space-y-2.5">
      {(stages || []).map((s) => (
        <div key={s.key}>
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-[12.5px] font-semibold text-[var(--text-main)]">
              {s.label}
            </span>
            <span className="text-[11.5px] text-[var(--text-muted)] tabular-nums">
              <strong className="text-[var(--text-main)]">{nf(s.count)}</strong>
              {' · '}{s.of_total}% of applied
              {' · '}{s.from_previous}% from previous
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--accent-indigo)] transition-all"
              style={{ width: `${top ? Math.max((s.count / top) * 100, s.count ? 1.5 : 0) : 0}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

/**
 * The CV funnel: received → reviewed → shortlisted → shared → client verdict → joined.
 *
 * Distinct from FunnelChart above, which ranks candidates by how far they got in the HIRING
 * pipeline. This one follows the CV itself through the client engagement, which is the
 * question a recruitment client actually asks.
 *
 * `of_previous` can be null, and that is rendered as "—" rather than hidden. The server
 * returns null exactly where a stage exceeds the one above it — an in-house requisition
 * never shares a CV, so Selected can legitimately outnumber Shared with client. Showing a
 * dash says "this step does not follow from the one above" instead of inventing a figure
 * over 100%.
 */
export const CvFunnel = ({ stages }) => {
  const top = stages?.[0]?.value || 0;
  if (!stages?.length) return null;
  return (
    <div className="space-y-3">
      {stages.map((s) => (
        <div key={s.key}>
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-[12.5px] font-semibold text-[var(--text-main)]">
              {s.label}
            </span>
            <span className="text-[11.5px] text-[var(--text-muted)] tabular-nums">
              <strong className="text-[var(--text-main)]">{nf(s.value)}</strong>
              {' · '}{s.of_total}% of CVs
              {' · '}
              {s.of_previous === null || s.of_previous === undefined
                ? <span title="This stage is not a subset of the one above it">—</span>
                : `${s.of_previous}% from previous`}
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--accent-indigo)] transition-all"
              style={{ width: `${top ? Math.max((s.value / top) * 100, s.value ? 1.5 : 0) : 0}%` }}
            />
          </div>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">{s.hint}</p>
        </div>
      ))}
    </div>
  );
};

/**
 * The internal-track KPI grid (Internal Recruitment SOP §10).
 *
 * Every tile shows its RATIO, not just its percentage. "83%" alone is unreadable — it could
 * be five of six or five hundred of six hundred, and those call for different conversations.
 *
 * A KPI with nothing to measure shows a dash and its reason, never 0% and never 100%. Both
 * of those are claims about performance that nothing has happened to justify, and a
 * dashboard that makes them is a dashboard nobody should trust.
 */
export const KpiGrid = ({ block }) => {
  if (!block) return null;
  if (!block.applicable) {
    return (
      <p className="text-[12.5px] text-[var(--text-muted)]">
        {block.reason || 'Not applicable.'}
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {block.kpis.map((kpi) => {
        const missing = kpi.value === null || kpi.value === undefined;
        const tone = missing || kpi.meets_target === null ? 'neutral'
          : kpi.meets_target ? 'good' : 'bad';
        return (
          <div key={kpi.key}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <p className="text-[12px] font-semibold text-[var(--text-main)] leading-snug">
              {kpi.label}
            </p>
            <p className={`mt-2 text-[26px] font-bold leading-none tracking-tight ${
              missing ? 'text-[var(--text-muted)]'
                : tone === 'bad' ? 'text-[var(--accent-red)]'
                  : tone === 'good' ? 'text-[var(--accent-green,var(--accent-indigo))]'
                    : 'text-[var(--text-main)]'}`}>
              {/* Phase INT-2: not every KPI is a rate. New-hire satisfaction is a 1-5
                  SCORE and sends `scale_max` to say so — without this it would render as
                  "4.2%", which is not a small cosmetic problem but a wrong number. */}
              {missing ? '—'
                : kpi.scale_max ? `${kpi.value} / ${kpi.scale_max}`
                  : `${kpi.value}%`}
            </p>
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)] tabular-nums">
              {kpi.numerator != null && kpi.denominator
                ? `${nf(kpi.numerator)} of ${nf(kpi.denominator)}`
                : kpi.eligible_n
                  ? `${nf(kpi.eligible_n)} response(s)`
                  : 'nothing to measure'}
              {kpi.target != null && ` · target ${kpi.target}%`}
              {kpi.response_rate != null && ` · ${kpi.response_rate}% answered`}
            </p>
            {/* Phase INT-2 denominator honesty: records deliberately left out are named
                here, so "why is this only counting eleven of our forty joiners" has an
                answer on the tile rather than in somebody's head. */}
            {kpi.excluded_n > 0 && kpi.excluded_reason && (
              <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-muted)]">
                Excluded: {kpi.excluded_reason}.
              </p>
            )}
            {(kpi.reason || kpi.hint) && (
              <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-muted)]">
                {kpi.reason || kpi.hint}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
};

/** A ranked list with proportional bars — sources, departments, platforms. */
export const BarList = ({ rows, emptyLabel = 'No data in this period.' }) => {
  const max = Math.max(1, ...(rows || []).map((r) => r.count));
  if (!rows?.length) {
    return <p className="text-[12.5px] text-[var(--text-muted)]">{emptyLabel}</p>;
  }
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-[12.5px] text-[var(--text-main)]"
            title={r.name}>
            {r.name}
          </span>
          <div className="flex-1 h-2 rounded-full bg-[var(--input-bg)] overflow-hidden">
            <div className="h-full rounded-full bg-[var(--accent-indigo)]"
              style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right text-[11.5px] text-[var(--text-muted)] tabular-nums">
            {nf(r.count)} · {r.share}%
          </span>
        </div>
      ))}
    </div>
  );
};

/**
 * A small labelled figure inside a card.
 *
 * Sits on the recessed surface so a group of them reads as a set of cells rather than
 * text floating in a card, and keeps a left rail in the tone colour where the figure
 * carries good or bad news — the label still names it, so the colour is reinforcement
 * and never the only signal.
 */
export const MiniStat = ({ label, value, tone }) => {
  const rail = tone === 'danger' ? 'border-l-[var(--accent-red)]'
    : tone === 'good' ? 'border-l-[var(--accent-green)]'
    : 'border-l-transparent';
  return (
    <div className={`rounded-lg border-l-2 bg-[var(--input-bg)] px-2.5 py-2 ${rail}`}>
      <p className="truncate text-[10.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]"
        title={label}>
        {label}
      </p>
      <p className="mt-0.5 text-[19px] font-bold leading-tight text-[var(--text-main)]">
        {value}
      </p>
    </div>
  );
};

/** Shown to a hiring manager, so they never read own-scope numbers as company-wide. */
export const ScopeNotice = () => (
  <div className="flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2">
    <TrendingDown size={14} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
    <p className="text-[11.5px] text-[var(--text-muted)]">
      These figures cover <strong>the requisitions you raised</strong>, not the whole
      company.
    </p>
  </div>
);

/** From/to pickers. Kept dumb — the server validates and bounds the range. */
export const RangePicker = ({ value, onChange }) => (
  <div className="flex flex-wrap items-center gap-2">
    {[['from', 'From'], ['to', 'To']].map(([key, label]) => (
      <label key={key} className="flex items-center gap-1.5 text-[11.5px] text-[var(--text-muted)]">
        {label}
        <input
          type="date"
          value={value[key] || ''}
          onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          className="h-8 px-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-main)]"
        />
      </label>
    ))}
    {(value.from || value.to) && (
      <button
        type="button"
        onClick={() => onChange({ from: '', to: '' })}
        className="h-8 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-semibold text-[var(--text-muted)] hover:text-[var(--text-main)]"
      >
        Last 90 days
      </button>
    )}
  </div>
);
