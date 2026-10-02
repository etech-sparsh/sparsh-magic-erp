import React, { useCallback, useEffect, useState } from 'react';
import { FolderOpen, Search, Download, AlertTriangle, Users, UserCircle } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getDocuments, getDocumentTypes, getDocumentUrl } from '../../../services/hrmsApi';
import DocumentPanel from './DocumentPanel';

/**
 * HRMS ▸ the document register (Phase 11-R, Item 2).
 *
 * The company-wide view: every document, filterable by owner kind, type, status and
 * expiry. Selecting a row opens that person's full checklist in the shared DocumentPanel —
 * the same component the employee profile and candidate journey mount, so there is one
 * upload/verify surface rather than three.
 *
 * Status and expiry are computed SERVER-side. This screen renders what the API says and
 * never re-derives "is this expired", which is how the two would drift.
 */

const FIELD = 'h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';

const STATUS_TONE = {
  Pending: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Uploaded: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  'Under Review': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Verified: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Rejected: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Expired: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

const Tile = ({ label, value, tone }) => (
  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
    <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
    <p className={`text-[22px] font-bold tracking-tight mt-1 ${tone || 'text-[var(--text-main)]'}`}>{value}</p>
  </div>
);

const DocumentCenter = () => {
  const { scope, companyId } = useHrms();
  const { showError } = useNotification();

  const [ownerType, setOwnerType] = useState('employee');
  const [filters, setFilters] = useState({ status: '', type_id: '', search: '', expiring: false });
  const [data, setData] = useState(null);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { ...scope, owner_type: ownerType };
      if (filters.status) params.status = filters.status;
      if (filters.type_id) params.type_id = filters.type_id;
      if (filters.search) params.search = filters.search;
      if (filters.expiring) params.expiring_soon = true;
      const [{ data: payload }, { data: typeList }] = await Promise.all([
        getDocuments(params),
        getDocumentTypes({ ...scope, applies_to: ownerType }),
      ]);
      setData(payload);
      setTypes(typeList?.document_types || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the document register.');
    } finally {
      setLoading(false);
    }
  }, [companyId, ownerType, filters.status, filters.type_id, filters.search, filters.expiring]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const open = async (docNo) => {
    try {
      const { data: url } = await getDocumentUrl(docNo, scope);
      window.open(url.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open the document.');
    }
  };

  const rows = data?.documents || [];
  const stats = data?.stats || {};

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={FolderOpen}
        title="Documents"
        subtitle="Every employee and candidate document, with its status, version history and expiry"
      />
      <HrmsScopeBar />

      {data?.scoped_to_own_requisitions && (
        <p className="text-[12px] text-[var(--text-muted)]">
          Showing documents for candidates on requisitions you raised.
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Tile label="Uploaded" value={stats.uploaded ?? 0} tone="text-[var(--accent-indigo)]" />
        <Tile label="Under review" value={stats.under_review ?? 0} />
        <Tile label="Verified" value={stats.verified ?? 0} tone="text-[var(--accent-green,var(--accent-indigo))]" />
        <Tile label="Rejected" value={stats.rejected ?? 0} tone="text-[var(--accent-red)]" />
        <Tile label="Expired" value={stats.expired ?? 0} tone="text-[var(--accent-red)]" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-[var(--border)] overflow-hidden">
          {[['employee', 'Employees', Users], ['candidate', 'Candidates', UserCircle]].map(
            ([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                onClick={() => { setOwnerType(value); setSelected(null); }}
                className={`h-9 px-3.5 flex items-center gap-1.5 text-[12px] font-bold transition-colors ${
                  ownerType === value
                    ? 'bg-[var(--accent-indigo)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                }`}
              >
                <Icon size={13} />
                {label}
              </button>
            ),
          )}
        </div>

        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className={`${FIELD} pl-8 w-56`}
            placeholder="Name, id or document"
            value={filters.search}
            onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
          />
        </div>

        <select
          className={FIELD}
          value={filters.type_id}
          onChange={(e) => setFilters((f) => ({ ...f, type_id: e.target.value }))}
        >
          <option value="">All types</option>
          {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>

        <select
          className={FIELD}
          value={filters.status}
          onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
        >
          <option value="">All statuses</option>
          {['Uploaded', 'Under Review', 'Verified', 'Rejected', 'Expired'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => setFilters((f) => ({ ...f, expiring: !f.expiring }))}
          className={`h-9 px-3 rounded-lg border text-[12px] font-bold flex items-center gap-1.5 transition-colors ${
            filters.expiring
              ? 'border-[var(--accent-red)] text-[var(--accent-red)] bg-[var(--accent-red-bg)]'
              : 'border-[var(--border)] text-[var(--text-muted)]'
          }`}
        >
          <AlertTriangle size={13} />
          Expiring soon
        </button>
      </div>

      {loading && <HrmsLoading label="Loading documents…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={FolderOpen}
          title="No documents yet"
          hint="Open a person from the directory or the pipeline to upload their paperwork against the checklist."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[820px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Owner</th>
                <th className="text-left px-4 py-2.5">Document</th>
                <th className="text-left px-4 py-2.5">Status</th>
                <th className="text-left px-4 py-2.5">Version</th>
                <th className="text-left px-4 py-2.5">Expires</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.doc_no} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => setSelected({ id: row.owner_id, name: row.owner_name })}
                      className="font-semibold text-[var(--accent-indigo)] hover:underline text-left"
                    >
                      {row.owner_name || row.owner_id}
                    </button>
                    <span className="block text-[11px] text-[var(--text-muted)]">{row.owner_id}</span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">
                    {row.type_name}
                    <span className="block text-[11px] text-[var(--text-muted)]">{row.doc_no}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-bold ${STATUS_TONE[row.status] || ''}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">v{row.current_version ?? 1}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.expiry_date || '—'}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => open(row.doc_no)}
                      title="Open"
                      className="h-7 w-7 rounded-lg border border-[var(--border)] inline-flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)]"
                    >
                      <Download size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-y-auto">
          <div className="w-full max-w-3xl my-8 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                Documents — {selected.name || selected.id}
              </h2>
              <button
                type="button"
                onClick={() => { setSelected(null); load(); }}
                className="h-8 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]"
              >
                Close
              </button>
            </div>
            <DocumentPanel
              ownerType={ownerType}
              ownerId={selected.id}
              ownerName={selected.name}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default DocumentCenter;
