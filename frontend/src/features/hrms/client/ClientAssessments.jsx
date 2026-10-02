import React, { useCallback, useEffect, useState } from 'react';
import { ClipboardCheck, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientAssessments, getClientCandidates, createClientAssessment,
  updateClientAssessment, actOnClientAssessment,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientList, useClientScope } from './clientKit';
import { AssessmentModal, ScoreModal } from './clientStageModals.jsx';

/**
 * HRMS ▸ Client Hiring ▸ the assessment board.
 *
 * The same work the candidate journey shows in context, seen the other way round: every
 * assessment at once, across people. The internal track has both views for the same reason
 * — "where is this person up to" and "what is sitting at this stage" are different
 * questions, and a board that only answers the first makes the second a hunt.
 *
 * -- Assigning ---------------------------------------------------------------------
 * "Assign" lists the candidates who are ELIGIBLE: the client has approved their CV and
 * they have no assessment yet. Deriving that here rather than showing every candidate
 * means the picker cannot offer somebody the API would refuse.
 */

const MOVES = [
  { id: 'record-submission', label: 'Mark submitted', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_MANAGE, from: ['Sent'] },
  { id: 'score', label: 'Record score', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_SCORE, from: ['Submitted'] },
  { id: 'share', label: 'Share result', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_SHARE, from: ['Scored'] },
  { id: 'client-review', label: 'Mark reviewed', tone: 'primary',
    cap: CAP.CLIENT_ASSESSMENT_REVIEW, from: ['Shared with Client'] },
];

/** The lifecycle, as a filter strip. Mirrors the internal AssessmentBoard's. */
const FILTERS = [
  ['all', 'All'],
  ['Sent', 'Issued'],
  ['Submitted', 'Submitted'],
  ['Scored', 'Scored'],
  ['Shared with Client', 'With the client'],
  ['Reviewed by Client', 'Reviewed'],
];

