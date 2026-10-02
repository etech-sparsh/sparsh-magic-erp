import React, { useCallback, useEffect, useState } from 'react';
import { ClipboardCheck, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientScorecards, getClientRequisitions, createClientScorecard,
  updateClientScorecard, actOnClientScorecard,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientList, useClientScope } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ Position Scorecard.
 *
 * PRO-fit SOP section 8. The scorecard is the benchmark every later stage is measured
 * against — the screening score, the assessment, the interview — so it is agreed with the
 * client BEFORE anyone is sourced. Sourcing against a benchmark the client has not signed
 * off produces candidates nobody asked for.
 *
 * Three hands touch it in order: the recruiter drafts, Sparsh reviews internally, the
 * client approves. Only the client's approval opens sourcing, and no Sparsh role can give
 * it — that is the point of the stage, not an oversight.
 */

/** The five sections of the scorecard, in the order the SOP lists them. */
const SECTIONS = [
  ['responsibilities', 'Key responsibilities',
    'What this person owns. The outcomes, not the tasks.'],
  ['skills', 'Skills and competencies',
    'What they must be able to do on day one.'],
  ['experience', 'Experience',
    'Years, domains, and the kind of organisation it was earned in.'],
  ['cultural_expectations', 'Cultural expectations',
    'How they need to work here to succeed here.'],
  ['success_indicators', 'Success indicators',
    'What "working out" looks like at three and six months.'],
];

const MOVES = [
  { id: 'submit-for-review', label: 'Submit for review', tone: 'primary',
    cap: CAP.CLIENT_SCORECARD_WRITE, from: ['Draft'] },
  { id: 'internal-approve', label: 'Approve internally', tone: 'primary',
    cap: CAP.CLIENT_SCORECARD_REVIEW, from: ['Pending Internal Review'] },
  { id: 'internal-return', label: 'Return to draft', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_SCORECARD_REVIEW, from: ['Pending Internal Review'],
    reasonHint: 'The recruiter sees this when they reopen the draft.' },
  { id: 'client-approve', label: 'Approve', tone: 'primary',
    cap: CAP.CLIENT_SCORECARD_APPROVE, from: ['Pending Client Approval'] },
  { id: 'client-return', label: 'Send back', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_SCORECARD_APPROVE, from: ['Pending Client Approval'],
    reasonHint: 'Say what the benchmark is missing so it comes back right.' },
];

