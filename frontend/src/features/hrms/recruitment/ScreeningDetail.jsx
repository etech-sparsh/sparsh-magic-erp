import React, { useCallback, useEffect, useState } from 'react';
import {
  X, FileText, Download, Save, ClipboardCheck, Phone, ListChecks, CalendarDays, Users2,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getCandidateScreening, recordCvScreening, getCandidateCv,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ HR Screening — one candidate, the whole screening record.
 *
 * Internal Recruitment SOP §1-§3. Four blocks, in the order the SOP performs them:
 *
 *   1. Who the candidate is, and their CV.
 *   2. What the APPROVED role asks for — the JD's wording and the approved Position
 *      Scorecard's criteria. The SOP screens against the scorecard, so the scorecard has to
 *      be on the screen; asking HR to judge "does this CV meet the bar" with the bar on
 *      another page is how screening drifts from what was approved.
 *   3. HR screening: the CV verdict (recorded here), then the telephonic and assessment
 *      records read from the boards that own them.
 *   4. Interview and shortlisting: panel, per-competency scores, committee decision.
 *
 * Only the CV screening is WRITTEN here. Telephonic, assessment, interview and shortlisting
 * each have their own board with their own gates and signatures, and duplicating those
 * forms here would be a second way to write the same record — with a second set of rules to
 * keep in step. This page reads them.
 */

const CV_RESULTS = ['Meets Requirements', 'Partially Meets', 'Does Not Meet'];
const SCREENING_STATUSES = ['In Progress', 'Cleared', 'On Hold', 'Rejected'];

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const AREA = 'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const SECTION = 'text-[10.5px] font-bold uppercase tracking-widest text-[var(--accent-indigo)] mb-3 flex items-center gap-1.5';

const day = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
};

const Fact = ({ label, value, wide }) => (
  <div className={wide ? 'col-span-2' : undefined}>
    <span className="block text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </span>
    <span className="text-[12.5px] font-semibold text-[var(--text-main)] break-words whitespace-pre-wrap">
      {value || '—'}
    </span>
  </div>
);

const Card = ({ icon: Icon, title, children, note }) => (
  <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
    <h3 className={SECTION}>{Icon && <Icon size={13} />}{title}</h3>
    {note && <p className="text-[11.5px] text-[var(--text-muted)] mb-2.5">{note}</p>}
    {children}
  </div>
);

