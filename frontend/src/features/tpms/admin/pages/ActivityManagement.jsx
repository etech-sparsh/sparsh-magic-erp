import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, ListChecks, Plus, Pencil, X, ShieldAlert, Layers,
  CheckCircle2, PauseCircle, PlayCircle, AlertTriangle,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, KpiTile, usePaged, Pager,
} from '../../common/dashboardKit';
import { getActivities, createActivity, updateActivity } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Activity Management (H4) — the activity catalogue.

   Full CRUD over the master activity list. "Delete" is a soft
   deactivate (updateActivity({active:false})) — there is no hard
   delete, so deactivated rows stay visible and can be reactivated.
   ───────────────────────────────────────────────────────────── */

// Alias so the animated element is a plain JSX identifier (keeps `motion` counted
// as used by no-unused-vars, which doesn't track `motion.div` member expressions).
const MotionDiv = motion.div;

const FREQUENCY_OPTIONS = ['once', 'once in a month', '3-4 in month', 'multiple times'];
const SCOPE_OPTIONS = ['company', 'hod'];
const SCORE_MODE_OPTIONS = ['manual', 'form', 'auto'];

/** A blank form — also the shape used to reset the modal. */
const EMPTY_FORM = {
  name: '',
  short: '',
  frequency: 'once',
  scope: 'company',
  upload_required: false,
  score_mode: 'manual',
};

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  muted:  { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};

const Pill = ({ label, tone = 'muted' }) => {
  const s = TONE[tone] || TONE.muted;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

const SCOPE_TONE = { company: 'indigo', hod: 'orange' };
const SCORE_TONE = { manual: 'muted', form: 'indigo', auto: 'green' };

/* Shared field styles for the modal. */
const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, children, required }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
    {children}
  </label>
);

const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} className={`${inputCls} cursor-pointer`}>
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);

/** Seed the form from an activity row (edit) or a blank (add). */
const seedForm = (editing) => (editing
  ? {
    name: editing.name || '',
    short: editing.short || '',
    frequency: FREQUENCY_OPTIONS.includes(editing.frequency) ? editing.frequency : 'once',
    scope: SCOPE_OPTIONS.includes(editing.scope) ? editing.scope : 'company',
    upload_required: !!editing.upload_required,
    score_mode: SCORE_MODE_OPTIONS.includes(editing.score_mode) ? editing.score_mode : 'manual',
  }
  : EMPTY_FORM);

/**
 * Add / Edit modal — reused for both create and update flows.
 * Mounted only while open (via a keyed parent), so state seeds cleanly from
 * props on mount — no effect-driven syncing needed.
 */
