import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  CheckCircle2, Clock, AlertTriangle, Loader2, ShieldAlert, Award, Lock, Send,
} from 'lucide-react';
import { getAssignedLeadershipForm, submitLeadershipFeedback } from '../../../services/leadershipApi';
import { errText, parseUtc } from './leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ the feedback giver's form (/lf/:token).

   The landing page for the unique link sent to each of a leader's 8 feedback givers.
   The token alone decides which leader is being rated and which level's questions are
   shown — there is no picker, so a giver cannot reach any form but their own.

   Access needs BOTH a signed-in session (the route sits behind PrivateRoute) and a token
   whose assignment names that same user; the backend enforces the second, so a forwarded
   link is useless to anyone else.

   Answers are option choices, not a numeric scale: the giver picks one of four written
   statements and never sees the score behind it, nor the question's weightage. That is
   deliberate — showing the numbers would invite people to work backwards to a total.
   ───────────────────────────────────────────────────────────── */

const Shell = ({ children }) => (
  <div className="max-w-3xl mx-auto w-full py-2">{children}</div>
);

const Notice = ({ icon: NoticeIcon, tone, title, detail }) => (
  <Shell>
    <div className="bg-[var(--bg-card)] rounded-[24px] border border-[var(--border)] p-8 text-center">
      <div className={`mx-auto w-14 h-14 rounded-2xl flex items-center justify-center mb-4 ${tone}`}>
        <NoticeIcon size={26} />
      </div>
      <h1 className="text-lg font-black text-[var(--text-main)] mb-1">{title}</h1>
      {detail && <p className="text-[13px] font-medium text-[var(--text-muted)]">{detail}</p>}
    </div>
  </Shell>
);

/** One question: the prompt, then its four written options as radio cards. */
const QuestionCard = ({ index, question, picked, onPick, disabled }) => (
  <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
    <div className="px-5 py-4 border-b border-[var(--border)] flex items-start gap-3">
      <span className="w-7 h-7 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center text-[12px] font-extrabold shrink-0 tabular-nums">
        {index + 1}
      </span>
      <div className="min-w-0">
        <p className="text-[14px] font-bold text-[var(--text-main)] leading-snug">{question.prompt}</p>
        {question.title && (
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{question.title}</p>
        )}
      </div>
    </div>
    <div className="p-3 flex flex-col gap-2">
      {(question.options || []).map((opt) => {
        const active = picked === opt.option_id;
        return (
          <label
            key={opt.option_id}
            className={`flex items-start gap-3 px-3.5 py-3 rounded-xl border cursor-pointer transition-colors ${
              active
                ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                : 'border-[var(--border)] hover:bg-[var(--input-bg)]'
            } ${disabled ? 'cursor-default opacity-70' : ''}`}
          >
            <input
              type="radio"
              name={question.item_id}
              checked={active}
              disabled={disabled}
              onChange={() => onPick(question.item_id, opt.option_id)}
              className="mt-0.5 w-[17px] h-[17px] accent-[var(--accent-indigo)] cursor-pointer disabled:cursor-default shrink-0"
            />
            <span className="text-[13px] font-medium text-[var(--text-main)] leading-snug">
              {opt.label}
            </span>
          </label>
        );
      })}
    </div>
  </div>
);

