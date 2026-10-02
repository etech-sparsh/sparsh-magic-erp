import React, { useCallback, useEffect, useState } from 'react';
import {
  Megaphone, Plus, Search, Copy, Check, ExternalLink, Radio, Users2, Trash2, Pause, Play,
  Send, ShieldCheck, History, X,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getPostings, updatePosting, deletePosting, applyUrlFor,
  publishPosting, approvePostingExecSearch, getPostingHistory,
} from '../../../services/hrmsApi';
import CreatePostingModal from './CreatePostingModal';

/**
 * HRMS ▸ Step 4 — job postings.
 *
 * One card per posting, and one LIVE posting per role. A posting is drafted first (channels
 * and all), then published as its own explicit act — so a card can be sitting in Draft,
 * waiting on Management (Executive Search only), Live, Paused, Expired or Closed.
 *
 * Channels are where HR chose to advertise; the single link is the destination all of them
 * point at. Which channel a candidate actually came through is answered on the form itself
 * and read from the `source` column in the pipeline — HR's intent and the applicant's own
 * answer are different facts, and conflating them is what made per-board postings wrong.
 *
 * External postings carry a visible warning: applications made on a job board never reach
 * this pipeline. Showing an application count of 0 without that context would look like a
 * bug rather than the design.
 */

const STATUS_TONES = {
  Draft: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  'Pending Management Approval': 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  Live: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Paused: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Expired: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Closed: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const Tile = ({ icon: Icon, label, value }) => (
  <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
    <div className="flex items-center gap-2 text-[var(--text-muted)]">
      <Icon size={14} />
      <span className="text-[10.5px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{value ?? 0}</p>
  </div>
);

const PostingCard = ({ posting: p, canWrite, canApproveExec, onCopy, copied, onStatus,
                       onDelete, onPublish, onApproveExec, onHistory }) => {
  const isExternal = p.apply_link_mode === 'external';
  const link = isExternal ? p.external_url : applyUrlFor(p.posting_code);
  const isDraft = p.live_status === 'Draft';
  const isPendingApproval = p.live_status === 'Pending Management Approval';
  // Before it is published there is no link to share and no applications to count, so the
  // link block and the live/pause controls would both be promising something untrue.
  const isPublished = !isDraft && !isPendingApproval;

  return (
    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--input-bg)] text-[var(--text-main)]">
              {isExternal ? 'External link' : 'Form link'}
            </span>
            <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
              STATUS_TONES[p.live_status] || 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
              {p.live_status}
            </span>
          </div>
          <p className="mt-1.5 text-[13.5px] font-bold text-[var(--text-main)] truncate">
            {p.title || 'Untitled role'}
          </p>
          <p className="font-mono text-[11px] text-[var(--text-muted)]">
            {p.posting_code} · {p.jd_no}
          </p>
        </div>
        <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${
          p.requires_assessment
            ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
            : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
          {p.requires_assessment ? 'Assessment required' : 'No assessment'}
        </span>
      </div>

      {(p.channels || []).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {p.channels.map((c) => (
            <span key={c}
              className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--input-bg)] text-[var(--text-muted)]">
              {c}
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-center">
        {[['Applied', p.application_count], ['Posted', p.posting_date || '—'],
          ['Closes', p.expiry_date || '—']].map(([label, value]) => (
          <div key={label} className="p-2 rounded-lg bg-[var(--input-bg)]">
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
            <p className="text-[12px] font-bold text-[var(--text-main)] truncate">{value}</p>
          </div>
        ))}
      </div>

      {isPublished ? (
        <div>
          <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--input-bg)]">
            <span className="flex-1 font-mono text-[11px] text-[var(--text-muted)] truncate">{link}</span>
            <button type="button" onClick={() => onCopy(p.posting_code, link)}
              title="Copy application link"
              className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
              {copied === p.posting_code ? <Check size={14} /> : <Copy size={14} />}
            </button>
            {isExternal && (
              <a href={link} target="_blank" rel="noopener noreferrer"
                className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                <ExternalLink size={14} />
              </a>
            )}
          </div>
          {isExternal ? (
            <p className="mt-1.5 text-[11px] text-[var(--accent-red)]">
              Applications made there do not appear here — it links out to another site.
            </p>
          ) : (
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
              Share this one link anywhere — applicants tell the form where they found the job.
            </p>
          )}
        </div>
      ) : (
        <p className="p-2 rounded-lg bg-[var(--input-bg)] text-[11.5px] text-[var(--text-muted)]">
          {isPendingApproval
            ? 'Executive Search needs Management’s approval before this can be published.'
            : 'Not published yet — publish it to open the application link.'}
        </p>
      )}

      {canWrite && (
        <div className="flex items-center gap-1.5 pt-1 flex-wrap">
          {isDraft && (
            <button type="button" onClick={() => onPublish(p)}
              className="h-8 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold flex items-center gap-1.5">
              <Send size={13} /> Publish
            </button>
          )}
          {isPendingApproval && canApproveExec && (
            <button type="button" onClick={() => onApproveExec(p)}
              className="h-8 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold flex items-center gap-1.5">
              <ShieldCheck size={13} /> Approve Executive Search
            </button>
          )}
          {isPublished && (p.live_status === 'Live' ? (
            <button type="button" onClick={() => onStatus(p, 'Paused')}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <Pause size={13} /> Pause
            </button>
          ) : p.live_status !== 'Closed' && (
            <button type="button" onClick={() => onStatus(p, 'Live')}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <Play size={13} /> Set live
            </button>
          ))}
          {p.live_status !== 'Closed' && (
            <button type="button" onClick={() => onStatus(p, 'Closed')}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)]">
              Close
            </button>
          )}
          <button type="button" onClick={() => onHistory(p)} title="Posting history"
            className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] ml-auto">
            <History size={13} />
          </button>
          <button type="button" onClick={() => onDelete(p)} title="Delete posting"
            className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)]">
            <Trash2 size={13} />
          </button>
        </div>
      )}
    </div>
  );
};

