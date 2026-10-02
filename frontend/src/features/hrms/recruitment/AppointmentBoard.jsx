import React, { useCallback, useEffect, useState } from 'react';
import {
  BadgeCheck, Plus, X, Copy, Check, Send, Ban, Eye, Printer,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getAppointments, getAppointableCandidates, createAppointment, updateAppointment,
  sendAppointment, cancelAppointment, appointmentUrlFor,
} from '../../../services/hrmsApi';
import AppointmentPaper from './AppointmentPaper';

/**
 * HRMS ▸ appointment letters (Phase 11-R, Item 3).
 *
 * The letter issued AFTER the offer is accepted, confirming joining terms. It is a separate
 * artifact from the offer with its own lifecycle — Generated → Sent → Pending
 * Acknowledgement → Acknowledged, or Cancelled.
 *
 * A GENERATED letter is editable; once sent it is frozen, and the UI shows that as a
 * read-only preview rather than letting the user discover it through a 409.
 *
 * The CTC row appears only when the server included it (`ctc_visible`), so a viewer without
 * salary rights cannot recover it from the payload.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const STATUS_TONE = {
  Generated: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Sent: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  'Pending Acknowledgement': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Acknowledged: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Cancelled: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

const inr = (n) => (typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '—');

const Tile = ({ label, value, tone }) => (
  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
    <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
    <p className={`text-[22px] font-bold tracking-tight mt-1 ${tone || 'text-[var(--text-main)]'}`}>{value}</p>
  </div>
);

const CreateModal = ({ onClose, onCreated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    uk: '', joining_date: '', designation: '', department: '', company_name: '',
    location: '', ctc: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    getAppointableCandidates(scope)
      .then(({ data }) => setPeople(data?.candidates || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load candidates.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pre-fill from the ACCEPTED OFFER. The letter confirms what was agreed, so retyping the
  // terms by hand is a way to introduce a discrepancy between two documents that must say
  // the same thing.
  const pick = (e) => {
    const uk = e.target.value;
    const person = people.find((p) => p.uk === uk);
    setForm((f) => ({
      ...f,
      uk,
      joining_date: person?.suggested_joining_date || '',
      designation: person?.suggested_designation || '',
      ctc: person?.suggested_ctc != null ? String(person.suggested_ctc) : '',
    }));
  };

  const submit = async () => {
    if (!form.uk) { showError('Choose a candidate.'); return; }
    setSaving(true);
    try {
      const payload = { ...form };
      payload.ctc = form.ctc === '' ? null : Number(form.ctc);
      await createAppointment(payload, scope);
      showSuccess('The appointment letter was drafted. Review it, then send.');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not draft the letter.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">
            Generate an appointment letter
          </h2>
          <button type="button" onClick={onClose} className="text-[var(--text-muted)]">
            <X size={17} />
          </button>
        </div>

        {loading && <HrmsLoading label="Loading eligible candidates…" />}

        {!loading && people.length === 0 && (
          <HrmsEmpty
            icon={BadgeCheck}
            title="Nobody is eligible yet"
            hint="An appointment letter can only be issued to a candidate who has accepted their offer and does not already have one."
          />
        )}

        {!loading && people.length > 0 && (
          <>
            <div>
              <label className={LABEL}>Candidate</label>
              <select className={FIELD} value={form.uk} onChange={pick}>
                <option value="">Choose…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>
                    {p.candidate_name} ({p.uk})
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={LABEL}>Joining date</label>
                <input type="date" className={FIELD} value={form.joining_date} onChange={set('joining_date')} />
              </div>
              <div>
                <label className={LABEL}>Annual CTC</label>
                <input type="number" className={FIELD} value={form.ctc} onChange={set('ctc')} />
              </div>
              <div>
                <label className={LABEL}>Designation</label>
                <input className={FIELD} value={form.designation} onChange={set('designation')} />
              </div>
              <div>
                <label className={LABEL}>Department</label>
                <input className={FIELD} value={form.department} onChange={set('department')} />
              </div>
              <div>
                <label className={LABEL}>Company name</label>
                <input className={FIELD} value={form.company_name} onChange={set('company_name')} />
              </div>
              <div>
                <label className={LABEL}>Location</label>
                <input className={FIELD} value={form.location} onChange={set('location')} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                {saving ? 'Drafting…' : 'Generate draft'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const AppointmentBoard = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [preview, setPreview] = useState(null);
  const [sending, setSending] = useState(null);
  const [signature, setSignature] = useState('');
  const [copied, setCopied] = useState(null);

  const canWrite = can(CAP.APPOINTMENT_WRITE);
  const canSend = can(CAP.APPOINTMENT_SEND);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: payload } = await getAppointments(scope);
      setData(payload);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load appointment letters.');
    } finally {
      setLoading(false);
    }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const copy = async (row) => {
    try {
      await navigator.clipboard.writeText(appointmentUrlFor(row.access_code));
      setCopied(row.appointment_no);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      showError('Could not copy the link.');
    }
  };

  const doSend = async () => {
    if (!sending) return;
    try {
      await sendAppointment(sending.appointment_no, { signature }, scope);
      showSuccess('The appointment letter has been issued.');
      setSending(null);
      setSignature('');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not send the letter.');
    }
  };

  const doCancel = async (row) => {
    try {
      await cancelAppointment(row.appointment_no, { reason: 'Cancelled by HR' }, scope);
      showSuccess('The letter was cancelled and its link revoked.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not cancel the letter.');
    }
  };

  const rows = data?.appointments || [];
  const stats = data?.stats || {};

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BadgeCheck}
        title="Appointment & Agreements"
        subtitle="Issued after an offer is accepted, confirming joining terms"
        actions={canWrite && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold flex items-center gap-1.5"
          >
            <Plus size={14} />
            Generate
          </button>
        )}
      />
      <HrmsScopeBar />

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Tile label="Generated" value={stats.generated ?? 0} />
        <Tile label="Sent" value={stats.sent ?? 0} tone="text-[var(--accent-indigo)]" />
        <Tile label="Awaiting ack" value={stats.pending_ack ?? 0} tone="text-[var(--accent-indigo)]" />
        <Tile label="Acknowledged" value={stats.acknowledged ?? 0} tone="text-[var(--accent-green,var(--accent-indigo))]" />
        <Tile label="Cancelled" value={stats.cancelled ?? 0} tone="text-[var(--accent-red)]" />
      </div>

      {loading && <HrmsLoading label="Loading appointment letters…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={BadgeCheck}
          title="No appointment letters yet"
          hint="Generate one for a candidate who has accepted their offer. This stage is optional — a company that does not issue appointment letters can go straight to onboarding."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[860px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Letter</th>
                <th className="text-left px-4 py-2.5">Candidate</th>
                <th className="text-left px-4 py-2.5">Designation</th>
                {data?.ctc_visible && <th className="text-left px-4 py-2.5">CTC</th>}
                <th className="text-left px-4 py-2.5">Joining</th>
                <th className="text-left px-4 py-2.5">Status</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.appointment_no} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5 font-mono text-[12px] text-[var(--text-muted)]">
                    {row.appointment_no}
                  </td>
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-main)]">
                    {row.candidate_name}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.designation}</td>
                  {data?.ctc_visible && (
                    <td className="px-4 py-2.5 text-[var(--text-main)]">{inr(row.ctc)}</td>
                  )}
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.joining_date}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-bold ${STATUS_TONE[row.status] || ''}`}>
                      {row.status}
                    </span>
                    {/* §7.5 Stage 7 — how many of the NDA / Code of Conduct / policy
                        documents this joiner has actually signed. A letter marked
                        Acknowledged says nothing about the documents behind it. */}
                    {(row.document_acks || []).length > 0 && (
                      <span className="block mt-1 text-[10.5px] font-semibold text-[var(--text-muted)]">
                        {row.document_acks.filter((d) => d.acknowledged_at).length}
                        /{row.document_acks.length} documents signed
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => setPreview(row)}
                        title="Preview"
                        className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)]"
                      >
                        <Eye size={13} />
                      </button>
                      {row.access_code && (
                        <button
                          type="button"
                          onClick={() => copy(row)}
                          title="Copy the candidate link"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)]"
                        >
                          {copied === row.appointment_no ? <Check size={13} /> : <Copy size={13} />}
                        </button>
                      )}
                      {canSend && row.status === 'Generated' && (
                        <button
                          type="button"
                          onClick={() => { setSending(row); setSignature(row.signature || ''); }}
                          title="Send"
                          className="h-7 px-2.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[11px] font-bold flex items-center gap-1"
                        >
                          <Send size={12} />
                          Send
                        </button>
                      )}
                      {canSend && !['Acknowledged', 'Cancelled'].includes(row.status) && (
                        <button
                          type="button"
                          onClick={() => doCancel(row)}
                          title="Cancel"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]"
                        >
                          <Ban size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <CreateModal onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />
      )}

      {preview && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="w-full max-w-3xl my-8 space-y-3">
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => window.print()}
                className="h-9 px-3.5 rounded-lg bg-white text-slate-900 text-[13px] font-bold flex items-center gap-1.5"
              >
                <Printer size={14} />
                Print
              </button>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="h-9 px-3.5 rounded-lg bg-white text-slate-900 text-[13px] font-bold"
              >
                Close
              </button>
            </div>
            <AppointmentPaper appointment={preview} />
          </div>
        </div>
      )}

      {sending && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                Send {sending.appointment_no}
              </h2>
              <p className="text-[12.5px] text-[var(--text-muted)] mt-1">
                Once sent, the letter is frozen — the candidate must be able to rely on what
                they are reading. Type the authorised signatory&rsquo;s name.
              </p>
            </div>
            <input
              className={FIELD}
              placeholder="Authorised signatory"
              value={signature}
              onChange={(e) => setSignature(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSending(null)}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doSend}
                disabled={!signature.trim()}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                Send letter
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AppointmentBoard;
