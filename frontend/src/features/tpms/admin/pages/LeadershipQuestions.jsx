import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ClipboardCheck, RefreshCw, AlertTriangle, CheckCircle2, X, ShieldAlert, Pencil,
  Save, RotateCcw, Star,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
} from '../../common/dashboardKit';
import {
  getLeadershipConfig, getLeadershipQuestions, updateLeadershipQuestion,
  saveLeadershipWeightages, restoreLeadershipQuestions,
} from '../../../../services/leadershipApi';
import {
  errText, fmtNum, isStaff, canEditWeightages, useLeadershipCompany,
} from '../../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ Questions & Weightages.

   "Feedback parameters will differ from designation to designation."
   "All parameters should have weightages to create scoring - HR and MD."

   Each level (L4 / L5 / L6 / L7+) has its own question set, and each question has four
   written options carrying the scores printed in the source document (1, 2, 4, 5 — the
   rubric awards no 3). The weightage column must total exactly 100 per level; the backend
   rejects anything else rather than silently normalising, because a half-configured level
   would otherwise produce a plausible-looking wrong score.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, hint, children }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}</span>
    {children}
    {hint && <span className="text-[10.5px] text-[var(--text-muted)] font-medium">{hint}</span>}
  </label>
);

/** Reword a question and restate its four options. Scores stay editable because the
 *  source rubric is under review — but item ids never change, since they key responses. */