/** The posting's own history, read from the audit trail the server already keeps -- so it
 *  cannot disagree with what actually happened to the posting. */
const PostingHistoryModal = ({ posting, scope, onClose }) => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getPostingHistory(posting.posting_code, scope)
      .then(({ data }) => setRows(data?.history || []))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the history.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const when = (value) => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)] flex items-center gap-2">
            <History size={16} className="text-[var(--accent-indigo)]" />
            History — {posting.posting_code}
          </h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <div className="p-5 overflow-y-auto">
          {error && <HrmsError message={error} />}
          {!rows && !error && <HrmsLoading label="Reading the audit trail…" />}
          {rows && rows.length === 0 && (
            <p className="text-[12.5px] text-[var(--text-muted)]">Nothing recorded yet.</p>
          )}
          {rows && rows.length > 0 && (
            <ol className="space-y-2.5">
              {rows.map((r, i) => (
                <li key={i} className="flex gap-3">
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[var(--accent-indigo)]" />
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-semibold text-[var(--text-main)] capitalize">
                      {r.action}
                    </p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      {r.actor_name || 'system'} · {when(r.at)}
                      {r.detail ? ` · ${r.detail}` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
};

const PostingList = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ postings: [], stats: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [copied, setCopied] = useState(null);
  const [historyFor, setHistoryFor] = useState(null);

  const canWrite = can(CAP.POSTING_WRITE);
  const canApproveExec = can(CAP.POSTING_APPROVE_EXEC_SEARCH);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getPostings({
        ...scope, search: search || undefined, live_status: status || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load postings.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, search, status]);

  useEffect(() => { load(); }, [load]);

  const copy = async (code, link) => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(code);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      showError("Couldn't copy to clipboard.");
    }
  };

  const setStatusFor = async (p, next) => {
    try {
      await updatePosting(p.posting_code, { live_status: next }, scope);
      showSuccess(`${p.posting_code} set to ${next}`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the posting.');
    }
  };

  const publish = async (p) => {
    try {
      await publishPosting(p.posting_code, scope);
      showSuccess(`${p.posting_code} is live — share ${applyUrlFor(p.posting_code)}`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not publish the posting.');
    }
  };

  const approveExec = async (p) => {
    try {
      await approvePostingExecSearch(p.posting_code, {}, scope);
      showSuccess(`Executive Search approved for ${p.posting_code} — it can now be published`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not approve Executive Search.');
    }
  };

  const remove = async (p) => {
    if (!window.confirm(
      `Remove posting ${p.posting_code}? Applications already received are kept.`)) return;
    try {
      await deletePosting(p.posting_code, scope);
      showSuccess(`${p.posting_code} removed`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete the posting.');
    }
  };

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Megaphone}
        title="Job Postings"
        subtitle="Publish an approved role and share its single application link anywhere."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canWrite && (
              <button type="button" onClick={() => setShowCreate(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> New posting
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-3 gap-3">
        <Tile icon={Radio} label="Live postings" value={stats.live} />
        <Tile icon={Users2} label="Applications" value={stats.applications} />
        <Tile icon={Megaphone} label="Postings" value={stats.postings} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by code, role or JD…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {['Draft', 'Pending Management Approval', 'Live', 'Paused', 'Expired', 'Closed']
            .map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading postings…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.postings.length === 0 ? (
        <HrmsEmpty icon={Megaphone} title="No postings yet"
          hint={canWrite
            ? 'Publish an approved job description to start receiving applications.'
            : undefined} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.postings.map((p) => (
            <PostingCard key={p.posting_code} posting={p} canWrite={canWrite}
              canApproveExec={canApproveExec}
              onCopy={copy} copied={copied} onStatus={setStatusFor} onDelete={remove}
              onPublish={publish} onApproveExec={approveExec} onHistory={setHistoryFor} />
          ))}
        </div>
      )}

      {showCreate && (
        <CreatePostingModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}

      {historyFor && (
        <PostingHistoryModal posting={historyFor} scope={scope}
          onClose={() => setHistoryFor(null)} />
      )}
    </div>
  );
};

export default PostingList;
