import React, { useState, useEffect, useCallback } from 'react';
import { Settings, Mail, Clock, Globe, ChevronDown, Check, Save, Loader2, Info } from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';

// Real, saveable preferences — backed by GET/PUT /notifications/preferences.
// email_notifications + task_reminders are shown; the other keys are preserved on save
// so the PUT (whose model defaults missing keys to true) never resets them.
const PREF_KEYS = ['email_notifications', 'task_reminders', 'delegation_updates', 'subscription_updates', 'holiday_alerts'];

// Full names kept for stable keys; boxes render just the first letter (M T W T F S S).
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// Green animated switch.
const Toggle = ({ checked, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={!!checked}
    onClick={() => onChange(!checked)}
    className={`relative w-11 h-6 rounded-full transition-colors duration-300 shrink-0 outline-none cursor-pointer ${
      checked ? 'bg-[var(--accent-indigo)]' : 'bg-[var(--border)]'
    }`}
  >
    <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-300 ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
  </button>
);

// Icon + label + toggle box.
const ToggleBox = ({ icon: Icon, label, checked, onChange }) => (
  <div className="flex items-center justify-between gap-3 p-4 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-sm">
    <div className="flex items-center gap-3 min-w-0">
      <div className="w-10 h-10 rounded-xl bg-[var(--input-bg)] flex items-center justify-center text-[var(--text-muted)] shrink-0"><Icon size={18} /></div>
      <span className="text-[14px] font-black text-[var(--text-main)] truncate">{label}</span>
    </div>
    <Toggle checked={checked} onChange={onChange} />
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm ${className}`}>{children}</div>
);

const NotificationSettings = () => {
  const { showSuccess, showError } = useNotification();
  const [prefs, setPrefs] = useState({
    email_notifications: false, task_reminders: false, delegation_updates: true,
    subscription_updates: true, holiday_alerts: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // UI-only (no backend field yet) — defaults per spec.
  const timezone = 'Asia/Kolkata';
  const reminderTime = '09:00';
  const [dailyTaskReport, setDailyTaskReport] = useState(false);
  const [weeklyOffs, setWeeklyOffs] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/notifications/preferences');
      const next = {};
      PREF_KEYS.forEach((k) => { next[k] = res.data?.[k] !== undefined ? !!res.data[k] : true; });
      setPrefs(next);
    } catch (err) {
      console.error('Failed to load notification preferences', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const setPref = (k, v) => setPrefs((p) => ({ ...p, [k]: v }));
  const toggleDay = (day) => setWeeklyOffs((w) => ({ ...w, [day]: !w[day] }));

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/notifications/preferences', prefs); // only API-supported keys are sent
      showSuccess('Notification settings saved');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const SaveButton = (
    <button onClick={save} disabled={saving || loading}
      className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white font-black text-[12px] uppercase tracking-widest rounded-xl shadow-sm hover:opacity-90 transition-all disabled:opacity-50 shrink-0 w-full sm:w-auto justify-center">
      {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Save Changes
    </button>
  );

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)] shrink-0">
          <Settings size={22} />
        </div>
        <div>
          <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight">Notifications</h1>
          <p className="text-[13px] font-medium text-[var(--text-muted)]">Configure alert preferences</p>
        </div>
      </div>

      {/* Main card */}
      <Card>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-black text-[var(--text-main)] tracking-tight">Notification Settings</h2>
            <p className="text-[12px] font-medium text-[var(--text-muted)]">Manage how you receive updates and reminders</p>
          </div>
          {SaveButton}
        </div>

        {/* Tab label */}
        <div className="border-b border-[var(--border)] mt-6 mb-5">
          <span className="inline-block pb-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)] border-b-2 border-[var(--accent-indigo)]">
            General Preferences
          </span>
        </div>

        {loading ? (
          <div className="h-20 rounded-2xl bg-[var(--input-bg)] animate-pulse" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ToggleBox icon={Mail} label="Email Notifications" checked={prefs.email_notifications} onChange={(v) => setPref('email_notifications', v)} />
            {/* Timezone — UI-only display box */}
            <div className="flex items-center gap-3 p-4 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-sm">
              <div className="w-10 h-10 rounded-xl bg-[var(--input-bg)] flex items-center justify-center text-[var(--text-muted)] shrink-0"><Clock size={18} /></div>
              <div className="flex-1 min-w-0">
                <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Timezone</p>
                <p className="text-[14px] font-black text-[var(--text-main)] truncate">{timezone}</p>
              </div>
              <ChevronDown size={16} className="text-[var(--text-muted)] shrink-0" />
            </div>
          </div>
        )}
      </Card>

      {/* Reminder Settings */}
      <Card>
        <h2 className="text-xl font-black text-[var(--text-main)] tracking-tight">Reminder Settings</h2>
        <p className="text-[12px] font-medium text-[var(--text-muted)] mb-5">Configure your recurring task reminders</p>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-center">
          {/* Daily Reminder Time — UI-only display */}
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] flex items-center justify-center text-white shrink-0 shadow-sm"><Clock size={20} /></div>
            <div className="min-w-0">
              <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Daily Reminder Time</p>
              <p className="text-[16px] font-black text-[var(--text-main)] flex items-center gap-1.5">{reminderTime} <Clock size={14} className="text-[var(--text-muted)]" /></p>
            </div>
          </div>
          <ToggleBox icon={Mail} label="Email Reminders" checked={prefs.task_reminders} onChange={(v) => setPref('task_reminders', v)} />
          <ToggleBox icon={Globe} label="Daily Task Report" checked={dailyTaskReport} onChange={setDailyTaskReport} />
        </div>
      </Card>

      {/* Weekly Offs */}
      <Card>
        <h2 className="text-xl font-black text-[var(--text-main)] tracking-tight">Weekly Offs</h2>
        <p className="text-[12px] font-medium text-[var(--text-muted)] mb-5">Select your non-working days</p>

        <div className="flex flex-wrap gap-3 sm:gap-4">
          {DAYS.map((day) => {
            const on = !!weeklyOffs[day];
            return (
              <div key={day} className="flex flex-col items-center gap-2">
                <button type="button" onClick={() => toggleDay(day)} title={day}
                  className={`w-12 h-12 sm:w-14 sm:h-14 rounded-2xl border flex items-center justify-center transition-all ${
                    on
                      ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white shadow-sm'
                      : 'bg-[var(--bg-card)] border-[var(--border)] hover:border-[var(--accent-indigo)]'
                  }`}>
                  {on && <Check size={22} strokeWidth={3} />}
                </button>
                <span className="text-[12px] font-black text-[var(--text-muted)]">{day.charAt(0)}</span>
              </div>
            );
          })}
        </div>

        <p className="mt-5 text-[10px] font-medium text-[var(--text-muted)] italic flex items-center gap-1.5">
          <Info size={11} /> Only Email Notifications and Email Reminders are saved. Timezone, daily reminder time, daily task report and weekly offs are UI-only until backend support is added.
        </p>
      </Card>
    </div>
  );
};

export default NotificationSettings;
