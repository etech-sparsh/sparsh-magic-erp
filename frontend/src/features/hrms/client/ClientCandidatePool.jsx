import React, { useCallback, useEffect, useState } from 'react';
import { Archive, Search, Building2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientCandidatePool, sourceFromClientPool,
  getClientRequisitions, getClientScorecards,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day, money } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientCompanies } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ candidates a client passed on, and who to send them to next.
 *
 * A client rejecting a CV ends that person's run at THAT client. It says nothing about
 * whether they suit somebody else, and deleting or closing them would throw away sourcing
 * Sparsh has already paid for — along with the candidate's own time.
 *
 * -- The one surface that spans tenants -------------------------------------------
 * Everything else in Client Hiring is scoped to one company. This is not, which is why the
 * SERVER refuses a client-side caller outright rather than filtering them down: a scoping
 * mistake here would show one client another client's applicants. Rendering it only for
 * Sparsh staff is the second lock, not the first.
 *
 * -- Re-sharing creates a NEW record ----------------------------------------------
 * You choose the receiving client and one of their requisitions, and a fresh candidate is
 * written in THEIR tenant carrying the CV and profile. The original stays with the client
 * who rejected them — their record, their decision. The receiving client never sees it and
 * never learns that anybody passed on this person, which is the only reading of "reusable"
 * that does not breach tenant isolation.
 */

/** Why somebody is available. Rejected-by-client leads, because it is the common case. */
const FILTERS = [
  ['all', 'All'],
  ['Client Rejected', 'Rejected by a client'],
  ['Telephonic Failed', 'Telephonic failed'],
  ['Offer Declined', 'Offer declined'],
  ['Dropped Out', 'Dropped out'],
  ['Withdrawn', 'Withdrawn'],
];

