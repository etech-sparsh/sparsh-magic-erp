import React, { useCallback, useEffect, useState } from 'react';
import {
  Settings, User, Briefcase, Heart, MapPin, Mail, Lock, ChevronRight, ChevronDown,
  Pencil, Save, X, Loader2, Phone, PhoneCall, Calendar, Globe, Cake, AtSign,
  Users as UsersIcon, IdCard, CheckSquare, CalendarClock,
} from 'lucide-react';
import { getMyProfile, updateMyProfile } from '../../services/settingsApi';
import { getInitials } from '../tasks/taskDisplayUtils';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { useTheme } from '../../context/ThemeContext';
import { canAccessTaskManagement } from '../../utils/taskAccess';
import { motion } from 'framer-motion';

const DEPARTMENTS = ['HOD', 'Manager', 'Implementor', 'EA', 'MD', 'HR', 'Other'];

// A single label + input row. Editable sections pass `editing`; unsupported/read-only
// fields (no backend self-update support yet) pass `readOnly` and just display the value
// or a placeholder — mirroring how the Profile page surfaces HR-managed fields.
const Field = ({ label, value, icon: Icon, editing, onChange, type = 'text', placeholder = 'Not provided', options }) => {
  const active = !!editing;
  const base = 'w-full pl-9 pr-3 py-2.5 rounded-xl text-[12px] font-bold outline-none border transition-all';
  const enabled = 'bg-[var(--input-bg)] border-[var(--input-border)] text-[var(--text-main)] focus:border-[var(--accent-indigo)]';
  const disabled = 'bg-[var(--input-bg)] border-[var(--border)] text-[var(--text-main)] opacity-70 cursor-not-allowed';
  const cls = `${base} ${active ? enabled : disabled}`;
  return (
    <div className="space-y-1.5 min-w-0">
      <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</label>
      <div className="relative">
        {Icon && <Icon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />}
        {options ? (
          <select disabled={!active} value={value || ''} onChange={e => onChange?.(e.target.value)} className={cls}>
            <option value="">{placeholder}</option>
            {options.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        ) : active ? (
          <input type={type === 'date' ? 'date' : 'text'} value={value || ''} onChange={e => onChange?.(e.target.value)} className={cls} />
        ) : (
          <input type="text" disabled value={value || ''} placeholder={placeholder} className={cls} />
        )}
      </div>
    </div>
  );
};

// Phone field with a decorative country-flag prefix (matches the reference). The stored
// value is a plain string — no phone-lib dependency added.
const PhoneField = ({ label, value, icon: Icon, editing, onChange, placeholder = 'Not provided' }) => {
  const active = !!editing;
  const inputCls = `flex-1 min-w-0 px-3 py-2.5 rounded-r-xl text-[12px] font-bold outline-none border border-l-0 transition-all ${
    active ? 'bg-[var(--input-bg)] border-[var(--input-border)] text-[var(--text-main)] focus:border-[var(--accent-indigo)]'
           : 'bg-[var(--input-bg)] border-[var(--border)] text-[var(--text-main)] opacity-70 cursor-not-allowed'}`;
  return (
    <div className="space-y-1.5 min-w-0">
      <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-1.5">
        {Icon && <Icon size={12} />} {label}
      </label>
      <div className="flex">
        <span className="flex items-center gap-1 px-2.5 rounded-l-xl border border-r-0 border-[var(--border)] bg-[var(--input-bg)] text-[13px] shrink-0 select-none">
          🇮🇳 <ChevronDown size={11} className="text-[var(--text-muted)]" />
        </span>
        <input type="text" disabled={!active} value={value || ''} onChange={e => onChange?.(e.target.value)} placeholder={placeholder} className={inputCls} />
      </div>
    </div>
  );
};

// White card with a colored section dot + optional edit / save / cancel controls.
const SectionCard = ({ dotColor, icon: Icon, title, editable, editing, onEdit, onCancel, onSave, saving, children }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
    <div className="flex items-center justify-between mb-5">
      <div className="flex items-center gap-3">
        <span className="w-8 h-8 rounded-full flex items-center justify-center text-white shrink-0" style={{ background: dotColor }}>
          {Icon && <Icon size={15} />}
        </span>
        <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">{title}</h2>
      </div>
      {editable && (editing ? (
        <div className="flex items-center gap-2">
          <button onClick={onCancel} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]" title="Cancel"><X size={15} /></button>
          <button onClick={onSave} disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-60">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
          </button>
        </div>
      ) : (
        <button onClick={onEdit} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--accent-indigo)]" title="Edit"><Pencil size={15} /></button>
      ))}
    </div>
    {children}
  </div>
);

