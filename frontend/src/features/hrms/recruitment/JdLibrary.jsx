import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, Search, Save, Rocket, ExternalLink, Lock, ArrowRight,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getJds, updateJd, getRequisition } from '../../../services/hrmsApi';

/**
 * HRMS ▸ Step 3 — Job Description.
 *
 * Internal Recruitment SOP §3: once Management/Finance has cleared headcount and budget
 * (Step 2), HR writes the JD against the now-approved requisition — not before. The read-
 * only panel is exactly what was approved (department, position, reporting line, business
 * justification, required skills/experience, the approved budget); everything below it is
 * HR's own authoring.
 *
 * A JD is still minted at raise time (see RequisitionFormModal) so it has somewhere to live
 * from the start, but it opens empty until this screen writes it — "HR creates the JD" means
 * HR is the one who first gives it real content, not that a new record is created here.
 *
 * Kept single-purpose on purpose: the Position Scorecard is its own screen
 * (ScorecardLibrary.jsx), with its own HOD/Management dual-approval signing already built
 * and tested there — this page only points to it once the JD is written, rather than
 * duplicating that builder here too.
 */

// Tone is meaning, and matches `toneFor` in internalKit: amber while somebody is being
// waited on, green once the JD is signed off, red when it came back. Approved used to be
// grey, which made the one state that unblocks sourcing the hardest to spot in the list.
const STATUS_TONES = {
  'Pending Approval': 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  Approved: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  Rejected: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Draft: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const STATUS_BAR = {
  'Pending Approval': 'var(--accent-orange)',
  Approved: 'var(--accent-green)',
  Rejected: 'var(--accent-red)',
  Draft: 'var(--border)',
};

// Approval states in which the linked requisition has not yet cleared its budget gate --
// mirrors backend PRE_BUDGET_STATES exactly (models/hrms.py), so this screen's message
// agrees with the 409 the server would otherwise give.
const PRE_BUDGET_STATES = new Set(['Pending HR Verification', 'Pending Budget Approval']);

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const AREA = 'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none disabled:opacity-60';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const READONLY_LABEL = 'block text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1';

const money = (value) => {
  if (value == null || value === '') return '—';
  const n = Number(value);
  return Number.isNaN(n) ? '—' : n.toLocaleString();
};

// A field renders editable only when the viewer holds JD_WRITE AND the JD isn't locked --
// otherwise it shows the same value as plain text, rather than an input the viewer might
// try to type into and wonder why nothing happens.
const JdField = ({ id, label, value, onChange, editable }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    {editable ? (
      <input id={id} value={value} onChange={onChange} className={FIELD} />
    ) : (
      <p className="h-9 flex items-center text-[13px] text-[var(--text-main)] truncate">{value || '—'}</p>
    )}
  </div>
);

const JdArea = ({ id, label, value, onChange, editable, rows = 3 }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    {editable ? (
      <textarea id={id} rows={rows} value={value} onChange={onChange} className={AREA} />
    ) : (
      <p className="text-[13px] text-[var(--text-main)] whitespace-pre-wrap">{value || '—'}</p>
    )}
  </div>
);

// What was actually approved at Step 1/2 -- shown read-only so HR writes the JD against the
// real request, not a half-remembered version of it. Fetched separately from the JD list
// because the JD document itself doesn't carry these facts (they live on the requisition).
const ApprovedRequisitionPanel = ({ requisition, loading }) => {
  if (loading) {
    return (
      <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
        <p className="text-[12px] text-[var(--text-muted)]">Loading approved request…</p>
      </div>
    );
  }
  if (!requisition) return null;
  const band = requisition.approved_salary_band_min != null
    ? `${money(requisition.approved_salary_band_min)} – ${money(requisition.approved_salary_band_max)}`
    : 'Not yet approved';
  const items = [
    ['Requisition ID', requisition.request_no],
    ['Department', requisition.department_name || '—'],
    ['Position', requisition.designation_name || '—'],
    ['Reporting To', requisition.reporting_manager_name || '—'],
    ['No. of Positions', requisition.approved_headcount ?? requisition.vacancy ?? '—'],
    ['Required Skills', requisition.essential_skills || '—'],
    ['Experience', requisition.experience_required || '—'],
    ['Approved Budget', band],
  ];
  return (
    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-3">
      <h3 className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        Approved Requisition (read-only)
      </h3>
      <div className="grid grid-cols-2 gap-3">
        {items.map(([label, value]) => (
          <div key={label}>
            <span className={READONLY_LABEL}>{label}</span>
            <p className="text-[12.5px] font-semibold text-[var(--text-main)] break-words">{value}</p>
          </div>
        ))}
      </div>
      <div>
        <span className={READONLY_LABEL}>Business Justification</span>
        <p className="text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
          {requisition.business_justification || '—'}
        </p>
      </div>
      <Link to={`/hrms/internal-requisitions/${requisition.request_no}`}
        className="inline-flex items-center gap-1.5 text-[11.5px] font-bold text-[var(--accent-indigo)]">
        <ExternalLink size={12} /> Open full requisition
      </Link>
    </div>
  );
};

const JdLibrary = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [requisition, setRequisition] = useState(null);
  const [reqLoading, setReqLoading] = useState(false);

  const canWrite = can(CAP.JD_WRITE);
  const locked = selected?.status === 'Approved';
  const preBudget = requisition && PRE_BUDGET_STATES.has(requisition.approval_status);
  const editable = canWrite && !locked && !preBudget;

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getJds({ ...scope, status: status || undefined, search: search || undefined });
      const list = data?.job_descriptions || [];
      setRows(list);
      setSelected((prev) => (prev ? list.find((j) => j.jd_no === prev.jd_no) || null : null));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load job descriptions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status, search]);

  useEffect(() => { load(); }, [load]);

  const select = (jd) => {
    setSelected(jd);
    setForm({
      title: jd.title || '', responsibilities: jd.responsibilities || '',
      job_summary: jd.job_summary || '',
      skills: jd.skills || '', qualifications: jd.qualifications || '',
      experience: jd.experience || '', ctc: jd.ctc || '',
      location: jd.location || '', benefits: jd.benefits || '',
      key_competencies: jd.key_competencies || '', culture_fit: jd.culture_fit || '',
      additional_requirements: jd.additional_requirements || '',
    });
    setRequisition(null);
    setReqLoading(true);
    getRequisition(jd.request_no, scope)
      .then(({ data }) => setRequisition(data))
      .catch(() => setRequisition(null))
      .finally(() => setReqLoading(false));
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await updateJd(selected.jd_no, form, scope);
      showSuccess(`${selected.jd_no} saved`);
      setSelected(data);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the job description.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading job descriptions…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={FileText}
        title="Job Description"
        subtitle="Step 3 — written by HR once Management or Finance has approved headcount and budget."
        actions={<HrmsScopeBar />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by JD number or title…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {['Pending Approval', 'Approved', 'Rejected'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {rows.length === 0 ? (
        <HrmsEmpty icon={FileText} title="No job descriptions yet"
          hint="Raise a requisition on the Requisitions screen — its JD opens here once budget is approved." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1">
            <p className="px-0.5 text-[11px] text-[var(--text-muted)]">
              {rows.length} job description{rows.length === 1 ? '' : 's'}
            </p>
            {rows.map((jd) => (
              <button key={jd.jd_no} type="button" onClick={() => select(jd)}
                className={`relative w-full text-left p-3 pl-4 rounded-xl border overflow-hidden transition-colors ${
                  selected?.jd_no === jd.jd_no
                    ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                    : 'border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)]'}`}>
                {/* The status colour runs down the edge so the list scans by state without
                    reading every chip. */}
                <span className="absolute left-0 top-0 bottom-0 w-1"
                  style={{ background: STATUS_BAR[jd.status] || 'var(--border)' }} />
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11.5px] text-[var(--text-muted)]">{jd.jd_no}</span>
                  <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${
                    STATUS_TONES[jd.status] || 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
                    {jd.status}
                  </span>
                </div>
                <p className="mt-1 text-[13.5px] font-bold text-[var(--text-main)] truncate">
                  {jd.title || 'Untitled'}
                </p>
                <p className="text-[11.5px] text-[var(--text-muted)] font-mono">{jd.request_no}</p>
              </button>
            ))}
          </div>

          <div className="lg:col-span-2 space-y-4">
            {!selected ? (
              <HrmsEmpty icon={FileText} title="Select a job description"
                hint="Pick one from the list to view or write its content." />
            ) : (
              <>
                <ApprovedRequisitionPanel requisition={requisition} loading={reqLoading} />

                {preBudget && (
                  <div className="p-3.5 rounded-lg border border-[var(--accent-orange)]/30 bg-[var(--accent-orange-bg)]
                                  text-[12px] text-[var(--accent-orange)] flex items-start gap-2">
                    <Lock size={14} className="shrink-0 mt-0.5" />
                    The Job Description cannot be written until Management or Finance approves
                    headcount and budget for this requisition ({requisition?.approval_status}).
                  </div>
                )}

                <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-4">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                      <p className="font-mono text-[12px] text-[var(--text-muted)]">{selected.jd_no}</p>
                      <p className="text-[15px] font-bold text-[var(--text-main)]">{selected.title || 'Untitled'}</p>
                      <p className="text-[12px] text-[var(--text-muted)]">
                        Linked to {selected.request_no} · v{selected.version || 1}
                      </p>
                    </div>
                    {locked ? (
                      <span className="h-8 px-3 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] text-[12px] font-bold flex items-center gap-1.5">
                        <Rocket size={14} /> Approved for Recruitment
                      </span>
                    ) : editable && (
                      <button type="button" onClick={save} disabled={saving}
                        className="h-8 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                        <Save size={14} /> {saving ? 'Saving…' : 'Save Job Description'}
                      </button>
                    )}
                  </div>

                  {locked && (
                    <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
                      This JD is approved and locked — it is what was signed off on and what
                      candidates will see. Raise a new requisition to hire on different terms.
                    </div>
                  )}
                  {selected.status === 'Pending Approval' && !preBudget && (
                    <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
                      Once this is saved, prepare the Position Scorecard next — the hiring
                      manager approves it (and Management too, for managerial+ roles) before
                      this JD becomes Approved for Recruitment.
                    </div>
                  )}
                  {selected.status === 'Rejected' && selected.md_remarks && (
                    <div className="p-3 rounded-lg border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)] text-[12px] text-[var(--accent-red)]">
                      Rejected: {selected.md_remarks}
                    </div>
                  )}

                  <JdArea id="jd-summary" label="Job Summary" rows={3} value={form.job_summary}
                    onChange={set('job_summary')} editable={editable} />

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <JdField id="jd-title" label="Title" value={form.title} onChange={set('title')}
                      editable={editable} />
                    <JdField id="jd-loc" label="Location" value={form.location} onChange={set('location')}
                      editable={editable} />
                    <JdField id="jd-exp" label="Required Experience" value={form.experience} onChange={set('experience')}
                      editable={editable} />
                    <JdField id="jd-ctc" label="CTC" value={form.ctc} onChange={set('ctc')}
                      editable={editable} />
                  </div>

                  <JdArea id="jd-resp" label="Key Responsibilities" rows={5} value={form.responsibilities}
                    onChange={set('responsibilities')} editable={editable} />
                  <JdArea id="jd-skills" label="Required Skills" value={form.skills} onChange={set('skills')}
                    editable={editable} />
                  <JdArea id="jd-qual" label="Qualifications" value={form.qualifications} onChange={set('qualifications')}
                    editable={editable} />
                  <JdArea id="jd-comp" label="Key Competencies" value={form.key_competencies}
                    onChange={set('key_competencies')} editable={editable} />
                  <JdArea id="jd-culture" label="Culture-Fit Expectations" value={form.culture_fit}
                    onChange={set('culture_fit')} editable={editable} />
                  <JdArea id="jd-extra" label="Additional Requirements" value={form.additional_requirements}
                    onChange={set('additional_requirements')} editable={editable} />
                  <JdArea id="jd-ben" label="Benefits" value={form.benefits} onChange={set('benefits')}
                    editable={editable} />
                </div>

                {!preBudget && !locked && (
                  <Link to="/hrms/scorecards"
                    className="flex items-center justify-between gap-2 p-4 rounded-xl border
                              border-[var(--border)] bg-[var(--bg-card)] text-[13px]
                              font-semibold text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)]">
                    Next: prepare the Position Scorecard
                    <ArrowRight size={15} />
                  </Link>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default JdLibrary;
