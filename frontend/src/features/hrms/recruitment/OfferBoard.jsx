import React, { useCallback, useEffect, useState } from 'react';
import {
  FileSignature, Plus, X, Copy, Check, Send, Ban, Trash2, Eye, History, Printer, ShieldCheck,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getOffers, getOfferableCandidates, createOffer, updateOffer, sendOffer, approveOffer,
  revokeOffer, deleteOffer, offerUrlFor,
} from '../../../services/hrmsApi';
import OfferPaper from './OfferPaper';

/**
 * HRMS ▸ offers.
 *
 * A Draft is editable and every edit is versioned; a Sent offer is frozen. The UI makes
 * that visible rather than surprising the user with a 409 — the editor becomes a read-only
 * preview once the letter has gone out.
 *
 * The CTC column appears only when the server included it (`ctc_visible`), so a viewer
 * without salary rights cannot recover it from the payload.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const STATUS_TONE = {
  Draft: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Sent: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Accepted: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Declined: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Revoked: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const inr = (n) => (typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '—');

const CreateModal = ({ onClose, onCreated }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    uk: '', ctc: '', joining_date: '', designation: '', company_name: '', location: '',
  });
  const [signature, setSignature] = useState('');
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const canSend = can(CAP.OFFER_SEND);

  useEffect(() => {
    getOfferableCandidates(scope)
      .then(({ data }) => setPeople(data?.candidates || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load candidates.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pre-fill the CTC from the server's suggestion when a candidate is chosen. A number the
  // recruiter corrects beats an empty box they guess at.
  const pickCandidate = (e) => {
    const uk = e.target.value;
    const person = people.find((p) => p.uk === uk);
    setForm((f) => ({
      ...f, uk,
      ctc: person?.suggested_ctc != null ? String(person.suggested_ctc) : '',
    }));
  };

  const submit = async (sendNow) => {
    if (!form.uk) return showError('Select a candidate.');
    if (sendNow && !signature.trim()) {
      return showError("Type the authorised signatory's name to send.");
    }
    setSaving(true);
    try {
      await createOffer({
        ...form,
        ctc: Number(form.ctc),
        send_now: sendNow,
        signature: sendNow ? signature.trim() : null,
      }, scope);
      showSuccess(sendNow ? 'Offer sent' : 'Draft created');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the offer.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">New offer</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <div className="p-5 space-y-3 overflow-y-auto">
          <div>
            <label className={LABEL} htmlFor="o-uk">Candidate *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No candidates are ready for an offer. A candidate becomes offerable once
                they reach <strong>Selected</strong> and have no live offer already.
              </p>
            ) : (
              <select id="o-uk" value={form.uk} onChange={pickCandidate} className={FIELD}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>{p.candidate_name}</option>
                ))}
              </select>
            )}
            {/* Says the rule up front rather than letting the server's 409 be the first
                anybody hears of it — the list above is filtered on stage, not on whether
                the checks have cleared. */}
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
              Background verification must be complete and approved before an offer can be
              raised.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="o-ctc">Annual CTC *</label>
              <input id="o-ctc" type="number" min="1" value={form.ctc} onChange={set('ctc')}
                className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="o-join">Joining date *</label>
              <input id="o-join" type="date" value={form.joining_date}
                onChange={set('joining_date')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="o-desig">Designation</label>
              <input id="o-desig" value={form.designation} onChange={set('designation')}
                placeholder="Defaults from the requisition" className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="o-co">Company name</label>
              <input id="o-co" value={form.company_name} onChange={set('company_name')}
                className={FIELD} />
            </div>
          </div>

          {canSend && (
            <div>
              <label className={LABEL} htmlFor="o-sig">Authorised signatory</label>
              <input id="o-sig" value={signature} onChange={(e) => setSignature(e.target.value)}
                placeholder="Required only to send now" className={FIELD} />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="button" disabled={saving || !form.uk} onClick={() => submit(false)}
              className="h-9 px-4 rounded-lg border border-[var(--accent-indigo)] text-[var(--accent-indigo)] text-[12px] font-bold disabled:opacity-50">
              Save draft
            </button>
            {canSend && (
              <button type="button" disabled={saving || !form.uk || !signature.trim()}
                onClick={() => submit(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
                {saving ? 'Working…' : 'Send now'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const EditorModal = ({ offer: initial, onClose, onChanged }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [offer, setOffer] = useState(initial);
  const [content, setContent] = useState(initial.content || '');
  const [signature, setSignature] = useState(initial.signature || '');
  const [preview, setPreview] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [saving, setSaving] = useState(false);
  // Management/Finance's separate sign-off (Annexure B) — its own signature box, not the
  // one used to send the letter, because approving and sending are two different people's
  // acts even when the same person happens to hold both capabilities.
  const [approveSig, setApproveSig] = useState('');
  const [approving, setApproving] = useState(false);

  const isDraft = offer.status === 'Draft';
  const canWrite = can(CAP.OFFER_WRITE);
  const canSend = can(CAP.OFFER_SEND);
  const canApprove = can(CAP.OFFER_APPROVE);
  const approval = offer.offer_approval;

  const approveIt = async () => {
    if (!approveSig.trim()) return showError('Type your name to sign this approval.');
    setApproving(true);
    try {
      const { data } = await approveOffer(offer.offer_no, { signature: approveSig.trim() }, scope);
      setOffer(data);
      showSuccess('Offer approved');
      onChanged();
    } catch (err) {
      // Surfaced verbatim on purpose: on a client-track offer the server explains that
      // approval is an internal-track control and the client approves it instead, which is
      // a more useful answer than a client-side guess at every offer's track ahead of time.
      showError(err?.response?.data?.detail || 'Could not approve.');
    } finally {
      setApproving(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await updateOffer(offer.offer_no, { content, signature }, scope);
      setOffer(data);
      showSuccess(`Saved as v${data.version}`);
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const issue = async () => {
    if (!signature.trim()) return showError("Type the authorised signatory's name.");
    setSaving(true);
    try {
      const { data } = await sendOffer(offer.offer_no, { signature: signature.trim() }, scope);
      setOffer(data);
      showSuccess('Offer sent');
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not send the offer.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4 print:p-0 print:bg-white">
      <div className="w-full max-w-3xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col print:max-w-none print:max-h-none print:border-0 print:shadow-none">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] print:hidden">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {offer.candidate_name}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {offer.offer_no} · v{offer.version} · {offer.status}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => setPreview((p) => !p)}
              title={preview ? 'Edit' : 'Preview'}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
              <Eye size={16} />
            </button>
            {(offer.history || []).length > 0 && (
              <button type="button" onClick={() => setShowHistory((h) => !h)} title="Versions"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                <History size={16} />
              </button>
            )}
            <button type="button" onClick={() => window.print()} title="Print / Save PDF"
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
              <Printer size={16} />
            </button>
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
              <X size={17} />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto">
          {!isDraft && (
            <div className="mx-5 mt-4 p-3 rounded-lg bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)] print:hidden">
              This offer has been sent, so the letter is frozen — the candidate may be
              reading it. Revoke it and raise a new one if the terms have changed.
            </div>
          )}

          {/* Management/Finance sign-off (internal-track offers only — Annexure B). Only
              relevant while still a Draft; once sent, whether it was approved is history,
              not something to act on. */}
          {isDraft && approval?.approved_at && (
            <div className="mx-5 mt-4 p-3 rounded-lg bg-[var(--accent-green-bg,var(--input-bg))] text-[12px] text-[var(--accent-green,var(--text-main))] flex items-center gap-2 print:hidden">
              <ShieldCheck size={14} />
              Approved by {approval.approved_by_name}
              {approval.approved_at ? ` · ${new Date(approval.approved_at).toLocaleDateString()}` : ''}
            </div>
          )}
          {isDraft && !approval?.approved_at && canApprove && (
            <div className="mx-5 mt-4 p-3.5 rounded-lg border border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] print:hidden space-y-2">
              <p className="text-[12.5px] font-semibold text-[var(--accent-indigo)] flex items-center gap-1.5">
                <ShieldCheck size={14} /> Awaiting your approval
              </p>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Only relevant for an internal-track offer — a client-track one is the
                client's own call, not Sparsh's.
              </p>
              <div className="flex items-center gap-2">
                <input value={approveSig} onChange={(e) => setApproveSig(e.target.value)}
                  placeholder="Type your name to sign"
                  className="flex-1 h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)]" />
                <button type="button" disabled={approving || !approveSig.trim()} onClick={approveIt}
                  className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50 whitespace-nowrap">
                  {approving ? 'Approving…' : 'Approve'}
                </button>
              </div>
            </div>
          )}

          {showHistory && (
            <div className="mx-5 mt-4 p-3 rounded-lg border border-[var(--border)] print:hidden">
              <p className={LABEL}>Earlier versions</p>
              <ul className="space-y-1.5">
                {(offer.history || []).map((h) => (
                  <li key={h.version} className="text-[12px] text-[var(--text-muted)]">
                    <strong className="text-[var(--text-main)]">v{h.version}</strong>
                    {' · '}{h.edited_by}
                    {h.edited_at ? ` · ${new Date(h.edited_at).toLocaleString()}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview || !isDraft || !canWrite ? (
            <div className="p-5 print:p-0">
              <OfferPaper offer={{ ...offer, content }} signature={signature} />
            </div>
          ) : (
            <div className="p-5 space-y-3 print:hidden">
              <div>
                <label className={LABEL} htmlFor="e-body">Letter body</label>
                <textarea id="e-body" rows={16} value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] font-mono text-[var(--text-main)] resize-y" />
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  {'{designation}'}, {'{company}'}, {'{ctc}'} and {'{joining_date}'} are
                  filled in automatically. An unknown placeholder is left as-is.
                </p>
              </div>
              <div>
                <label className={LABEL} htmlFor="e-sig">Authorised signatory *</label>
                <input id="e-sig" value={signature} onChange={(e) => setSignature(e.target.value)}
                  className={FIELD} />
              </div>
            </div>
          )}
        </div>

        {isDraft && canWrite && (
          <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)] print:hidden">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Close
            </button>
            <button type="button" disabled={saving} onClick={save}
              className="h-9 px-4 rounded-lg border border-[var(--accent-indigo)] text-[var(--accent-indigo)] text-[12px] font-bold disabled:opacity-50">
              Save draft
            </button>
            {canSend && (
              <button type="button" disabled={saving || !signature.trim()} onClick={issue}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                <Send size={13} /> Send to candidate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const OfferBoard = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ offers: [], stats: {}, ctc_visible: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);
  const [copied, setCopied] = useState(null);

  const canWrite = can(CAP.OFFER_WRITE);
  const canSend = can(CAP.OFFER_SEND);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getOffers({ ...scope, status: status || undefined });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load offers.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status]);

  useEffect(() => { load(); }, [load]);

  const copy = async (code) => {
    try {
      await navigator.clipboard.writeText(offerUrlFor(code));
      setCopied(code);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      showError("Couldn't copy to clipboard.");
    }
  };

  const revoke = async (o) => {
    const reason = window.prompt(`Revoke ${o.offer_no}? Optionally note why:`);
    if (reason === null) return;
    try {
      await revokeOffer(o.offer_no, { reason: reason || null }, scope);
      showSuccess('Offer revoked');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not revoke.');
    }
  };

  const remove = async (o) => {
    if (!window.confirm(`Delete draft ${o.offer_no}?`)) return;
    try {
      await deleteOffer(o.offer_no, scope);
      showSuccess('Draft deleted');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={FileSignature}
        title="Offers"
        subtitle="Issue offer letters and track acceptance."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canWrite && (
              <button type="button" onClick={() => setShowCreate(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> New offer
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[['Drafts', stats.drafts], ['Awaiting response', stats.awaiting],
          ['Accepted', stats.accepted], ['Declined', stats.declined]].map(([l, v]) => (
          <div key={l} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{l}</p>
            <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{v ?? 0}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {[['', 'All'], ['Draft', 'Draft'], ['Sent', 'Sent'], ['Accepted', 'Accepted'],
          ['Declined', 'Declined'], ['Revoked', 'Revoked']].map(([key, label]) => (
          <button key={key || 'all'} type="button" onClick={() => setStatus(key)}
            className={`px-2.5 py-1 rounded-lg text-[12px] font-bold border ${
              status === key
                ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <HrmsLoading label="Loading offers…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.offers.length === 0 ? (
        <HrmsEmpty icon={FileSignature} title="No offers yet"
          hint={canWrite ? 'Create one for a candidate who has been Selected.' : undefined} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.offers.map((o) => (
            <div key={o.offer_no}
              className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                    {o.candidate_name}
                  </p>
                  <p className="font-mono text-[10.5px] text-[var(--text-muted)]">
                    {o.offer_no} · v{o.version}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${
                  STATUS_TONE[o.status]}`}>
                  {o.status}
                </span>
              </div>

              <p className="text-[12.5px] text-[var(--text-main)]">{o.designation}</p>

              {o.status === 'Draft' && o.offer_approval?.approved_at && (
                <p className="text-[11px] font-semibold text-[var(--accent-green,var(--accent-indigo))] flex items-center gap-1">
                  <ShieldCheck size={11} /> Approved by {o.offer_approval.approved_by_name}
                </p>
              )}

              <div className={`grid ${data.ctc_visible ? 'grid-cols-2' : 'grid-cols-1'} gap-2 text-center`}>
                {data.ctc_visible && (
                  <div className="p-2 rounded-lg bg-[var(--input-bg)]">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">CTC</p>
                    <p className="text-[12px] font-bold text-[var(--text-main)]">{inr(o.ctc)}</p>
                  </div>
                )}
                <div className="p-2 rounded-lg bg-[var(--input-bg)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Joining</p>
                  <p className="text-[12px] font-bold text-[var(--text-main)]">{o.joining_date}</p>
                </div>
              </div>

              {o.access_code && (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--input-bg)]">
                  <span className="flex-1 font-mono text-[10.5px] text-[var(--text-muted)] truncate">
                    {offerUrlFor(o.access_code)}
                  </span>
                  <button type="button" onClick={() => copy(o.access_code)} title="Copy link"
                    className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                    {copied === o.access_code ? <Check size={13} /> : <Copy size={13} />}
                  </button>
                </div>
              )}

              {o.response_note && (
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Candidate note: “{o.response_note}”
                </p>
              )}

              <div className="flex items-center gap-1.5">
                <button type="button" onClick={() => setEditing(o)}
                  className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)]">
                  {o.status === 'Draft' && canWrite ? 'Edit & send' : 'View'}
                </button>
                {canSend && o.status === 'Sent' && (
                  <button type="button" onClick={() => revoke(o)} title="Revoke"
                    className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1">
                    <Ban size={12} /> Revoke
                  </button>
                )}
                {canWrite && o.status === 'Draft' && (
                  <button type="button" onClick={() => remove(o)} title="Delete draft"
                    className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)] ml-auto">
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateModal onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }} />
      )}
      {editing && (
        <EditorModal offer={editing} onClose={() => setEditing(null)} onChanged={load} />
      )}
    </div>
  );
};

export default OfferBoard;