const ClientScorecards = ({ embedded, onChanged }) => {
  // Every mutation already reloads this screen's own list. The workspace's stage rail
  // counts the same records independently, so it has to be told as well -- otherwise
  // acting inside a panel leaves the rail above it showing figures from before the
  // action, which reads as the action not having worked.
  const refresh = () => { reload(); onChanged?.(); };
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientScorecards, 'client_scorecards');

  const [drafting, setDrafting] = useState(false);
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.CLIENT_SCORECARD_WRITE);

  const act = async (pscNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientScorecard(pscNo, { action, ...payload }, scope);
      showSuccess(`${pscNo} updated`);
      setViewing(null);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'psc', label: 'Scorecard',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.psc_no}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.role_title || r.cr_no}
          </span>
        </>
      ) },
    { key: 'cr', label: 'Requisition',
      render: (r) => <span className="text-[var(--text-muted)]">{r.cr_no || '—'}</span> },
    { key: 'drafted', label: 'Drafted',
      render: (r) => (
        <>
          <span className="text-[var(--text-muted)]">{day(r.created_at)}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.drafted_by_name || '—'}
          </span>
        </>
      ) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {canWrite && r.status === 'Draft' && (
            <Btn onClick={() => setEditing(r)}>Edit</Btn>
          )}
          <Btn onClick={() => setViewing(r)}>Open</Btn>
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.psc_no}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.role_title || r.cr_no}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Requisition', value: r.cr_no || '—' },
        { label: 'Drafted', value: day(r.created_at) },
        { label: 'By', value: r.drafted_by_name || '—' },
      ]} />
      <div className="flex items-center gap-1.5">
        {canWrite && r.status === 'Draft' && <Btn onClick={() => setEditing(r)}>Edit</Btn>}
        <Btn onClick={() => setViewing(r)}>Open</Btn>
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader
          title="Position scorecards"
          subtitle="The benchmark every later stage is measured against — agreed before sourcing begins (SOP section 8)"
          actions={canWrite && (
          <Btn tone="primary" onClick={() => setDrafting(true)}>
            <Plus size={14} /> Draft a scorecard
          </Btn>
        )}
        />
      ) : (
        <>
          <HrmsPageHeader
            icon={ClipboardCheck}
            title="Position scorecards"
            subtitle="The benchmark every later stage is measured against — agreed before sourcing begins (SOP section 8)"
            actions={canWrite && (
          <Btn tone="primary" onClick={() => setDrafting(true)}>
            <Plus size={14} /> Draft a scorecard
          </Btn>
        )}
          />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        {isInternal ? (
          <>
            A scorecard moves recruiter → Sparsh review → client approval, and only the
            client&apos;s approval opens sourcing. Once it leaves the recruiter&apos;s
            draft it stops being editable, so an approval always refers to the text that
            was read.
          </>
        ) : (
          <>
            Sparsh drafts the benchmark and reviews it internally; only your approval
            opens sourcing. It stops being editable once it reaches you, so what you
            approve is exactly the text you read.
          </>
        )}
      </WhoseMove>

      {loading && <HrmsLoading label="Loading scorecards…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.psc_no}
          empty={<HrmsEmpty
            icon={ClipboardCheck}
            title="No scorecards yet"
            hint={canWrite
              ? 'Draft one against an approved requisition to start the benchmark.'
              : 'Nothing has been sent for your approval yet.'}
          />}
        />
      )}

      {drafting && (
        <ScorecardModal
          busy={busy}
          onClose={() => setDrafting(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await createClientScorecard(payload, scope);
              showSuccess(`${data.psc_no} drafted`);
              setDrafting(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be drafted.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editing && (
        <ScorecardModal
          row={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateClientScorecard(editing.psc_no, payload, scope);
              showSuccess(`${editing.psc_no} saved`);
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

      {viewing && (
        <Modal
          title={viewing.psc_no}
          subtitle={viewing.role_title || viewing.cr_no}
          onClose={() => setViewing(null)}
          footer={(
            <>
              <Btn onClick={() => setViewing(null)}>Close</Btn>
              <Moves
                row={viewing} moves={MOVES} busy={busy}
                onAct={(action, payload) => act(viewing.psc_no, action, payload)}
              />
            </>
          )}
        >
          <div className="space-y-3.5">
            <div className="flex items-center gap-2">
              <StatusChip status={viewing.status} />
              {viewing.returned_reason && (
                <span className="text-[11.5px] text-[var(--accent-orange)]">
                  Sent back: {viewing.returned_reason}
                </span>
              )}
            </div>
            {SECTIONS.map(([key, label]) => (
              <Detail key={key} label={label}>{viewing[key] || '—'}</Detail>
            ))}
            <div className="grid grid-cols-2 gap-3 pt-1">
              <Detail label="Requisition">{viewing.cr_no}</Detail>
              <Detail label="Drafted">{day(viewing.created_at)}</Detail>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};

/**
 * Draft or edit the five sections.
 *
 * On a new scorecard the requisition has to be chosen, and only an APPROVED one can carry
 * a scorecard — the feasibility review is what decides the engagement is deliverable, and
 * writing a benchmark for a requisition Sparsh has not accepted is work nobody has agreed
 * to do. On an edit the requisition is fixed and shown, not re-picked.
 */
const ScorecardModal = ({ row, busy, onClose, onSubmit }) => {
  const scope = useClientScope();
  const editing = !!row;
  const [form, setForm] = useState(() => ({
    cr_no: row?.cr_no || '',
    responsibilities: row?.responsibilities || '',
    skills: row?.skills || '',
    experience: row?.experience || '',
    cultural_expectations: row?.cultural_expectations || '',
    success_indicators: row?.success_indicators || '',
  }));
  const [reqs, setReqs] = useState([]);
  const [reqsLoaded, setReqsLoaded] = useState(editing);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const loadReqs = useCallback(async () => {
    if (editing) return;
    try {
      const { data } = await getClientRequisitions(
        { ...scope, status: 'Approved', limit: 200 });
      setReqs(data?.client_requisitions || []);
    } catch {
      setReqs([]);
    } finally {
      setReqsLoaded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, JSON.stringify(scope)]);

  useEffect(() => { loadReqs(); }, [loadReqs]);

  const ready = editing || !!form.cr_no;

  return (
    <Modal
      title={editing ? `Edit ${row.psc_no}` : 'Draft a position scorecard'}
      subtitle="Every later score is measured against this, so write it as a benchmark rather than a job advert."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready}
            onClick={() => onSubmit(editing
              ? { ...form, cr_no: undefined }
              : form)}>
            {busy ? 'Saving…' : (editing ? 'Save' : 'Create draft')}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3.5">
        {editing ? (
          <Detail label="Requisition">{row.cr_no}</Detail>
        ) : (
          <div>
            <label className={LABEL} htmlFor="psc-cr">Requisition</label>
            <select id="psc-cr" className={FIELD} value={form.cr_no}
              onChange={set('cr_no')}>
              <option value="">Select an approved requisition…</option>
              {reqs.map((r) => (
                <option key={r.cr_no} value={r.cr_no}>
                  {r.cr_no} — {r.role_title || 'Untitled role'}
                </option>
              ))}
            </select>
            {reqsLoaded && !reqs.length && (
              <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
                No approved requisition to scorecard yet. Sparsh&apos;s feasibility review
                has to clear one first.
              </p>
            )}
          </div>
        )}

        {SECTIONS.map(([key, label, hint]) => (
          <div key={key}>
            <label className={LABEL} htmlFor={`psc-${key}`}>{label}</label>
            <textarea
              id={`psc-${key}`}
              className={TEXTAREA}
              rows={3}
              value={form[key]}
              onChange={set(key)}
              placeholder={hint}
            />
          </div>
        ))}
      </div>
    </Modal>
  );
};

export default ClientScorecards;
