import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RefreshCw, Building2, Plus, Pencil, Check, X, ShieldCheck, Power, PowerOff, Info, Lock,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, usePaged, Pager,
} from '../../common/dashboardKit';
import { getDepartments, createDepartment, updateDepartment } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Department Management (H5) — the department master.

   Two kinds of rows:
     • Governance roles (is_governance_role:true) — seeded, READ-ONLY. The API
       rejects edits with 400, so their edit / (de)activate controls are disabled.
     • Custom departments — admin-added (global or company-scoped). These can be
       renamed and soft-deactivated (never hard-deleted → active:false retires one).

   Route: /tpms/admin/departments   (wired separately)
   ───────────────────────────────────────────────────────────── */

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

const TypeBadge = ({ governance }) => (
  <span
    className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border"
    style={governance
      ? { color: 'var(--accent-indigo)', background: 'var(--accent-indigo-bg)', borderColor: 'var(--accent-indigo-border)' }
      : { color: 'var(--text-main)', background: 'var(--input-bg)', borderColor: 'var(--border)' }}
  >
    {governance ? <ShieldCheck size={12} /> : <Building2 size={12} />}
    {governance ? 'Governance role' : 'Custom'}
  </span>
);

const ActiveBadge = ({ active }) => (
  <span
    className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border"
    style={active
      ? { color: 'var(--accent-green)', background: 'var(--accent-green-bg)', borderColor: 'var(--accent-green-border)' }
      : { color: 'var(--text-muted)', background: 'var(--input-bg)', borderColor: 'var(--border)' }}
  >
    <span className="w-1.5 h-1.5 rounded-full" style={{ background: active ? 'var(--accent-green)' : 'var(--text-muted)' }} />
    {active ? 'Active' : 'Inactive'}
  </span>
);

const IconBtn = ({ icon: Icon, label, onClick, disabled, tone = 'plain' }) => {
  const tones = {
    plain:  { c: 'var(--text-main)',    bg: 'var(--input-bg)',           bd: 'var(--border)' },
    indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)',  bd: 'var(--accent-indigo-border)' },
    green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
    red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',     bd: 'var(--accent-red-border)' },
  };
  const s = tones[tone] || tones.plain;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold border transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-95"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}
    >
      {Icon && <Icon size={13} />} {label}
    </button>
  );
};

