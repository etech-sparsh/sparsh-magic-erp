import React, { useCallback, useEffect, useState } from 'react';
import { FileCog, Plus, Trash2, X } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getDocumentTypes, createDocumentType, updateDocumentType, deleteDocumentType,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ the document-type master (Phase 11-R, Item 2).
 *
 * Sits alongside Departments and Designations as company reference data. A sensible Indian
 * HR default set is seeded by the server on first read, so a new company is usable
 * immediately; everything in it is editable and nothing is mandatory to keep.
 *
 * Deletion is refused while any document references a type — the API says how many, and
 * offers deactivation as the non-destructive alternative. Same rule the department master
 * applies, and for the same reason: a Mongo deployment has no foreign keys, so referential
 * integrity is enforced here or nowhere.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const CATEGORIES = ['Identity', 'Educational', 'Employment', 'Statutory', 'PSC', 'Company Issued', 'Other'];
const APPLIES = [['both', 'Both'], ['candidate', 'Candidates'], ['employee', 'Employees']];

const EMPTY = {
  name: '', code: '', category: 'Other', applies_to: 'both',
  mandatory: false, expires: false, active: true,
};

const DocumentTypeManager = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const canWrite = can(CAP.DOCUMENT_WRITE);
  const set = (k) => (e) => setForm((f) => ({
    ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value,
  }));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getDocumentTypes({ ...scope, include_inactive: true });
      setRows(data?.document_types || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load document types.');
    } finally {
      setLoading(false);
    }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const openNew = () => { setForm(EMPTY); setEditing('new'); };
  const openEdit = (row) => { setForm({ ...EMPTY, ...row }); setEditing(row.id); };

  const save = async () => {
    if (!form.name.trim()) {
      showError('Give the document type a name.');
      return;
    }
    setSaving(true);
    try {
      if (editing === 'new') {
        await createDocumentType(form, scope);
        showSuccess('Document type created.');
      } else {
        await updateDocumentType(editing, form, scope);
        showSuccess('Document type updated.');
      }
      setEditing(null);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the document type.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    try {
      await deleteDocumentType(row.id, scope);
      showSuccess(`'${row.name}' was deleted.`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete the document type.');
    }
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={FileCog}
        title="Document Types"
        subtitle="The checklist every employee and candidate is measured against"
        actions={canWrite && (
          <button
            type="button"
            onClick={openNew}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold flex items-center gap-1.5"
          >
            <Plus size={14} />
            Add type
          </button>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading document types…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={FileCog}
          title="No document types yet"
          hint="A default set is created the first time this screen is opened. Add your own to extend it."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[720px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Name</th>
                <th className="text-left px-4 py-2.5">Category</th>
                <th className="text-left px-4 py-2.5">Applies to</th>
                <th className="text-left px-4 py-2.5">Required</th>
                <th className="text-left px-4 py-2.5">Expires</th>
                <th className="text-left px-4 py-2.5">Active</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-main)]">{row.name}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.category}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {APPLIES.find(([v]) => v === row.applies_to)?.[1] || row.applies_to}
                  </td>
                  <td className="px-4 py-2.5">{row.mandatory ? 'Yes' : '—'}</td>
                  <td className="px-4 py-2.5">{row.expires ? 'Yes' : '—'}</td>
                  <td className="px-4 py-2.5">
                    {row.active
                      ? <span className="text-[var(--accent-green,var(--accent-indigo))] font-semibold">Active</span>
                      : <span className="text-[var(--text-muted)]">Inactive</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      {canWrite && (
                        <button
                          type="button"
                          onClick={() => openEdit(row)}
                          className="h-7 px-2.5 rounded-lg border border-[var(--border)] text-[11px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)]"
                        >
                          Edit
                        </button>
                      )}
                      {canWrite && (
                        <button
                          type="button"
                          onClick={() => remove(row)}
                          title="Delete"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]"
                        >
                          <Trash2 size={13} />
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

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                {editing === 'new' ? 'Add document type' : 'Edit document type'}
              </h2>
              <button type="button" onClick={() => setEditing(null)} className="text-[var(--text-muted)]">
                <X size={17} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className={LABEL}>Name</label>
                <input className={FIELD} value={form.name} onChange={set('name')} />
              </div>
              <div>
                <label className={LABEL}>Category</label>
                <select className={FIELD} value={form.category} onChange={set('category')}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>Applies to</label>
                <select className={FIELD} value={form.applies_to} onChange={set('applies_to')}>
                  {APPLIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className={LABEL}>Code (optional)</label>
                <input className={FIELD} value={form.code || ''} onChange={set('code')} />
              </div>
            </div>

            <div className="flex flex-wrap gap-4 pt-1">
              {[['mandatory', 'Mandatory'], ['expires', 'Has an expiry date'], ['active', 'Active']].map(
                ([key, label]) => (
                  <label key={key} className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
                    <input type="checkbox" checked={!!form[key]} onChange={set(key)} />
                    {label}
                  </label>
                ),
              )}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DocumentTypeManager;
