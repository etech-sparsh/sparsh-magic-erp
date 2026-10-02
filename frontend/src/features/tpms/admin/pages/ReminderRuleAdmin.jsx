import React, { useCallback, useEffect, useState } from 'react';
import {
  RefreshCw, BellRing, Plus, Check, X, ShieldAlert, Power, PowerOff, Info, AlertTriangle, Clock,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, Th, Td, TableShell, usePaged, Pager,
} from '../../common/dashboardKit';
import { getReminderRules, createReminderRule, updateReminderRule } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Reminder Rule Management (M12).

   Rules that drive the automated reminder cadence. Each rule fires an offset
   relative to an activity's due date (e.g. "2 days before"). Activity '*' means
   the rule applies to every activity. Rules are never hard-deleted — deactivating
   retires one (soft delete via active:false).

   Route: /tpms/admin/reminder-rules   (wired separately)
   ───────────────────────────────────────────────────────────── */

const UNIT_OPTIONS = ['days', 'hours'];
const DIR_OPTIONS = ['before', 'after'];
const CHANNEL_OPTIONS = ['email', 'whatsapp', 'both'];

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

/** A blank add form — also the reset shape. */
const EMPTY_FORM = {
  activity: '*',
  stage: 'reminder',
  offset_value: 2,
  offset_unit: 'days',
  offset_dir: 'before',
  channel: 'email',
};

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
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

const CHANNEL_TONE = { email: 'indigo', whatsapp: 'green', both: 'orange' };

/* Shared field styles. */
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

const IconBtn = ({ icon: Icon, label, onClick, disabled, tone = 'plain' }) => {
  const tones = {
    plain:  { c: 'var(--text-main)',     bg: 'var(--input-bg)',          bd: 'var(--border)' },
    green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
    red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',     bd: 'var(--accent-red-border)' },
  };
  const s = tones[tone] || tones.plain;
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={label} aria-label={label}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold border transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-95"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {Icon && <Icon size={13} />} {label}
    </button>
  );
};

/** Render an offset as a human phrase, e.g. "2 days before". */
const offsetLabel = (r) => {
  const v = Number(r?.offset_value);
  const value = Number.isFinite(v) ? v : '—';
  return `${value} ${r?.offset_unit || 'days'} ${r?.offset_dir || 'before'}`;
};

