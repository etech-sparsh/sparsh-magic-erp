import React, { useCallback, useEffect, useState } from 'react';
import { Users, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientCandidates, createClientCandidate,
  updateClientCandidate, actOnClientCandidate,
  getClientAssessments, createClientAssessment, updateClientAssessment,
  actOnClientAssessment,
  getClientInterviews, createClientInterview, updateClientInterview,
  actOnClientInterview,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, money } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import {
  useClientList, useClientScope, useSourceableRequisitions,
} from './clientKit';
import {
  AssessmentModal, InterviewModal, OutcomeModal, ScoreModal,
} from './clientStageModals.jsx';

/**
 * HRMS ▸ Client Hiring ▸ candidates, CV share, assessment and interview.
 *
 * PRO-fit SOP sections 10-14. Four stages live on one screen because they are one
 * person's journey, and splitting them across four pages would mean four places to look
 * for the answer to "where has this candidate got to".
 *
 * -- The two gates ---------------------------------------------------------------
 * The client owns two decisions here and Sparsh owns none of them:
 *   * the CV verdict — nobody is assessed until the client has approved the CV;
 *   * the selection after the interview.
 * Sparsh sources, screens, shortlists, shares, administers and scores. The screen shows
 * both sides but offers each hand only its own moves, because the API only accepts each
 * hand's own moves.
 *
 * -- What a client can see -------------------------------------------------------
 * A candidate becomes visible to the client when they are SHARED, not before. Sourcing
 * and screening are working process: a client reading a half-formed opinion is being
 * shown a judgement nobody has made yet. That rule lives in the API, which simply does
 * not return the earlier rows; this screen renders whatever it is given.
 */

const CANDIDATE_MOVES = [
  { id: 'screen', label: 'Record screening', tone: 'primary',
    cap: CAP.CLIENT_CANDIDATE_WRITE, from: ['Sourced'] },
  { id: 'telephonic-pass', label: 'Telephonic passed', tone: 'primary',
    cap: CAP.CLIENT_CANDIDATE_WRITE, from: ['Screened'] },
  { id: 'telephonic-fail', label: 'Telephonic failed', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_CANDIDATE_WRITE, from: ['Screened'],
    reasonHint: 'Not a rejection of the person — they stay revivable for another role.' },
  // A telephonic failure parks somebody rather than rejecting them, so there has to be a
  // way back. Straight to Screened: the screening scores still stand, it is the telephonic
  // that is being given a second run.
  { id: 'revive', label: 'Revive', tone: 'primary', remarks: true,
    cap: CAP.CLIENT_CANDIDATE_WRITE, from: ['Telephonic Failed'],
    reasonHint: 'Why this candidate is worth another telephonic after failing the first.' },
  { id: 'shortlist', label: 'Shortlist', tone: 'primary',
    cap: CAP.CLIENT_CANDIDATE_WRITE, from: ['Telephonic Passed'] },
  { id: 'share', label: 'Share with client', tone: 'primary',
    cap: CAP.CLIENT_CANDIDATE_SHARE, from: ['Shortlisted'] },
  { id: 'client-approve', label: 'Approve CV', tone: 'primary',
    cap: CAP.CLIENT_CANDIDATE_DECIDE, from: ['Shared with Client'] },
  { id: 'client-reject', label: 'Reject CV', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_CANDIDATE_DECIDE, from: ['Shared with Client'],
    reasonHint: 'Sparsh sources against this, so say what missed rather than just no.' },
];

const ASSESSMENT_MOVES = [
  { id: 'record-submission', label: 'Mark submitted', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_MANAGE, from: ['Sent'] },
  { id: 'score', label: 'Record score', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_SCORE, from: ['Submitted'] },
  { id: 'share', label: 'Share result', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_SHARE, from: ['Scored'] },
  { id: 'client-review', label: 'Mark reviewed', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_REVIEW, from: ['Shared with Client'] },
];

