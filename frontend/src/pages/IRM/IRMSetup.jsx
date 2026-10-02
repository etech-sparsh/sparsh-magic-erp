import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  SlidersHorizontal, Save, RotateCcw, AlertTriangle, CheckCircle2, RefreshCw,
  Percent, ShieldAlert, Gauge, Calculator, ArrowLeft, Clock, Undo2,
  Plus, Pencil, Trash2, X, Target,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
} from '../../features/tpms/common/dashboardKit';
import {
  getIrmConfig, saveIrmConfig, saveIrmShift, getIrmPeople, clearIrmPersonConfig,
  getIrmKpis, createIrmKpi, updateIrmKpi, deleteIrmKpi,
} from '../../services/irmApi';
import {
  canEditWeightages, errText, fmtNum, scoreColor, useAsync, useIrmCompany,
} from './irmUtils';

/* ─────────────────────────────────────────────────────────────
   IRM ▸ Setup — the sheet's highlighted weightage cells, made editable.

   The column must total exactly 100: the backend refuses anything else, and Save stays
   disabled until the draft agrees, so an invalid split can never be persisted. The
   preview panel re-runs the worked example against the draft as it is typed, so the
   effect of a change is visible before it is saved.

   Saving takes effect immediately — scores are derived from this config on every read,
   so there is no recalculation to wait for.
   ───────────────────────────────────────────────────────────── */


/* ─────────────────────────────────────────────────────────────
   Custom KPIs.

   The five built-in parameters measure things the ERP already records, so they are the same
   for everybody. A custom KPI measures something it does not — so it is given to NAMED people
   and its number is reported by the person being scored.

   Giving somebody a KPI necessarily changes their column: the weightage has to come from
   somewhere, and which parameter gives it up is a judgement about what matters — not
   arithmetic. So it is asked, not assumed. The default leaves every column alone and lets the
   admin place the number themselves; the two automatic modes are there when the split really
   is mechanical.
   ───────────────────────────────────────────────────────────── */
// Manual is the default deliberately: re-cutting somebody's weightage column is a decision,
// and a default that does it quietly is the kind of help you only notice once it has changed
// a number you had chosen on purpose.
const BLANK_KPI = {
  name: '', description: '', weightage: '10', person_ids: [],
  balance: 'manual', balance_from: '',
};

const BALANCE_CHOICES = [
  {
    id: 'manual',
    label: "I'll set the columns myself",
    hint: 'Nobody\u2019s weightages are touched. Each assignee\u2019s column will read over 100% until you edit it here, and the board flags it until you do.',
  },
  {
    id: 'from',
    label: 'Take it out of one parameter',
    hint: 'That parameter drops by the KPI\u2019s weightage. Everything else stays exactly as you set it.',
  },
  {
    id: 'spread',
    label: 'Spread across the others',
    hint: 'Every other parameter scales down in proportion, keeping their relative sizes.',
  },
];

