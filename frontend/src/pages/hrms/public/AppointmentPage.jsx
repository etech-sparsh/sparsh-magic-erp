import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { PartyPopper, XCircle, Loader2, Printer, Check } from 'lucide-react';
import {
  getPublicAppointment, acknowledgeAppointment,
} from '../../../services/hrmsPublicApi';
import AppointmentPaper from '../../../features/hrms/recruitment/AppointmentPaper';

/**
 * HRMS ▸ PUBLIC appointment letter (Phase 11-R, Item 3).
 *
 * Mounted OUTSIDE PrivateRoute, and modelled exactly on OfferPage. Renders the SAME
 * `AppointmentPaper` the HR team previewed, so what was proof-read is exactly what the
 * candidate acknowledges — two renderings would drift, and the one that drifts is the one
 * somebody acts on.
 *
 * There is no "decline" here, deliberately. Declining happens at the OFFER, one step
 * earlier; by the time an appointment letter exists the candidate has already accepted, and
 * offering a decline button would imply this is a second negotiation. A candidate who has
 * changed their mind needs a conversation, not a button.
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

const AppointmentPage = () => {
  const { code } = useParams();

  const [appointment, setAppointment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [signature, setSignature] = useState('');
  const [note, setNote] = useState('');
  // §7.5 Stage 7 — the NDA, Code of Conduct and policies, each accepted in its own right.
  const [agreed, setAgreed] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  useEffect(() => {
    document.title = 'Your appointment letter';
    getPublicAppointment(code)
      .then(({ data }) => {
        setAppointment(data);
        if (data?.designation) document.title = `Appointment — ${data.designation}`;
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This appointment link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const documents = appointment?.documents || [];
  const outstanding = documents.filter(
    (d) => d.required && !d.acknowledged_at && !agreed.has(d.doc));

  const toggleDoc = (name) => setAgreed((prev) => {
    const next = new Set(prev);
    if (next.has(name)) next.delete(name); else next.add(name);
    return next;
  });

  const acknowledge = async () => {
    setError('');
    if (outstanding.length) {
      setError(`Please read and accept each document first: ${outstanding.map((d) => d.doc).join(', ')}.`);
      return;
    }
    if (!signature.trim()) {
      setError('Please type your full name to acknowledge this letter.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await acknowledgeAppointment(code, {
        signature, note, documents: [...agreed] });
      setDone(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Your acknowledgement could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <div className="py-24 flex flex-col items-center gap-3 text-slate-500">
          <Loader2 size={24} className="animate-spin" />
          <p className="text-sm font-medium">Loading your appointment letter…</p>
        </div>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="p-10 text-center">
          <XCircle size={30} className="mx-auto text-slate-400" />
          <h1 className="text-lg font-bold text-slate-900 mt-4">
            This link is not available
          </h1>
          <p className="text-[13.5px] text-slate-500 mt-2 max-w-md mx-auto">{loadError}</p>
        </Card>
      </Shell>
    );
  }

  const acknowledged = done || appointment?.already_acknowledged;

  return (
    <Shell>
      {acknowledged && (
        <Card className="p-6 mb-4 text-center no-print print:hidden">
          <PartyPopper size={26} className="mx-auto text-emerald-600" />
          <h1 className="text-[17px] font-bold text-slate-900 mt-3">
            Your appointment is confirmed
          </h1>
          <p className="text-[13.5px] text-slate-600 mt-1.5 max-w-lg mx-auto">
            {done?.message
              || 'Your acknowledgement has been recorded. The HR team will be in touch about '
                 + 'your joining formalities.'}
          </p>
        </Card>
      )}

      <div className="flex items-center justify-end gap-2 mb-3 no-print print:hidden">
        <button
          type="button"
          onClick={() => window.print()}
          className="h-9 px-3.5 rounded-lg border border-slate-300 bg-white text-slate-700 text-[13px] font-bold flex items-center gap-1.5"
        >
          <Printer size={14} />
          Print / save as PDF
        </button>
      </div>

      <Card className="overflow-hidden print:border-0 print:shadow-none print:rounded-none">
        <AppointmentPaper appointment={appointment} />
      </Card>

      {!acknowledged && (
        <Card className="p-6 mt-4 no-print print:hidden">
          <h2 className="text-[15px] font-bold text-slate-900">
            Acknowledge this appointment
          </h2>
          <p className="text-[13px] text-slate-500 mt-1">
            Typing your name below confirms that you have read and accepted the terms of
            this appointment letter
            {documents.length > 0 ? ', and each of the documents ticked below.' : '.'}
          </p>

          {/* §7.5 Stage 7 — NDA, Code of Conduct and the required policies. Each is
              ticked separately so the record says which documents the signature below
              actually covers, rather than one tick standing for all of them. */}
          {documents.length > 0 && (
            <div className="mt-5 space-y-2">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
                Employment documents
              </p>
              {documents.map((d) => {
                const already = !!d.acknowledged_at;
                return (
                  <label key={d.doc}
                    className={`flex items-start gap-2.5 p-3 rounded-lg border cursor-pointer ${
                      already || agreed.has(d.doc)
                        ? 'border-emerald-200 bg-emerald-50/60'
                        : 'border-slate-200 hover:border-slate-300'}`}>
                    <input type="checkbox" className="mt-0.5"
                      checked={already || agreed.has(d.doc)}
                      disabled={already}
                      onChange={() => toggleDoc(d.doc)} />
                    <span className="text-[13px] text-slate-800">
                      I have read and accept the <strong>{d.doc}</strong>
                      {d.required
                        ? <span className="ml-1.5 text-[10.5px] font-bold text-rose-600">REQUIRED</span>
                        : <span className="ml-1.5 text-[10.5px] font-semibold text-slate-400">OPTIONAL</span>}
                      {already && (
                        <span className="block text-[11.5px] text-emerald-700">
                          Already accepted
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          <label className="block text-[11px] font-bold uppercase tracking-widest text-slate-500 mt-5 mb-1.5">
            Your full name
          </label>
          <input
            className="w-full h-10 px-3 rounded-lg border border-slate-300 text-[14px] text-slate-900"
            placeholder="Type your full name"
            value={signature}
            onChange={(e) => setSignature(e.target.value)}
          />

          <label className="block text-[11px] font-bold uppercase tracking-widest text-slate-500 mt-4 mb-1.5">
            Anything you would like to add (optional)
          </label>
          <textarea
            className="w-full h-24 px-3 py-2 rounded-lg border border-slate-300 text-[14px] text-slate-900"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />

          {error && (
            <p className="text-[13px] font-semibold text-rose-600 mt-3">{error}</p>
          )}

          <button
            type="button"
            onClick={acknowledge}
            disabled={busy || outstanding.length > 0 || !signature.trim()}
            className="mt-5 h-10 px-5 rounded-lg bg-slate-900 text-white text-[14px] font-bold flex items-center gap-2 disabled:opacity-50"
          >
            <Check size={15} />
            {busy ? 'Recording…' : 'Acknowledge appointment'}
          </button>

          <p className="text-[12px] text-slate-400 mt-4">
            If any of the details above are not what you expected, please contact the HR
            team before acknowledging.
          </p>
        </Card>
      )}
    </Shell>
  );
};

export default AppointmentPage;