const ClientAssessments = ({ embedded, onChanged }) => {
  const { can } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientAssessments, 'client_assessments');
  const refresh = () => { reload(); onChanged?.(); };

  const [filter, setFilter] = useState('all');
  const [assigning, setAssigning] = useState(false);
  const [scoring, setScoring] = useState(null);
  const [busy, setBusy] = useState(false);

  const canManage = can(CAP.CLIENT_ASSESSMENT_MANAGE);
  const shown = filter === 'all' ? rows : rows.filter((r) => r.status === filter);

  const act = async (casNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientAssessment(casNo, { action, ...payload }, scope);
      showSuccess(`${casNo} updated`);
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
            {r.candidate_name || r.ccn_no}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.cas_no} · {r.ccn_no}
          </span>
        </>
      ) },
    { key: 'title', label: 'Assessment',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{r.title || '—'}</span>
          {r.due_on && (
            <span className="block text-[11px] text-[var(--text-muted)]">
              due {day(r.due_on)}
            </span>
          )}
        </>
      ) },
    { key: 'score', label: 'Score',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-main)]">
          {r.score != null ? `${r.score}/${r.max_score ?? 5}` : '—'}
          {r.result && (
            <span className="block text-[11px] text-[var(--text-muted)]">{r.result}</span>
          )}
        </span>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {can(CAP.CLIENT_ASSESSMENT_SCORE) && r.status === 'Submitted' && (
            <Btn onClick={() => setScoring(r)}>Enter score</Btn>
          )}
          <Moves row={r} moves={MOVES} busy={busy}
            onAct={(action, payload) => act(r.cas_no, action, payload)} />
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name || r.ccn_no}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.title || r.cas_no}</p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Score', value: r.score != null ? `${r.score}/${r.max_score ?? 5}` : '—' },
        { label: 'Result', value: r.result || '—' },
        { label: 'Due', value: r.due_on ? day(r.due_on) : '—' },
      ]} />
      <div className="flex flex-wrap items-center gap-1.5">
        {can(CAP.CLIENT_ASSESSMENT_SCORE) && r.status === 'Submitted' && (
          <Btn onClick={() => setScoring(r)}>Enter score</Btn>
        )}
        <Moves row={r} moves={MOVES} busy={busy}
          onAct={(action, payload) => act(r.cas_no, action, payload)} />
      </div>
    </div>
  );

  const header = {
    title: 'Assessments',
    subtitle: 'The Talent Fit Assessment, marked against the scorecard the client approved',
    actions: canManage && (
      <Btn tone="primary" onClick={() => setAssigning(true)}>
        <Plus size={14} /> Assign an assessment
      </Btn>
    ),
  };

  return (
    <div className="space-y-5">
      {embedded ? <PanelHeader {...header} /> : (
        <>
          <HrmsPageHeader icon={ClipboardCheck} {...header} />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        An assessment can only be assigned once the client has approved that CV. Sparsh
        issues it, marks it and shares the result; the client records that they have read
        it, and that is what opens the interview.
      </WhoseMove>

      <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl border
        border-[var(--border)] bg-[var(--input-bg)] w-fit">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" onClick={() => setFilter(key)}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-bold transition-colors
              ${filter === key
                ? 'bg-[var(--accent-indigo)] text-white'
                : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
            {label}
            {key !== 'all' && (
              <span className="ml-1.5 tabular-nums opacity-70">
                {rows.filter((r) => r.status === key).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && <HrmsLoading label="Loading assessments…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={shown} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.cas_no}
          empty={<HrmsEmpty
            icon={ClipboardCheck}
            title={filter === 'all' ? 'No assessments yet' : 'Nothing at this stage'}
            hint={filter === 'all'
              ? 'Assign one to a candidate whose CV the client has approved.'
              : 'Try another filter.'}
          />}
        />
      )}

      {assigning && (
        <AssignModal
          busy={busy}
          existing={rows}
          onClose={() => setAssigning(false)}
          onSubmit={async ({ ccn_no, ...rest }) => {
            setBusy(true);
            try {
              await createClientAssessment({ ccn_no, ...rest }, scope);
              showSuccess('Assessment assigned');
              setAssigning(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be assigned.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {scoring && (
        <ScoreModal
          row={scoring}
          busy={busy}
          onClose={() => setScoring(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientAssessment(scoring.cas_no, payload, scope);
              showSuccess(`${scoring.cas_no} scored`);
              setScoring(null);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be saved.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
};

/**
 * Pick who to assess, then describe the assessment.
 *
 * Eligible = the client approved their CV AND they have no assessment already. Both halves
 * matter: the first is the server's gate, the second stops a second assessment being
 * issued to somebody mid-way through their first.
 */
const AssignModal = ({ busy, existing, onClose, onSubmit }) => {
  const scope = useClientScope();
  const [eligible, setEligible] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [ccn, setCcn] = useState('');
  const [describing, setDescribing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getClientCandidates(
        { ...scope, status: 'Client Approved', limit: 200 });
      const taken = new Set((existing || []).map((a) => a.ccn_no));
      setEligible((data?.client_candidates || []).filter((c) => !taken.has(c.ccn_no)));
    } catch { setEligible([]); } finally { setLoaded(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(scope), (existing || []).length]);

  useEffect(() => { load(); }, [load]);

  // Two steps rather than one long form: choosing the person and writing the assessment
  // are different decisions, and the second is the one worth thinking about.
  if (describing) {
    return (
      <AssessmentModal
        busy={busy}
        onClose={() => setDescribing(false)}
        onSubmit={(payload) => onSubmit({ ...payload, ccn_no: ccn })}
      />
    );
  }

  return (
    <Modal
      title="Assign an assessment"
      subtitle="Only candidates whose CV the client has already approved can be assessed."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={!ccn} onClick={() => setDescribing(true)}>
            Next
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div>
          <label className={LABEL} htmlFor="as-ccn">Candidate</label>
          <select id="as-ccn" className={FIELD} value={ccn}
            onChange={(e) => setCcn(e.target.value)}>
            <option value="">Select a candidate…</option>
            {eligible.map((c) => (
              <option key={c.ccn_no} value={c.ccn_no}>
                {c.candidate_name} — {c.cr_no}
              </option>
            ))}
          </select>
          {loaded && !eligible.length && (
            <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
              Nobody is waiting for an assessment. A candidate becomes eligible once the
              client approves their CV.
            </p>
          )}
        </div>
        {!!ccn && (
          <Detail label="Selected">
            {(eligible.find((c) => c.ccn_no === ccn) || {}).candidate_name}
          </Detail>
        )}
      </div>
    </Modal>
  );
};

export default ClientAssessments;
