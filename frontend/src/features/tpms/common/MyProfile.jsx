import React, { useState } from 'react';
import {
  UserCircle, IdCard, User, Mail, Building2, Shield, Lock, Eye, EyeOff, Save, CheckCircle2, AlertCircle,
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { DashboardHero, Section } from './dashboardKit';

/* ─────────────────────────────────────────────────────────────
   My Profile — account details (read-only, from the logged-in user)
   + change-password form with client-side validation. Shared by the
   Admin and SMOPS panels. No backend/DB calls (UI only).
   ───────────────────────────────────────────────────────────── */

const Row = ({ icon: Icon, label, value }) => (
  <div className="grid grid-cols-[130px_1fr] items-center gap-3 py-3 border-b border-[var(--border)] last:border-0">
    <span className="inline-flex items-center gap-2 text-[12px] font-bold text-[var(--text-muted)]">
      {Icon && <Icon size={14} />} {label}
    </span>
    <span className="text-[13px] font-bold text-[var(--text-main)] truncate">{value || '—'}</span>
  </div>
);

const PasswordField = ({ label, value, onChange, placeholder, error }) => {
  const [show, setShow] = useState(false);
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-bold text-[var(--text-main)]">{label} <span className="text-[var(--accent-red)]">*</span></span>
      <div className="relative">
        <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={`w-full pl-9 pr-10 py-2.5 rounded-lg text-[13px] font-medium outline-none transition-all bg-[var(--input-bg)] border ${error ? 'border-[var(--accent-red)]' : 'border-[var(--input-border)] focus:border-[var(--accent-indigo)]'}`}
        />
        <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-main)]">
          {show ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
      {error && <span className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--accent-red)]"><AlertCircle size={12} /> {error}</span>}
    </label>
  );
};

const MyProfile = ({ panelLabel = 'TPMS' }) => {
  const { user } = useAuth();

  const account = {
    staffId: user?.staff_id || user?.emp_id || user?._id || 'STA-009',
    name: user?.full_name || 'TPMS User',
    email: user?.email || user?.sub || 'user@sparshmagic.com',
    department: user?.department || '—',
    role: user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : 'Member',
  };
  const initials = (account.name || 'U').split(' ').map((x) => x[0]).slice(0, 2).join('');

  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState({});
  const [done, setDone] = useState(false);

  const submit = (e) => {
    e.preventDefault();
    const errs = {};
    if (!cur) errs.cur = 'Enter your current password';
    if (next.length < 6) errs.next = 'At least 6 characters';
    if (confirm !== next) errs.confirm = 'Passwords do not match';
    setErrors(errs);
    if (Object.keys(errs).length) { setDone(false); return; }
    // UI-only: no backend call.
    setDone(true); setCur(''); setNext(''); setConfirm('');
    setTimeout(() => setDone(false), 2600);
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={UserCircle} title="My Profile" subtitle="Account details & security" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* Account Details */}
        <Section title="Account Details" subtitle={`${panelLabel} account`} icon={User}>
          <div className="p-5">
            <div className="flex items-center gap-3 pb-4 mb-2 border-b border-[var(--border)]">
              <span className="w-14 h-14 rounded-2xl text-white text-[18px] font-extrabold flex items-center justify-center shadow-sm" style={{ background: 'var(--avatar-bg)' }}>
                {initials}
              </span>
              <div className="min-w-0">
                <p className="text-[15px] font-extrabold tracking-tight truncate">{account.name}</p>
                <span className="inline-flex items-center gap-1.5 mt-1 text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                  <Shield size={11} /> {account.role}
                </span>
              </div>
            </div>
            <Row icon={IdCard}    label="Staff ID"   value={account.staffId} />
            <Row icon={User}      label="Name"       value={account.name} />
            <Row icon={Mail}      label="Email"      value={account.email} />
            <Row icon={Building2} label="Department" value={account.department} />
            <Row icon={Shield}    label="Role"       value={account.role} />
          </div>
        </Section>

        {/* Change Password */}
        <Section title="Change Password" subtitle="Update your account password" icon={Lock}>
          <form onSubmit={submit} className="p-5 space-y-4">
            <PasswordField label="Current Password" value={cur} onChange={(v) => setCur(v)} placeholder="Enter current password" error={errors.cur} />
            <PasswordField label="New Password" value={next} onChange={(v) => setNext(v)} placeholder="At least 6 characters" error={errors.next} />
            <PasswordField label="Confirm New Password" value={confirm} onChange={(v) => setConfirm(v)} placeholder="Re-enter new password" error={errors.confirm} />

            {done && (
              <div className="flex items-center gap-2 text-[12.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] rounded-lg px-3 py-2">
                <CheckCircle2 size={15} /> Password updated.
              </div>
            )}

            <button type="submit" className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-all" style={{ background: 'var(--btn-primary)' }}>
              <Save size={15} /> Update Password
            </button>
          </form>
        </Section>
      </div>
    </div>
  );
};

export default MyProfile;