const DepartmentManagement = () => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Add form
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState('');

  // Inline rename
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');
  const [rowBusy, setRowBusy] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getDepartments();
      setItems(Array.isArray(res?.data?.items) ? res.data.items : []);
    } catch (e) {
      setError(errMsg(e, 'Failed to load departments'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (admin) load(); }, [admin, load]);

  const rows = useMemo(
    () => [...items].sort((a, b) => {
      const g = Number(!!b.is_governance_role) - Number(!!a.is_governance_role);
      if (g) return g;
      return String(a.name || '').toLowerCase().localeCompare(String(b.name || '').toLowerCase());
    }),
    [items],
  );

  const pRows = usePaged(rows || [], 10);

  const governanceCount = rows.filter((r) => r.is_governance_role).length;
  const customCount = rows.length - governanceCount;

  const handleAdd = async () => {
    const name = newName.trim();
    if (!name) { setAddError('Department name is required'); return; }
    setAddBusy(true);
    setAddError('');
    try {
      await createDepartment({ name }); // no company_id → global department
      setNewName('');
      setShowAdd(false);
      setNotice(`Department “${name}” added.`);
      await load();
    } catch (e) {
      setAddError(errMsg(e, 'Failed to add department'));
    } finally {
      setAddBusy(false);
    }
  };

  const startEdit = (row) => {
    setEditingId(row._id);
    setEditName(row.name || '');
    setNotice('');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditName('');
  };

  const saveEdit = async (row) => {
    const name = editName.trim();
    if (!name) { setError('Department name cannot be empty'); return; }
    if (name === row.name) { cancelEdit(); return; }
    setRowBusy(row._id);
    setError('');
    try {
      await updateDepartment(row._id, { name });
      setNotice(`Renamed to “${name}”.`);
      cancelEdit();
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to rename department'));
    } finally {
      setRowBusy(null);
    }
  };

  const toggleActive = async (row) => {
    const next = !(row.active !== false);
    setRowBusy(row._id);
    setError('');
    try {
      await updateDepartment(row._id, { active: next });
      setNotice(`“${row.name}” ${next ? 'activated' : 'deactivated'}.`);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to update department'));
    } finally {
      setRowBusy(null);
    }
  };

  if (!admin) {
    return (
      <div className="px-5 py-16 text-center">
        <span className="inline-flex w-11 h-11 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] items-center justify-center mb-3"><Lock size={20} /></span>
        <p className="text-[14px] font-extrabold">Admin access required</p>
        <p className="text-[12.5px] text-[var(--text-muted)] mt-1">Department Management is available to Admin / Super Admin only.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero
        icon={Building2}
        title="Department Management"
        subtitle="Governance roles & custom departments the doers are grouped by"
      >
        <HeroButton icon={Plus} onClick={() => { setShowAdd((v) => !v); setAddError(''); setNewName(''); }}>
          Add Department
        </HeroButton>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)] flex items-center justify-between gap-3">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice('')} aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      {/* Info banner */}
      <div className="rounded-2xl border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          <b>Governance roles</b> are seeded and read-only — they can’t be renamed or deactivated.
          Only <b>custom departments</b> can be edited. Deactivating a department retires it (soft delete, never removed).
        </p>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
          <p className="text-[12.5px] font-extrabold mb-2.5">New custom department</p>
          <div className="flex flex-wrap items-start gap-2.5">
            <div className="flex-1 min-w-[220px]">
              <input
                autoFocus
                type="text"
                value={newName}
                onChange={(e) => { setNewName(e.target.value); if (addError) setAddError(''); }}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') setShowAdd(false); }}
                placeholder="Department name (e.g. Sales, Operations, Finance)"
                className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-medium outline-none focus:border-[var(--accent-indigo)]"
              />
              {addError && <p className="text-[11px] font-bold text-[var(--accent-red)] mt-1.5">{addError}</p>}
              <p className="text-[10.5px] text-[var(--text-muted)] mt-1.5">Added as a global department (available to all companies).</p>
            </div>
            <button
              type="button"
              onClick={handleAdd}
              disabled={addBusy}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:brightness-110 transition-all disabled:opacity-50"
            >
              <Check size={14} /> {addBusy ? 'Adding…' : 'Add'}
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[12.5px] font-bold hover:brightness-95 transition-all"
            >
              <X size={14} /> Cancel
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      <Section
        title="Departments"
        subtitle={loading ? 'Loading…' : `${rows.length} total · ${governanceCount} governance · ${customCount} custom`}
        icon={Building2}
      >
        {loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading departments…</div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-14 text-center">
            <p className="text-[13px] font-bold text-[var(--text-muted)]">No departments found.</p>
            <p className="text-[12px] text-[var(--text-muted)] mt-1">Use “Add Department” to create your first custom department.</p>
          </div>
        ) : (
          <>
          <TableShell minWidth={840}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Scope</Th>
                <Th align="center">Active</Th>
                <Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pRows.pageRows.map((row, i) => {
                const governance = !!row.is_governance_role;
                const active = row.active !== false;
                const busy = rowBusy === row._id;
                const editing = editingId === row._id;
                const rowKey = row._id || `${row.name}-${i}`;
                return (
                  <tr key={rowKey} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className="font-bold">
                      {editing ? (
                        <input
                          autoFocus
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(row); if (e.key === 'Escape') cancelEdit(); }}
                          className="w-full max-w-[240px] px-2.5 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--accent-indigo)] text-[12.5px] font-bold outline-none"
                        />
                      ) : (
                        <span className="inline-flex items-center gap-2">
                          {row.name || '—'}
                          {governance && <Lock size={12} className="text-[var(--text-muted)]" />}
                        </span>
                      )}
                    </Td>
                    <Td><TypeBadge governance={governance} /></Td>
                    <Td className="text-[var(--text-muted)] font-medium">
                      {row.company_id
                        ? <span className="inline-flex items-center gap-1.5"><Building2 size={12} /> Company-specific</span>
                        : <span className="inline-flex items-center gap-1.5"><ShieldCheck size={12} /> Global</span>}
                    </Td>
                    <Td align="center"><ActiveBadge active={active} /></Td>
                    <Td align="right">
                      {governance ? (
                        <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--text-muted)]">
                          <Lock size={12} /> Read-only
                        </span>
                      ) : editing ? (
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          <IconBtn icon={Check} label={busy ? 'Saving…' : 'Save'} tone="green" onClick={() => saveEdit(row)} disabled={busy} />
                          <IconBtn icon={X} label="Cancel" onClick={cancelEdit} disabled={busy} />
                        </div>
                      ) : (
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          <IconBtn icon={Pencil} label="Edit" tone="indigo" onClick={() => startEdit(row)} disabled={busy} />
                          {active ? (
                            <IconBtn icon={PowerOff} label="Deactivate" tone="red" onClick={() => toggleActive(row)} disabled={busy} />
                          ) : (
                            <IconBtn icon={Power} label="Activate" tone="green" onClick={() => toggleActive(row)} disabled={busy} />
                          )}
                        </div>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          <Pager {...pRows} label="departments" />
          </>
        )}
      </Section>
    </div>
  );
};

export default DepartmentManagement;