const ClientCandidatePool = ({ embedded, onChanged }) => {
  const { can, isInternal } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [term, setTerm] = useState('');
  const [filter, setFilter] = useState('all');
  const [sharing, setSharing] = useState(null);
  const [busy, setBusy] = useState(false);

  const canSource = can(CAP.CLIENT_CANDIDATE_WRITE);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getClientCandidatePool(
        { limit: 200, ...(term ? { search: term } : {}) });
      setRows(data?.client_candidate_pool || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'The pool could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [term]);

  useEffect(() => { load(); }, [load]);

  const shown = filter === 'all'
    ? rows : rows.filter((r) => r.last_status === filter);

  const columns = [
    { key: 'who', label: 'Candidate',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.candidate_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {[r.email, r.phone].filter(Boolean).join(' · ') || '—'}
          </span>
        </>
      ) },
    { key: 'current', label: 'Current',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{r.current_employer || '—'}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.notice_period || '—'}
          </span>
        </>
      ) },
    { key: 'ctc', label: 'Expected',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)]">
          {r.expected_ctc != null ? money(r.expected_ctc) : '—'}
        </span>
      ) },
    { key: 'cv', label: 'CV',
      render: (r) => (
        <span className="text-[11.5px] text-[var(--text-muted)] truncate block max-w-[180px]"
          title={r.cv_reference || ''}>
          {r.cv_reference || '—'}
        </span>
      ) },
    { key: 'seen', label: 'Last seen',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.last_seen)}</span>
          {r.engagements > 1 && (
            <span className="block text-[11px] text-[var(--text-muted)]">
              {r.engagements} engagements
            </span>
          )}
        </>
      ) },
    { key: 'status', label: 'Why available', align: 'right',
      render: (r) => <StatusChip status={r.last_status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (canSource
        ? <Btn tone="primary" onClick={() => setSharing(r)}>Share with a client</Btn>
        : null) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.email || '—'}</p>
        </div>
        <StatusChip status={r.last_status} />
      </div>
      <Facts items={[
        { label: 'Current', value: r.current_employer || '—' },
        { label: 'Expected', value: r.expected_ctc != null ? money(r.expected_ctc) : '—' },
        { label: 'Last seen', value: day(r.last_seen) },
      ]} />
      {canSource && (
        <Btn tone="primary" onClick={() => setSharing(r)}>Share with a client</Btn>
      )}
    </div>
  );

  const header = {
    title: 'Rejected & available candidates',
    subtitle: 'People a client passed on, kept for the next role that suits them',
  };

  // A client-side account cannot reach the endpoint at all, so if one somehow renders this
  // screen it should say why rather than show an empty table.
  if (!isInternal) {
    return (
      <div className="space-y-5">
        <PanelHeader {...header} />
        <p className="text-[12.5px] text-[var(--text-muted)]">
          This pool spans every client engagement, so it is Sparsh&apos;s. Your own
          company&apos;s candidates are on the candidate list.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {embedded ? <PanelHeader {...header} /> : (
        <>
          <HrmsPageHeader icon={Archive} {...header} />
        </>
      )}

      <WhoseMove>
        A client rejecting a CV ends that person&apos;s run at that client, not their
        usefulness. Sharing somebody from here creates a fresh candidate against the
        requisition you choose — the original record stays where it is, and the receiving
        client never learns that anybody passed on them.
      </WhoseMove>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 flex-1 min-w-[220px] max-w-sm">
          <Search size={14} className="text-[var(--text-muted)] shrink-0" />
          <input
            className={FIELD}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search by name…"
            aria-label="Search the candidate pool"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl border
        border-[var(--border)] bg-[var(--input-bg)] w-fit">
        {FILTERS.map(([key, label]) => {
          const n = key === 'all' ? rows.length
            : rows.filter((r) => r.last_status === key).length;
          if (!n && key !== 'all' && filter !== key) return null;
          return (
            <button key={key} type="button" onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-bold transition-colors
                ${filter === key
                  ? 'bg-[var(--accent-indigo)] text-white'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
              {label}
              <span className="ml-1.5 tabular-nums opacity-70">{n}</span>
            </button>
          );
        })}
      </div>

      {loading && <HrmsLoading label="Loading the pool…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={shown} columns={columns} renderCard={renderCard}
          keyOf={(r) => `${r.from_company_id}:${r.ccn_no}`}
          empty={<HrmsEmpty
            icon={Archive}
            title={term ? 'Nobody matches that search' : 'Nobody is available yet'}
            hint={term
              ? 'Try a shorter name.'
              : 'Candidates appear here once a client passes on them, or an offer or '
                + 'joining falls through.'}
          />}
        />
      )}

      {sharing && (
        <ShareModal
          person={sharing}
          busy={busy}
          onClose={() => setSharing(null)}
          onSubmit={async ({ company_id, ...payload }) => {
            setBusy(true);
            try {
              const { data } = await sourceFromClientPool(payload, { company_id });
              showSuccess(`${data.candidate_name} shared as ${data.ccn_no}`);
              setSharing(null);
              load();
              onChanged?.();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'That candidate could not be shared.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
};

/**
 * Choose the receiving client, then one of their requisitions.
 *
 * Two pickers rather than one, because the second depends on the first: only requisitions
 * belonging to the chosen client, and only those whose scorecard THAT client has approved
 * — the same gate ordinary sourcing passes, so this cannot offer a target the API refuses.
 */
const ShareModal = ({ person, busy, onClose, onSubmit }) => {
  const { clients } = useClientCompanies();
  const [company, setCompany] = useState('');
  const [crNo, setCrNo] = useState('');
  const [reqs, setReqs] = useState([]);
  const [loadingReqs, setLoadingReqs] = useState(false);

  // The client who passed on them is excluded: re-sharing somebody back to the company
  // that just rejected them is never the intent, and the API would refuse the same
  // requisition anyway.
  const targets = clients.filter((c) => c.id !== person.from_company_id);

  const loadReqs = useCallback(async () => {
    if (!company) { setReqs([]); return; }
    setLoadingReqs(true);
    setCrNo('');
    try {
      const [reqRes, scRes] = await Promise.all([
        getClientRequisitions({ company_id: company, status: 'Approved', limit: 200 }),
        getClientScorecards({ company_id: company, status: 'Approved', limit: 200 }),
      ]);
      const agreed = new Set(
        (scRes.data?.client_scorecards || []).map((s) => s.cr_no).filter(Boolean));
      setReqs((reqRes.data?.client_requisitions || [])
        .filter((r) => agreed.has(r.cr_no)));
    } catch {
      setReqs([]);
    } finally {
      setLoadingReqs(false);
    }
  }, [company]);

  useEffect(() => { loadReqs(); }, [loadReqs]);

  return (
    <Modal
      title={`Share ${person.candidate_name} with a client`}
      subtitle="A fresh candidate record in the receiving client's own tenant."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !company || !crNo}
            onClick={() => onSubmit({
              company_id: company,
              ccn_no: person.ccn_no,
              from_company_id: person.from_company_id,
              cr_no: crNo,
            })}>
            {busy ? 'Sharing…' : 'Share for review'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Detail label="Current employer">{person.current_employer}</Detail>
          <Detail label="Notice period">{person.notice_period}</Detail>
          <Detail label="Expected CTC">
            {person.expected_ctc != null ? money(person.expected_ctc) : '—'}
          </Detail>
          <Detail label="CV">{person.cv_reference}</Detail>
        </div>

        <div>
          <label className={LABEL} htmlFor="share-co">
            <span className="inline-flex items-center gap-1.5">
              <Building2 size={12} /> Receiving client
            </span>
          </label>
          <select id="share-co" className={FIELD} value={company}
            onChange={(e) => setCompany(e.target.value)}>
            <option value="">Select a client…</option>
            {targets.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}{c.enabled ? '' : ' (module off)'}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            The client who passed on them is not listed.
          </p>
        </div>

        <div>
          <label className={LABEL} htmlFor="share-cr">Requisition</label>
          <select id="share-cr" className={FIELD} value={crNo} disabled={!company}
            onChange={(e) => setCrNo(e.target.value)}>
            <option value="">
              {company ? 'Select a requisition…' : 'Choose a client first'}
            </option>
            {reqs.map((r) => (
              <option key={r.cr_no} value={r.cr_no}>
                {r.cr_no} — {r.role_title || 'Untitled role'}
              </option>
            ))}
          </select>
          {company && !loadingReqs && !reqs.length && (
            <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
              That client has no requisition with an approved scorecard to source into.
            </p>
          )}
        </div>

        <p className="text-[11.5px] text-[var(--text-muted)]">
          Their CV and profile carry across. Their scores do not — those were measured
          against a different client&apos;s scorecard, and a number that means
          &ldquo;strong&rdquo; for one role means nothing for another. The receiving client
          sees them only once you screen and share them in the ordinary way.
        </p>
      </div>
    </Modal>
  );
};

export default ClientCandidatePool;
