import React, { useEffect, useState } from 'react';
import { X, FilePlus2, AlertTriangle, Save } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { useAuth } from '../../../context/AuthContext';
import {
  createRequisition, updateRequisition, getDepartments, getDesignations, getEmployees,
  getSanctionedPosition,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ raise / edit a hiring requisition.
 *
 * Reorganised around the Internal Recruitment SOP's own §3: "the HOD raises a requisition
 * specifying role, reporting line, and business justification" — three sections in the
 * order the SOP itself reads in: Request Information, Position Details, Business
 * Requirement.
 *
 * The Job Description is deliberately NOT authored here. SOP §3 (Step 3) makes writing it
 * HR's job, once Management/Finance has cleared headcount and budget — see JdLibrary.jsx,
 * which is where it gets written once this requisition clears that gate.
 *
 * Department and designation are pickers over the Phase 2 masters, not free-text boxes.
 * That is the whole point of those masters: the source shipped a department dropdown that
 * disagreed with another dropdown on the same screen.
 *
 * -- Save Draft ------------------------------------------------------------------------
 * The server has no draft status for a requisition — raising one starts the approval
 * chain immediately (SOP §3), so there is nowhere on the server for an unfinished one to
 * sit. "Save Draft" is therefore a LOCAL save (one slot, this browser only): it lets a HOD
 * close the form without losing what they typed, and is offered back the next time they
 * open a NEW requisition. It is explicitly not a second record type, a second approval
 * chain, or anything the server or another user ever sees.
 */
const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const AREA = 'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const READONLY = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-muted)] flex items-center';
const SECTION_HEADING = 'text-[10.5px] font-bold uppercase tracking-widest text-[var(--accent-indigo)] mb-3';

const DRAFT_KEY = 'hrms_requisition_draft_v1';

const day = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};

