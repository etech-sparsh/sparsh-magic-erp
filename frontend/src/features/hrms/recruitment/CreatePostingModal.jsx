import React, { useEffect, useState } from 'react';
import { X, Megaphone, Link2, FileText, Copy, Check, ShieldAlert } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { getJds, createPosting, applyUrlFor } from '../../../services/hrmsApi';

/**
 * HRMS ▸ Step 4 — draft a job posting from an approved JD.
 *
 * Creating and publishing are separate moments (Internal Recruitment SOP Step 4: Create Job
 * Posting -> Select Sourcing Channels -> Publish), so this modal produces a DRAFT. The
 * Postings board is where it is reviewed and published.
 *
 * ONE posting, ONE link, several CHANNELS. The channels are where HR chose to advertise the
 * role; the link is the single destination all of them point at. A candidate's `source` is
 * still what the applicant says on the form — the channel is HR's intent, the source is the
 * applicant's own answer, and conflating them is what made the old per-board postings wrong
 * the moment a link was forwarded.
 *
 * Two things this screen is careful about:
 *
 * 1. **The code is previewed client-side and sent with the request.** The user copies the
 *    apply link while filling the form, so the code they copied must be the one stored. The
 *    server honours it only if it matches the public pattern and is unused, and returns
 *    whatever it actually saved.
 * 2. **An external posting is labelled honestly.** Applications made on a job board never
 *    reach this pipeline — nothing writes them back, and no source is captured either.
 *    Saying so here is better than an application count that silently stays at zero.
 */

// Mirrors backend RecruitmentChannel exactly (models/hrms.py). Executive Search is the one
// channel with a gate: a posting naming it opens Pending Management Approval.
const CHANNELS = [
  { value: 'Internal Database', hint: 'Search people already in the talent pool.' },
  { value: 'Job Portals', hint: 'Naukri, LinkedIn, and the rest.' },
  { value: 'Employee Referrals', hint: 'Ask the team who they know.' },
  { value: 'Executive Search', hint: 'Leadership roles — needs Management approval.' },
];
const EXEC_SEARCH = 'Executive Search';

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

/** Mirrors the server's `^[A-Z]{2}-[A-Z0-9]{6}$`. Uses crypto when available — this is a
 *  public identifier, and guessable codes would let someone enumerate a company's openings. */
