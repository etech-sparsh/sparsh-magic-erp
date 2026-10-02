import React, { useState } from 'react';
import { Key, Lock, Loader2, AlertCircle } from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';

// Change-password form — reuses the existing PATCH /auth/change-password flow
// (same endpoint ProfilePage.jsx already uses).
const SecurityTab = () => {
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (form.newPassword.length < 8) return showError('New password must be at least 8 characters');
    if (form.newPassword !== form.confirmPassword) return showError('Passwords do not match');
    setSaving(true);
    try {
      await api.patch('/auth/change-password', {
        current_password: form.currentPassword,
        new_password: form.newPassword,
      });
      showSuccess('Password updated successfully');
      setForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update password');
    } finally {
      setSaving(false);
    }
  };

  const inputCls = "w-full pl-10 pr-4 py-2.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)]";

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm max-w-md">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]"><Key size={16} /></div>
        <div>
          <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">Change Password</h2>
          <p className="text-[11px] font-medium text-[var(--text-muted)]">Update your account credentials.</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {[
          { k: 'currentPassword', label: 'Current Password', ph: '••••••••' },
          { k: 'newPassword', label: 'New Password', ph: 'Minimum 8 characters' },
          { k: 'confirmPassword', label: 'Confirm New Password', ph: 'Re-type new password' },
        ].map(({ k, label, ph }) => (
          <div key={k} className="space-y-1">
            <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest ml-1">{label}</label>
            <div className="relative">
              <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input type="password" required value={form[k]} placeholder={ph}
                onChange={e => setForm({ ...form, [k]: e.target.value })} className={inputCls} />
            </div>
          </div>
        ))}

        <button type="submit" disabled={saving}
          className="w-full py-2.5 bg-[var(--accent-indigo)] text-white font-black text-[12px] uppercase tracking-widest rounded-xl shadow-sm hover:opacity-90 transition-all flex items-center justify-center gap-2 disabled:opacity-60">
          {saving ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />} Update Password
        </button>
      </form>

      <div className="mt-5 p-4 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] rounded-xl flex items-start gap-3">
        <AlertCircle size={16} className="text-[var(--accent-orange)] shrink-0 mt-0.5" />
        <p className="text-[11px] font-medium text-[var(--accent-orange)] leading-relaxed">
          Password changes take effect immediately. You may need to re-login on other devices.
        </p>
      </div>
    </div>
  );
};

export default SecurityTab;