const emptyForm = {
  department_id: '', designation_id: '', vacancy: 1, experience_required: '',
  qualification: '', essential_skills: '', required_date: '',
  reporting_manager_id: '', offering_ctc: '', urgency_level: 'Medium',
  work_location: 'Office', gender_preferred: 'Any', employment_type: 'Full-time',
  business_justification: '', notes: '',
  requisition_type: 'New Position', replacement_for_user_id: '',
  replacement_reason: '', last_working_day: '',
};
const RequisitionFormModal = ({ existing, onClose, onSaved }) => {
  const { scope } = useHrms();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const isEdit = !!existing;

  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [people, setPeople] = useState([]);
  const [saving, setSaving] = useState(false);
  const [moreDetails, setMoreDetails] = useState(false);
  const [restoredDraft, setRestoredDraft] = useState(false);

  const [form, setForm] = useState(() => {
    if (existing) {
      return {
        department_id: existing.department_id || '',
        designation_id: existing.designation_id || '',
        vacancy: existing.vacancy ?? 1,
        experience_required: existing.experience_required || '',
        qualification: existing.qualification || '',
        essential_skills: existing.essential_skills || '',
        required_date: existing.required_date || '',
        reporting_manager_id: existing.reporting_manager_id || '',
        offering_ctc: existing.offering_ctc ?? '',
        urgency_level: existing.urgency_level || 'Medium',
        work_location: existing.work_location || 'Office',
        gender_preferred: existing.gender_preferred || 'Any',
        employment_type: existing.employment_type || 'Full-time',
        business_justification: existing.business_justification || '',
        notes: existing.notes || '',
        requisition_type: existing.requisition_type || 'New Position',
        replacement_for_user_id: existing.replacement_for_user_id || '',
        replacement_reason: existing.replacement_reason || '',
        last_working_day: existing.last_working_day || '',
      };
    }
    // A NEW requisition offers back whatever was last saved as a draft in this browser.
    try {
      const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
      if (saved?.form) return { ...emptyForm, ...saved.form };
    } catch { /* a corrupt or missing draft is simply no draft */ }
    return emptyForm;
  });

  useEffect(() => {
    if (!existing) {
      try {
        if (localStorage.getItem(DRAFT_KEY)) setRestoredDraft(true);
      } catch { /* localStorage unavailable — simply no draft banner */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    getDepartments(scope).then(({ data }) => setDepartments((data?.departments || []).filter((d) => d.active))).catch(() => {});
    getDesignations(scope).then(({ data }) => setDesignations((data?.designations || []).filter((d) => d.active))).catch(() => {});
    // Assignee, "reporting to" and "replacing" all need a real login account — the server
    // validates whoever is picked against the `learners` collection. A profile created at
    // onboarding before the person has a login (`pending_user_link`) has no `user_id` at
    // all, and offering it here meant its option fell back to the person's NAME as the
    // submitted value, which the server then rejected as "Invalid" for that field.
    getEmployees({ ...scope, limit: 500 })
      .then(({ data }) => setPeople((data?.employees || []).filter((e) => e.user_id)))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Phase 11-R, Item 7 ── read the live sanction position whenever the department,
  // designation or vacancy count changes, so the raiser is told BEFORE they submit that
  // the request will be escalated. This is a HINT: the server re-evaluates the same figures
  // at raise time and again at each approval step, and its answer is the one that decides.
  const [sanction, setSanction] = useState(null);
  useEffect(() => {
    if (!form.department_id || !form.designation_id) {
      setSanction(null);
      return;
    }
    let cancelled = false;
    getSanctionedPosition({
      ...scope,
      department_id: form.department_id,
      designation_id: form.designation_id,
      requested: Number(form.vacancy) || 1,
    })
      .then(({ data }) => { if (!cancelled) setSanction(data); })
      .catch(() => { if (!cancelled) setSanction(null); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.department_id, form.designation_id, form.vacancy]);

  const isReplacement = form.requisition_type === 'Replacement';

  const buildPayload = () => ({
    ...form,
    vacancy: Number(form.vacancy) || 1,
    offering_ctc: form.offering_ctc === '' ? null : Number(form.offering_ctc),
    reporting_manager_id: form.reporting_manager_id || null,
    replacement_for_user_id: form.replacement_for_user_id || null,
  });

  const saveDraft = () => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ form }));
      showSuccess('Draft saved on this device — reopen "Raise" to pick up where you left off.');
      onClose();
    } catch {
      showError('Could not save a draft on this device.');
    }
  };

  const discardDraft = () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to discard */ }
    setForm(emptyForm);
    setRestoredDraft(false);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.reporting_manager_id) {
      showError('Name who this position reports to.');
      return;
    }
    if (!form.business_justification.trim()) {
      showError('Give the business justification for this position.');
      return;
    }
    // Phase 11-R, Item 7. Mirrors the server rule; the server still enforces it.
    if (isReplacement && !form.replacement_for_user_id) {
      showError('Name the employee being replaced, or switch this to a new position.');
      return;
    }
    if (isReplacement && !form.replacement_reason.trim()) {
      showError('Give the reason for the replacement.');
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      if (isEdit) {
        await updateRequisition(existing.request_no, payload, scope);
        showSuccess(`Requisition ${existing.request_no} updated`);
      } else {
        const { data } = await createRequisition(payload, scope);
        try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clear */ }
        showSuccess(
          `Requisition ${data.request_no} raised — HR verifies it, then Management or `
          + 'Finance approves the budget before sourcing can begin');
      }
      onSaved();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the requisition.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <FilePlus2 size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">
              {isEdit ? `Edit ${existing.request_no}` : 'Raise Internal Recruitment Request'}
            </h2>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        {restoredDraft && !isEdit && (
          <div className="mx-5 mt-4 flex items-center justify-between gap-3 rounded-lg
                          border border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)]
                          px-3.5 py-2.5">
            <p className="text-[12px] text-[var(--accent-indigo)]">
              Restored from a draft saved on this device.
            </p>
            <button type="button" onClick={discardDraft}
              className="text-[11.5px] font-bold text-[var(--accent-indigo)] underline shrink-0">
              Discard draft
            </button>
          </div>
        )}

        <form onSubmit={submit} className="p-5 space-y-6 overflow-y-auto">
          {/* ══ 1. Request Information ══ */}
          <div>
            <h3 className={SECTION_HEADING}>1. Request Information</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {isEdit && (
                <>
                  <div>
                    <label className={LABEL}>Requisition ID</label>
                    <p className={READONLY}>{existing.request_no}</p>
                  </div>
                  <div>
                    <label className={LABEL}>Request date</label>
                    <p className={READONLY}>{day(existing.created_at)}</p>
                  </div>
                </>
              )}
              <div>
                <label className={LABEL} htmlFor="r-dept">Department *</label>
                <select id="r-dept" required value={form.department_id} onChange={set('department_id')} className={FIELD}>
                  <option value="">Select…</option>
                  {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL}>Requesting HOD</label>
                <p className={READONLY}>
                  {isEdit ? (existing.created_by_name || '—') : (user?.full_name || 'You')}
                </p>
              </div>
            </div>
          </div>

          {/* ══ 2. Position Details ══ */}
          <div className="pt-5 border-t border-[var(--border)]">
            <h3 className={SECTION_HEADING}>2. Position Details</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="r-desig">Position / Role *</label>
                <select id="r-desig" required value={form.designation_id} onChange={set('designation_id')} className={FIELD}>
                  <option value="">Select…</option>
                  {designations.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
                {designations.length === 0 && (
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    No designations yet — add one under HRMS ▸ Designations first.
                  </p>
                )}
              </div>
              <div>
                <label className={LABEL} htmlFor="r-report">Reporting To *</label>
                <select id="r-report" required value={form.reporting_manager_id}
                  onChange={set('reporting_manager_id')} className={FIELD}>
                  <option value="">Select…</option>
                  {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label className={LABEL} htmlFor="r-vac">No. of Positions *</label>
                <input id="r-vac" type="number" min="1" required value={form.vacancy} onChange={set('vacancy')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="r-date">Required by *</label>
                <input id="r-date" type="date" required value={form.required_date} onChange={set('required_date')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="r-exp">Required Experience *</label>
                <input id="r-exp" required value={form.experience_required} onChange={set('experience_required')}
                  placeholder="e.g. 3–5 years" className={FIELD} />
              </div>
              {/* MANDATORY, so it belongs here and not behind the "optional" toggle
                  below. `qualification` is a bare `str` on RequisitionCreate -- the API
                  answers 422 "Qualification is required" without it. It used to sit inside
                  the collapsed extras, so the submit failed with an error naming a field
                  that was not on screen and stayed hidden while you looked for it. */}
              <div>
                <label className={LABEL} htmlFor="r-qual">Qualification *</label>
                <input id="r-qual" required value={form.qualification} onChange={set('qualification')}
                  placeholder="e.g. B.Tech / MCA" className={FIELD} />
              </div>
            </div>
            <div className="mt-3">
              <label className={LABEL} htmlFor="r-skills">Required Skills / Competencies *</label>
              <textarea id="r-skills" rows={2} required value={form.essential_skills}
                onChange={set('essential_skills')} placeholder="Comma-separated" className={AREA} />
            </div>

            <button type="button" onClick={() => setMoreDetails((v) => !v)}
              className="mt-3 text-[11.5px] font-bold text-[var(--accent-indigo)]">
              {moreDetails ? 'Hide' : 'Show'} additional position details (optional)
            </button>
            {moreDetails && (
              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="r-ctc">Offered CTC (annual)</label>
                  <input id="r-ctc" type="number" min="0" value={form.offering_ctc} onChange={set('offering_ctc')} className={FIELD} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-urg">Urgency</label>
                  <select id="r-urg" value={form.urgency_level} onChange={set('urgency_level')} className={FIELD}>
                    {['High', 'Medium', 'Low'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-loc">Work location</label>
                  <select id="r-loc" value={form.work_location} onChange={set('work_location')} className={FIELD}>
                    {['Office', 'Factory', 'Remote', 'Hybrid'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-type">Employment type</label>
                  <select id="r-type" value={form.employment_type} onChange={set('employment_type')} className={FIELD}>
                    {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-gender">Gender preference</label>
                  <select id="r-gender" value={form.gender_preferred} onChange={set('gender_preferred')} className={FIELD}>
                    {['Any', 'Male', 'Female'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
              </div>
            )}
          </div>

          {/* ══ 3. Business Requirement ══ */}
          <div className="pt-5 border-t border-[var(--border)]">
            <h3 className={SECTION_HEADING}>3. Business Requirement</h3>

            <div className="flex flex-wrap gap-4 mb-3">
              {['New Position', 'Replacement'].map((value) => (
                <label key={value} className="flex items-center gap-2 text-[13px] text-[var(--text-main)]">
                  <input
                    type="radio"
                    name="requisition_type"
                    value={value}
                    checked={form.requisition_type === value}
                    onChange={set('requisition_type')}
                  />
                  {value}
                </label>
              ))}
            </div>

            {isReplacement && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                <div>
                  <label className={LABEL} htmlFor="r-repl">Replacing *</label>
                  <select id="r-repl" value={form.replacement_for_user_id}
                    onChange={set('replacement_for_user_id')} className={FIELD}>
                    <option value="">Select…</option>
                    {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-lwd">Their last working day</label>
                  <input id="r-lwd" type="date" value={form.last_working_day}
                    onChange={set('last_working_day')} className={FIELD} />
                </div>
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="r-reason">Reason for replacement *</label>
                  <input id="r-reason" value={form.replacement_reason}
                    onChange={set('replacement_reason')}
                    placeholder="Resignation, transfer, end of contract…" className={FIELD} />
                </div>
              </div>
            )}

            <div className="mb-3">
              <label className={LABEL} htmlFor="r-just">Business Justification *</label>
              <textarea id="r-just" rows={3} required value={form.business_justification}
                onChange={set('business_justification')}
                placeholder="Why the organisation needs this position" className={AREA} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-remarks">Additional Remarks</label>
              <textarea id="r-remarks" rows={2} value={form.notes}
                onChange={set('notes')} placeholder="Any other role-specific requirement" className={AREA} />
            </div>

            {sanction && (
              <div className={`mt-3 rounded-lg border px-3.5 py-3 ${
                sanction.is_over_sanction
                  ? 'border-[var(--accent-amber,var(--accent-red))] bg-[var(--accent-amber-bg,var(--accent-red-bg))]'
                  : 'border-[var(--border)] bg-[var(--input-bg)]'
              }`}>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-[12.5px]">
                  <span className="text-[var(--text-muted)]">
                    Sanctioned:{' '}
                    <b className="text-[var(--text-main)]">
                      {sanction.has_sanction ? sanction.sanctioned : 'not set'}
                    </b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Filled: <b className="text-[var(--text-main)]">{sanction.actual}</b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Already committed:{' '}
                    <b className="text-[var(--text-main)]">{sanction.open_requisitions}</b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Available:{' '}
                    <b className="text-[var(--text-main)]">
                      {sanction.available ?? '—'}
                    </b>
                  </span>
                </div>
                {sanction.is_over_sanction && (
                  <p className="flex items-start gap-1.5 mt-2 text-[12.5px] font-semibold text-[var(--accent-amber,var(--accent-red))]">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    This requisition exceeds the sanctioned strength and will be escalated
                    for approval. MD approval is mandatory.
                  </p>
                )}
              </div>
            )}
          </div>

          {!isEdit && (
            <div className="pt-5 border-t border-[var(--border)] flex items-start gap-2.5">
              <FilePlus2 size={15} className="text-[var(--accent-indigo)] mt-0.5 shrink-0" />
              <p className="text-[11.5px] text-[var(--text-muted)]">
                The Job Description and Position Scorecard are written by HR once Management
                or Finance approves headcount and budget for this request — see the
                Requisitions screen once it clears that gate.
              </p>
            </div>
          )}

          {/* ══ Budget — Management/Finance's own figures, recorded at approval, shown here
              read-only once they exist. Not part of the HOD's raise (SOP §3 names only role,
              reporting line and justification as theirs to give). ══ */}
          {isEdit && (existing.budget_sanctioned_amount != null || existing.budget_hod_amount != null) && (
            <div className="pt-5 border-t border-[var(--border)]">
              <h3 className={SECTION_HEADING}>Budget (recorded at approval)</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-[13px]">
                <div>
                  <label className={LABEL}>Sanctioned by management</label>
                  <p className={READONLY}>{existing.budget_sanctioned_amount ?? '—'}</p>
                </div>
                <div>
                  <label className={LABEL}>Approved by HOD</label>
                  <p className={READONLY}>{existing.budget_hod_amount ?? '—'}</p>
                </div>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            {!isEdit && (
              <button type="button" onClick={saveDraft} disabled={saving}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold
                          text-[var(--text-main)] flex items-center gap-1.5 disabled:opacity-50">
                <Save size={13} /> Save Draft
              </button>
            )}
            <button type="submit" disabled={saving}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Submit Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RequisitionFormModal;
