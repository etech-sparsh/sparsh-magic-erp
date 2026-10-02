import React, { useCallback, useEffect, useState } from 'react';
import { User, Pencil, Save, X, Loader2, CheckCircle2, Briefcase } from 'lucide-react';
import { getMyProfile, updateMyProfile } from '../../services/settingsApi';
import { getInitials } from '../tasks/taskDisplayUtils';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { motion } from 'framer-motion';

const DEPARTMENTS = ['HOD', 'Manager', 'Implementor', 'EA', 'MD', 'HR', 'Other'];

// One editable field row (label + value display, or input while editing).
const Field = ({ label, value, editing, children }) => (
  <div className="space-y-1.5">
    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</label>
    {editing ? children : (
      <p className="text-[13px] font-bold text-[var(--text-main)]">{value || <span className="text-[var(--text-muted)] font-medium">Not provided</span>}</p>
    )}
  </div>
);

const inputCls = "w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]";

// Reusable white card with an edit/save/cancel header (matches the screenshot's cards).
const EditableCard = ({ icon: Icon, title, editing, onEdit, onCancel, onSave, saving, children }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
    <div className="flex items-center justify-between mb-5">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]"><Icon size={16} /></div>
        <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-wide">{title}</h2>
      </div>
      {editing ? (
        <div className="flex items-center gap-2">
          <button onClick={onCancel} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]" title="Cancel"><X size={15} /></button>
          <button onClick={onSave} disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-60">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
          </button>
        </div>
      ) : (
        <button onClick={onEdit} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--accent-indigo)]" title="Edit"><Pencil size={15} /></button>
      )}
    </div>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">{children}</div>
  </div>
);

const GeneralTab = () => {
  const { refreshUser } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const [editingGeneral, setEditingGeneral] = useState(false);
  const [editingPro, setEditingPro] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [savingPro, setSavingPro] = useState(false);
  const [form, setForm] = useState({});

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getMyProfile();
      setProfile(res.data);
      setForm(res.data);
    } catch {
      showError('Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, [showError]);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 size={22} className="animate-spin text-[var(--accent-indigo)]" />
      </div>
    );
  }

  const p = profile || {};
  const isActive = p.is_active !== false;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* ── Profile card ── */}
      <div className="lg:col-span-1">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm flex flex-col items-center text-center">
          <div className="relative">
            <div className="w-24 h-24 rounded-2xl bg-[var(--avatar-bg)] flex items-center justify-center text-white text-3xl font-black shadow-lg">
              {getInitials(p.full_name || p.first_name || 'U')}
            </div>
            <span className={`absolute -bottom-1 -right-1 px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-widest border-2 border-[var(--bg-card)] ${isActive ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]' : 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'}`}>
              {isActive ? 'Active' : 'Inactive'}
            </span>
          </div>
          <h1 className="mt-4 text-lg font-black text-[var(--text-main)] tracking-tight">{p.full_name || '—'}</h1>
          <p className="text-[12px] font-bold text-[var(--text-muted)]">{p.designation || 'No designation'}</p>
          <p className="text-[11px] font-medium text-[var(--text-muted)] mt-0.5">{p.department || 'No department'}</p>
          <span className="mt-3 px-3 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10px] font-black uppercase tracking-widest rounded-full border border-[var(--accent-indigo-border)]">
            {p.role || 'user'}
          </span>
          <div className="mt-4 w-full flex items-center justify-center gap-2 text-[11px] font-bold text-[var(--text-muted)]">
            <CheckCircle2 size={13} className="text-[var(--accent-green)]" /> {p.email}
          </div>
        </div>
      </div>

      {/* ── Editable cards ── */}
      <div className="lg:col-span-2 space-y-6">
        <EditableCard icon={User} title="General Information" editing={editingGeneral}
          onEdit={() => setEditingGeneral(true)} onCancel={cancelGeneral} onSave={saveGeneral} saving={savingGeneral}>
          <Field label="First Name" value={p.first_name} editing={editingGeneral}>
            <input className={inputCls} value={form.first_name || ''} onChange={e => setField('first_name', e.target.value)} placeholder="First name" />
          </Field>
          <Field label="Last Name" value={p.last_name} editing={editingGeneral}>
            <input className={inputCls} value={form.last_name || ''} onChange={e => setField('last_name', e.target.value)} placeholder="Last name" />
          </Field>
          <Field label="Primary Mobile" value={p.mobile} editing={editingGeneral}>
            <input className={inputCls} value={form.mobile || ''} onChange={e => setField('mobile', e.target.value)} placeholder="Primary mobile" />
          </Field>
          <Field label="Emergency Mobile" value={p.emergency_mobile} editing={editingGeneral}>
            <input className={inputCls} value={form.emergency_mobile || ''} onChange={e => setField('emergency_mobile', e.target.value)} placeholder="Emergency mobile" />
          </Field>
        </EditableCard>

        <EditableCard icon={Briefcase} title="Professional Profile" editing={editingPro}
          onEdit={() => setEditingPro(true)} onCancel={cancelPro} onSave={savePro} saving={savingPro}>
          <Field label="Designation" value={p.designation} editing={editingPro}>
            <input className={inputCls} value={form.designation || ''} onChange={e => setField('designation', e.target.value)} placeholder="Designation" />
          </Field>
          <Field label="Department" value={p.department} editing={editingPro}>
            <select className={inputCls} value={form.department || ''} onChange={e => setField('department', e.target.value)}>
              <option value="">Select department...</option>
              {DEPARTMENTS.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Reporting Manager" value={p.reporting_manager} editing={editingPro}>
            <input className={inputCls} value={form.reporting_manager || ''} onChange={e => setField('reporting_manager', e.target.value)} placeholder="Reporting manager" />
          </Field>
          <Field label="Joining Date" value={p.joining_date} editing={editingPro}>
            <input type="date" className={inputCls} value={form.joining_date || ''} onChange={e => setField('joining_date', e.target.value)} />
          </Field>
        </EditableCard>
      </div>
    </motion.div>
  );
};

export default GeneralTab;
