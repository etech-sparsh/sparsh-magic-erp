import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { PartyPopper, XCircle, Loader2, Printer, Check, X } from 'lucide-react';
import { getPublicOffer, respondToOffer } from '../../../services/hrmsPublicApi';
import OfferPaper from '../../../features/hrms/recruitment/OfferPaper';

/**
 * HRMS ▸ PUBLIC offer letter.
 *
 * Mounted OUTSIDE PrivateRoute. Renders the SAME `OfferPaper` the recruiter previewed, so
 * what was proof-read is exactly what the candidate signs — two renderings would drift, and
 * the one that drifts is the one somebody acts on.
 *
 * Print-to-PDF works from here: `.no-print` hides the chrome and the letter keeps its
 * accent bars via `print-color-adjust: exact`.
 */

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-100 py-8 px-4 print:bg-white print:p-0">
    <div className="max-w-3xl mx-auto print:max-w-none">{children}</div>
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const OfferPage = () => {
  const { code } = useParams();

  const [offer, setOffer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [mode, setMode] = useState(null);          // 'accept' | 'decline'
  const [signature, setSignature] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  useEffect(() => {
    document.title = 'Your offer';
    getPublicOffer(code)
      .then(({ data }) => {
        setOffer(data);
        if (data?.designation) document.title = `Offer — ${data.designation}`;
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This offer link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const respond = async (action) => {
    setError('');
    if (action === 'accept' && !signature.trim()) {
      setError('Please type your full name to accept.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await respondToOffer(code, {
        action,
        signature: signature.trim() || null,
        note: note.trim() || null,
      });
      setDone(data);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'Your response could not be recorded. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <div className="py-24 flex flex-col items-center gap-3 text-slate-500">
          <Loader2 size={24} className="animate-spin" />
          <p className="text-[14px]">Loading your offer…</p>
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

  const responded = done || offer.already_responded;
  const finalStatus = done?.status || offer.status;

  return (
    <Shell>
      {responded && (
        <Card className="p-6 mb-4 text-center no-print">
          {finalStatus === 'Accepted' ? (
            <>
              <PartyPopper size={32} className="mx-auto text-emerald-500" />
              <h1 className="mt-3 text-[19px] font-bold text-slate-900">
                Congratulations — offer accepted
              </h1>
            </>
          ) : (
            <>
              <Check size={32} className="mx-auto text-slate-400" />
              <h1 className="mt-3 text-[19px] font-bold text-slate-900">Response recorded</h1>
            </>
          )}
          <p className="mt-2 text-[14px] text-slate-600">
            {done?.message
              || (finalStatus === 'Accepted'
                ? 'Your acceptance has been recorded. The team will be in touch about your onboarding.'
                : 'Thank you for letting us know.')}
          </p>
        </Card>
      )}

      <Card className="overflow-hidden print:border-0 print:shadow-none print:rounded-none">
        <OfferPaper offer={offer} />
      </Card>

      <div className="mt-4 no-print">
        {!responded ? (
          <Card className="p-6">
            <h2 className="text-[16px] font-bold text-slate-900">Your response</h2>
            <p className="text-[12.5px] text-slate-500">
              Please take your time. You can only respond once.
            </p>

            {!mode ? (
              <div className="mt-5 flex flex-col sm:flex-row gap-2">
                <button type="button" onClick={() => setMode('accept')}
                  className="flex-1 h-11 rounded-lg bg-slate-900 text-white text-[14px] font-bold flex items-center justify-center gap-2">
                  <Check size={16} /> Accept this offer
                </button>
                <button type="button" onClick={() => setMode('decline')}
                  className="flex-1 h-11 rounded-lg border border-slate-300 text-slate-700 text-[14px] font-bold flex items-center justify-center gap-2">
                  <X size={16} /> Decline
                </button>
              </div>
            ) : mode === 'accept' ? (
              <div className="mt-5 space-y-3">
                <div>
                  <label htmlFor="o-sig" className="block text-[12px] font-semibold text-slate-700 mb-1.5">
                    Type your full name to sign *
                  </label>
                  <input id="o-sig" value={signature} onChange={(e) => setSignature(e.target.value)}
                    placeholder="Your full name"
                    className="w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-[14px] text-slate-900 focus:border-slate-500 focus:outline-none" />
                  <p className="mt-1 text-[11.5px] text-slate-400">
                    Typing your name here forms your acceptance of the terms above.
                  </p>
                </div>
                {error && (
                  <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
                    {error}
                  </div>
                )}
                <div className="flex gap-2">
                  <button type="button" onClick={() => { setMode(null); setError(''); }}
                    className="h-10 px-4 rounded-lg border border-slate-300 text-slate-700 text-[13px] font-bold">
                    Back
                  </button>
                  <button type="button" disabled={busy || !signature.trim()}
                    onClick={() => respond('accept')}
                    className="flex-1 h-10 rounded-lg bg-slate-900 text-white text-[14px] font-bold disabled:opacity-50 flex items-center justify-center gap-2">
                    {busy && <Loader2 size={15} className="animate-spin" />}
                    Confirm acceptance
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-5 space-y-3">
                <div>
                  <label htmlFor="o-note" className="block text-[12px] font-semibold text-slate-700 mb-1.5">
                    Anything you would like to tell us? (optional)
                  </label>
                  <textarea id="o-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-300 bg-white text-[14px] text-slate-900 resize-none focus:border-slate-500 focus:outline-none" />
                </div>
                {error && (
                  <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
                    {error}
                  </div>
                )}
                <div className="flex gap-2">
                  <button type="button" onClick={() => { setMode(null); setError(''); }}
                    className="h-10 px-4 rounded-lg border border-slate-300 text-slate-700 text-[13px] font-bold">
                    Back
                  </button>
                  <button type="button" disabled={busy} onClick={() => respond('decline')}
                    className="flex-1 h-10 rounded-lg border border-slate-400 text-slate-700 text-[14px] font-bold disabled:opacity-50">
                    {busy ? 'Recording…' : 'Confirm decline'}
                  </button>
                </div>
              </div>
            )}
          </Card>
        ) : null}

        <button type="button" onClick={() => window.print()}
          className="mt-3 w-full h-10 rounded-lg border border-slate-300 bg-white text-slate-700 text-[13px] font-bold flex items-center justify-center gap-2">
          <Printer size={15} /> Save a PDF copy
        </button>

        <p className="mt-3 text-center text-[11.5px] text-slate-400">
          Questions about this offer? Reply to the email that brought you here.
        </p>
      </div>

      <style>{`@media print { .no-print { display: none !important; } }`}</style>
    </Shell>
  );
};

export default OfferPage;
