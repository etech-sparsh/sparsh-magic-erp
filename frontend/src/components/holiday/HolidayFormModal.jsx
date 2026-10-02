import React, { useEffect, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, CalendarDays, Save } from 'lucide-react';
import { createHoliday, updateHoliday } from '../../services/holidayApi';
import { useNotification } from '../../context/NotificationContext';

const HOLIDAY_TYPES = ['National', 'Festival', 'Company', 'Optional'];

const emptyForm = { holiday_name: '', holiday_date: '', description: '', holiday_type: 'Company', status: 'active' };

// Add / edit a holiday. `holiday` non-null = edit mode. onSaved refreshes the parent list.
const HolidayFormModal = ({ isOpen, onClose, holiday = null, onSaved }) => {
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    if (holiday) {
      setForm({
        holiday_name: holiday.holiday_name || '',
        holiday_date: holiday.holiday_date || '',
        description: holiday.description || '',
        holiday_type: holiday.holiday_type || 'Company',
        status: holiday.status || 'active',
      });
    } else {
      setForm(emptyForm);
    }
  }, [isOpen, holiday]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.holiday_name.trim()) return showError('Holiday name is required');
    if (!form.holiday_date) return showError('Holiday date is required');

    setSaving(true);
    try {
      if (holiday) {
        await updateHoliday(holiday.id, form);
        showSuccess('Holiday updated');
      } else {
        await createHoliday(form);
        showSuccess('Holiday added');
      }
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save holiday');
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}
          className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-md bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 rounded-t-[24px] border-b border-[var(--border)] flex items-center gap-3 bg-[var(--accent-indigo-bg)]">
            <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shrink-0 shadow-md shadow-[var(--accent-indigo)]/20">
              <CalendarDays size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-[15px] font-black text-[var(--text-main)] leading-tight">{holiday ? 'Edit Holiday' : 'Add Holiday'}</h3>
              <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">Holiday Calendar</p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-full hover:bg-[var(--bg-card)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"><X size={18} /></button>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Holiday Name *</label>
              <input autoFocus value={form.holiday_name} onChange={e => setForm({ ...form, holiday_name: e.target.value })}
                placeholder="e.g. Diwali"
                className="mt-1.5 w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Date *</label>
                <input type="date" value={form.holiday_date} onChange={e => setForm({ ...form, holiday_date: e.target.value })}
                  className="mt-1.5 w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
              </div>
              <div>
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Type</label>
                <select value={form.holiday_type} onChange={e => setForm({ ...form, holiday_type: e.target.value })}
                  className="mt-1.5 w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)]">
                  {HOLIDAY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Description</label>
              <textarea rows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                placeholder="Optional note about this holiday"
                className="mt-1.5 w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] resize-none" />
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Status</label>
              <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}
                className="mt-1.5 w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)]">
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>

            <div className="flex items-center justify-end gap-3 pt-1">
              <button type="button" onClick={onClose} className="px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
              <button type="submit" disabled={saving}
                className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 disabled:opacity-60 transition-all">
                <Save size={14} /> {saving ? 'Saving...' : (holiday ? 'Save Changes' : 'Add Holiday')}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default HolidayFormModal;
