import React, { useCallback, useEffect, useState } from 'react';
import { Bell, Save, Loader2, ToggleLeft, ToggleRight } from 'lucide-react';
import { getNotificationPrefs, updateNotificationPrefs } from '../../services/settingsApi';
import { useNotification } from '../../context/NotificationContext';

// Order + labels for the 5 preference keys the backend stores (notification.py).
const PREFS = [
  { key: 'email_notifications', label: 'Email Notifications', desc: 'Receive updates over email.' },
  { key: 'task_reminders', label: 'Task Reminders', desc: 'Reminders before task deadlines.' },
  { key: 'delegation_updates', label: 'Delegation Updates', desc: 'Alerts when delegated tasks change.' },
  { key: 'subscription_updates', label: 'Subscription Updates', desc: 'Activity on tasks you follow.' },
  { key: 'holiday_alerts', label: 'Holiday Alerts', desc: 'Notify about upcoming holidays.' },
];

const NotificationsTab = () => {
  const { showSuccess, showError } = useNotification();
  const [prefs, setPrefs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchPrefs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getNotificationPrefs();
      setPrefs(res.data);
    } catch {
      showError('Failed to load notification preferences');
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => { fetchPrefs(); }, [fetchPrefs]);

  const toggle = (key) => setPrefs(p => ({ ...p, [key]: !p[key] }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateNotificationPrefs(prefs);
      showSuccess('Notification preferences saved');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save preferences');
    } finally {
      setSaving(false);
    }
  };

  if (loading || !prefs) {
    return <div className="flex items-center justify-center py-24"><Loader2 size={22} className="animate-spin text-[var(--accent-indigo)]" /></div>;
  }

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm max-w-2xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]"><Bell size={16} /></div>
          <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">Notification Preferences</h2>
        </div>
        <button onClick={handleSave} disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-60">
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
        </button>
      </div>

      <div className="space-y-2">
        {PREFS.map(({ key, label, desc }) => (
          <button key={key} onClick={() => toggle(key)}
            className="w-full flex items-center justify-between gap-4 px-4 py-3 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-left hover:border-[var(--accent-indigo-border)] transition-all">
            <div>
              <p className="text-[13px] font-bold text-[var(--text-main)]">{label}</p>
              <p className="text-[11px] font-medium text-[var(--text-muted)]">{desc}</p>
            </div>
            {prefs[key]
              ? <ToggleRight size={30} className="text-[var(--accent-indigo)] shrink-0" />
              : <ToggleLeft size={30} className="text-[var(--text-muted)] shrink-0" />}
          </button>
        ))}
      </div>
    </div>
  );
};

export default NotificationsTab;
