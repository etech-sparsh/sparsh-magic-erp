import React, { useEffect, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  X, Plus, ChevronDown, Paperclip, Users, CalendarClock, Flag,
  Tag, Bell, ShieldCheck, FileCheck2, CheckCircle2, Circle, Clock,
  Link2, Tags as TagsIcon, Save, Mic, Trash2,
} from 'lucide-react';
import api from '../../services/api';
import { createTask, updateTask, uploadTaskAttachment, deleteTaskAttachment } from '../../services/taskApi';
import { createTaskCategory, createTaskTag } from '../../services/taskMetaApi';
import { getHolidays } from '../../services/holidayApi';
import { useAuth } from '../../context/AuthContext';
import { canManageTaskSettings } from '../../utils/taskAccess';
import { useNotification } from '../../context/NotificationContext';
import PickerModal from './PickerModal';
import MiniDatePicker from './MiniDatePicker';
import ReminderModal from '../calendar/ReminderModal';
import TaskTagsModal from './TaskTagsModal';
import VoiceNoteModal from './VoiceNoteModal';
import { formatDate, formatDateTime, getAttachmentKind, isMdUser } from './taskDisplayUtils';

const PRIORITY_CYCLE = ['Low', 'Normal', 'High'];

// Matches the working values in CalendarPage.jsx's recurring-event engine exactly
// ("periodic" is the real stored value behind the "Periodically" label; Weekly/Monthly
// map 1:1). The recurrence-generation engine (calendar_events.py) now also auto-generates
// Custom occurrences, stepping by repeat_interval in repeat_data.customUnit (Days/Weeks/Months).
// Yearly is still reference-only: the backend checks for "Annually", not "Yearly", so it
// won't auto-generate future occurrences yet.
const REPEAT_OPTIONS = [
  { value: 'Daily', label: 'Daily' },
  { value: 'Weekly', label: 'Weekly' },
  { value: 'Monthly', label: 'Monthly' },
  { value: 'Yearly', label: 'Yearly' },
  { value: 'periodic', label: 'Periodically' },
  { value: 'Custom', label: 'Custom' },
];

const emptyForm = {
  title: '',
  description: '',
  category: '',
  tags: [],
  end: '',
  repeat: 'Does not repeat',
  start: '',
  repeat_end_date: '',
  repeat_interval: 1,
  repeat_data: { monthlyDates: [], weekdays: [], lastDay: false },
  priority: 'Normal',
  target_staff_id: [],
  watchers: [],
  assignment_mode: 'combined', // combined (shared task) | separate (one task per assignee)
  evidence_required: false,
  verification_required: false,
  reminders: [],
};

// Reconciles whatever shape repeat_data comes back as (including the older single-value
// day_of_month/weekday shape saved by an earlier version of this form) into the
// { monthlyDates: [], weekdays: [], lastDay } shape this form now uses, so editing an
// older task doesn't crash and its prior selection still shows correctly.
const normalizeRepeatData = (data) => {
  const base = { monthlyDates: [], weekdays: [], lastDay: false };
  if (!data) return base;
  if (Array.isArray(data.monthlyDates) || Array.isArray(data.weekdays)) {
    return { ...base, ...data };
  }
  if (data.day_of_month === 'last') return { ...base, lastDay: true };
  if (typeof data.day_of_month === 'number') return { ...base, monthlyDates: [data.day_of_month] };
  if (typeof data.weekday === 'number') return { ...base, weekdays: [data.weekday] };
  return base;
};

const customUnitLabel = (unit, interval) => {
  const singular = { Weeks: 'Week', Months: 'Month' }[unit || 'Months'];
  return (interval || 1) === 1 ? singular : (unit || 'Months');
};

const formatFileSize = (bytes) => (bytes || bytes === 0) ? `${(bytes / (1024 * 1024)).toFixed(2)} MB` : null;

