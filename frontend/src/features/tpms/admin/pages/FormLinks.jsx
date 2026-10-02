import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RefreshCw, Link2 as LinkIcon, Copy, Check, ExternalLink, Send, AlertTriangle, Inbox, Trash2, X } from 'lucide-react';
import { DashboardHero, HeroButton, Section, TableShell, Th, Td, usePaged, Pager } from '../../common/dashboardKit';
import { getCompanies, getFormAssignments, resendFormAssignment, deleteFormAssignment } from '../../../../services/tpmsFormsApi';
import { currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import { useNotification } from '../../../../context/NotificationContext';

/* ─────────────────────────────────────────────────────────────
   TPMS ▸ Admin ▸ Form Links.
   Every unique, single-use form link (Accountability / Ownership / Culture /
   Implementation Feedback) per company + month, with copy, open, resend and delete.
   Data: GET /forms/assignments  ·  resend: POST /forms/assignments/{id}/resend  ·  delete: DELETE /forms/assignments/{id}
   ───────────────────────────────────────────────────────────── */

const FORM_LABEL = {
  accountability: 'Accountability',
  ownership: 'Ownership',
  culture: 'Culture',
  implementation_feedback: 'Implementation Feedback',
};

// Aliased rather than used as `motion.div` inline — matches LeadershipCycles, and the
// no-unused-vars rule does not recognise the member-expression form as a use.
const MotionDiv = motion.div;

/** Confirm deleting one form link.
    Not a formality: the link has already been emailed, so deleting it breaks a URL sitting
    in someone's inbox — and if they had started the form, their progress goes with it. The
    browser confirm this replaces could name the respondent and nothing else. Mounted only
    while a row is pending, so it seeds from that row and needs no reset. */
const ConfirmDeleteLinkModal = ({ row, busy, onClose, onConfirm }) => {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-red-bg)] text-[var(--accent-red)] shrink-0">
              <Trash2 size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Delete this form link?</h3>
          </div>
          <button type="button" onClick={onClose} disabled={busy}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-2.5">
            <span className="block text-[13.5px] font-bold truncate">{row.respondent_name || 'This respondent'}</span>
            <span className="block text-[10.5px] font-semibold text-[var(--text-muted)] truncate">
              {row.respondent_email}
            </span>
          </div>

          {row.status === 'submitted' ? (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>This form has already been <b>submitted</b>. Deleting the link discards the response with it.</span>
            </div>
          ) : (
            <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
              The link has already been emailed, so deleting it breaks the URL in
              {row.respondent_name ? ` ${row.respondent_name}'s` : ' their'} inbox. Any answers
              started and not yet submitted are lost. Resend issues a fresh link instead.
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Keep it
          </button>
          <button type="button" onClick={onConfirm} disabled={busy} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {busy ? 'Deleting…' : 'Delete Link'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const STATUS_TONE = {
  submitted: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  opened: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  sent: { c: 'var(--text-muted)', bg: 'var(--input-bg)' },
  expired: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
  pending: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)' },
};

const selectCls =
  'h-9 px-3 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]';

const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ value, label: periodLabel(value) || value });
  }
  return out;
};

const fullUrl = (link) => (!link ? '' : link.startsWith('http') ? link : window.location.origin + link);

/* "Last sent" reads as an age, because the question it answers is "did my schedule just go
   out?" — and a date alone makes the reader do that subtraction. The exact timestamp stays on
   the title attribute for anyone who needs it. */
/* A timestamp with no offset is UTC, not local. The API stamps one now, but an older
   deployment (or any other endpoint reusing this helper) can still send a bare
   "2026-08-25T07:16:38" — read as local that is 5h30m off in IST, which is precisely how a
   link mailed minutes ago came to read "5h ago". */
