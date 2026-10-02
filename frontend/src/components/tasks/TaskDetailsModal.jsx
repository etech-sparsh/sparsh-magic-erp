import React, { useCallback, useEffect, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ArrowLeft, Trash2, Pencil, FileText, History, Info, Users, Layers, Plus,
  Paperclip, CheckSquare, Square, X, Tags as TagsIcon,
  ShieldCheck, CalendarClock, FileCheck2, Save, Bell, Check,
} from 'lucide-react';
import api from '../../services/api';
import {
  getTaskDetail, updateTaskStatus, updateChecklistItem,
  deleteChecklistItem, uploadTaskAttachment, softDeleteTask,
  uploadCompletionAttachment, deleteCompletionAttachment, reviseTaskDeadline,
  addTaskFollowUp, approveDeadlineRequest, rejectDeadlineRequest,
} from '../../services/taskApi';
import { getHolidays } from '../../services/holidayApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, REASON_REQUIRED_STATUSES } from './statusConfig';
import { getInitials, formatFrequencyLabel, formatDate, formatDateTime } from './taskDisplayUtils';
import TaskFormModal from './TaskFormModal';
import { describeReminder } from '../calendar/ReminderModal';
import MiniDatePicker from './MiniDatePicker';
import StatusReasonModal from './StatusReasonModal';
import AttachmentItem from './AttachmentItem';

// Follow-Ups is the task's single communication timeline: everything people say plus the
// system's own record of what happened to the task. These are the system lines, keyed by the
// status a transition landed on. A transition that already carries a `note` (the dependency
// hand-off / hand-back, written by the backend) uses that instead.
const SYSTEM_STATUS_MESSAGE = {
  pending: 'Task assigned',
  accepted: 'Delegation acknowledged',
  in_progress: 'Status changed to In Progress',
  blocked: 'Marked as Blocked',
  dependent_on_others: 'Marked as Dependent on Other',
  verification: 'Verification requested',
  in_progress_reopened: 'Task reopened',
  dependency_completed: 'Dependency completed — back with the assignee for final completion',
  completed: 'Task completed',
};

const systemStatusMessage = (h) => {
  if (h.note) return h.note;
  // Completing straight out of verification is the assigner approving it — say so.
  if (h.old_status === 'verification' && h.new_status === 'completed') return 'Verification approved — task completed';
  return SYSTEM_STATUS_MESSAGE[h.new_status]
    || `Status changed to ${STATUS_CONFIG[h.new_status]?.label || h.new_status}`;
};

