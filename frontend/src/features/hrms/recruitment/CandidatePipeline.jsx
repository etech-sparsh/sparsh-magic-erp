import React, { useCallback, useEffect, useState } from 'react';
import {
  Users2, Search, Plus, LayoutGrid, List as ListIcon, Columns3, X, Route, AlertTriangle,
  Mail, Phone, Save, Trash2, FileText, Download, Link2, Globe, Paperclip,
  Image as ImageIcon, Check, Minus,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getCandidates, getCandidate, updateCandidate, deleteCandidate, createCandidate,
  getRequisitions, getCandidateCv, getCandidateAttachment,
  getAssessments, getTelephonicScreenings, getCandidateInterviews,
} from '../../../services/hrmsApi';
import { CandidateJourneyModal } from './CandidateJourney';
import { CANDIDATE_SOP_LABEL, sopLabelFor } from '../internal/sopLabels';

/**
 * HRMS ▸ candidate pipeline.
 *
 * Three layouts over one dataset and one filter set: Kanban, List and Grid. The columns and
 * their counts come from the server, computed with the same scoping as the rows — so a
 * hiring manager's board totals reflect their own slice, never the company's.
 *
 * Stage changes are made in the drawer from `allowed_next` — the server's own answer for
 * what this candidate may legally become. There is no drag-and-drop: dropping a card into
 * an arbitrary column implies every move is legal, and most are not.
 */

/** Mirrors backend ReferralSource (models/hrms.py) — the values a candidate's `source` may
 *  hold. `Referral` is the label a declared employee referral is filed under. */
const SOURCES = [
  'Job Portal', 'Referral', 'Employee', 'Internal Database', 'Company Website',
  'Direct Application', 'Executive Search', 'Consultant / Agency', 'Social Media',
  'Walk-in', 'Ex-Employee', 'Other',
];

/** The recruitment workflow, as the SOP words it, mapped onto the statuses that actually
 *  represent each stage. One filter entry per stage, so picking "Assessment" finds every
 *  candidate sitting anywhere inside it rather than just one of its four statuses. */
const STAGE_FILTERS = [
  ['Applied', 'Applied'],
  ['CV Screening', 'Under Review'],
  ['Telephonic Screening', 'Telephonic Passed,Telephonic Rejected'],
  ['Assessment', 'Assessment Pending,Assessment Completed,Assessment Passed,Assessment Failed'],
  ['Interview', 'Interview Scheduled,Technical Round,MD Round'],
  ['Shortlisted', 'Shortlisted'],
  ['Selected', 'Selected'],
  ['Rejected', 'Rejected,Telephonic Rejected,Assessment Failed,Duplicate'],
];

const EMPTY_FILTERS = {
  request_no: '', source: '', status: '', location: '', experience: '',
  date_from: '', date_to: '',
};

const FILTER_FIELD = 'h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)]';

const STAGE_TONE = (status) => {
  if (['Rejected', 'Duplicate', 'Offer Declined', 'Assessment Failed'].includes(status))
    return 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]';
  if (['Selected', 'Offer Accepted', 'Joined', 'Employee Created', 'Assessment Passed'].includes(status))
    return 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]';
  if (status === 'On Hold') return 'bg-[var(--input-bg)] text-[var(--text-muted)]';
  return 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]';
};

const StageBadge = ({ status }) => (
  <span className={`inline-block px-2 py-1 rounded-md text-[11px] font-bold whitespace-nowrap ${STAGE_TONE(status)}`}>
    {status}
  </span>
);

const initials = (name) => (name || '?')
  .split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

/**
 * What has actually HAPPENED to this candidate — the telephonic screens, assessments and
 * interviews already recorded against them, each read from the board that owns it rather
 * than duplicated onto the candidate record. Fetched lazily when the drawer opens, and
 * silent when a domain has nothing: an empty "Assessments" heading on every profile is
 * noise, not information.
 */
