import React, { useCallback, useEffect, useState } from 'react';
import {
  ClipboardCheck, Plus, X, Copy, Check, ExternalLink, ThumbsUp, ThumbsDown, Clock,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getAssessments, getAssessableCandidates, sendAssessment, reviewAssessment, assessUrlFor,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ assessments with dual review.
 *
 * Two people sign off every submission: HR, and the hiring manager who raised the
 * requisition. The card shows BOTH decisions side by side — the whole point is to surface
 * disagreement before an interview panel is booked, and a single merged verdict would hide it.
 *
 * Which slot the current user fills is decided by the SERVER (`my_slot`, `awaiting_me`), not
 * re-derived here. The client never has to know the dual-review rules.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const LIFECYCLE_TONE = {
  Assigned: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  'In Progress': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Submitted: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Passed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Failed: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

const DecisionChip = ({ label, decision, by }) => (
  <div className="flex items-center gap-1.5">
    <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </span>
    {decision ? (
      <span className={`px-1.5 py-0.5 rounded text-[10.5px] font-bold ${
        decision === 'Pass'
          ? 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]'
          : 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'}`}
        title={by ? `by ${by}` : undefined}>
        {decision}
      </span>
    ) : (
      <span className="px-1.5 py-0.5 rounded bg-[var(--input-bg)] text-[var(--text-muted)] text-[10.5px] font-bold">
        Pending
      </span>
    )}
  </div>
);

const SendModal = ({ onClose, onSent }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    uk: '', title: '', instructions: '', link: '', max_score: 100, due_date: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    getAssessableCandidates(scope)
      .then(({ data }) => setPeople(data?.candidates || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load candidates.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await sendAssessment({
        ...form,
        max_score: Number(form.max_score) || 100,
        link: form.link || null,
        due_date: form.due_date || null,
      }, scope);
      showSuccess('Assessment sent');
      onSent();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not send the assessment.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Send an assessment</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-3 overflow-y-auto">
          <div>
            <label className={LABEL} htmlFor="a-uk">Candidate *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No candidates are waiting for an assessment. Only roles flagged
                <strong> Requires assessment </strong> on their posting appear here, once
                they reach the assessment stage.
              </p>
            ) : (
              <select id="a-uk" required value={form.uk} onChange={set('uk')} className={FIELD}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>
                    {p.candidate_name} — {p.application_status}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className={LABEL} htmlFor="a-title">Title *</label>
            <input id="a-title" required value={form.title} onChange={set('title')}
              placeholder="e.g. Excel modelling task" className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="a-inst">Instructions</label>
            <textarea id="a-inst" rows={4} value={form.instructions} onChange={set('instructions')}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2">
              <label className={LABEL} htmlFor="a-link">External test link</label>
              <input id="a-link" value={form.link} onChange={set('link')}
                placeholder="https://…" className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="a-max">Max score</label>
              <input id="a-max" type="number" min="1" value={form.max_score}
                onChange={set('max_score')} className={FIELD} />
            </div>
          </div>
          <div>
            <label className={LABEL} htmlFor="a-due">Due date</label>
            <input id="a-due" type="date" value={form.due_date} onChange={set('due_date')} className={FIELD} />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.uk || !form.title.trim()}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Sending…' : 'Send'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const ReviewModal = ({ assessment: a, onClose, onReviewed }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [decision, setDecision] = useState('');
  const [score, setScore] = useState(a.score ?? '');
  const [remarks, setRemarks] = useState('');
  const [saving, setSaving] = useState(false);

  const otherSlot = a.my_slot === 'hr' ? 'manager' : 'hr';
  const otherLabel = otherSlot === 'hr' ? 'HR' : 'Hiring manager';
  const otherDecision = a[`${otherSlot}_decision`];

  const submit = async () => {
    setSaving(true);
    try {
      await reviewAssessment(a.assessment_no, {
        decision,
        score: score === '' ? null : Number(score),
        remarks: remarks.trim() || null,
      }, scope);
      showSuccess(`Decision recorded: ${decision}`);
      onReviewed();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record your decision.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {a.candidate_name}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">{a.assessment_no} · {a.title}</p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          {a.response && (
            <div>
              <p className={LABEL}>Candidate response</p>
              <p className="p-3 rounded-lg bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap max-h-48 overflow-y-auto">
                {a.response}
              </p>
            </div>
          )}
          {(a.attachments || []).length > 0 && (
            <div>
              <p className={LABEL}>Attachments</p>
              <ul className="space-y-1">
                {a.attachments.map((f, i) => (
                  <li key={i} className="text-[12.5px] text-[var(--text-main)]">{f.name}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="p-3 rounded-lg border border-[var(--border)]">
            <DecisionChip label={otherLabel} decision={otherDecision}
              by={a[`${otherSlot}_decision_by_name`]} />
            {a[`${otherSlot}_remarks`] && (
              <p className="mt-1.5 text-[12px] text-[var(--text-muted)]">
                “{a[`${otherSlot}_remarks`]}”
              </p>
            )}
            {!otherDecision && (
              <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                They have not decided yet — your decision does not wait on theirs.
              </p>
            )}
          </div>

          <div>
            <label className={LABEL} htmlFor="r-score">Score (out of {a.max_score})</label>
            <input id="r-score" type="number" min="0" max={a.max_score} value={score}
              onChange={(e) => setScore(e.target.value)} className={FIELD} />
            {a.recommendation && (
              <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                Suggested: <strong>{a.recommendation}</strong> — advisory only, the decision is yours.
              </p>
            )}
          </div>

          <div>
            <span className={LABEL}>Your decision *</span>
            <div className="flex gap-2">
              {[['Pass', ThumbsUp], ['Fail', ThumbsDown]].map(([value, Icon]) => (
                <button key={value} type="button" onClick={() => setDecision(value)}
                  className={`flex-1 h-10 rounded-lg border text-[13px] font-bold flex items-center justify-center gap-2 transition-colors ${
                    decision === value
                      ? value === 'Pass'
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : 'border-[var(--accent-red)] bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                      : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  <Icon size={15} /> {value}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)]">
              The candidate advances to interviews only when <strong>both</strong> HR and the
              hiring manager pass.
            </p>
          </div>

          <div>
            <label className={LABEL} htmlFor="r-remarks">Remarks</label>
            <textarea id="r-remarks" rows={3} value={remarks} onChange={(e) => setRemarks(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none" />
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="button" disabled={saving || !decision} onClick={submit}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : 'Record decision'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const AssessmentBoard = () => {
  const { can, scope, companyId } = useHrms();
  const { showError } = useNotification();

  const [data, setData] = useState({ assessments: [], stats: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [showSend, setShowSend] = useState(false);
  const [reviewing, setReviewing] = useState(null);
  const [copied, setCopied] = useState(null);

  const canSend = can(CAP.ASSESSMENT_SEND);
  const canReview = can(CAP.ASSESSMENT_REVIEW);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getAssessments({
        ...scope, mine: filter === 'mine' || undefined,
        status: ['Sent', 'Opened', 'Completed', 'Reviewed'].includes(filter) ? filter : undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load assessments.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, filter]);

  useEffect(() => { load(); }, [load]);

  const copy = async (code) => {
    try {
      await navigator.clipboard.writeText(assessUrlFor(code));
      setCopied(code);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      showError("Couldn't copy to clipboard.");
    }
  };

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={ClipboardCheck}
        title="Assessments"
        subtitle="Send assessments and dual-review them (HR + hiring manager) before interviews."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canSend && (
              <button type="button" onClick={() => setShowSend(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> Send
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[['Awaiting candidate', stats.awaiting_candidate], ['To review by me', stats.to_review],
          ['Passed', stats.passed], ['Failed', stats.failed]].map(([label, value]) => (
          <div key={label} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
            <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{value ?? 0}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {[['all', 'All'], ['mine', `To review by me${stats.to_review ? ` (${stats.to_review})` : ''}`],
          ['Sent', 'Assigned'], ['Opened', 'In progress'], ['Completed', 'Submitted'],
          ['Reviewed', 'Reviewed']].map(([key, label]) => (
          <button key={key} type="button" onClick={() => setFilter(key)}
            className={`px-2.5 py-1 rounded-lg text-[12px] font-bold border ${
              filter === key
                ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <HrmsLoading label="Loading assessments…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.assessments.length === 0 ? (
        <HrmsEmpty icon={ClipboardCheck} title="No assessments"
          hint={canSend ? 'Send one to a candidate at the assessment stage.' : undefined} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.assessments.map((a) => (
            <div key={a.assessment_no}
              className={`p-4 rounded-xl border bg-[var(--bg-card)] space-y-3 ${
                a.awaiting_me ? 'border-[var(--accent-indigo)] ring-1 ring-[var(--accent-indigo)]'
                              : 'border-[var(--border)]'}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                    {a.candidate_name}
                  </p>
                  <p className="font-mono text-[10.5px] text-[var(--text-muted)]">
                    {a.assessment_no}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${
                  LIFECYCLE_TONE[a.lifecycle] || LIFECYCLE_TONE.Assigned}`}>
                  {a.lifecycle}
                </span>
              </div>

              <p className="text-[12.5px] text-[var(--text-main)]">{a.title}</p>

              <div className="flex flex-wrap items-center gap-3">
                <DecisionChip label="HR" decision={a.hr_decision} by={a.hr_decision_by_name} />
                <DecisionChip label="Manager" decision={a.manager_decision}
                  by={a.manager_decision_by_name} />
              </div>

              {typeof a.score === 'number' && (
                <p className="text-[12px] text-[var(--text-muted)]">
                  Score: <strong className="text-[var(--text-main)]">{a.score}</strong> / {a.max_score}
                  {a.recommendation ? ` · ${a.recommendation}` : ''}
                </p>
              )}

              {a.access_code && (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--input-bg)]">
                  <span className="flex-1 font-mono text-[10.5px] text-[var(--text-muted)] truncate">
                    {assessUrlFor(a.access_code)}
                  </span>
                  <button type="button" onClick={() => copy(a.access_code)}
                    title="Copy the candidate's link"
                    className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                    {copied === a.access_code ? <Check size={13} /> : <Copy size={13} />}
                  </button>
                </div>
              )}

              <div className="flex items-center gap-2">
                {a.link && (
                  <a href={a.link} target="_blank" rel="noopener noreferrer"
                    className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
                    <ExternalLink size={12} /> Test
                  </a>
                )}
                {canReview && a.awaiting_me && (
                  <button type="button" onClick={() => setReviewing(a)}
                    className="h-8 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold ml-auto">
                    Review
                  </button>
                )}
                {a.my_decision && (
                  <span className="ml-auto text-[11.5px] text-[var(--text-muted)] flex items-center gap-1">
                    <Clock size={11} /> You said {a.my_decision}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showSend && (
        <SendModal onClose={() => setShowSend(false)}
          onSent={() => { setShowSend(false); load(); }} />
      )}
      {reviewing && (
        <ReviewModal assessment={reviewing} onClose={() => setReviewing(null)}
          onReviewed={() => { setReviewing(null); load(); }} />
      )}
    </div>
  );
};

export default AssessmentBoard;
