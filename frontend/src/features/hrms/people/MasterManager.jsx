import React, { useCallback, useEffect, useState } from 'react';
import { Building2, Plus, Pencil, Trash2, Check, X, Lightbulb } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getDepartments, createDepartment, updateDepartment, deleteDepartment,
  getDesignations, createDesignation, updateDesignation, deleteDesignation,
  getMasterSuggestions,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ department / designation master.
 *
 * One component drives both masters — they have identical shape, so two near-identical
 * screens would be pure duplication. `kind` selects the API set and the copy.
 *
 * The "Suggestions" panel reads the distinct values already present on the company's users
 * and offers them for one-click creation. It deliberately does NOT auto-create: the live
 * directory contains 'ACCOUNT', 'Accounts', 'Account & Finance' and 'Accounts & Finance'
 * as separate values, so importing blindly would promote that mess into the master. HR
 * decides which spelling wins.
 */

/**
 * The SOP's seniority bands, mirroring DesignationLevel in models/hrms.py.
 *
 * This is not decoration. Two rules are stated in terms of it: who must sit on an
 * interview panel, and whether a candidate needs the Management final round before they
 * can be selected. Leaving it unset reads as "mid", which silently means no final round --
 * so a managerial role that nobody banded is a managerial role hired without one.
 */
const SENIORITY = [
  ['', 'Not set (treated as mid)'],
  ['junior', 'Junior'],
  ['mid', 'Mid'],
  ['senior', 'Senior \u2014 needs the Management final round'],
  ['managerial', 'Managerial \u2014 needs the Management final round'],
];

const SENIORITY_LABEL = Object.fromEntries(SENIORITY.map(([v, l]) => [v, l]));

const API = {
  department: {
    list: getDepartments, create: createDepartment, update: updateDepartment, remove: deleteDepartment,
    key: 'departments', label: 'Department', plural: 'Departments',
    blurb: 'Departments group your people and drive requisitions, reporting and payroll.',
  },
  designation: {
    list: getDesignations, create: createDesignation, update: updateDesignation, remove: deleteDesignation,
    key: 'designations', label: 'Designation', plural: 'Designations',
    blurb: 'Designations are the job titles you hire and promote into.',
  },
};

