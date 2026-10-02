import React, { useState } from 'react';
import { Lock, Loader2 } from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';

// Change-password card. Reuses the existing /auth/change-password endpoint (no backend change).
const PasswordCard = () => {
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (form.newPassword !== form.confirmPassword) {
      showError('Passwords do not match');
      return;
    }
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

  const inputCls = 'w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-medium text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all';

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]">
          <Lock size={18} />
        </div>
        <div>
          <h3 className="text-[14px] font-bold text-[var(--text-main)] tracking-tight">Change Password</h3>
          <p className="text-[11px] text-[var(--text-muted)] font-medium">Update your account password.</p>
        </div>
      </div>
      <form onSubmit={submit} className="space-y-3 max-w-md">
        <div className="space-y-1.5">
          <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Current Password</label>
          <input type="password" required value={form.currentPassword} onChange={(e) => setForm({ ...form, currentPassword: e.target.value })} className={inputCls} />
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">New Password</label>
          <input type="password" required value={form.newPassword} onChange={(e) => setForm({ ...form, newPassword: e.target.value })} className={inputCls} />
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Confirm New Password</label>
          <input type="password" required value={form.confirmPassword} onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })} className={inputCls} />
        </div>
        <button type="submit" disabled={saving}
          className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />} Update Password
        </button>
      </form>
    </div>
  );
};

export default PasswordCard;