const KpiEditor = ({ draft, setDraft, people, parameters, saving, onSave, onCancel, isEdit }) => {
  const toggle = (pid) => setDraft((d) => ({
    ...d,
    person_ids: d.person_ids.includes(pid)
      ? d.person_ids.filter((x) => x !== pid)
      : [...d.person_ids, pid],
  }));
  const weight = Number(draft.weightage);
  const needsSource = draft.balance === 'from';
  const source = parameters.find((x) => x.code === draft.balance_from);
  // "Take it from Task" is only honest if Task has that much to give. Saying so up front beats
  // emptying the parameter and leaving the column short for somebody to discover later.
  const sourceShort = needsSource && source && Number(source.weightage) < weight;
  const valid = draft.name.trim() && weight >= 0 && weight < 100
    && draft.person_ids.length > 0 && (!needsSource || Boolean(draft.balance_from));

  return (
    <div className="rounded-xl border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)]/30 p-4 space-y-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <label className="flex flex-col gap-1">
          <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">KPI name</span>
          <input type="text" value={draft.name} maxLength={60} disabled={saving || isEdit}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="e.g. Client Calls"
            title={isEdit ? 'The name is fixed once created, so filed scores stay attached' : undefined}
            className="px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)] disabled:opacity-60" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">Weightage</span>
          <div className="flex items-center gap-1.5">
            <input type="number" min={0} max={99} step={1} value={draft.weightage} disabled={saving}
              onChange={(e) => setDraft((d) => ({ ...d, weightage: e.target.value }))}
              className="w-24 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold text-right tabular-nums outline-none focus:border-[var(--accent-indigo)]" />
            <span className="text-[12px] font-bold text-[var(--text-muted)]">%</span>
          </div>
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">
          What it measures <span className="font-semibold normal-case tracking-normal">(shown to the person filling it in)</span>
        </span>
        <input type="text" value={draft.description} maxLength={300} disabled={saving}
          onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          placeholder="e.g. Calls logged against the monthly target"
          className="px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-semibold outline-none focus:border-[var(--accent-indigo)]" />
      </label>

      <div>
        <div className="flex items-baseline justify-between gap-2 mb-1.5">
          <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">
            Who carries it
          </span>
          <span className="text-[11px] font-bold text-[var(--text-muted)] tabular-nums">
            {draft.person_ids.length} selected
          </span>
        </div>
        <div className="max-h-44 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--bg-card)] divide-y divide-[var(--border)]">
          {people.length === 0 && (
            <p className="px-3 py-3 text-[12px] text-[var(--text-muted)]">No people on this roster.</p>
          )}
          {people.map((pp) => (
            <label key={pp.person_id}
              className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-[var(--input-bg)]">
              <input type="checkbox" checked={draft.person_ids.includes(pp.person_id)}
                disabled={saving} onChange={() => toggle(pp.person_id)}
                className="w-4 h-4 accent-[var(--accent-indigo)] cursor-pointer" />
              <span className="text-[12.5px] font-bold truncate">{pp.name}</span>
              {pp.designation && (
                <span className="text-[10.5px] text-[var(--text-muted)] truncate">{pp.designation}</span>
              )}
            </label>
          ))}
        </div>
        <p className="mt-1.5 text-[11px] text-[var(--text-muted)] leading-relaxed">
          Only these people get the KPI — nobody else&rsquo;s sheet changes. Their column has to
          find {fmtNum(Number(draft.weightage) || 0)}% for it; choose how below.
        </p>
      </div>

      <div>
        <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">
          Where its {fmtNum(weight || 0)}% comes from
        </span>
        <div className="mt-1.5 space-y-1.5">
          {BALANCE_CHOICES.map((choice) => (
            <label key={choice.id}
              className={`flex gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                draft.balance === choice.id
                  ? 'border-[var(--accent-indigo)] bg-[var(--bg-card)]'
                  : 'border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo-border)]'}`}>
              <input type="radio" name="kpi-balance" checked={draft.balance === choice.id}
                disabled={saving}
                onChange={() => setDraft((d) => ({ ...d, balance: choice.id }))}
                className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--accent-indigo)] cursor-pointer" />
              <span className="min-w-0">
                <span className="block text-[12.5px] font-bold">{choice.label}</span>
                <span className="block text-[11px] text-[var(--text-muted)] leading-relaxed mt-0.5">
                  {choice.hint}
                </span>
                {choice.id === 'from' && draft.balance === 'from' && (
                  <span className="block mt-2">
                    <select value={draft.balance_from} disabled={saving}
                      onChange={(e) => setDraft((d) => ({ ...d, balance_from: e.target.value }))}
                      aria-label="Parameter to take the weightage from"
                      className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-bold outline-none focus:border-[var(--accent-indigo)] cursor-pointer">
                      <option value="">Choose a parameter…</option>
                      {parameters.filter((x) => !x.custom).map((x) => (
                        <option key={x.code} value={x.code}>
                          {x.name} — currently {fmtNum(x.weightage)}%
                        </option>
                      ))}
                    </select>
                    {sourceShort && (
                      <span className="block mt-1.5 text-[11px] font-bold text-[var(--accent-orange)] leading-relaxed">
                        {source.name} only has {fmtNum(source.weightage)}% to give. It will go to
                        0% and the column will be {fmtNum(weight - Number(source.weightage))}%
                        short for you to place.
                      </span>
                    )}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button type="button" onClick={onCancel} disabled={saving}
          className="px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
          Cancel
        </button>
        <button type="button" onClick={onSave} disabled={saving || !valid}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
          {saving ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Add KPI'}
        </button>
      </div>
    </div>
  );
};

const CustomKpiSection = ({ companyId, people, parameters, canEdit, onChanged }) => {
  const [kpis, setKpis] = useState([]);
  const [draft, setDraft] = useState(null);       // null = not editing
  const [editing, setEditing] = useState(null);   // the code being edited
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) return;
    try {
      setKpis((await getIrmKpis(companyId)).data?.kpis || []);
    } catch (e) {
      setErr(errText(e, 'Could not load KPIs.'));
    }
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const nameOf = (pid) => people.find((x) => x.person_id === pid)?.name || 'someone';

  const save = async () => {
    setSaving(true);
    setErr('');
    try {
      const payload = {
        name: draft.name.trim(),
        description: draft.description.trim(),
        weightage: Number(draft.weightage) || 0,
        person_ids: draft.person_ids,
        balance: draft.balance,
        balance_from: draft.balance === 'from' ? draft.balance_from : null,
      };
      const res = editing
        ? await updateIrmKpi(companyId, editing, payload)
        : await createIrmKpi(companyId, payload);
      const rebalanced = res?.data?.columns_rebalanced ?? 0;
      setNotice(draft.balance === 'manual'
        ? `Saved. No weightages were changed — set each person\u2019s column yourself using the scope picker above.`
        : `Saved. ${rebalanced} column${rebalanced === 1 ? '' : 's'} rebalanced to 100%.`);
      setDraft(null);
      setEditing(null);
      await load();
      onChanged?.();
    } catch (e) {
      setErr(errText(e, 'Could not save that KPI.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (code) => {
    setSaving(true);
    setErr('');
    try {
      await deleteIrmKpi(companyId, code);
      setConfirming(null);
      await load();
      onChanged?.();
    } catch (e) {
      setErr(errText(e, 'Could not remove that KPI.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="Custom KPIs"
      subtitle={kpis.length
        ? `${kpis.length} KPI${kpis.length === 1 ? '' : 's'} on top of the five standard parameters`
        : 'Add a parameter of your own, for the people it applies to'}
      icon={Target}
      action={canEdit && !draft && (
        <button type="button"
          onClick={() => { setEditing(null); setDraft({ ...BLANK_KPI }); setErr(''); }}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity">
          <Plus size={13} /> Add KPI
        </button>
      )}
    >
      <div className="px-4 py-4 space-y-3">
        <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">
          A custom KPI is scored by the person it belongs to — they fill in their own
          achievement each month on the IRM board, and you can correct it. Its weightage stays
          yours to set. Until somebody fills one in it counts as &ldquo;no data&rdquo; and is
          left out of the score rather than counting as zero.
        </p>

        {err && (
          <div className="flex items-start gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2.5 text-[12px] font-bold text-[var(--accent-red)]">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {err}
          </div>
        )}

        {notice && !draft && (
          <div className="flex items-start gap-2 rounded-lg border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-3 py-2.5 text-[12px] font-bold text-[var(--accent-green)]">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> {notice}
          </div>
        )}

        {draft && (
          <KpiEditor draft={draft} setDraft={setDraft} people={people} parameters={parameters}
            saving={saving} isEdit={Boolean(editing)} onSave={save}
            onCancel={() => { setDraft(null); setEditing(null); setErr(''); }} />
        )}

        {kpis.length === 0 && !draft ? (
          <p className="py-6 text-center text-[12.5px] text-[var(--text-muted)]">
            No custom KPIs yet. The five standard parameters apply to everyone as they are.
          </p>
        ) : (
          <div className="space-y-2">
            {kpis.map((k) => (
              <div key={k.code}
                className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3.5 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-extrabold tracking-tight truncate">{k.name}</span>
                      <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] tabular-nums">
                        {fmtNum(k.weightage)}%
                      </span>
                    </div>
                    {k.description && (
                      <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{k.description}</p>
                    )}
                    <p className="text-[11px] text-[var(--text-muted)] mt-1">
                      {k.person_count === 0 ? 'Nobody yet' : k.person_ids.slice(0, 4).map(nameOf).join(', ')}
                      {k.person_count > 4 && ` +${k.person_count - 4} more`}
                    </p>
                  </div>
                  {canEdit && (
                    <div className="shrink-0 flex items-center gap-1.5">
                      <button type="button" title="Edit"
                        onClick={() => {
                          setEditing(k.code);
                          setDraft({
                            name: k.name, description: k.description || '',
                            weightage: String(k.weightage), person_ids: [...k.person_ids],
                            // Never carried over from the last edit: how to make room is a
                            // fresh decision each time, and re-applying "take it from Task"
                            // on an unrelated rename would raid it again.
                            balance: 'manual', balance_from: '',
                          });
                          setErr('');
                        }}
                        className="p-1.5 rounded-lg text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        <Pencil size={12} />
                      </button>
                      <button type="button" title="Remove" onClick={() => setConfirming(k)}
                        className="p-1.5 rounded-lg text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity">
                        <Trash2 size={12} />
                      </button>
                    </div>
                  )}
                </div>

                {confirming?.code === k.code && (
                  <div className="mt-3 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2.5">
                    <p className="text-[12px] font-semibold text-[var(--text-main)] leading-relaxed">
                      Remove <b>{k.name}</b>? Every score filed against it goes too, and the
                      {' '}{k.person_count} {k.person_count === 1 ? 'person' : 'people'} carrying it
                      get its {fmtNum(k.weightage)}% shared back across their other parameters.
                      This cannot be undone.
                    </p>
                    <div className="flex items-center justify-end gap-2 mt-2">
                      <button type="button" onClick={() => setConfirming(null)} disabled={saving}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)] transition-colors disabled:opacity-50">
                        Keep it
                      </button>
                      <button type="button" onClick={() => remove(k.code)} disabled={saving}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--accent-red)] text-white text-[12px] font-bold hover:opacity-90 transition-opacity disabled:opacity-50">
                        {saving ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />}
                        Remove
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
};

/** Sample achievement %s used only to illustrate the draft weightages. */
// Illustrative achievement per parameter, used only to show what the weightages would
// produce. `punctuality` joins the others here so the worked example stays complete —
// without it a company that has given punctuality weightage would see the preview quietly
// exclude it and disagree with the real score.
const PREVIEW_ACHIEVEMENT = {
  task: 80, delegation: 50, culture: 90, accountability: 75, punctuality: 95,
};

// Shift defaults mirror app/models/irm.py. Only used before the config lands.
const SHIFT_FALLBACK = { start: '09:30', end: '18:30', grace_minutes: 10 };

const numOrZero = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** The editable weightage cell. Kept as a string so a half-typed value isn't clobbered. */
const WeightageInput = ({ value, onChange, disabled }) => (
  <input
    type="number"
    min={0}
    max={100}
    step="0.01"
    value={value}
    disabled={disabled}
    onChange={(e) => onChange(e.target.value)}
    className="w-24 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold tabular-nums text-right outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
  />
);

const IRMSetup = () => {
  const navigate = useNavigate();
  const { user, staff, companies, companyId, setCompanyId } = useIrmCompany();
  const canEdit = canEditWeightages(user);

  const [draft, setDraft] = useState({});      // {code: string} — raw input values
  // '' = the company default column. A person id = that person's own column, which falls
  // back to the company one wherever it says nothing.
  const [personId, setPersonId] = useState('');
  const [shift, setShift] = useState(SHIFT_FALLBACK);
  const [shiftSaving, setShiftSaving] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState('');

  const waitingForCompany = staff && !companyId;
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  const load = useCallback(
    async () => (await getIrmConfig(companyId, personId)).data,
    [companyId, personId],
  );
  const { data: config, loading, error, reload } = useAsync(load, [companyId, personId], {
    skip: waitingForCompany,
  });

  const loadPeople = useCallback(async () => (await getIrmPeople(companyId)).data, [companyId]);
  const { data: roster, reload: reloadPeople } = useAsync(loadPeople, [companyId], {
    skip: waitingForCompany,
  });

  // "Company default" first, then everyone, with a mark against anyone already on their own
  // column — otherwise the only way to find out who is customised is to click through them.
  const scopeOptions = useMemo(() => ([
    { id: '', name: 'Company default — everyone' },
    ...(roster?.people || []).map((p) => ({
      id: p.person_id,
      name: p.has_override ? `${p.name} ✓ own column` : p.name,
    })),
  ]), [roster]);

  const person = (roster?.people || []).find((p) => p.person_id === personId);

  // Seed the draft from whatever the server currently holds.
  useEffect(() => {
    if (!config) return;
    setDraft(Object.fromEntries(config.parameters.map((p) => [p.code, String(p.weightage)])));
    setShift({ ...SHIFT_FALLBACK, ...(config.shift || {}) });
    setSaveError('');
    setSaved('');
  }, [config]);

  // Saved on its own, not with the weightage column: the shift decides what punctuality
  // MEANS, while the column decides how much it counts for. Tying them together would make
  // fixing a shift time require re-saving a column that was already correct.
  const saveShift = async () => {
    setShiftSaving(true);
    setSaveError('');
    setSaved('');
    try {
      await saveIrmShift(companyId, {
        start: shift.start,
        end: shift.end,
        grace_minutes: Number(shift.grace_minutes) || 0,
      });
      setSaved('Shift saved. Punctuality is recalculated from it on the next read.');
      await reload();
    } catch (e) {
      setSaveError(errText(e, 'Could not save the shift.'));
    } finally {
      setShiftSaving(false);
    }
  };

  const parameters = useMemo(() => config?.parameters || [], [config]);
  const total = useMemo(
    () => Math.round(parameters.reduce((s, p) => s + numOrZero(draft[p.code]), 0) * 100) / 100,
    [parameters, draft],
  );
  const isValid = Math.abs(total - 100) < 0.01;
  const isDirty = parameters.some((p) => numOrZero(draft[p.code]) !== p.weightage);

  const setWeight = (code, value) => {
    setDraft((d) => ({ ...d, [code]: value }));
    setSaved('');
    setSaveError('');
  };

  const resetToSaved = () => {
    setDraft(Object.fromEntries(parameters.map((p) => [p.code, String(p.weightage)])));
    setSaved('');
    setSaveError('');
  };

  // Removing an override is not the same as zeroing it: the person goes back to whatever
  // the company column says, and keeps tracking it as it changes.
  const removeOverride = async () => {
    setSaving(true);
    setSaveError('');
    setSaved('');
    try {
      await clearIrmPersonConfig(companyId, personId);
      setSaved(`${person?.name || 'This person'} is back on the company column.`);
      await reload();
      await reloadPeople();
    } catch (e) {
      setSaveError(errText(e, 'Could not remove the override.'));
    } finally {
      setSaving(false);
    }
  };

  const resetToDefaults = () => {
    setDraft(Object.fromEntries(parameters.map((p) => [p.code, String(p.default_weightage)])));
    setSaved('');
    setSaveError('');
  };

  const save = async () => {
    setSaving(true);
    setSaveError('');
    setSaved('');
    try {
      const payload = parameters.map((p) => ({
        code: p.code,
        weightage: numOrZero(draft[p.code]),
      }));
      await saveIrmConfig(companyId, payload, personId);
      setSaved(personId
        ? `Saved for ${person?.name || 'this person'}. Everyone else stays on the company default.`
        : 'Weightages saved. IRM scores now use the updated values.');
      await reload();
      await reloadPeople();
    } catch (e) {
      setSaveError(errText(e, 'Could not save weightages.'));
    } finally {
      setSaving(false);
    }
  };

  // Worked example against the DRAFT, so the effect of an edit is visible before saving.
  const preview = useMemo(() => {
    const rows = parameters.map((p) => {
      const achievement = PREVIEW_ACHIEVEMENT[p.code] ?? 100;
      const weightage = numOrZero(draft[p.code]);
      return { ...p, achievement, weightage, weighted: Math.round(achievement * weightage) / 100 };
    });
    return { rows, final: Math.round(rows.reduce((s, r) => s + r.weighted, 0) * 100) / 100 };
  }, [parameters, draft]);

  if (!canEdit) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">Administrators only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          IRM weightages decide how every person is scored, so only a Super Admin or Admin
          can change them. You can see the weightages in force on the IRM scoreboard.
        </p>
        <Link to="/irm" className="text-[12.5px] font-bold text-[var(--accent-indigo)] hover:underline">
          Back to IRM
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={SlidersHorizontal}
        title="IRM Setup"
        subtitle="Set each parameter's weightage — the column must total exactly 100%"
      >
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        {/* Which column is being edited. The whole screen follows this — the sheet, the
            worked example and Save all act on the scope chosen here. */}
        {!waitingForCompany && (
          <HeaderSelect value={personId} onChange={setPersonId} options={scopeOptions} />
        )}
        <HeroButton icon={ArrowLeft} onClick={() => navigate('/irm')}>Back to IRM</HeroButton>
      </DashboardHero>

      {(error || saveError) && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error || saveError}
        </div>
      )}
      {saved && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {saved}
        </div>
      )}

      {waitingForCompany ? (
        <Section title="Weightage" subtitle="Select a company" icon={Percent}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to configure its IRM weightages.
          </div>
        </Section>
      ) : loading ? (
        <Section title="Weightage" subtitle="Loading" icon={Percent}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading weightages…
          </div>
        </Section>
      ) : (
        <>
          {/* Says whose column is on screen, and whether it is theirs or inherited — the
              numbers alone cannot tell those apart, since an inherited column shows the
              company's figures. */}
          {personId && (
            <div className="flex items-start gap-2 rounded-2xl border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] px-4 py-3">
              <Percent size={15} className="mt-[1px] shrink-0 text-[var(--accent-indigo)]" />
              <div className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-bold text-[var(--accent-indigo)]">
                  Editing {person?.name || 'this person'}&rsquo;s own column
                </span>
                <span className="block text-[11.5px] font-semibold text-[var(--text-muted)]">
                  {config?.inherited
                    ? 'They are on the company default right now — saving here gives them a column of their own.'
                    : 'They already have their own column. Everyone else stays on the company default.'}
                </span>
              </div>
              {canEdit && !config?.inherited && (
                <button type="button" onClick={removeOverride} disabled={saving}
                  className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] bg-[var(--bg-card)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  <Undo2 size={12} /> Use company default
                </button>
              )}
            </div>
          )}

          <Section
            title="Evaluation Parameters"
            subtitle={config?.is_customised
              ? `Last updated by ${config.updated_by || 'an administrator'}`
              : 'Using the default weightages — not yet customised'}
            icon={Percent}
          >
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Evaluation Parameter</Th>
                  <Th>Measured From</Th>
                  <Th align="center">Default</Th>
                  <Th align="right">Weightage</Th>
                </tr>
              </thead>
              <tbody>
                {parameters.map((p) => (
                  <tr key={p.code} className="border-b border-[var(--border)] last:border-0">
                    <Td>
                      <span className="font-bold">{p.name}</span>
                      {p.description && (
                        <span className="block text-[10.5px] text-[var(--text-muted)] mt-0.5 max-w-[420px]">
                          {p.description}
                        </span>
                      )}
                    </Td>
                    <Td className="text-[var(--text-muted)]">
                      {p.source === 'form' ? 'Rating form (0–5 scale)' : 'Achieved ÷ Assigned'}
                    </Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">
                      {fmtNum(p.default_weightage)}%
                    </Td>
                    <Td align="right">
                      <WeightageInput
                        value={draft[p.code] ?? ''}
                        onChange={(v) => setWeight(p.code, v)}
                        disabled={saving}
                      />
                    </Td>
                  </tr>
                ))}

                {/* GRAND TOTAL — the sheet's green row, and the rule Save enforces. */}
                <tr style={{
                  background: isValid ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                }}>
                  <Td className="font-extrabold uppercase tracking-wide text-[11px]"
                    style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    Grand Total
                  </Td>
                  <Td />
                  <Td />
                  <Td align="right">
                    <span className="text-[15px] font-extrabold tabular-nums pr-[26px]"
                      style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {fmtNum(total)}%
                    </span>
                  </Td>
                </tr>
              </tbody>
            </TableShell>

            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <p className="text-[11.5px] font-bold"
                style={{ color: isValid ? 'var(--text-muted)' : 'var(--accent-red)' }}>
                {isValid
                  ? 'Total is 100% — ready to save.'
                  : `Total must be exactly 100% (currently ${fmtNum(total)}%, ${total > 100 ? 'over' : 'under'} by ${fmtNum(Math.abs(100 - total))}%).`}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={resetToDefaults} disabled={saving}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  <RotateCcw size={13} /> Defaults
                </button>
                <button type="button" onClick={resetToSaved} disabled={saving || !isDirty}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                  <RefreshCw size={13} /> Discard changes
                </button>
                <button type="button" onClick={save} disabled={saving || !isValid || !isDirty}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
                  {saving ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
                  {saving ? 'Saving…' : 'Save Weightages'}
                </button>
              </div>
            </div>
          </Section>

          {/* This company's own parameters, on top of the five above. Placed directly after
              them because that is what it extends — and before the Preview, which only ever
              illustrates the shared five. */}
          <CustomKpiSection
            companyId={companyId}
            people={roster?.people || []}
            parameters={parameters}
            canEdit={canEdit}
            onChanged={reload}
          />

          {/* Live worked example against the draft. */}
          <Section
            title="Preview"
            subtitle="A sample person scored with the weightages above"
            icon={Calculator}
            tone="green"
          >
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Parameter</Th>
                  <Th align="center">Achievement %</Th>
                  <Th align="center">Weightage</Th>
                  <Th align="right">Weighted Score</Th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.code} className="border-b border-[var(--border)] last:border-0">
                    <Td className="font-bold">{r.name}</Td>
                    <Td align="center" className="tabular-nums">{fmtNum(r.achievement)}%</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtNum(r.weightage)}%</Td>
                    <Td align="right">
                      <span className="text-[11px] font-mono text-[var(--text-muted)] mr-2">
                        ({fmtNum(r.achievement)} × {fmtNum(r.weightage)}) ÷ 100 =
                      </span>
                      <span className="text-[13px] font-extrabold tabular-nums">{fmtNum(r.weighted)}</span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <span className="inline-flex items-center gap-2 text-[12px] font-bold text-[var(--text-muted)]">
                <Gauge size={14} /> Final IRM ={' '}
                <span className="font-mono tabular-nums">
                  {preview.rows.map((r) => fmtNum(r.weighted)).join(' + ')}
                </span>
              </span>
              <span className="text-[18px] font-extrabold tabular-nums"
                style={{ color: scoreColor(preview.final) }}>
                {fmtNum(preview.final)}%
              </span>
            </div>
          </Section>

          {/* ─── Shift rule ───
              Punctuality cannot be derived from punch times alone: 09:41 is early for one
              company and late for another. It lives here rather than on the dashboard
              because it is configuration that changes how people are scored, which is
              exactly what this screen is for. */}
          {/* COMPANY-WIDE, always — unlike the weightage column above, which the person
              picker scopes. One office has one set of hours; per-person shifts would mean
              a different definition of "on time" for each row of the same report. The
              controls are therefore locked while a person is selected, so this section can
              never read as part of that person's column. */}
          <Section title="Shift & Punctuality" icon={Clock}
            subtitle="Company-wide — one rule for everyone, whoever is selected above">
            <div className="px-5 py-4 space-y-4">
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                A day counts as punctual when the person punched in by{' '}
                <b className="text-[var(--text-main)]">{shift.start}</b> plus the grace below,
                and punched out no earlier than{' '}
                <b className="text-[var(--text-main)]">{shift.end}</b> minus it. A day with no
                out-punch counts as present but not punctual — a half-recorded day cannot be
                shown to have been worked in full.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {[
                  { key: 'start', label: 'Shift start', type: 'time' },
                  { key: 'end', label: 'Shift end', type: 'time' },
                  { key: 'grace_minutes', label: 'Grace (minutes)', type: 'number' },
                ].map((f) => (
                  <label key={f.key} className="flex flex-col gap-1.5">
                    <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                      {f.label}
                    </span>
                    <input
                      type={f.type}
                      min={f.type === 'number' ? 0 : undefined}
                      max={f.type === 'number' ? 240 : undefined}
                      value={shift[f.key] ?? ''}
                      disabled={!canEdit || !!personId}
                      onChange={(e) => setShift((s) => ({ ...s, [f.key]: e.target.value }))}
                      className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-60"
                    />
                  </label>
                ))}
              </div>

              {personId && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--text-muted)]">
                  <Clock size={14} className="mt-[1px] shrink-0" />
                  <span>
                    Shown for context — these hours apply to everyone, not just{' '}
                    {person?.name || 'this person'}. Switch the picker back to{' '}
                    <b className="text-[var(--text-main)]">Company default</b> to change them.
                  </span>
                </div>
              )}

              <div className="flex items-center justify-between gap-3 flex-wrap">
                <span className="text-[11.5px] font-semibold text-[var(--text-muted)]">
                  Changing this re-scores past months on the next read — the verdict comes
                  from the stored punches, so nothing needs re-importing.
                </span>
                {canEdit && !personId && (
                  <button type="button" onClick={saveShift} disabled={shiftSaving}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
                    {shiftSaving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                    {shiftSaving ? 'Saving…' : 'Save Shift'}
                  </button>
                )}
              </div>
            </div>
          </Section>
        </>
      )}
    </div>
  );
};

export default IRMSetup;