const previewCode = () => {
  const bytes = new Uint8Array(6);
  (window.crypto || window.msCrypto)?.getRandomValues?.(bytes);
  const body = Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join('');
  return `JB-${body || 'XXXXXX'}`;
};

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const CreatePostingModal = ({ onClose, onCreated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [jds, setJds] = useState([]);
  const [jdNo, setJdNo] = useState('');
  const [mode, setMode] = useState('auto');
  const [externalUrl, setExternalUrl] = useState('');
  // Minted once per modal, not per render: the user copies this link while the rest of the
  // form is still being filled in, and a code that changed underneath them would be copied
  // wrong. The server stores this exact value unless it is already taken.
  const [code] = useState(previewCode);
  const [expiry, setExpiry] = useState('');
  const [notes, setNotes] = useState('');
  const [requiresAssessment, setRequiresAssessment] = useState(false);
  const [channels, setChannels] = useState([]);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);

  const applyUrl = applyUrlFor(code);
  const selectedJd = jds.find((j) => j.jd_no === jdNo);
  const needsExecApproval = channels.includes(EXEC_SEARCH);

  const toggleChannel = (value) => setChannels((prev) =>
    (prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]));

  useEffect(() => {
    getJds({ ...scope, status: 'Approved' })
      .then(({ data }) => {
        const list = data?.job_descriptions || [];
        setJds(list);
        if (list.length) setJdNo(list[0].jd_no);
      })
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load job descriptions.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(applyUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      showError('Could not copy the link.');
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!jdNo) return showError('Select an approved job description.');
    if (!channels.length) return showError('Select at least one recruitment channel.');
    if (mode === 'external' && !/^https?:\/\//i.test(externalUrl.trim())) {
      return showError('Enter a link starting with http:// or https://, or switch back to the generated form.');
    }

    setSaving(true);
    try {
      const { data } = await createPosting({
        jd_no: jdNo,
        apply_link_mode: mode,
        external_url: mode === 'external' ? externalUrl.trim() : null,
        code: mode === 'external' ? null : code,
        expiry_date: expiry || null,
        notes: notes || null,
        requires_assessment: requiresAssessment,
        channels,
      }, scope);
      showSuccess(needsExecApproval
        ? `${data.posting.posting_code} drafted — it needs Management's approval before it can be published`
        : `${data.posting.posting_code} drafted — review it on the board, then publish`);
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the posting.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <Megaphone size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Create a job posting</h2>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-5 overflow-y-auto">
          <div>
            <label className={LABEL} htmlFor="p-jd">Job description *</label>
            {jds.length === 0 ? (
              <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-muted)] flex items-start gap-2">
                <FileText size={14} className="mt-0.5 shrink-0" />
                <span>
                  No approved job descriptions yet. A JD becomes publishable once its
                  requisition clears HR review and MD approval.
                </span>
              </div>
            ) : (
              <select id="p-jd" value={jdNo} onChange={(e) => setJdNo(e.target.value)} className={FIELD}>
                {jds.map((j) => (
                  <option key={j.jd_no} value={j.jd_no}>{j.jd_no} — {j.title || 'Untitled'}</option>
                ))}
              </select>
            )}
          </div>

          {/* The approved JD's own content, pulled straight from the selected JD so the
              poster can see what is about to be advertised without leaving the modal. It is
              read-only here: the JD is approved, and editing it is Step 3's job. */}
          {selectedJd && (
            <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-2">
              <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                From the approved JD (read-only)
              </p>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
                {[
                  ['Job Title', selectedJd.title],
                  ['Experience', selectedJd.experience],
                  ['Qualifications', selectedJd.qualifications],
                  ['Location', selectedJd.location],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span className="block text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                      {label}
                    </span>
                    <span className="text-[var(--text-main)]">{value || '—'}</span>
                  </div>
                ))}
              </div>
              {selectedJd.job_summary && (
                <p className="text-[11.5px] text-[var(--text-muted)] whitespace-pre-wrap">
                  {selectedJd.job_summary}
                </p>
              )}
              {selectedJd.skills && (
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  <span className="font-bold">Skills:</span> {selectedJd.skills}
                </p>
              )}
            </div>
          )}

          <div>
            <span className={LABEL}>Recruitment channels *</span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {CHANNELS.map((c) => (
                <label key={c.value}
                  className={`flex items-start gap-2 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                    channels.includes(c.value)
                      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                      : 'border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                  <input type="checkbox" className="mt-0.5" checked={channels.includes(c.value)}
                    onChange={() => toggleChannel(c.value)} />
                  <span>
                    <span className="block text-[12.5px] font-semibold text-[var(--text-main)]">
                      {c.value}
                    </span>
                    <span className="block text-[11px] text-[var(--text-muted)]">{c.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            {needsExecApproval && (
              <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-[var(--accent-orange)]">
                <ShieldAlert size={13} className="shrink-0 mt-0.5" />
                Executive Search is selected — this posting will open Pending Management
                Approval and cannot be published until Management clears it.
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-2 flex-wrap mb-1.5">
              <span className={`${LABEL} mb-0`}>Where applicants apply</span>
              <div className="flex gap-1">
                {[['auto', 'Generate form link'], ['external', 'Paste external link']].map(([m, label]) => (
                  <button key={m} type="button" onClick={() => setMode(m)}
                    className={`px-2 py-0.5 rounded-md text-[11px] font-bold border ${
                      mode === m
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {mode === 'external' ? (
              <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-2">
                <input value={externalUrl} onChange={(e) => setExternalUrl(e.target.value)}
                  placeholder="https://…" className={FIELD} />
                <p className="text-[11px] text-[var(--accent-red)]">
                  Applications made on that site will <strong>not</strong> appear in this
                  pipeline — nothing sends them back here, and no source is recorded.
                </p>
              </div>
            ) : (
              <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-2">
                <div className="flex items-center gap-2">
                  <Link2 size={13} className="shrink-0 text-[var(--text-muted)]" />
                  <span className="flex-1 font-mono text-[11.5px] text-[var(--text-main)] truncate">
                    {applyUrl}
                  </span>
                  <button type="button" onClick={copyLink} title="Copy application link"
                    className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                  </button>
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  One link for this role. Share it on LinkedIn, Naukri, your careers page or
                  a WhatsApp group — the form asks every applicant where they found the job,
                  and that answer becomes their <strong>source</strong> in the candidate
                  pipeline.
                </p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="p-exp">Expiry date</label>
              <input id="p-exp" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="p-notes">Notes</label>
              <input id="p-notes" value={notes} onChange={(e) => setNotes(e.target.value)} className={FIELD} />
            </div>
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={requiresAssessment}
              onChange={(e) => setRequiresAssessment(e.target.checked)} className="mt-0.5" />
            <span className="text-[12.5px] text-[var(--text-main)]">
              <span className="font-bold">Require an assessment</span>
              <span className="block text-[11.5px] text-[var(--text-muted)]">
                Applicants must pass an assessment before interviews can be scheduled. The flag
                is copied onto each applicant when they apply.
              </span>
            </span>
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !jdNo || !channels.length}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : 'Create draft'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default CreatePostingModal;
