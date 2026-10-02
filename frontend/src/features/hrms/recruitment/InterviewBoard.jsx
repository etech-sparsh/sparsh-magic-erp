import React, { useCallback, useEffect, useState } from 'react';
import {
  CalendarClock, Plus, X, Video, MapPin, Star, CalendarDays, Ban, Download, Clock,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getInterviews, getSchedulableCandidates, scheduleInterview, updateInterview,
  cancelInterview, evaluateInterview, getEmployees, inviteUrlFor,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ interviews.
 *
 * Grouped by day, because "what is happening today" is the question this screen exists to
 * answer. Every row carries `can_evaluate` computed **server-side**, so the Evaluate button
 * appears only where the API will actually accept a scorecard — including the MD-round
 * restriction, which the client never has to know about.
 */

const ROUNDS = ['HR Round', 'Technical', 'Manager Round', 'MD Round'];
const STATUSES = ['Scheduled', 'Completed', 'Cancelled', 'No Show'];
const COMPETENCIES = [
  ['technical', 'Technical Knowledge'],
  ['communication', 'Communication'],
  ['problem_solving', 'Problem Solving'],
  ['behavior', 'Behaviour'],
  ['confidence', 'Confidence'],
  ['team_fit', 'Team Fit'],
];

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const STATUS_TONE = {
  Scheduled: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Completed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Cancelled: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  'No Show': 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};
const OUTCOME_TONE = {
  Pass: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Fail: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Hold: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

/** Human day header — "Today", "Tomorrow", else a weekday + date. */
const dayLabel = (iso) => {
  if (!iso) return 'Unscheduled';
  const d = new Date(`${iso}T00:00:00`);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' });
};

const timeOf = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const ScheduleModal = ({ onClose, onScheduled }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    uk: '', round: 'HR Round', mode: 'Virtual', scheduled_at: '',
    duration_min: 45, interviewer_id: '', meeting_link: '', location: '', notes: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    Promise.all([
      getSchedulableCandidates(scope).then(({ data }) => setPeople(data?.candidates || [])),
      // The interviewer needs a real login account — a profile onboarded before the person
      // has one (`pending_user_link`) has no `user_id`, and its option would fall back to
      // the person's NAME as the submitted value, which the server rejects as an invalid id.
      getEmployees({ ...scope, limit: 500 })
        .then(({ data }) => setStaff((data?.employees || []).filter((e) => e.user_id))),
    ]).catch((err) => showError(err?.response?.data?.detail || 'Could not load options.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await scheduleInterview({
        ...form,
        duration_min: Number(form.duration_min) || 45,
        meeting_link: form.mode === 'Virtual' ? form.meeting_link : null,
        location: form.mode === 'Offline' ? form.location : null,
      }, scope);
      // The server WARNS and never blocks (short notice, an interview outside the
      // department's window). A warning the screen swallows is one nobody acts on.
      if (data?.warning) showError(data.warning);
      showSuccess('Interview scheduled');
      onScheduled();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not schedule the interview.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Schedule an interview</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-3 overflow-y-auto">
          <div>
            <label className={LABEL} htmlFor="i-uk">Candidate *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No candidates are ready to interview. Roles that require an assessment only
                become schedulable once the candidate reaches <strong>Assessment Passed</strong>.
              </p>
            ) : (
              <select id="i-uk" required value={form.uk} onChange={set('uk')} className={FIELD}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>
                    {p.candidate_name} — {p.application_status}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="i-round">Round</label>
              <select id="i-round" value={form.round} onChange={set('round')} className={FIELD}>
                {ROUNDS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="i-mode">Mode</label>
              <select id="i-mode" value={form.mode} onChange={set('mode')} className={FIELD}>
                <option value="Virtual">Virtual</option>
                <option value="Offline">In person</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="i-when">Date &amp; time *</label>
              <input id="i-when" type="datetime-local" required value={form.scheduled_at}
                onChange={set('scheduled_at')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="i-dur">Duration (minutes)</label>
              <input id="i-dur" type="number" min="15" step="15" value={form.duration_min}
                onChange={set('duration_min')} className={FIELD} />
            </div>
          </div>

          <div>
            <label className={LABEL} htmlFor="i-who">Interviewer *</label>
            <select id="i-who" required value={form.interviewer_id}
              onChange={set('interviewer_id')} className={FIELD}>
              <option value="">Select who will take it…</option>
              {staff.map((s) => (
                <option key={s.user_id} value={s.user_id}>{s.name}</option>
              ))}
            </select>
          </div>

          {form.mode === 'Virtual' ? (
            <div>
              <label className={LABEL} htmlFor="i-link">Meeting link *</label>
              <input id="i-link" required value={form.meeting_link} onChange={set('meeting_link')}
                placeholder="https://…" className={FIELD} />
            </div>
          ) : (
            <div>
              <label className={LABEL} htmlFor="i-loc">Location *</label>
              <input id="i-loc" required value={form.location} onChange={set('location')}
                placeholder="Meeting room, floor, address…" className={FIELD} />
            </div>
          )}

          <div>
            <label className={LABEL} htmlFor="i-notes">Notes</label>
            <input id="i-notes" value={form.notes} onChange={set('notes')} className={FIELD} />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.uk || !form.interviewer_id}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Scheduling…' : 'Schedule'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const StarRow = ({ label, value, onChange }) => (
  <div className="flex items-center justify-between gap-3">
    <span className="text-[12.5px] text-[var(--text-main)]">{label}</span>
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" aria-label={`${label} ${n}`}
          // Clicking the current value clears it — otherwise a mis-click can never be undone.
          onClick={() => onChange(value === n ? 0 : n)}
          className={n <= value ? 'text-[var(--accent-indigo)]' : 'text-[var(--border)]'}>
          <Star size={17} fill={n <= value ? 'currentColor' : 'none'} />
        </button>
      ))}
    </div>
  </div>
);

