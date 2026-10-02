import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import api from '../services/api';
import {
  User, Mail, Phone, Shield, Briefcase, Lock, Loader2, LogOut, Pencil, Check, X,
  Building2, Calendar, KeyRound, ShieldCheck, PhoneCall, AlertCircle, IdCard,
  MapPin, Globe, Heart, Cake, AtSign, Hash, Users as UsersIcon,
} from 'lucide-react';
import NotificationSettings from '../components/settings/NotificationSettings';
import { motion } from 'framer-motion';

// Fields the self-service PATCH /users/me endpoint accepts (see backend SelfProfileUpdate).
// Everything NOT in here is rendered read-only / disabled (no backend support yet).
const EDITABLE = {
  general: ['first_name', 'last_name', 'mobile', 'emergency_mobile'],
  professional: ['designation', 'department', 'reporting_manager', 'joining_date'],
};

const hydrate = (u) => ({
  first_name: u?.first_name || '',
  last_name: u?.last_name || '',
  mobile: u?.mobile || '',
  emergency_mobile: u?.emergency_mobile || '',
  designation: u?.designation || '',
  department: u?.department || '',
  reporting_manager: u?.reporting_manager || '',
  joining_date: u?.joining_date ? String(u.joining_date).slice(0, 10) : '',
});

/**
 * Every field renders as a form control so the layout always matches the reference.
 *  - editable + section in edit mode  → enabled input/select
 *  - otherwise                        → disabled control showing the value, or a
 *                                       placeholder ("Not Provided" / "dd-mm-yyyy" /
 *                                       "Select …") when there's no data.
 * Unsupported fields (editable=false) stay disabled even in edit mode.
 */
const Field = ({ icon: Icon, label, value, editing, onChange, kind = 'text', options, placeholder = 'Not Provided', editable = true }) => {
  const active = editable && editing;
  const base = 'w-full px-3.5 py-2 border rounded-xl text-[13px] font-medium transition-all outline-none';
  const enabledCls = 'bg-[var(--input-bg)] border-[var(--input-border)] text-[var(--text-main)] focus:border-[var(--accent-indigo)]';
  const disabledCls = 'bg-[var(--input-bg)] border-[var(--border)] text-[var(--text-main)] opacity-70 cursor-not-allowed';
  const cls = `${base} ${active ? enabledCls : disabledCls}`;

  return (
    <div className="space-y-1.5 min-w-0">
      <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-1.5">
        {Icon && <Icon size={12} />} {label}
      </label>
      {kind === 'select' ? (
        <select disabled={!active} value={value || ''} onChange={(e) => onChange && onChange(e.target.value)} className={cls}>
          <option value="">{placeholder}</option>
          {(options || []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : active ? (
        <input type={kind === 'date' ? 'date' : 'text'} value={value || ''} onChange={(e) => onChange && onChange(e.target.value)} className={cls} />
      ) : (
        <input type="text" disabled value={value || ''} placeholder={kind === 'date' ? 'dd-mm-yyyy' : placeholder} className={cls} />
      )}
    </div>
  );
};

const SectionCard = ({ icon: Icon, title, subtitle, editKey, editing, onEdit, onSave, onCancel, saving, editable = true, children }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
    <div className="flex items-start justify-between gap-3 mb-5">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)] shrink-0">
          <Icon size={18} />
        </div>
        <div>
          <h2 className="text-[15px] font-bold text-[var(--text-main)] tracking-tight">{title}</h2>
          {subtitle && <p className="text-[11px] text-[var(--text-muted)] font-medium">{subtitle}</p>}
        </div>
      </div>
      {editable && (
        editing === editKey ? (
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={onCancel} disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-all disabled:opacity-50">
              <X size={13} /> Cancel
            </button>
            <button onClick={onSave} disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo)] text-white shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
              {saving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Save
            </button>
          </div>
        ) : (
          <button onClick={() => onEdit(editKey)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] hover:opacity-80 transition-all shrink-0">
            <Pencil size={12} /> Edit
          </button>
        )
      )}
    </div>
    {children}
  </div>
);

