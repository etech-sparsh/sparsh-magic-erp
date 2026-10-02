import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  UserCheck, PartyPopper, XCircle, Loader2, Upload, X, Plus, Trash2,
  CheckCircle2, Circle,
} from 'lucide-react';
import {
  getPublicOnboarding, submitOnboarding, readFileAsUpload,
} from '../../../services/hrmsPublicApi';

/**
 * HRMS ▸ PUBLIC pre-onboarding form.
 *
 * Mounted OUTSIDE PrivateRoute. A new hire is not yet a user of this ERP and must never see
 * its navigation.
 *
 * The one rule worth stating: **PAN or Aadhaar is required, and the server enforces it.**
 * The check below is a courtesy that saves a round trip — it is not the guard. The source
 * HRMS checked this in the browser only (BACKEND_ANALYSIS §8), so any request that skipped
 * the form put an employee into payroll with no identity document at all.
 *
 * Submitting is once-only: HR verifies these details by hand, and letting them change
 * afterwards would silently invalidate that verification. Revisiting shows a calm done
 * screen rather than an error — someone re-checking their own link has done nothing wrong.
 */

const MAX_MB = 15;

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

const FIELD = 'w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-[13.5px] text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500';
const LABEL = 'block text-[12px] font-semibold text-slate-700 mb-1.5';

const Field = ({ id, label, hint, children }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    {children}
    {hint && <p className="text-[11.5px] text-slate-500 mt-1">{hint}</p>}
  </div>
);

/** One numbered step of the joining form. The numbers are the point: §7.5 gives these
 *  sections an order, and a new hire filling in bank details wants to know how much is
 *  left rather than meeting one undifferentiated wall of inputs. */
const Section = ({ n, title, note, children }) => (
  <section className="space-y-3">
    <div className="flex items-center gap-2.5">
      <span className="h-6 w-6 shrink-0 rounded-full bg-indigo-600 text-white grid place-items-center text-[11px] font-bold">
        {n}
      </span>
      <h2 className="text-[13.5px] font-bold text-slate-900">{title}</h2>
    </div>
    {note && <p className="text-[12px] text-slate-500 pl-[34px]">{note}</p>}
    <div className="pl-0 sm:pl-[34px] space-y-3">{children}</div>
  </section>
);


