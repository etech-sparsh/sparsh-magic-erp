import React, { useCallback, useEffect, useState } from 'react';
import { Video, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientInterviews, getClientAssessments, createClientInterview,
  updateClientInterview, actOnClientInterview,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientList, useClientScope } from './clientKit';
import { InterviewModal, OutcomeModal } from './clientStageModals.jsx';

/**
 * HRMS ▸ Client Hiring ▸ the interview board.
 *
 * Every interview at once, across people — the other half of the view the candidate
 * journey gives. Sparsh schedules and conducts; the client watches the recording and makes
 * the selection, which is the one decision on this screen that no Sparsh role can take.
 *
 * -- Scheduling --------------------------------------------------------------------
 * "Schedule" lists only candidates whose assessment the CLIENT HAS REVIEWED and who have
 * no interview yet. That is the server's gate (`assert_interview_allowed`), derived here
 * so the picker cannot offer a booking the API would refuse.
 */

const MOVES = [
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

const FILTERS = [
  ['all', 'All'],
  ['Scheduled', 'Scheduled'],
  ['Conducted', 'Conducted'],
  ['Shared with Client', 'With the client'],
  ['Selected by Client', 'Selected'],
  ['Rejected by Client', 'Rejected'],
];

const ClientInterviews = ({ embedded, onChanged }) => {
  const { can } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientInterviews, 'client_interviews');
  const refresh = () => { reload(); onChanged?.(); };

  const [filter, setFilter] = useState('all');
  const [scheduling, setScheduling] = useState(false);
  const [outcoming, setOutcoming] = useState(null);
  const [busy, setBusy] = useState(false);

  const canManage = can(CAP.CLIENT_INTERVIEW_MANAGE);
  const shown = filter === 'all' ? rows : rows.filter((r) => r.status === filter);

  const act = async (cinNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientInterview(cinNo, { action, ...payload }, scope);
      showSuccess(`${cinNo} updated`);
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
            {r.cin_no} · {r.ccn_no}
          </span>
        </>
      ) },
    { key: 'when', label: 'When',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.scheduled_at)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.mode || 'Virtual'}
          </span>
        </>
      ) },
    { key: 'scores', label: 'Panel',
      render: (r) => (
        <span className="tabular-nums text-[var(--text-muted)] text-[11.5px]">
          {r.average_score != null ? `avg ${r.average_score}` : '—'}
          {r.outcome && <span className="block">{r.outcome}</span>}
        </span>
      ) },
    { key: 'rec', label: 'Recording',
      render: (r) => (r.recording_link && r.status !== 'Scheduled' ? (
        <a href={r.recording_link} target="_blank" rel="noreferrer"
          className="text-[11.5px] font-semibold text-[var(--accent-indigo)]">
          Watch
        </a>
      ) : <span className="text-[var(--text-muted)]">—</span>) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canManage && r.status === 'Scheduled' && (
            <Btn onClick={() => setOutcoming(r)}>Enter scores</Btn>
          )}
          <Moves row={r} moves={MOVES} busy={busy}
            onAct={(action, payload) => act(r.cin_no, action, payload)} />
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
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {day(r.scheduled_at)} · {r.mode || 'Virtual'}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Average', value: r.average_score != null ? String(r.average_score) : '—' },
        { label: 'Outcome', value: r.outcome || '—' },
        { label: 'Panel', value: (r.panel || []).join(', ') || '—' },
      ]} />
      <div className="flex flex-wrap items-center gap-1.5">
        {canManage && r.status === 'Scheduled' && (
          <Btn onClick={() => setOutcoming(r)}>Enter scores</Btn>
        )}
        <Moves row={r} moves={MOVES} busy={busy}
          onAct={(action, payload) => act(r.cin_no, action, payload)} />
      </div>
    </div>
  );

  const header = {
    title: 'Interviews',
    subtitle: 'Conducted by Sparsh, watched by the client — the selection is theirs',
    actions: canManage && (
      <Btn tone="primary" onClick={() => setScheduling(true)}>
        <Plus size={14} /> Schedule an interview
      </Btn>
    ),
  };

  return (
    <div className="space-y-5">
      {embedded ? <PanelHeader {...header} /> : (
        <>
          <HrmsPageHeader icon={Video} {...header} />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        An interview can only be booked once the client has read the assessment result.
        All four panel scores and the recording link are required before it can be shared,
        and the selection that follows is the client&apos;s alone.
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

      {loading && <HrmsLoading label="Loading interviews…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={shown} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.cin_no}
          empty={<HrmsEmpty
            icon={Video}
            title={filter === 'all' ? 'No interviews yet' : 'Nothing at this stage'}
            hint={filter === 'all'
              ? 'Schedule one for a candidate whose assessment the client has reviewed.'
              : 'Try another filter.'}
          />}
        />
      )}

      {scheduling && (
        <ScheduleModal
          busy={busy}
          existing={rows}
          onClose={() => setScheduling(false)}
          onSubmit={async ({ ccn_no, ...rest }) => {
            setBusy(true);
            try {
              await createClientInterview({ ccn_no, ...rest }, scope);
              showSuccess('Interview scheduled');
              setScheduling(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be scheduled.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {outcoming && (
        <OutcomeModal
          row={outcoming}
          busy={busy}
          onClose={() => setOutcoming(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientInterview(outcoming.cin_no, payload, scope);
              showSuccess(`${outcoming.cin_no} updated`);
              setOutcoming(null);
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
 * Pick who to interview, then book it.
 *
 * Eligible = their assessment is "Reviewed by Client" AND they have no interview yet.
 * Read off the ASSESSMENTS, because that is where the gate actually lives — a candidate's
 * own status does not say whether the client has read the result.
 */
const ScheduleModal = ({ busy, existing, onClose, onSubmit }) => {
  const scope = useClientScope();
  const [eligible, setEligible] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [ccn, setCcn] = useState('');
  const [booking, setBooking] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getClientAssessments(
        { ...scope, status: 'Reviewed by Client', limit: 200 });
      const booked = new Set((existing || []).map((i) => i.ccn_no));
      setEligible((data?.client_assessments || [])
        .filter((a) => !booked.has(a.ccn_no)));
    } catch { setEligible([]); } finally { setLoaded(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(scope), (existing || []).length]);

  useEffect(() => { load(); }, [load]);

  if (booking) {
    return (
      <InterviewModal
        busy={busy}
        onClose={() => setBooking(false)}
        onSubmit={(payload) => onSubmit({ ...payload, ccn_no: ccn })}
      />
    );
  }

  return (
    <Modal
      title="Schedule an interview"
      subtitle="Only candidates whose assessment the client has reviewed can be interviewed."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={!ccn} onClick={() => setBooking(true)}>
            Next
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div>
          <label className={LABEL} htmlFor="iv-ccn">Candidate</label>
          <select id="iv-ccn" className={FIELD} value={ccn}
            onChange={(e) => setCcn(e.target.value)}>
            <option value="">Select a candidate…</option>
            {eligible.map((a) => (
              <option key={a.ccn_no} value={a.ccn_no}>
                {a.candidate_name || a.ccn_no}
                {a.score != null ? ` — assessed ${a.score}/${a.max_score ?? 5}` : ''}
              </option>
            ))}
          </select>
          {loaded && !eligible.length && (
            <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
              Nobody is ready to interview. A candidate becomes eligible once the client
              has reviewed their assessment result.
            </p>
          )}
        </div>
        {!!ccn && (
          <Detail label="Assessment">
            {(() => {
              const a = eligible.find((x) => x.ccn_no === ccn) || {};
              return a.result
                ? `${a.result}${a.score != null ? ` · ${a.score}/${a.max_score ?? 5}` : ''}`
                : '—';
            })()}
          </Detail>
        )}
      </div>
    </Modal>
  );
};

export default ClientInterviews;
