import React, { useCallback, useEffect, useState } from 'react';
import { ScrollText, Download } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getHrmsAudit } from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Audit Viewer (SM-HR-052).
 *
 * The audit trail itself (hrms_audit_log) and its read API (GET /hrms/audit, gated on the
 * existing Cap.AUDIT_READ) both already existed — every write path in this module has
 * called audit() since Phase 1. What was missing was a screen: the frontend API wrapper
 * (getHrmsAudit) was written but never called by any page. This is that page.
 */

const AuditViewer = () => {
  const { scope, companyId } = useHrms();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [entity, setEntity] = useState('');
  const [entityId, setEntityId] = useState('');

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getHrmsAudit({
        ...scope, limit: 200,
        entity: entity.trim() || undefined,
        entity_id: entityId.trim() || undefined,
      });
      setRows(data?.audit || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the audit trail.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, entity, entityId]);

  useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    if (!rows.length) return;
    const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const headers = ['created_at', 'actor_name', 'action', 'entity', 'entity_id', 'detail'];
    const csv = [headers, ...rows.map((r) => headers.map((h) => r[h]))]
      .map((r) => r.map(escape).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `hrms-audit-trail-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const columns = [
    { key: 'when', label: 'When', render: (r) => (
      <span className="text-[var(--text-main)] whitespace-nowrap">
        {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
      </span>
    ) },
    { key: 'actor', label: 'Actor', render: (r) => (
      <span className="text-[var(--text-main)]">{r.actor_name || 'system'}</span>
    ) },
    { key: 'action', label: 'Action', render: (r) => (
      <span className="text-[var(--text-main)]">{r.action}</span>
    ) },
    { key: 'entity', label: 'Entity', render: (r) => (
      <>
        <span className="text-[var(--text-main)]">{r.entity}</span>
        {r.entity_id && <span className="block text-[11px] text-[var(--text-muted)]">{r.entity_id}</span>}
      </>
    ) },
    { key: 'detail', label: 'Detail', render: (r) => (
      <span className="text-[var(--text-main)]">{r.detail || '—'}</span>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={ScrollText}
        title="Audit Viewer"
        subtitle="Every write this module has made, newest first (SM-HR-052)."
        actions={(
          <Btn tone="ghost" onClick={exportCsv} disabled={!rows.length}>
            <Download size={14} /> Export CSV
          </Btn>
        )}
      />
      <HrmsScopeBar />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
        <div>
          <label className={LABEL} htmlFor="audit-entity">Entity</label>
          <input id="audit-entity" value={entity} className={FIELD}
            placeholder="e.g. separation, pip_record, discipline_case"
            onChange={(e) => setEntity(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="audit-entity-id">Entity ID</label>
          <input id="audit-entity-id" value={entityId} className={FIELD}
            placeholder="e.g. SEP-2026-001"
            onChange={(e) => setEntityId(e.target.value)} />
        </div>
      </div>

      {loading && <HrmsLoading label="Loading audit trail…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-1.5">
                <p className="text-[11px] text-[var(--text-muted)]">
                  {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                </p>
                <p className="text-[13px] font-bold text-[var(--text-main)]">{r.action}</p>
                <p className="text-[12px] text-[var(--text-muted)]">
                  {r.actor_name || 'system'} · {r.entity}{r.entity_id ? ` · ${r.entity_id}` : ''}
                </p>
                {r.detail && <p className="text-[12px] text-[var(--text-main)]">{r.detail}</p>}
              </div>
            )}
            keyOf={(r) => r._id} />
        ) : (
          <HrmsEmpty icon={ScrollText} title="No audit entries match this filter" />
        )
      )}
    </div>
  );
};

export default AuditViewer;