const OnboardPage = () => {
  const { code } = useParams();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const [form, setForm] = useState({
    pan: '', aadhaar: '', passport: '', driving_license: '',
    date_of_birth: '', gender: '',
    address: '', permanent_address: '', personal_email: '', personal_phone: '',
    bank_name: '', bank_branch: '', bank_account_name: '', bank_account: '', bank_ifsc: '',
    uan: '', pf_number: '', esic_number: '', previous_employer: '',
    emergency_contact_name: '', emergency_contact_phone: '', emergency_contact_relation: '',
    asset_requirements: '',
  });
  const [references, setReferences] = useState([]);
  // One file per named joining document (§7.5), keyed by doc_type, plus anything extra the
  // new hire wants to send. Keyed rather than a flat list so "which task is still open" is
  // answerable without matching on filenames.
  const [taskFiles, setTaskFiles] = useState({});
  const [files, setFiles] = useState([]);

  const tasks = data?.document_tasks || [];
  const outstanding = tasks.filter((t) => t.required && !t.uploaded && !taskFiles[t.doc_type]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    document.title = 'Joining details';
    getPublicOnboarding(code)
      .then(({ data: d }) => {
        setData(d);
        if (d?.already_submitted) setDone(true);
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const pickFiles = (e) => {
    const chosen = Array.from(e.target.files || []);
    const max = data?.max_documents || 15;
    if (files.length + chosen.length > max) {
      setError(`You can attach at most ${max} documents.`);
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

  const pickTaskFile = (docType) => (e) => {
    const chosen = (e.target.files || [])[0];
    e.target.value = '';
    if (!chosen) return;
    if (chosen.size > MAX_MB * 1024 * 1024) {
      setError(`"${chosen.name}" is too large. The limit is ${MAX_MB} MB per file.`);
      return;
    }
    setError('');
    setTaskFiles((c) => ({ ...c, [docType]: chosen }));
  };

  const dropTaskFile = (docType) => setTaskFiles((c) => {
    const next = { ...c };
    delete next[docType];
    return next;
  });

  const addReference = () => {
    const max = data?.max_references || 5;
    if (references.length >= max) {
      setError(`You can add at most ${max} references.`);
      return;
    }
    setReferences((r) => [...r, { name: '', relation: '', phone: '' }]);
  };

  const setReference = (i, key) => (e) => setReferences((rows) =>
    rows.map((r, idx) => (idx === i ? { ...r, [key]: e.target.value } : r)));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    // Courtesy check only — the server enforces this regardless of what the browser did.
    if (!form.pan.trim() && !form.aadhaar.trim()) {
      setError('Provide your PAN or your Aadhaar number — at least one is required.');
      return;
    }
    if (outstanding.length) {
      setError(`Still needed: ${outstanding.map((t) => t.doc_type).join(', ')}.`);
      return;
    }
    setSubmitting(true);
    try {
      // Typed uploads carry their doc_type so the server can answer "which joining
      // document is missing"; anything extra goes up untyped.
      const typed = await Promise.all(
        Object.entries(taskFiles).map(async ([docType, file]) => ({
          ...(await readFileAsUpload(file)), doc_type: docType,
        })));
      const extra = files.length ? await Promise.all(files.map(readFileAsUpload)) : [];
      const payload = {
        ...form,
        gender: form.gender || null,
        references: references.filter((r) => r.name.trim()),
        documents: [...typed, ...extra],
      };
      await submitOnboarding(code, payload);
      setDone(true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Your details could not be submitted.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <Card className="py-16 flex flex-col items-center gap-3">
          <Loader2 size={22} className="animate-spin text-indigo-600" />
          <p className="text-[13px] text-slate-500">Loading your form…</p>
        </Card>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="py-16 px-6 flex flex-col items-center gap-3 text-center">
          <XCircle size={26} className="text-slate-400" />
          <p className="text-[15px] font-bold text-slate-900">Link unavailable</p>
          <p className="text-[13px] text-slate-500 max-w-sm">{loadError}</p>
        </Card>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <Card className="py-16 px-6 flex flex-col items-center gap-3 text-center">
          <PartyPopper size={28} className="text-indigo-600" />
          <p className="text-[16px] font-bold text-slate-900">Thank you</p>
          <p className="text-[13.5px] text-slate-600 max-w-md">
            Your details have been received. The HR team will verify them and be in touch
            before your joining date.
          </p>
          {data?.joining_date && (
            <p className="text-[12.5px] text-slate-500">
              Joining on {new Date(data.joining_date).toLocaleDateString('en-IN', {
                day: '2-digit', month: 'long', year: 'numeric',
              })}
            </p>
          )}
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card className="overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-200 flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-indigo-50 text-indigo-600 grid place-items-center shrink-0">
            <UserCheck size={19} />
          </div>
          <div>
            <h1 className="text-[17px] font-bold text-slate-900">
              Welcome{data?.candidate_name ? `, ${data.candidate_name}` : ''}
            </h1>
            <p className="text-[12.5px] text-slate-500 mt-0.5">
              {data?.designation ? `${data.designation} · ` : ''}
              Please complete your joining details.
            </p>
          </div>
        </div>

        {tasks.length > 0 && (
          <div className="px-6 py-3 bg-slate-50 border-b border-slate-200 flex items-center gap-2 flex-wrap">
            <span className="text-[11.5px] font-semibold text-slate-600">
              Documents to upload:
            </span>
            {tasks.map((t) => {
              const complete = t.uploaded || !!taskFiles[t.doc_type];
              return (
                <span key={t.doc_type}
                  className={'px-2 py-0.5 rounded-md text-[11px] font-semibold '
                    + (complete
                      ? 'bg-emerald-100 text-emerald-700'
                      : t.required ? 'bg-rose-50 text-rose-600' : 'bg-white text-slate-500 border border-slate-200')}>
                  {t.doc_type}
                </span>
              );
            })}
          </div>
        )}

        <form onSubmit={submit} className="p-6 space-y-7">
          <Section n="1" title="Personal information">
            <p className="text-[12px] text-slate-500">
              Provide your PAN or your Aadhaar number &mdash; at least one is required.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field id="pan" label="PAN" hint="e.g. ABCDE1234F">
                <input id="pan" className={FIELD} value={form.pan} onChange={set('pan')}
                  autoComplete="off" />
              </Field>
              <Field id="aadhaar" label="Aadhaar" hint="12 digits">
                <input id="aadhaar" className={FIELD} value={form.aadhaar}
                  onChange={set('aadhaar')} inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="dob" label="Date of birth">
                <input id="dob" type="date" className={FIELD} value={form.date_of_birth}
                  onChange={set('date_of_birth')} />
              </Field>
              <Field id="gender" label="Gender">
                <select id="gender" className={FIELD} value={form.gender}
                  onChange={set('gender')}>
                  <option value="">Prefer not to say</option>
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                  <option value="Other">Other</option>
                </select>
              </Field>
              <Field id="passport" label="Passport number (optional)">
                <input id="passport" className={FIELD} value={form.passport}
                  onChange={set('passport')} />
              </Field>
              <Field id="dl" label="Driving licence (optional)">
                <input id="dl" className={FIELD} value={form.driving_license}
                  onChange={set('driving_license')} />
              </Field>
            </div>
          </Section>

          <Section n="2" title="Contact information">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field id="p-email" label="Personal email">
                <input id="p-email" type="email" className={FIELD} value={form.personal_email}
                  onChange={set('personal_email')} autoComplete="off" />
              </Field>
              <Field id="p-phone" label="Mobile number">
                <input id="p-phone" className={FIELD} value={form.personal_phone}
                  onChange={set('personal_phone')} inputMode="tel" />
              </Field>
            </div>
            <Field id="address" label="Current address">
              <textarea id="address" rows={3} value={form.address} onChange={set('address')}
                className={FIELD + ' h-auto py-2 resize-y'} />
            </Field>
            <Field id="perm-address" label="Permanent address"
              hint="Leave blank if it is the same as your current address.">
              <textarea id="perm-address" rows={3} value={form.permanent_address}
                onChange={set('permanent_address')}
                className={FIELD + ' h-auto py-2 resize-y'} />
            </Field>

            <p className="text-[12px] font-semibold text-slate-700 pt-1">Emergency contact</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Field id="ec-name" label="Name">
                <input id="ec-name" className={FIELD} value={form.emergency_contact_name}
                  onChange={set('emergency_contact_name')} />
              </Field>
              <Field id="ec-phone" label="Phone">
                <input id="ec-phone" className={FIELD} value={form.emergency_contact_phone}
                  onChange={set('emergency_contact_phone')} inputMode="tel" />
              </Field>
              <Field id="ec-rel" label="Relationship">
                <input id="ec-rel" className={FIELD} value={form.emergency_contact_relation}
                  onChange={set('emergency_contact_relation')} />
              </Field>
            </div>

            <div className="flex items-center justify-between pt-1">
              <p className="text-[12px] font-semibold text-slate-700">References (optional)</p>
              <button type="button" onClick={addReference}
                className="h-8 px-3 rounded-lg border border-slate-300 text-[12px] font-semibold text-slate-600 hover:bg-slate-50 flex items-center gap-1.5">
                <Plus size={13} /> Add
              </button>
            </div>
            {references.map((r, i) => (
              // Index key: rows are only appended and removed by position, and there
              // is no stable id until the server has them.
              <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-2">
                <input className={FIELD} placeholder="Name" value={r.name}
                  onChange={setReference(i, 'name')} aria-label={'Reference ' + (i + 1) + ' name'} />
                <input className={FIELD} placeholder="Relationship" value={r.relation}
                  onChange={setReference(i, 'relation')}
                  aria-label={'Reference ' + (i + 1) + ' relationship'} />
                <input className={FIELD} placeholder="Phone" value={r.phone}
                  onChange={setReference(i, 'phone')}
                  aria-label={'Reference ' + (i + 1) + ' phone'} />
                <button type="button"
                  onClick={() => setReferences((rows) => rows.filter((_, idx) => idx !== i))}
                  className="h-10 w-10 grid place-items-center rounded-lg border border-slate-300 text-slate-400 hover:text-rose-600"
                  aria-label={'Remove reference ' + (i + 1)}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </Section>

          <Section n="3" title="Bank information"
            note="Your salary is paid into this account, so please check it against your passbook or a cheque.">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field id="bank" label="Bank name">
                <input id="bank" className={FIELD} value={form.bank_name}
                  onChange={set('bank_name')} />
              </Field>
              <Field id="branch" label="Branch">
                <input id="branch" className={FIELD} value={form.bank_branch}
                  onChange={set('bank_branch')} />
              </Field>
              <Field id="acct-name" label="Account holder name">
                <input id="acct-name" className={FIELD} value={form.bank_account_name}
                  onChange={set('bank_account_name')} />
              </Field>
              <Field id="acct" label="Account number">
                <input id="acct" className={FIELD} value={form.bank_account}
                  onChange={set('bank_account')} inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="ifsc" label="IFSC" hint="e.g. HDFC0001234">
                <input id="ifsc" className={FIELD} value={form.bank_ifsc}
                  onChange={set('bank_ifsc')} autoComplete="off" />
              </Field>
            </div>
          </Section>

          <Section n="4" title="Statutory information"
            note="Leave any of these blank if you do not have one — this is your first job, or your previous employer did not enrol you.">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field id="uan" label="UAN" hint="12 digits, from your PF passbook">
                <input id="uan" className={FIELD} value={form.uan} onChange={set('uan')}
                  inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="pf" label="PF account number">
                <input id="pf" className={FIELD} value={form.pf_number}
                  onChange={set('pf_number')} autoComplete="off" />
              </Field>
              <Field id="esic" label="ESIC number" hint="17 digits">
                <input id="esic" className={FIELD} value={form.esic_number}
                  onChange={set('esic_number')} inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="prev-emp" label="Previous employer">
                <input id="prev-emp" className={FIELD} value={form.previous_employer}
                  onChange={set('previous_employer')} />
              </Field>
            </div>
          </Section>

          <Section n="5" title="Document upload"
            note={'PDF, Word or images, up to ' + MAX_MB + ' MB each.'}>
            <ul className="space-y-2">
              {tasks.map((t) => {
                const chosen = taskFiles[t.doc_type];
                const complete = t.uploaded || !!chosen;
                return (
                  <li key={t.doc_type}
                    className={'flex items-center gap-3 p-3 rounded-lg border '
                      + (complete ? 'border-emerald-200 bg-emerald-50/60' : 'border-slate-200')}>
                    {complete
                      ? <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
                      : <Circle size={16} className="text-slate-300 shrink-0" />}
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold text-slate-800">
                        {t.doc_type}
                        {t.required
                          ? <span className="ml-1.5 text-[10.5px] font-bold text-rose-600">REQUIRED</span>
                          : <span className="ml-1.5 text-[10.5px] font-semibold text-slate-400">OPTIONAL</span>}
                      </p>
                      {chosen && (
                        <p className="text-[11.5px] text-slate-500 truncate">{chosen.name}</p>
                      )}
                      {t.uploaded && !chosen && (
                        <p className="text-[11.5px] text-emerald-700">Already received</p>
                      )}
                    </div>
                    {!t.uploaded && (
                      <label className="h-8 px-3 shrink-0 rounded-lg border border-slate-300 text-[12px] font-semibold text-slate-600 hover:bg-white hover:border-indigo-400 hover:text-indigo-600 cursor-pointer flex items-center gap-1.5">
                        <Upload size={13} /> {chosen ? 'Replace' : 'Upload'}
                        <input type="file" className="hidden" onChange={pickTaskFile(t.doc_type)}
                          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" />
                      </label>
                    )}
                    {chosen && (
                      <button type="button" onClick={() => dropTaskFile(t.doc_type)}
                        className="p-1 shrink-0 rounded text-slate-400 hover:text-rose-600"
                        aria-label={'Remove ' + t.doc_type}>
                        <X size={14} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>

            <p className="text-[12px] font-semibold text-slate-700 pt-1">
              Anything else (optional)
            </p>
            <label className="flex items-center justify-center gap-2 h-16 rounded-lg border-2 border-dashed border-slate-300 text-[13px] text-slate-500 cursor-pointer hover:border-indigo-400 hover:text-indigo-600">
              <Upload size={16} /> Choose files
              <input type="file" multiple className="hidden" onChange={pickFiles}
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" />
            </label>
            {files.length > 0 && (
              <ul className="space-y-1.5">
                {files.map((f, i) => (
                  <li key={f.name + '-' + f.size + '-' + i}
                    className="flex items-center gap-2 text-[12.5px] text-slate-700">
                    <span className="truncate flex-1">{f.name}</span>
                    <button type="button"
                      onClick={() => setFiles((c) => c.filter((_, idx) => idx !== i))}
                      className="p-1 rounded text-slate-400 hover:text-rose-600"
                      aria-label={'Remove ' + f.name}>
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Field id="assets" label="Anything you need on day one? (optional)"
            hint="e.g. a laptop with more memory, a left-handed mouse, dietary needs for induction">
            <textarea id="assets" rows={2} value={form.asset_requirements}
              onChange={set('asset_requirements')}
              className={`${FIELD} h-auto py-2 resize-y`} />
          </Field>

          {error && (
            <p className="text-[12.5px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button type="submit" disabled={submitting}
            className="w-full h-11 rounded-lg bg-indigo-600 text-white text-[14px] font-bold hover:bg-indigo-700 disabled:opacity-60 transition-colors">
            {submitting ? 'Submitting…' : 'Submit my details'}
          </button>
          <p className="text-[11.5px] text-slate-500 text-center">
            You can submit this form once. Contact the HR team if something needs to change
            afterwards.
          </p>
        </form>
      </Card>
    </Shell>
  );
};

export default OnboardPage;
