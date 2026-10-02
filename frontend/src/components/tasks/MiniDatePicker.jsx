import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, ChevronLeft, ChevronRight, Save } from 'lucide-react';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const isSameDay = (a, b) => a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

// Hand-rolled month-grid date/time picker (no date-picker library installed in this
// project) matching the reference "Select Due Date" popover.
// `holidayDates`: array of "YYYY-MM-DD" strings. `weeklyOffs`: array of weekday numbers
// (0=Sun) to block. `onBlocked(message)`: called when a blocked date is picked.
// `blockHolidays`: when true (default) holidays are un-selectable (due/start pickers); when
// false, holidays are still visibly marked but remain selectable — used for the Repeat End
// Date, which is only a series boundary (the recurring engine skips holiday occurrences).
// `disablePast`: when true, any date before today is un-selectable — used for due-date fields.
// `remarkLabel`: when set, a remark box is shown under the picker and its text is passed as the
// 2nd argument to `onApply(iso, remark)` — used by the assigner's Reopen action, which carries
// both a new deadline and an optional reason. `remarkRequired` (opt-in) gates Done on it.
// `dateOnly`: when true, the DATE/TIME tabs and the time input are hidden — only a date is
// picked. Used by the Todo Repeat End Date, where the series stop is decided purely by date
// (the time is ignored), so a time picker would only mislead.
const MiniDatePicker = ({ isOpen, onClose, value, onApply, title = 'Select Due Date', holidayDates = [], weeklyOffs = [], onBlocked, blockHolidays = true, disablePast = false, remarkLabel = '', remarkRequired = false, dateOnly = false }) => {
  const [viewMonth, setViewMonth] = useState(0);
  const [viewYear, setViewYear] = useState(2000);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [time, setTime] = useState('12:00');
  const [tab, setTab] = useState('date');
  const [remark, setRemark] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    const d = value ? new Date(value) : new Date();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setViewMonth(d.getMonth());
    setViewYear(d.getFullYear());
    setSelectedDate(d);
    setTime(`${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`);
    setTab('date');
    setRemark('');
  }, [isOpen, value]);

  if (!isOpen) return null;

  const holidaySet = new Set(holidayDates);
  const keyOf = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  const today = new Date();
  const todayKey = keyOf(today);
  const blockedInfo = (dt) => {
    if (disablePast && keyOf(dt) < todayKey) return { blocked: true, msg: 'Past dates cannot be selected.', label: 'Past date' };
    const isHoliday = holidaySet.has(keyOf(dt));
    if (isHoliday && blockHolidays) return { blocked: true, holiday: true, msg: 'Holiday detected! Please select another date.', label: 'Holiday' };
    if (weeklyOffs.includes(dt.getDay())) return { blocked: true, msg: 'Weekly off! Please select another date.', label: 'Weekly off' };
    // Marked but selectable (repeat end date): the recurring engine skips holiday occurrences.
    if (isHoliday) return { blocked: false, holiday: true, label: 'Holiday' };
    return { blocked: false };
  };

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay();

  const cells = [];
  for (let i = 0; i < firstDayOfWeek; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const navigate = (delta) => {
    let m = viewMonth + delta, y = viewYear;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    setViewMonth(m); setViewYear(y);
  };

  const handleApply = () => {
    const sd = new Date(viewYear, viewMonth, selectedDate.getDate());
    const info = blockedInfo(sd);
    if (info.blocked) { onBlocked?.(info.msg); return; }
    if (remarkRequired && !remark.trim()) { onBlocked?.(`${remarkLabel || 'Remark'} is required.`); return; }
    const [h, min] = time.split(':').map(Number);
    const final = new Date(viewYear, viewMonth, selectedDate.getDate(), h, min);
    onApply(final.toISOString(), remark.trim());
    onClose();
  };

  // Portal to <body> so the picker escapes any transformed / overflow-hidden ancestor
  // (e.g. the framer-motion Event Architect modal), which would otherwise make this
  // `fixed` overlay resolve relative to — and get clipped by — that modal card.
  return createPortal(
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{title}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="p-5">
            {!dateOnly && (
              <div className="flex bg-[var(--input-bg)] p-1 rounded-full mb-4">
                {['date', 'time'].map(t => (
                  <button type="button" key={t} onClick={() => setTab(t)}
                    className={`flex-1 py-2 rounded-full text-[10px] font-black uppercase tracking-widest transition-all ${tab === t ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
                    {t}
                  </button>
                ))}
              </div>
            )}

            {(dateOnly || tab === 'date') ? (
              <>
                <div className="flex items-center justify-between mb-4">
                  <span className="px-4 py-1.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-full text-[11px] font-black uppercase tracking-widest">
                    {new Date(viewYear, viewMonth).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
                  </span>
                  <div className="flex gap-1.5">
                    <button type="button" onClick={() => navigate(-1)} className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)]"><ChevronLeft size={14} /></button>
                    <button type="button" onClick={() => navigate(1)} className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)]"><ChevronRight size={14} /></button>
                  </div>
                </div>
                <div className="grid grid-cols-7 gap-1 text-center mb-1">
                  {WEEKDAYS.map(w => <span key={w} className="text-[9px] font-black text-[var(--text-muted)] uppercase">{w}</span>)}
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {cells.map((d, i) => {
                    if (!d) return <span key={i} />;
                    const cellDate = new Date(viewYear, viewMonth, d);
                    const isToday = isSameDay(cellDate, today);
                    const isSelected = isSameDay(cellDate, selectedDate) && !isToday;
                    const info = blockedInfo(cellDate);
                    const onCell = () => (info.blocked ? onBlocked?.(info.msg) : setSelectedDate(cellDate));
                    return (
                      <button type="button" key={i} onClick={onCell} title={info.label}
                        className={`relative aspect-square flex items-center justify-center rounded-full text-[11px] font-bold transition-all ${
                          info.blocked ? 'text-[var(--accent-red)] bg-[var(--accent-red-bg)] opacity-70 cursor-not-allowed line-through'
                            : isToday ? 'bg-[var(--accent-indigo)] text-white'
                            : isSelected ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                            : info.holiday ? 'text-[var(--accent-red)] bg-[var(--accent-red-bg)]'
                            : 'text-[var(--text-main)]'
                        }`}>
                        {d}
                        {info.holiday && !info.blocked && (
                          <span className="absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[var(--accent-red)]" />
                        )}
                      </button>
                    );
                  })}
                </div>
                {holidayDates.length > 0 && (
                  <div className="mt-3 flex items-center gap-1.5 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <span className="w-2 h-2 rounded-full bg-[var(--accent-red)]" /> Holiday
                  </div>
                )}
              </>
            ) : (
              <input type="time" value={time} onChange={e => setTime(e.target.value)}
                className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[14px] font-bold outline-none text-center" />
            )}

            {remarkLabel && (
              <div className="mt-4">
                <label className="block mb-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  {remarkLabel}{remarkRequired && <span className="text-[var(--accent-red)]"> *</span>}
                </label>
                <textarea value={remark} onChange={e => setRemark(e.target.value)} rows={3}
                  placeholder="Explain why the task is being sent back..."
                  className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none resize-none focus:border-[var(--accent-indigo)]" />
              </div>
            )}
          </div>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <button type="button" onClick={handleApply} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
              <Save size={13} /> Done
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body
  );
};

export default MiniDatePicker;