const MasterManager = ({ kind = 'department' }) => {
  const cfg = API[kind];
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [newName, setNewName] = useState('');
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const canWrite = can(kind === 'department' ? CAP.DEPARTMENT_WRITE : CAP.DESIGNATION_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await cfg.list({ ...scope, include_inactive: true });
      setRows(data?.[cfg.key] || []);
    } catch (err) {
      setError(err?.response?.data?.detail || `Could not load ${cfg.plural.toLowerCase()}.`);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, kind]);

  useEffect(() => { load(); }, [load]);

  const loadSuggestions = async () => {
    try {
      const { data } = await getMasterSuggestions(scope);
      setSuggestions(data?.[cfg.key] || []);
      setShowSuggestions(true);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not load suggestions.');
    }
  };

  const add = async (name) => {
    const value = (name ?? newName).trim();
    if (!value) return showError(`Enter a ${cfg.label.toLowerCase()} name.`);
    setSaving(true);
    try {
      await cfg.create({ name: value, active: true }, scope);
      showSuccess(`${cfg.label} "${value}" added`);
      setNewName('');
      setSuggestions((s) => s.map((x) => (x.name === value ? { ...x, exists: true } : x)));
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || `Could not add the ${cfg.label.toLowerCase()}.`);
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async (row) => {
    const value = editName.trim();
    if (!value) return showError(`${cfg.label} name is required.`);
    try {
      await cfg.update(row.id, { name: value }, scope);
      showSuccess(`${cfg.label} renamed`);
      setEditingId(null);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the change.');
    }
  };

  const setSeniority = async (row, value) => {
    try {
      await cfg.update(row.id, { designation_level: value || null }, scope);
      showSuccess(`${row.name} set to ${SENIORITY_LABEL[value] || 'not set'}`);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not set the seniority band.');
    }
  };

  const toggleActive = async (row) => {
    try {
      await cfg.update(row.id, { active: !row.active }, scope);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update.');
    }
  };

  const remove = async (row) => {
    // The server refuses with a 409 that names how many employees block the delete; that
    // message is more useful than anything we could compose here, so we surface it verbatim.
    if (!window.confirm(`Delete ${cfg.label.toLowerCase()} "${row.name}"?`)) return;
    try {
      await cfg.remove(row.id, scope);
      showSuccess(`${cfg.label} deleted`);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  if (loading) return <HrmsLoading label={`Loading ${cfg.plural.toLowerCase()}…`} />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Building2}
        title={cfg.plural}
        subtitle={cfg.blurb}
        actions={<HrmsScopeBar />}
      />

      {canWrite && (
        <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && add()}
              placeholder={`New ${cfg.label.toLowerCase()} name`}
              className="flex-1 min-w-[200px] h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
            />
            <button
              type="button" onClick={() => add()} disabled={saving || !newName.trim()}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50"
            >
              <Plus size={14} /> Add
            </button>
            <button
              type="button" onClick={showSuggestions ? () => setShowSuggestions(false) : loadSuggestions}
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5"
            >
              <Lightbulb size={14} /> {showSuggestions ? 'Hide' : 'Suggest from directory'}
            </button>
          </div>

          {showSuggestions && (
            <div className="pt-3 border-t border-[var(--border)]">
              <p className="text-[11.5px] text-[var(--text-muted)] mb-2">
                Values already used on this company&apos;s user records. Nothing is created
                until you click one — review the spellings first, several may mean the same thing.
              </p>
              {suggestions.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)]">No values found on user records.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.map((s) => (
                    <button
                      key={s.name} type="button" disabled={s.exists} onClick={() => add(s.name)}
                      title={s.exists ? 'Already added' : `Add "${s.name}"`}
                      className={`px-2.5 py-1 rounded-lg text-[11.5px] font-semibold border transition-colors ${
                        s.exists
                          ? 'border-[var(--border)] text-[var(--text-muted)] opacity-50 cursor-not-allowed'
                          : 'border-[var(--accent-indigo)] text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]'
                      }`}
                    >
                      {s.name} <span className="opacity-60">({s.count})</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {kind === 'designation' && rows.length > 0 && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          <b>Seniority</b> drives two SOP rules: who must sit on the interview panel, and
          whether a candidate needs the Management final round before they can be selected.
          A designation left unset is treated as mid, which means no final round.
        </p>
      )}

      {rows.length === 0 ? (
        <HrmsEmpty
          icon={Building2}
          title={`No ${cfg.plural.toLowerCase()} yet`}
          hint={canWrite ? `Add your first ${cfg.label.toLowerCase()} above.` : undefined}
        />
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-hidden">
          <table className="w-full text-[13px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                <th className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{cfg.label}</th>
                {kind === 'designation' && (
                  <th className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest w-64">
                    Seniority
                  </th>
                )}
                <th className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest w-28">Status</th>
                {canWrite && <th className="px-4 py-2.5 w-28" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2.5">
                    {editingId === r.id ? (
                      <input
                        autoFocus value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveEdit(r);
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        className="h-8 px-2 w-full rounded-lg border border-[var(--accent-indigo)] bg-[var(--input-bg)] text-[13px]"
                      />
                    ) : (
                      <span className="font-semibold text-[var(--text-main)]">{r.name}</span>
                    )}
                  </td>
                  {kind === 'designation' && (
                    <td className="px-4 py-2.5">
                      <select
                        value={r.designation_level || ''} disabled={!canWrite}
                        onChange={(e) => setSeniority(r, e.target.value)}
                        aria-label={`Seniority band for ${r.name}`}
                        className="h-8 px-2 w-full rounded-lg border border-[var(--border)]
                          bg-[var(--input-bg)] text-[12px] text-[var(--text-main)]
                          disabled:opacity-50"
                      >
                        {SENIORITY.map(([value, label]) => (
                          <option key={value || 'unset'} value={value}>{label}</option>
                        ))}
                      </select>
                    </td>
                  )}
                  <td className="px-4 py-2.5">
                    <button
                      type="button" disabled={!canWrite} onClick={() => toggleActive(r)}
                      className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
                        r.active
                          ? 'bg-[var(--accent-green-bg,var(--input-bg))] text-[var(--accent-green,var(--text-main))]'
                          : 'bg-[var(--input-bg)] text-[var(--text-muted)]'
                      }`}
                    >
                      {r.active ? 'Active' : 'Inactive'}
                    </button>
                  </td>
                  {canWrite && (
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        {editingId === r.id ? (
                          <>
                            <button type="button" onClick={() => saveEdit(r)} className="p-1.5 rounded-lg text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]" title="Save"><Check size={15} /></button>
                            <button type="button" onClick={() => setEditingId(null)} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]" title="Cancel"><X size={15} /></button>
                          </>
                        ) : (
                          <>
                            <button type="button" onClick={() => { setEditingId(r.id); setEditName(r.name); }} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]" title="Rename"><Pencil size={15} /></button>
                            <button type="button" onClick={() => remove(r)} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]" title="Delete"><Trash2 size={15} /></button>
                          </>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default MasterManager;