// Creates/edits type:"task" calendar_event docs via the existing /calendar/events API
// (same one the Calendar page's "Architect Tasks" panel uses), so tasks made here also
// show up on the Calendar page and vice versa. `end` is the task's own due date/time
// (top-level field); `start`/`repeat_end_date` below are the separate recurrence-series
// bounds, matching the existing recurring-event engine's fields exactly.
const TaskFormModal = ({ isOpen, onClose, onSaved, task = null, categories = [], tags: availableTags = [], groupId = null, parentId = null, onTaxonomyChanged }) => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState(emptyForm);
  const [staffOptions, setStaffOptions] = useState([]);
  // Who may be kept IN LOOP is a wider set than who may be ASSIGNED to. The backend rank rule
  // (calendar_events.py: get_rank_ineligible_assignees) is "assignees only" — a client HR may
  // loop in their MD even though they may not assign to them — so the loop picker reads the
  // full directory while the assign picker keeps the rank-filtered list.
  const [loopOptions, setLoopOptions] = useState([]);
  const [saving, setSaving] = useState(false);

  const [checklistOpen, setChecklistOpen] = useState(false);
  const [checklist, setChecklist] = useState([]);
  const [newChecklistItem, setNewChecklistItem] = useState('');

  const [attachments, setAttachments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [uploading, setUploading] = useState(false);

  const [pickerOpen, setPickerOpen] = useState(null); // 'assignee' | 'inLoop' | 'category' | null
  const [deadlinePickerOpen, setDeadlinePickerOpen] = useState(false);
  const [startDatePickerOpen, setStartDatePickerOpen] = useState(false);
  const [repeatEndPickerOpen, setRepeatEndPickerOpen] = useState(false);
  const [reminderModalOpen, setReminderModalOpen] = useState(false);

  // Holidays + weekly-offs block task due/start dates in the picker. weeklyOffs defaults to
  // Sunday (0) — there is no persisted per-user weekly-off setting in the backend yet.
  const [holidayDates, setHolidayDates] = useState([]);
  const WEEKLY_OFFS = [0];
  const [repeatDropdownOpen, setRepeatDropdownOpen] = useState(false);

  // Repeat ON turns the task into a Recurring Checklist: it renews itself every day at
  // 12:00 AM, each occurrence is live until 11:59 PM, and it carries no deadline at all.
  const isRecurring = form.repeat !== 'Does not repeat';
  const [customIntervalOpen, setCustomIntervalOpen] = useState(false);
  const [customUnitOpen, setCustomUnitOpen] = useState(false);
  const [tagsModalOpen, setTagsModalOpen] = useState(false);
  const [voiceNoteOpen, setVoiceNoteOpen] = useState(false);

  // Fetch holidays when the form opens so the due/start date pickers can block them.
  useEffect(() => {
    if (!isOpen) return;
    getHolidays().then(res => {
      setHolidayDates((res.data || []).map(h => h.holiday_date).filter(Boolean));
    }).catch(() => setHolidayDates([]));
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    // Only internal Sparsh users are assignable / can be added In Loop — client-side users
    // must never appear here (backend also enforces this on save). See /tasks/assignable-users.
    api.get('/tasks/assignable-users').then(res => setStaffOptions(res.data || [])).catch(() => setStaffOptions([]));
    api.get('/tasks/assignable-users?all=true').then(res => setLoopOptions(res.data || [])).catch(() => setLoopOptions([]));

    if (task) {
      setForm({
        title: task.title || '',
        description: task.description || '',
        category: task.category || '',
        tags: task.tags || [],
        end: task.end || '',
        repeat: task.frequency || task.repeat || 'Does not repeat',
        start: task.start || '',
        repeat_end_date: task.repeatEndDate || '',
        repeat_interval: task.repeatInterval || 1,
        repeat_data: normalizeRepeatData(task.repeatData),
        priority: task.priority || 'Normal',
        target_staff_id: task.assignedTo || task.target_staff_id || [],
        watchers: task.watchers || [],
        assignment_mode: 'combined', // edit acts on the existing single doc; mode applies to create only

        evidence_required: task.evidenceRequired || false,
        verification_required: task.verificationRequired || false,
        reminders: task.reminders || [],
      });
      setChecklist(task.checklist || []);
      setAttachments(task.attachments || []);
    } else {
      // New task: default the recurrence Start Date to today (the day it's being created)
      setForm({ ...emptyForm, start: new Date().toISOString() });
      setChecklist([]);
      setAttachments([]);
    }
    setPendingFiles([]);
    setChecklistOpen(false);
    setNewChecklistItem('');
    setPickerOpen(null);
  }, [isOpen, task]);

  if (!isOpen) return null;

  const addChecklistItem = () => {
    const title = newChecklistItem.trim();
    if (!title) return;
    setChecklist(c => [...c, { id: `new-${Date.now()}`, title, completed: false }]);
    setNewChecklistItem('');
  };

  const removeChecklistItem = (id) => setChecklist(c => c.filter(item => item.id !== id));

  // Creating a category/tag is an internal task-settings action (the backend restricts it to
  // internal admins). Company users on a Delegation-enabled company pick from the existing
  // list; a brand-new name they type is still persisted server-side when the task itself is
  // saved, so nothing is lost — this just avoids firing a call that would 403 for them.
  const canManageTaxonomy = canManageTaskSettings(user);

  // Category/tags picked here are persisted immediately via the task_categories/task_tags
  // APIs (not just local form state) so they survive a refresh and show up in every other
  // task list/create view right away — see taskMetaApi.js. Re-saving an existing name is a
  // harmless no-op (the backend get-or-creates by case-insensitive match).
  const handleCategoryApply = async (val) => {
    const name = (val || '').trim();
    if (!name) return;
    setForm(f => ({ ...f, category: name }));
    const isNew = !categories.some(c => c.toLowerCase() === name.toLowerCase());
    if (isNew && canManageTaxonomy) {
      try {
        await createTaskCategory(name);
        onTaxonomyChanged?.();
      } catch (err) {
        showError(err.response?.data?.detail || 'Failed to save new category');
      }
    }
  };

  // "Add More" in the category picker: create + refresh the list only. Deliberately does
  // NOT touch form.category, so the currently-selected category is preserved (the new one
  // is just appended and available to pick). Backend get-or-creates, so re-adds are no-ops.
  const handleCategoryAddNew = async (name) => {
    const n = (name || '').trim();
    if (!n || !canManageTaxonomy) return;
    const exists = categories.some(c => c.toLowerCase() === n.toLowerCase());
    try {
      if (!exists) await createTaskCategory(n);
      onTaxonomyChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save new category');
    }
  };

  const handleTagsApply = async (selectedTags) => {
    setForm(f => ({ ...f, tags: selectedTags }));
    const newTags = selectedTags.filter(t => !availableTags.some(a => a.toLowerCase() === t.toLowerCase()));
    if (newTags.length && canManageTaxonomy) {
      try {
        await Promise.all(newTags.map(t => createTaskTag(t)));
        onTaxonomyChanged?.();
      } catch (err) {
        showError(err.response?.data?.detail || 'Failed to save new tag');
      }
    }
  };

  // Multiple monthly dates can be selected (e.g. 3, 4, 5); "Last Day" is mutually
  // exclusive with picking specific dates, matching the reference behavior.
  const toggleMonthlyDate = (day) => {
    setForm(f => {
      const current = f.repeat_data.monthlyDates || [];
      const monthlyDates = current.includes(day) ? current.filter(d => d !== day) : [...current, day].sort((a, b) => a - b);
      return { ...f, repeat_data: { ...f.repeat_data, monthlyDates, lastDay: false } };
    });
  };

  const toggleLastDay = () => {
    setForm(f => ({ ...f, repeat_data: { ...f.repeat_data, lastDay: !f.repeat_data.lastDay, monthlyDates: [] } }));
  };

  const toggleWeekday = (weekdayIndex) => {
    setForm(f => {
      const current = f.repeat_data.weekdays || [];
      const weekdays = current.includes(weekdayIndex) ? current.filter(d => d !== weekdayIndex) : [...current, weekdayIndex].sort();
      return { ...f, repeat_data: { ...f.repeat_data, weekdays } };
    });
  };

  // Shared by file-input attachments, image uploads, and the voice note recorder: an
  // existing task uploads immediately, a not-yet-created one queues the file for upload
  // right after createTask() succeeds (see handleSubmit).
  const attachFile = async (file) => {
    if (task) {
      setUploading(true);
      try {
        const res = await uploadTaskAttachment(task.id, file);
        setAttachments(a => [...a, res.data]);
        showSuccess('File attached');
      } catch (err) {
        showError(err.response?.data?.detail || 'Failed to attach file');
      } finally {
        setUploading(false);
      }
    } else {
      setPendingFiles(p => [...p, file]);
    }
  };

  const handleFileChosen = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    await attachFile(file);
  };

  const removePendingFile = (idx) => setPendingFiles(p => p.filter((_, i) => i !== idx));

  // Link-type entries are plain data (saved on the next form submit, like the rest of the
  // task fields), so they can just be dropped from local state. File-type entries were
  // already persisted the moment they were uploaded (see attachFile), so removing one has
  // to call the backend too.
  const handleRemoveAttachment = async (attachment) => {
    if (attachment.type !== 'link' && task) {
      try {
        await deleteTaskAttachment(task.id, attachment.id);
      } catch (err) {
        showError(err.response?.data?.detail || 'Failed to remove attachment');
        return;
      }
    }
    setAttachments(a => a.filter(x => x.id !== attachment.id));
  };

  const validate = () => {
    if (!form.title.trim()) return 'Task title is required';
    if (!form.category.trim()) return 'Category is required';
    // A deadline is mandatory when delegating (assigning to others) so every assignee has a due date.
    // Only a one-time task has a deadline to require. A Recurring Checklist is due at the
    // end of each of its own days, so there is nothing for the user to set.
    if (!isRecurring && form.target_staff_id.length && !form.end) {
      return 'Deadline is required when delegating a task';
    }
    // Due date can't be in the past. Only enforced on create — editing an already-overdue
    // task (a normal, common state) must still be possible without forcing a date change.
    if (!isRecurring && !task && form.end) {
      const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
      if (new Date(form.end) < todayStart) return 'Due date cannot be in the past';
    }
    if (form.repeat !== 'Does not repeat') {
      if (!form.start) return 'Start Date is required when Repeat is enabled';
      if (!form.repeat) return 'Frequency is required when Repeat is enabled';
      if (form.repeat === 'Monthly' && !form.repeat_data.lastDay && form.repeat_data.monthlyDates.length === 0) {
        return 'Select at least one date (or Last Day) for a Monthly repeat';
      }
      if (form.repeat === 'Custom' && (form.repeat_data.customUnit || 'Months') === 'Months' && !form.repeat_data.lastDay && form.repeat_data.monthlyDates.length === 0) {
        return 'Select at least one date (or Last Day) for a Custom repeat';
      }
      if (form.repeat_end_date && new Date(form.repeat_end_date) < new Date(form.start)) {
        return 'End Date cannot be before Start Date';
      }
    }
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) return showError(validationError);

    // A checklist item typed but not confirmed with Enter/Add would otherwise be silently
    // dropped on save (it never made it into `checklist` state) — commit it now instead.
    const pendingItemTitle = newChecklistItem.trim();
    const checklistToSave = pendingItemTitle
      ? [...checklist, { id: `new-${Date.now()}`, title: pendingItemTitle, completed: false }]
      : checklist;
    if (pendingItemTitle) {
      setChecklist(checklistToSave);
      setNewChecklistItem('');
    }

    setSaving(true);
    try {
      const isRepeating = form.repeat !== 'Does not repeat';
      const payload = {
        title: form.title,
        description: form.description,
        category: form.category,
        tags: form.tags,
        end: form.end ? new Date(form.end).toISOString() : null,
        repeat: form.repeat,
        repeat_end_date: isRepeating && form.repeat_end_date ? new Date(form.repeat_end_date).toISOString() : null,
        repeat_interval: (form.repeat === 'periodic' || form.repeat === 'Custom') ? (form.repeat_interval || 1) : undefined,
        repeat_data: isRepeating ? form.repeat_data : undefined,
        priority: form.priority,
        assigned_to: form.target_staff_id.length ? 'other' : 'myself',
        target_staff_id: form.target_staff_id,
        watchers: form.watchers,
        // Tag the task to a group when opened from the Groups workspace (else keep the
        // task's existing group on edit, or ungrouped for a normal create).
        group_id: groupId || task?.groupId || undefined,
        // Link this task to a parent when opened as "Add Subtask" (else keep existing on edit).
        parent_task_id: parentId || task?.parentTaskId || undefined,
        evidence_required: form.evidence_required,
        verification_required: form.verification_required,
        reminders: form.reminders,
        checklist: checklistToSave.map(c => ({
          id: c.id,
          title: c.title,
          completed: c.completed || false,
          completed_at: c.completed_at || null,
        })),
        attachments: attachments.filter(a => a.type === 'link'), // link-attachments are plain data, safe to send with the task doc
      };
      if (task) {
        if (form.start) payload.start = new Date(form.start).toISOString();
        await updateTask(task.id, payload);
        showSuccess('Task updated');
      } else {
        // `start` seeds the existing recurrence engine (calendar_events.py) when repeating;
        // otherwise it's just the task's start/creation reference point. Defaults to today
        // (set when the modal opened) but honors whatever the user picked in the Start Date chip.
        payload.start = new Date(form.start || Date.now()).toISOString();
        // Assignment mode only matters for a multi-assignee create; the backend ignores it
        // otherwise. "separate" returns `ids` (one task per assignee); "combined" returns `id`.
        payload.assignment_mode = form.target_staff_id.length > 1 ? (form.assignment_mode || 'combined') : 'combined';
        const res = await createTask(payload);
        const newIds = res.data?.ids || (res.data?.id ? [res.data.id] : []);
        if (newIds.length && pendingFiles.length) {
          // Each separate task is independent, so attachment(s) go onto every created task.
          for (const id of newIds) {
            for (const file of pendingFiles) {
              await uploadTaskAttachment(id, file).catch(() => {});
            }
          }
        }
        showSuccess(newIds.length > 1 ? `Created ${newIds.length} tasks` : 'Task created');
      }
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save task');
    } finally {
      setSaving(false);
    }
  };

  // Resolve names across BOTH directories: a watcher may be someone the assign list excludes
  // (an MD above the creator's rank), and they must not render as blank.
  // Plain Map, not useMemo: this sits after the early `if (!isOpen) return null`, so a hook
  // here would break hook order. Two short arrays — the cost is nil.
  const directory = new Map([...staffOptions, ...loopOptions].map(u => [u._id, u]));
  const nameOf = (id) => directory.get(id)?.full_name || directory.get(id)?.email;
  const assigneeNames = form.target_staff_id.map(nameOf).filter(Boolean);
  const watcherNames = form.watchers.map(nameOf).filter(Boolean);

  const toItem = (u) => ({ id: u._id, primary: u.full_name || u.email, secondary: u.email });
  const staffItems = staffOptions.filter(u => u._id !== user?._id).map(toItem);
  // The loop list falls back to the assign list until the wider fetch lands, so the picker is
  // never momentarily empty.
  const loopSource = loopOptions.length ? loopOptions : staffOptions;
  const loopItems = loopSource.filter(u => u._id !== user?._id).map(toItem);
  // "Include MD" — built from the SAME list the loop picker renders, so every id it stages is
  // one the user could have ticked by hand, and self can never be looped in as their own MD.
  const mdIds = loopSource
    .filter(u => u._id !== user?._id && isMdUser(u))
    .map(u => u._id);
  const categoryItems = Array.from(new Set([...categories, form.category].filter(Boolean))).map(c => ({ id: c, primary: c }));

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl"
        >
          {/* Header */}
          <div className="px-6 py-4 rounded-t-[24px] border-b border-[var(--border)] flex items-center gap-3.5 sticky top-0 bg-[var(--accent-indigo-bg)] z-10">
            <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shrink-0 shadow-md shadow-[var(--accent-indigo)]/20">
              <Plus size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-[15px] font-black text-[var(--text-main)] leading-tight">{task ? 'Edit Task' : 'Assign New Task'}</h3>
              <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">{task ? 'Update Delegation' : 'New Delegation'}</p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-full hover:bg-[var(--bg-card)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"><X size={18} /></button>
          </div>

          <form onSubmit={handleSubmit} onClick={() => { setRepeatDropdownOpen(false); setCustomIntervalOpen(false); setCustomUnitOpen(false); }}>
            {/* Title */}
            <div className="px-6 pt-4 pb-3 border-b border-[var(--border)] transition-colors focus-within:border-[var(--accent-indigo)]">
              <input autoFocus value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}
                placeholder="Add Task Title *..."
                className="w-full text-[15px] font-bold bg-transparent outline-none placeholder:text-[var(--text-muted)] placeholder:font-semibold placeholder:opacity-50 text-[var(--text-main)]" />
            </div>

            {/* Description */}
            <div className="px-6 pt-3 pb-3 border-b border-[var(--border)] transition-colors focus-within:border-[var(--accent-indigo)]">
              <textarea rows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                placeholder="Write task details, instructions or goals here *..."
                className="w-full bg-transparent outline-none text-[12px] font-medium leading-relaxed placeholder:text-[var(--text-muted)] placeholder:opacity-50 text-[var(--text-main)] resize-none" />
            </div>

            {/* Check Points (formerly "Checklist") */}
            <div className="px-6 pt-4">
              <button type="button" onClick={() => setChecklistOpen(o => !o)}
                className="w-full flex items-center justify-between text-[12px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">
                <span className="flex items-center gap-1.5"><Plus size={14} /> Add Check Points {checklist.length > 0 && `(${checklist.length})`}</span>
                <ChevronDown size={16} className={`transition-transform ${checklistOpen ? 'rotate-180' : ''}`} />
              </button>
              {checklistOpen && (
                <div className="mt-3 space-y-2">
                  {checklist.map(item => (
                    <div key={item.id} className="flex items-center gap-2 bg-[var(--input-bg)] rounded-lg px-3 py-2">
                      <span className="flex-1 text-[12px] font-bold text-[var(--text-main)] truncate">{item.title}</span>
                      <button type="button" onClick={() => removeChecklistItem(item.id)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]"><X size={13} /></button>
                    </div>
                  ))}
                  <div className="flex items-center gap-2">
                    <input value={newChecklistItem} onChange={e => setNewChecklistItem(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addChecklistItem(); } }}
                      placeholder="Add a sub-task / checkpoint..."
                      className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                    <button type="button" onClick={addChecklistItem} className="px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[11px] font-black">Add</button>
                  </div>
                </div>
              )}
            </div>

            {/* Tags (selected via Extra Options -> Add Tags) */}
            {form.tags.length > 0 && (
              <div className="px-6 pt-4 flex flex-wrap gap-2">
                {form.tags.map(tag => (
                  <span key={tag} onClick={() => setTagsModalOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-green)] text-white border-[var(--accent-green)] cursor-pointer">
                    <TagsIcon size={11} /> {tag}
                  </span>
                ))}
              </div>
            )}

            {/* Attachments */}
            <div className="px-6 pt-5">
              <div className="flex items-center justify-between mb-2">
                <span className="flex items-center gap-1.5 text-[11px] font-black text-[var(--accent-green)] uppercase tracking-widest">
                  <Paperclip size={13} /> Attachments ({attachments.length + pendingFiles.length})
                </span>
              </div>
              {(attachments.length > 0 || pendingFiles.length > 0) && (
                <div className="mb-2 space-y-2">
                  {attachments.map(a => {
                    // Uploaded files can preview inline: audio → player, image → thumbnail;
                    // links/docs stay as an open-in-new-tab link (browser previews the doc).
                    const kind = a.type === 'link' ? 'link' : getAttachmentKind(a.name);
                    return (
                      <div key={a.id} className="flex items-center gap-3 px-4 py-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl">
                        {kind === 'link' ? <Link2 size={16} className="shrink-0 text-[var(--accent-green)]" /> : <Paperclip size={16} className="shrink-0 text-[var(--accent-green)]" />}
                        <div className="min-w-0 flex-1">
                          <a href={a.url} target="_blank" rel="noreferrer" className="block">
                            <p className="text-[12px] font-bold text-[var(--text-main)] truncate hover:text-[var(--accent-indigo)]">{a.name}</p>
                            {formatFileSize(a.size) && <p className="text-[10px] font-semibold text-[var(--text-muted)]">{formatFileSize(a.size)}</p>}
                          </a>
                          {kind === 'audio' && <audio className="mt-2 w-full h-9" controls src={a.url} />}
                          {kind === 'image' && (
                            <a href={a.url} target="_blank" rel="noreferrer">
                              <img src={a.url} alt={a.name} className="mt-2 max-h-32 rounded-lg border border-[var(--border)]" />
                            </a>
                          )}
                        </div>
                        <button type="button" onClick={() => handleRemoveAttachment(a)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] shrink-0"><Trash2 size={15} /></button>
                      </div>
                    );
                  })}
                  {pendingFiles.map((f, i) => {
                    // Not-yet-uploaded files (incl. a fresh voice note) preview from a local
                    // object URL so the user can review/listen before saving.
                    const kind = getAttachmentKind(f.name);
                    const localUrl = (kind === 'audio' || kind === 'image') ? URL.createObjectURL(f) : null;
                    return (
                      <div key={i} className="flex items-center gap-3 px-4 py-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl">
                        <Paperclip size={16} className="shrink-0 text-[var(--accent-green)]" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[12px] font-bold text-[var(--text-main)] truncate">{f.name}</p>
                          <p className="text-[10px] font-semibold text-[var(--text-muted)]">{formatFileSize(f.size)} · will upload on save</p>
                          {kind === 'audio' && localUrl && <audio className="mt-2 w-full h-9" controls src={localUrl} />}
                          {kind === 'image' && localUrl && <img src={localUrl} alt={f.name} className="mt-2 max-h-32 rounded-lg border border-[var(--border)]" />}
                        </div>
                        <button type="button" onClick={() => removePendingFile(i)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] shrink-0"><Trash2 size={15} /></button>
                      </div>
                    );
                  })}
                </div>
              )}
              <label className="flex flex-col items-center justify-center gap-1.5 py-6 border-2 border-dashed border-[var(--border)] rounded-2xl cursor-pointer hover:border-[var(--accent-indigo)] transition-colors">
                <Paperclip size={20} className="text-[var(--text-muted)] opacity-50" />
                <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{uploading ? 'Uploading...' : 'Click or drag files to attach'}</span>
                <input type="file" className="hidden" onChange={handleFileChosen} disabled={uploading} />
              </label>
            </div>

            {/* Chips */}
            <div className="px-6 pt-5 flex flex-wrap gap-2">
              <button type="button" onClick={() => setPickerOpen('assignee')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.target_staff_id.length ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                <Users size={12} /> {assigneeNames.length ? assigneeNames.join(', ') : 'Assignee *'}
              </button>

{/* A Recurring Checklist has no deadline — each occurrence owns its own day and
                  closes at 11:59 PM — so the control is hidden rather than shown disabled. */}
              {!isRecurring && (
                <button type="button" onClick={() => setDeadlinePickerOpen(true)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.end ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  <CalendarClock size={12} /> {form.end ? formatDateTime(form.end) : (form.target_staff_id.length ? 'Set Deadline *' : 'Set Deadline')}
                </button>
              )}

              <button type="button" onClick={() => setForm(f => ({ ...f, priority: PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(f.priority) + 1) % 3] }))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border border-[var(--accent-indigo)] text-[var(--accent-indigo)]">
                <Flag size={12} /> {form.priority}
              </button>

              <button type="button" onClick={() => setPickerOpen('category')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.category ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                <Tag size={12} /> {form.category || 'Category *'}
              </button>

              <button type="button" onClick={() => setPickerOpen('inLoop')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.watchers.length ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                <Bell size={12} /> {watcherNames.length ? `In Loop (${watcherNames.length})` : 'In Loop'}
              </button>

              <button type="button" onClick={() => setForm(f => ({ ...f, evidence_required: !f.evidence_required }))}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.evidence_required ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                {form.evidence_required ? <CheckCircle2 size={12} /> : <FileCheck2 size={12} />} Evidence
              </button>

              <button type="button" onClick={() => setForm(f => ({ ...f, verification_required: !f.verification_required }))}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.verification_required ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                {form.verification_required ? <CheckCircle2 size={12} /> : <ShieldCheck size={12} />} Verification
              </button>

              {/* Tag — sits right beside Verification; opens the same Task Tags picker as Extra Options → Add Tags. */}
              <button type="button" onClick={() => setTagsModalOpen(true)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.tags.length ? 'border-[var(--accent-green)] text-[var(--accent-green)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                <TagsIcon size={12} /> {form.tags.length ? `Tag (${form.tags.length})` : 'Tag'}
              </button>
            </div>

            {/* Task Completion Type — only when creating a task for more than one assignee.
                Team Task (combined) = one shared task, done for all when any one completes.
                Individual Task (separate) = one independent task per member, completed on their
                own. Hidden on edit (an existing task is already a single doc). */}
            {!task && form.target_staff_id.length > 1 && (
              <div className="px-6 pt-4">
                <div className="p-3 bg-[var(--input-bg)] rounded-xl">
                  <div className="flex items-center gap-1.5 mb-2">
                    <Users size={13} className="text-[var(--accent-indigo)]" />
                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Task Completion Type</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {[
                      { value: 'combined', label: 'Combined', desc: 'Complete for everyone when any one member completes (verified, if enabled). Everyone shares the same status.' },
                      { value: 'separate', label: 'Separate', desc: 'Each member must complete separately — their own status, evidence, verification & due date. One member’s completion doesn’t affect others.' },
                    ].map(opt => {
                      const active = (form.assignment_mode || 'combined') === opt.value;
                      return (
                        <button type="button" key={opt.value}
                          onClick={() => setForm(f => ({ ...f, assignment_mode: opt.value }))}
                          className={`text-left p-3 rounded-xl border transition-all ${active ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]' : 'border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)]'}`}>
                          <div className="flex items-center gap-1.5">
                            {active ? <CheckCircle2 size={13} className="text-[var(--accent-indigo)]" /> : <Circle size={13} className="text-[var(--text-muted)]" />}
                            <span className={`text-[12px] font-black ${active ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{opt.label}</span>
                          </div>
                          <p className="mt-1 text-[10px] font-medium text-[var(--text-muted)] leading-snug">{opt.desc}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Repeat — a Recurring Checklist */}
            <div className="px-6 pt-4">
              <div className="flex items-center gap-2 flex-wrap p-3 bg-[var(--input-bg)] rounded-xl">
                <button type="button" onClick={() => setForm(f => (f.repeat === 'Does not repeat'
                  // Switching to a Recurring Checklist drops the deadline: the backend
                  // discards it anyway, so leaving it in the form would only mislead.
                  ? { ...f, repeat: 'Daily', end: '' }
                  : { ...f, repeat: 'Does not repeat' }))}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider border transition-all ${form.repeat !== 'Does not repeat' ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  {isRecurring ? <CheckCircle2 size={12} /> : <Circle size={12} />} Repeat
                </button>
                {isRecurring && (
                  <span className="text-[10px] font-black uppercase tracking-wider text-[var(--accent-indigo)]">
                    Recurring checklist
                  </span>
                )}
                {isRecurring && (
                  <>
                    <div className="relative" onClick={e => e.stopPropagation()}>
                      <button type="button" onClick={() => setRepeatDropdownOpen(o => !o)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-full text-[10px] font-black uppercase tracking-wider text-[var(--text-main)]">
                        {REPEAT_OPTIONS.find(o => o.value === form.repeat)?.label || 'Daily'}
                        <ChevronDown size={12} className={`transition-transform ${repeatDropdownOpen ? 'rotate-180' : ''}`} />
                      </button>
                      {repeatDropdownOpen && (
                        <div className="absolute top-full left-0 mt-1.5 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-xl overflow-hidden z-20 p-1.5 space-y-0.5">
                          {REPEAT_OPTIONS.map(o => (
                            <button type="button" key={o.value}
                              onClick={() => { setForm(f => ({ ...f, repeat: o.value })); setRepeatDropdownOpen(false); }}
                              className={`w-full text-left px-3 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider transition-all ${
                                form.repeat === o.value ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
                              }`}>
                              {o.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    <button type="button" onClick={() => setStartDatePickerOpen(true)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-card)] border rounded-full text-[10px] font-black uppercase tracking-wider ${form.start ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                      <CalendarClock size={12} /> {form.start ? formatDate(form.start) : 'Start Date *'}
                    </button>

                    <button type="button" onClick={() => setRepeatEndPickerOpen(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-full text-[10px] font-black text-[var(--text-muted)]">
                      <CalendarClock size={12} /> {form.repeat_end_date ? formatDate(form.repeat_end_date) : 'End Date'}
                    </button>
                  </>
                )}
              </div>

              {form.repeat === 'periodic' && (
                <div className="mt-2 p-3 bg-[var(--input-bg)] rounded-xl flex items-center justify-between">
                  <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Repeat Every</span>
                  <input type="number" min="1" value={form.repeat_interval}
                    onChange={e => setForm({ ...form, repeat_interval: parseInt(e.target.value) || 1 })}
                    className="w-16 text-center px-2 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-green)]" />
                  <span className="text-[10px] font-black text-[var(--accent-green)] uppercase tracking-wider">Days</span>
                </div>
              )}

              {/* Monthly: pick one or more dates of the month, or "Last Day". Weekly: pick
                  one or more days of the week. Purely descriptive metadata stored in
                  repeat_data — the existing recurrence engine still derives its single
                  per-period occurrence from `start`'s own day-of-month/weekday. */}
              {form.repeat === 'Monthly' && (
                <div className="mt-2 p-3 bg-[var(--input-bg)] rounded-xl">
                  <div className="grid grid-cols-10 gap-1.5">
                    {Array.from({ length: 31 }, (_, i) => i + 1).map(day => (
                      <button type="button" key={day} onClick={() => toggleMonthlyDate(day)}
                        className={`aspect-square flex items-center justify-center rounded-lg text-[11px] font-bold border transition-all ${
                          form.repeat_data.monthlyDates.includes(day) ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                        }`}>
                        {day}
                      </button>
                    ))}
                    <button type="button" onClick={toggleLastDay}
                      className={`col-span-3 flex items-center justify-center rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${
                        form.repeat_data.lastDay ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                      }`}>
                      Last Day
                    </button>
                  </div>
                </div>
              )}

              {form.repeat === 'Weekly' && (
                <div className="mt-2 p-3 bg-[var(--input-bg)] rounded-xl">
                  <div className="grid grid-cols-7 gap-1.5">
                    {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((label, idx) => (
                      <button type="button" key={label} onClick={() => toggleWeekday(idx)}
                        className={`py-2 rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${
                          form.repeat_data.weekdays.includes(idx) ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                        }`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {form.repeat === 'Custom' && (
                <div className="mt-2 p-3 bg-[var(--input-bg)] rounded-xl space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Occur Every</span>

                    <div className="relative" onClick={e => e.stopPropagation()}>
                      <button type="button" onClick={() => { setCustomIntervalOpen(o => !o); setCustomUnitOpen(false); }}
                        className="flex items-center gap-1 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)]">
                        {form.repeat_interval || 1}
                        <ChevronDown size={12} className={`transition-transform ${customIntervalOpen ? 'rotate-180' : ''}`} />
                      </button>
                      {customIntervalOpen && (
                        <div className="absolute top-full left-0 mt-1.5 w-16 max-h-48 overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-20 p-1">
                          {Array.from({ length: 30 }, (_, i) => i + 1).map(n => (
                            <button type="button" key={n}
                              onClick={() => { setForm(f => ({ ...f, repeat_interval: n })); setCustomIntervalOpen(false); }}
                              className={`w-full text-center px-2 py-1.5 rounded-lg text-[11px] font-bold ${
                                (form.repeat_interval || 1) === n ? 'bg-[var(--accent-green)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
                              }`}>
                              {n}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="relative" onClick={e => e.stopPropagation()}>
                      <button type="button" onClick={() => { setCustomUnitOpen(o => !o); setCustomIntervalOpen(false); }}
                        className="flex items-center gap-1 px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-[var(--text-main)]">
                        {customUnitLabel(form.repeat_data.customUnit, form.repeat_interval)}
                        <ChevronDown size={12} className={`transition-transform ${customUnitOpen ? 'rotate-180' : ''}`} />
                      </button>
                      {customUnitOpen && (
                        <div className="absolute top-full left-0 mt-1.5 w-24 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-20 p-1 space-y-0.5">
                          {['Weeks', 'Months'].map(unit => (
                            <button type="button" key={unit}
                              onClick={() => { setForm(f => ({ ...f, repeat_data: { ...f.repeat_data, customUnit: unit } })); setCustomUnitOpen(false); }}
                              className={`w-full text-left px-2.5 py-1.5 rounded-lg text-[12px] font-bold ${
                                (form.repeat_data.customUnit || 'Months') === unit ? 'bg-[var(--accent-green)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
                              }`}>
                              {customUnitLabel(unit, form.repeat_interval)}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {form.repeat_data.customUnit === 'Weeks' && (
                    <div>
                      <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Select Days :</span>
                      <div className="mt-1.5 grid grid-cols-7 gap-1.5">
                        {[[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [0, 'Sun']].map(([idx, label]) => (
                          <button type="button" key={label} onClick={() => toggleWeekday(idx)}
                            className={`py-2 rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${
                              form.repeat_data.weekdays.includes(idx) ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                            }`}>
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* "Months" picks which date(s) of the month this falls on (repeat_data.monthlyDates/
                      lastDay, same field Monthly uses); "Occur Every N" then steps N months at a time,
                      same engine as Monthly just with a custom interval instead of a fixed 1. */}
                  {(form.repeat_data.customUnit || 'Months') === 'Months' && (
                    <div>
                      <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">Select Dates :</span>
                      <div className="mt-1.5 grid grid-cols-10 gap-1.5">
                        {Array.from({ length: 31 }, (_, i) => i + 1).map(day => (
                          <button type="button" key={day} onClick={() => toggleMonthlyDate(day)}
                            className={`aspect-square flex items-center justify-center rounded-lg text-[11px] font-bold border transition-all ${
                              form.repeat_data.monthlyDates.includes(day) ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                            }`}>
                            {day}
                          </button>
                        ))}
                        <button type="button" onClick={toggleLastDay}
                          className={`col-span-3 flex items-center justify-center rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${
                            form.repeat_data.lastDay ? 'bg-[var(--accent-green)] text-white border-[var(--accent-green)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                          }`}>
                          Last Day
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-5 mt-4 flex items-center justify-between">
              <div className="flex items-center gap-1 relative" onClick={e => e.stopPropagation()}>
                <button type="button" onClick={() => setReminderModalOpen(true)} title="Reminders"
                  className="relative p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                  <Clock size={18} />
                  {form.reminders.length > 0 && <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-[var(--accent-indigo)]" />}
                </button>
                <button type="button" onClick={() => setVoiceNoteOpen(true)} title="Voice Note"
                  className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                  <Mic size={18} />
                </button>
              </div>

              <button type="submit" disabled={saving}
                className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 disabled:opacity-60 transition-all">
                <Save size={14} /> {saving ? 'Saving...' : (task ? 'Save Changes' : 'Assign Task')}
              </button>
            </div>
          </form>
        </motion.div>
      </div>

      <PickerModal
        isOpen={pickerOpen === 'assignee'} onClose={() => setPickerOpen(null)}
        title="Assign Tasks To" searchPlaceholder="Search Users..." items={staffItems}
        multi selected={form.target_staff_id} renderAvatar
        onApply={(ids) => setForm(f => ({ ...f, target_staff_id: ids }))}
      />
      <PickerModal
        isOpen={pickerOpen === 'inLoop'} onClose={() => setPickerOpen(null)}
        title="Keep In Loop" searchPlaceholder="Search Users..." items={loopItems}
        multi selected={form.watchers} renderAvatar
        bulkOption={{
          label: 'Include MD',
          ids: mdIds,
          hint: 'Keeps the Managing Director in the loop on this task.',
          emptyHint: 'No one in your organisation is marked as MD.',
        }}
        onApply={(ids) => setForm(f => ({ ...f, watchers: ids }))}
      />
      <PickerModal
        isOpen={pickerOpen === 'category'} onClose={() => setPickerOpen(null)}
        title="Select Category" searchPlaceholder="Find category..." items={categoryItems}
        multi={false} selected={form.category} renderDot allowAddMore addMoreLabel="Add More"
        onApply={handleCategoryApply} onAddNew={handleCategoryAddNew}
      />
      <MiniDatePicker isOpen={deadlinePickerOpen} onClose={() => setDeadlinePickerOpen(false)}
        value={form.end} title="Select Due Date" onApply={(iso) => setForm(f => ({ ...f, end: iso }))}
        holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError} disablePast />
      {/* Both repeat bounds are `dateOnly`: a Recurring Checklist has no deadline — every
          occurrence owns its whole calendar day and closes at 23:59:59 IST — and the series
          stop is a date, not an instant. Offering a time here only invited a choice that is
          then ignored. */}
      <MiniDatePicker isOpen={startDatePickerOpen} onClose={() => setStartDatePickerOpen(false)}
        value={form.start} title="Repeat Start Date" onApply={(iso) => setForm(f => ({ ...f, start: iso }))}
        holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError} dateOnly />
      {/* Repeat End Date: holidays are marked (indicator + label) but still selectable —
          the end date is only the series boundary; the recurring engine skips holiday
          occurrences within the range. */}
      <MiniDatePicker isOpen={repeatEndPickerOpen} onClose={() => setRepeatEndPickerOpen(false)}
        value={form.repeat_end_date} title="Repeat End Date" onApply={(iso) => setForm(f => ({ ...f, repeat_end_date: iso }))}
        holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError} dateOnly />
      <ReminderModal isOpen={reminderModalOpen} onClose={() => setReminderModalOpen(false)}
        reminders={form.reminders} onApply={(reminders) => setForm(f => ({ ...f, reminders: reminders.map(r => ({ ...r, parent_type: 'task' })) }))} />
      <TaskTagsModal
        isOpen={tagsModalOpen} onClose={() => setTagsModalOpen(false)}
        tags={availableTags} selected={form.tags}
        onApply={handleTagsApply}
      />
      <VoiceNoteModal
        isOpen={voiceNoteOpen} onClose={() => setVoiceNoteOpen(false)}
        onSave={attachFile}
      />
    </AnimatePresence>
  );
};

export default TaskFormModal;
