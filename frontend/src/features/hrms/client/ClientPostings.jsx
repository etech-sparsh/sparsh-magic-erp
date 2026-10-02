import React, { useCallback, useEffect, useState } from 'react';
import { Megaphone, Plus, Link2, Users } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientPostings, createClientPosting,
  updateClientPosting, actOnClientPosting, getClientApplications,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, money } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import {
  useClientList, useClientScope, useSourceableRequisitions,
} from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ the job posting, and the applications against it.
 *
 * An approved Position Scorecard is a benchmark. It is not an advert, and nobody can apply
 * to a benchmark. This screen is what turns one into the other.
 *
 * -- Sparsh's screen, not the client's ---------------------------------------------
 * The client agrees the scorecard and reads the candidates. The advert is Sparsh's
 * professional work and its public link is Sparsh's to open and close, so a client holds
 * no posting capability at all and never reaches this panel.
 *
 * -- Applications are candidates -------------------------------------------------
 * An applicant IS a candidate; the posting is only how they arrived. So the applications
 * list here reads the same candidate records the Sourcing panel does, filtered to the ones
 * that came through a posting. Screening and shortlisting happen there, in the one place
 * they already happen, rather than being duplicated into a second pipeline.
 */

const MOVES = [
  { id: 'publish', label: 'Publish', tone: 'primary',
    cap: CAP.CLIENT_POSTING_PUBLISH, from: ['Draft'] },
  { id: 'close', label: 'Close vacancy', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_POSTING_WRITE, from: ['Published'],
    reasonHint: 'Why this vacancy is closing. Somebody will ask.' },
];

/** The advert's own fields, in the order somebody writes them. */
const SECTIONS = [
  ['summary', 'Summary', 'The job in a short paragraph — what it is and why it exists.'],
  ['responsibilities', 'Responsibilities', 'What this person will own day to day.'],
  ['requirements', 'Requirements', 'What an applicant needs before they apply.'],
];