const QuickInfo = ({ icon: Icon, label, value }) => (
  <div className="flex items-center gap-3 p-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-sm">
    <div className="w-9 h-9 rounded-xl bg-[var(--input-bg)] flex items-center justify-center text-[var(--accent-indigo)] shrink-0">
      <Icon size={15} />
    </div>
    <div className="min-w-0">
      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
      <p className="text-[12px] font-bold text-[var(--text-main)] truncate">{value || 'Not Provided'}</p>
    </div>
  </div>
);

const ProfilePage = () => {
  const { user, logout, refreshUser } = useAuth();
  const { showSuccess, showError } = useNotification();

  const [editing, setEditing] = useState(null); // 'general' | 'professional' | null
  const [form, setForm] = useState(hydrate(null));
  const [saving, setSaving] = useState(false);

  const [pwd, setPwd] = useState({ current: '', next: '', confirm: '' });
  const [changingPwd, setChangingPwd] = useState(false);

  // Reporting manager is stored as a user _id; resolve it to a display name via the
  // manager-options endpoint (scope by company_id for client users, omit for internal staff).
  const [managers, setManagers] = useState([]);

  useEffect(() => { if (user) setForm(hydrate(user)); }, [user]);

  useEffect(() => {
    if (!user) return;
    const params = user.company_id ? { company_id: user.company_id } : {};
    api.get('/users/reporting-manager-options', { params })
      .then((res) => setManagers(Array.isArray(res.data) ? res.data : []))
      .catch(() => setManagers([]));
  }, [user]);

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const cancelEdit = () => { setForm(hydrate(user)); setEditing(null); };

  const saveSection = async (sec) => {
    setSaving(true);
    try {
      const payload = {};
      EDITABLE[sec].forEach((k) => { payload[k] = form[k]; });
      await api.patch('/users/me', payload); // only API-supported fields are ever sent
      await refreshUser();
      showSuccess('Profile updated successfully');
      setEditing(null);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    if (pwd.next !== pwd.confirm) { showError('Passwords do not match'); return; }
    setChangingPwd(true);
    try {
      await api.patch('/auth/change-password', { current_password: pwd.current, new_password: pwd.next });
      showSuccess('Password updated successfully');
      setPwd({ current: '', next: '', confirm: '' });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update password');
    } finally {
      setChangingPwd(false);
    }
  };

  if (!user) {
    return (
      <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="h-64 rounded-3xl bg-[var(--input-bg)] animate-pulse" />
        <div className="lg:col-span-2 space-y-6">
          {[0, 1].map((i) => <div key={i} className="h-56 rounded-3xl bg-[var(--input-bg)] animate-pulse" />)}
        </div>
      </div>
    );
  }

  const fullName = user.full_name || `${user.first_name || ''} ${user.last_name || ''}`.trim() || user.email || 'User';
  const isActive = user.is_active !== false;
  const permissions = user.permissions && typeof user.permissions === 'object' ? user.permissions : null;
  const isEditingGeneral = editing === 'general';
  const isEditingPro = editing === 'professional';
  const reportingManagerName =
    (user.reporting_manager && managers.find((m) => m._id === user.reporting_manager)?.full_name) || '—';

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6 pb-10">
      {/* ───────────── LEFT: Profile summary ───────────── */}
      <div className="lg:col-span-1 space-y-4 lg:sticky lg:top-24 self-start">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm text-center">
          <div className="w-24 h-24 mx-auto rounded-2xl bg-[var(--avatar-bg)] flex items-center justify-center text-white text-3xl font-black shadow-xl ring-4 ring-[var(--bg-card)]">
            {(fullName.charAt(0) || 'U').toUpperCase()}
          </div>
          <h1 className="mt-4 text-xl font-black text-[var(--text-main)] tracking-tight truncate">{fullName}</h1>
          <p className="text-[12px] font-bold text-[var(--text-muted)] truncate">{user.email}</p>
          <div className="flex flex-wrap items-center justify-center gap-2 mt-3">
            <span className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">{user.role || '—'}</span>
            <span className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest" style={{ color: isActive ? 'var(--accent-green)' : 'var(--accent-red)', background: 'var(--input-bg)' }}>
              {isActive ? 'Active' : 'Inactive'}
            </span>
          </div>
          <button onClick={logout}
            className="mt-5 w-full py-2.5 bg-[var(--accent-red-bg)] text-[var(--accent-red)] font-black text-[11px] uppercase tracking-widest rounded-xl flex items-center justify-center gap-2 hover:bg-[var(--accent-red)] hover:text-white transition-all">
            <LogOut size={15} /> Sign Out
          </button>
        </div>

        {/* Quick info — reference fields (placeholder when data is absent) */}
        <div className="space-y-3">
          <QuickInfo icon={Mail} label="Email" value={user.email} />
          <QuickInfo icon={Hash} label="Employee ID" value={user.employee_id} />
          <QuickInfo icon={Shield} label="Role" value={user.role} />
          <QuickInfo icon={Briefcase} label="Department" value={user.department} />
        </div>
      </div>

      {/* ───────────── RIGHT: Sections ───────────── */}
      <div className="lg:col-span-2 space-y-6">
        {/* Section 1 — General Information */}
        <SectionCard icon={User} title="General Information" subtitle="Your basic identity and contact details."
          editKey="general" editing={editing} onEdit={setEditing} onSave={() => saveSection('general')} onCancel={cancelEdit} saving={saving}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={User} label="First Name" value={isEditingGeneral ? form.first_name : user.first_name} editing={isEditingGeneral} onChange={(v) => setField('first_name', v)} />
            <Field icon={User} label="Last Name" value={isEditingGeneral ? form.last_name : user.last_name} editing={isEditingGeneral} onChange={(v) => setField('last_name', v)} />
            <Field icon={AtSign} label="Username" value={user.email} editable={false} />
            <Field icon={Mail} label="Email" value={user.email} editable={false} />
            <Field icon={Phone} label="Mobile Number" value={isEditingGeneral ? form.mobile : user.mobile} editing={isEditingGeneral} onChange={(v) => setField('mobile', v)} />
            <Field icon={PhoneCall} label="Alternate Mobile" value={isEditingGeneral ? form.emergency_mobile : user.emergency_mobile} editing={isEditingGeneral} onChange={(v) => setField('emergency_mobile', v)} />
          </div>
        </SectionCard>

        {/* Section 2 — Professional Profile */}
        <SectionCard icon={Briefcase} title="Professional Profile" subtitle="Role, department and reporting details."
          editKey="professional" editing={editing} onEdit={setEditing} onSave={() => saveSection('professional')} onCancel={cancelEdit} saving={saving}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={Hash} label="Employee ID" value={user.employee_id} editable={false} />
            <Field icon={Shield} label="Role" value={user.role} editable={false} />
            <Field icon={IdCard} label="Designation" value={isEditingPro ? form.designation : user.designation} editing={isEditingPro} onChange={(v) => setField('designation', v)} />
            <Field icon={Briefcase} label="Department" value={isEditingPro ? form.department : user.department} editing={isEditingPro} onChange={(v) => setField('department', v)} />
            <Field icon={UsersIcon} label="Reporting Manager" value={reportingManagerName} editable={false} />
            <Field icon={Calendar} label="Joining Date" kind="date" value={isEditingPro ? form.joining_date : (user.joining_date ? String(user.joining_date).slice(0, 10) : '')} editing={isEditingPro} onChange={(v) => setField('joining_date', v)} />
            <Field icon={MapPin} label="Office Location" value={user.office_location} editable={false} />
            <Field icon={Hash} label="Employee Code" value={user.employee_code} editable={false} />
          </div>
        </SectionCard>

        {/* Section 3 — Personal Details (no backend support yet → read-only placeholders) */}
        <SectionCard icon={Heart} title="Personal Details" subtitle="Personal information (managed by HR)." editable={false}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={AtSign} label="Personal Email" value={user.personal_email} editable={false} />
            <Field icon={UsersIcon} label="Gender" kind="select" options={['Male', 'Female', 'Other']} placeholder="Select Gender" value={user.gender} editable={false} />
            <Field icon={Cake} label="Date of Birth" kind="date" value={user.date_of_birth} editable={false} />
            <Field icon={Heart} label="Marital Status" kind="select" options={['Single', 'Married', 'Other']} placeholder="Select Marital Status" value={user.marital_status} editable={false} />
            <Field icon={Globe} label="Nationality" value={user.nationality} editable={false} />
            <Field icon={Cake} label="Anniversary Date" kind="date" value={user.anniversary_date} editable={false} />
          </div>
        </SectionCard>

        {/* Section 4 — Residential Address (no backend support yet → read-only placeholders) */}
        <SectionCard icon={MapPin} title="Residential Address" subtitle="Address details (managed by HR)." editable={false}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field icon={MapPin} label="Address" value={user.address} editable={false} />
            <Field icon={Building2} label="City" value={user.city} editable={false} />
            <Field icon={Building2} label="State" value={user.state} editable={false} />
            <Field icon={Globe} label="Country" value={user.country} editable={false} />
            <Field icon={Hash} label="Pincode" value={user.pincode} editable={false} />
          </div>
        </SectionCard>

        {/* Section 5 — Account & Security */}
        <SectionCard icon={KeyRound} title="Account & Security" subtitle="Manage your credentials." editable={false}>
          <form onSubmit={changePassword} className="space-y-4 max-w-md">
            {[
              ['current', 'Current Password'],
              ['next', 'New Password'],
              ['confirm', 'Confirm New Password'],
            ].map(([key, label]) => (
              <div key={key} className="space-y-1.5">
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</label>
                <div className="relative">
                  <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                  <input type="password" required value={pwd[key]} onChange={(e) => setPwd({ ...pwd, [key]: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all" />
                </div>
              </div>
            ))}
            <button type="submit" disabled={changingPwd}
              className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white font-black text-[11px] uppercase tracking-widest rounded-xl shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
              {changingPwd ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />} Update Password
            </button>
          </form>
          <div className="mt-5 p-3.5 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] rounded-xl flex items-start gap-2.5">
            <AlertCircle size={15} className="text-[var(--accent-orange)] shrink-0 mt-0.5" />
            <p className="text-[11px] font-medium text-[var(--accent-orange)] leading-relaxed">
              Password changes take effect immediately. You may need to re-login on other devices.
            </p>
          </div>
        </SectionCard>

        {/* Notification Settings (real per-user preferences via /notifications/preferences) */}
        <NotificationSettings />

        {/* Section 6 — System Access (permissions, read-only) */}
        {permissions && Object.keys(permissions).length > 0 && (
          <SectionCard icon={ShieldCheck} title="System Access" subtitle="Your module permissions (read-only)." editable={false}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {Object.entries(permissions).map(([mod, actions]) => (
                <div key={mod} className="p-3.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl">
                  <p className="text-[11px] font-black text-[var(--text-main)] uppercase tracking-widest mb-2">{mod}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {['create', 'read', 'update', 'delete'].map((a) => {
                      const on = actions && actions[a];
                      return (
                        <span key={a}
                          className="px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-widest"
                          style={{
                            color: on ? 'var(--accent-green)' : 'var(--text-muted)',
                            background: on ? 'var(--accent-green-bg)' : 'var(--input-bg)',
                            border: `1px solid ${on ? 'var(--accent-green-border)' : 'var(--border)'}`,
                            opacity: on ? 1 : 0.5,
                          }}>
                          {a}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        )}
      </div>
    </motion.div>
  );
};

export default ProfilePage;