const INTERVIEW_MOVES = [
  { id: 'record-outcome', label: 'Record outcome', tone: 'primary',
    cap: CAP.CLIENT_INTERVIEW_MANAGE, from: ['Scheduled'] },
  { id: 'share', label: 'Share recording', tone: 'primary',
    cap: CAP.CLIENT_INTERVIEW_SHARE, from: ['Conducted'] },
  { id: 'client-select', label: 'Select candidate', tone: 'primary',
    cap: CAP.CLIENT_INTERVIEW_DECIDE, from: ['Shared with Client'] },
  { id: 'client-reject', label: 'Reject', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_INTERVIEW_DECIDE, from: ['Shared with Client'],
    reasonHint: 'Recorded against the interview so the next shortlist is better aimed.' },
];

/** Where the client's CV verdict has been given, so assessment may begin. */
const ASSESSABLE = new Set([
  'Client Approved', 'Assessment', 'Assessment Reviewed', 'Interview',
]);

/**
 * The pipeline, as a filter strip.
 *
 * "Who is telephonic passed" was a question you answered by scanning a Status column.
 * The internal track's boards all carry one of these; the client track had none, which
 * made every stage question a hunt through one undifferentiated list.
 */
const FILTERS = [
  ['all', 'All'],
  ['Sourced', 'Applied / sourced'],
  ['Screened', 'Screened'],
  ['Telephonic Passed', 'Telephonic passed'],
  ['Telephonic Failed', 'Telephonic failed'],
  ['Shortlisted', 'Shortlisted'],
  ['Shared with Client', 'With the client'],
  ['Client Approved', 'CV approved'],
  ['Client Rejected', 'CV rejected'],
];

