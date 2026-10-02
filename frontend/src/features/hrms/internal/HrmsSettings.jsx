import React, { useCallback, useEffect, useState } from 'react';
import {
  SlidersHorizontal, RotateCcw, Save, CalendarOff, Plus, Trash2, DownloadCloud,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getHrmsSettings, updateHrmsSettings, resetHrmsSettings,
  getHrmsHolidays, addHrmsHoliday, importHrmsHolidays, removeHrmsHoliday,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from './internalKit';
import { Btn, Chip } from './internalKit.jsx';

/**
 * HRMS ▸ the per-company rule set (Phase INT-5).
 *
 * SLA targets, retention periods, probation duration, reminder tiers and score band
 * floors — the numbers a second Sparsh entity is entitled to disagree with.
 *
 * Three things the screen has to make obvious:
 *
 *   - WHAT IS OVERRIDDEN, and what the module default was. A company reviewing its own
 *     policy needs to see where it has departed from the shipped one, which is why every
 *     changed value carries its default beside it rather than replacing it.
 *   - THAT RESETTING IS DIFFERENT FROM TYPING THE DEFAULT. A stored value stays where it
 *     was put if the default ever moves; resetting is how a company says it no longer
 *     wants that.
 *   - THAT NO GATE IS IN HERE. These are targets and durations. The budget gate, the
 *     reference check, the scorecard approval and the phone screen are not settings, and a
 *     reader should not have to hunt for a switch that does not exist.
 *
 * Rendered entirely from the server's own `CONFIG_SPEC` — labels, bounds, permitted names
 * and defaults all arrive in the payload — so adding a setting is a backend change and this
 * screen picks it up with no edit.
 */

const HrmsSettings = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.SETTINGS_WRITE);
  const kindOf = (key) => (data?.settings || []).find((s) => s.key === key)?.kind;

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: payload } = await getHrmsSettings(scope);
      setData(payload);
      setDraft({});
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the HRMS settings.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const setValue = (key, name, raw) => setDraft((d) => ({
    ...d, [key]: { ...(d[key] || {}), [name]: raw },
  }));

  const setList = (key, raw) => setDraft((d) => ({ ...d, [key]: raw }));
  const setFlag = (key, value) => setDraft((d) => ({ ...d, [key]: value }));

  const dirty = Object.keys(draft).length > 0;

  const save = async () => {
    // Blanks are dropped rather than sent as null: leaving a field empty means "I did not
    // change this", and sending it would ask the server to validate a number nobody typed.
    const payload = {};
    Object.entries(draft).forEach(([key, value]) => {
      if (typeof value === 'boolean') {
        payload[key] = value;
        return;
      }
      // An open {label: required?} catalogue. Sent whole and untouched: the server REPLACES
      // rather than merges it (see hrms_config_service.config_for), which is what lets a
      // company delete an entry, and the values are booleans that must not be coerced to
      // numbers by the map branch below.
      if (kindOf(key) === 'flag_map') {
        payload[key] = value;
        return;
      }
      if (typeof value === 'string') {
        const list = value.split(',').map((v) => v.trim()).filter(Boolean).map(Number);
        if (list.length) payload[key] = list;
        return;
      }
      // null is an explicit "switch this band off" (an optional name) and IS sent; '' and
      // undefined mean "untouched" and are dropped.
      const entries = Object.entries(value)
        .filter(([, v]) => v !== '' && v !== undefined)
        .map(([n, v]) => [n, v === null ? null : Number(v)]);
      if (entries.length) payload[key] = Object.fromEntries(entries);
    });
    if (!Object.keys(payload).length) {
      showError('Nothing has been changed.');
      return;
    }
    setBusy(true);
    try {
      const { data: updated } = await updateHrmsSettings(payload, scope);
      setData(updated);
      setDraft({});
      showSuccess('Settings updated. New records and reports use these from now on.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the settings.');
    } finally {
      setBusy(false);
    }
  };

  const reset = async (key) => {
    setBusy(true);
    try {
      const { data: updated } = await resetHrmsSettings(key ? [key] : null, scope);
      setData(updated);
      setDraft({});
      showSuccess(key
        ? 'That setting follows the module default again.'
        : 'Every setting follows the module default again.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not reset the settings.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={SlidersHorizontal}
        title="HRMS settings"
        subtitle="The rules this company runs by — every one defaults to the module's own, and only what you change is yours"
        actions={canWrite && data && (
          <div className="flex items-center gap-2">
            {!data.follows_defaults && (
              <Btn onClick={() => reset(null)} disabled={busy}>
                <RotateCcw size={14} /> Follow defaults
              </Btn>
            )}
            <Btn tone="primary" onClick={save} disabled={busy || !dirty}>
              <Save size={14} /> {busy ? 'Saving…' : 'Save changes'}
            </Btn>
          </div>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading settings…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-4">
            <p className="text-[12.5px] text-[var(--text-muted)]">
              {data.follows_defaults
                ? 'This company follows every module default. Change a number below and only '
                  + 'that number becomes yours — the rest keep following the default.'
                : 'This company has adopted some of its own numbers. A value you set stays '
                  + 'where you put it even if the module default later moves; use '
                  + '“Follow defaults” to go back to tracking it.'}
            </p>
            <p className="mt-2 text-[11.5px] text-[var(--text-muted)]">
              <b>Nothing here switches a control off.</b> The budget approval, the reference
              check, the scorecard sign-off and the telephonic screen are the process itself —
              a departure from one is logged as an exception, where it is attributable.
            </p>
          </div>

          {data.settings.map((setting) => (
            <section
              key={setting.key}
              className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-4"
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <h2 className="text-[13.5px] font-bold text-[var(--text-main)]">
                    {setting.label}
                  </h2>
                  {setting.note && (
                    <p className="mt-1 text-[11.5px] text-[var(--text-muted)] max-w-3xl">
                      {setting.note}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {setting.overridden.length > 0
                    ? <Chip tone="warn">Customised</Chip>
                    : <Chip tone="neutral">Module default</Chip>}
                  {canWrite && setting.overridden.length > 0 && (
                    <Btn onClick={() => reset(setting.key)} disabled={busy}>
                      <RotateCcw size={13} /> Reset
                    </Btn>
                  )}
                </div>
              </div>

              {setting.kind === 'flag' ? (
                <label className="mt-3 flex items-center gap-2 text-[13px]
                  text-[var(--text-main)]">
                  <input
                    type="checkbox"
                    disabled={!canWrite}
                    checked={draft[setting.key] ?? setting.value}
                    onChange={(e) => setFlag(setting.key, e.target.checked)}
                  />
                  <span>
                    {(draft[setting.key] ?? setting.value)
                      ? 'On — this company’s holidays are skipped as well as weekends'
                      : 'Off — weekends only'}
                  </span>
                </label>
              ) : setting.kind === 'int_list' ? (
                <div className="mt-3 max-w-md">
                  <label className={LABEL} htmlFor={`cfg-${setting.key}`}>
                    Days before the end date, descending (max {setting.max_entries})
                  </label>
                  <input
                    id={`cfg-${setting.key}`}
                    className={FIELD}
                    disabled={!canWrite}
                    placeholder={setting.value.join(', ')}
                    value={draft[setting.key] ?? ''}
                    onChange={(e) => setList(setting.key, e.target.value)}
                  />
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    In force: <b>{setting.value.join(', ')}</b>
                    {' · '}module default: {setting.default.join(', ')}
                  </p>
                </div>
              ) : setting.kind === 'flag_map' ? (
                <FlagMap
                  setting={setting}
                  draft={draft[setting.key]}
                  canWrite={canWrite}
                  onChange={(next) => setFlag(setting.key, next)}
                />
              ) : (
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {setting.names.map((name) => {
                    const current = setting.value[name];
                    const fallback = setting.default[name];
                    const changed = current !== fallback;
                    const optional = (setting.optional_names || []).includes(name);
                    const draftValue = draft[setting.key]?.[name];
                    // Off when the draft says null, or when nothing is drafted and the
                    // value in force is null.
                    const off = draftValue === null || (draftValue === undefined && current === null);
                    const show = (v) => (v === null ? 'Off' : String(v));
                    return (
                      <div key={name}>
                        <label className={LABEL} htmlFor={`cfg-${setting.key}-${name}`}>
                          {name.replace(/_/g, ' ')}
                        </label>
                        {optional && (
                          <label className="mb-1 flex items-center gap-2 text-[12px]
                            text-[var(--text-main)]">
                            <input
                              type="checkbox"
                              disabled={!canWrite}
                              checked={!off}
                              onChange={(e) => setValue(
                                setting.key, name,
                                e.target.checked ? String(current ?? fallback) : null,
                              )}
                            />
                            <span>{off ? 'Band switched off (three-band reading)' : 'Band in use'}</span>
                          </label>
                        )}
                        <input
                          id={`cfg-${setting.key}-${name}`}
                          type="number"
                          step={setting.kind === 'float_map' ? '0.1' : '1'}
                          min={setting.min}
                          max={setting.max}
                          disabled={!canWrite || off}
                          className={FIELD}
                          placeholder={show(current)}
                          value={off ? '' : (draftValue ?? '')}
                          onChange={(e) => setValue(setting.key, name, e.target.value)}
                        />
                        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                          In force: <b>{show(current)}</b>
                          {changed && ` · default ${show(fallback)}`}
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          ))}

          <WorkingCalendar
            scope={scope}
            canWrite={canWrite}
            honoured={Boolean(
              data.settings.find((x) => x.key === 'honour_holidays')?.value,
            )}
            showSuccess={showSuccess}
            showError={showError}
          />

          {!canWrite && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              You can see these numbers so you can plan against them. Changing them is
              Management&rsquo;s and Finance&rsquo;s — the SOP makes them accountable for the
              policy behind the process.
            </p>
          )}
        </>
      )}
    </div>
  );
};

/**
 * An OPEN {label: required?} catalogue — the joining documents a new hire uploads, and the
 * employment documents they sign.
 *
 * Unlike every other map on this screen it has no fixed `names`: a company adds a document
 * its own statutory or client obligations need, and removes one that does not apply. That
 * is why the whole map is edited as a unit and sent whole — the server REPLACES a flag_map
 * rather than merging it, which is precisely what makes a deletion stick instead of the
 * entry reappearing from the module default.
 *
 * `draft` is undefined until the first edit, at which point it becomes the entire map; the
 * value in force is the fallback so an untouched catalogue sends nothing at all.
 */
const FlagMap = ({ setting, draft, canWrite, onChange }) => {
  const [adding, setAdding] = useState('');
  const current = draft ?? setting.value ?? {};
  const entries = Object.entries(current);

  const write = (next) => onChange(next);
  const toggle = (name) => write({ ...current, [name]: !current[name] });
  const remove = (name) => {
    const next = { ...current };
    delete next[name];
    write(next);
  };
  const add = () => {
    const name = adding.trim();
    if (!name) return;
    // Adding a name that already exists would silently overwrite its tick rather than
    // adding anything, so it is refused by doing nothing visible except clearing the box.
    if (!(name in current)) write({ ...current, [name]: true });
    setAdding('');
  };

  return (
    <div className="mt-3 space-y-2">
      {entries.length === 0 && (
        <p className="text-[12px] text-[var(--text-muted)]">
          Nothing in this catalogue. Add the first document below.
        </p>
      )}
      {entries.map(([name, required]) => (
        <div
          key={name}
          className="flex items-center gap-3 rounded-lg border border-[var(--border)]
                     px-3 py-2"
        >
          <input
            id={`cfg-${setting.key}-${name}`}
            type="checkbox"
            disabled={!canWrite}
            checked={Boolean(required)}
            onChange={() => toggle(name)}
          />
          <label
            htmlFor={`cfg-${setting.key}-${name}`}
            className="min-w-0 flex-1 text-[12.5px] text-[var(--text-main)]"
          >
            {name}
            <span className="ml-2 text-[11px] text-[var(--text-muted)]">
              {required ? 'Required' : 'Optional'}
            </span>
          </label>
          {canWrite && (
            <Btn onClick={() => remove(name)}>Remove</Btn>
          )}
        </div>
      ))}
      {canWrite && (
        <div className="flex items-center gap-2 pt-1">
          <input
            className={FIELD}
            placeholder="Add a document…"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
          />
          <Btn onClick={add} disabled={!adding.trim()}>Add</Btn>
        </div>
      )}
    </div>
  );
};

/**
 * The working calendar — the dates SLA maths skips for this company.
 *
 * Kept beside the flag that switches it on rather than on a screen of its own: a calendar
 * nothing reads is confusing, and the two are one decision. The empty state says which,
 * because "no holidays recorded" and "holidays are not honoured" are different answers and
 * the difference decides whether a due date moves.
 */
const WorkingCalendar = ({ scope, canWrite, honoured, showSuccess, showError }) => {
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ holiday_date: '', holiday_name: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getHrmsHolidays({ ...scope, year });
      setRows(data?.holidays || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, scope?.company_id]);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!form.holiday_date || !form.holiday_name.trim()) {
      showError('A holiday needs both a date and a name.');
      return;
    }
    setBusy(true);
    try {
      await addHrmsHoliday(form, scope);
      setForm({ holiday_date: '', holiday_name: '' });
      showSuccess('Added to the working calendar.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not add that date.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (date) => {
    setBusy(true);
    try {
      await removeHrmsHoliday(date, scope);
      showSuccess('Removed from the working calendar.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not remove that date.');
    } finally {
      setBusy(false);
    }
  };

  const importYear = async () => {
    setBusy(true);
    try {
      const { data } = await importHrmsHolidays(year, scope);
      showSuccess(data.imported
        ? `Adopted ${data.imported} date(s) from the company holiday list`
          + (data.already_present ? `; ${data.already_present} were already here.` : '.')
        : 'Nothing new to adopt — every date for that year is already on this calendar.');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not import the holiday list.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[13.5px] font-bold text-[var(--text-main)]">
            Working calendar
          </h2>
          <p className="mt-1 text-[11.5px] text-[var(--text-muted)] max-w-3xl">
            The dates this company does not work. Read by SLA maths only while the setting
            above is on. This calendar is HRMS&rsquo;s own — importing from the company
            holiday list copies those dates here, so a later change there cannot move this
            company&rsquo;s due dates behind its back.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Chip tone={honoured ? 'good' : 'neutral'}>
            {honoured ? 'In use' : 'Not in use'}
          </Chip>
          <select
            aria-label="Calendar year"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="h-9 px-3 rounded-lg border border-[var(--border)]
              bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
          >
            {[thisYear - 1, thisYear, thisYear + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          {canWrite && (
            <Btn onClick={importYear} disabled={busy}>
              <DownloadCloud size={13} /> Import {year}
            </Btn>
          )}
        </div>
      </div>

      {canWrite && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className={LABEL} htmlFor="hol-date">Date</label>
            <input
              id="hol-date" type="date" className={FIELD}
              value={form.holiday_date}
              onChange={(e) => setForm((f) => ({ ...f, holiday_date: e.target.value }))}
            />
          </div>
          <div className="min-w-[12rem] flex-1">
            <label className={LABEL} htmlFor="hol-name">Name</label>
            <input
              id="hol-name" className={FIELD} placeholder="Founders Day"
              value={form.holiday_name}
              onChange={(e) => setForm((f) => ({ ...f, holiday_name: e.target.value }))}
            />
          </div>
          <Btn tone="primary" onClick={add} disabled={busy}>
            <Plus size={14} /> Add
          </Btn>
        </div>
      )}

      <div className="mt-4">
        {loading ? (
          <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
            <CalendarOff size={14} />
            No dates recorded for {year}.
            {honoured
              ? ' SLA targets currently skip weekends only.'
              : ' This calendar is not in use — turn the setting above on to apply it.'}
          </p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {rows.map((r) => (
              <li
                key={r.holiday_date}
                className="flex items-center gap-2 rounded-lg border border-[var(--border)]
                  px-3 py-2 text-[12.5px] text-[var(--text-main)]"
              >
                <span className="font-semibold">{day(r.holiday_date)}</span>
                <span className="text-[var(--text-muted)]">{r.holiday_name}</span>
                {r.imported_from_erp && <Chip tone="neutral">imported</Chip>}
                {canWrite && (
                  <button
                    type="button"
                    aria-label={`Remove ${r.holiday_name}`}
                    disabled={busy}
                    onClick={() => remove(r.holiday_date)}
                    className="text-[var(--text-muted)] hover:opacity-70 disabled:opacity-50"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

export default HrmsSettings;
