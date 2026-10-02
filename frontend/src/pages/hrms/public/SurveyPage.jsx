import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ClipboardCheck, Check, Loader2, ShieldCheck, XCircle } from 'lucide-react';
import { getPublicSurvey, submitSurvey } from '../../../services/hrmsPublicApi';

/**
 * HRMS ▸ PUBLIC new-hire experience survey (Phase INT-2, SOP §10).
 *
 * Mounted OUTSIDE PrivateRoute, like every other public HRMS page.
 *
 * -- The page deliberately does not know who you are ----------------------------------
 * There is no name, no employee code and no role anywhere on this screen, because the API
 * does not send them. That is not an oversight to be tidied up later: a survey page that
 * greets you by name is one you can screenshot beside your answers, and the whole value of
 * the instrument rests on people believing their individual response is not readable.
 *
 * The anonymity promise is stated ON THE PAGE, in the words the server sends, rather than
 * assumed. Somebody deciding how honest to be about their induction deserves to know what
 * happens to the answer before they give it, not after.
 *
 * -- One submission, and the page says so before you send ------------------------------
 * A response is final once submitted. The confirm step exists because "final" is a surprise
 * if you meet it after clicking.
 */

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-100 py-8 px-4">
    <div className="max-w-2xl mx-auto">{children}</div>
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const SurveyPage = () => {
  const { code } = useParams();

  const [survey, setSurvey] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [scores, setScores] = useState({});
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  useEffect(() => {
    document.title = 'Your feedback';
    getPublicSurvey(code)
      .then(({ data }) => {
        setSurvey(data);
        if (data?.title) document.title = data.title;
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This survey link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const questions = survey?.questions || [];
  const scale = survey?.scale || { min: 1, max: 5, labels: {} };
  const points = Array.from(
    { length: (scale.max - scale.min) + 1 }, (_, i) => scale.min + i);
  const answered = questions.filter((q) => scores[q.key] != null).length;
  const complete = questions.length > 0 && answered === questions.length;

  const submit = async () => {
    setError('');
    if (!complete) {
      setError('Please answer every question before submitting.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await submitSurvey(code, { scores, comment });
      setDone(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Your answers could not be submitted.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <Card className="p-10 flex flex-col items-center gap-3 text-slate-500">
          <Loader2 size={22} className="animate-spin" />
          <p className="text-[13px] font-medium">Loading…</p>
        </Card>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="p-10 flex flex-col items-center gap-3 text-center">
          <XCircle size={26} className="text-rose-500" />
          <p className="text-[14px] font-semibold text-slate-800">{loadError}</p>
          <p className="text-[12.5px] text-slate-500 max-w-sm">
            If you were expecting to give feedback, ask the HR team to send you a fresh link.
          </p>
        </Card>
      </Shell>
    );
  }

  if (done || survey?.already_submitted) {
    return (
      <Shell>
        <Card className="p-10 flex flex-col items-center gap-3 text-center">
          <div className="h-12 w-12 rounded-2xl bg-emerald-50 text-emerald-600
            grid place-items-center">
            <Check size={24} />
          </div>
          <p className="text-[15px] font-bold text-slate-800">
            {done?.message || 'You have already answered this survey. Thank you.'}
          </p>
          <p className="text-[12.5px] text-slate-500 max-w-sm">
            Your answers are reported as averages only. Nobody sees your individual response.
          </p>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card className="p-6 sm:p-8">
        <div className="flex items-start gap-3.5 pb-5 border-b border-slate-200">
          <div className="h-10 w-10 rounded-xl bg-indigo-50 text-indigo-600
            grid place-items-center shrink-0">
            <ClipboardCheck size={19} />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg font-bold text-slate-900 tracking-tight">
              {survey?.title}
            </h1>
            {survey?.intro && (
              <p className="text-[12.5px] text-slate-500 mt-1">{survey.intro}</p>
            )}
          </div>
        </div>

        {/* The anonymity promise, in the server's own words. Shown BEFORE the questions,
            because it is what somebody needs in order to decide how honestly to answer. */}
        {survey?.anonymity_note && (
          <div className="mt-5 flex items-start gap-2.5 rounded-xl bg-slate-50
            border border-slate-200 px-3.5 py-3">
            <ShieldCheck size={16} className="text-slate-500 mt-0.5 shrink-0" />
            <p className="text-[12px] text-slate-600">{survey.anonymity_note}</p>
          </div>
        )}

        <div className="mt-6 space-y-6">
          {questions.map((q, index) => (
            <fieldset key={q.key}>
              <legend className="text-[13.5px] font-semibold text-slate-800">
                <span className="text-slate-400 mr-1.5">{index + 1}.</span>
                {q.prompt}
              </legend>
              <div className="mt-3 flex flex-wrap gap-2">
                {points.map((point) => {
                  const selected = scores[q.key] === point;
                  return (
                    <button
                      key={point}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setScores((s) => ({ ...s, [q.key]: point }))}
                      className={`h-10 min-w-[3rem] px-3 rounded-xl text-[13px] font-bold
                        border transition-colors ${selected
                          ? 'bg-indigo-600 border-indigo-600 text-white'
                          : 'bg-white border-slate-200 text-slate-600 hover:border-slate-400'}`}
                    >
                      {point}
                    </button>
                  );
                })}
              </div>
              {/* The ends of the scale, once per question, so nobody has to remember
                  whether 5 is good. */}
              <div className="mt-1.5 flex justify-between text-[11px] text-slate-400
                max-w-[19rem]">
                <span>{scale.labels?.[String(scale.min)] || scale.min}</span>
                <span>{scale.labels?.[String(scale.max)] || scale.max}</span>
              </div>
            </fieldset>
          ))}
        </div>

        <div className="mt-6">
          <label htmlFor="survey-comment"
            className="block text-[12px] font-bold uppercase tracking-widest text-slate-400">
            Anything else? (optional)
          </label>
          <textarea
            id="survey-comment"
            rows={4}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Anything that would have made your first days easier."
            className="mt-1.5 w-full px-3 py-2 rounded-xl border border-slate-200
              text-[13px] text-slate-800 resize-none focus:outline-none
              focus:ring-2 focus:ring-indigo-500/30"
          />
        </div>

        {error && (
          <p className="mt-4 text-[12.5px] font-semibold text-rose-600">{error}</p>
        )}

        <div className="mt-6 pt-5 border-t border-slate-200 flex items-center
          justify-between gap-4 flex-wrap">
          <p className="text-[12px] text-slate-500">
            {answered} of {questions.length} answered.
            {' '}You can only submit once.
          </p>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !complete}
            className="h-10 px-5 rounded-xl bg-indigo-600 text-white text-[13px] font-bold
              inline-flex items-center gap-2 disabled:opacity-50 transition-opacity"
          >
            {busy && <Loader2 size={15} className="animate-spin" />}
            Submit my answers
          </button>
        </div>
      </Card>
    </Shell>
  );
};

export default SurveyPage;