const ActivityModal = ({ editing, onClose, onSubmit }) => {
  const [form, setForm] = useState(() => seedForm(editing));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { setErr('Name is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({ ...form, name: form.name.trim(), short: form.short.trim() });
    } catch (ex) {
      setErr(ex?.response?.data?.detail || 'Failed to save activity. Please try again.');
      setSaving(false);
    }
  };

  return (
    <MotionDiv
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
            {/* header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <div className="flex items-center gap-2.5">
                <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                  {editing ? <Pencil size={16} /> : <Plus size={16} />}
                </span>
                <h3 className="text-[15px] font-extrabold tracking-tight">{editing ? 'Edit Activity' : 'Add Activity'}</h3>
              </div>
              <button type="button" onClick={onClose} disabled={saving}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                <X size={16} />
              </button>
            </div>

            <form onSubmit={submit} className="px-5 py-4 space-y-4">
              <Field label="Name" required>
                <input type="text" value={form.name} onChange={(e) => set('name', e.target.value)}
                  placeholder="e.g. Monthly Review Meeting" className={inputCls} autoFocus />
              </Field>

              <Field label="Short">
                <input type="text" value={form.short} onChange={(e) => set('short', e.target.value)}
                  placeholder="e.g. MRM" className={inputCls} />
              </Field>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field label="Frequency">
                  <Select value={form.frequency} onChange={(v) => set('frequency', v)} options={FREQUENCY_OPTIONS} />
                </Field>
                <Field label="Scope">
                  <Select value={form.scope} onChange={(v) => set('scope', v)} options={SCOPE_OPTIONS} />
                </Field>
                <Field label="Score Mode">
                  <Select value={form.score_mode} onChange={(v) => set('score_mode', v)} options={SCORE_MODE_OPTIONS} />
                </Field>
                <Field label="Upload Required">
                  <button type="button" onClick={() => set('upload_required', !form.upload_required)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold transition-colors hover:border-[var(--accent-indigo)]">
                    <span className="relative inline-flex w-9 h-5 rounded-full transition-colors"
                      style={{ background: form.upload_required ? 'var(--accent-green)' : 'var(--border)' }}>
                      <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
                        style={{ left: form.upload_required ? '18px' : '2px' }} />
                    </span>
                    <span style={{ color: form.upload_required ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                      {form.upload_required ? 'Yes' : 'No'}
                    </span>
                  </button>
                </Field>
              </div>

              {err && (
                <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
                  <AlertTriangle size={14} /> {err}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-1">
                <button type="button" onClick={onClose} disabled={saving}
                  className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  Cancel
                </button>
                <button type="submit" disabled={saving}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
                  {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                  {saving ? 'Saving…' : editing ? 'Save Changes' : 'Create Activity'}
                </button>
              </div>
            </form>
      </MotionDiv>
    </MotionDiv>
  );
};

const ActivityManagement = () => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState(null); // row id mid activate/deactivate

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getActivities(true); // include inactive
      const list = res?.data?.activities;
      setActivities(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load activities.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (admin) load(); }, [admin, load]);

  const kpis = useMemo(() => {
    const total = activities.length;
    const active = activities.filter((a) => a.active !== false).length;
    const uploads = activities.filter((a) => a.upload_required).length;
    return [
      { value: total, label: 'Total Activities', sub: 'In catalogue', tone: 'blue', icon: Layers },
      { value: active, label: 'Active', sub: 'Currently in use', tone: active ? 'green' : 'plain', icon: CheckCircle2 },
      { value: total - active, label: 'Inactive', sub: 'Deactivated', tone: total - active ? 'yellow' : 'plain', icon: PauseCircle },
      { value: uploads, label: 'Upload Required', sub: 'Need evidence', tone: 'blue', icon: ListChecks },
    ];
  }, [activities]);

  const pActs = usePaged(activities || [], 10);

  const openAdd = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (row) => { setEditing(row); setModalOpen(true); };

  const handleSubmit = async (payload) => {
    if (editing?._id) {
      await updateActivity(editing._id, payload);
    } else {
      await createActivity(payload);
    }
    setModalOpen(false);
    setEditing(null);
    await load();
  };

  const toggleActive = async (row) => {
    if (!row?._id) return;
    const next = row.active === false; // currently inactive → activate
    setBusyId(row._id);
    setError('');
    try {
      await updateActivity(row._id, { active: next });
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to update activity status.');
    } finally {
      setBusyId(null);
    }
  };

  // Admin-only page — non-admins never see the catalogue.
  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Activity Management is restricted to TPMS administrators.
        </p>
      </div>
    );
  }

  if (loading && activities.length === 0) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading activities…</div>;
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={ListChecks} title="Activity Management" subtitle="Manage the TPMS activity catalogue (H4)">
        <HeroButton icon={Plus} onClick={openAdd}>Add Activity</HeroButton>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <Section
        title="Activity Catalogue"
        subtitle={activities.length ? `${activities.length} activit${activities.length === 1 ? 'y' : 'ies'}` : 'Nothing yet'}
        icon={Layers}>
        {activities.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <ListChecks size={20} />
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No activities yet</p>
            <p className="text-[12px] text-[var(--text-muted)]">Add your first activity to get started.</p>
            <button onClick={openAdd}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
              <Plus size={14} /> Add Activity
            </button>
          </div>
        ) : (
          <>
          <TableShell minWidth={980}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Name</Th><Th>Short</Th><Th>Frequency</Th><Th align="center">Scope</Th>
                <Th align="center">Upload Required</Th><Th align="center">Score Mode</Th>
                <Th align="center">Active</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pActs.pageRows.map((a, i) => {
                const isActive = a.active !== false;
                const rowBusy = busyId === a._id;
                return (
                  <tr key={a._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                    style={{ opacity: isActive ? 1 : 0.6 }}>
                    <Td className="font-bold">{a.name || '—'}</Td>
                    <Td className="text-[var(--text-muted)]">{a.short || '—'}</Td>
                    <Td className="font-medium whitespace-nowrap">{a.frequency || '—'}</Td>
                    <Td align="center"><Pill label={a.scope || '—'} tone={SCOPE_TONE[a.scope] || 'muted'} /></Td>
                    <Td align="center">
                      <Pill label={a.upload_required ? 'Yes' : 'No'} tone={a.upload_required ? 'green' : 'muted'} />
                    </Td>
                    <Td align="center"><Pill label={a.score_mode || '—'} tone={SCORE_TONE[a.score_mode] || 'muted'} /></Td>
                    <Td align="center">
                      <Pill label={isActive ? 'Active' : 'Inactive'} tone={isActive ? 'green' : 'muted'} />
                    </Td>
                    <Td align="right">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        <button type="button" onClick={() => openEdit(a)}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                          <Pencil size={12} /> Edit
                        </button>
                        <button type="button" onClick={() => toggleActive(a)} disabled={rowBusy}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold border transition-opacity hover:opacity-90 disabled:opacity-50"
                          style={{
                            color: isActive ? 'var(--accent-red)' : 'var(--accent-green)',
                            background: isActive ? 'var(--accent-red-bg)' : 'var(--accent-green-bg)',
                            borderColor: isActive ? 'var(--accent-red-border)' : 'var(--accent-green-border)',
                          }}>
                          {rowBusy
                            ? <RefreshCw size={12} className="animate-spin" />
                            : isActive ? <PauseCircle size={12} /> : <PlayCircle size={12} />}
                          {isActive ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          <Pager {...pActs} label="activities" />
          </>
        )}
      </Section>

      <AnimatePresence>
        {modalOpen && (
          <ActivityModal
            key={editing?._id || 'new'}
            editing={editing}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSubmit={handleSubmit}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default ActivityManagement;