// Full single-task view: description, revision (status) history, core info,
// involved parties, sub-tasks/checklist, attachments, and the Follow-Ups timeline.
// Opened from the row menu in TaskListView ("Details").
const TaskDetailsModal = ({ isOpen, onClose, taskId, scope, onChanged, onEdit }) => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [task, setTask] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  // Real subtasks (child tasks): add-form + nested detail view + taxonomy for the form.
  const [subtaskFormOpen, setSubtaskFormOpen] = useState(false);
  const [subtaskDetailId, setSubtaskDetailId] = useState(null);
  const [metaCats, setMetaCats] = useState([]);
  const [metaTags, setMetaTags] = useState([]);
  const [uploadingEvidence, setUploadingEvidence] = useState(false);
  const [deadlinePickerOpen, setDeadlinePickerOpen] = useState(false);
  const [savingDeadline, setSavingDeadline] = useState(false);
  // The assigner's verdict on an assignee's pending deadline revision request: an optional
  // remark that rides along with Approve / Reject.
  const [decisionRemark, setDecisionRemark] = useState('');
  const [decidingRequest, setDecidingRequest] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Reopen requires the assigner to set a NEW deadline before the task goes back to the assignee.
  const [reopenPickerOpen, setReopenPickerOpen] = useState(false);
  const [reopening, setReopening] = useState(false);
  // Follow-Up (In-Loop members): a nudge + remark.
  const [followUpText, setFollowUpText] = useState('');
  const [postingFollowUp, setPostingFollowUp] = useState(false);
  // In-Loop top controls: which quick-input (Follow Up / Remark) is expanded.
  const [inLoopBox, setInLoopBox] = useState(null); // 'followup' | 'remark' | null
  // Holidays + Sunday weekly-off block selection in the Revision / Reopen / Date-Revision pickers,
  // matching the create form. There is no persisted per-user weekly-off, so Sunday (0) is used.
  const [holidayDates, setHolidayDates] = useState([]);
  const WEEKLY_OFFS = [0];
  // Target status awaiting a Doer Name + Reason (Dependent on Other / Blocked).
  const [reasonStatus, setReasonStatus] = useState(null);
  const [savingReason, setSavingReason] = useState(false);
  // Working copy of the checklist — ticking/removing items edits this locally and only
  // persists when the user clicks Save (so a click no longer auto-saves each toggle).
  const [localChecklist, setLocalChecklist] = useState([]);
  const [savingChecklist, setSavingChecklist] = useState(false);

  const userMap = React.useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  // `silent` refetches update the data in place WITHOUT flipping `loading` — so the modal
  // never flashes its "Loading task details..." state after in-modal actions (status
  // change, comment, attach, deadline revise). Only the very first open shows the spinner.
  // Returns false ONLY when `tolerate403` is set and the task came back 403 — i.e. the viewer
  // can no longer see it, which after some actions is the expected outcome rather than an
  // error. Every other case keeps the old behaviour and returns true.
  const fetchDetail = useCallback(async ({ silent = false, tolerate403 = false } = {}) => {
    if (!taskId) return true;
    if (!silent) setLoading(true);
    try {
      const res = await getTaskDetail(taskId);
      setTask(res.data);
    } catch (err) {
      if (tolerate403 && err.response?.status === 403) return false;
      showError(err.response?.data?.detail || 'Failed to load task details');
    } finally {
      if (!silent) setLoading(false);
    }
    return true;
  }, [taskId, showError]);

  useEffect(() => {
    if (!isOpen) return;
    fetchDetail();
    // `?all=true` → full directory for name resolution (must include the assigner/higher-rank
    // users the viewer can't assign to, so they don't show as "Unknown").
    api.get('/tasks/assignable-users?all=true').then(res => setUsers(res.data || [])).catch(() => {});
    // Categories/tags for the "Add Subtask" form.
    api.get('/task-categories').then(r => setMetaCats((r.data || []).map(c => c.name).filter(Boolean))).catch(() => {});
    api.get('/task-tags').then(r => setMetaTags((r.data || []).map(t => t.name).filter(Boolean))).catch(() => {});
    // Holidays block dates in the Revision / Reopen / Date-Revision pickers.
    getHolidays().then(res => setHolidayDates((res.data || []).map(h => h.holiday_date).filter(Boolean))).catch(() => setHolidayDates([]));
  }, [isOpen, fetchDetail]);

  // Reset the working copy whenever the SERVER checklist changes (open, or after a Save) —
  // keyed on its content signature so unrelated silent refetches (comment/status/attach)
  // don't wipe unsaved local ticks.
  const checklistSig = JSON.stringify(task?.checklist || []);
  useEffect(() => {
    setLocalChecklist((task?.checklist || []).map(c => ({ ...c })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, checklistSig]);

  if (!isOpen) return null;

  // Dependent on Other / Blocked need a Doer Name + Reason first — open the modal and let
  // its submit call doStatusUpdate. Everything else applies immediately.
  const handleStatusChange = (status) => {
    if (REASON_REQUIRED_STATUSES.includes(status)) {
      setReasonStatus(status);
      return;
    }
    doStatusUpdate(status);
  };

  const doStatusUpdate = async (status, { reason, doerName, doerId } = {}) => {
    // A dependency doer's "completed" resolves their dependency and hands the task back to the
    // assignee who raised it — it isn't a completion of the task, so the check-point / evidence
    // rules (which gate the real assignee's completion) don't apply. The backend agrees.
    const resolvingDependency = status === 'completed' && isDependencyDoer;
    if (status === 'completed' && !resolvingDependency) {
      // Completion rule: a task can't be marked Completed until all check points are done.
      const items = task?.checklist || [];
      const pending = items.filter(c => !c.completed);
      if (pending.length) {
        showError(`Complete all check points first (${items.length - pending.length}/${items.length} done).`);
        return;
      }
      // Evidence Required: block completion until at least one evidence file is uploaded
      // (backend enforces this too — this is just the immediate, friendly message).
      if (task?.evidenceRequired && !(task?.completionAttachments || []).length) {
        showError('Evidence upload is required before completing this task.');
        return;
      }
    }
    if (reasonStatus) setSavingReason(true);
    try {
      await updateTaskStatus(taskId, status, reason, doerName, doerId);
      if (resolvingDependency) {
        showSuccess('Dependency completed — the task is back with the assignee for final completion');
        // Resolving the dependency hands the task back and takes this viewer off it, so the
        // refetch below may legitimately come back 403. That is the shape of success here, not
        // a failure: refresh the list behind and close, rather than contradicting the message
        // above with "Not authorized to view this task". A doer who is also in the loop can
        // still see it, so the modal only closes when the task has genuinely gone.
        onChanged?.();
        setReasonStatus(null);
        const stillVisible = await fetchDetail({ silent: true, tolerate403: true });
        if (!stillVisible) onClose();
        return;
      }
      if (status === 'completed' && task?.verificationRequired && !canAdminister) {
        // Verification-required tasks completed by the assignee are routed to "verification"
        // by the backend — the silent refetch below reflects whatever the server decided.
        showSuccess('Verification requested — sent to the assigner');
      }
      fetchDetail({ silent: true });
      onChanged?.();
      setReasonStatus(null);
    } catch (err) {
      // A 403 here usually means the task moved on while this modal sat open — most often the
      // viewer resolved a dependency, which hands the task back and takes them off it. Re-read
      // it: if it is still theirs the message explains why the move was refused; if it is not,
      // the modal is stale, so close it rather than leave a control that can only fail.
      if (err.response?.status === 403) {
        try {
          await getTaskDetail(taskId);
          showError(err.response?.data?.detail || 'Not authorized to update this task');
          fetchDetail({ silent: true });
        } catch {
          showError(err.response?.data?.detail
            || 'This task is no longer yours — it has moved on since you opened it.');
          onChanged?.();
          onClose();
        }
        return;
      }
      showError(err.response?.data?.detail || 'Failed to update status');
    } finally {
      setSavingReason(false);
    }
  };

  // Verification actions — assigner/delegator only (backend also enforces).
  // Approve: the assigner's own "completed" is NOT rerouted to verification by the backend
  // (that reroute only applies to the assignee), so this finalizes the task.
  const handleFinalComplete = async () => {
    try {
      await updateTaskStatus(taskId, 'completed');
      showSuccess('Verification approved — task completed');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to complete task');
    }
  };

  // Reopen must carry a NEW deadline and a mandatory remark (spec): open the picker first; the
  // actual hand-back happens in handleReopenWithDeadline once the assigner submits both.
  const handleReopen = () => setReopenPickerOpen(true);

  const handleReopenWithDeadline = async (iso, remark) => {
    setReopenPickerOpen(false);
    setReopening(true);
    try {
      // Set the new deadline first (assigner-only endpoint), then flip status to Reopened,
      // which hands the task back to the assignee for rework. Reuses the existing APIs — the
      // remark lands in both the deadline-revision history and the status history.
      await reviseTaskDeadline(taskId, iso, remark, 'reopen');
      await updateTaskStatus(taskId, 'in_progress_reopened', remark);
      showSuccess('Task reopened — sent back to the assignee for rework');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to send the task back');
    } finally {
      setReopening(false);
    }
  };

  // Follow-Up — In-Loop members (watchers) / participants nudge with a remark.
  const handleAddFollowUp = async () => {
    const remark = followUpText.trim();
    if (!remark) return;
    setPostingFollowUp(true);
    try {
      await addTaskFollowUp(taskId, remark);
      setFollowUpText('');
      showSuccess('Follow-up added');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add follow-up');
    } finally {
      setPostingFollowUp(false);
    }
  };

  // One control, two outcomes: the assigner / reporting manager revises the deadline outright,
  // while an assignee's pick comes back as a pending REQUEST (the backend decides which, from
  // who is calling) — so the toast has to say which of the two just happened.
  const handleReviseDeadline = async (iso, remark) => {
    setSavingDeadline(true);
    try {
      const res = await reviseTaskDeadline(taskId, iso, remark);
      showSuccess(res?.data?.status === 'pending_approval'
        ? 'Deadline revision requested — awaiting the assigner’s approval'
        : 'Deadline revised');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to revise deadline');
    } finally {
      setSavingDeadline(false);
    }
  };

  // Approve / reject the assignee's pending request. Approving is the moment the revised
  // deadline takes effect and lands in the deadline history; rejecting leaves the original
  // deadline in force.
  const handleDecideDeadlineRequest = async (approve) => {
    const req = task?.pendingDeadlineRequest;
    if (!req) return;
    setDecidingRequest(true);
    try {
      const decide = approve ? approveDeadlineRequest : rejectDeadlineRequest;
      await decide(taskId, req.id, decisionRemark.trim());
      setDecisionRemark('');
      showSuccess(approve
        ? 'Deadline revision approved — the new deadline is now in force'
        : 'Deadline revision rejected — the original deadline stands');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to decide the deadline revision request');
    } finally {
      setDecidingRequest(false);
    }
  };

  // The delete itself is soft — the task moves to Deleted Tasks and can be brought back.
  // The MAIL is not: the backend fires the `deleted` task notification to the assignee and
  // every watcher, and that cannot be recalled. Since this button sits directly beside
  // Edit Task, one misclick told everyone on the task it was deleted, with nothing in
  // between. Hence the confirmation.
  const handleDelete = async () => {
    setDeleting(true);
    try {
      await softDeleteTask(taskId);
      showSuccess('Task moved to Deleted Tasks');
      setConfirmDelete(false);
      onChanged?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to delete task');
      setDeleting(false);
    }
  };

  // Local-only edits — persisted together by handleSaveChecklist.
  const handleToggleSubtask = (item) => {
    setLocalChecklist(list => list.map(c => (c.id === item.id ? { ...c, completed: !c.completed } : c)));
  };

  const handleRemoveSubtask = (item) => {
    setLocalChecklist(list => list.filter(c => c.id !== item.id));
  };

  const handleSaveChecklist = async () => {
    const orig = task?.checklist || [];
    const localIds = new Set(localChecklist.map(c => c.id));
    const toDelete = orig.filter(o => !localIds.has(o.id));
    const toToggle = localChecklist.filter(l => {
      const o = orig.find(x => x.id === l.id);
      return o && !!o.completed !== !!l.completed;
    });
    if (!toDelete.length && !toToggle.length) return;
    setSavingChecklist(true);
    try {
      await Promise.all([
        ...toDelete.map(o => deleteChecklistItem(taskId, o.id)),
        ...toToggle.map(l => updateChecklistItem(taskId, l.id, { completed: l.completed })),
      ]);
      showSuccess('Check points saved');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save check points');
    } finally {
      setSavingChecklist(false);
    }
  };

  const handleAttach = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadTaskAttachment(taskId, file);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to attach file');
    } finally {
      e.target.value = '';
    }
  };

  // Completion evidence — uploaded/removed against the separate completion_attachments store.
  const handleEvidenceAttach = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingEvidence(true);
    try {
      await uploadCompletionAttachment(taskId, file);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to upload evidence');
    } finally {
      setUploadingEvidence(false);
      e.target.value = '';
    }
  };

  const handleRemoveEvidence = async (attachmentId) => {
    try {
      await deleteCompletionAttachment(taskId, attachmentId);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to remove evidence');
    }
  };

  const cfg = task ? (STATUS_CONFIG[task.status] || STATUS_CONFIG.pending) : null;
  // Edit/Delete are available to the creator and to admins (backend enforces the same on
  // update/delete). Assignees / in-loop users can view + change status but not edit/delete.
  // Company MD (backend-scoped to only their own company's tasks): the client-side equivalent
  // of an admin, so it unlocks the same actions. A client MD's role is "clientadmin", which is
  // deliberately NOT in the role list above — the backend decides, and sends this flag.
  const isCompanyAdmin = !!task?.isCompanyAdmin;
  const canManage = !!task && (task.isCreator || isCompanyAdmin || ['superadmin', 'admin'].includes(user?.role));
  // Reporting Manager of an assignee (backend-scoped to only their reports): has the SAME task
  // workflow as an admin on this task — drive the working status, finalize/verify, reopen,
  // revise, edit, delete. Folded into the gating booleans below.
  const isReportingManager = !!task?.isReportingManager;
  // Counts + progress reflect the local working copy so ticks show instantly (pre-Save).
  const checklistDone = localChecklist.filter(c => c.completed).length;
  const checklistTotal = localChecklist.length;
  // Unsaved changes = an item removed, or a completed-state flipped vs the server copy.
  const origChecklist = task?.checklist || [];
  const localChecklistIds = new Set(localChecklist.map(c => c.id));
  const checklistDirty = origChecklist.some(o => !localChecklistIds.has(o.id))
    || localChecklist.some(l => { const o = origChecklist.find(x => x.id === l.id); return o && !!o.completed !== !!l.completed; });
  // A verification-required task the assignee has submitted is now the assigner's to
  // finalize or reopen — the assignee-side status control is hidden while it's here.
  const isAwaitingVerification = !!task && task.verificationRequired && task.status === 'verification';
  // In-Loop member (watcher) of this task — gets the Follow-Up action. Everyone involved can
  // still see the follow-up count + history; only in-loop members can raise a new follow-up.
  const isInLoop = !!task && (task.watchers || []).includes(user?._id);
  // Assignee-side "Revision": the assignee can set a new deadline (calendar) when they can't
  // finish by the current one. Available while the task is still theirs to work on (not
  // completed, and not handed to the assigner for verification). The assigner keeps the
  // separate "Revise" action (canManage) already shown next to the deadline.
  const isAssignee = !!task && (task.assignedTo || []).includes(user?._id);
  // Self-assigned task (creator is the doer, no other assignees) — the creator works it like an assignee.
  const isSelfTask = !!task && task.isCreator && !(task.assignedTo || []).length;
  // Pure In-Loop member (watcher, not the doer or the assigner) — e.g. a Subscribed task. They
  // are observers: View + Follow Up + Add Subtask only. Every workflow action (status change,
  // request verification / complete, approve / reopen, revise deadline, edit, delete) is frozen
  // for them, regardless of their role — an admin who is merely in-loop gets no more than this.
  // The two exceptions are the reporting manager and the company MD, who administer the task
  // however they came to it.
  const isPureWatcher = !!task && isInLoop && !isAssignee && !task.isCreator
    && !isReportingManager && !isCompanyAdmin;
  // Who drives the working-status dropdown: the assignee, the creator of a self-task, the
  // reporting manager, or the company MD (same workflow as an admin on this task).
  const canWork = ((isAssignee || isSelfTask) && !isPureWatcher) || isReportingManager || isCompanyAdmin;
  // Assigner-side actions (approve/reopen a verification, revise the deadline) — also the
  // reporting manager and the company MD, who administer these tasks like an admin.
  const canAdminister = (canManage && !isPureWatcher) || isReportingManager || isCompanyAdmin;
  // ─── Whose deadline is it to move ───
  // Doing somebody else's task makes you the DOER, whatever your role on the platform: an admin
  // or reporting manager who is also an assignee asks for a new deadline like anyone else, and
  // cannot approve their own request. (Deliberately narrower than canAdminister, which still
  // governs verification and edit/delete — this is about the deadline alone.) Mirrors
  // acts_as_doer in routes/tasks.py; the backend enforces it regardless of what is rendered.
  const actsAsDoer = !!task && (task.assignedTo || []).includes(user?._id) && !task.isCreator;
  const canDecideDeadline = canAdminister && !actsAsDoer;
  // A doer can only ASK for a new deadline — the backend turns their calendar pick into a
  // pending request. Say so everywhere the action is offered.
  const revisionLabel = canDecideDeadline ? 'Revise' : 'Request Revision';
  // ─── The two-revision budget ───
  // A deadline may be moved twice and no more (backend: MAX_DEADLINE_REVISIONS), counting the
  // assigner's own revisions and the assignee requests they approved alike. Once it is spent the
  // action is withdrawn from both sides rather than left to fail on submit. A Reopen is exempt
  // and is not offered here anyway — it has its own control on the verification screen.
  const deadlineRevisionLimit = task?.deadlineRevisionLimit ?? 2;
  const deadlineRevisionsUsed = task?.deadlineRevisionCount ?? 0;
  const deadlineRevisionsLeft = Math.max(0, deadlineRevisionLimit - deadlineRevisionsUsed);
  // A completed task's deadline is settled — it decides whether the work landed on time, so
  // there is nothing left to revise and no one left to revise it for. Withdraws the assigner's
  // Revise button and the doer's Revise / Request Revision option together, both of which gate
  // on this. (The backend refuses it either way.)
  const canReviseDeadline = deadlineRevisionsLeft > 0 && task?.status !== 'completed';
  // Editing/deleting the task definition belongs to the assigner (creator) / admins — NOT the
  // assignee (their "My Tasks" view) and NOT a pure watcher (their Subscribed view). So hide
  // Edit + Delete for a doer who isn't also the creator, and for in-loop-only members. A
  // reporting manager — and a company MD — additively get Edit/Delete on those tasks.
  const canEditOrDelete = (canAdminister && !(isAssignee && !task?.isCreator))
    || isReportingManager || isCompanyAdmin;
  // ─── Follow-Ups: the task's ONE communication timeline ───
  // Everything people said (follow-ups, plus the remarks left by the old chat section, folded in
  // so that history isn't orphaned) merged with the system's record of what happened (status
  // transitions, deadline revisions), oldest first. Everyone on the task can read it and post to
  // it — assigner, assignee and in-loop members alike.
  const activityTimeline = (() => {
    if (!task) return [];
    const items = [];
    if (task.createdAt) {
      const names = (task.assignedTo || []).map(id => userMap[id]).filter(Boolean).join(', ');
      items.push({ id: 'created', kind: 'system', text: `Task assigned to ${names || 'themselves'}`, at: task.createdAt });
    }
    (task.remarks || []).forEach(r => items.push({
      id: `remark-${r.id}`, kind: 'user', name: r.author_name, text: r.text, at: r.created_at,
    }));
    (task.followUps || []).forEach(f => items.push({
      id: `followup-${f.id}`, kind: 'user', name: f.by_name, text: f.remark, at: f.created_at,
    }));
    (task.statusHistory || []).forEach((h, i) => items.push({
      id: `status-${i}`, kind: 'system', by: h.changed_by_name, text: systemStatusMessage(h), reason: h.reason, at: h.changed_at,
    }));
    (task.deadlineHistory || []).forEach((d, i) => items.push({
      id: `deadline-${i}`, kind: 'system', by: d.revised_by_name, reason: d.reason, at: d.revised_at,
      text: `Deadline revised${d.new_end ? ` to ${formatDateTime(d.new_end)}` : ''}`
        + (d.requested_by_name ? ` (${d.requested_by_name}’s request approved)` : ''),
    }));
    // The request side of the trail: raising one, and a rejection (an approval already shows up
    // above as the revision it caused, so it isn't repeated here).
    (task.deadlineRequests || []).forEach((r) => {
      items.push({
        id: `dlreq-${r.id}`, kind: 'system', by: r.requested_by_name, reason: r.reason, at: r.requested_at,
        text: `Deadline revision requested${r.new_end ? ` to ${formatDateTime(r.new_end)}` : ''}`,
      });
      if (r.status === 'rejected') items.push({
        id: `dlreq-${r.id}-rejected`, kind: 'system', by: r.decided_by_name, reason: r.decision_remark, at: r.decided_at,
        text: 'Deadline revision rejected — the original deadline stands',
      });
    });
    return items.sort((a, b) => new Date(a.at || 0) - new Date(b.at || 0));
  })();

  // ─── Role-based working dropdown (assignee / dependent-on-other doer) ───
  // "Pending" is surfaced as "In Progress"; "Revision" opens the deadline calendar (no status
  // change). The closed control shows the current status; the options are exactly the role set.
  const REVISION_OPT = '__revision__';
  const curDisplayStatus = task?.status === 'pending' ? 'in_progress' : task?.status;
  const curCfg = (task && (STATUS_CONFIG[curDisplayStatus] || cfg)) || {};
  const curLabel = STATUS_CONFIG[curDisplayStatus]?.label || curDisplayStatus || '';
  // Requirement: Verification Required = Yes → the doer's completion option reads "Request for
  // Verification" (routes to the verification stage via the same 'completed' status transition,
  // which the backend reroutes when verification_required is set and the caller isn't the
  // assigner). Verification Required = No → the plain "Complete" flow, unchanged.
  const canComplete = canWork && !['completed', 'verification'].includes(task?.status);
  // Dependency doer: the task was handed to them via "Dependent on Other", so they own the
  // dependency only — never the task. Their "Complete" resolves the dependency and hands the
  // task back to the assignee who raised it (the backend pops the dependency stack), so it must
  // NOT read "Request for Verification": verification is that assignee's step, later.
  const isDependencyDoer = !!task?.dependencyDoerId && task.dependencyDoerId === user?._id;
  // The assignee who raised the dependency keeps the task (and sees it parked at "Dependent on
  // Other"), but it isn't theirs to move until the doer resolves it — so their control is frozen.
  const isAwaitingDependency = isAssignee && !!task?.dependencyDoerId && !isDependencyDoer;
  const dependencyDoerName = userMap[task?.dependencyDoerId] || 'the dependency doer';
  // ─── The person this task depends on ───
  // Named whenever the task HAS a dependency, not only while one is outstanding. Resolving a
  // dependency takes the doer off the task, and the card then said nothing at all about the
  // person who actually did that part — which is the opposite of what Involved Parties is for.
  //   • live      — dependencyDoerId, the person it is waiting on right now
  //   • resolved  — the last hand-off in the status history, which also covers a doer who was
  //                 typed as a free-text name and never added to the task as a user
  const dependencyPerson = (() => {
    if (!task) return null;
    if (task.dependencyDoerId) {
      return { id: task.dependencyDoerId, name: userMap[task.dependencyDoerId] || 'Unknown', resolved: false };
    }
    const handOff = [...(task.statusHistory || [])].reverse()
      .find(h => h.new_status === 'dependent_on_others' && (h.doer_name || h.doer_id));
    if (!handOff) return null;
    return {
      id: handOff.doer_id || null,
      name: (handOff.doer_id && userMap[handOff.doer_id]) || handOff.doer_name || 'Unknown',
      resolved: true,
    };
  })();

  // ─── Who performed the final completion ───
  // Almost always somebody the card already names — the assignee who finished it, or the
  // assigner who approved it — so it is marked against THEIR row rather than repeating the
  // person as a separate entry. Only a completer who appears nowhere else (an admin closing
  // somebody's task) still needs a row of their own.
  const completedById = task?.status === 'completed' ? task?.completedBy : null;
  const completionBadge = (id) => (completedById && id && String(id) === String(completedById) ? (
    <span className="ml-auto text-right shrink-0">
      <span className="block text-[9px] font-black uppercase tracking-wider text-[var(--accent-green)]">Final Complete</span>
      {task.completedAt && (
        <span className="block text-[9px] font-bold text-[var(--text-muted)]">{formatDate(task.completedAt)}</span>
      )}
    </span>
  ) : null);
  const completerHasOwnRow = !!completedById && (
    String(completedById) === String(task?.assignedBy)
    || (task?.assignedTo || []).some(id => String(id) === String(completedById))
    || (dependencyPerson?.id && String(dependencyPerson.id) === String(completedById))
  );
  const requestingVerification = task?.verificationRequired && !canAdminister && !isDependencyDoer;
  // Dependency doer → Complete, Dependent on Other (chain it on), Revise. Nothing else.
  // Normal assignee → Accept, Dependent on Other, Blocked, Revise + the completion option.
  const workingActions = isDependencyDoer
    ? [
      ...(canComplete ? [['completed', 'Complete']] : []),
      ['dependent_on_others', 'Dependent on Other'],
      ...(canReviseDeadline ? [[REVISION_OPT, revisionLabel]] : []),
    ]
    : [
      ['accepted', 'Acknowledged Delegation'],
      ['dependent_on_others', 'Dependent on Other'],
      ['blocked', 'Blocked'],
      ...(canReviseDeadline ? [[REVISION_OPT, revisionLabel]] : []),
      ...(canComplete ? [['completed', requestingVerification ? 'Request for Verification' : 'Complete']] : []),
    ];
  // Only show the current status as a separate (disabled) line when it isn't already one of the
  // action options — otherwise it would duplicate it (e.g. two "Accept" entries).
  const showCurrentOpt = !workingActions.some(([v]) => v === curDisplayStatus);
  const handleWorkingSelect = (val) => {
    if (val === REVISION_OPT) { setDeadlinePickerOpen(true); return; }
    handleStatusChange(val);
  };
  // Pending Verification is the assigner's call: Approve (→ Completed, final) or Reopen (→ back
  // to the assignee for rework, with a new deadline + mandatory remark). Both live in the status
  // dropdown rather than as separate buttons.
  const APPROVE_OPT = '__approve__';
  const REOPEN_OPT = '__reopen__';
  const handleVerificationSelect = (val) => {
    if (val === APPROVE_OPT) { handleFinalComplete(); return; }
    if (val === REOPEN_OPT) { handleReopen(); }
  };

  return (
    <>
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-2xl max-h-[88vh] overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl">

          {/* Header */}
          <div className="px-6 py-4 border-b border-[var(--border)] sticky top-0 bg-[var(--bg-card)] z-10">
            {/* Top row: breadcrumb on the left, close (×) always pinned top-right. */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-widest">
                <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><ArrowLeft size={16} /></button>
                <span className="text-[var(--text-muted)]">Delegations</span>
                <span className="text-[var(--text-muted)]">/</span>
                <span className="text-[var(--accent-indigo)]">Details</span>
              </div>
              <button type="button" onClick={onClose} title="Close"
                className="p-1.5 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors shrink-0">
                <X size={18} />
              </button>
            </div>
            {task && (
              <div className="flex items-center gap-2 flex-wrap mt-3">
                {isPureWatcher ? (
                  // Pure In-Loop member (watcher, not the doer or the assigner) — including admins:
                  // observers only. The status control is shown but frozen, so it's clear the task's
                  // workflow isn't theirs to drive; their actions are Follow Up + Add Subtask.
                  <div className="flex items-center gap-2 flex-wrap w-full">
                    <select value={curDisplayStatus} disabled title="Read-only — In-Loop members can't change the task status"
                      className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none opacity-60 cursor-not-allowed"
                      style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                      <option value={curDisplayStatus}>{curLabel}</option>
                    </select>
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]">
                      <Bell size={12} /> Follow-Ups: {task.followUpCount ?? (task.followUps || []).length}
                    </span>
                    <button type="button" onClick={() => setInLoopBox(b => (b === 'followup' ? null : 'followup'))}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border hover:opacity-90 ${inLoopBox === 'followup' ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'}`}>
                      <Bell size={13} /> Follow Up
                    </button>
                    {inLoopBox === 'followup' && (
                      <div className="flex items-center gap-2 w-full">
                        <input autoFocus value={followUpText} onChange={e => setFollowUpText(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddFollowUp(); } }}
                          placeholder="Add a follow-up remark..."
                          className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                        <button type="button" onClick={handleAddFollowUp} disabled={postingFollowUp || !followUpText.trim()}
                          className="flex items-center gap-1.5 px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest disabled:opacity-50 shrink-0">
                          <Bell size={13} /> {postingFollowUp ? '...' : 'Follow Up'}
                        </button>
                      </div>
                    )}
                  </div>
                ) : isAwaitingVerification ? (
                  // Verification hand-off: the delegator/assigner gets a status dropdown with
                  // exactly two actions — Approve (final) and Reopen (back for rework); the
                  // assignee only sees a read-only "Pending Verification" badge.
                  canAdminister ? (
                    <select value={curDisplayStatus} disabled={reopening}
                      onChange={e => handleVerificationSelect(e.target.value)}
                      className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none cursor-pointer disabled:opacity-50"
                      style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                      <option value={curDisplayStatus} disabled>{reopening ? 'Reopening…' : cfg.label}</option>
                      <option value={APPROVE_OPT}>Approve</option>
                      <option value={REOPEN_OPT}>Reopen</option>
                    </select>
                  ) : (
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                      <ShieldCheck size={13} /> {cfg.label}
                    </span>
                  )
                ) : isAwaitingDependency ? (
                  // The dependency is out with someone else: the task stays the assignee's, but
                  // it's parked at "Dependent on Other" until the doer resolves it.
                  <select value={curDisplayStatus} disabled
                    title={`Waiting on ${dependencyDoerName} to complete the dependency`}
                    className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none opacity-60 cursor-not-allowed"
                    style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                    <option value={curDisplayStatus}>{curLabel}</option>
                  </select>
                ) : canWork ? (
                  // Assignee / dependent-on-other doer: role-based working options. The closed
                  // control shows the current status; the list is exactly the role's action set,
                  // ending with Complete / Request for Verification.
                  <select value={curDisplayStatus} onChange={e => handleWorkingSelect(e.target.value)}
                    className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none cursor-pointer"
                    style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                    {showCurrentOpt && <option value={curDisplayStatus} disabled>{curLabel}</option>}
                    {workingActions.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
                  </select>
                ) : (
                  // Assigner/admin (not the doer): status is read-only here. Their actions are
                  // Final Complete / Reopen (during verification) + Date Revision + Edit/Delete.
                  <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border" style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                    {curLabel}
                  </span>
                )}
                {task.verificationRequired && (
                  <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]">
                    Verification Required
                  </span>
                )}
                <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)]">
                  {formatFrequencyLabel(task.frequency)}
                </span>
                {canEditOrDelete && (
                  <>
                    <button onClick={() => onEdit?.(task)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90">
                      <Pencil size={13} /> Edit Task
                    </button>
                    <button onClick={() => setConfirmDelete(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)] hover:opacity-90">
                      <Trash2 size={13} /> Delete Task
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          {loading || !task ? (
            <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading task details...</div>
          ) : (
            <div className="p-6 space-y-5">
              <h2 className="text-xl font-black text-[var(--text-main)]">{task.title}</h2>

              {/* Description */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-2">
                  <FileText size={13} /> Description
                </p>
                <p className="text-[13px] font-medium text-[var(--text-main)]">{task.description || '—'}</p>
              </div>

              {/* Revision History */}
              {task.statusHistory?.length > 0 && (
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                    <History size={13} /> Revision History ({task.statusHistory.length})
                  </p>
                  <div className="space-y-3">
                    {[...task.statusHistory].reverse().map((h, i) => (
                      <div key={i} className="flex items-start justify-between gap-3 border-b border-[var(--border)] last:border-0 pb-3 last:pb-0">
                        <div className="min-w-0">
                          <p className="text-[11px] font-black text-[var(--text-main)]">Revision #{task.statusHistory.length - i}</p>
                          <p className="text-[11px] font-bold text-[var(--text-muted)]">
                            {STATUS_CONFIG[h.old_status]?.label || h.old_status} <span className="mx-1">→</span>
                            <span className="text-[var(--accent-indigo)]">{STATUS_CONFIG[h.new_status]?.label || h.new_status}</span>
                          </p>
                          {h.note && <p className="mt-1 text-[11px] font-bold text-[var(--text-main)]">{h.note}</p>}
                          {h.doer_name && <p className="mt-1 text-[10px] font-bold text-[var(--text-muted)]">Doer: <span className="text-[var(--text-main)]">{h.doer_name}</span></p>}
                          {h.reason && <p className="mt-1 px-2 py-1 bg-[var(--accent-yellow-bg)] text-[var(--text-muted)] text-[11px] rounded-lg italic">"{h.reason}"</p>}
                          <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70 mt-1">By {h.changed_by_name || 'Unknown'}</p>
                        </div>
                        <span className="text-[10px] font-black text-[var(--text-muted)] shrink-0">{h.changed_at ? formatDate(h.changed_at) : ''}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {/* Core Information */}
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4 space-y-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Info size={13} /> Core Information
                  </p>
                  <div className="grid grid-cols-2 gap-3 text-[12px]">
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Category</p><p className="font-bold text-[var(--text-main)]">{task.category || '—'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Priority</p><p className="font-bold text-[var(--text-main)]">{task.priority}</p></div>
                    <div className="col-span-2">
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Deadline</p>
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-bold text-[var(--text-main)]">{task.end ? formatDateTime(task.end) : '—'}</p>
                        {/* Date Revision — assigner/delegator (backend-enforced), never in-loop.
                            Withdrawn once the task's two revisions are spent. */}
                        {canDecideDeadline && canReviseDeadline && (
                          <button type="button" onClick={() => setDeadlinePickerOpen(true)} disabled={savingDeadline}
                            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90 disabled:opacity-50">
                            <CalendarClock size={11} /> {savingDeadline ? 'Saving...' : 'Revise'}
                          </button>
                        )}
                      </div>
                      {/* How much of the revision budget is left. Shown only once one has been
                          used, so an untouched deadline isn't captioned with a limit nobody has
                          come near yet. */}
                      {deadlineRevisionsUsed > 0 && (
                        <p className={`mt-1 text-[9px] font-black uppercase tracking-wider ${canReviseDeadline ? 'text-[var(--text-muted)]' : 'text-[var(--accent-red)]'}`}>
                          {canReviseDeadline
                            ? `Revisions used ${deadlineRevisionsUsed} of ${deadlineRevisionLimit}`
                            : `Revision limit reached (${deadlineRevisionLimit} of ${deadlineRevisionLimit}) — this deadline is final`}
                        </p>
                      )}
                      {/* Pending deadline revision request. The date above is still the one in
                          force — it only moves when the assigner approves below. */}
                      {task.pendingDeadlineRequest && (
                        <div className="mt-2 p-3 rounded-xl border bg-[var(--accent-yellow-bg)] border-[var(--accent-yellow-border)]">
                          <p className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-wider text-[var(--accent-yellow)]">
                            <CalendarClock size={11} /> Deadline Revision Requested
                          </p>
                          <p className="mt-1 text-[11px] font-bold text-[var(--text-muted)]">
                            {task.pendingDeadlineRequest.old_end ? formatDateTime(task.pendingDeadlineRequest.old_end) : '—'}
                            <span className="mx-1">→</span>
                            <span className="text-[var(--accent-indigo)]">
                              {task.pendingDeadlineRequest.new_end ? formatDateTime(task.pendingDeadlineRequest.new_end) : '—'}
                            </span>
                            <span className="opacity-70"> · {task.pendingDeadlineRequest.requested_by_name || 'Unknown'}</span>
                          </p>
                          {task.pendingDeadlineRequest.reason && (
                            <p className="mt-1 pl-2 border-l-2 border-[var(--border)] text-[11px] font-medium text-[var(--text-main)] leading-relaxed">
                              {task.pendingDeadlineRequest.reason}
                            </p>
                          )}
                          {canDecideDeadline ? (
                            <div className="mt-2 space-y-2">
                              <input value={decisionRemark} onChange={e => setDecisionRemark(e.target.value)}
                                placeholder="Remark (optional)"
                                className="w-full px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[11px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                              <div className="flex items-center gap-2">
                                {/* Approving would move the deadline of a finished task; rejecting
                                    just clears a request that events have overtaken. */}
                                {task.status !== 'completed' && (
                                <button type="button" disabled={decidingRequest} onClick={() => handleDecideDeadlineRequest(true)}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-green-bg)] text-[var(--accent-green)] border-[var(--accent-green-border)] hover:opacity-90 disabled:opacity-50">
                                  <Check size={11} /> {decidingRequest ? 'Saving...' : 'Approve'}
                                </button>
                                )}
                                <button type="button" disabled={decidingRequest} onClick={() => handleDecideDeadlineRequest(false)}
                                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)] hover:opacity-90 disabled:opacity-50">
                                  <X size={11} /> Reject
                                </button>
                              </div>
                            </div>
                          ) : (
                            <p className="mt-1.5 text-[10px] font-bold text-[var(--text-muted)]">
                              Awaiting the assigner’s approval — the current deadline still applies.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Evidence</p><p className="font-bold text-[var(--text-main)]">{task.evidenceRequired ? 'Required' : 'Optional'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Verification</p><p className="font-bold text-[var(--text-main)]">{task.verificationRequired ? 'Required' : 'Not Required'}</p></div>
                  </div>
                  {/* Deadline revision history (assigner-only actions, but everyone can see the trail). */}
                  {(task.deadlineHistory || []).length > 0 && (
                    <div className="pt-2 border-t border-[var(--border)]">
                      <p className="flex items-center gap-1.5 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider mb-1.5">
                        <History size={11} /> Deadline Revisions ({task.deadlineHistory.length})
                      </p>
                      <div className="space-y-1.5">
                        {[...task.deadlineHistory].reverse().map((h, i) => (
                          <div key={i} className="text-[10px] font-bold text-[var(--text-muted)]">
                            <div>
                              {h.old_end ? formatDate(h.old_end) : '—'} <span className="mx-1">→</span>
                              <span className="text-[var(--accent-indigo)]">{h.new_end ? formatDate(h.new_end) : '—'}</span>
                              <span className="opacity-70"> · {h.revised_by_name || 'Unknown'}</span>
                            </div>
                            {/* Why it moved. Older revisions predate the mandatory reason, so
                                this stays conditional rather than rendering an empty quote. */}
                            {h.reason && (
                              <p className="mt-0.5 pl-2 border-l-2 border-[var(--border)] font-medium text-[var(--text-main)] leading-relaxed">
                                {h.reason}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* Tags — mirrors the green pill style used in the task form; shows every tag
                      saved on the task (persists across refresh since it reads task.tags). */}
                  <div>
                    <p className="text-[9px] font-black text-[var(--text-muted)] uppercase mb-1.5">Tags</p>
                    {(task.tags || []).length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {task.tags.map(tag => (
                          <span key={tag} className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--accent-green)] text-white border border-[var(--accent-green)]">
                            <TagsIcon size={10} /> {tag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[12px] font-bold text-[var(--text-main)]">—</p>
                    )}
                  </div>
                  {/* Reminders — read-only. Saved by the task form onto the event doc; the
                      detail response now carries them back (tasks.py _serialize_task_detail).
                      Described via describeReminder so this reads identically to the editor. */}
                  <div>
                    <p className="text-[9px] font-black text-[var(--text-muted)] uppercase mb-1.5">Reminders</p>
                    {(task.reminders || []).length > 0 ? (
                      <div className="flex flex-col gap-1.5">
                        {task.reminders.map((r, i) => {
                          const { when, channel } = describeReminder(r);
                          return (
                            <div key={r.id || i}
                              className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border)]">
                              <Bell size={12} className="text-[var(--accent-indigo)] shrink-0" />
                              <span className="text-[11px] font-bold text-[var(--text-main)]">{when}</span>
                              <span className="text-[10px] font-semibold text-[var(--text-muted)]">· {channel}</span>
                              {r.sent && (
                                <span className="ml-auto text-[9px] font-black uppercase tracking-wider"
                                  style={{ color: 'var(--status-active-text)' }}>Sent</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-[12px] font-bold text-[var(--text-main)]">—</p>
                    )}
                  </div>
                </div>

                {/* Involved Parties */}
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4 space-y-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Users size={13} /> Involved Parties
                  </p>
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {getInitials(userMap[task.assignedBy])}
                    </div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Assigned By</p><p className="text-[12px] font-bold text-[var(--text-main)]">{userMap[task.assignedBy] || 'Unknown'}</p></div>
                    {completionBadge(task.assignedBy)}
                  </div>
                  {/* A live dependency doer is on target_staff_id like an assignee, but they hold
                      the dependency only — never the task — so they get their own row below. */}
                  {(task.assignedTo || []).filter(id => id !== task.dependencyDoerId).map(id => (
                    <div key={id} className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {getInitials(userMap[id])}
                      </div>
                      <div>
                        <p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Assigned To</p>
                        <p className="text-[12px] font-bold text-[var(--text-main)]">{userMap[id] || 'Unknown'}</p>
                      </div>
                      {completionBadge(id)}
                    </div>
                  ))}
                  {/* Only when the completer is on the task in no other capacity — otherwise
                      their own row carries the mark, on the right. */}
                  {completedById && !completerHasOwnRow && (
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {getInitials(userMap[task.completedBy])}
                      </div>
                      <div className="min-w-0">
                        <p className="text-[9px] font-black text-[var(--text-muted)] uppercase">
                          Final Completion By
                          {task.completedAt && (
                            <span className="ml-1 text-[var(--accent-green)]">· {formatDate(task.completedAt)}</span>
                          )}
                        </p>
                        <p className="text-[12px] font-bold text-[var(--text-main)]">
                          {userMap[task.completedBy] || 'Unknown'}
                        </p>
                      </div>
                    </div>
                  )}
                  {dependencyPerson && (
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {getInitials(dependencyPerson.name)}
                      </div>
                      <div className="min-w-0">
                        <p className="text-[9px] font-black text-[var(--text-muted)] uppercase">
                          Depend On Other
                          {/* Says whether the task is still waiting on them, so the row doesn't
                              read as an open dependency once they have finished their part. */}
                          {dependencyPerson.resolved && (
                            <span className="ml-1 text-[var(--accent-green)]">· Completed</span>
                          )}
                        </p>
                        <p className="text-[12px] font-bold text-[var(--text-main)]">{dependencyPerson.name}</p>
                      </div>
                      {completionBadge(dependencyPerson.id)}
                    </div>
                  )}
                  {task.watchers?.length > 0 && (
                    <div>
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase mb-1.5">In Loop</p>
                      <div className="flex flex-wrap gap-1.5">
                        {task.watchers.map(id => (
                          <span key={id} className="flex items-center gap-1 px-2 py-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-full text-[10px] font-black">
                            <span className="w-4 h-4 rounded-full flex items-center justify-center text-white text-[8px]" style={{ background: 'var(--avatar-bg)' }}>{getInitials(userMap[id])}</span>
                            {userMap[id] || 'Unknown'}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-[10px] font-black text-[var(--text-muted)] uppercase pt-2 border-t border-[var(--border)]">
                    <span>Created On</span><span>{task.createdAt ? formatDate(task.createdAt) : '—'}</span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-black text-[var(--text-muted)] uppercase">
                    <span>Delegation ID</span><span className="opacity-60">{task.id?.slice(-8)}</span>
                  </div>
                </div>
              </div>

              {/* Check Points (checklist) */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <CheckSquare size={13} /> Check Points ({checklistDone}/{checklistTotal})
                  </p>
                  {checklistTotal > 0 && (
                    <span className="text-[10px] font-black text-[var(--accent-indigo)]">{Math.round((checklistDone / checklistTotal) * 100)}%</span>
                  )}
                </div>
                {checklistTotal > 0 && (
                  <div className="h-1.5 w-full rounded-full bg-[var(--bg-card)] overflow-hidden mb-3">
                    <div className="h-full rounded-full bg-[var(--accent-indigo)] transition-all duration-300"
                      style={{ width: `${(checklistDone / checklistTotal) * 100}%` }} />
                  </div>
                )}
                {checklistTotal === 0 ? (
                  <div className="py-6 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2 mb-3">
                    <CheckSquare size={24} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No check points yet</p>
                  </div>
                ) : (
                  <div className="space-y-1.5 mb-3">
                    {localChecklist.map(item => (
                      <div key={item.id} className="flex items-center gap-2 bg-[var(--bg-card)] rounded-lg px-3 py-2">
                        {/* In-Loop members observe the check points; they can't tick or remove them. */}
                        <button type="button" onClick={() => handleToggleSubtask(item)} disabled={isPureWatcher}
                          className="text-[var(--accent-indigo)] shrink-0 disabled:opacity-40 disabled:cursor-not-allowed">
                          {item.completed ? <CheckSquare size={16} /> : <Square size={16} />}
                        </button>
                        <span className={`flex-1 text-[12px] font-bold text-[var(--text-main)] ${item.completed ? 'line-through opacity-50' : ''}`}>{item.title}</span>
                        {!isPureWatcher && (
                          <button type="button" onClick={() => handleRemoveSubtask(item)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]"><X size={13} /></button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {/* Save appears only when there are unsaved tick/remove changes. */}
                {checklistDirty && !isPureWatcher && (
                  <div className="flex justify-end">
                    <button type="button" onClick={handleSaveChecklist} disabled={savingChecklist}
                      className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo)] text-white shadow-sm hover:opacity-90 disabled:opacity-60">
                      <Save size={13} /> {savingChecklist ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                )}
              </div>

              {/* Subtasks (real child tasks linked by parent_task_id) */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Layers size={13} /> Subtasks ({(task.subtasks || []).length})
                  </p>
                  <button type="button" onClick={() => setSubtaskFormOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest">
                    <Plus size={13} /> Add Subtask
                  </button>
                </div>
                {(task.subtasks || []).length === 0 ? (
                  <button type="button" onClick={() => setSubtaskFormOpen(true)}
                    className="w-full py-6 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2 hover:border-[var(--accent-indigo)] transition-colors">
                    <Layers size={24} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No subtasks yet — tap to add</p>
                  </button>
                ) : (
                  <div className="space-y-1.5">
                    {task.subtasks.map(st => {
                      const scfg = STATUS_CONFIG[st.status] || STATUS_CONFIG.pending;
                      return (
                        <button type="button" key={st.id} onClick={() => setSubtaskDetailId(st.id)}
                          className="w-full flex items-center gap-2.5 bg-[var(--bg-card)] rounded-lg px-3 py-2.5 text-left hover:border-[var(--accent-indigo)] border border-transparent transition-all">
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: scfg.color }} />
                          <span className="flex-1 min-w-0">
                            <span className="block text-[12px] font-bold text-[var(--text-main)] truncate">{st.title}</span>
                            {(st.assignedTo || []).length > 0 && (
                              <span className="block text-[10px] text-[var(--text-muted)] truncate">{st.assignedTo.map(id => userMap[id] || id).join(', ')}</span>
                            )}
                          </span>
                          <span className="px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider shrink-0" style={{ color: scfg.color, background: 'var(--input-bg)' }}>{scfg.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Assignment Attachments — files added when the task was created/assigned. */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Paperclip size={13} /> Assignment Attachments ({task.attachments?.length || 0})
                  </p>
                  {!isPureWatcher && (
                    <label className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer">
                      Attach File
                      <input type="file" className="hidden" onChange={handleAttach} />
                    </label>
                  )}
                </div>
                {(task.attachments || []).length > 0 ? (
                  <div className="space-y-2">
                    {task.attachments.map(a => (
                      <AttachmentItem key={a.id} attachment={a} />
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">No assignment attachments.</p>
                )}
              </div>

              {/* Completion Evidence — files uploaded while completing the task, kept
                  entirely separate from the assignment attachments above (#16). Required
                  before completion when Evidence Required is active (#14). */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <FileCheck2 size={13} /> Completion Evidence ({task.completionAttachments?.length || 0})
                    {task.evidenceRequired && (
                      <span className="px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-[var(--accent-red-bg)] text-[var(--accent-red)] border border-[var(--accent-red-border)]">Required</span>
                    )}
                  </p>
                  {!isPureWatcher && (
                    <label className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-green)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer">
                      {uploadingEvidence ? 'Uploading...' : 'Upload Evidence'}
                      <input type="file" className="hidden" onChange={handleEvidenceAttach} disabled={uploadingEvidence} />
                    </label>
                  )}
                </div>
                {task.evidenceRequired && !(task.completionAttachments || []).length && (
                  <p className="mb-2 text-[10px] font-bold text-[var(--accent-red)]">Evidence upload is required before completing this task.</p>
                )}
                {(task.completionAttachments || []).length > 0 ? (
                  <div className="space-y-2">
                    {task.completionAttachments.map(a => (
                      <AttachmentItem key={a.id} attachment={a} onRemove={isPureWatcher ? undefined : () => handleRemoveEvidence(a.id)}
                        icon={FileCheck2} iconClass="text-[var(--accent-green)]" linkHover="hover:text-[var(--accent-green)]" />
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">No completion evidence uploaded yet.</p>
                )}
              </div>

              {/* Follow-Ups — the task's single communication timeline. People's messages and the
                  system's record of what happened, interleaved oldest-first. Anyone on the task
                  (assigner, assignee, in-loop member) can read it and post to it. */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                  <Bell size={13} /> Follow-Ups (Activity Timeline) · {task.followUpCount ?? (task.followUps || []).length}
                </p>
                {activityTimeline.length === 0 ? (
                  <div className="py-8 flex flex-col items-center justify-center gap-2">
                    <Bell size={28} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">Nothing here yet</p>
                  </div>
                ) : (
                  <div className="space-y-3 mb-3 max-h-72 overflow-y-auto no-scrollbar">
                    {activityTimeline.map(item => (
                      <div key={item.id} className="flex items-start gap-2">
                        {item.kind === 'system' ? (
                          <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)]">
                            <Info size={13} />
                          </div>
                        ) : (
                          <div className="w-7 h-7 rounded-full flex items-center justify-center text-white font-black text-[9px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                            {getInitials(item.name)}
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className={`text-[11px] font-black ${item.kind === 'system' ? 'text-[var(--text-muted)] uppercase tracking-wider' : 'text-[var(--text-main)]'}`}>
                            {item.kind === 'system' ? 'System' : item.name}
                          </p>
                          <p className={`text-[12px] ${item.kind === 'system' ? 'font-bold text-[var(--text-muted)]' : 'font-medium text-[var(--text-main)]'}`}>
                            {item.text}
                            {item.kind === 'system' && item.by && <span className="opacity-70"> · by {item.by}</span>}
                          </p>
                          {item.reason && (
                            <p className="mt-1 px-2 py-1 bg-[var(--accent-yellow-bg)] text-[var(--text-muted)] text-[11px] rounded-lg italic">"{item.reason}"</p>
                          )}
                          <p className="text-[9px] font-bold text-[var(--text-muted)] opacity-70">{item.at ? formatDateTime(item.at) : ''}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input value={followUpText} onChange={e => setFollowUpText(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddFollowUp(); } }}
                    placeholder="Add a follow-up..."
                    className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                  <button type="button" onClick={handleAddFollowUp} disabled={postingFollowUp || !followUpText.trim()}
                    className="flex items-center gap-1.5 px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest disabled:opacity-50 shrink-0">
                    <Bell size={13} /> {postingFollowUp ? '...' : 'Follow Up'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </AnimatePresence>

    {/* Sibling of the task panel, not a child of it: that panel is a scroll container
        (`overflow-y-auto`), so an absolutely-positioned dialog inside it would be placed
        against the scrolled content and drift with it. Fixed at z-[310] instead — one step
        above the panel's z-[300], so the task stays visible behind the question. */}
    {confirmDelete && (
      <div className="fixed inset-0 z-[310] flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          onClick={deleting ? undefined : () => setConfirmDelete(false)} />
        <div role="alertdialog" aria-modal="true"
          className="relative w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-red-bg)] text-[var(--accent-red)] shrink-0">
              <Trash2 size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Delete this task?</h3>
          </div>

          <div className="px-5 py-4 space-y-3">
            <p className="text-[12.5px] font-bold truncate">{task?.title}</p>
            <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
              It moves to <b className="text-[var(--text-main)]">Deleted Tasks</b> and can be
              brought back from there.
            </p>
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <Bell size={14} className="mt-[1px] shrink-0" />
              <span>
                The assignee and everyone in the loop are emailed that it was deleted. That
                notification cannot be recalled.
              </span>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
            <button type="button" onClick={() => setConfirmDelete(false)} disabled={deleting}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Keep it
            </button>
            <button type="button" onClick={handleDelete} disabled={deleting} autoFocus
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              <Trash2 size={14} /> {deleting ? 'Deleting…' : 'Delete Task'}
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Deadline / Date Revision picker. Reached two ways: the assigner's "Revise" button next
        to the deadline, and the assignee's "Revise" option in their working dropdown — the
        latter is how a doer shifts a delegation they can't finish in time.

        The reason is optional — the picker no longer blocks Done on it, and the backend accepts
        a reasonless revision too. */}
    <MiniDatePicker
      isOpen={deadlinePickerOpen}
      onClose={() => setDeadlinePickerOpen(false)}
      value={task?.end}
      title={canDecideDeadline ? 'Revise Deadline' : 'Request Deadline Revision'}
      onApply={(iso, remark) => handleReviseDeadline(iso, remark)}
      holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
      disablePast
      remarkLabel="Reason for Revision"
    />

    {/* Reopen picker — the assigner sets a NEW deadline and may optionally give a reason; then
        the task is handed back to the assignee for rework. */}
    <MiniDatePicker
      isOpen={reopenPickerOpen}
      onClose={() => setReopenPickerOpen(false)}
      value={task?.end}
      title="Reopen Task"
      onApply={(iso, remark) => handleReopenWithDeadline(iso, remark)}
      holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
      disablePast
      remarkLabel="Reason for Reopening"
    />

    {/* Doer Name + Reason capture for Dependent on Other / Blocked. */}
    <StatusReasonModal
      isOpen={!!reasonStatus}
      status={reasonStatus}
      users={users}
      // Whoever already holds the task — its assignees (which includes the caller, and any doer
      // it was previously handed to) — cannot be the person it now waits on.
      excludeIds={[...(task?.assignedTo || []), task?.dependencyDoerId].filter(Boolean)}
      saving={savingReason}
      onClose={() => setReasonStatus(null)}
      onSubmit={({ reason, doerName, doerId }) => doStatusUpdate(reasonStatus, { reason, doerName, doerId })}
    />

    {/* Add Subtask — a real child task linked by parent_task_id */}
    <TaskFormModal
      isOpen={subtaskFormOpen}
      parentId={taskId}
      categories={metaCats}
      tags={metaTags}
      onClose={() => setSubtaskFormOpen(false)}
      onSaved={() => { setSubtaskFormOpen(false); fetchDetail({ silent: true }); onChanged?.(); }}
    />

    {/* Nested subtask detail (its own status / check points / subtasks) */}
    {subtaskDetailId && (
      <TaskDetailsModal
        isOpen
        taskId={subtaskDetailId}
        scope={scope}
        onClose={() => setSubtaskDetailId(null)}
        onChanged={() => { fetchDetail({ silent: true }); onChanged?.(); }}
        onEdit={onEdit}
      />
    )}
    </>
  );
};

export default TaskDetailsModal;
