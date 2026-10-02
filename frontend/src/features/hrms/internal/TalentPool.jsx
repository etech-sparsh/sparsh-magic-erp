import React, { useCallback, useEffect, useState } from 'react';
import { Bookmark, Search } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getCandidates, setTalentPool, sourceFromTalentPool, getRequisitions,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ internal track — the talent pool (Annexure C).
 *
 * "Build and maintain an internal talent pool of prior applicants and referrals."
 *
 * -- Consent is the feature, not a checkbox on it ---------------------------------------
 * A CV enters the pool only with the candidate's explicit consent, and that consent may not
 * outlive the record's retention period. The screen shows the expiry beside every entry for
 * a reason: keeping a CV past its retention date BECAUSE it is "in the pool" is exactly the
 * compliance failure SOP §11 and §13 exist to prevent, and an expiry nobody can see is one
 * nobody honours.
 *
 * -- Sourcing forward COPIES ---------------------------------------------------------------
 * Putting somebody forward creates a NEW candidate record against the new requisition, with
 * its own id and its own retention clock. It never re-points the original: their first
 * application is a record of what they applied for and when.
 */

const TalentPool = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tags, setTags] = useState('');
  const [search, setSearch] = useState('');
  const [sourcing, setSourcing] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.CANDIDATE_WRITE);
  const today = new Date().toISOString().slice(0, 10);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getCandidates({
        ...scope,
        talent_pool: true,
        tags: tags || undefined,
        search: search || undefined,
      });
      setRows(data?.candidates || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the talent pool.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, tags, search]);

  useEffect(() => { load(); }, [load]);

  const remove = async (candidate) => {
    setBusy(true);
    try {
      await setTalentPool(candidate.uk, { talent_pool: false }, scope);
      showSuccess(`${candidate.candidate_name} removed from the pool.`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'They could not be removed.');
    } finally {
      setBusy(false);
    }
  };

  const expired = (r) => r.consent_expires_at && String(r.consent_expires_at) < today;

  const columns = [
    {
      key: 'who',
      label: 'Candidate',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.candidate_name}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">{r.uk}</span>
        </>
      ),
    },
    {
      key: 'tags',
      label: 'Tags',
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          {(r.talent_pool_tags || []).map((t) => <Chip key={t}>{t}</Chip>)}
        </span>
      ),
    },
    {
      key: 'experience',
      label: 'Experience',
      render: (r) => r.total_experience || '—',
    },
    {
      key: 'consent',
      label: 'Consent until',
      render: (r) => (expired(r)
        ? <Chip tone="bad" title="Ask again before putting them forward.">
            expired {day(r.consent_expires_at)}
          </Chip>
        : <span className="text-[var(--text-main)]">
            {r.consent_expires_at ? day(r.consent_expires_at) : '—'}
          </span>),
    },
    { key: 'added', label: 'Added', render: (r) => day(r.talent_pool_added_at) },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (canWrite ? (
        <span className="inline-flex gap-1.5">
          <Btn disabled={expired(r)} onClick={() => setSourcing(r)}>Put forward</Btn>
          <Btn disabled={busy} onClick={() => remove(r)}>Remove</Btn>
        </span>
      ) : null),
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Bookmark}
        title="Talent pool"
        subtitle="Prior applicants and referrals who consented to being kept for future roles."
      />
      <HrmsScopeBar />

      <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)]
        px-4 py-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          A CV is here only because the candidate agreed to it, and only until their consent
          expires. Being in the pool does not extend how long we may keep a record — if the
          consent has lapsed, ask again rather than putting them forward.
        </p>
      </div>

      <div className="flex items-end gap-2.5 flex-wrap">
        <div>
          <label className={LABEL} htmlFor="pool-search">Search</label>
          <input id="pool-search" className={`${FIELD} w-56`} value={search}
            onChange={(e) => setSearch(e.target.value)} placeholder="Name, email, id" />
        </div>
        <div>
          <label className={LABEL} htmlFor="pool-tags">Tags</label>
          <input id="pool-tags" className={`${FIELD} w-56`} value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="python, ops — matches any" />
        </div>
        <Btn onClick={load}><Search size={14} /> Find</Btn>
      </div>

      {loading && <HrmsLoading label="Searching the pool…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Bookmark}
          title="Nobody in the pool yet"
          hint="Candidates join the pool from their own record, and only where they consented to being kept."
        />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.uk}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-[13px] text-[var(--text-main)]">
                    {r.candidate_name}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">{r.uk}</p>
                </div>
                {expired(r) && <Chip tone="bad">consent expired</Chip>}
              </div>
              <div className="flex flex-wrap gap-1">
                {(r.talent_pool_tags || []).map((t) => <Chip key={t}>{t}</Chip>)}
              </div>
              <Facts items={[
                { label: 'Experience', value: r.total_experience },
                { label: 'Consent until', value: day(r.consent_expires_at) },
                { label: 'Added', value: day(r.talent_pool_added_at) },
              ]} />
              {canWrite && (
                <div className="flex gap-1.5">
                  <Btn disabled={expired(r)} onClick={() => setSourcing(r)}>
                    Put forward
                  </Btn>
                  <Btn disabled={busy} onClick={() => remove(r)}>Remove</Btn>
                </div>
              )}
            </div>
          )}
        />
      )}

      {sourcing && (
        <SourceModal
          candidate={sourcing}
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          onClose={() => setSourcing(null)}
          onDone={(uk) => {
            setSourcing(null);
            showSuccess(`Brought forward as ${uk}.`);
          }}
          onError={showError}
        />
      )}
    </div>
  );
};

const SourceModal = ({ candidate, scope, busy, setBusy, onClose, onDone, onError }) => {
  const [reqs, setReqs] = useState([]);
  const [requestNo, setRequestNo] = useState('');

  useEffect(() => {
    getRequisitions({ ...scope })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
  }, [scope]);

  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await sourceFromTalentPool(candidate.uk, requestNo, scope);
      onDone(data?.uk);
    } catch (err) {
      onError(err?.response?.data?.detail || 'They could not be brought forward.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Put ${candidate.candidate_name} forward`}
      subtitle="This creates a NEW candidate record against the requisition you pick. Their original application is left exactly as it was."
      labelledBy="pool-source"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !requestNo} onClick={submit}>
            Put forward
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="pool-req">Requisition *</label>
        <select id="pool-req" className={FIELD} value={requestNo}
          onChange={(e) => setRequestNo(e.target.value)}>
          <option value="">Choose an internal requisition</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.request_no} — {r.designation_name}
            </option>
          ))}
        </select>
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          The budget gate applies exactly as it would to a fresh application — sourcing is
          sourcing, whichever drawer the CV came out of.
        </p>
      </div>
    </Modal>
  );
};

export default TalentPool;