const EvaluateModal = ({ interview: i, onClose, onEvaluated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [scores, setScores] = useState(
    Object.fromEntries(COMPETENCIES.map(([k]) => [k, 0])));
  const [outcome, setOutcome] = useState('');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [saving, setSaving] = useState(false);

  const isMd = i.round === 'MD Round';

  const submit = async () => {
    setSaving(true);
    try {
      await evaluateInterview(i.interview_no, {
        ...scores, outcome, remarks: remarks.trim() || null, signature: signature.trim(),
      }, scope);
      showSuccess(`Recorded: ${outcome}`);
      onEvaluated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the evaluation.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {isMd ? 'MD interview decision' : 'Evaluate interview'}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {i.candidate_name} · {i.round}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <div className="space-y-2">
            {COMPETENCIES.map(([key, label]) => (
              <StarRow key={key} label={label} value={scores[key]}
                onChange={(v) => setScores((s) => ({ ...s, [key]: v }))} />
            ))}
          </div>

          <div>
            <span className={LABEL}>Decision *</span>
            <div className="flex gap-2">
              {(isMd ? ['Pass', 'Hold', 'Fail'] : ['Pass', 'Hold', 'Fail']).map((v) => (
                <button key={v} type="button" onClick={() => setOutcome(v)}
                  className={`flex-1 h-9 rounded-lg border text-[12.5px] font-bold ${
                    outcome === v
                      ? v === 'Pass'
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : v === 'Fail'
                        ? 'border-[var(--accent-red)] bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                        : 'border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-main)]'
                      : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  {isMd && v === 'Pass' ? 'Approve' : isMd && v === 'Fail' ? 'Reject' : v}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className={LABEL} htmlFor="e-remarks">Remarks</label>
            <textarea id="e-remarks" rows={3} value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none" />
          </div>

          <div>
            <label className={LABEL} htmlFor="e-sign">Signature *</label>
            <input id="e-sign" value={signature} onChange={(e) => setSignature(e.target.value)}
              placeholder="Type your full name" className={FIELD} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              This evaluation may justify a rejection later, so it is recorded against your name.
            </p>
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="button" disabled={saving || !outcome || !signature.trim()}
              onClick={submit}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : 'Record'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const InterviewBoard = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ interviews: [], stats: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [round, setRound] = useState('');
  const [status, setStatus] = useState('');
  const [showSchedule, setShowSchedule] = useState(false);
  const [evaluating, setEvaluating] = useState(null);

  const canSchedule = can(CAP.INTERVIEW_SCHEDULE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getInterviews({
        ...scope, round: round || undefined, status: status || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load interviews.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, round, status]);

  useEffect(() => { load(); }, [load]);

  const setStatusFor = async (i, next) => {
    try {
      await updateInterview(i.interview_no, { status: next }, scope);
      showSuccess(`${i.interview_no} marked ${next}`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the interview.');
    }
  };

  const cancel = async (i) => {
    if (!window.confirm(`Cancel ${i.interview_no} (${i.round} — ${i.candidate_name})?`)) return;
    try {
      await cancelInterview(i.interview_no, scope);
      showSuccess('Interview cancelled');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not cancel.');
    }
  };

  // Group by day, preserving the server's chronological order.
  const groups = [];
  data.interviews.forEach((i) => {
    const key = i.day || null;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(i);
    else groups.push({ key, items: [i] });
  });

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={CalendarClock}
        title="Interviews"
        subtitle="Schedule rounds, capture scorecards and drive the decision chain."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canSchedule && (
              <button type="button" onClick={() => setShowSchedule(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> Schedule
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[['Today', stats.today], ['Upcoming', stats.upcoming],
          ['Completed', stats.completed], ['Cancelled / No show', stats.dropped]].map(([l, v]) => (
          <div key={l} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{l}</p>
            <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{v ?? 0}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select value={round} onChange={(e) => setRound(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All rounds</option>
          {ROUNDS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading interviews…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.interviews.length === 0 ? (
        <HrmsEmpty icon={CalendarClock} title="No interviews scheduled"
          hint={canSchedule
            ? 'Schedule one for a candidate who has cleared screening or their assessment.'
            : 'Interviews you are booked for will appear here.'} />
      ) : (
        <div className="space-y-5">
          {groups.map((g) => (
            <div key={g.key || 'none'}>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] flex items-center gap-1.5">
                <CalendarDays size={12} /> {dayLabel(g.key)}
              </p>
              <div className="space-y-2">
                {g.items.map((i) => (
                  <div key={i.interview_no}
                    className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] flex flex-wrap items-center gap-3">
                    <div className="text-center shrink-0 w-16">
                      <p className="text-[14px] font-bold text-[var(--text-main)]">
                        {timeOf(i.scheduled_at)}
                      </p>
                      <p className="text-[10.5px] text-[var(--text-muted)]">{i.duration_min}m</p>
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                        {i.candidate_name}
                      </p>
                      <p className="text-[11.5px] text-[var(--text-muted)] flex items-center gap-1.5 flex-wrap">
                        <span>{i.round}</span>
                        <span>·</span>
                        {i.mode === 'Virtual'
                          ? <><Video size={11} /> Virtual</>
                          : <><MapPin size={11} /> {i.location}</>}
                        <span>·</span>
                        <span>{i.interviewer_name}</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold ${
                        STATUS_TONE[i.status] || STATUS_TONE.Scheduled}`}>
                        {i.status}
                      </span>
                      {i.outcome && (
                        <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold ${
                          OUTCOME_TONE[i.outcome]}`}>
                          {i.outcome}
                        </span>
                      )}
                      {typeof i.average_score === 'number' && (
                        <span className="px-1.5 py-0.5 rounded bg-[var(--input-bg)] text-[10.5px] font-bold text-[var(--text-main)] flex items-center gap-0.5">
                          <Star size={10} fill="currentColor" /> {i.average_score}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5">
                      {i.mode === 'Virtual' && i.meeting_link && i.status === 'Scheduled' && (
                        <a href={i.meeting_link} target="_blank" rel="noopener noreferrer"
                          className="h-8 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold">
                          Join
                        </a>
                      )}
                      <a href={inviteUrlFor(i.interview_no)} title="Download calendar invite"
                        className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                        <Download size={13} />
                      </a>
                      {i.can_evaluate && !i.outcome && i.status !== 'Cancelled' && (
                        <button type="button" onClick={() => setEvaluating(i)}
                          className="h-8 px-3 rounded-lg border border-[var(--accent-indigo)] text-[var(--accent-indigo)] text-[11.5px] font-bold">
                          Evaluate
                        </button>
                      )}
                      {canSchedule && i.status === 'Scheduled' && (
                        <>
                          <button type="button" onClick={() => setStatusFor(i, 'No Show')}
                            title="Mark no show"
                            className="h-8 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)]">
                            <Clock size={12} />
                          </button>
                          <button type="button" onClick={() => cancel(i)} title="Cancel"
                            className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)]">
                            <Ban size={13} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {showSchedule && (
        <ScheduleModal onClose={() => setShowSchedule(false)}
          onScheduled={() => { setShowSchedule(false); load(); }} />
      )}
      {evaluating && (
        <EvaluateModal interview={evaluating} onClose={() => setEvaluating(null)}
          onEvaluated={() => { setEvaluating(null); load(); }} />
      )}
    </div>
  );
};

export default InterviewBoard;
