import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, Download, ClipboardCheck, Users, Star, Search, LayoutGrid, LineChart as LineIcon,
  MessageSquare, AlertTriangle, Sigma, Filter, UserCheck, ListChecks, CheckCircle2, XCircle,
  X, Building2, CalendarDays, StickyNote, Maximize2,
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { DashboardHero, HeroButton, Section, KpiTile, FilterSelect, TILE, usePaged, Pager } from './dashboardKit';
import { useAuth } from '../../../context/AuthContext';
import { getReviewReports, currentPeriod, periodLabel } from '../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   Review Report — review-form responses with a Cards view and a
   Monthly Trend chart. Shared by the Admin panel and SMOPS panel.
   Data comes from GET /tpms/reports/reviews (per-respondent
   submissions + monthly score trend); see tpms_dashboard_service
   .get_review_reports for the response shape.
   ───────────────────────────────────────────────────────────── */

// Fallback form list so the source selector renders before the first fetch.
const DEFAULT_SOURCES = [
  { id: 'accountability', label: 'Accountability Rating' },
  { id: 'ownership', label: 'Ownership Rating' },
  { id: 'culture', label: 'Culture Rating' },
  { id: 'implementation_feedback', label: 'Implementation Update Feedback' },
];

// Last 12 months as { id: 'YYYY-MM', name: 'Jul26' } for the period picker.
const monthOptions = () => {
  const out = [{ id: '', name: 'All Periods' }];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const id = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ id, name: periodLabel(id) || id });
  }
  return out;
};

// Rating scale ceiling — matches SCALE_MAX in backend/app/models/forms.py. Score % for a
// matrix is Σratings ÷ (answered × SCALE_MAX) × 100, which is how the server computes it too.
const SCALE_MAX = 5;

// Status bands mirror the backend (≥85 strong / ≥70 moderate / below).
const scoreColor = (p) => (p >= 85 ? 'var(--accent-green)' : p >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)');
const initials = (name) => (name || '?').split(' ').filter(Boolean).map((x) => x[0]).join('').slice(0, 2).toUpperCase();
const nOrDash = (v) => (v == null ? '—' : v);

/** One figure in the Grand Total strip — icon chip, label, value, context line. */
const TotalStat = ({ icon: Icon, label, value, sub, tone = 'plain' }) => {
  const t = TILE[tone] || TILE.plain;
  return (
    <div className="bg-[var(--bg-card)] px-4 py-3.5 flex items-start gap-3">
      <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: t.bg, color: t.fg }}>
        {Icon && <Icon size={16} />}
      </span>
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] truncate">{label}</p>
        <p className="text-[21px] font-extrabold tabular-nums leading-tight mt-0.5" style={{ color: t.fg }}>{value}</p>
        {sub && <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5 truncate">{sub}</p>}
      </div>
    </div>
  );
};

const Stars = ({ value }) => (
  <span className="inline-flex items-center gap-0.5">
    {[1, 2, 3, 4, 5].map((i) => (
      <Star key={i} size={13} style={{ color: 'var(--accent-yellow)', fill: i <= Math.round(value) ? 'var(--accent-yellow)' : 'transparent' }} className={i <= Math.round(value) ? '' : 'opacity-30'} />
    ))}
  </span>
);

/* ─────────────────────────────────────────────────────────────
   Submission detail — the full breakdown behind one review card.

   A modal rather than a route: this page is mounted at two paths
   (/tpms/admin/reviews and /tpms/smops/reviews), and a dialog keeps
   the caller's filter + scroll state intact on close.

   Everything rendered here already ships in the list payload
   (entry.questions × entry.employees[].ratings, or entry.items for a
   checklist) — opening a card costs no extra request.
   ───────────────────────────────────────────────────────────── */
const MotionDiv = motion.div;