const ScreeningDetail = ({ uk, onClose, onChanged }) => {
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    result: '', remarks: '', hr_remarks: '', screening_status: '',
  });

  const canScreen = can(CAP.CANDIDATE_SCREEN);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data: res } = await getCandidateScreening(uk, scope);
      setData(res);
      const c = res.candidate || {};
      setForm({
        result: c.cv_screening_result || '',
        remarks: c.cv_screening_remarks || '',
        hr_remarks: c.hr_remarks || '',
        screening_status: c.screening_status || '',
      });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the screening record.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk]);

  useEffect(() => { load(); }, [load]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    if (!form.result) return showError('Choose a CV screening result.');
    setSaving(true);
    try {
      await recordCvScreening(uk, {
        result: form.result,
        remarks: form.remarks || null,
        hr_remarks: form.hr_remarks || null,
        screening_status: form.screening_status || null,
      }, scope);
      showSuccess(`CV screening recorded for ${uk}`);
      await load();
      onChanged?.();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the CV screening.');
    } finally {
      setSaving(false);
    }
  };

  const openCv = async () => {
    try {
      const { data: res } = await getCandidateCv(uk, scope);
      window.open(res.url, '_blank', 'noopener');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open the CV.');
    }
  };

  const c = data?.candidate || {};
  const req = data?.requisition;
  const r = data?.requirements || {};
  const scorecard = r.scorecard;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-3xl h-full bg-[var(--bg-main,var(--bg-card))] overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 px-5 py-4
                        border-b border-[var(--border)] bg-[var(--bg-card)]">
          <div className="min-w-0">
            <h2 className="text-[16px] font-bold text-[var(--text-main)] truncate">
              {c.candidate_name || 'Screening'}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              HR Screening · {uk}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={18} />
          </button>
        </div>

        {error && <div className="p-5"><HrmsError message={error} onRetry={load} /></div>}
        {!data && !error && <div className="p-5"><HrmsLoading label="Loading screening record…" /></div>}

        {data && (
          <div className="p-5 space-y-4">
            {/* ── 1. Candidate information ── */}
            <Card icon={FileText} title="1. Candidate information">
              <div className="grid grid-cols-2 gap-3">
                <Fact label="Candidate name" value={c.candidate_name} />
                <Fact label="Applied position"
                  value={c.applied_position || req?.designation_name} />
                <Fact label="Email" value={c.can_email} />
                <Fact label="Mobile" value={c.can_contact} />
                <Fact label="Requisition ID" value={c.request_no} />
                <Fact label="Job posting" value={c.posting_code} />
                <Fact label="Application source" value={c.source} />
                <Fact label="Application date" value={day(c.applied_at)} />
                <Fact label="Experience" value={c.total_experience} />
                <Fact label="Location" value={c.current_location} />
              </div>
              <div className="mt-3">
                {c.resume?.name ? (
                  <button type="button" onClick={openCv}
                    className="h-8 px-3 rounded-lg border border-[var(--border)] text-[12px]
                              font-bold text-[var(--text-main)] flex items-center gap-1.5">
                    <Download size={13} /> Open CV ({c.resume.name})
                  </button>
                ) : (
                  <p className="text-[12px] text-[var(--text-muted)]">No CV on file.</p>
                )}
              </div>
            </Card>

            {/* ── 2. What the approved role requires ── */}
            <Card icon={ClipboardCheck} title="2. Approved position requirements"
              note="From the approved Job Description and Position Scorecard — the bar this CV is screened against.">
              <div className="grid grid-cols-2 gap-3">
                <Fact label="Skills" value={r.skills} wide />
                <Fact label="Experience" value={r.experience} />
                <Fact label="Qualifications" value={r.qualifications} />
                <Fact label="Key competencies" value={r.key_competencies} wide />
                <Fact label="Culture-fit expectations" value={r.culture_fit} wide />
                <Fact label="Other requirements" value={r.additional_requirements} wide />
              </div>

              {scorecard ? (
                <div className="mt-3 pt-3 border-t border-[var(--border)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                    Position Scorecard {scorecard.scr_no} · {scorecard.status}
                    {scorecard.managerial ? ' · managerial' : ''}
                  </p>
                  <ul className="space-y-2">
                    {(scorecard.criteria || []).map((crit, i) => (
                      <li key={crit.label || i} className="text-[12.5px]">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="font-semibold text-[var(--text-main)]">
                            {i + 1}. {crit.label}
                          </span>
                          <span className="text-[var(--text-muted)] shrink-0">
                            weight {crit.weight}
                          </span>
                        </div>
                        {crit.expected_level && (
                          <p className="text-[11.5px] text-[var(--text-main)]">
                            Expected: {crit.expected_level}
                          </p>
                        )}
                        {crit.evaluation_criteria && (
                          <p className="text-[11.5px] text-[var(--text-muted)]">
                            {crit.evaluation_criteria}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="mt-3 pt-3 border-t border-[var(--border)] text-[12px] text-[var(--accent-orange)]">
                  No approved Position Scorecard for this requisition yet — the SOP screens
                  against it, so agree it first.
                </p>
              )}
            </Card>

            {/* ── 3. HR screening ── */}
            <Card icon={ClipboardCheck} title="3. HR screening">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="cv-result">CV screening result *</label>
                  <select id="cv-result" value={form.result} onChange={set('result')}
                    className={FIELD} disabled={!canScreen}>
                    <option value="">Not screened yet</option>
                    {CV_RESULTS.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="scr-status">Overall screening status</label>
                  <select id="scr-status" value={form.screening_status}
                    onChange={set('screening_status')} className={FIELD} disabled={!canScreen}>
                    <option value="">Not set</option>
                    {SCREENING_STATUSES.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
              </div>
              <div className="mt-3">
                <label className={LABEL} htmlFor="cv-remarks">CV screening remarks</label>
                <textarea id="cv-remarks" rows={2} value={form.remarks} onChange={set('remarks')}
                  className={AREA} disabled={!canScreen}
                  placeholder="How the CV measures against the approved requirements" />
              </div>
              <div className="mt-3">
                <label className={LABEL} htmlFor="hr-remarks">HR remarks</label>
                <textarea id="hr-remarks" rows={2} value={form.hr_remarks}
                  onChange={set('hr_remarks')} className={AREA} disabled={!canScreen}
                  placeholder="HR's overall note across the screening" />
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  {c.screened_by_name
                    ? `Screened by ${c.screened_by_name} on ${day(c.screening_date)}`
                    : 'Not screened yet.'}
                </p>
                {canScreen && (
                  <button type="button" onClick={save} disabled={saving}
                    className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white
                              text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                    <Save size={14} /> {saving ? 'Saving…' : 'Record CV screening'}
                  </button>
                )}
              </div>
            </Card>

            {/* Telephonic — read from the board that owns it. */}
            <Card icon={Phone} title="Telephonic screening"
              note="Recorded on the Phone Screen board; its criteria and weights live there.">
              {data.telephonic.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)]">No telephonic screening yet.</p>
              ) : (
                <ul className="space-y-2">
                  {data.telephonic.map((t) => (
                    <li key={t.tel_no} className="text-[12.5px] border-t border-[var(--border)]
                                                   pt-2 first:border-0 first:pt-0">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="font-semibold text-[var(--text-main)]">{t.outcome}</span>
                        <span className="text-[var(--text-muted)] shrink-0">
                          {t.score != null ? `${t.score} / 5` : '—'}
                          {t.band ? ` · ${t.band}` : ''}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {t.screened_by_name || '—'} · {day(t.screened_on)}
                      </p>
                      {t.comments && (
                        <p className="text-[11.5px] text-[var(--text-muted)]">{t.comments}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* Assessment — read from the board that owns it. */}
            <Card icon={ListChecks} title="Skill / competency assessment"
              note="Sent and reviewed on the Assessments board; HR and the hiring manager each decide.">
              {data.assessments.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)]">
                  {c.requires_assessment
                    ? 'Assessment is required for this role but none has been sent yet.'
                    : 'No assessment recorded. This role does not require one.'}
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.assessments.map((a) => (
                    <li key={a.assessment_no} className="text-[12.5px] border-t border-[var(--border)]
                                                          pt-2 first:border-0 first:pt-0">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="font-semibold text-[var(--text-main)]">
                          {a.title || a.assessment_no}
                        </span>
                        <span className="text-[var(--text-muted)] shrink-0">
                          {a.outcome || a.status}
                          {a.score != null ? ` · ${a.score}/${a.max_score}` : ''}
                        </span>
                      </div>
                      {(a.hr_decision || a.manager_decision) && (
                        <p className="text-[11px] text-[var(--text-muted)]">
                          HR: {a.hr_decision || 'pending'} · Manager: {a.manager_decision || 'pending'}
                        </p>
                      )}
                      {(a.hr_remarks || a.manager_remarks) && (
                        <p className="text-[11.5px] text-[var(--text-muted)]">
                          {[a.hr_remarks, a.manager_remarks].filter(Boolean).join(' · ')}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* ── 4. Interview & shortlisting ── */}
            <Card icon={CalendarDays} title="4. Panel interview">
              {data.interviews.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)]">No interview scheduled yet.</p>
              ) : (
                <ul className="space-y-3">
                  {data.interviews.map((i) => (
                    <li key={i.interview_no} className="text-[12.5px] border-t border-[var(--border)]
                                                         pt-3 first:border-0 first:pt-0">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="font-semibold text-[var(--text-main)]">{i.round}</span>
                        <span className="text-[var(--text-muted)] shrink-0">
                          {i.outcome || i.status}
                          {i.average_score != null ? ` · ${i.average_score} / 5` : ''}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {day(i.scheduled_at)}
                        {i.eval_by_name ? ` · scored by ${i.eval_by_name}` : ''}
                      </p>
                      {(i.panel || []).length > 0 && (
                        <p className="text-[11.5px] text-[var(--text-muted)]">
                          Panel: {i.panel.map((p) => `${p.name}${p.role ? ` (${p.role})` : ''}`
                            + (p.recused ? ' — recused' : '')).join(', ')}
                        </p>
                      )}
                      {[['Technical', i.score_technical], ['Communication', i.score_communication],
                        ['Problem solving', i.score_problem_solving], ['Behaviour', i.score_behavior],
                        ['Confidence', i.score_confidence], ['Team fit', i.score_team_fit]]
                        .some(([, v]) => v != null) && (
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                          {[['Technical', i.score_technical], ['Communication', i.score_communication],
                            ['Problem solving', i.score_problem_solving], ['Behaviour', i.score_behavior],
                            ['Confidence', i.score_confidence], ['Team fit', i.score_team_fit]]
                            .filter(([, v]) => v != null).map(([label, v]) => (
                              <span key={label} className="text-[11px] text-[var(--text-muted)]">
                                {label} <b className="text-[var(--text-main)]">{v}</b>
                              </span>
                            ))}
                        </div>
                      )}
                      {i.eval_remarks && (
                        <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
                          {i.eval_remarks}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card icon={Users2} title="5. Shortlisting"
              note="HR and the HOD sit as the committee. Score 4.0+ reads Strong, below 3.0 reads Reject — the band is advice, the committee decides.">
              {data.shortlist_reviews.length === 0 ? (
                <p className="text-[12px] text-[var(--text-muted)]">
                  No shortlisting sitting has named this candidate yet.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.shortlist_reviews.map((s) => (
                    <li key={s.slr_no} className="text-[12.5px] border-t border-[var(--border)]
                                                   pt-2 first:border-0 first:pt-0">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="font-semibold text-[var(--text-main)]">{s.slr_no}</span>
                        <span className="text-[var(--text-muted)] shrink-0">{s.outcome}</span>
                      </div>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {(s.committee_members || [])
                          .map((m) => `${m.name}${m.role ? ` (${m.role})` : ''}`
                            + (m.decision ? ` — ${m.decision}` : '')).join(', ') || '—'}
                      </p>
                      {(s.decision_guide || []).filter((g) => g.uk === uk).map((g) => (
                        <p key={g.uk} className="text-[11.5px] text-[var(--text-main)]">
                          Overall score {g.weighted_score ?? '—'}
                          {g.decision_guide_band ? ` · ${g.decision_guide_band}` : ''}
                        </p>
                      ))}
                      {s.notes && (
                        <p className="text-[11.5px] text-[var(--text-muted)]">{s.notes}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {c.scorecard_score != null && (
                <p className="mt-2 pt-2 border-t border-[var(--border)] text-[12px] text-[var(--text-main)]">
                  Scorecard evaluation: <b>{c.scorecard_score} / 5</b>
                  {c.scorecard_band ? ` · ${c.scorecard_band}` : ''}
                </p>
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default ScreeningDetail;
