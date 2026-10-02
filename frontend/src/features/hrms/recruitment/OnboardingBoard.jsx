import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  UserPlus, Plus, X, Copy, Check, ShieldCheck, ShieldAlert, BadgeCheck, Search,
  Paperclip, CalendarDays, Link2, FileCheck2, FileX2, FileClock, FileWarning,
  LogIn, Briefcase,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getOnboardings, getOnboardableCandidates, getOnboarding, startOnboarding,
  updateOnboarding, updateOnboardingBg, verifyOnboardingDocuments,
  setOnboardingChecklist, generateEmployeeId, onboardUrlFor,
  reviewOnboardingDocument, confirmOnboardingJoining,
  getDepartments, getDesignations, getEmployees,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ onboarding — where a candidate becomes an employee.
 *
 * Two things this screen is careful about:
 *
 *  • **The three system-owned checklist items** (`employee_id`, `documents_verified`,
 *    `bg_cleared`) are rendered as read-only with an explanation. The API refuses to set
 *    them by hand; showing a checkbox that always 409s would be a lie.
 *  • **Generate Employee ID says WHY it is disabled.** The server returns `id_blockers` as
 *    prose, so the button never sits greyed out with no explanation — the single most
 *    common source of "the system is broken" tickets.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const BTN = 'h-9 px-3.5 rounded-lg text-[12.5px] font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

const STATUS_TONE = {
  'Pre-Onboarding': 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Onboarding: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Completed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
};

const BG_TONE = {
  Pending: 'text-[var(--text-muted)]',
  'In Progress': 'text-[var(--accent-indigo)]',
  Cleared: 'text-[var(--accent-green,var(--accent-indigo))]',
  Flagged: 'text-[var(--accent-red)]',
};

const SYSTEM_ITEMS = new Set(['employee_id', 'documents_verified', 'bg_cleared']);

/** Completeness reads as a traffic light: green only at 100, because 90% complete still
 *  means somebody cannot be activated. */
const pctTone = (pct) => (pct >= 100 ? 'bg-[var(--accent-green)]'
  : pct >= 60 ? 'bg-[var(--accent-indigo)]'
  : 'bg-[var(--accent-orange)]');

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString('en-IN', {
  day: '2-digit', month: 'short', year: 'numeric',
}) : '—');