const QuestionModal = ({ question, onClose, onSubmit }) => {
  const [title, setTitle] = useState(question.title || '');
  const [prompt, setPrompt] = useState(question.prompt || '');
  const [options, setOptions] = useState(
    (question.options || []).map((o) => ({ ...o, score: String(o.score) })));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const setOpt = (i, key, value) =>
    setOptions((os) => os.map((o, idx) => (idx === i ? { ...o, [key]: value } : o)));

  const submit = async (e) => {
    e.preventDefault();
    if (!prompt.trim()) { setErr('The question text is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({
        title: title.trim(),
        prompt: prompt.trim(),
        options: options.map((o) => ({
          option_id: o.option_id,
          label: String(o.label || '').trim(),
          score: Number(o.score),
        })),
      });
    } catch (ex) {
      setErr(errText(ex, 'Could not save the question.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 border-b border-[var(--border)] bg-[var(--bg-card)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <Pencil size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Edit Question</h3>
              <p className="text-[11px] text-[var(--text-muted)] font-mono">
                {question.level} · {question.item_id}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50 shrink-0">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          <Field label="Parameter">
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Managing others" className={inputCls} />
          </Field>
          <Field label="Question" hint="Shown to the feedback giver.">
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2}
              className={`${inputCls} resize-y`} />
          </Field>

          <div className="flex flex-col gap-2">
            <span className={labelCls}>Options &amp; scores</span>
            {options.map((o, i) => (
              <div key={o.option_id} className="grid grid-cols-[28px_1fr_86px] gap-2 items-center">
                <span className="text-[12px] font-bold text-[var(--text-muted)] text-center font-mono">
                  {o.option_id}
                </span>
                <input type="text" value={o.label} onChange={(e) => setOpt(i, 'label', e.target.value)}
                  className={inputCls} />
                <input type="number" min={1} max={5} step="1" value={o.score}
                  onChange={(e) => setOpt(i, 'score', e.target.value)}
                  className={`${inputCls} text-right tabular-nums`} />
              </div>
            ))}
            <span className="text-[10.5px] text-[var(--text-muted)]">
              The source document scores its four options 1, 2, 4 and 5 — it never awards a 3.
            </span>
          </div>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

const LeadershipQuestions = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  // Editing the question master stays with internal staff. HR and MD reach this screen to
  // read the rubric and set weightages — they cannot reword it.
  //
  // Nothing here reviews or approves the questions: the seeded questions and options are
  // the single source of truth and are used exactly as they stand.
  const admin = isStaff(user);
  const reviewer = canEditWeightages(user);

  const [config, setConfig] = useState(null);
  const [level, setLevel] = useState('L4');
  const [questions, setQuestions] = useState([]);
  const [summary, setSummary] = useState([]);
  const [draft, setDraft] = useState({});      // {item_id: string weightage}
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!reviewer) return undefined;
    let alive = true;
    getLeadershipConfig()
      .then((res) => { if (alive) setConfig(res.data); })
      .catch(() => {});
    return () => { alive = false; };
  }, [reviewer]);

  // The question master is company-scoped, so every request below needs the picked
  // company. Staff open this page before /companies has answered, so hold the load until
  // there is one rather than firing a request the backend can only reject.
  const load = useMemo(() => async () => {
    if (staff && !companyId) { setLoading(false); return; }
    setLoading(true);
    setError('');
    try {
      const res = await getLeadershipQuestions(companyId, level);
      const rows = res.data?.questions || [];
      setQuestions(rows);
      setSummary(res.data?.weightage_summary || []);
      setDraft(Object.fromEntries(rows.map((q) => [q.item_id, String(q.weightage ?? 0)])));
    } catch (e) {
      setError(errText(e, 'Could not load the questions.'));
    } finally {
      setLoading(false);
    }
  }, [level, companyId, staff]);

  useEffect(() => { if (reviewer) load(); }, [reviewer, load]);

  const total = useMemo(
    () => Math.round(questions.reduce((s, q) => s + (Number(draft[q.item_id]) || 0), 0) * 100) / 100,
    [questions, draft],
  );
  const isValid = Math.abs(total - 100) < 0.01;
  const dirty = questions.some((q) => (Number(draft[q.item_id]) || 0) !== (q.weightage ?? 0));

  const saveWeights = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await saveLeadershipWeightages(companyId, level, questions.map((q) => ({
        item_id: q.item_id, weightage: Number(draft[q.item_id]) || 0,
      })));
      setNotice('Weightages saved. Leadership Scores now use the updated values.');
      await load();
    } catch (e) {
      setError(errText(e, 'Could not save the weightages.'));
    } finally {
      setSaving(false);
    }
  };

  const restore = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const res = await restoreLeadershipQuestions(companyId, level);
      setNotice(`${res.data?.restored ?? 0} missing question(s) restored. Existing questions were not changed.`);
      await load();
    } catch (e) {
      setError(errText(e, 'Could not restore questions.'));
    } finally {
      setSaving(false);
    }
  };

  const saveQuestion = async (payload) => {
    await updateLeadershipQuestion(companyId, editing._id, payload);
    setEditing(null);
    setNotice('Question updated. Leadership Scores now use the updated wording.');
    await load();
  };

  if (!reviewer) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">HR, MD or an administrator only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Leadership questions and weightages decide how every leader is scored. HR and the
          MD set the weightages; an administrator maintains the wording.
        </p>
      </div>
    );
  }

  const levelMeta = (config?.levels || []).find((l) => l.code === level);
  const needsCompany = staff && !companyId;

  return (
    <div className="space-y-5">
      <DashboardHero icon={ClipboardCheck} title="Leadership Score — Questions"
        subtitle="Level-specific parameters, options and weightages">
        {/* Questions are stored per company, so staff pick one first. */}
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        <HeaderSelect value={level} onChange={setLevel}
          options={(config?.levels || [{ code: 'L4', label: 'L4' }]).map(
            (l) => ({ id: l.code, name: l.label }))} />
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {notice}
        </div>
      )}

      {/* Per-level weightage health, so a mis-set level is visible without hunting. */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {summary.map((s) => (
          <button key={s.level} type="button" onClick={() => setLevel(s.level)}
            className={`text-left rounded-2xl border bg-[var(--bg-card)] p-4 transition-all hover:shadow-md ${
              s.level === level ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)]'}`}>
            <p className="text-[12.5px] font-extrabold">{s.label}</p>
            <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5 leading-snug">{s.theme}</p>
            <p className="text-[20px] font-extrabold tabular-nums mt-2"
              style={{ color: s.is_valid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {fmtNum(s.total_weightage)}%
            </p>
            <p className="text-[10.5px] text-[var(--text-muted)]">
              {s.questions} question{s.questions === 1 ? '' : 's'}
              {!s.is_valid && <span className="text-[var(--accent-red)] font-bold"> · must total 100%</span>}
            </p>
          </button>
        ))}
      </div>

      <Section title={levelMeta?.label || level} icon={Star} subtitle={levelMeta?.theme || ''}
        action={admin ? (
          <button type="button" onClick={restore} disabled={saving || needsCompany}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <RotateCcw size={13} /> Restore missing
          </button>
        ) : null}>
        {/* Questions are per company, so an unpicked company means nothing to show — say
            that instead of an empty table reading a misleading 0% total. */}
        {needsCompany ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Pick a company above to load its questions and weightages.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading questions…
          </div>
        ) : (
          <>
            <TableShell minWidth={900}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>#</Th><Th>Parameter / Question</Th><Th>Options &amp; scores</Th>
                  <Th align="right">Weightage</Th><Th align="right">Edit</Th>
                </tr>
              </thead>
              <tbody>
                {questions.map((q, i) => (
                  <tr key={q._id} className="border-b border-[var(--border)] last:border-0">
                    <Td className="tabular-nums text-[var(--text-muted)] font-mono">{i + 1}</Td>
                    <Td>
                      <span className="font-bold">{q.title}</span>
                      <span className="block text-[11px] text-[var(--text-muted)] mt-0.5 max-w-[320px]">
                        {q.prompt}
                      </span>
                    </Td>
                    <Td>
                      <div className="flex flex-col gap-0.5 max-w-[340px]">
                        {(q.options || []).map((o) => (
                          <span key={o.option_id} className="text-[11px] text-[var(--text-muted)]">
                            <span className="font-mono font-bold">{o.option_id}</span> {o.label}
                            <span className="font-bold text-[var(--text-main)] tabular-nums"> · {o.score}</span>
                          </span>
                        ))}
                      </div>
                    </Td>
                    <Td align="right">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        <input type="number" min={0} max={100} step="0.01"
                          value={draft[q.item_id] ?? ''} readOnly={!admin} disabled={!admin}
                          onChange={(e) => { setDraft((d) => ({ ...d, [q.item_id]: e.target.value })); setNotice(''); }}
                          className="w-20 px-2.5 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-bold tabular-nums text-right outline-none focus:border-[var(--accent-indigo)] disabled:opacity-70" />
                        <span className="text-[11px] font-bold text-[var(--text-muted)]">%</span>
                      </div>
                    </Td>
                    <Td align="right">
                      {admin && (
                        <button type="button" onClick={() => setEditing(q)}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                          <Pencil size={12} />
                        </button>
                      )}
                    </Td>
                  </tr>
                ))}

                {/* Grand total — the rule the save enforces. */}
                <tr style={{ background: isValid ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)' }}>
                  <Td /><Td className="font-extrabold uppercase tracking-wide text-[11px]"
                    style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    Grand Total
                  </Td>
                  <Td />
                  <Td align="right">
                    <span className="text-[15px] font-extrabold tabular-nums pr-6"
                      style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {fmtNum(total)}%
                    </span>
                  </Td>
                  <Td />
                </tr>
              </tbody>
            </TableShell>

            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <p className="text-[11.5px] font-bold"
                style={{ color: isValid ? 'var(--text-muted)' : 'var(--accent-red)' }}>
                {!admin
                  ? 'Weightages are maintained by an administrator.'
                  : isValid
                    ? 'Total is 100% — ready to save.'
                    : `Total must be exactly 100% (currently ${fmtNum(total)}%).`}
              </p>
              <div className="flex items-center gap-2" style={{ display: admin ? undefined : 'none' }}>
                <button type="button" onClick={load} disabled={saving || !dirty}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                  <RefreshCw size={13} /> Discard
                </button>
                <button type="button" onClick={saveWeights} disabled={saving || !isValid || !dirty}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
                  {saving ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
                  {saving ? 'Saving…' : 'Save Weightages'}
                </button>
              </div>
            </div>
          </>
        )}
      </Section>

      <AnimatePresence>
        {editing && (
          <QuestionModal key={editing._id} question={editing}
            onClose={() => setEditing(null)} onSubmit={saveQuestion} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipQuestions;
