import React, { useCallback, useEffect, useState } from 'react';
import { Gauge, Plus, Trash2, X, AlertTriangle } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getSanctionedStrength, setSanctionedStrength, deleteSanctionedStrength,
  getDepartments, getDesignations,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ sanctioned strength (Phase 11-R, Item 7).
 *
 * The authorised headcount per department + designation, and the live comparison against
 * it.
 *
 * `Sanctioned` is a decision somebody made, so it is stored. `Actual` is a fact about the
 * world, so it is COUNTED from employee profiles on every read and never stored — a stored
 * figure would be wrong the moment somebody resigned, and "somebody resigned, can we
 * backfill" is exactly the question this screen exists to answer.
 *
 * `Committed` counts seats already taken by approved, still-open requisitions. Leaving them
 * out would let five requisitions for one seat each pass the check independently.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const Tile = ({ label, value, tone }) => (
  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
    <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
    <p className={`text-[22px] font-bold tracking-tight mt-1 ${tone || 'text-[var(--text-main)]'}`}>{value}</p>
  </div>
);

const SanctionedStrength = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    department_id: '', designation_id: '', sanctioned_count: '', effective_from: '', notes: '',
  });

  const canWrite = can(CAP.SANCTION_WRITE);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [{ data: payload }, { data: depts }, { data: desigs }] = await Promise.all([
        getSanctionedStrength(scope),
        getDepartments(scope),
        getDesignations(scope),
      ]);
      setData(payload);
      setDepartments(depts?.departments || []);
      setDesignations(desigs?.designations || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load sanctioned strength.');
    } finally {
      setLoading(false);
    }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.department_id || !form.designation_id) {
      showError('Choose both a department and a designation.');
      return;
    }
    if (form.sanctioned_count === '') {
      showError('Enter the sanctioned headcount.');
      return;
    }
    setSaving(true);
    try {
      await setSanctionedStrength(
        { ...form, sanctioned_count: Number(form.sanctioned_count) }, scope,
      );
      showSuccess('Sanctioned strength saved.');
      setAdding(false);
      setForm({
        department_id: '', designation_id: '', sanctioned_count: '',
        effective_from: '', notes: '',
      });
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the sanctioned figure.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    try {
      const { data: result } = await deleteSanctionedStrength(row.id, scope);
      showSuccess(result?.note || 'Removed.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not remove the figure.');
    }
  };

  const rows = data?.sanctions || [];
  const stats = data?.stats || {};

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Gauge}
        title="Sanctioned Strength"
        subtitle="Authorised headcount per position, against the live actual"
        actions={canWrite && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold flex items-center gap-1.5"
          >
            <Plus size={14} />
            Set a figure
          </button>
        )}
      />
      <HrmsScopeBar />

      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 flex items-start gap-2.5">
        <AlertTriangle size={15} className="text-[var(--accent-indigo)] shrink-0 mt-0.5" />
        <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
          A position with <b className="text-[var(--text-main)]">no sanctioned figure</b> is
          treated as over-sanction: requisitions for it are routed through the escalation
          chain before they reach the MD. That is deliberate — a headcount nobody has
          authorised is exactly the case worth escalating.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Tile label="Positions" value={stats.positions ?? 0} />
        <Tile label="Sanctioned" value={stats.sanctioned ?? 0} tone="text-[var(--accent-indigo)]" />
        <Tile label="Actual" value={stats.actual ?? 0} />
        <Tile label="Over sanction" value={stats.over_sanction ?? 0} tone="text-[var(--accent-red)]" />
      </div>

      {loading && <HrmsLoading label="Loading sanctioned strength…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={Gauge}
          title="No sanctioned figures set"
          hint="Until a position has a figure, every requisition raised for it will be escalated. Set the authorised headcount per department and designation."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[820px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Department</th>
                <th className="text-left px-4 py-2.5">Designation</th>
                <th className="text-right px-4 py-2.5">Sanctioned</th>
                <th className="text-right px-4 py-2.5">Actual</th>
                <th className="text-right px-4 py-2.5">Committed</th>
                <th className="text-right px-4 py-2.5">Available</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className={`border-b border-[var(--border)] last:border-0 ${
                    row.is_over_sanction ? 'bg-[var(--accent-red-bg)]/30' : ''
                  }`}
                >
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-main)]">
                    {row.department_name}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{row.designation_name}</td>
                  <td className="px-4 py-2.5 text-right font-bold text-[var(--text-main)]">
                    {row.sanctioned_count}
                  </td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-main)]">{row.actual}</td>
                  <td className="px-4 py-2.5 text-right text-[var(--text-muted)]">
                    {row.open_requisitions}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-bold ${
                    row.is_over_sanction ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'
                  }`}>
                    {row.available ?? '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {canWrite && (
                      <button
                        type="button"
                        onClick={() => remove(row)}
                        title="Remove"
                        className="h-7 w-7 rounded-lg border border-[var(--border)] inline-flex items-center justify-center text-[var(--accent-red)]"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {adding && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                Set sanctioned strength
              </h2>
              <button type="button" onClick={() => setAdding(false)} className="text-[var(--text-muted)]">
                <X size={17} />
              </button>
            </div>

            <div>
              <label className={LABEL}>Department</label>
              <select className={FIELD} value={form.department_id} onChange={set('department_id')}>
                <option value="">Choose…</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL}>Designation</label>
              <select className={FIELD} value={form.designation_id} onChange={set('designation_id')}>
                <option value="">Choose…</option>
                {designations.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={LABEL}>Sanctioned count</label>
                <input
                  type="number"
                  min="0"
                  className={FIELD}
                  value={form.sanctioned_count}
                  onChange={set('sanctioned_count')}
                />
              </div>
              <div>
                <label className={LABEL}>Effective from</label>
                <input type="date" className={FIELD} value={form.effective_from} onChange={set('effective_from')} />
              </div>
            </div>
            <div>
              <label className={LABEL}>Notes</label>
              <textarea
                className="w-full h-16 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
                value={form.notes}
                onChange={set('notes')}
              />
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setAdding(false)}
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

export default SanctionedStrength;
