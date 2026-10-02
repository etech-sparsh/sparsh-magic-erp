import React, { useCallback, useEffect, useState } from 'react';
import { BookMarked, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getPolicies, getPolicy, logPolicyRevision, approvePolicyRevision, registerPolicy,
  updatePolicyApplicability, getPolicyAcknowledgements, getAcknowledgementDashboard,
  getDepartments, uploadPolicyDocument,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList, SignatureField } from './internalKit.jsx';

const EMPLOYMENT_TYPES = ['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'];
const MAX_MB = 15;

/** Same read-as-base64 shape DocumentPanel.jsx uses for every other HRMS upload. */
const readFile = (file) => new Promise((resolve, reject) => {
  if (file.size > MAX_MB * 1024 * 1024) {
    reject(new Error(`That file is larger than ${MAX_MB} MB.`));
    return;
  }
  const reader = new FileReader();
  reader.onload = () => resolve({
    name: file.name,
    mime_type: file.type || 'application/octet-stream',
    data: String(reader.result).split(',')[1] || '',
  });
  reader.onerror = () => reject(new Error('That file could not be read.'));
  reader.readAsDataURL(file);
});

const MultiCheck = ({ label, options, value, onChange, optionLabel = (o) => o, optionValue = (o) => o }) => (
  <div>
    <label className={LABEL}>{label}</label>
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const v = optionValue(opt);
        const checked = value.includes(v);
        return (
          <button key={v} type="button"
            onClick={() => onChange(checked ? value.filter((x) => x !== v) : [...value, v])}
            className={`px-2.5 h-7 rounded-full border text-[11.5px] font-semibold transition-colors
              ${checked
                ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)]/10 text-[var(--accent-indigo)]'
                : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
            {optionLabel(opt)}
          </button>
        );
      })}
    </div>
    {!options.length && <p className="text-[11px] text-[var(--text-muted)]">None configured.</p>}
  </div>
);

/**
 * HRMS ▸ the policy register and its review cycle (SOP §14).
 *
 * "This policy shall be reviewed annually... All amendments shall be logged in the
 * Modification History table."
 *
 * The register answers three questions a document in a folder cannot: which version is in
 * force, when it is next due to be looked at, and what changed last time.
 *
 * -- Drafting a revision is not approving it -----------------------------------------------
 * Anybody with `policy.write` can log "v1.1: added a clause about panel composition". Until
 * the MD approves it, the register still says v1.0 governs. The screen shows unapproved
 * revisions as exactly that, so nobody reads a draft as the rule.
 *
 * -- An overdue review is shown, never enforced ---------------------------------------------
 * Nothing in the module is blocked by a lapsed review. Refusing to hire because a policy
 * review slipped would punish the wrong people, and would guarantee the register gets worked
 * around instead of kept.
 */

const reviewTone = (status) => ({
  overdue: 'bad', due_soon: 'warn', current: 'good', unscheduled: 'neutral',
}[status] || 'neutral');

const PolicyRegister = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({ overdue: 0, due_soon: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [ackDash, setAckDash] = useState(null);

  const canWrite = can(CAP.POLICY_WRITE);
  const canApprove = can(CAP.POLICY_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getPolicies(scope);
      setRows(data?.policies || []);
      setCounts({ overdue: data?.overdue ?? 0, due_soon: data?.due_soon ?? 0 });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the policy register.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!companyId || !canWrite) return;
    getAcknowledgementDashboard(scope).then(({ data }) => setAckDash(data)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, canWrite]);

  const openPolicy = async (policyKey) => {
    try {
      const { data } = await getPolicy(policyKey, scope);
      setOpen(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open that policy.');
    }
  };

  const columns = [
    {
      key: 'policy',
      label: 'Policy',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.title}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.policy_key}
          </span>
        </>
      ),
    },
    { key: 'version', label: 'In force', render: (r) => `v${r.version}` },
    { key: 'effective', label: 'Effective', render: (r) => day(r.effective_date) },
    {
      key: 'review',
      label: 'Next review',
      render: (r) => (
        <>
          {day(r.next_review_due)}
          <Chip tone={reviewTone(r.review_status)}>
            {r.review_status.replace('_', ' ')}
          </Chip>
        </>
      ),
    },
    { key: 'owner', label: 'Owner', render: (r) => r.owner_role || '—' },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => <Btn onClick={() => openPolicy(r.policy_key)}>Open</Btn>,
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BookMarked}
        title="Policy register"
        subtitle="Which version governs, when it is next due for review, and what changed last time (SOP section 14)."
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setCreating(true)}>
            <Plus size={14} /> New policy
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {(counts.overdue > 0 || counts.due_soon > 0) && (
        <div className={`rounded-xl px-4 py-3 border ${counts.overdue
          ? 'border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)]'
          : 'border-[var(--accent-orange)]/30 bg-[var(--accent-orange-bg)]'}`}>
          <p className={`text-[12.5px] font-semibold ${counts.overdue
            ? 'text-[var(--accent-red)]' : 'text-[var(--accent-orange)]'}`}>
            {counts.overdue > 0 && `${counts.overdue} policy review(s) overdue.`}
            {counts.overdue > 0 && counts.due_soon > 0 && ' '}
            {counts.due_soon > 0 && `${counts.due_soon} due within the month.`}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            Nothing is blocked by this. A lapsed review is a conversation to have, not a
            reason to stop hiring.
          </p>
        </div>
      )}

      {/* §22.12 — "HR policy acknowledgement pending/completed" dashboard. */}
      {ackDash && ackDash.policies.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
            Acknowledgement completion ({ackDash.total_pending} pending)
          </p>
          <div className="space-y-1.5">
            {ackDash.policies.map((p) => (
              <div key={p.policy_key} className="flex items-center justify-between text-[12.5px]">
                <span className="text-[var(--text-main)]">{p.title} (v{p.version})</span>
                <Chip tone={p.pending === 0 ? 'good' : 'warn'}>
                  {p.acknowledged}/{p.applicable} acknowledged
                </Chip>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && <HrmsLoading label="Loading the register…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty icon={BookMarked} title="The register is empty"
          hint="The two recruitment policies are seeded the first time this screen is opened." />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.policy_key}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <p className="font-semibold text-[13px] text-[var(--text-main)]">
                  {r.title}
                </p>
                <Chip tone={reviewTone(r.review_status)}>
                  {r.review_status.replace('_', ' ')}
                </Chip>
              </div>
              <Facts items={[
                { label: 'In force', value: `v${r.version}` },
                { label: 'Effective', value: day(r.effective_date) },
                { label: 'Next review', value: day(r.next_review_due) },
              ]} />
              <Btn onClick={() => openPolicy(r.policy_key)}>Open</Btn>
            </div>
          )}
        />
      )}

      {open && (
        <PolicyModal
          policy={open}
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          canWrite={canWrite}
          canApprove={canApprove}
          onClose={() => setOpen(null)}
          onChanged={async () => {
            await openPolicy(open.policy_key);
            load();
          }}
          onSuccess={showSuccess}
          onError={showError}
        />
      )}
      {creating && (
        <NewPolicyModal
          scope={scope}
          onClose={() => setCreating(false)}
          onDone={() => { setCreating(false); load(); }}
          onSuccess={showSuccess}
          onError={showError}
        />
      )}
    </div>
  );
};

const NewPolicyModal = ({ scope, onClose, onDone, onSuccess, onError }) => {
  const [policyKey, setPolicyKey] = useState('');
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [ownerRole, setOwnerRole] = useState('');
  const [departments, setDepartments] = useState([]);
  const [departmentIds, setDepartmentIds] = useState([]);
  const [employmentTypes, setEmploymentTypes] = useState([]);
  const [ackRequired, setAckRequired] = useState(false);
  const [acceptanceDueDays, setAcceptanceDueDays] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (!policyKey.trim() || !title.trim()) {
      onError('A policy needs a key and a title.');
      return;
    }
    setBusy(true);
    try {
      const { data: policy } = await registerPolicy({
        policy_key: policyKey.trim(), title: title.trim(),
        category: category.trim() || undefined,
        owner_role: ownerRole.trim() || undefined,
        department_ids: departmentIds,
        employment_types: employmentTypes,
        acknowledgement_required: ackRequired,
        acceptance_due_days: acceptanceDueDays ? Number(acceptanceDueDays) : undefined,
      }, scope);
      if (file) {
        const uploaded = await readFile(file);
        await uploadPolicyDocument(policy.policy_key, uploaded, scope);
      }
      onSuccess('Policy registered.');
      onDone();
    } catch (err) {
      onError(err?.response?.data?.detail || err?.message || 'Could not register the policy.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="New policy" labelledBy="new-policy-title" onClose={onClose}
      subtitle="Category and applicability decide who sees this in their own HR Policy Library."
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Register'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="np-key">Key *</label>
          <input id="np-key" className={FIELD} value={policyKey}
            onChange={(e) => setPolicyKey(e.target.value)} placeholder="leave_policy" />
        </div>
        <div>
          <label className={LABEL} htmlFor="np-title">Title *</label>
          <input id="np-title" className={FIELD} value={title}
            onChange={(e) => setTitle(e.target.value)} placeholder="Leave Policy" />
        </div>
        <div>
          <label className={LABEL} htmlFor="np-category">Category</label>
          <input id="np-category" className={FIELD} value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Leave / Attendance / Conduct / …" />
        </div>
        <div>
          <label className={LABEL} htmlFor="np-owner">Owner role</label>
          <input id="np-owner" className={FIELD} value={ownerRole}
            onChange={(e) => setOwnerRole(e.target.value)} placeholder="HR" />
        </div>
        <div>
          <label className={LABEL} htmlFor="np-due">Acceptance due (days)</label>
          <input id="np-due" type="number" min="0" className={FIELD} value={acceptanceDueDays}
            onChange={(e) => setAcceptanceDueDays(e.target.value)} placeholder="e.g. 14" />
        </div>
      </div>

      <MultiCheck label="Departments (none selected = company-wide)" value={departmentIds}
        onChange={setDepartmentIds} options={departments}
        optionValue={(d) => d.id} optionLabel={(d) => d.name} />
      <MultiCheck label="Employment types (none selected = all)" value={employmentTypes}
        onChange={setEmploymentTypes} options={EMPLOYMENT_TYPES} />

      <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={ackRequired} onChange={(e) => setAckRequired(e.target.checked)} />
        Employees must acknowledge this policy
      </label>

      <div>
        <label className={LABEL} htmlFor="np-file">Policy document (PDF)</label>
        <input id="np-file" type="file" accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="block w-full text-[12px] text-[var(--text-muted)]" />
      </div>
    </Modal>
  );
};

const PolicyModal = ({
  policy, scope, busy, setBusy, canWrite, canApprove,
  onClose, onChanged, onSuccess, onError,
}) => {
  const [mode, setMode] = useState('history');
  const [version, setVersion] = useState('');
  const [summary, setSummary] = useState('');
  const [signature, setSignature] = useState('');
  const [approveVersion, setApproveVersion] = useState('');
  const [category, setCategory] = useState(policy.category || '');
  const [ackRequired, setAckRequired] = useState(!!policy.acknowledgement_required);
  const [acceptanceDueDays, setAcceptanceDueDays] = useState(policy.acceptance_due_days ?? '');
  const [departments, setDepartments] = useState([]);
  const [departmentIds, setDepartmentIds] = useState(policy.department_ids || []);
  const [employmentTypes, setEmploymentTypes] = useState(policy.employment_types || []);
  const [file, setFile] = useState(null);
  const [acks, setAcks] = useState(null);

  const pending = (policy.revisions || []).filter((r) => !r.approved_at);

  useEffect(() => {
    if (mode !== 'applicability' || departments.length) return;
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const saveApplicability = async () => {
    setBusy(true);
    try {
      await updatePolicyApplicability(policy.policy_key, {
        category: category.trim() || undefined,
        department_ids: departmentIds,
        employment_types: employmentTypes,
        acknowledgement_required: ackRequired,
        acceptance_due_days: acceptanceDueDays === '' ? undefined : Number(acceptanceDueDays),
      }, scope);
      if (file) {
        const uploaded = await readFile(file);
        await uploadPolicyDocument(policy.policy_key, uploaded, scope);
        setFile(null);
      }
      onSuccess('Applicability saved.');
      setMode('history');
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.detail || err?.message || 'Could not save applicability.');
    } finally {
      setBusy(false);
    }
  };

  const loadAcks = async () => {
    setMode('acknowledgements');
    try {
      const { data } = await getPolicyAcknowledgements(policy.policy_key, scope);
      setAcks(data);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not load acknowledgements.');
    }
  };

  const draft = async () => {
    setBusy(true);
    try {
      await logPolicyRevision(policy.policy_key,
        { version, summary_of_change: summary }, scope);
      onSuccess(`v${version} logged. It does not govern until it is approved.`);
      setMode('history');
      setVersion('');
      setSummary('');
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The revision could not be logged.');
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    try {
      await approvePolicyRevision(policy.policy_key,
        { version: approveVersion, signature }, scope);
      onSuccess(`v${approveVersion} is now the version in force.`);
      setMode('history');
      setSignature('');
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The revision could not be approved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={policy.title}
      subtitle={`v${policy.version} in force from ${day(policy.effective_date)}`}
      labelledBy="policy-open"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          {mode === 'draft' && (
            <Btn tone="primary" disabled={busy || !version.trim() || !summary.trim()}
              onClick={draft}>
              Log revision
            </Btn>
          )}
          {mode === 'approve' && (
            <Btn tone="primary"
              disabled={busy || !approveVersion || !signature.trim()} onClick={approve}>
              Approve
            </Btn>
          )}
          {mode === 'applicability' && (
            <Btn tone="primary" disabled={busy} onClick={saveApplicability}>
              {busy ? 'Saving…' : 'Save'}
            </Btn>
          )}
        </>
      )}
    >
      <Facts items={[
        { label: 'Key', value: policy.policy_key },
        { label: 'Owner', value: policy.owner_role },
        { label: 'Category', value: policy.category || '— company-wide —' },
        { label: 'Next review', value: day(policy.next_review_due) },
        { label: 'Status', value: policy.status },
      ]} />
      {policy.document_url && (
        <a href={policy.document_url} target="_blank" rel="noreferrer"
          className="inline-block text-[12px] font-bold text-[var(--accent-indigo)]">
          View policy document{policy.document_file_name ? ` (${policy.document_file_name})` : ''}
        </a>
      )}
      {policy.review_note && (
        <p className={`text-[12px] ${policy.review_status === 'overdue'
          ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
          {policy.review_note}
        </p>
      )}

      {mode === 'history' && (
        <>
          <div className="flex flex-wrap gap-2">
            {canWrite && <Btn onClick={() => setMode('draft')}>
              <Plus size={14} /> Log a revision
            </Btn>}
            {canApprove && !!pending.length && (
              <Btn tone="primary" onClick={() => {
                setMode('approve');
                setApproveVersion(pending[0].version);
              }}>
                Approve a revision
              </Btn>
            )}
            {canWrite && <Btn onClick={() => setMode('applicability')}>Applicability</Btn>}
            {canWrite && <Btn onClick={loadAcks}>Acknowledgements</Btn>}
          </div>

          <div>
            <p className={LABEL}>Modification history</p>
            {(policy.revisions || []).length ? (
              <ul className="space-y-2.5">
                {policy.revisions.map((r) => (
                  <li key={r.version}
                    className="rounded-lg border border-[var(--border)] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                        v{r.version}
                      </p>
                      <Chip tone={r.approved_at ? 'good' : 'warn'}>
                        {r.approved_at ? 'approved' : 'awaiting approval'}
                      </Chip>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                      {r.summary_of_change}
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                      Drafted by {r.changed_by_name} on {day(r.changed_at)}
                      {r.approved_at && ` · approved by ${r.approved_by_name} on ${day(r.approved_at)}`}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No amendments logged yet.
              </p>
            )}
          </div>
        </>
      )}

      {mode === 'draft' && (
        <>
          <div>
            <label className={LABEL} htmlFor="policy-version">New version *</label>
            <input id="policy-version" className={FIELD} value={version}
              onChange={(e) => setVersion(e.target.value)} placeholder="1.1" />
          </div>
          <div>
            <label className={LABEL} htmlFor="policy-summary">What changed *</label>
            <textarea id="policy-summary" rows={4} className={TEXTAREA} value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="A modification history that does not say what was modified is a list of dates." />
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Logging this changes nothing about which version governs. It comes into force
            when the MD approves it.
          </p>
        </>
      )}

      {mode === 'approve' && (
        <>
          <div>
            <label className={LABEL} htmlFor="policy-approve">Version *</label>
            <select id="policy-approve" className={FIELD} value={approveVersion}
              onChange={(e) => setApproveVersion(e.target.value)}>
              {pending.map((r) => (
                <option key={r.version} value={r.version}>
                  v{r.version} — {r.summary_of_change.slice(0, 60)}
                </option>
              ))}
            </select>
          </div>
          <SignatureField
            id="policy-signature"
            value={signature}
            onChange={setSignature}
            hint="This changes which version of the policy the company is held to."
          />
        </>
      )}

      {mode === 'applicability' && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="policy-category">Category</label>
              <input id="policy-category" className={FIELD} value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="Leave / Attendance / Conduct / …" />
            </div>
            <div>
              <label className={LABEL} htmlFor="policy-due">Acceptance due (days)</label>
              <input id="policy-due" type="number" min="0" className={FIELD}
                value={acceptanceDueDays} onChange={(e) => setAcceptanceDueDays(e.target.value)} />
            </div>
          </div>

          <MultiCheck label="Departments (none selected = company-wide)" value={departmentIds}
            onChange={setDepartmentIds} options={departments}
            optionValue={(d) => d.id} optionLabel={(d) => d.name} />
          <MultiCheck label="Employment types (none selected = all)" value={employmentTypes}
            onChange={setEmploymentTypes} options={EMPLOYMENT_TYPES} />

          <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
            <input type="checkbox" checked={ackRequired}
              onChange={(e) => setAckRequired(e.target.checked)} />
            Employees must acknowledge this policy
          </label>

          <div>
            <label className={LABEL} htmlFor="policy-file">
              {policy.document_url ? 'Replace policy document (PDF)' : 'Upload policy document (PDF)'}
            </label>
            <input id="policy-file" type="file" accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-[12px] text-[var(--text-muted)]" />
          </div>
        </>
      )}

      {mode === 'acknowledgements' && (
        <div>
          <p className={LABEL}>
            Acknowledged v{policy.version} ({acks?.total ?? '…'})
          </p>
          {!acks ? (
            <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
          ) : acks.acknowledgements.length ? (
            <ul className="space-y-1.5">
              {acks.acknowledgements.map((a) => (
                <li key={a.employee_code} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">{a.employee_name || a.employee_code}</span>
                  <span className="text-[11px] text-[var(--text-muted)]">{day(a.acknowledged_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12.5px] text-[var(--text-muted)]">No one has acknowledged this version yet.</p>
          )}
        </div>
      )}
    </Modal>
  );
};

export default PolicyRegister;