// ── Start modal ───────────────────────────────────────────────
const StartModal = ({ onClose, onStarted }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ uk: '', joining_date: '' });

  useEffect(() => {
    getOnboardableCandidates(scope)
      .then(({ data }) => setPeople(Array.isArray(data) ? data : data?.candidates || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load candidates.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (!form.uk) return showError('Select a candidate.');
    setSaving(true);
    try {
      const { data } = await startOnboarding(form, scope);
      showSuccess(`Onboarding ${data.onb_no} opened`);
      onStarted(data.onb_no);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not start onboarding.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Start onboarding</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className={LABEL} htmlFor="ob-uk">New hire *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Nobody is ready to onboard. A candidate becomes onboardable once they have{' '}
                <strong>accepted their offer</strong> — we ask for PAN, Aadhaar and bank
                details, so we do not collect them from someone who may still say no.
              </p>
            ) : (
              <select id="ob-uk" value={form.uk} className={FIELD}
                onChange={(e) => setForm((f) => ({ ...f, uk: e.target.value }))}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>{p.candidate_name}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className={LABEL} htmlFor="ob-join">Joining date</label>
            <input id="ob-join" type="date" className={FIELD} value={form.joining_date}
              onChange={(e) => setForm((f) => ({ ...f, joining_date: e.target.value }))} />
            <p className="text-[11.5px] text-[var(--text-muted)] mt-1">
              Leave blank to use the date from the accepted offer.
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className={`${BTN} border border-[var(--border)] text-[var(--text-muted)]`}>
            Cancel
          </button>
          <button type="button" onClick={submit} disabled={saving || people.length === 0}
            className={`${BTN} bg-[var(--accent-indigo)] text-white`}>
            {saving ? 'Starting…' : 'Start onboarding'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Detail panel ──────────────────────────────────────────────
/** How each document verdict reads (§7.5 Stage 3). Exception is amber rather than green:
 *  it lets the joining proceed, but it is a decision somebody signed, not a clean pass. */
const DOC_TONE = {
  Verified:  { icon: FileCheck2,   cls: 'text-[var(--accent-green)]',  bg: 'bg-[var(--accent-green-bg)]' },
  Rejected:  { icon: FileX2,       cls: 'text-[var(--accent-red)]',    bg: 'bg-[var(--accent-red-bg)]' },
  Exception: { icon: FileWarning,  cls: 'text-[var(--accent-orange)]', bg: 'bg-[var(--accent-orange-bg)]' },
  Pending:   { icon: FileClock,    cls: 'text-[var(--text-muted)]',    bg: 'bg-[var(--input-bg)]' },
};

const Detail = ({ onbNo, onClose, onChanged }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [row, setRow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const mayWrite = can(CAP.ONBOARDING_WRITE);
  const mayGenerate = can(CAP.ONBOARDING_GENERATE_ID);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getOnboarding(onbNo, scope);
      setRow(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this onboarding.');
    } finally {
      setLoading(false);
    }
  }, [onbNo, scope]);

  useEffect(() => { load(); }, [load]);

  const run = async (fn, okMessage) => {
    setBusy(true);
    try {
      const { data } = await fn();
      setRow(data);
      if (okMessage) showSuccess(okMessage);
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  // The doc_type currently being given a Rejected/Exception verdict, and the note that
  // must come with it. Verified needs no note, so it does not open this.
  const [reviewing, setReviewing] = useState(null);   // {doc_type, status}
  const [reviewNote, setReviewNote] = useState('');

  const reviewDoc = (docType, status, note) => run(
    () => reviewOnboardingDocument(onbNo, { doc_type: docType, status, note }, scope),
    `${docType} marked ${status.toLowerCase()}.`);

  const submitReview = async () => {
    if (!reviewNote.trim()) return;
    await reviewDoc(reviewing.doc_type, reviewing.status, reviewNote.trim());
    setReviewing(null);
    setReviewNote('');
  };

  // ── §7.5 Stage 6 -- joining day ──
  // Department, designation and reporting manager reference real records; grade, location,
  // unit and payroll group are free text because this codebase has no master for any of
  // them yet (confirmed against the org-structure module before choosing this shape).
  const [depts, setDepts] = useState([]);
  const [desigs, setDesigs] = useState([]);
  const [managers, setManagers] = useState([]);
  const [joinForm, setJoinForm] = useState(null);   // null until "Confirm joining" is opened

  useEffect(() => {
    if (!joinForm) return;
    getDepartments(scope).then(({ data }) => setDepts(data?.departments || data || []))
      .catch(() => {});
    getDesignations(scope).then(({ data }) => setDesigs(data?.designations || data || []))
      .catch(() => {});
    getEmployees({ ...scope, limit: 500 }).then(({ data }) => setManagers(data?.employees || data || []))
      .catch(() => {});
  }, [joinForm, scope]);

  const openJoinForm = () => setJoinForm({
    actual_doj: new Date().toISOString().slice(0, 10),
    note: '', unit: '', department_id: row.department_id || '',
    designation_id: row.designation_id || '', grade: '', work_location: '',
    reporting_manager_id: row.reporting_manager_id || '',
    employment_type: 'Full-time', employment_status: 'Active', payroll_group: '',
  });

  const submitJoinForm = async () => {
    if (!joinForm.actual_doj) return;
    const payload = { ...joinForm };
    // Blank optional fields are omitted rather than sent as "" -- the server treats an
    // absent field as "leave whatever is already on the case", and an empty string would
    // instead overwrite it with nothing.
    Object.keys(payload).forEach((k) => { if (payload[k] === '') delete payload[k]; });
    await run(() => confirmOnboardingJoining(onbNo, payload, scope), 'Joining confirmed');
    setJoinForm(null);
  };

  const copyLink = () => {
    navigator.clipboard?.writeText(onboardUrlFor(row.access_code));
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const blockers = row?.id_blockers || [];
  // §7.5 Stage 4: when a verification file exists it owns `bg_verification`, so the manual
  // dropdown stands down rather than offering an edit the server would refuse.
  // §7.5 Stage 8 — checklist grouped by owner, in the order responsibility flows:
  // HR opens the case, IT and Admin prepare, the manager inducts.
  const OWNER_ORDER = ['HR', 'IT', 'Admin', 'Reporting Manager'];
  const groupedTasks = useMemo(() => {
    const groups = new Map();
    for (const item of row?.checklist || []) {
      const owner = item.owner || 'HR';
      if (!groups.has(owner)) groups.set(owner, []);
      groups.get(owner).push(item);
    }
    return [...groups.entries()].sort(
      (a, b) => OWNER_ORDER.indexOf(a[0]) - OWNER_ORDER.indexOf(b[0]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row?.checklist]);

  const comp = row?.completeness;
  const vf = row?.verification || {};
  const hasFile = (vf.checks || []).length > 0;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-full bg-[var(--bg-card)] border-l border-[var(--border)] shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] shrink-0">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {row?.candidate_name || onbNo}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {onbNo}{row?.designation ? ` · ${row.designation}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {loading && <HrmsLoading label="Loading onboarding…" />}
          {error && !loading && <HrmsError message={error} onRetry={load} />}

          {row && !loading && (
            <>
              {/* Employee ID — the headline once issued */}
              {row.employee_id && (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-center gap-3">
                  <BadgeCheck size={20} className="text-[var(--accent-indigo)] shrink-0" />
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">
                      Employee ID {row.employee_id}
                    </p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      They now appear in the employee directory. Link a login account from
                      there once it exists.
                    </p>
                  </div>
                </div>
              )}

              {/* The pre-onboarding link */}
              <section className="space-y-2">
                <p className={LABEL}>Pre-onboarding form</p>
                <div className="flex items-center gap-2">
                  <input readOnly value={row.access_code ? onboardUrlFor(row.access_code) : ''}
                    className={`${FIELD} font-mono text-[11.5px]`} />
                  <button type="button" onClick={copyLink}
                    className={`${BTN} border border-[var(--border)] text-[var(--text-muted)] shrink-0 flex items-center gap-1.5`}>
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Status: <strong>{row.pre_status}</strong>
                  {row.submitted_at ? ` · submitted ${fmtDate(row.submitted_at)}` : ''}
                </p>
                {row.pre_status === 'Submitted' && mayWrite && (
                  <button type="button" disabled={busy}
                    onClick={() => run(() => verifyOnboardingDocuments(onbNo, scope),
                      'Documents verified')}
                    className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
                    <ShieldCheck size={14} /> Mark documents verified
                  </button>
                )}
              </section>

              {/* Joining details. A viewer who lacks ONBOARDING_WRITE sees the same facts as
                  plain text rather than a greyed-out input/select they might mistake for an
                  interactive control that simply isn't responding. */}
              <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="d-join">Joining date</label>
                  {mayWrite ? (
                    <input id="d-join" type="date" className={FIELD} disabled={busy}
                      value={row.joining_date || ''}
                      onChange={(e) => run(
                        () => updateOnboarding(onbNo, { joining_date: e.target.value }, scope))} />
                  ) : (
                    <p className="h-9 flex items-center text-[13px] text-[var(--text-main)]">
                      {fmtDate(row.joining_date)}
                    </p>
                  )}
                </div>
                <div>
                  <label className={LABEL} htmlFor="d-bg">Background verification</label>
                  {mayWrite && !hasFile ? (
                    <select id="d-bg" className={FIELD} disabled={busy}
                      value={row.bg_verification || 'Pending'}
                      onChange={(e) => run(
                        () => updateOnboardingBg(onbNo, { bg_verification: e.target.value }, scope),
                        'Background check updated')}>
                      {['Pending', 'In Progress', 'Cleared', 'Flagged'].map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  ) : (
                    <p className={`h-9 flex items-center text-[13px] font-semibold ${
                      BG_TONE[row.bg_verification] || 'text-[var(--text-main)]'}`}>
                      {row.bg_verification || 'Pending'}
                    </p>
                  )}
                  {hasFile && (
                    <p className="text-[11px] text-[var(--text-muted)] mt-1">
                      Follows the verification file below.
                    </p>
                  )}
                  {row.bg_verification === 'Flagged' && (
                    <p className="text-[11.5px] text-[var(--accent-red)] mt-1 flex items-center gap-1">
                      <ShieldAlert size={12} /> An Employee ID cannot be issued while flagged.
                    </p>
                  )}
                </div>
              </section>

              {/* Verification file (§7.5 Stage 4) — shown ON the case, because BGV and
                  reference checks are part of onboarding rather than a separate process
                  somebody has to go and remember about. Read-only here: the result is
                  recorded where the check is, and this case follows it. */}
              <section>
                <p className={LABEL}>Verification file</p>
                {!hasFile && !vf.reference ? (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    No background or reference check has been recorded for this joiner.
                    Where your policy requires one, raise it on the Verification screen —
                    the result appears here automatically.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {(vf.checks || []).map((c) => (
                      <div key={c.bgv_no}
                        className="flex items-center gap-2.5 p-2.5 rounded-lg border border-[var(--border)]">
                        <ShieldCheck size={14} className="shrink-0 text-[var(--text-muted)]" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[12.5px] font-semibold text-[var(--text-main)] truncate">
                            {c.check_type}
                          </p>
                          {c.remarks && (
                            <p className="text-[11px] text-[var(--text-muted)] truncate">
                              {c.remarks}
                            </p>
                          )}
                        </div>
                        <span className={`text-[11px] font-bold shrink-0 ${
                          c.status === 'Flagged' ? 'text-[var(--accent-red)]'
                            : c.status === 'Cleared' ? 'text-[var(--accent-green)]'
                            : 'text-[var(--text-muted)]'}`}>
                          {c.status}
                        </span>
                      </div>
                    ))}

                    {(vf.outstanding || []).length > 0 && (
                      <p className="text-[11.5px] text-[var(--accent-orange)]">
                        Still outstanding: {vf.outstanding.join(', ')}.
                      </p>
                    )}

                    {vf.approval?.status && vf.approval.status !== 'Not Requested' && (
                      <p className="text-[11.5px] text-[var(--text-muted)]">
                        HR sign-off: <strong className="text-[var(--text-main)]">
                          {vf.approval.status}
                        </strong>
                        {vf.approval.signed_by ? ` · ${vf.approval.signed_by}` : ''}
                      </p>
                    )}

                    {vf.reference && (
                      <div className="flex items-center gap-2.5 p-2.5 rounded-lg border border-[var(--border)]">
                        <BadgeCheck size={14} className="shrink-0 text-[var(--accent-green)]" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                            Reference check
                          </p>
                          <p className="text-[11px] text-[var(--text-muted)] truncate">
                            {vf.reference.referee_name || vf.reference.ref_no}
                          </p>
                        </div>
                        <span className="text-[11px] font-bold text-[var(--accent-green)] shrink-0">
                          {vf.reference.outcome}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </section>

              {/* Joining documents (§7.5 Stage 3) — one row per document the company
                  asks for, carrying the current version's verdict and the controls to
                  change it. Chips alone could show state but not act on it. */}
              {(row.document_tasks || []).length > 0 && (
                <section>
                  <p className={LABEL}>Joining documents</p>
                  <ul className="space-y-1.5">
                    {row.document_tasks.map((t) => {
                      const tone = DOC_TONE[t.status] || DOC_TONE.Pending;
                      const Icon = tone.icon;
                      return (
                        <li key={t.doc_type}
                          className="p-2.5 rounded-lg border border-[var(--border)]">
                          <div className="flex items-center gap-2.5">
                            <span className={`h-7 w-7 shrink-0 rounded-lg grid place-items-center ${tone.bg} ${tone.cls}`}>
                              <Icon size={14} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="text-[12.5px] font-semibold text-[var(--text-main)] truncate">
                                {t.doc_type}
                                {t.version > 1 && (
                                  <span className="ml-1.5 text-[10.5px] font-bold text-[var(--text-muted)]">
                                    v{t.version}
                                  </span>
                                )}
                                {!t.required && (
                                  <span className="ml-1.5 text-[10px] font-semibold text-[var(--text-muted)]">
                                    optional
                                  </span>
                                )}
                              </p>
                              <p className={`text-[11px] font-bold ${tone.cls}`}>
                                {t.uploaded ? t.status : 'Not received'}
                                {t.reviewed_by && (
                                  <span className="font-normal text-[var(--text-muted)]">
                                    {' '}· {t.reviewed_by}
                                  </span>
                                )}
                              </p>
                              {t.review_note && (
                                <p className="text-[11px] text-[var(--text-muted)]">
                                  {t.review_note}
                                </p>
                              )}
                            </div>
                            {mayWrite && t.uploaded && (
                              <div className="flex items-center gap-1 shrink-0">
                                <button type="button" disabled={busy}
                                  onClick={() => reviewDoc(t.doc_type, 'Verified')}
                                  title="The document is in order"
                                  className="h-7 px-2 rounded-lg border border-[var(--border)] text-[11px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-green)] hover:text-[var(--accent-green)] disabled:opacity-50">
                                  Verify
                                </button>
                                <button type="button" disabled={busy}
                                  onClick={() => { setReviewing({ doc_type: t.doc_type, status: 'Rejected' }); setReviewNote(''); }}
                                  title="Send it back to be replaced"
                                  className="h-7 px-2 rounded-lg border border-[var(--border)] text-[11px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-red)] hover:text-[var(--accent-red)] disabled:opacity-50">
                                  Reject
                                </button>
                                <button type="button" disabled={busy}
                                  onClick={() => { setReviewing({ doc_type: t.doc_type, status: 'Exception' }); setReviewNote(''); }}
                                  title="Allow joining to continue without it, on record"
                                  className="h-7 px-2 rounded-lg border border-[var(--border)] text-[11px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-orange)] hover:text-[var(--accent-orange)] disabled:opacity-50">
                                  Exception
                                </button>
                              </div>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}

              {/* Documents */}
              <section>
                <p className={LABEL}>Documents ({(row.documents || []).length})</p>
                {(row.documents || []).length === 0 ? (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    Nothing uploaded yet.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {row.documents.map((d, i) => (
                      <li key={`${d.name}-${i}`}
                        className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
                        <Paperclip size={13} className="text-[var(--text-muted)] shrink-0" />
                        <span className="truncate">{d.name}</span>
                        {d.doc_type && (
                          <span className="px-1.5 rounded bg-[var(--input-bg)] text-[10.5px] font-bold text-[var(--text-main)] shrink-0">
                            {d.doc_type}
                          </span>
                        )}
                        <span className="text-[11px] text-[var(--text-muted)] shrink-0">
                          {d.source === 'hr' ? 'added by HR' : 'from candidate'}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Onboarding completeness (§7.5 Stage 5) — the six groups, and exactly
                  what is still missing in each. The list matters more than the number:
                  it is what tells HR whom to chase before activation. */}
              {comp && (
                <section>
                  <div className="flex items-center justify-between mb-2">
                    <p className={`${LABEL} mb-0`}>Onboarding completeness</p>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">
                      {comp.percent}%
                    </p>
                  </div>
                  <div className="h-2 rounded-full bg-[var(--input-bg)] overflow-hidden mb-3">
                    <div className={`h-full transition-all ${pctTone(comp.percent)}`}
                      style={{ width: `${comp.percent}%` }} />
                  </div>
                  <ul className="space-y-1.5">
                    {(comp.groups || []).map((g) => (
                      <li key={g.key} className="text-[12px]">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-[var(--text-main)]">
                            {g.label}
                          </span>
                          <span className={g.done === g.total
                            ? 'text-[var(--accent-green)] font-bold'
                            : 'text-[var(--text-muted)] font-bold'}>
                            {g.done}/{g.total}
                          </span>
                        </div>
                        {g.missing.length > 0 && (
                          <p className="text-[11px] text-[var(--accent-orange)]">
                            Missing: {g.missing.join(', ')}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                  {comp.missing.length === 0 && (
                    <p className="mt-2 text-[11.5px] text-[var(--accent-green)]">
                      Nothing outstanding — every mandatory item is in.
                    </p>
                  )}
                </section>
              )}

              {/* Checklist */}
              <section>
                <div className="flex items-center justify-between mb-2">
                  <p className={`${LABEL} mb-0`}>Joining checklist</p>
                  <p className="text-[11.5px] font-bold text-[var(--text-muted)]">
                    {row.progress?.done ?? 0}/{row.progress?.total ?? 0}
                  </p>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden mb-3">
                  <div className="h-full bg-[var(--accent-indigo)] transition-all"
                    style={{ width: `${row.progress?.percent ?? 0}%` }} />
                </div>
                {!mayWrite && (
                  <p className="text-[11px] text-[var(--text-muted)] mb-2">
                    Read-only — you can see the checklist but not update it.
                  </p>
                )}
                {/* §7.5 Stage 8 — grouped by who actually owns the work. One flat list
                    made every item read as HR's job; IT creates the accounts, Admin
                    allocates the desk, and the manager runs the induction. */}
                {groupedTasks.map(([owner, items]) => (
                  <div key={owner} className="mb-3 last:mb-0">
                    <div className="flex items-center justify-between px-2 mb-1">
                      <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                        {owner}
                      </p>
                      <p className="text-[10.5px] font-bold text-[var(--text-muted)]">
                        {items.filter((i) => i.done).length}/{items.length}
                      </p>
                    </div>
                    <ul className="space-y-1">
                      {items.map((item) => {
                        const owned = SYSTEM_ITEMS.has(item.key);
                        return (
                          <li key={item.key}
                            className="flex items-start gap-2.5 py-1.5 px-2 rounded-lg hover:bg-[var(--input-bg)]">
                            <input type="checkbox" checked={!!item.done}
                              disabled={owned || !mayWrite || busy}
                              onChange={(e) => run(() => setOnboardingChecklist(
                                onbNo, { key: item.key, done: e.target.checked }, scope))}
                              className="mt-0.5 accent-[var(--accent-indigo)] disabled:opacity-60"
                              aria-label={item.label} />
                            <div className="min-w-0">
                              <p className={`text-[12.5px] ${item.done ? 'text-[var(--text-muted)] line-through' : 'text-[var(--text-main)]'}`}>
                                {item.label}
                              </p>
                              {owned && (
                                <p className="text-[11px] text-[var(--text-muted)]">
                                  Set automatically — it follows the action that achieves it.
                                </p>
                              )}
                              {!owned && !item.done && item.assigned_at && (
                                <p className="text-[11px] text-[var(--accent-indigo)]">
                                  Assigned {fmtDate(item.assigned_at)}
                                </p>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </section>

              {/* §7.5 Stage 6 -- "Candidate Reports -> HR Verifies Joining -> Confirm
                  Actual DOJ". Sits before the Employee ID section because it is the
                  precondition the server now enforces: an ID cannot be issued until
                  somebody has confirmed the joiner actually turned up. */}
              {!row.employee_id && (
                <section className="rounded-xl border border-[var(--border)] p-4 space-y-2">
                  <p className="text-[13px] font-bold text-[var(--text-main)] flex items-center gap-1.5">
                    <LogIn size={14} /> Joining day
                  </p>
                  {row.actual_doj ? (
                    <div className="text-[12.5px] text-[var(--text-main)] space-y-1">
                      <p>
                        Reported on <strong>{fmtDate(row.actual_doj)}</strong>
                        {row.joining_confirmed_by && (
                          <span className="text-[var(--text-muted)]"> · confirmed by {row.joining_confirmed_by}</span>
                        )}
                      </p>
                      {row.joining_note && (
                        <p className="text-[11.5px] text-[var(--text-muted)]">{row.joining_note}</p>
                      )}
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {[['Unit', row.unit], ['Grade', row.grade], ['Location', row.work_location],
                          ['Category', row.employment_type], ['Status', row.employment_status],
                          ['Payroll group', row.payroll_group]]
                          .filter(([, v]) => v)
                          .map(([label, v]) => (
                            <span key={label} className="px-2 py-0.5 rounded-md bg-[var(--input-bg)] text-[11px] font-semibold text-[var(--text-main)]">
                              {label}: {v}
                            </span>
                          ))}
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-[11.5px] text-[var(--text-muted)]">
                        Confirm the date they actually reported, and the role they are
                        joining into, before an Employee ID can be issued.
                      </p>
                      {mayWrite && (
                        <button type="button" onClick={openJoinForm}
                          className={`${BTN} border border-[var(--border)] text-[var(--text-main)] flex items-center gap-1.5`}>
                          <Briefcase size={14} /> Confirm joining
                        </button>
                      )}
                    </>
                  )}
                </section>
              )}

              {/* The handover. Blockers are server prose explaining exactly what is still
                  missing — the single most common source of "the system is broken" tickets
                  per this screen's own note above, so every viewer sees them, not only the
                  one holding ONBOARDING_GENERATE_ID. Only the button itself — the
                  irreversible act — is gated on that narrower capability. */}
              {!row.employee_id && (
                <section className="rounded-xl border border-[var(--border)] p-4 space-y-2">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">
                    Create the employee record
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    Issues the Employee ID and adds them to the directory. This cannot be
                    undone.
                  </p>
                  {blockers.length > 0 && (
                    <ul className="text-[11.5px] text-[var(--accent-red)] space-y-0.5">
                      {blockers.map((b) => <li key={b}>• {b}</li>)}
                    </ul>
                  )}
                  {mayGenerate ? (
                    <button type="button" disabled={busy || blockers.length > 0}
                      onClick={() => run(() => generateEmployeeId(onbNo, scope),
                        'Employee ID issued')}
                      className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
                      <BadgeCheck size={14} /> Generate Employee ID
                    </button>
                  ) : blockers.length === 0 ? (
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      Ready — this needs someone with permission to issue the Employee ID.
                    </p>
                  ) : null}
                </section>
              )}
            </>
          )}
        </div>
      </div>

      {/* §7.5 Stage 6 -- confirm the actual DOJ and the nine assignment attributes. */}
      {joinForm && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="w-full max-w-lg my-8 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <h3 className="text-[14.5px] font-bold text-[var(--text-main)]">Confirm joining</h3>
              <button type="button" onClick={() => setJoinForm(null)}
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                <X size={17} />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className={LABEL} htmlFor="jf-doj">Actual date of joining *</label>
                <input id="jf-doj" type="date" className={FIELD}
                  max={new Date().toISOString().slice(0, 10)}
                  value={joinForm.actual_doj}
                  onChange={(e) => setJoinForm((f) => ({ ...f, actual_doj: e.target.value }))} />
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  The day they actually reported — kept separate from the planned date, so a
                  late start does not overwrite what was agreed.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="jf-dept">Department</label>
                  <select id="jf-dept" className={FIELD} value={joinForm.department_id}
                    onChange={(e) => setJoinForm((f) => ({ ...f, department_id: e.target.value }))}>
                    <option value="">—</option>
                    {depts.map((d) => (
                      <option key={d._id || d.id} value={d._id || d.id}>{d.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-desig">Designation</label>
                  <select id="jf-desig" className={FIELD} value={joinForm.designation_id}
                    onChange={(e) => setJoinForm((f) => ({ ...f, designation_id: e.target.value }))}>
                    <option value="">—</option>
                    {desigs.map((d) => (
                      <option key={d._id || d.id} value={d._id || d.id}>{d.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-mgr">Reporting manager</label>
                  <select id="jf-mgr" className={FIELD} value={joinForm.reporting_manager_id}
                    onChange={(e) => setJoinForm((f) => ({ ...f, reporting_manager_id: e.target.value }))}>
                    <option value="">—</option>
                    {managers.map((m) => (
                      <option key={m.user_id || m._id} value={m.user_id || m._id}>
                        {m.full_name || m.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-unit">Company / Unit</label>
                  <input id="jf-unit" className={FIELD} value={joinForm.unit}
                    onChange={(e) => setJoinForm((f) => ({ ...f, unit: e.target.value }))} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-grade">Grade / Level</label>
                  <input id="jf-grade" className={FIELD} value={joinForm.grade}
                    onChange={(e) => setJoinForm((f) => ({ ...f, grade: e.target.value }))} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-loc">Location</label>
                  <input id="jf-loc" className={FIELD} value={joinForm.work_location}
                    onChange={(e) => setJoinForm((f) => ({ ...f, work_location: e.target.value }))} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-type">Employment category</label>
                  <select id="jf-type" className={FIELD} value={joinForm.employment_type}
                    onChange={(e) => setJoinForm((f) => ({ ...f, employment_type: e.target.value }))}>
                    {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'].map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="jf-status">Employment status</label>
                  <select id="jf-status" className={FIELD} value={joinForm.employment_status}
                    onChange={(e) => setJoinForm((f) => ({ ...f, employment_status: e.target.value }))}>
                    {['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave'].map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="jf-payroll">Payroll group</label>
                  <input id="jf-payroll" className={FIELD} value={joinForm.payroll_group}
                    onChange={(e) => setJoinForm((f) => ({ ...f, payroll_group: e.target.value }))} />
                </div>
              </div>

              <div>
                <label className={LABEL} htmlFor="jf-note">Note (optional)</label>
                <textarea id="jf-note" rows={2} value={joinForm.note}
                  onChange={(e) => setJoinForm((f) => ({ ...f, note: e.target.value }))}
                  className={`${FIELD} h-auto py-2 resize-y`} />
              </div>
            </div>
            <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
              <button type="button" onClick={() => setJoinForm(null)}
                className={`${BTN} border border-[var(--border)] text-[var(--text-muted)]`}>
                Cancel
              </button>
              <button type="button" onClick={submitJoinForm}
                disabled={busy || !joinForm.actual_doj}
                className={`${BTN} bg-[var(--accent-indigo)] text-white`}>
                Confirm joining
              </button>
            </div>
          </div>
        </div>
      )}

      {/* A rejection and an exception both have to say why: one tells the new hire what
          to fix, the other is the written basis for letting joining proceed without it. */}
      {reviewing && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl p-5 space-y-3">
            <h3 className="text-[14.5px] font-bold text-[var(--text-main)]">
              {reviewing.status === 'Rejected' ? 'Reject' : 'Allow an exception for'}
              {' '}{reviewing.doc_type}
            </h3>
            <p className="text-[12px] text-[var(--text-muted)]">
              {reviewing.status === 'Rejected'
                ? 'Tell the new hire what is wrong, so they can send a replacement.'
                : 'Record what was accepted and on whose authority. Joining can then go '
                  + 'ahead without this document, and this note is the reason why.'}
            </p>
            <textarea rows={3} value={reviewNote} autoFocus
              onChange={(e) => setReviewNote(e.target.value)}
              placeholder={reviewing.status === 'Rejected'
                ? 'e.g. The scan is cut off — the number is not readable.'
                : 'e.g. Degree certificate still with the university; undertaking signed, '
                  + 'to be produced within 60 days. Approved by the HR Head.'}
              className={`${FIELD} h-auto py-2 resize-y`} />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setReviewing(null)}
                className={`${BTN} border border-[var(--border)] text-[var(--text-muted)]`}>
                Cancel
              </button>
              <button type="button" onClick={submitReview}
                disabled={busy || !reviewNote.trim()}
                className={`${BTN} text-white ${
                  reviewing.status === 'Rejected'
                    ? 'bg-[var(--accent-red)]' : 'bg-[var(--accent-orange)]'}`}>
                {reviewing.status === 'Rejected' ? 'Reject document' : 'Allow exception'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Board ─────────────────────────────────────────────────────
const OnboardingBoard = () => {
  const { scope, can, companyId } = useHrms();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [starting, setStarting] = useState(false);
  const [open, setOpen] = useState(null);

  const mayWrite = can(CAP.ONBOARDING_WRITE);

  const load = useCallback(async () => {
    // Wait for the company scope. `scope` starts empty while HrmsContext resolves it, and
    // GET /hrms/onboarding without a company_id is a 400 -- so every visit to this board
    // fired two failing requests before the real one. The same guard every other board
    // already has (AttendanceBoard, RecruitmentDashboard, AuditViewer, ...).
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getOnboardings({ ...scope, status: status || undefined }, scope);
      setRows(Array.isArray(data) ? data : data?.onboardings || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load onboarding.');
    } finally {
      setLoading(false);
    }
  }, [companyId, status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((r) => [r.candidate_name, r.onb_no, r.employee_id]
      .some((v) => (v || '').toLowerCase().includes(term)));
  }, [rows, search]);

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={UserPlus}
        title="Onboarding Cases"
        subtitle="Where a candidate becomes an employee"
        actions={mayWrite && (
          <button type="button" onClick={() => setStarting(true)}
            className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
            <Plus size={15} /> Start onboarding
          </button>
        )}
      />
      <HrmsScopeBar />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, ONB number or Employee ID"
            className={`${FIELD} pl-9`} aria-label="Search onboarding" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className={`${FIELD} w-auto min-w-[160px]`} aria-label="Filter by status">
          <option value="">All statuses</option>
          {['Pre-Onboarding', 'Onboarding', 'Completed'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading onboarding…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && visible.length === 0 && (
        <HrmsEmpty
          icon={UserPlus}
          title="Nobody is being onboarded"
          hint="Onboarding opens once a candidate accepts their offer."
        />
      )}

      {!loading && !error && visible.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {visible.map((r) => (
            <button key={r.onb_no} type="button" onClick={() => setOpen(r.onb_no)}
              className="text-left rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 hover:border-[var(--accent-indigo)] transition-colors">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                    {r.candidate_name}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    {r.onb_no}{r.designation ? ` · ${r.designation}` : ''}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${STATUS_TONE[r.status] || ''}`}>
                  {r.status}
                </span>
              </div>

              {/* §7.5 Stage 5 — completeness across all six groups, not just the
                  joining checklist. This is the number that answers "who is behind?". */}
              <div className="mt-3 flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
                  <div className={`h-full ${pctTone(r.completeness?.percent ?? 0)}`}
                    style={{ width: `${r.completeness?.percent ?? 0}%` }} />
                </div>
                <span className="text-[11px] font-bold text-[var(--text-muted)] shrink-0">
                  {r.completeness?.percent ?? 0}%
                </span>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
                <span className="flex items-center gap-1 text-[var(--text-muted)]">
                  <CalendarDays size={12} /> {fmtDate(r.joining_date)}
                </span>
                <span className={`flex items-center gap-1 ${BG_TONE[r.bg_verification] || ''}`}>
                  <ShieldCheck size={12} /> {r.bg_verification}
                </span>
                {r.employee_id && (
                  <span className="flex items-center gap-1 font-bold text-[var(--accent-indigo)]">
                    <Link2 size={12} /> {r.employee_id}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {starting && (
        <StartModal onClose={() => setStarting(false)}
          onStarted={(no) => { setStarting(false); load(); setOpen(no); }} />
      )}
      {open && (
        <Detail onbNo={open} onClose={() => setOpen(null)} onChanged={load} />
      )}
    </div>
  );
};

export default OnboardingBoard;