const RecruitmentRecord = ({ uk, scope }) => {
  const [record, setRecord] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      getTelephonicScreenings({ ...scope, uk }),
      getAssessments({ ...scope, uk }),
      getCandidateInterviews(uk, scope),
    ]).then(([tel, ass, int]) => {
      if (cancelled) return;
      setRecord({
        screenings: tel.value?.data?.screenings || [],
        assessments: ass.value?.data?.assessments || [],
        interviews: int.value?.data?.interviews || [],
      });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk]);

  if (!record) {
    return <p className="text-[12px] text-[var(--text-muted)]">Loading recruitment record…</p>;
  }
  const { screenings, assessments, interviews } = record;
  if (!screenings.length && !assessments.length && !interviews.length) {
    return (
      <p className="text-[12px] text-[var(--text-muted)]">
        Nothing recorded yet — screening, assessment and interview results appear here as
        they happen.
      </p>
    );
  }

  const Row = ({ title, meta, detail }) => (
    <li className="border-t border-[var(--border)] pt-2 first:border-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12.5px] font-semibold text-[var(--text-main)]">{title}</span>
        <span className="text-[11px] text-[var(--text-muted)] shrink-0">{meta}</span>
      </div>
      {detail && <p className="text-[11.5px] text-[var(--text-muted)]">{detail}</p>}
    </li>
  );

  return (
    <div className="space-y-3">
      {screenings.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
            Telephonic screening
          </p>
          <ul className="space-y-2">
            {screenings.map((s) => (
              <Row key={s.tel_no} title={s.outcome || 'Recorded'}
                meta={s.screened_on ? new Date(s.screened_on).toLocaleDateString() : s.tel_no}
                detail={s.remarks} />
            ))}
          </ul>
        </div>
      )}
      {assessments.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
            Assessments
          </p>
          <ul className="space-y-2">
            {assessments.map((a) => (
              <Row key={a.assessment_no} title={a.title || a.assessment_no}
                meta={a.status || a.outcome || '—'}
                detail={a.score != null ? `Score ${a.score}` : a.remarks} />
            ))}
          </ul>
        </div>
      )}
      {interviews.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
            Interviews
          </p>
          <ul className="space-y-2">
            {interviews.map((i) => (
              <Row key={i.interview_no} title={i.round || i.interview_no}
                meta={i.status || (i.scheduled_at
                  ? new Date(i.scheduled_at).toLocaleDateString() : '—')}
                detail={[i.overall_score != null ? `Score ${i.overall_score}` : null,
                         i.recommendation, i.remarks].filter(Boolean).join(' · ')} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const CandidateCard = ({ candidate: c, onOpen }) => (
  <button type="button" onClick={() => onOpen(c.uk)}
    className="w-full text-left p-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)] hover:shadow-sm transition-all">
    <div className="flex items-start gap-2.5">
      <span className="grid place-items-center w-8 h-8 shrink-0 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[11px] font-bold">
        {initials(c.candidate_name)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="text-[13px] font-bold text-[var(--text-main)] truncate">{c.candidate_name}</p>
          {c.duplicate_flag && (
            <span title="Shares an email or phone with another candidate"
              className="px-1.5 py-0.5 rounded bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[9.5px] font-bold shrink-0">
              DUP
            </span>
          )}
        </div>
        <p className="text-[11px] text-[var(--text-muted)] truncate">
          {c.applied_position || c.request_no || c.uk}
        </p>
      </div>
    </div>
    {c.can_email && (
      <p className="mt-2 text-[11px] text-[var(--text-muted)] truncate">{c.can_email}</p>
    )}
    <div className="mt-2 flex items-center gap-1.5 flex-wrap">
      <StageBadge status={c.application_status} />
      {c.source && (
        <span className="text-[10.5px] text-[var(--text-muted)]">{c.source}</span>
      )}
    </div>
  </button>
);

// ── Drawer presentation helpers ──
// The profile is the record of what the candidate told us on the form, so it shows every
// field the form collects — including the ones they left blank, which is itself worth
// seeing when deciding whether to chase them for it.
const Section = ({ title, children }) => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
      {title}
    </p>
    {children}
  </div>
);

const Facts = ({ rows }) => (
  <div className="grid grid-cols-2 gap-3">
    {rows.map(([label, value]) => (
      <div key={label}>
        <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          {label}
        </p>
        <p className="text-[12.5px] font-semibold text-[var(--text-main)] break-words">
          {value || '—'}
        </p>
      </div>
    ))}
  </div>
);

// Applicants type a bare domain as often as a full URL, so normalise rather than render a
// link that resolves against our own origin.
const LinkRow = ({ icon: Icon, label, href }) => (
  <a href={/^https?:\/\//i.test(href) ? href : `https://${href}`}
    target="_blank" rel="noopener noreferrer"
    className="flex items-center gap-2 text-[13px] text-[var(--accent-indigo)] break-all">
    <Icon size={14} className="shrink-0" />
    <span className="truncate">{label}: {href}</span>
  </a>
);

const FileChip = ({ name, icon: Icon = FileText, onClick }) => (
  <button type="button" onClick={onClick}
    className="flex items-center gap-2 h-9 px-3 rounded-lg border border-[var(--border)] text-[12.5px] font-semibold text-[var(--text-main)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)]">
    <Icon size={14} className="shrink-0" />
    <span className="truncate max-w-[180px]">{name}</span>
    <Download size={13} className="shrink-0" />
  </button>
);

const Consent = ({ ok, at, label }) => (
  <div className="flex items-start gap-2">
    {ok
      ? <Check size={14} className="mt-0.5 shrink-0 text-[var(--accent-green,#16a34a)]" />
      : <Minus size={14} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />}
    <p className={`text-[12px] ${ok ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}`}>
      {label}
      {ok && at && (
        <span className="text-[var(--text-muted)]"> · {new Date(at).toLocaleDateString()}</span>
      )}
      {!ok && <span className="text-[var(--text-muted)]"> — not given</span>}
    </p>
  </div>
);

const Drawer = ({ uk, onClose, onChanged }) => {
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [journey, setJourney] = useState(false);

  const canWrite = can(CAP.CANDIDATE_WRITE);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await getCandidate(uk, scope);
      setC(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this candidate.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk]);

  useEffect(() => { load(); }, [load]);

  const move = async (status) => {
    const previous = c.application_status;
    // Optimistic: the move is almost always legal (the options came from the server), so
    // showing it immediately is right — and reverting on failure is cheap.
    setC((prev) => ({ ...prev, application_status: status }));
    setSaving(true);
    try {
      const { data } = await updateCandidate(uk, { application_status: status }, scope);
      setC(data);
      showSuccess(`Moved to ${status}`);
      onChanged();
    } catch (err) {
      setC((prev) => ({ ...prev, application_status: previous }));
      showError(err?.response?.data?.detail || 'Could not change the stage.');
    } finally {
      setSaving(false);
    }
  };

  // A real download, not a new tab — the signed URL is short-lived and the server names
  // the file via Content-Disposition, matching the pattern used for shared CVs.
  const downloadResume = async () => {
    try {
      const { data } = await getCandidateCv(uk, scope);
      if (!data?.url) return;
      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.name || 'resume.pdf';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not download the resume.');
    }
  };

  const downloadAttachment = async (slot, index, name) => {
    try {
      const { data } = await getCandidateAttachment(uk, slot, index, scope);
      if (!data?.url) return;
      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.name || name || slot;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not download that file.');
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete ${c.candidate_name} (${uk})? This cannot be undone.`)) return;
    try {
      await deleteCandidate(uk, scope);
      showSuccess('Candidate deleted');
      onChanged();
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-screen w-full max-w-lg z-50 bg-[var(--bg-card)] border-l border-[var(--border)] shadow-2xl overflow-y-auto">
        <div className="sticky top-0 bg-[var(--bg-card)] border-b border-[var(--border)] px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[16px] font-bold text-[var(--text-main)] truncate">
              {c?.candidate_name || 'Loading…'}
            </h2>
            <p className="font-mono text-[11.5px] text-[var(--text-muted)]">{uk}</p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {c && (
              <button type="button" onClick={() => setJourney(true)} title="Journey"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                <Route size={16} />
              </button>
            )}
            {c && canWrite && (
              <button type="button" onClick={remove} title="Delete"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]">
                <Trash2 size={16} />
              </button>
            )}
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
              <X size={17} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="p-5"><HrmsError message={error} onRetry={load} /></div>
        ) : !c ? (
          <HrmsLoading label="Loading candidate…" />
        ) : (
          <div className="p-5 space-y-5">
            <div className="flex items-center gap-2 flex-wrap">
              <StageBadge status={c.application_status} />
              {sopLabelFor(c.application_status, CANDIDATE_SOP_LABEL) && (
                <span className="text-[10.5px] text-[var(--text-muted)] italic">
                  SOP: {sopLabelFor(c.application_status, CANDIDATE_SOP_LABEL)}
                </span>
              )}
              {c.requires_assessment && (
                <span className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--input-bg)] text-[var(--text-main)]">
                  Assessment required
                </span>
              )}
              {c.duplicate_flag && (
                <span className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center gap-1">
                  <AlertTriangle size={11} /> Possible duplicate
                </span>
              )}
            </div>

            {canWrite && (
              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Move to stage
                </p>
                {(c.allowed_next || []).length === 0 ? (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    This is a final stage — the pipeline ends here.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {c.allowed_next.map((s) => (
                      <button key={s} type="button" disabled={saving} onClick={() => move(s)}
                        className="px-2.5 py-1 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] disabled:opacity-50">
                        {s}
                      </button>
                    ))}
                  </div>
                )}
                <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
                  Only stages the lifecycle allows from here are offered.
                </p>
              </div>
            )}

            <Section title="Contact">
              <div className="space-y-1.5">
                {c.can_email && (
                  <a href={`mailto:${c.can_email}`}
                    className="flex items-center gap-2 text-[13px] text-[var(--accent-indigo)]">
                    <Mail size={14} /> {c.can_email}
                  </a>
                )}
                {c.can_contact && (
                  <p className="flex items-center gap-2 text-[13px] text-[var(--text-main)]">
                    <Phone size={14} className="text-[var(--text-muted)]" /> {c.can_contact}
                  </p>
                )}
                {c.linkedin && <LinkRow icon={Link2} label="LinkedIn" href={c.linkedin} />}
                {c.portfolio && <LinkRow icon={Globe} label="Portfolio" href={c.portfolio} />}
              </div>
            </Section>

            <Section title="Application">
              <Facts rows={[
                ['Applied position', c.applied_position],
                ['Department', c.department_name],
                ['Applied on', c.applied_at ? new Date(c.applied_at).toLocaleDateString() : null],
                ['Source', c.source],
                ['Requisition', c.request_no],
                ['Job posting', c.posting_code],
                ['Job description', c.jd_no],
                ['Assigned to', c.assigned_recruiter_name],
              ]} />
            </Section>

            <Section title="Professional details">
              <Facts rows={[
                ['Location', c.current_location],
                ['Experience', c.total_experience],
                ['Qualification', c.qualification],
                ['Current company', c.current_company],
                ['Current designation', c.current_designation],
                ['Notice period', c.notice_period],
                ['Current CTC', c.current_ctc],
                ['Expected CTC', c.expected_ctc],
              ]} />
            </Section>

            <Section title="Attachments">
              <div className="flex flex-wrap gap-2">
                {c.resume?.name && (
                  <FileChip name={c.resume.name} onClick={downloadResume} />
                )}
                {c.photo?.name && (
                  <FileChip name={c.photo.name} icon={ImageIcon}
                    onClick={() => downloadAttachment('photo', 0, c.photo.name)} />
                )}
                {(c.certificates || []).map((cert, i) => (
                  <FileChip key={i} name={cert?.name || `Certificate ${i + 1}`}
                    icon={Paperclip}
                    onClick={() => downloadAttachment('certificate', i, cert?.name)} />
                ))}
                {!c.resume?.name && !c.photo?.name && !(c.certificates || []).length && (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    Nothing was attached to this application.
                  </p>
                )}
              </div>
            </Section>

            <div className="p-3 rounded-xl border border-[var(--border)]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                Recruitment record
              </p>
              <RecruitmentRecord uk={uk} scope={scope} />
            </div>

            {/* ── Phase 11-R, Item 5 ── the referral block, shown only when there is one. */}
            {c.is_referral && (
              <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)]">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                  Referral
                </p>
                <p className="mt-1 text-[12.5px] text-[var(--text-main)]">
                  {c.referred_by}
                  {c.referral_source && (
                    <span className="text-[var(--text-muted)]"> · {c.referral_source}</span>
                  )}
                </p>
                {c.referral_relation && (
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    Relationship: {c.referral_relation}
                  </p>
                )}
                {c.referrer_name && (
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    Verified employee: {c.referrer_name}
                    {c.referrer_employee_code && ` (${c.referrer_employee_code})`}
                  </p>
                )}
              </div>
            )}

            {c.cover_note && (
              <Section title="Note from the candidate">
                <p className="text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
                  {c.cover_note}
                </p>
              </Section>
            )}

            {c.remarks && (
              <Section title="Internal remarks">
                <p className="text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
                  {c.remarks}
                </p>
              </Section>
            )}

            {/* What the applicant agreed to, and when. The timestamp is the point: the
                wording is editable, so "they agreed" only means something with a date. */}
            <Section title="Declarations & consent">
              <div className="space-y-1">
                <Consent ok={c.declaration} at={c.declaration_at}
                  label="Confirmed the information given is accurate and complete" />
                <Consent ok={c.eeo_ack} at={c.eeo_ack_at}
                  label="Read the equal-opportunity statement" />
                <Consent ok={c.data_use_ack} at={c.data_use_ack_at}
                  label="Read how their information will be used" />
                <Consent ok={c.consent_to_retain} at={c.consent_to_retain_at}
                  label="Agreed to be kept on file for future roles" />
              </div>
              {c.retention_until && (
                <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                  Scheduled for disposal on {new Date(c.retention_until).toLocaleDateString()}.
                </p>
              )}
            </Section>
          </div>
        )}
      </aside>

      {journey && c && (
        <CandidateJourneyModal uk={uk} name={c.candidate_name} onClose={() => setJourney(false)} />
      )}
    </>
  );
};

const AddModal = ({ onClose, onCreated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState({
    candidate_name: '', can_email: '', can_contact: '', source: 'Direct Application',
    total_experience: '', qualification: '', current_ctc: '', expected_ctc: '',
    current_location: '', current_company: '', current_designation: '', notice_period: '',
    linkedin: '', portfolio: '', cover_note: '',
    // request_no is optional — a candidate added here with none stays unlinked, exactly as
    // before. When set, the server both records it AND re-checks the same sourcing-budget
    // gate a job posting is held to (SOP §11); this picker only makes an already-supported
    // field reachable from the UI, it does not relax anything server-side.
    request_no: '',
    // ── Phase 11-R, Item 5 ── the SAME referral fields the public form captures, validated
    // by the same server-side resolver. A referral HR types onto a walk-in CV must be as
    // reportable as one an applicant declared, or the referral figures count two things.
    is_referral: false, referred_by: '', referral_source: '',
    referrer_employee_code: '', referral_relation: '',
  });
  const [requisitions, setRequisitions] = useState([]);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
  const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

  useEffect(() => {
    getRequisitions({ ...scope, closing_status: 'Open', limit: 200 })
      .then(({ data }) => setRequisitions(data?.requisitions || []))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      // The referral fields are collapsed/blank by default (is_referral: false), but the
      // backend's `referral_source` is `Optional[ReferralSource]` -- it accepts a real enum
      // value or nothing at all, not an empty string. Sending the blank default 422s on
      // EVERY non-referral add, so those fields are only included when actually referred.
      const { is_referral, referred_by, referral_source, referrer_employee_code,
        referral_relation, ...rest } = form;
      const payload = { ...rest, request_no: form.request_no || null, is_referral };
      if (is_referral) {
        Object.assign(payload, {
          referred_by, referral_source, referrer_employee_code, referral_relation,
        });
      }
      await createCandidate(payload, scope);
      showSuccess('Candidate added');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not add the candidate.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Add a candidate</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-3">
          <p className="text-[12px] text-[var(--text-muted)]">
            For walk-ins, referrals and agency CVs. Candidates who apply through a posting
            arrive automatically.
          </p>
          <div>
            <label className={LABEL} htmlFor="c-name">Full name *</label>
            <input id="c-name" required value={form.candidate_name} onChange={set('candidate_name')} className={FIELD} />
          </div>
          <div>
            <label className={LABEL} htmlFor="c-req">Requisition</label>
            <select id="c-req" value={form.request_no} onChange={set('request_no')} className={FIELD}>
              <option value="">Not linked to a requisition yet</option>
              {requisitions.map((r) => (
                <option key={r.request_no} value={r.request_no}>
                  {r.request_no} — {r.designation_name || r.department_name || 'Untitled'}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              Attaches this CV to that requisition's pipeline. Leave unset for a general CV
              on file — this cannot be changed once the candidate is added.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="c-email">Email</label>
              <input id="c-email" type="email" value={form.can_email} onChange={set('can_email')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-phone">Phone</label>
              <input id="c-phone" value={form.can_contact} onChange={set('can_contact')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-source">Source</label>
              <select id="c-source" value={form.source} onChange={set('source')} className={FIELD}>
                {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="c-exp">Experience</label>
              <input id="c-exp" value={form.total_experience} onChange={set('total_experience')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-loc">Location</label>
              <input id="c-loc" value={form.current_location} onChange={set('current_location')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-co">Current company</label>
              <input id="c-co" value={form.current_company} onChange={set('current_company')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-desig">Current designation</label>
              <input id="c-desig" value={form.current_designation} onChange={set('current_designation')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-qual">Highest qualification</label>
              <input id="c-qual" value={form.qualification} onChange={set('qualification')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-cctc">Current CTC</label>
              <input id="c-cctc" value={form.current_ctc} onChange={set('current_ctc')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-ectc">Expected salary</label>
              <input id="c-ectc" value={form.expected_ctc} onChange={set('expected_ctc')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-notice">Notice period</label>
              <input id="c-notice" value={form.notice_period} onChange={set('notice_period')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-li">LinkedIn profile</label>
              <input id="c-li" value={form.linkedin} onChange={set('linkedin')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-pf">Portfolio / website</label>
              <input id="c-pf" value={form.portfolio} onChange={set('portfolio')} className={FIELD} />
            </div>
          </div>
          <div>
            <label className={LABEL} htmlFor="c-note">Note</label>
            <textarea id="c-note" rows={3} value={form.cover_note} onChange={set('cover_note')}
              placeholder="Anything worth recording about this CV" className={FIELD} />
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Provide at least an email address or a phone number.
          </p>

          {/* ── Phase 11-R, Item 5 ── collapsed by default, exactly as on the public form. */}
          <div className="pt-2 border-t border-[var(--border)] space-y-3">
            <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
              <input
                type="checkbox"
                checked={form.is_referral}
                onChange={(e) => setForm((f) => ({ ...f, is_referral: e.target.checked }))}
              />
              This candidate was referred
            </label>

            {form.is_referral && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="c-refby">Referred by *</label>
                  <input id="c-refby" value={form.referred_by}
                    onChange={set('referred_by')} className={FIELD} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="c-refsrc">Referral source *</label>
                  <select id="c-refsrc" value={form.referral_source}
                    onChange={set('referral_source')} className={FIELD}>
                    <option value="">Choose…</option>
                    {['Employee', 'Ex-Employee', 'Consultant / Agency', 'Job Portal',
                      'Social Media', 'Walk-in', 'Client', 'Other'].map((s) => (
                        <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                {form.referral_source === 'Employee' && (
                  <div className="sm:col-span-2">
                    <label className={LABEL} htmlFor="c-refcode">
                      Referring employee code *
                    </label>
                    <input id="c-refcode" value={form.referrer_employee_code}
                      onChange={set('referrer_employee_code')}
                      placeholder="EMP-2026-014" className={FIELD} />
                  </div>
                )}
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="c-refrel">Relationship</label>
                  <input id="c-refrel" value={form.referral_relation}
                    onChange={set('referral_relation')} className={FIELD} />
                </div>
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.candidate_name.trim()}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Adding…' : 'Add candidate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const CandidatePipeline = () => {
  const { can, scope, companyId } = useHrms();

  const [data, setData] = useState({ candidates: [], columns: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [layout, setLayout] = useState('kanban');
  const [openUk, setOpenUk] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [reqs, setReqs] = useState([]);

  const canWrite = can(CAP.CANDIDATE_WRITE);
  // Debounced separately from the dropdowns: typing into Location or Experience should not
  // fire a request per keystroke, but picking from a select should answer immediately.
  const [typed, setTyped] = useState({ location: '', experience: '' });

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    const t = setTimeout(
      () => setFilters((f) => ({ ...f, ...typed })), 350);
    return () => clearTimeout(t);
  }, [typed]);

  useEffect(() => {
    getRequisitions({ ...scope, limit: 200 })
      .then(({ data }) => setReqs(data?.requisitions || []))
      .catch(() => setReqs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getCandidates({
        ...scope, search: debounced || undefined, limit: 500,
        request_no: filters.request_no || undefined,
        source: filters.source || undefined,
        status: filters.status || undefined,
        location: filters.location || undefined,
        experience: filters.experience || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load candidates.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, debounced, filters]);

  useEffect(() => { load(); }, [load]);

  // `applied_position` is denormalised onto candidates going forward, but every CV added
  // before that lands without one. Resolving through the requisitions already loaded for
  // the filter means those rows still show a position, with no data migration and no extra
  // request — and the stored value still wins when it is there.
  const positionFor = (c) => c.applied_position
    || reqs.find((r) => r.request_no === c.request_no)?.designation_name
    || null;

  const setFilter = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));
  const activeFilters = Object.entries(filters).filter(([, v]) => v).length;
  const clearFilters = () => { setFilters(EMPTY_FILTERS); setTyped({ location: '', experience: '' }); };

  const byColumn = (statuses) =>
    data.candidates.filter((c) => statuses.includes(c.application_status));

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Users2}
        title="Candidates"
        subtitle={`${data.total || 0} in the pipeline`}
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
              {[['kanban', Columns3], ['list', ListIcon], ['grid', LayoutGrid]].map(([key, Icon]) => (
                <button key={key} type="button" onClick={() => setLayout(key)} title={key}
                  className={`h-9 w-9 grid place-items-center ${
                    layout === key ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                                   : 'text-[var(--text-muted)]'}`}>
                  <Icon size={15} />
                </button>
              ))}
            </div>
            {canWrite && (
              <button type="button" onClick={() => setShowAdd(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> Add
              </button>
            )}
          </div>
        }
      />

      {/* Where applications are coming from, over whatever filters are currently applied.
          Each chip is also a filter: clicking one narrows the list to that source. */}
      {(data.sources || []).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mr-1">
            By source
          </span>
          {data.sources.map((s) => (
            <button key={s.source} type="button"
              onClick={() => setFilters((f) => ({
                ...f, source: f.source === s.source ? '' : s.source }))}
              className={`px-2.5 py-1 rounded-lg text-[11.5px] font-bold border transition-colors ${
                filters.source === s.source
                  ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                  : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--accent-indigo)]'}`}>
              {s.source} <span className="tabular-nums">{s.count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, ID, email or phone…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>

        <select value={filters.request_no} onChange={setFilter('request_no')}
          className={FILTER_FIELD} aria-label="Filter by job or position">
          <option value="">All positions</option>
          {reqs.map((r) => (
            <option key={r.request_no} value={r.request_no}>
              {r.designation_name} · {r.request_no}
            </option>
          ))}
        </select>

        <select value={filters.source} onChange={setFilter('source')}
          className={FILTER_FIELD} aria-label="Filter by application source">
          <option value="">All sources</option>
          {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select value={filters.status} onChange={setFilter('status')}
          className={FILTER_FIELD} aria-label="Filter by application status">
          <option value="">All statuses</option>
          {STAGE_FILTERS.map(([label, value]) => (
            <option key={label} value={value}>{label}</option>
          ))}
        </select>

        <input value={typed.location}
          onChange={(e) => setTyped((t) => ({ ...t, location: e.target.value }))}
          placeholder="Location" aria-label="Filter by location"
          className={`${FILTER_FIELD} w-[120px]`} />

        <input value={typed.experience}
          onChange={(e) => setTyped((t) => ({ ...t, experience: e.target.value }))}
          placeholder="Experience" aria-label="Filter by experience"
          className={`${FILTER_FIELD} w-[120px]`} />

        <input type="date" value={filters.date_from} onChange={setFilter('date_from')}
          aria-label="Applied from" title="Applied from" className={FILTER_FIELD} />
        <input type="date" value={filters.date_to} onChange={setFilter('date_to')}
          aria-label="Applied to" title="Applied to" className={FILTER_FIELD} />

        {activeFilters > 0 && (
          <button type="button" onClick={clearFilters}
            className="h-9 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
            Clear ({activeFilters})
          </button>
        )}
      </div>

      {loading ? (
        <HrmsLoading label="Loading candidates…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.candidates.length === 0 ? (
        <HrmsEmpty icon={Users2} title="No candidates"
          hint={search ? 'Try a different search.'
                       : 'Applications from your live postings will appear here.'} />
      ) : layout === 'kanban' ? (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {data.columns.map((col) => {
            const rows = byColumn(col.statuses);
            return (
              <div key={col.key} className="w-[280px] shrink-0">
                <div className="flex items-center justify-between gap-2 px-3 py-2 mb-2 rounded-lg bg-[var(--input-bg)]">
                  <span className="text-[11.5px] font-bold uppercase tracking-wider text-[var(--text-main)] truncate">
                    {col.label}
                  </span>
                  <span className="px-2 py-0.5 rounded-md bg-[var(--bg-card)] text-[11px] font-bold text-[var(--text-main)] shrink-0">
                    {col.count}
                  </span>
                </div>
                <div className="space-y-2">
                  {rows.length === 0 ? (
                    <p className="p-3 rounded-xl border border-dashed border-[var(--border)] text-[11.5px] text-[var(--text-muted)] text-center">
                      No candidates
                    </p>
                  ) : rows.map((c) => (
                    <CandidateCard key={c.uk} candidate={c} onOpen={setOpenUk} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : layout === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {data.candidates.map((c) => (
            <CandidateCard key={c.uk} candidate={c} onOpen={setOpenUk} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[900px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                {['Candidate Name', 'Position', 'Applied Date', 'Source', 'Experience',
                  'Location', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((c) => (
                <tr key={c.uk} onClick={() => setOpenUk(c.uk)}
                  className="border-t border-[var(--border)] cursor-pointer hover:bg-[var(--input-bg)]">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <span className="grid place-items-center w-8 h-8 shrink-0 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[11px] font-bold">
                        {initials(c.candidate_name)}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-[var(--text-main)]">{c.candidate_name}</span>
                          {c.duplicate_flag && (
                            <span className="px-1 rounded bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[9.5px] font-bold">DUP</span>
                          )}
                        </div>
                        <span className="block text-[11px] text-[var(--text-muted)] truncate">
                          {c.can_email || c.uk}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-[var(--text-main)]">{positionFor(c) || '—'}</span>
                    <span className="block text-[11px] text-[var(--text-muted)]">
                      {c.request_no || '—'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)] whitespace-nowrap">
                    {c.applied_at ? new Date(c.applied_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{c.source || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{c.total_experience || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{c.current_location || '—'}</td>
                  <td className="px-4 py-2.5"><StageBadge status={c.application_status} /></td>
                  <td className="px-4 py-2.5">
                    <button type="button"
                      onClick={(e) => { e.stopPropagation(); setOpenUk(c.uk); }}
                      className="h-7 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] hover:text-[var(--accent-indigo)] whitespace-nowrap">
                      View profile
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openUk && (
        <Drawer uk={openUk} onClose={() => setOpenUk(null)} onChanged={load} />
      )}
      {showAdd && (
        <AddModal onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }} />
      )}
    </div>
  );
};

export default CandidatePipeline;