const ReminderRuleAdmin = () => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null); // row id mid activate/deactivate

  // Add form
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getReminderRules();
      const list = res?.data?.rules;
      setRules(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(errMsg(e, 'Failed to load reminder rules.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (admin) load(); }, [admin, load]);

  const pRules = usePaged(rules || [], 10);

  const resetForm = () => setForm(EMPTY_FORM);

  const handleAdd = async () => {
    const activity = (form.activity || '').trim() || '*';
    const stage = (form.stage || '').trim() || 'reminder';
    const value = Math.max(1, parseInt(form.offset_value, 10) || 1);
    setAddBusy(true);
    setAddError('');
    try {
      await createReminderRule({
        activity,
        stage,
        offset_value: value,
        offset_unit: form.offset_unit,
        offset_dir: form.offset_dir,
        channel: form.channel,
      });
      resetForm();
      setShowAdd(false);
      await load();
    } catch (e) {
      setAddError(errMsg(e, 'Failed to add reminder rule.'));
    } finally {
      setAddBusy(false);
    }
  };

  const toggleActive = async (row) => {
    if (!row?._id) return;
    const next = !(row.active !== false); // currently active → deactivate
    setBusyId(row._id);
    setError('');
    try {
      await updateReminderRule(row._id, { active: next });
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to update reminder rule status.'));
    } finally {
      setBusyId(null);
    }
  };

  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Reminder Rule Management is restricted to TPMS administrators.
        </p>
      </div>
    );
  }

  if (loading && rules.length === 0) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading reminder rules…</div>;
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={BellRing} title="Reminder Rules" subtitle="Automated reminder cadence relative to activity due dates (M12)">
        <HeroButton icon={Plus} onClick={() => { setShowAdd((v) => !v); setAddError(''); resetForm(); }}>
          Add Rule
        </HeroButton>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Info banner */}
      <div className="rounded-2xl border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-start gap-2.5">
        <span className="w-7 h-7 rounded-lg bg-[var(--bg-card)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0 shadow-sm"><Info size={15} /></span>
        <p className="text-[12px] font-medium text-[var(--text-main)] leading-relaxed">
          Activity <b>*</b> applies the rule to <b>all activities</b>. Offsets fire relative to the due date
          (e.g. <b>2 days before</b>). Deactivating a rule retires it — nothing is ever hard-deleted.
        </p>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
          <p className="text-[12.5px] font-extrabold mb-3">New reminder rule</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Field label="Activity">
              <input type="text" value={form.activity} onChange={(e) => set('activity', e.target.value)}
                placeholder="* (all)" className={inputCls} />
            </Field>
            <Field label="Stage">
              <input type="text" value={form.stage} onChange={(e) => set('stage', e.target.value)}
                placeholder="reminder" className={inputCls} />
            </Field>
            <Field label="Offset" required>
              <input type="number" min={1} value={form.offset_value}
                onChange={(e) => set('offset_value', e.target.value)} className={inputCls} />
            </Field>
            <Field label="Unit">
              <Select value={form.offset_unit} onChange={(v) => set('offset_unit', v)} options={UNIT_OPTIONS} />
            </Field>
            <Field label="Direction">
              <Select value={form.offset_dir} onChange={(v) => set('offset_dir', v)} options={DIR_OPTIONS} />
            </Field>
            <Field label="Channel">
              <Select value={form.channel} onChange={(v) => set('channel', v)} options={CHANNEL_OPTIONS} />
            </Field>
          </div>

          {addError && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)] mt-3">
              <AlertTriangle size={14} /> {addError}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 mt-3">
            <button type="button" onClick={() => setShowAdd(false)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[12.5px] font-bold hover:brightness-95 transition-all">
              <X size={14} /> Cancel
            </button>
            <button type="button" onClick={handleAdd} disabled={addBusy}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:brightness-110 transition-all disabled:opacity-50">
              {addBusy ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
              {addBusy ? 'Adding…' : 'Add Rule'}
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      <Section
        title="Reminder Rules"
        subtitle={rules.length ? `${rules.length} rule${rules.length === 1 ? '' : 's'}` : 'Nothing yet'}
        icon={Clock}>
        {rules.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <BellRing size={20} />
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No reminder rules yet</p>
            <p className="text-[12px] text-[var(--text-muted)]">Add your first rule to drive the reminder cadence.</p>
            <button onClick={() => { setShowAdd(true); setAddError(''); resetForm(); }}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
              <Plus size={14} /> Add Rule
            </button>
          </div>
        ) : (
          <>
          <TableShell minWidth={860}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Activity</Th><Th>Stage</Th><Th>Offset</Th>
                <Th align="center">Channel</Th><Th align="center">Active</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pRules.pageRows.map((r, i) => {
                const isActive = r.active !== false;
                const rowBusy = busyId === r._id;
                return (
                  <tr key={r._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                    style={{ opacity: isActive ? 1 : 0.6 }}>
                    <Td className="font-bold whitespace-nowrap">{r.activity || '*'}</Td>
                    <Td className="font-medium">{r.stage || '—'}</Td>
                    <Td className="font-medium whitespace-nowrap tabular-nums">{offsetLabel(r)}</Td>
                    <Td align="center"><Pill label={r.channel || '—'} tone={CHANNEL_TONE[r.channel] || 'muted'} /></Td>
                    <Td align="center"><Pill label={isActive ? 'Active' : 'Inactive'} tone={isActive ? 'green' : 'muted'} /></Td>
                    <Td align="right">
                      {isActive ? (
                        <IconBtn icon={PowerOff} label={rowBusy ? 'Working…' : 'Deactivate'} tone="red" onClick={() => toggleActive(r)} disabled={rowBusy} />
                      ) : (
                        <IconBtn icon={Power} label={rowBusy ? 'Working…' : 'Activate'} tone="green" onClick={() => toggleActive(r)} disabled={rowBusy} />
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          <Pager {...pRules} label="rules" />
          </>
        )}
      </Section>
    </div>
  );
};

export default ReminderRuleAdmin;