/** A 0–5 cell coloured on the same bands as the percentages elsewhere. */
const RatingCell = ({ value }) => {
  if (typeof value !== 'number') {
    return <span className="text-[var(--text-muted)] opacity-50">—</span>;
  }
  const c = scoreColor((value / SCALE_MAX) * 100);
  return (
    <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-[12.5px] font-extrabold tabular-nums"
      style={{ color: c, background: `${c}1a` }}>
      {value}
    </span>
  );
};

const ReviewDetailModal = ({ entry, sourceLabel, isYesno, statusLabel, onClose }) => {
  // Esc to dismiss + freeze the page behind the dialog.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const employees = entry.employees || [];
  const items = entry.items || [];
  const pct = Number(entry.score_pct) || 0;

  // Column set = the form's criteria, PLUS any code that actually carries a rating. The list
  // payload reads the hard-coded form definition, so a criterion added through the question
  // master (M10) would otherwise be silently dropped from the breakdown.
  const columns = useMemo(() => {
    const cols = (entry.questions || []).map((qq) => ({ id: String(qq.id), text: qq.text || String(qq.id) }));
    const seen = new Set(cols.map((c) => c.id));
    (entry.employees || []).forEach((emp) => Object.keys(emp.ratings || {}).forEach((code) => {
      if (!seen.has(String(code))) {
        seen.add(String(code));
        cols.push({ id: String(code), text: String(code) });
      }
    }));
    return cols;
  }, [entry]);

  /** Mean rating a criterion drew across everyone this respondent rated. */
  const columnAvg = (code) => {
    const vals = employees.map((e) => e.ratings?.[code]).filter((v) => typeof v === 'number');
    return vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10 : null;
  };

  const answered = employees.reduce((a, e) => a + Object.keys(e.ratings || {}).length, 0);
  const grandTotal = employees.reduce((a, e) => a + (Number(e.grand_total) || 0), 0);

  const summary = isYesno
    ? [
      { label: 'Score', value: `${pct}%` },
      { label: 'Yes', value: entry.yes ?? 0 },
      { label: 'No', value: Math.max(0, (entry.total ?? 0) - (entry.yes ?? 0)) },
      { label: 'Questions', value: entry.total ?? 0 },
    ]
    : [
      { label: 'Score', value: `${pct}%` },
      { label: 'Employees', value: employees.length },
      { label: 'Ratings', value: answered },
      { label: 'Grand Total', value: `${grandTotal} / ${answered * SCALE_MAX}` },
    ];

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <MotionDiv
        role="dialog" aria-modal="true" aria-label={`${entry.name} — ${sourceLabel} detail`}
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">

        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-11 h-11 rounded-2xl text-white text-[13px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
              {initials(entry.name)}
            </span>
            <div className="min-w-0">
              <h3 className="text-[15.5px] font-extrabold tracking-tight truncate">{entry.name || '—'}</h3>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                <span className="inline-flex items-center gap-1 truncate"><Building2 size={12} />{entry.company || '—'}</span>
                <span className="inline-flex items-center gap-1"><CalendarDays size={12} />{entry.period_label || entry.period || '—'}</span>
                <span className="inline-flex items-center gap-1"><ClipboardCheck size={12} />{sourceLabel}</span>
              </div>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors shrink-0">
            <X size={16} />
          </button>
        </div>

        {/* Headline score */}
        <div className="px-5 py-3.5 border-b border-[var(--border)] flex flex-wrap items-center gap-x-4 gap-y-2">
          {!isYesno && entry.avg !== '' && entry.avg != null && <Stars value={Number(entry.avg)} />}
          <span className="text-[22px] font-extrabold tabular-nums leading-none" style={{ color: scoreColor(pct) }}>{pct}%</span>
          <span className="text-[10.5px] font-bold px-2.5 py-1 rounded-full" style={{ color: scoreColor(pct), background: `${scoreColor(pct)}1a` }}>
            {statusLabel(pct)}
          </span>
          {!isYesno && entry.avg !== '' && entry.avg != null && (
            <span className="text-[11.5px] font-semibold text-[var(--text-muted)]">
              avg <span className="tabular-nums font-extrabold text-[var(--text-main)]">{entry.avg}</span> / {SCALE_MAX}
            </span>
          )}
        </div>

        {/* Summary strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-[var(--border)] border-b border-[var(--border)]">
          {summary.map((s) => (
            <div key={s.label} className="bg-[var(--bg-card)] px-4 py-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{s.label}</p>
              <p className="text-[16px] font-extrabold tabular-nums mt-0.5">{s.value}</p>
            </div>
          ))}
        </div>

        {/* Breakdown */}
        <div className="overflow-auto no-scrollbar flex-1">
          {isYesno ? (
            items.length === 0 ? (
              <p className="py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">No answers recorded.</p>
            ) : (
              <div className="divide-y divide-[var(--border)]">
                {items.map((it, k) => (
                  <div key={k} className="px-5 py-3.5 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold leading-snug">
                        <span className="text-[var(--text-muted)] font-bold mr-1.5 tabular-nums">{k + 1}.</span>
                        {it.question}
                      </p>
                      {/* Remarks are invisible on the card — some questions (e.g. "which
                          departments…") carry their real answer here, not in the Yes/No. */}
                      {it.remark && (
                        <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)] flex items-start gap-1.5">
                          <StickyNote size={12} className="mt-0.5 shrink-0" />
                          <span className="italic">{it.remark}</span>
                        </p>
                      )}
                    </div>
                    <span className="text-[10.5px] font-bold px-2.5 py-1 rounded-full shrink-0"
                      style={{
                        color: it.yes ? 'var(--accent-green)' : 'var(--accent-red)',
                        background: it.yes ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                      }}>
                      {it.answer}
                    </span>
                  </div>
                ))}
              </div>
            )
          ) : employees.length === 0 ? (
            <p className="py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">No ratings recorded.</p>
          ) : (
            <>
              <div className="overflow-x-auto no-scrollbar">
                <table className="w-full" style={{ minWidth: Math.max(560, 300 + columns.length * 72) }}>
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] sticky left-0 z-10 bg-[var(--table-header-bg)]">
                        Employee
                      </th>
                      {columns.map((c) => (
                        <th key={c.id} title={c.text}
                          className="px-2 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] whitespace-nowrap">
                          {c.id}
                        </th>
                      ))}
                      <th className="px-3 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Total</th>
                      <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {employees.map((emp) => {
                      const n = Object.keys(emp.ratings || {}).length;
                      const empPct = Number(emp.score_pct) || 0;
                      return (
                        <tr key={emp.id} className="group border-b border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors">
                          <td className="px-4 py-3 text-[12.5px] font-bold sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--table-hover)]">
                            {emp.name}
                          </td>
                          {columns.map((c) => (
                            <td key={c.id} className="px-2 py-3 text-center">
                              <RatingCell value={emp.ratings?.[c.id]} />
                            </td>
                          ))}
                          <td className="px-3 py-3 text-center text-[12.5px] font-bold tabular-nums text-[var(--text-muted)]">
                            {emp.grand_total ?? 0}<span className="opacity-60">/{n * SCALE_MAX}</span>
                          </td>
                          <td className="px-4 py-3 text-center text-[12.5px] font-extrabold tabular-nums" style={{ color: scoreColor(empPct) }}>
                            {empPct}%
                          </td>
                        </tr>
                      );
                    })}
                    {/* Per-criterion mean across everyone this respondent rated. */}
                    <tr className="bg-[var(--table-header-bg)]">
                      <td className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] sticky left-0 z-10 bg-[var(--table-header-bg)]">
                        Criterion avg
                      </td>
                      {columns.map((c) => {
                        const a = columnAvg(c.id);
                        return (
                          <td key={c.id} className="px-2 py-3 text-center text-[12px] font-extrabold tabular-nums"
                            style={{ color: a == null ? 'var(--text-muted)' : scoreColor((a / SCALE_MAX) * 100) }}>
                            {a == null ? '—' : a}
                          </td>
                        );
                      })}
                      <td className="px-3 py-3 text-center text-[12px] font-extrabold tabular-nums text-[var(--text-muted)]">
                        {grandTotal}<span className="opacity-60">/{answered * SCALE_MAX}</span>
                      </td>
                      <td className="px-4 py-3 text-center text-[12px] font-extrabold tabular-nums" style={{ color: scoreColor(pct) }}>{pct}%</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Column headers are criterion codes — spell them out. */}
              {columns.length > 0 && (
                <div className="px-5 py-4 border-t border-[var(--border)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">Criteria</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5">
                    {columns.map((c) => (
                      <p key={c.id} className="text-[11.5px] text-[var(--text-muted)] leading-snug">
                        <span className="font-extrabold text-[var(--accent-indigo)] mr-1.5">{c.id}</span>{c.text}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-between gap-3">
          <span className="text-[11px] font-medium text-[var(--text-muted)]">
            {isYesno
              ? `${entry.yes ?? 0} of ${entry.total ?? 0} answered yes`
              : `${employees.length} employee${employees.length === 1 ? '' : 's'} · ${answered} rating${answered === 1 ? '' : 's'}`}
          </span>
          <button type="button" onClick={onClose}
            className="px-3.5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold hover:opacity-90 transition-opacity">
            Close
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-lg">
      <p className="text-[11px] font-bold text-[var(--text-muted)] mb-1">{label}</p>
      <p className="text-[12px] font-bold text-[var(--accent-indigo)]">Avg score: {payload[0].value}%</p>
    </div>
  );
};

const ReviewReport = ({ title = 'Review Reports', subtitle = 'Evaluation & feedback responses across teams' }) => {
  useAuth(); // ensure an authenticated context; server scopes results by role.

  const periods = useMemo(() => monthOptions(), []);

  const [view, setView] = useState('cards');
  const [source, setSource] = useState('accountability');
  const [period, setPeriod] = useState(currentPeriod());
  const [companyId, setCompanyId] = useState('');
  const [respondentId, setRespondentId] = useState('');
  const [q, setQ] = useState('');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // The submission whose full breakdown is open in the detail dialog (null = closed).
  const [detail, setDetail] = useState(null);

  // The company list comes from the report payload, which is already role-scoped (spec §3).
  // It must NOT be loaded from /companies — that endpoint returns every client in the system,
  // which would show a client-side MD the names of every other customer.
  const companies = useMemo(() => data?.companies || [], [data]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = { source: source || 'accountability' };
      if (period) params.period = period;
      if (companyId) params.company_id = companyId;
      const res = await getReviewReports(params);
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e.response?.data?.detail || 'Failed to load review reports');
    } finally {
      setLoading(false);
    }
  }, [source, period, companyId]);

  // Fetch on mount + whenever source / period / company change.
  useEffect(() => { load(); }, [load]);

  const sources = data?.sources?.length ? data.sources : DEFAULT_SOURCES;
  const totals = data?.totals || {};
  const isYesno = !!data?.is_yesno;
  const sourceMeta = data?.source || {};
  // Privacy: client HOD/employees are locked to their own reviews (server
  // already filters the data). Only admin/staff/client-admin/MD can pick a
  // different respondent, signalled by can_pick. Hide the picker otherwise.
  const canPick = data?.can_pick !== false;

  // Spec §10 — each form has its OWN status vocabulary (Accountable / Taking Ownership /
  // Follows Culture …), served on `source.status` so the wording lives in one place. The
  // generic fallback only applies if an unknown form_type ever appears.
  const isChecklist = isYesno || (source || '') === 'implementation_feedback';
  const statusVocab = sourceMeta.status || (isChecklist
    ? { high: 'Compliant', mid: 'Partial', low: 'At Risk' }
    : { high: 'Strong', mid: 'Healthy', low: 'Needs Focus' });
  // Bands: ≥85 high · 70–84 mid · <70 low.
  const statusLabel = (p) => (p >= 85 ? statusVocab.high : p >= 70 ? statusVocab.mid : statusVocab.low);

  const companyOpts = useMemo(
    () => [{ id: '', name: 'All Companies' }, ...companies.map((c) => ({ id: String(c.id), name: c.name }))],
    [companies],
  );
  // A caller scoped to one company has nothing to choose between — drop the picker rather
  // than show a one-item dropdown that hints other companies exist.
  const canPickCompany = companies.length > 1;
  const respondentOpts = useMemo(
    () => [{ id: '', name: 'All Respondents' },
      ...(data?.respondent_options || []).map((r) => ({ id: String(r.id), name: r.name }))],
    [data],
  );

  // Respondent + search are refined client-side over the fetched entries.
  const rows = useMemo(() => {
    const entries = data?.entries || [];
    const needle = q.trim().toLowerCase();
    return entries.filter((e) => {
      if (respondentId && String(e.respondent_id) !== String(respondentId)) return false;
      if (!needle) return true;
      const names = e.matrix ? (e.employees || []).map((emp) => emp.name).join(' ') : '';
      return `${e.name} ${e.company} ${names}`.toLowerCase().includes(needle);
    });
  }, [data, respondentId, q]);

  // Client-side pagination over the filtered submission cards (9 per page).
  const pCards = usePaged(rows || [], 9);

  // Respondent + Search narrow `rows` client-side, so the server `totals` no longer describe
  // what is on screen. Everything summarised below is recomputed from `rows` — the same set
  // the cards and the CSV export use — so the headline figures, the Grand Total and the
  // export can never disagree with each other.
  const isFiltered = Boolean(respondentId || q.trim());

  const agg = useMemo(() => {
    const respondentIds = new Set();
    const employeeIds = new Set();
    const bands = { high: 0, mid: 0, low: 0 };
    let ratingSum = 0, ratingCount = 0, yes = 0, answered = 0;

    rows.forEach((r) => {
      if (r.respondent_id) respondentIds.add(String(r.respondent_id));
      const pct = Number(r.score_pct) || 0;
      bands[pct >= 85 ? 'high' : pct >= 70 ? 'mid' : 'low'] += 1;

      if (r.yesno) {
        yes += r.yes || 0;
        answered += r.total || 0;
      } else {
        (r.employees || []).forEach((emp) => {
          // An employee rated by two different HODs is one person but two rating sets —
          // count the person once, the ratings twice.
          employeeIds.add(String(emp.id));
          ratingSum += Number(emp.grand_total) || 0;
          ratingCount += Object.keys(emp.ratings || {}).length;
        });
      }
    });

    return {
      responses: rows.length,
      respondents: respondentIds.size,
      employees: employeeIds.size,
      ratingSum,
      ratingCount,
      avgRating: ratingCount ? Math.round((ratingSum / ratingCount) * 100) / 100 : null,
      scorePct: ratingCount ? Math.round((ratingSum / (ratingCount * SCALE_MAX)) * 100) : null,
      yes,
      no: Math.max(0, answered - yes),
      answered,
      yesPct: answered ? Math.round((yes / answered) * 100) : null,
      bands,
    };
  }, [rows]);

  const overallPct = isYesno ? agg.yesPct : agg.scorePct;

  const kpis = [
    {
      value: agg.responses, label: 'Responses',
      sub: isFiltered ? `of ${totals.responses ?? 0} submitted` : 'Submitted',
      tone: 'blue', icon: ClipboardCheck,
    },
    {
      value: agg.respondents, label: 'Respondents',
      sub: isFiltered ? `of ${totals.respondent_count ?? 0} reviewers` : 'Reviewers',
      tone: 'green', icon: Users,
    },
    isYesno
      ? { value: agg.yesPct == null ? '—' : `${agg.yesPct}%`, label: 'Yes Rate', sub: `${agg.yes} of ${agg.answered} answered`, tone: 'yellow', icon: Star }
      : { value: nOrDash(agg.avgRating), label: 'Avg Rating', sub: `Out of ${SCALE_MAX}`, tone: 'yellow', icon: Star },
  ];

  // ── Grand Total ───────────────────────────────────────────────
  // Responses / Respondents / Avg Rating already head the page as KPI tiles, and the filter
  // bar already names the form, period and company — so none of that is repeated here. This
  // band carries only the figures that exist nowhere else on the page.
  const grandSubtitle = isFiltered
    ? `Aggregated across ${agg.responses} of ${totals.responses ?? 0} responses`
    : 'Aggregated across every response shown above';

  // A checklist totals its answers; a rating matrix totals the scores themselves — the sheet's
  // grand total is Σ of every rating given, against the maximum that many cells could score.
  const grandStats = isYesno ? [
    { label: 'Questions Answered', value: agg.answered, sub: 'Across all responses', tone: 'blue', icon: ListChecks },
    { label: 'Yes', value: agg.yes, sub: 'Answered yes', tone: 'green', icon: CheckCircle2 },
    { label: 'No', value: agg.no, sub: 'Answered no', tone: 'red', icon: XCircle },
  ] : [
    { label: 'Employees Rated', value: agg.employees, sub: 'Distinct people', tone: 'blue', icon: UserCheck },
    { label: 'Ratings Counted', value: agg.ratingCount, sub: `Cells scored 0–${SCALE_MAX}`, tone: 'plain', icon: ListChecks },
    { label: 'Sum of Ratings', value: agg.ratingSum, sub: `of ${agg.ratingCount * SCALE_MAX} possible`, tone: 'green', icon: Sigma },
  ];

  const bandSegments = [
    { key: 'high', label: statusVocab.high, count: agg.bands.high, color: 'var(--accent-green)' },
    { key: 'mid', label: statusVocab.mid, count: agg.bands.mid, color: 'var(--accent-orange)' },
    { key: 'low', label: statusVocab.low, count: agg.bands.low, color: 'var(--accent-red)' },
  ];

  // Monthly trend: average score % across rated people per period (ascending).
  const trendData = useMemo(() => {
    const trend = data?.trend || { periods: [], people: [] };
    const ps = [...(trend.periods || [])].reverse();
    const people = trend.people || [];
    return ps.map((p) => {
      const vals = people
        .map((pp) => pp.scores?.[p.id])
        .filter((v) => typeof v === 'number');
      const avg = vals.length ? Math.round(vals.reduce((a, v) => a + v, 0) / vals.length) : null;
      return { m: p.name, rating: avg };
    });
  }, [data]);

  // M6 — export the currently filtered entries as a CSV file, built client-side.
  const exportCsv = useCallback(() => {
    const cell = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lastHeader = isYesno ? 'Yes %' : 'Avg Rating';
    const countHeader = isYesno ? 'Answered' : 'Rated';
    const header = ['Respondent', 'Company', 'Period', countHeader, 'Score %', lastHeader];
    const body = rows.map((r) => {
      const last = isYesno
        ? (r.total ? Math.round(((r.yes || 0) / r.total) * 100) : (r.score_pct ?? ''))
        : (r.avg ?? '');
      const count = isYesno ? (r.total ?? 0) : (r.employees || []).length;
      return [r.name ?? '', r.company ?? '', r.period_label || r.period || '', count, r.score_pct ?? '', last];
    });
    // Trailing Grand Total row — the same figures the on-screen summary shows.
    const totalRow = isYesno
      ? ['GRAND TOTAL', `${agg.respondents} respondents`, `${agg.responses} responses`,
        agg.answered, agg.yesPct ?? '', agg.yesPct ?? '']
      : ['GRAND TOTAL', `${agg.respondents} respondents`, `${agg.responses} responses`,
        agg.employees, agg.scorePct ?? '', agg.avgRating ?? ''];
    const csv = [header, ...body, totalRow].map((row) => row.map(cell).join(',')).join('\r\n');
    const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const date = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `tpms-review-${source || 'form'}-${date}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [rows, isYesno, source, agg]);

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={ClipboardCheck} title={title} subtitle={subtitle}>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {[{ k: 'cards', label: 'Cards', icon: LayoutGrid }, { k: 'trend', label: 'Monthly Trend', icon: LineIcon }].map((v) => (
            <button key={v.k} onClick={() => setView(v.k)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${view === v.k ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <v.icon size={13} /> {v.label}
            </button>
          ))}
        </div>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        <HeroButton icon={Download} onClick={exportCsv}>Export CSV</HeroButton>
      </DashboardHero>

      {/* KPI tiles */}
      <div className="grid grid-cols-3 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Filter bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 items-end">
          {[
            { label: 'Form', value: source, set: setSource, opts: sources.map((s) => ({ id: s.id, name: s.label })) },
            { label: 'Period', value: period, set: setPeriod, opts: periods },
            // Company picker only when the caller actually spans more than one (spec §3).
            ...(canPickCompany ? [{ label: 'Company', value: companyId, set: setCompanyId, opts: companyOpts }] : []),
            // Respondent picker only for users allowed to view others (can_pick).
            ...(canPick ? [{ label: 'Respondent', value: respondentId, set: setRespondentId, opts: respondentOpts }] : []),
          ].map((f) => (
            <label key={f.label} className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{f.label}</span>
              <FilterSelect value={f.value} onChange={f.set} options={f.opts} />
            </label>
          ))}
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Search</span>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Respondent, company, employee…"
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          </label>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="py-24 flex flex-col items-center justify-center text-[var(--text-muted)]">
          <RefreshCw size={26} className="animate-spin mb-3 opacity-60" />
          <p className="text-[13px] font-bold">Loading review reports…</p>
        </div>
      ) : view === 'trend' ? (
        <Section title="Monthly Score Trend" subtitle="Average review score % over time" icon={LineIcon}>
          <div className="px-2 py-5 h-[320px]">
            {trendData.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-[var(--text-muted)]">
                <AlertTriangle size={24} className="mb-2 opacity-40" />
                <p className="text-[13px] font-bold">No trend data for this selection.</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="m" tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line type="monotone" dataKey="rating" stroke="var(--accent-indigo)" strokeWidth={2.5} dot={{ r: 4, fill: 'var(--accent-indigo)' }} activeDot={{ r: 6 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </Section>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm py-16 text-center">
          <MessageSquare size={26} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">No responses match these filters.</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">Try a different form, period, company or respondent.</p>
        </div>
      ) : (
        <>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {pCards.pageRows.map((r, i) => {
            const pctVal = Number(r.score_pct) || 0;
            return (
              <div key={`${r.respondent_id}-${r.period}-${i}`}
                role="button" tabIndex={0}
                aria-label={`Open ${r.name} rating breakdown`}
                onClick={() => setDetail(r)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDetail(r); }
                }}
                className="group/card cursor-pointer rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4 flex flex-col transition-all hover:shadow-md hover:border-[var(--accent-indigo)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-indigo)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-main)]">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="w-9 h-9 rounded-xl text-white text-[11px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {initials(r.name)}
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-bold truncate">{r.name || '—'}</p>
                      <p className="text-[11px] text-[var(--text-muted)] truncate">{r.company || '—'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-[10px] font-bold px-2 py-1 rounded-md tabular-nums" style={{ color: 'var(--accent-indigo)', background: 'var(--input-bg)' }}>{r.period_label || r.period}</span>
                    <Maximize2 size={13} className="text-[var(--text-muted)] opacity-0 group-hover/card:opacity-100 transition-opacity" />
                  </div>
                </div>

                <div className="flex items-center gap-2 mt-3">
                  {!isYesno && r.avg !== '' && r.avg != null && <Stars value={Number(r.avg)} />}
                  <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(pctVal) }}>{pctVal}%</span>
                  {statusLabel(pctVal) && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ color: scoreColor(pctVal), background: `${scoreColor(pctVal)}1a` }}>{statusLabel(pctVal)}</span>
                  )}
                </div>

                {/* Matrix: per-employee scores · Checklist: per-question answers */}
                <div className="mt-3 flex-1 max-h-56 overflow-y-auto no-scrollbar space-y-1.5">
                  {isYesno
                    ? (r.items || []).map((it, k) => (
                      <div key={k} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="text-[var(--text-main)] truncate">{it.question}</span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0" style={{ color: it.yes ? 'var(--accent-green)' : 'var(--accent-red)', background: it.yes ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)' }}>{it.answer}</span>
                      </div>
                    ))
                    : (r.employees || []).map((emp) => (
                      <div key={emp.id} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="text-[var(--text-main)] truncate">{emp.name}</span>
                        <span className="text-[11px] font-extrabold tabular-nums shrink-0" style={{ color: scoreColor(Number(emp.score_pct) || 0) }}>{emp.score_pct}%</span>
                      </div>
                    ))}
                </div>

                {/* The form name is the same on every card (it's the Form filter) — the slot
                    is better spent signalling that the card opens a breakdown. */}
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--border)] text-[11px] font-medium text-[var(--text-muted)]">
                  <span>{isYesno ? `${r.yes ?? 0}/${r.total ?? 0} yes` : `${(r.employees || []).length} rated`}</span>
                  <span className="font-bold group-hover/card:text-[var(--accent-indigo)] transition-colors">View breakdown</span>
                </div>
              </div>
            );
          })}
        </div>
        <Pager {...pCards} label="submissions" />
        </>
      )}

      {/* M6 — Grand Total. Computed from the filtered rows, so it always describes exactly
          what the cards above show (and what Export CSV writes out). */}
      {!loading && rows.length > 0 && (
        <Section title="Grand Total" icon={Sigma} subtitle={grandSubtitle}
          action={isFiltered && (
            <span className="inline-flex items-center gap-1.5 text-[10.5px] font-bold px-2.5 py-1 rounded-full border shrink-0"
              style={{ color: 'var(--accent-indigo)', background: 'var(--accent-indigo-bg)', borderColor: 'var(--accent-indigo-border)' }}>
              <Filter size={11} /> Filtered view
            </span>
          )}>
          {/* Hairline grid — gap-px over the border colour keeps the rules clean at any wrap. */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-px bg-[var(--border)]">
            {grandStats.map((s) => <TotalStat key={s.label} {...s} />)}
          </div>

          {/* Spread across the status bands the cards are labelled with. */}
          <div className="px-5 py-4 border-t border-[var(--border)] space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                {isChecklist ? 'Compliance spread' : 'Review health spread'}
              </span>
              <span className="text-[11.5px] font-bold text-[var(--text-muted)]">
                Overall{' '}
                <span className="text-[13px] tabular-nums" style={{ color: scoreColor(overallPct || 0) }}>
                  {overallPct == null ? '—' : `${overallPct}%`}
                </span>
              </span>
            </div>
            <div className="h-2.5 rounded-full overflow-hidden flex bg-[var(--input-bg)]">
              {bandSegments.filter((s) => s.count > 0).map((s) => (
                <div key={s.key} title={`${s.label}: ${s.count}`} style={{ width: `${(s.count / agg.responses) * 100}%`, background: s.color }} />
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
              {bandSegments.map((s) => (
                <span key={s.key} className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
                  <span className="text-[var(--text-muted)]">{s.label}</span>
                  <span className="tabular-nums font-extrabold" style={{ color: s.color }}>{s.count}</span>
                  <span className="text-[10.5px] text-[var(--text-muted)] tabular-nums">
                    ({agg.responses ? Math.round((s.count / agg.responses) * 100) : 0}%)
                  </span>
                </span>
              ))}
            </div>
          </div>
        </Section>
      )}

      {/* Full breakdown for the clicked card. */}
      <AnimatePresence>
        {detail && (
          <ReviewDetailModal
            key={`${detail.respondent_id}-${detail.period}`}
            entry={detail}
            sourceLabel={sourceMeta.label || ''}
            isYesno={!!detail.yesno}
            statusLabel={statusLabel}
            onClose={() => setDetail(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default ReviewReport;