const asDate = (value) => {
  if (!value) return null;
  const s = String(value).trim().replace(' ', 'T');
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(s);
  const d = new Date(hasZone ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
};

const sentAgo = (value) => {
  const then = asDate(value);
  if (!then) return '—';
  const mins = Math.floor((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return then.toLocaleDateString();
};

const StatusPill = ({ status }) => {
  const t = STATUS_TONE[status] || STATUS_TONE.sent;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full capitalize"
      style={{ color: t.c, background: t.bg }}>
      {status || '—'}
    </span>
  );
};

const FormLinks = () => {
  const { showSuccess, showError } = useNotification();
  const months = useMemo(() => monthOptions(), []);
  const [companies, setCompanies] = useState([]);
  const [company, setCompany] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [formType, setFormType] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copiedId, setCopiedId] = useState('');
  const [resending, setResending] = useState('');
  const [deletingId, setDeletingId] = useState('');
  const [pendingDelete, setPendingDelete] = useState(null);   // row awaiting confirmation

  useEffect(() => {
    getCompanies()
      .then((res) => setCompanies((res.data || []).map((c) => ({ id: String(c._id || c.id), name: c.name || c._id }))))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getFormAssignments({ company_id: company || undefined, period: period || undefined });
      setRows(res.data?.assignments || []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load form links.');
    } finally {
      setLoading(false);
    }
  }, [company, period]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(
    () => (formType ? rows.filter((r) => r.form_type === formType) : rows),
    [rows, formType],
  );
  const paged = usePaged(filtered, 15);

  const copy = async (row) => {
    try {
      await navigator.clipboard.writeText(fullUrl(row.link));
      setCopiedId(row.id);
      setTimeout(() => setCopiedId(''), 1600);
    } catch {
      showError('Could not copy — select the link and copy manually.');
    }
  };

  const resend = async (row) => {
    if (!row.respondent_email) { showError('This recipient has no email on file.'); return; }
    setResending(row.id);
    try {
      await resendFormAssignment(row.id);
      showSuccess(`Link re-sent to ${row.respondent_email}`);
      load();
    } catch (e) {
      showError(e.response?.data?.detail || 'Resend failed.');
    } finally {
      setResending('');
    }
  };

  const handleDelete = async () => {
    const row = pendingDelete;
    if (!row) return;
    setDeletingId(row.id);
    try {
      await deleteFormAssignment(row.id);
      setPendingDelete(null);
      showSuccess('Form link deleted successfully');
      load();
    } catch (e) {
      // The dialog stays open on failure so the error is read next to what it refers to,
      // and the delete can be retried without hunting for the row again.
      showError(e.response?.data?.detail || 'Delete failed.');
    } finally {
      setDeletingId('');
    }
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={LinkIcon} title="Form Links" subtitle="Unique monthly form links per company & HOD — copy, open, resend or delete">
        <select value={company} onChange={(e) => setCompany(e.target.value)} className={selectCls}>
          <option value="">All companies</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)} className={selectCls}>
          {months.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <select value={formType} onChange={(e) => setFormType(e.target.value)} className={selectCls}>
          <option value="">All forms</option>
          {Object.entries(FORM_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <Section title="Generated links" icon={LinkIcon}
        subtitle={filtered.length ? `${filtered.length} link${filtered.length === 1 ? '' : 's'}` : 'Nothing for this selection'}>
        {loading && !rows.length ? (
          <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-14 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><Inbox size={20} /></span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No form links yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-md">
              Links are created when a form activity (Accountability &amp; Ownership Rating, Culture Rating,
              Implementation Update Feedback) is <b>scheduled</b> for this company &amp; month.
            </p>
          </div>
        ) : (
          <>
            <TableShell minWidth={1000}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Form</Th><Th>HOD / MD</Th><Th>Company</Th>
                  <Th align="center">Status</Th><Th align="center">Last sent</Th>
                  <Th>Link</Th><Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {paged.pageRows.map((r) => (
                  <tr key={r.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className="font-bold whitespace-nowrap">{FORM_LABEL[r.form_type] || r.form_type}</Td>
                    <Td>
                      <div className="font-semibold">{r.respondent_name || '—'}</div>
                      <div className="text-[11px] text-[var(--text-muted)]">{r.respondent_email || 'no email'}</div>
                    </Td>
                    <Td className="text-[var(--text-muted)] whitespace-nowrap">{r.company_name || r.company_id}</Td>
                    <Td align="center"><StatusPill status={r.status} /></Td>
                    <Td align="center" className="whitespace-nowrap text-[11px] font-semibold text-[var(--text-muted)]"
                      title={asDate(r.last_sent)?.toLocaleString() || ''}>
                      {sentAgo(r.last_sent)}
                    </Td>
                    <Td>
                      <code className="text-[11px] text-[var(--text-muted)] font-mono truncate inline-block max-w-[260px] align-middle">{r.link}</code>
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button type="button" onClick={() => copy(r)} title="Copy link"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90">
                          {copiedId === r.id ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
                        </button>
                        <a href={fullUrl(r.link)} target="_blank" rel="noreferrer" title="Open form"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)]">
                          <ExternalLink size={12} /> Open
                        </a>
                        <button type="button" onClick={() => resend(r)} disabled={resending === r.id || !r.respondent_email} title="Email this link again"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed">
                          <Send size={12} /> {resending === r.id ? 'Sending…' : 'Resend'}
                        </button>
                        <button type="button" onClick={() => setPendingDelete(r)} disabled={deletingId === r.id} title="Delete form link"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed">
                          <Trash2 size={12} /> {deletingId === r.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <Pager {...paged} label="links" />
          </>
        )}
      </Section>

      <AnimatePresence>
        {pendingDelete && (
          <ConfirmDeleteLinkModal key="delete-link" row={pendingDelete}
            busy={deletingId === pendingDelete.id}
            onClose={() => setPendingDelete(null)} onConfirm={handleDelete} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default FormLinks;