const LeadershipFormPage = () => {
  const { token } = useParams();
  const [state, setState] = useState({ loading: true });
  const [picks, setPicks] = useState({});
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getAssignedLeadershipForm(token);
        if (alive) setState({ loading: false, data: res.data });
      } catch (err) {
        if (!alive) return;
        setState({
          loading: false,
          // The backend distinguishes 403 / 404 / 409 / 410 — surface its own message.
          error: errText(err, 'This feedback link could not be opened.'),
          code: err.response?.status,
        });
      }
    })();
    return () => { alive = false; };
  }, [token]);

  const d = state.data;
  const questions = useMemo(() => d?.questions || [], [d]);
  const answered = Object.keys(picks).length;
  const complete = questions.length > 0 && answered === questions.length;

  const pick = useCallback((questionId, optionId) => {
    setPicks((p) => ({ ...p, [questionId]: optionId }));
    setError('');
  }, []);

  const submit = async () => {
    if (!complete) {
      setError('Please answer every question before submitting.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await submitLeadershipFeedback(token, Object.entries(picks).map(
        ([question_id, option_id]) => ({ question_id, option_id }),
      ));
      setDone(true);
    } catch (e) {
      setError(errText(e, 'Your feedback could not be submitted. Please try again.'));
      setSaving(false);
    }
  };

  if (state.loading) {
    return (
      <Shell>
        <div className="bg-[var(--bg-card)] rounded-[24px] border border-[var(--border)] p-8 flex items-center justify-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="animate-spin" size={18} />
          <span className="text-[13px] font-bold">Opening your feedback form…</span>
        </div>
      </Shell>
    );
  }

  if (done || d?.state === 'submitted' || state.code === 409) {
    return <Notice icon={CheckCircle2} tone="bg-emerald-50 text-emerald-600"
      title="Thank you — your feedback has been recorded."
      detail="Your response is confidential and cannot be traced back to you. This form does not need to be filled again." />;
  }

  if (d?.state === 'expired' || state.code === 410) {
    return <Notice icon={Clock} tone="bg-amber-50 text-amber-600"
      title="This feedback link has expired."
      detail="The cycle this feedback belonged to has closed. Please contact your HR team if you still need to submit it." />;
  }

  // Arriving before the window opens is the expected consequence of inviting people
  // early, so it gets its own state rather than a refusal. Placed above the form: the
  // questions must not render at all, or a giver answers all of them and loses the answers
  // to a 403 on Submit. Deliberately NOT 'expired' — "not yet" and "too late" are opposite
  // problems, and only one of them means come back.
  if (d?.window === 'pending') {
    const opensOn = parseUtc(d.window_opens_at);
    return <Notice icon={Clock} tone="bg-sky-50 text-sky-600"
      title="This feedback form has not opened yet."
      detail={opensOn
        ? `It opens on ${opensOn.toLocaleString(undefined, {
          day: 'numeric', month: 'long', year: 'numeric',
          hour: '2-digit', minute: '2-digit',
        })}. Your link stays valid — please come back then and it will be ready.`
        : 'Your link stays valid. Please come back once your HR team opens the window.'} />;
  }

  if (state.code === 403) {
    return <Notice icon={ShieldAlert} tone="bg-rose-50 text-rose-600"
      title="This form was assigned to someone else." detail={state.error} />;
  }

  if (state.error) {
    return <Notice icon={AlertTriangle} tone="bg-rose-50 text-rose-600"
      title="This link is not valid." detail={state.error} />;
  }

  return (
    <Shell>
      <div className="flex flex-col gap-4">
        {/* Who is being rated, and the confidentiality promise the document insists on. */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
          <div className="px-5 py-4 flex items-start gap-3 border-b border-[var(--border)]">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0">
              <Award size={20} />
            </span>
            <div className="min-w-0">
              <h1 className="text-[17px] font-extrabold tracking-tight text-[var(--text-main)] leading-tight">
                Leadership Feedback
              </h1>
              <p className="text-[13px] font-bold text-[var(--text-main)] mt-1">
                {d.subject_name}
                {d.subject_designation && (
                  <span className="font-medium text-[var(--text-muted)]"> · {d.subject_designation}</span>
                )}
              </p>
              <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
                {[d.level_label, d.level_theme, d.cycle_label].filter(Boolean).join(' · ')}
              </p>
            </div>
          </div>
          <div className="px-5 py-3 flex items-start gap-2 bg-[var(--accent-green-bg)]">
            <Lock size={14} className="text-[var(--accent-green)] mt-0.5 shrink-0" />
            <p className="text-[12px] font-medium text-[var(--accent-green)]">
              Your responses are completely confidential. {d.subject_name || 'The leader'} receives
              only a combined score and never sees who gave which rating.
            </p>
          </div>
        </div>

        {questions.map((q, i) => (
          <QuestionCard
            key={q.item_id}
            index={i}
            question={q}
            picked={picks[q.item_id]}
            onPick={pick}
            disabled={saving}
          />
        ))}

        {error && (
          <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
            <AlertTriangle size={15} /> {error}
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-5 py-4 flex flex-wrap items-center justify-between gap-3">
          <span className="text-[12.5px] font-bold text-[var(--text-muted)] tabular-nums">
            {answered} of {questions.length} answered
          </span>
          <button
            type="button"
            onClick={submit}
            disabled={saving || !complete}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            {saving ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
        <p className="text-[11px] text-[var(--text-muted)] text-center pb-2">
          Feedback can be submitted once. Please review your answers before submitting.
        </p>
      </div>
    </Shell>
  );
};

export default LeadershipFormPage;
