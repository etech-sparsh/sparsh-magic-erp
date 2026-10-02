import React, { useCallback, useEffect, useState } from 'react';
import { BookMarked, CheckCircle2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getMyPolicies, acknowledgePolicy } from '../../../services/hrmsApi';
import { Btn, Chip, Facts, RecordList } from '../internal/internalKit.jsx';
import { day } from '../internal/internalKit';

/**
 * HRMS ▸ HR Policy Library (§22.6, screen SM-HR-062).
 *
 * Every published policy applicable to the current user, with their own acknowledgement
 * status for its CURRENT version. Separate from the HR-side Policy Register (that screen
 * administers the register; this one is what every employee sees of it).
 */
const PolicyLibrary = () => {
  const { scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [acking, setAcking] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getMyPolicies(scope);
      setRows(data?.policies || []);
      setPending(data?.pending_acknowledgement ?? 0);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the policy library.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const acknowledge = async (policyKey) => {
    setAcking(policyKey);
    try {
      await acknowledgePolicy(policyKey, scope);
      showSuccess('Acknowledged.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record your acknowledgement.');
    } finally {
      setAcking(null);
    }
  };

  const columns = [
    { key: 'title', label: 'Policy', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.title}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.category || 'Company-wide'} · v{r.version}</span>
        {r.document_url && (
          <a href={r.document_url} target="_blank" rel="noreferrer"
            className="block text-[11px] font-bold text-[var(--accent-indigo)]">
            View document
          </a>
        )}
      </>
    ) },
    { key: 'effective', label: 'Effective', render: (r) => day(r.effective_date) },
    { key: 'status', label: '', align: 'right', render: (r) => (
      r.acknowledged ? (
        <Chip tone="good"><CheckCircle2 size={12} className="inline -mt-0.5 mr-1" />Acknowledged</Chip>
      ) : r.acknowledgement_required ? (
        <Btn tone="primary" disabled={acking === r.policy_key} onClick={() => acknowledge(r.policy_key)}>
          {acking === r.policy_key ? 'Working…' : 'Acknowledge'}
        </Btn>
      ) : (
        <Chip tone="neutral">No action needed</Chip>
      )
    ) },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BookMarked}
        title="HR Policy Library"
        subtitle="Every policy that applies to you, and whether you still need to acknowledge it."
      />
      <HrmsScopeBar />

      {pending > 0 && (
        <div className="rounded-xl px-4 py-3 border border-[var(--accent-orange)]/30 bg-[var(--accent-orange-bg)]">
          <p className="text-[12.5px] font-semibold text-[var(--accent-orange)]">
            {pending} polic{pending === 1 ? 'y needs' : 'ies need'} your acknowledgement.
          </p>
        </div>
      )}

      {loading && <HrmsLoading label="Loading policies…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty icon={BookMarked} title="No policies apply to you yet" />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.policy_key}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <p className="font-semibold text-[13px] text-[var(--text-main)]">{r.title}</p>
              <Facts items={[
                { label: 'Category', value: r.category || 'Company-wide' },
                { label: 'Version', value: `v${r.version}` },
                { label: 'Effective', value: day(r.effective_date) },
              ]} />
              {r.acknowledged ? (
                <Chip tone="good">Acknowledged</Chip>
              ) : r.acknowledgement_required ? (
                <Btn tone="primary" disabled={acking === r.policy_key} onClick={() => acknowledge(r.policy_key)}>
                  {acking === r.policy_key ? 'Working…' : 'Acknowledge'}
                </Btn>
              ) : (
                <Chip tone="neutral">No action needed</Chip>
              )}
            </div>
          )}
        />
      )}
    </div>
  );
};

export default PolicyLibrary;