const ClientPostings = ({ embedded, onChanged }) => {
  const { can } = useHrms();
  const scope = useClientScope();
  const refresh = () => { reload(); onChanged?.(); };
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientPostings, 'client_postings');

  const [drafting, setDrafting] = useState(false);
  const [editing, setEditing] = useState(null);
  const [opened, setOpened] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.CLIENT_POSTING_WRITE);

  const act = async (postingNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientPosting(postingNo, { action, ...payload }, scope);
      showSuccess(`${postingNo} updated`);
      setOpened(null);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'post', label: 'Vacancy',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.title}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.posting_no} · {r.cr_no}
          </span>
        </>
      ) },
    { key: 'where', label: 'Location',
      render: (r) => (
        <span className="text-[var(--text-muted)]">{r.location || '—'}</span>
      ) },
    { key: 'apps', label: 'Applications',
      render: (r) => (
        <span className="tabular-nums font-semibold text-[var(--text-main)]">
          {r.applications ?? 0}
        </span>
      ) },
    { key: 'published', label: 'Published',
      render: (r) => (
        <span className="text-[var(--text-muted)]">
          {r.published_at ? day(r.published_at) : '—'}
        </span>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canWrite && r.status === 'Draft' && (
            <Btn onClick={() => setEditing(r)}>Edit</Btn>
          )}
          <Btn onClick={() => setOpened(r)}>Open</Btn>
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.title}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.posting_no} · {r.cr_no}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Location', value: r.location || '—' },
        { label: 'Applications', value: String(r.applications ?? 0) },
        { label: 'Published', value: r.published_at ? day(r.published_at) : '—' },
      ]} />
      <div className="flex items-center gap-1.5">
        {canWrite && r.status === 'Draft' && <Btn onClick={() => setEditing(r)}>Edit</Btn>}
        <Btn onClick={() => setOpened(r)}>Open</Btn>
      </div>
    </div>
  );

  const header = {
    title: 'Job postings',
    subtitle: 'The advert behind an approved scorecard, and the people who applied to it',
    actions: canWrite && (
      <Btn tone="primary" onClick={() => setDrafting(true)}>
        <Plus size={14} /> Create a posting
      </Btn>
    ),
  };

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader {...header} />
      ) : (
        <>
          <HrmsPageHeader icon={Megaphone} {...header} />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        A posting can only be written against a requisition whose scorecard the client has
        already approved — an advert written before the benchmark is agreed collects
        applicants measured against nothing. Applications arrive as ordinary candidates, so
        screening and shortlisting happen on the Sourcing step, not here.
      </WhoseMove>

      {loading && <HrmsLoading label="Loading postings…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.posting_no}
          empty={<HrmsEmpty
            icon={Megaphone}
            title="No job postings yet"
            hint={canWrite
              ? 'Create one against a requisition whose scorecard the client has approved.'
              : 'Nothing has been advertised yet.'}
          />}
        />
      )}

      {drafting && (
        <PostingModal
          busy={busy}
          onClose={() => setDrafting(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await createClientPosting(payload, scope);
              showSuccess(`${data.posting_no} drafted`);
              setDrafting(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be created.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editing && (
        <PostingModal
          row={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientPosting(editing.posting_no, payload, scope);
              showSuccess(`${editing.posting_no} saved`);
              setEditing(null);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be saved.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {opened && (
        <PostingDetail
          row={opened}
          busy={busy}
          onClose={() => setOpened(null)}
          onAct={(action, payload) => act(opened.posting_no, action, payload)}
        />
      )}
    </div>
  );
};

/** Write the advert. On a new one the requisition is chosen; on an edit it is fixed. */
const PostingModal = ({ row, busy, onClose, onSubmit }) => {
  const scope = useClientScope();
  const editing = !!row;
  const [form, setForm] = useState(() => ({
    cr_no: row?.cr_no || '',
    title: row?.title || '',
    location: row?.location || '',
    summary: row?.summary || '',
    responsibilities: row?.responsibilities || '',
    requirements: row?.requirements || '',
    show_salary: !!row?.show_salary,
  }));
  // Only requisitions whose scorecard the client has APPROVED: those are the ones the
  // server will accept a posting against, and offering any others invites a 409.
  const { requisitions: reqs, loading: loaded } = useSourceableRequisitions(
    scope, { enabled: !editing });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const ready = editing || !!form.cr_no;

  return (
    <Modal
      title={editing ? `Edit ${row.posting_no}` : 'Create a job posting'}
      subtitle="This is what an applicant reads, so write it for them rather than for the file."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready}
            onClick={() => onSubmit(editing ? { ...form, cr_no: undefined } : form)}>
            {busy ? 'Saving…' : (editing ? 'Save' : 'Create draft')}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        {editing ? (
          <Detail label="Requisition">{row.cr_no}</Detail>
        ) : (
          <div>
            <label className={LABEL} htmlFor="jp-cr">Requisition</label>
            <select id="jp-cr" className={FIELD} value={form.cr_no} onChange={set('cr_no')}>
              <option value="">Select an approved requisition…</option>
              {reqs.map((r) => (
                <option key={r.cr_no} value={r.cr_no}>
                  {r.cr_no} — {r.role_title || 'Untitled role'}
                </option>
              ))}
            </select>
            {!loaded && !reqs.length && (
              <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
                Nothing to advertise yet — a posting needs a requisition whose scorecard
                the client has approved.
              </p>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="jp-title">Title</label>
            <input id="jp-title" className={FIELD} value={form.title}
              onChange={set('title')} placeholder="Defaults to the role title" />
          </div>
          <div>
            <label className={LABEL} htmlFor="jp-loc">Location</label>
            <input id="jp-loc" className={FIELD} value={form.location}
              onChange={set('location')} />
          </div>
        </div>

        {SECTIONS.map(([key, label, hint]) => (
          <div key={key}>
            <label className={LABEL} htmlFor={`jp-${key}`}>{label}</label>
            <textarea id={`jp-${key}`} className={TEXTAREA} rows={3}
              value={form[key]} onChange={set(key)} placeholder={hint} />
          </div>
        ))}

        <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
          <input type="checkbox" checked={form.show_salary}
            onChange={(e) => setForm((f) => ({ ...f, show_salary: e.target.checked }))} />
          Advertise the salary range
        </label>
        <p className="text-[11px] text-[var(--text-muted)]">
          Off by default. A band the client agreed with Sparsh is not automatically one
          they want published.
        </p>
      </div>
    </Modal>
  );
};

/** The advert, its public link, and everyone who has applied through it. */
const PostingDetail = ({ row, busy, onClose, onAct }) => {
  const scope = useClientScope();
  const [apps, setApps] = useState([]);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getClientApplications(
        { ...scope, posting_no: row.posting_no, limit: 200 });
      setApps(data?.client_applications || []);
    } catch { setApps([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.posting_no, JSON.stringify(scope)]);

  useEffect(() => { load(); }, [load]);

  const link = row.posting_code
    ? `${window.location.origin}/hrms/client-apply/${row.posting_code}`
    : null;

  return (
    <Modal
      title={row.title}
      subtitle={`${row.posting_no} · ${row.cr_no}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Moves row={row} moves={MOVES} busy={busy} onAct={onAct} />
        </>
      )}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <StatusChip status={row.status} />
          {row.closed_reason && (
            <span className="text-[11.5px] text-[var(--accent-orange)]">
              Closed: {row.closed_reason}
            </span>
          )}
        </div>

        {/* The public link only exists once the vacancy is open. Showing it on a draft
            would be offering an address that answers 410. */}
        {row.status === 'Published' && link && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)]
            p-2.5">
            <div className="flex items-center gap-2">
              <Link2 size={14} className="text-[var(--text-muted)] shrink-0" />
              <span className="text-[11.5px] font-mono truncate
                text-[var(--text-main)]">{link}</span>
              <Btn onClick={() => {
                try {
                  navigator.clipboard.writeText(link);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                } catch { /* clipboard blocked — the link is on screen to copy by hand */ }
              }}>
                {copied ? 'Copied' : 'Copy'}
              </Btn>
            </div>
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
              Anyone with this link can apply. It stays valid until the vacancy is closed.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Detail label="Location">{row.location}</Detail>
          <Detail label="Employment type">{row.employment_type}</Detail>
          <Detail label="Salary range">
            {row.show_salary && row.salary_range_min != null
              ? `${money(row.salary_range_min)} – ${money(row.salary_range_max)}`
              : 'Not advertised'}
          </Detail>
          <Detail label="Published">
            {row.published_at ? day(row.published_at) : '—'}
          </Detail>
        </div>

        {SECTIONS.map(([key, label]) => (
          <Detail key={key} label={label}>{row[key] || '—'}</Detail>
        ))}

        <div className="border-t border-[var(--border)] pt-3.5">
          <div className="flex items-center gap-2">
            <Users size={14} className="text-[var(--text-muted)]" />
            <p className="text-[10px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">Applications</p>
            <span className="ml-auto text-[13px] font-bold tabular-nums
              text-[var(--text-main)]">{apps.length}</span>
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            They arrive as candidates — screen and shortlist them on the Sourcing step.
          </p>
          <div className="mt-2.5 space-y-2">
            {!apps.length && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Nobody has applied yet.
              </p>
            )}
            {apps.map((a) => (
              <div key={a.ccn_no}
                className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)]
                  p-2.5 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                    {a.candidate_name}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {a.ccn_no}
                    {a.current_employer ? ` · ${a.current_employer}` : ''}
                    {a.applied_at ? ` · applied ${day(a.applied_at)}` : ''}
                  </p>
                </div>
                <StatusChip status={a.status} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default ClientPostings;
