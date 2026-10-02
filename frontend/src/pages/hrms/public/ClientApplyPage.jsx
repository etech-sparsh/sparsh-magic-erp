import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { Briefcase, MapPin, CheckCircle2 } from 'lucide-react';

/**
 * The public application page for a CLIENT company's vacancy.
 *
 * Reached with no account and no token, by anyone with the link. Separate from
 * /apply/:code, which is Sparsh Magic's OWN recruitment — same contract, different
 * endpoint, different tenant.
 *
 * -- Why this uses bare axios ------------------------------------------------------
 * The app's shared client attaches an Authorization header and redirects to /login on a
 * 401. Neither is right here: an applicant has no session, and bouncing them to a login
 * screen would lose the application they were part-way through writing.
 *
 * -- What it shows on a bad link ---------------------------------------------------
 * Whatever the server says, and nothing more. The API answers an unknown code and a
 * closed vacancy with deliberately opaque messages so the page cannot be used to probe
 * which codes exist; repeating them verbatim keeps that property.
 */

const API = import.meta.env.VITE_API_BASE_URL || '/api';

const FIELD = 'w-full px-3 py-2 rounded-lg border border-[var(--input-border,#d4d4d8)] '
  + 'bg-white text-[13.5px] text-[#18181b] outline-none focus:border-[#6366f1]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[#71717a] mb-1';

const ClientApplyPage = () => {
  const { code } = useParams();
  const [ad, setAd] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const [form, setForm] = useState({
    candidate_name: '', email: '', phone: '', cv_reference: '',
    current_employer: '', notice_period: '', declaration: false,
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/hrms/public/client-apply/${code}`);
      setAd(data);
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'This application link could not be opened.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    setSubmitting(true);
    try {
      const { data } = await axios.post(
        `${API}/hrms/public/client-apply/${code}`, form);
      setDone(data);
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'Your application could not be submitted.');
    } finally {
      setSubmitting(false);
    }
  };

  const ready = form.candidate_name.trim() && form.email.trim()
    && form.phone.trim() && form.cv_reference.trim() && form.declaration;

  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#fafafa]">
        <p className="text-[13px] font-bold text-[#71717a]">Loading…</p>
      </div>
    );
  }

  if (error && !ad) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#fafafa] px-4">
        <div className="max-w-md text-center">
          <h1 className="text-[18px] font-bold text-[#18181b]">
            This vacancy is not available
          </h1>
          <p className="mt-2 text-[13px] text-[#71717a]">{error}</p>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#fafafa] px-4">
        <div className="max-w-md text-center">
          <CheckCircle2 size={40} className="mx-auto text-[#16a34a]" />
          <h1 className="mt-3 text-[18px] font-bold text-[#18181b]">
            {done.already_applied
              ? 'You have already applied for this role'
              : 'Application received'}
          </h1>
          <p className="mt-2 text-[13px] text-[#71717a]">
            {done.already_applied
              ? 'We already have your application on file. There is no need to send it again.'
              : 'Thank you. If your experience matches what the role needs, somebody will '
                + 'be in touch.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#fafafa] py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-5">
        <header className="bg-white rounded-2xl border border-[#e4e4e7] p-6">
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 rounded-xl bg-[#eef2ff] text-[#6366f1]
              grid place-items-center shrink-0">
              <Briefcase size={20} />
            </div>
            <div className="min-w-0">
              <h1 className="text-[20px] font-bold text-[#18181b]">{ad.title}</h1>
              <p className="mt-0.5 flex items-center gap-3 text-[12.5px] text-[#71717a]">
                {ad.location && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin size={13} /> {ad.location}
                  </span>
                )}
                {ad.employment_type && <span>{ad.employment_type}</span>}
                {ad.salary_range_min != null && (
                  <span className="tabular-nums">
                    {Number(ad.salary_range_min).toLocaleString()} –{' '}
                    {Number(ad.salary_range_max).toLocaleString()}
                  </span>
                )}
              </p>
            </div>
          </div>

          {[['About the role', ad.summary],
            ['Responsibilities', ad.responsibilities],
            ['Requirements', ad.requirements]].map(([label, body]) => (body ? (
              <section key={label} className="mt-5">
                <h2 className="text-[11px] font-bold uppercase tracking-widest
                  text-[#71717a]">{label}</h2>
                <p className="mt-1 text-[13.5px] text-[#3f3f46] whitespace-pre-wrap">
                  {body}
                </p>
              </section>
            ) : null))}
        </header>

        <div className="bg-white rounded-2xl border border-[#e4e4e7] p-6 space-y-3">
          <h2 className="text-[15px] font-bold text-[#18181b]">Apply for this role</h2>

          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="ca-name">Full name</label>
              <input id="ca-name" className={FIELD} value={form.candidate_name}
                onChange={set('candidate_name')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="ca-email">Email</label>
              <input id="ca-email" className={FIELD} type="email" value={form.email}
                onChange={set('email')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="ca-phone">Phone</label>
              <input id="ca-phone" className={FIELD} value={form.phone}
                onChange={set('phone')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="ca-emp">Current employer</label>
              <input id="ca-emp" className={FIELD} value={form.current_employer}
                onChange={set('current_employer')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="ca-notice">Notice period</label>
              <input id="ca-notice" className={FIELD} value={form.notice_period}
                onChange={set('notice_period')} placeholder="30 days" />
            </div>
            <div>
              <label className={LABEL} htmlFor="ca-cv">Link to your CV</label>
              <input id="ca-cv" className={FIELD} value={form.cv_reference}
                onChange={set('cv_reference')}
                placeholder="A shared link we can open" />
            </div>
          </div>

          <label className="flex items-start gap-2 text-[12.5px] text-[#3f3f46] pt-1">
            <input type="checkbox" className="mt-0.5" checked={form.declaration}
              onChange={(e) => setForm((f) => ({ ...f, declaration: e.target.checked }))} />
            I confirm the information above is accurate, and consent to it being shared
            with the hiring company for this role.
          </label>

          {error && (
            <p className="text-[12.5px] text-[#dc2626]">{error}</p>
          )}

          <button
            type="button"
            disabled={!ready || submitting}
            onClick={submit}
            className="w-full py-2.5 rounded-lg bg-[#6366f1] text-white text-[13.5px]
              font-bold disabled:opacity-50"
          >
            {submitting ? 'Sending…' : 'Submit application'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ClientApplyPage;