// Read-only visual switch that reflects module access (self-service can't change access).
const AccessRow = ({ icon: Icon, iconColor, title, subtitle, on }) => (
  <div className="flex items-center gap-3">
    <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ color: iconColor, background: 'var(--input-bg)' }}>
      {Icon && <Icon size={16} />}
    </span>
    <div className="flex-1 min-w-0">
      <p className="text-[12px] font-black text-[var(--text-main)] truncate">{title}</p>
      <p className="text-[10px] font-medium text-[var(--text-muted)] truncate">{subtitle}</p>
    </div>
    <span className={`w-9 h-5 rounded-full p-0.5 shrink-0 transition-colors ${on ? 'bg-[var(--accent-indigo)]' : 'bg-[var(--border)]'}`} title={on ? 'Enabled' : 'No access'}>
      <span className={`block w-4 h-4 rounded-full bg-white shadow transition-transform ${on ? 'translate-x-4' : ''}`} />
    </span>
  </div>
);

const GeneralSection = ({ onNavigateSection }) => {
  const { user, refreshUser } = useAuth();
  const { showSuccess, showError } = useNotification();
  const { theme, toggleTheme } = useTheme();

  const [profile, setProfile] = useState(user || null);
  const [form, setForm] = useState({});
  const [loading, setLoading] = useState(true);

  const [editingGeneral, setEditingGeneral] = useState(false);
  const [editingPro, setEditingPro] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [savingPro, setSavingPro] = useState(false);

  const fetchProfile = useCallback(async () => {
    try {
      const res = await getMyProfile();
      setProfile(res.data);
      setForm(res.data);
    } catch {
      // Fall back to the AuthContext user if the fetch fails — the page still renders.
      if (user) { setProfile(user); setForm(user); }
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { fetchProfile(); }, [fetchProfile]);

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const saveGeneral = async () => {
    if (!(form.first_name || '').trim()) return showError('First name is required');
    setSavingGeneral(true);
    try {
      const res = await updateMyProfile({
        first_name: form.first_name, last_name: form.last_name,
        mobile: form.mobile, emergency_mobile: form.emergency_mobile,
      });
      setProfile(res.data); setForm(res.data); setEditingGeneral(false);
      await refreshUser?.();
      showSuccess('Profile updated');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update profile');
    } finally {
      setSavingGeneral(false);
    }
  };

  const savePro = async () => {
    setSavingPro(true);
    try {
      const res = await updateMyProfile({
        designation: form.designation, department: form.department,
        reporting_manager: form.reporting_manager, joining_date: form.joining_date,
      });
      setProfile(res.data); setForm(res.data); setEditingPro(false);
      await refreshUser?.();
      showSuccess('Professional profile updated');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update profile');
    } finally {
      setSavingPro(false);
    }
  };

  const cancelGeneral = () => { setForm(profile); setEditingGeneral(false); };
  const cancelPro = () => { setForm(profile); setEditingPro(false); };

  if (loading && !profile) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 size={22} className="animate-spin text-[var(--accent-indigo)]" />
      </div>
    );
  }

  const p = profile || {};
  const isActive = p.is_active !== false;
  const fullName = p.full_name || `${p.first_name || ''} ${p.last_name || ''}`.trim() || p.email || 'User';
  const joiningValue = p.joining_date ? String(p.joining_date).slice(0, 10) : '';
  const taskAccess = canAccessTaskManagement(p);
  const leaveAccess = !!(p.permissions?.attendance?.read || p.permissions?.leave?.read) || taskAccess;

  return (
    <div className="max-w-6xl mx-auto w-full">
      {/* Page header */}
      <div className="flex items-center gap-3 mb-6">
        <span className="w-10 h-10 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shrink-0">
          <Settings size={20} />
        </span>
        <div>
          <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight leading-tight">General</h1>
          <p className="text-[12px] font-medium text-[var(--text-muted)]">Update profile and workspace preferences</p>
        </div>
      </div>

      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ───────────── LEFT column ───────────── */}
        <div className="lg:col-span-1 space-y-5">
          {/* Profile card */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm relative">
            <span className="absolute top-4 right-4 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-widest bg-[var(--bg-card)] border border-[var(--border)]"
              style={{ color: isActive ? 'var(--accent-indigo)' : 'var(--accent-red)' }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: isActive ? 'var(--accent-indigo)' : 'var(--accent-red)' }} />
              {isActive ? 'Active' : 'Inactive'}
            </span>

            <div className="flex flex-col items-center text-center pt-2">
              <div className="w-24 h-24 rounded-full bg-[var(--avatar-bg)] flex items-center justify-center text-white text-3xl font-black shadow-lg">
                {getInitials(fullName)}
              </div>
              <h2 className="mt-4 text-lg font-black text-[var(--text-main)] tracking-tight">{fullName}</h2>
              <p className="text-[12px] font-black text-[var(--accent-indigo)]">{p.designation || '—'}</p>
              <p className="text-[11px] font-medium text-[var(--text-muted)]">{p.department || '—'}</p>
            </div>

            <div className="mt-5 space-y-2.5">
              <div className="flex items-center justify-between px-3.5 py-2.5 bg-[var(--input-bg)] rounded-xl">
                <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Official Role</span>
                <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">{p.role || '—'}</span>
              </div>
              <div className="flex items-center justify-between px-3.5 py-2.5 bg-[var(--input-bg)] rounded-xl">
                <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Employee ID</span>
                <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)]">
                  {p.employee_id || (p.id || p._id || '').toString().slice(-8).toUpperCase() || '—'}
                </span>
              </div>

              <button type="button" onClick={() => onNavigateSection?.('security')}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 bg-[var(--input-bg)] rounded-xl text-left hover:border-[var(--accent-indigo)] border border-transparent transition-all">
                <Mail size={16} className="text-[var(--text-muted)] shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-bold text-[var(--text-main)] truncate">{p.email}</p>
                  <p className="text-[9px] font-black text-[var(--accent-orange)] uppercase tracking-widest">Update Email</p>
                </div>
                <ChevronRight size={15} className="text-[var(--text-muted)] shrink-0" />
              </button>

              <button type="button" onClick={() => onNavigateSection?.('security')}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 bg-[var(--input-bg)] rounded-xl text-left hover:border-[var(--accent-indigo)] border border-transparent transition-all">
                <Lock size={16} className="text-[var(--text-muted)] shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-bold text-[var(--text-main)] tracking-widest">••••••••</p>
                  <p className="text-[9px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">Security Check</p>
                </div>
                <ChevronRight size={15} className="text-[var(--text-muted)] shrink-0" />
              </button>
            </div>
          </div>

          {/* System Access card */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-5">
              <span className="w-8 h-8 rounded-full bg-[var(--accent-indigo)] flex items-center justify-center text-white shrink-0"><CheckSquare size={15} /></span>
              <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">System Access</h2>
            </div>
            <div className="space-y-4">
              <AccessRow icon={CheckSquare} iconColor="var(--accent-indigo)" title="Task Management" subtitle="Manage assignments and checklists" on={taskAccess} />
              <AccessRow icon={CalendarClock} iconColor="var(--accent-indigo)" title="Leave & Attendance" subtitle="Request leaves and view logs" on={leaveAccess} />
            </div>
            <p className="mt-4 text-[9px] font-medium text-[var(--text-muted)] italic">Module access is managed by your administrator.</p>
          </div>
        </div>

        {/* ───────────── RIGHT column ───────────── */}
        <div className="lg:col-span-2 space-y-6">
          {/* General Information (editable) */}
          <SectionCard dotColor="var(--accent-orange)" icon={User} title="General Information" editable
            editing={editingGeneral} onEdit={() => setEditingGeneral(true)} onCancel={cancelGeneral} onSave={saveGeneral} saving={savingGeneral}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <Field label="First Name" icon={User} value={editingGeneral ? form.first_name : p.first_name} editing={editingGeneral} onChange={v => setField('first_name', v)} />
              <Field label="Last Name" icon={User} value={editingGeneral ? form.last_name : p.last_name} editing={editingGeneral} onChange={v => setField('last_name', v)} />
              <PhoneField label="Primary Mobile" icon={Phone} value={editingGeneral ? form.mobile : p.mobile} editing={editingGeneral} onChange={v => setField('mobile', v)} />
              <PhoneField label="Emergency Mobile" icon={PhoneCall} value={editingGeneral ? form.emergency_mobile : p.emergency_mobile} editing={editingGeneral} onChange={v => setField('emergency_mobile', v)} />
            </div>
          </SectionCard>

          {/* Professional Profile (editable) */}
          <SectionCard dotColor="var(--accent-indigo)" icon={Briefcase} title="Professional Profile" editable
            editing={editingPro} onEdit={() => setEditingPro(true)} onCancel={cancelPro} onSave={savePro} saving={savingPro}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <Field label="Designation" icon={IdCard} value={editingPro ? form.designation : p.designation} editing={editingPro} onChange={v => setField('designation', v)} />
              {editingPro ? (
                <Field label="Department" icon={Briefcase} value={form.department} editing options={DEPARTMENTS} placeholder="Select department..." onChange={v => setField('department', v)} />
              ) : (
                <Field label="Department" icon={Briefcase} value={p.department} />
              )}
              <Field label="Reporting Manager" icon={UsersIcon} value={editingPro ? form.reporting_manager : p.reporting_manager} editing={editingPro} onChange={v => setField('reporting_manager', v)} />
              <Field label="Joining Date" icon={Calendar} type="date" value={editingPro ? (form.joining_date || '') : joiningValue} editing={editingPro} onChange={v => setField('joining_date', v)} placeholder="mm/dd/yyyy" />
            </div>
          </SectionCard>

          {/* Personal Details (read-only — managed by HR, no self-update endpoint) */}
          <SectionCard dotColor="var(--accent-pink, #ec4899)" icon={Heart} title="Personal Details">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <Field label="Personal Email" icon={AtSign} value={p.personal_email} />
              <Field label="Date of Birth" icon={Calendar} value={p.date_of_birth} placeholder="mm/dd/yyyy" />
              <Field label="Gender" icon={UsersIcon} value={p.gender} options={['Male', 'Female', 'Other']} placeholder="Select Gender" />
              <Field label="Marital Status" icon={Heart} value={p.marital_status} options={['Single', 'Married', 'Other']} placeholder="Select Status" />
              <Field label="Anniversary Date" icon={Cake} value={p.anniversary_date} placeholder="mm/dd/yyyy" />
              <Field label="Nationality" icon={Globe} value={p.nationality} />
            </div>
            <p className="mt-4 text-[9px] font-medium text-[var(--text-muted)] italic">Personal details are managed by HR.</p>
          </SectionCard>

          {/* Residential Address (read-only) + Theme preference (functional) */}
          <SectionCard dotColor="var(--accent-indigo)" icon={MapPin} title="Residential Address">
            <div className="grid grid-cols-1 gap-5">
              <Field label="Full Address" icon={MapPin} value={p.address} />
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
                <Field label="City" value={p.city} />
                <Field label="State" value={p.state} />
                <div className="space-y-1.5 min-w-0">
                  <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Theme Preference</label>
                  <select value={theme} onChange={e => { if (e.target.value !== theme) toggleTheme(); }}
                    className="w-full px-3 py-2.5 rounded-xl text-[12px] font-bold outline-none border bg-[var(--input-bg)] border-[var(--input-border)] text-[var(--text-main)] focus:border-[var(--accent-indigo)] transition-all">
                    <option value="light">light</option>
                    <option value="dark">dark</option>
                  </select>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      </motion.div>
    </div>
  );
};

export default GeneralSection;
