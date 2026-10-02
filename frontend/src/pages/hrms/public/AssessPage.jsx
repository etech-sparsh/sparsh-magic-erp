import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  ClipboardCheck, PartyPopper, XCircle, Loader2, Upload, X, ExternalLink, CalendarClock,
} from 'lucide-react';
import {
  getPublicAssessment, submitAssessment,
} from '../../../services/hrmsPublicApi';
import { readFileAsUpload } from '../../../services/hrmsPublicApi';

/**
 * HRMS ▸ PUBLIC assessment page.
 *
 * Mounted OUTSIDE PrivateRoute, like the apply page. Standalone chrome: a candidate is not
 * a user of this ERP and must never see its navigation.
 *
 * Simply loading this page marks the assessment **Opened** server-side, which is how HR
 * tells "never looked at it" from "opened it and went quiet". Revisiting after submission
 * shows a calm done screen rather than an error — a candidate re-checking their own link
 * has done nothing wrong.
 */

const MAX_MB = 15;
const MAX_FILES = 10;

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 py-8 px-4">
    <div className="max-w-2xl mx-auto">{children}</div>
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const AssessPage = () => {
  const { code } = useParams();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [response, setResponse] = useState('');
  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    document.title = 'Assessment';
    getPublicAssessment(code)
      .then(({ data: d }) => {
        setData(d);
        if (d?.title) document.title = `Assessment — ${d.title}`;
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This assessment link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const pickFiles = (e) => {
    const chosen = Array.from(e.target.files || []);
    if (files.length + chosen.length > MAX_FILES) {
      setError(`You can attach at most ${MAX_FILES} files.`);
      e.target.value = '';
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_MB * 1024 * 1024);
    if (tooBig) {
      setError(`"${tooBig.name}" is too large. The limit is ${MAX_MB} MB per file.`);
      e.target.value = '';
      return;
    }
    setError('');
    setFiles((c) => [...c, ...chosen]);
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!response.trim() && files.length === 0) {
      setError('Add your response, or attach at least one file.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = { response: response.trim() || null };
      if (files.length) payload.attachments = await Promise.all(files.map(readFileAsUpload));
      await submitAssessment(code, payload);
      setDone(true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'Your assessment could not be submitted. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <div className="py-24 flex flex-col items-center gap-3 text-slate-500">
          <Loader2 size={24} className="animate-spin" />
          <p className="text-[14px]">Loading your assessment…</p>
        </div>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="p-8 text-center">
          <XCircle size={34} className="mx-auto text-slate-400" />
          <h1 className="mt-4 text-[18px] font-bold text-slate-900">Link unavailable</h1>
          <p className="mt-2 text-[14px] text-slate-600">{loadError}</p>
          <p className="mt-4 text-[12.5px] text-slate-400">
            If someone shared this with you, ask them for an up-to-date link.
          </p>
        </Card>
      </Shell>
    );
  }

  if (done || data?.already_done) {
    return (
      <Shell>
        <Card className="p-8 text-center">
          <PartyPopper size={34} className="mx-auto text-emerald-500" />
          <h1 className="mt-4 text-[20px] font-bold text-slate-900">
            {done ? 'Submitted!' : 'Already submitted'}
          </h1>
          <p className="mt-2 text-[14px] text-slate-600">
            {done
              ? 'Thank you. The hiring team will review your submission and be in touch.'
              : 'You have already completed this assessment. Nothing further is needed.'}
          </p>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card className="p-6 mb-4">
        <div className="flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-slate-900 text-white grid place-items-center shrink-0">
            <ClipboardCheck size={19} />
          </div>
          <div className="min-w-0">
            <h1 className="text-[20px] font-bold text-slate-900">{data.title}</h1>
            {data.candidate_name && (
              <p className="text-[13px] text-slate-500">For {data.candidate_name}</p>
            )}
          </div>
        </div>

        {data.due_date && (
          <p className="mt-4 flex items-center gap-2 text-[13px] text-slate-600">
            <CalendarClock size={14} className="text-slate-400" />
            Please submit by <strong>{data.due_date}</strong>
          </p>
        )}

        {data.instructions && (
          <div className="mt-4 pt-4 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900">Instructions</h2>
            <p className="mt-1.5 text-[13.5px] text-slate-600 whitespace-pre-wrap">
              {data.instructions}
            </p>
          </div>
        )}

        {data.link && (
          <a href={data.link} target="_blank" rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-2 h-10 px-4 rounded-lg bg-slate-900 text-white text-[13px] font-bold">
            <ExternalLink size={14} /> Open the test
          </a>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-[16px] font-bold text-slate-900">Your submission</h2>
        <p className="text-[12.5px] text-slate-500">
          Write your response below, attach files, or both.
        </p>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <div>
            <label htmlFor="s-response" className="block text-[12px] font-semibold text-slate-700 mb-1.5">
              Response
            </label>
            <textarea id="s-response" rows={8} value={response}
              onChange={(e) => setResponse(e.target.value)}
              placeholder="Type your answer here…"
              className="w-full px-3 py-2 rounded-lg border border-slate-300 bg-white text-[14px] text-slate-900 resize-y focus:border-slate-500 focus:outline-none" />
          </div>

          <div>
            <label htmlFor="s-files" className="block text-[12px] font-semibold text-slate-700 mb-1.5">
              Attachments (optional, up to {MAX_FILES}, {MAX_MB} MB each)
            </label>
            <label htmlFor="s-files"
              className="flex items-center gap-2 h-10 px-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 text-[13px] text-slate-500 cursor-pointer hover:border-slate-400">
              <Upload size={15} /> Add files…
            </label>
            <input id="s-files" type="file" multiple className="hidden"
              accept=".pdf,.doc,.docx,image/*" onChange={pickFiles} />
            {files.length > 0 && (
              <ul className="mt-2 space-y-1">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`}
                    className="flex items-center gap-2 text-[12.5px] text-slate-600">
                    <span className="truncate flex-1">{f.name}</span>
                    <button type="button" onClick={() => setFiles((c) => c.filter((_, j) => j !== i))}
                      className="p-0.5 text-slate-400 hover:text-red-500">
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {error && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
              {error}
            </div>
          )}

          <button type="submit" disabled={submitting}
            className="w-full h-11 rounded-lg bg-slate-900 text-white text-[14px] font-bold disabled:opacity-50 flex items-center justify-center gap-2">
            {submitting && <Loader2 size={16} className="animate-spin" />}
            {submitting ? 'Submitting…' : 'Submit assessment'}
          </button>
          <p className="text-center text-[11.5px] text-slate-400">
            You can only submit once — please check your work before sending.
          </p>
        </form>
      </Card>
    </Shell>
  );
};

export default AssessPage;