const ClientCandidates = ({ embedded, onChanged }) => {
  // Every mutation already reloads this screen's own list. The workspace's stage rail
  // counts the same records independently, so it has to be told as well -- otherwise
  // acting inside a panel leaves the rail above it showing figures from before the
  // action, which reads as the action not having worked.
  const refresh = () => { reload(); onChanged?.(); };
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientCandidates, 'client_candidates');

  const [filter, setFilter] = useState('all');
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const [opened, setOpened] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.CLIENT_CANDIDATE_WRITE);

  const act = async (ccnNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientCandidate(ccnNo, { action, ...payload }, scope);
      showSuccess(`${ccnNo} updated`);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'who', label: 'Candidate',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.candidate_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.ccn_no} · {r.cr_no}
          </span>
        </>
      ) },
    { key: 'employer', label: 'Current',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{r.current_employer || '—'}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.notice_period ? `${r.notice_period} notice` : '—'}
          </span>
        </>
      ) },
    { key: 'ctc', label: 'CTC',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)]">
          {r.current_ctc != null ? money(r.current_ctc) : '—'}
          {r.expected_ctc != null && (
            <span className="block text-[11px]">exp {money(r.expected_ctc)}</span>
          )}
        </span>
      ) },
    { key: 'scores', label: 'Scores',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)] text-[11.5px]">
          {r.tfs_score != null ? `TFS ${r.tfs_score}` : '—'}
          {r.pi_score != null && <span className="block">PI {r.pi_score}</span>}
        </span>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canWrite && ['Sourced', 'Screened'].includes(r.status) && (
            <Btn onClick={() => setEditing(r)}>Edit</Btn>
          )}
          <Btn onClick={() => setOpened(r)}>Open</Btn>
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.ccn_no} · {r.cr_no}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Current', value: r.current_employer || '—' },
        { label: 'Notice', value: r.notice_period || '—' },
        { label: 'Expected', value: r.expected_ctc != null ? money(r.expected_ctc) : '—' },
        { label: 'TFS', value: r.tfs_score != null ? String(r.tfs_score) : '—' },
      ]} />
      <div className="flex items-center gap-1.5">
        {canWrite && ['Sourced', 'Screened'].includes(r.status) && (
          <Btn onClick={() => setEditing(r)}>Edit</Btn>
        )}
        <Btn onClick={() => setOpened(r)}>Open</Btn>
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader
          title="Candidates"
          subtitle="Sourcing, screening, the CV share, the assessment and the interview (SOP sections 10–14)"
          actions={canWrite && (
          <Btn tone="primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> Add a candidate
          </Btn>
        )}
        />
      ) : (
        <>
          <HrmsPageHeader
            icon={Users}
            title="Candidates"
            subtitle="Sourcing, screening, the CV share, the assessment and the interview (SOP sections 10–14)"
            actions={canWrite && (
          <Btn tone="primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> Add a candidate
          </Btn>
        )}
          />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        {isInternal ? (
          <>
            Two decisions belong to the client and to nobody at Sparsh: the CV verdict,
            which is what opens the assessment, and the selection after the interview.
            Everything between them — sourcing, screening, administering and scoring —
            is Sparsh&apos;s.
          </>
        ) : (
          <>
            Two decisions are yours and nobody&apos;s at Sparsh: the CV verdict, which is
            what opens the assessment, and the selection after the interview. Everything
            between them — sourcing, screening, administering and scoring — Sparsh does.
            You see a candidate once they have been shared with you.
          </>
        )}
      </WhoseMove>

      <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl border
        border-[var(--border)] bg-[var(--input-bg)] w-fit">
        {FILTERS.map(([key, label]) => {
          const n = key === 'all' ? rows.length
            : rows.filter((r) => r.status === key).length;
          // A stage nobody is at is noise on a strip meant for finding people, so an
          // empty one is hidden -- except "All", which has to stay reachable.
          if (!n && key !== 'all' && filter !== key) return null;
          return (
            <button key={key} type="button" onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-bold transition-colors
                ${filter === key
                  ? 'bg-[var(--accent-indigo)] text-white'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
              {label}
              <span className="ml-1.5 tabular-nums opacity-70">{n}</span>
            </button>
          );
        })}
      </div>

      {loading && <HrmsLoading label="Loading candidates…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={filter === 'all' ? rows : rows.filter((r) => r.status === filter)}
          columns={columns} renderCard={renderCard}
          keyOf={(r) => r.ccn_no}
          empty={<HrmsEmpty
            icon={Users}
            title="No candidates yet"
            hint={canWrite
              ? 'Add one against a requisition whose scorecard the client has approved.'
              : 'Nothing has been shared with you yet.'}
          />}
        />
      )}

      {adding && (
        <CandidateModal
          busy={busy}
          onClose={() => setAdding(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await createClientCandidate(payload, scope);
              showSuccess(`${data.ccn_no} added`);
              setAdding(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be added.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editing && (
        <CandidateModal
          row={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientCandidate(editing.ccn_no, payload, scope);
              showSuccess(`${editing.ccn_no} saved`);
              setEditing(null);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be saved.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {opened && (
        <CandidateJourney
          row={opened}
          busy={busy}
          onClose={() => setOpened(null)}
          onChanged={refresh}
          onAct={async (action, payload) => {
            await act(opened.ccn_no, action, payload);
            setOpened(null);
          }}
        />
      )}
    </div>
  );
};

/** Add a candidate, or correct the screening figures on one still in Sparsh's hands. */
const CandidateModal = ({ row, busy, onClose, onSubmit }) => {
  const scope = useClientScope();
  const editing = !!row;
  const [form, setForm] = useState(() => ({
    cr_no: row?.cr_no || '',
    candidate_name: row?.candidate_name || '',
    email: row?.email || '',
    phone: row?.phone || '',
    source: row?.source || '',
    cv_reference: row?.cv_reference || '',
    current_employer: row?.current_employer || '',
    notice_period: row?.notice_period || '',
    current_ctc: row?.current_ctc ?? '',
    expected_ctc: row?.expected_ctc ?? '',
    tfs_score: row?.tfs_score ?? '',
    competency_score: row?.competency_score ?? '',
    pi_score: row?.pi_score ?? '',
    screening_notes: row?.screening_notes || '',
  }));
  // Sourcing is gated on an APPROVED SCORECARD, not merely an approved requisition, so
  // the picker lists only what the server will actually accept.
  const { requisitions: reqs } = useSourceableRequisitions(scope, { enabled: !editing });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const num = (v) => (v === '' || v == null ? undefined : Number(v));

  const submit = () => {
    const base = {
      candidate_name: form.candidate_name.trim(),
      email: form.email || undefined,
      phone: form.phone || undefined,
      source: form.source || undefined,
      cv_reference: form.cv_reference || undefined,
      current_employer: form.current_employer || undefined,
      notice_period: form.notice_period || undefined,
      current_ctc: num(form.current_ctc),
      expected_ctc: num(form.expected_ctc),
    };
    onSubmit(editing
      ? { ...base,
          tfs_score: num(form.tfs_score),
          competency_score: num(form.competency_score),
          pi_score: num(form.pi_score),
          screening_notes: form.screening_notes || undefined }
      : { ...base, cr_no: form.cr_no });
  };

  const ready = form.candidate_name.trim() && (editing || form.cr_no);

  return (
    <Modal
      title={editing ? `Edit ${row.ccn_no}` : 'Add a candidate'}
      subtitle={editing
        ? 'Screening figures are measured against the approved scorecard.'
        : 'Sourced against a requisition whose scorecard the client has approved.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready} onClick={submit}>
            {busy ? 'Saving…' : (editing ? 'Save' : 'Add')}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        {editing ? (
          <Detail label="Requisition">{row.cr_no}</Detail>
        ) : (
          <div>
            <label className={LABEL} htmlFor="cand-cr">Requisition</label>
            <select id="cand-cr" className={FIELD} value={form.cr_no} onChange={set('cr_no')}>
              <option value="">Select a requisition with an approved scorecard…</option>
              {reqs.map((r) => (
                <option key={r.cr_no} value={r.cr_no}>
                  {r.cr_no} — {r.role_title || 'Untitled role'}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field id="cand-name" label="Name" value={form.candidate_name}
            onChange={set('candidate_name')} />
          <Field id="cand-source" label="Source" value={form.source}
            onChange={set('source')} placeholder="Referral, portal, network…" />
          <Field id="cand-email" label="Email" value={form.email} onChange={set('email')} />
          <Field id="cand-phone" label="Phone" value={form.phone} onChange={set('phone')} />
          <Field id="cand-emp" label="Current employer" value={form.current_employer}
            onChange={set('current_employer')} />
          <Field id="cand-notice" label="Notice period" value={form.notice_period}
            onChange={set('notice_period')} placeholder="30 days" />
          <Field id="cand-cctc" label="Current CTC" type="number" value={form.current_ctc}
            onChange={set('current_ctc')} />
          <Field id="cand-ectc" label="Expected CTC" type="number" value={form.expected_ctc}
            onChange={set('expected_ctc')} />
          <Field id="cand-cv" label="CV reference" value={form.cv_reference}
            onChange={set('cv_reference')} placeholder="Link or file reference" />
        </div>

        {editing && (
          <>
            <p className="pt-1 text-[10px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Screening, against the approved scorecard
            </p>
            <div className="grid grid-cols-3 gap-3">
              <Field id="cand-tfs" label="Talent Fit" type="number" value={form.tfs_score}
                onChange={set('tfs_score')} />
              <Field id="cand-comp" label="Competency" type="number"
                value={form.competency_score} onChange={set('competency_score')} />
              <Field id="cand-pi" label="PI score" type="number" value={form.pi_score}
                onChange={set('pi_score')} />
            </div>
            <div>
              <label className={LABEL} htmlFor="cand-notes">Screening notes</label>
              <textarea id="cand-notes" className={TEXTAREA} rows={3}
                value={form.screening_notes} onChange={set('screening_notes')} />
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};

const Field = ({ id, label, ...rest }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    <input id={id} className={FIELD} {...rest} />
  </div>
);

/**
 * One candidate's whole journey: the record, the assessment, the interview.
 *
 * The assessment and interview panels only appear once the client's CV verdict has opened
 * them. Showing an empty assessment panel to somebody who cannot yet create one would
 * read as a missing feature rather than as a gate.
 */
const CandidateJourney = ({ row, busy, onClose, onAct, onChanged }) => {
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const [assessments, setAssessments] = useState([]);
  const [interviews, setInterviews] = useState([]);
  const [stageBusy, setStageBusy] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [scoring, setScoring] = useState(null);
  const [scheduling, setScheduling] = useState(false);
  const [outcoming, setOutcoming] = useState(null);

  const open = ASSESSABLE.has(row.status) || row.status === 'Selected';

  const loadStages = useCallback(async () => {
    if (!open) return;
    try {
      const [a, i] = await Promise.all([
        getClientAssessments({ ...scope, ccn_no: row.ccn_no, limit: 50 }),
        getClientInterviews({ ...scope, ccn_no: row.ccn_no, limit: 50 }),
      ]);
      setAssessments(a.data?.client_assessments || []);
      setInterviews(i.data?.client_interviews || []);
    } catch {
      setAssessments([]);
      setInterviews([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, row.ccn_no, JSON.stringify(scope)]);

  useEffect(() => { loadStages(); }, [loadStages]);

  const run = async (fn, okMessage) => {
    setStageBusy(true);
    try {
      await fn();
      showSuccess(okMessage);
      loadStages();
      // An assessment or interview move also advances the CANDIDATE (the services call
      // _move_candidate), so the list behind this modal and the rail above it are both
      // out of date until they are told.
      onChanged?.();
      return true;
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
      return false;
    } finally {
      setStageBusy(false);
    }
  };

  return (
    <Modal
      title={row.candidate_name}
      subtitle={`${row.ccn_no} · ${row.cr_no}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Moves row={row} moves={CANDIDATE_MOVES} busy={busy} onAct={onAct} />
        </>
      )}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <StatusChip status={row.status} />
          {row.rejection_reason && (
            <span className="text-[11.5px] text-[var(--accent-orange)]">
              {row.rejection_reason}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Detail label="Current employer">{row.current_employer}</Detail>
          <Detail label="Notice period">{row.notice_period}</Detail>
          <Detail label="Current CTC">
            {row.current_ctc != null ? money(row.current_ctc) : '—'}
          </Detail>
          <Detail label="Expected CTC">
            {row.expected_ctc != null ? money(row.expected_ctc) : '—'}
          </Detail>
          <Detail label="Talent Fit score">
            {row.tfs_score != null ? row.tfs_score : '—'}
          </Detail>
          <Detail label="PI score">{row.pi_score != null ? row.pi_score : '—'}</Detail>
          {row.screening_notes && (
            <Detail label="Screening notes" span>{row.screening_notes}</Detail>
          )}
        </div>

        {!open && (
          <p className="text-[11.5px] text-[var(--text-muted)] border-t
            border-[var(--border)] pt-3">
            {isInternal
              ? 'The assessment opens once the client has approved this CV. That verdict '
                + 'is theirs alone — no Sparsh role can give it.'
              : 'The assessment opens once you have approved this CV. That verdict is '
                + 'yours alone — no Sparsh role can give it for you.'}
          </p>
        )}

        {open && (
          <>
            <StagePanel
              title="Assessment"
              hint="Marked against the approved scorecard, then shared with the client."
              rows={assessments}
              empty="No assessment issued yet."
              onAdd={can(CAP.CLIENT_ASSESSMENT_MANAGE) && !assessments.length
                ? () => setIssuing(true) : null}
              addLabel="Issue assessment"
              renderRow={(a) => (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                        {a.title || a.cas_no}
                      </p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {a.cas_no}
                        {a.due_on ? ` · due ${day(a.due_on)}` : ''}
                        {a.score != null ? ` · ${a.score}/${a.max_score ?? 5}` : ''}
                        {a.result ? ` · ${a.result}` : ''}
                      </p>
                    </div>
                    <StatusChip status={a.status} />
                  </div>
                  <div className="mt-2 flex items-center justify-end gap-1.5">
                    {can(CAP.CLIENT_ASSESSMENT_SCORE) && a.status === 'Submitted' && (
                      <Btn onClick={() => setScoring(a)}>Enter score</Btn>
                    )}
                    <Moves
                      row={a} moves={ASSESSMENT_MOVES} busy={stageBusy}
                      onAct={(action, payload) => run(
                        () => actOnClientAssessment(
                          a.cas_no, { action, ...(payload || {}) }, scope),
                        `${a.cas_no} updated`)}
                    />
                  </div>
                </>
              )}
            />

            <StagePanel
              title="Interview"
              hint="Sparsh conducts it and shares the recording; the client makes the selection."
              rows={interviews}
              empty="No interview scheduled yet."
              onAdd={can(CAP.CLIENT_INTERVIEW_MANAGE) ? () => setScheduling(true) : null}
              addLabel="Schedule"
              renderRow={(i) => (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                        {day(i.scheduled_at)} · {i.mode || 'Virtual'}
                      </p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {i.cin_no}
                        {i.outcome ? ` · ${i.outcome}` : ''}
                        {(i.panel || []).length ? ` · ${i.panel.join(', ')}` : ''}
                      </p>
                      {i.recording_link && i.status !== 'Scheduled' && (
                        <a href={i.recording_link} target="_blank" rel="noreferrer"
                          className="text-[11px] font-semibold text-[var(--accent-indigo)]">
                          Watch the recording
                        </a>
                      )}
                    </div>
                    <StatusChip status={i.status} />
                  </div>
                  <div className="mt-2 flex items-center justify-end gap-1.5">
                    {can(CAP.CLIENT_INTERVIEW_MANAGE) && i.status === 'Scheduled' && (
                      <Btn onClick={() => setOutcoming(i)}>Enter scores</Btn>
                    )}
                    <Moves
                      row={i} moves={INTERVIEW_MOVES} busy={stageBusy}
                      onAct={(action, payload) => run(
                        () => actOnClientInterview(
                          i.cin_no, { action, ...(payload || {}) }, scope),
                        `${i.cin_no} updated`)}
                    />
                  </div>
                </>
              )}
            />
          </>
        )}
      </div>

      {issuing && (
        <AssessmentModal
          busy={stageBusy}
          onClose={() => setIssuing(false)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => createClientAssessment({ ...payload, ccn_no: row.ccn_no }, scope),
              'Assessment issued');
            if (ok) setIssuing(false);
          }}
        />
      )}

      {scoring && (
        <ScoreModal
          row={scoring}
          busy={stageBusy}
          onClose={() => setScoring(null)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => updateClientAssessment(scoring.cas_no, payload, scope),
              `${scoring.cas_no} scored`);
            if (ok) setScoring(null);
          }}
        />
      )}

      {scheduling && (
        <InterviewModal
          busy={stageBusy}
          onClose={() => setScheduling(false)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => createClientInterview({ ...payload, ccn_no: row.ccn_no }, scope),
              'Interview scheduled');
            if (ok) setScheduling(false);
          }}
        />
      )}

      {outcoming && (
        <OutcomeModal
          row={outcoming}
          busy={stageBusy}
          onClose={() => setOutcoming(null)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => updateClientInterview(outcoming.cin_no, payload, scope),
              `${outcoming.cin_no} updated`);
            if (ok) setOutcoming(null);
          }}
        />
      )}
    </Modal>
  );
};

const StagePanel = ({ title, hint, rows, empty, onAdd, addLabel, renderRow }) => (
  <div className="border-t border-[var(--border)] pt-3.5">
    <div className="flex items-center justify-between gap-2">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest
          text-[var(--text-muted)]">{title}</p>
        <p className="text-[11px] text-[var(--text-muted)]">{hint}</p>
      </div>
      {onAdd && <Btn onClick={onAdd}>{addLabel}</Btn>}
    </div>
    <div className="mt-2.5 space-y-2">
      {rows.length === 0 && (
        <p className="text-[11.5px] text-[var(--text-muted)]">{empty}</p>
      )}
      {rows.map((r, idx) => (
        <div key={r.cas_no || r.cin_no || idx}
          className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] p-2.5">
          {renderRow(r)}
        </div>
      ))}
    </div>
  </div>
);

export default ClientCandidates;
