import React, { useCallback, useEffect, useState } from 'react';
import { UserCheck, Plus, AlertTriangle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getClientJoinings, getClientCandidates, openClientJoining,
  updateClientJoining, actOnClientJoining, recordClientTouchpoint,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import { Detail, Moves, StatusChip, WhoseMove, PanelHeader } from './clientKit.jsx';
import { useClientList, useClientScope } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ pre-boarding, joining and handover.
 *
 * PRO-fit SOP sections 18-20. The gap between "accepted" and "day one" is where placements
 * are lost, so this stage is about staying in contact rather than about paperwork: each
 * touchpoint is logged, and one can be marked at risk.
 *
 * The joining itself is confirmed by the CLIENT — they are the only party who knows
 * whether somebody actually turned up. Sparsh can record a drop-out and can hand over the
 * file, but cannot declare somebody joined.
 */

const MOVES = [
  // Section 18 confirms joining IN WRITING, so the server demands the date they actually
  // started and the candidate's own acknowledgement. Asked for here rather than let the
  // click fail with a 422 explaining what it should have collected.
  { id: 'confirm-joining', label: 'Confirm joining', tone: 'primary',
    cap: CAP.CLIENT_JOINING_CONFIRM, from: ['Pre-boarding'],
    reasonHint: 'Section 18: the date they actually started, and their acknowledgement.',
    fields: [
      { name: 'actual_joining_date', label: 'Date they actually started', type: 'date',
        hint: 'The real first day, which is not always the date that was planned.' },
      { name: 'acknowledged', label: 'The candidate has acknowledged joining',
        type: 'checkbox' },
    ] },
  { id: 'record-drop', label: 'Record drop-out', tone: 'danger', remarks: true,
    cap: CAP.CLIENT_JOINING_MANAGE, from: ['Pre-boarding'],
    reasonHint: 'What happened. Drop-outs between offer and day one are the ones worth understanding.' },
  { id: 'share-handover', label: 'Share handover', tone: 'primary',
    cap: CAP.CLIENT_JOINING_HANDOVER, from: ['Joined'] },
];

/** Section 20's handover pack — what goes to the client when the placement closes. */
const HANDOVER = [
  ['candidate_file', 'Candidate file'],
  ['scorecards', 'Scorecards'],
  ['interview_records', 'Interview records'],
  ['verification_status', 'Verification status'],
];

const ClientJoinings = ({ embedded, onChanged }) => {
  // Every mutation already reloads this screen's own list. The workspace's stage rail
  // counts the same records independently, so it has to be told as well -- otherwise
  // acting inside a panel leaves the rail above it showing figures from before the
  // action, which reads as the action not having worked.
  const refresh = () => { reload(); onChanged?.(); };
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const { rows, loading, error, reload } = useClientList(
    getClientJoinings, 'client_joinings');

  const [opening, setOpening] = useState(false);
  const [opened, setOpened] = useState(null);
  const [busy, setBusy] = useState(false);

  const canManage = can(CAP.CLIENT_JOINING_MANAGE);

  const act = async (cjnNo, action, payload = {}) => {
    setBusy(true);
    try {
      await actOnClientJoining(cjnNo, { action, ...payload }, scope);
      showSuccess(`${cjnNo} updated`);
      setOpened(null);
      refresh();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'who', label: 'Joiner',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.candidate_name || r.ccn_no}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.cjn_no} · {r.cr_no}
          </span>
        </>
      ) },
    { key: 'date', label: 'Joining date',
      render: (r) => (
        <span className="text-[var(--text-muted)]">
          {r.joining_date ? day(r.joining_date) : '—'}
        </span>
      ) },
    // The contact log is Sparsh's working record and the API does not return it to a
    // client. Shown as a column only to the side that has it -- rendering "Never" for
    // every row would read as "nobody has called this person" rather than "withheld".
    ...(isInternal ? [{ key: 'contact', label: 'Last contact',
      render: (r) => {
        const last = (r.touchpoints || []).slice(-1)[0];
        return (
          <span className="text-[var(--text-muted)] text-[11.5px]">
            {last ? day(last.contacted_on || last.created_at) : 'Never'}
            {last?.channel ? <span className="block">{last.channel}</span> : null}
          </span>
        );
      } }] : []),
    { key: 'risk', label: 'Risk',
      render: (r) => (r.at_risk ? (
        <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold
          text-[var(--accent-orange)]">
          <AlertTriangle size={12} /> At risk
        </span>
      ) : <span className="text-[var(--text-muted)]">—</span>) },
    { key: 'status', label: 'Status', align: 'right',
      render: (r) => <StatusChip status={r.status} /> },
    { key: 'act', label: '', align: 'right',
      render: (r) => <Btn onClick={() => setOpened(r)}>Open</Btn> },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.candidate_name || r.ccn_no}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.cjn_no} · {r.cr_no}
          </p>
        </div>
        <StatusChip status={r.status} />
      </div>
      <Facts items={[
        { label: 'Joining', value: r.joining_date ? day(r.joining_date) : '—' },
        ...(isInternal
          ? [{ label: 'Touchpoints', value: String((r.touchpoints || []).length) }]
          : []),
        { label: 'Risk', value: r.at_risk ? 'At risk' : '—' },
      ]} />
      <Btn onClick={() => setOpened(r)}>Open</Btn>
    </div>
  );

  return (
    <div className="space-y-5">
      {embedded ? (
        <PanelHeader
          title="Pre-boarding & joining"
          subtitle="Staying in contact between acceptance and day one, then the handover (SOP sections 18–20)"
          actions={canManage && (
          <Btn tone="primary" onClick={() => setOpening(true)}>
            <Plus size={14} /> Open pre-boarding
          </Btn>
        )}
        />
      ) : (
        <>
          <HrmsPageHeader
            icon={UserCheck}
            title="Pre-boarding & joining"
            subtitle="Staying in contact between acceptance and day one, then the handover (SOP sections 18–20)"
            actions={canManage && (
          <Btn tone="primary" onClick={() => setOpening(true)}>
            <Plus size={14} /> Open pre-boarding
          </Btn>
        )}
          />
          <HrmsScopeBar />
        </>
      )}

      <WhoseMove>
        {isInternal ? (
          <>
            The client confirms the joining — they are the only party who knows whether
            somebody turned up. Sparsh keeps contact through the gap, records a drop-out
            if it happens, and hands over the file once the placement closes.
          </>
        ) : (
          <>
            You confirm the joining — you are the only party who knows whether somebody
            turned up, so section 18 asks for it in writing. Sparsh keeps contact through
            the gap and hands over the file once the placement closes.
          </>
        )}
      </WhoseMove>

      {loading && <HrmsLoading label="Loading joiners…" />}
      {error && !loading && <HrmsError message={error} onRetry={reload} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.cjn_no}
          empty={<HrmsEmpty
            icon={UserCheck}
            title="Nobody in pre-boarding"
            hint={canManage
              ? 'Open pre-boarding for a candidate who has accepted their offer.'
              : 'Nothing is waiting for your confirmation.'}
          />}
        />
      )}

      {opening && (
        <OpenModal
          busy={busy}
          onClose={() => setOpening(false)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              const { data } = await openClientJoining(payload, scope);
              showSuccess(`${data.cjn_no} opened`);
              setOpening(false);
              refresh();
            } catch (err) {
              showError(err?.response?.data?.detail || 'That could not be opened.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {opened && (
        <JoiningDetail
          row={opened}
          busy={busy}
          onClose={() => setOpened(null)}
          onAct={(action, payload) => act(opened.cjn_no, action, payload)}
          onChanged={reload}
        />
      )}
    </div>
  );
};

const OpenModal = ({ busy, onClose, onSubmit }) => {
  const scope = useClientScope();
  const [ccnNo, setCcnNo] = useState('');
  const [joiningDate, setJoiningDate] = useState('');
  const [candidates, setCandidates] = useState([]);

  const load = useCallback(async () => {
    try {
      const { data } = await getClientCandidates({ ...scope, limit: 200 });
      // Only an accepted offer opens pre-boarding; anybody else is a dead end here.
      setCandidates((data?.client_candidates || [])
        .filter((c) => c.status === 'Offer Accepted'));
    } catch { setCandidates([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(scope)]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal
      title="Open pre-boarding"
      subtitle="The gap between acceptance and day one is where placements are lost."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ccnNo}
            onClick={() => onSubmit({
              ccn_no: ccnNo,
              joining_date: joiningDate || undefined,
            })}>
            {busy ? 'Saving…' : 'Open'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div>
          <label className={LABEL} htmlFor="jn-ccn">Candidate</label>
          <select id="jn-ccn" className={FIELD} value={ccnNo}
            onChange={(e) => setCcnNo(e.target.value)}>
            <option value="">Select a candidate who accepted…</option>
            {candidates.map((c) => (
              <option key={c.ccn_no} value={c.ccn_no}>
                {c.candidate_name} — {c.cr_no}
              </option>
            ))}
          </select>
          {!candidates.length && (
            <p className="mt-1.5 text-[11.5px] text-[var(--accent-orange)]">
              No accepted offer yet.
            </p>
          )}
        </div>
        <div>
          <label className={LABEL} htmlFor="jn-date">Expected joining date</label>
          <input id="jn-date" className={FIELD} type="date" value={joiningDate}
            onChange={(e) => setJoiningDate(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

/** The joiner, the contact log, and section 20's handover pack. */
const JoiningDetail = ({ row, busy, onClose, onAct, onChanged }) => {
  const { can, isInternal } = useHrms();
  const scope = useClientScope();
  const { showSuccess, showError } = useNotification();
  const [record, setRecord] = useState(row);
  const [logging, setLogging] = useState(false);
  const [editing, setEditing] = useState(false);
  const [panelBusy, setPanelBusy] = useState(false);

  const canManage = can(CAP.CLIENT_JOINING_MANAGE);
  const touchpoints = record.touchpoints || [];

  const run = async (fn, okMessage) => {
    setPanelBusy(true);
    try {
      const { data } = await fn();
      if (data && data.cjn_no) setRecord(data);
      showSuccess(okMessage);
      onChanged();
      return true;
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be recorded.');
      return false;
    } finally {
      setPanelBusy(false);
    }
  };

  return (
    <Modal
      title={record.candidate_name || record.ccn_no}
      subtitle={`${record.cjn_no} · ${record.cr_no}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Moves row={record} moves={MOVES} busy={busy}
            onAct={(action, payload) => onAct(action, payload)} />
        </>
      )}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <StatusChip status={record.status} />
          {record.at_risk && (
            <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold
              text-[var(--accent-orange)]">
              <AlertTriangle size={12} /> At risk
            </span>
          )}
          {canManage && <Btn onClick={() => setEditing(true)}>Edit details</Btn>}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Detail label="Joining date">
            {record.joining_date ? day(record.joining_date) : '—'}
          </Detail>
          <Detail label="Actual joining">
            {record.actual_joining_date ? day(record.actual_joining_date) : '—'}
          </Detail>
          <Detail label="Client requirements ready">
            {record.client_requirements_ready == null
              ? '—' : (record.client_requirements_ready ? 'Yes' : 'Not yet')}
          </Detail>
          <Detail label="Background check">{record.background_check_result}</Detail>
          <Detail label="Culture score">
            {record.culture_score != null ? record.culture_score : '—'}
          </Detail>
          {record.drop_reason && (
            <Detail label="Drop reason" span>{record.drop_reason}</Detail>
          )}
        </div>

        <div className="border-t border-[var(--border)] pt-3.5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest
                text-[var(--text-muted)]">Contact log</p>
              <p className="text-[11px] text-[var(--text-muted)]">
                {isInternal
                  ? 'Every call and message through the gap, and whether it left you worried.'
                  : 'Sparsh keeps the contact log. What a candidate says about a counter-offer is a working note, not something to hand their future employer — the at-risk flag above is the part that concerns you.'}
              </p>
            </div>
            {canManage && record.status === 'Pre-boarding' && (
              <Btn onClick={() => setLogging(true)}>Log contact</Btn>
            )}
          </div>
          <div className="mt-2.5 space-y-2">
            {isInternal && !touchpoints.length && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                No contact logged yet.
              </p>
            )}
            {touchpoints.map((t, idx) => (
              <div key={idx}
                className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)]
                  p-2.5 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[12.5px] text-[var(--text-main)]">
                    {day(t.contacted_on || t.created_at)}
                    {t.channel ? ` · ${t.channel}` : ''}
                  </p>
                  {t.notes && (
                    <p className="text-[11px] text-[var(--text-muted)]">{t.notes}</p>
                  )}
                </div>
                {t.at_risk && (
                  <span className="text-[11px] font-semibold text-[var(--accent-orange)]">
                    At risk
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="border-t border-[var(--border)] pt-3.5">
          <p className="text-[10px] font-bold uppercase tracking-widest
            text-[var(--text-muted)]">Handover pack</p>
          <p className="text-[11px] text-[var(--text-muted)]">
            What goes to the client when the placement closes (section 20).
          </p>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {HANDOVER.map(([key, label]) => (
              <p key={key} className="text-[12px] text-[var(--text-main)]">
                {record[key] ? '✓' : '○'}{' '}
                <span className={record[key] ? '' : 'text-[var(--text-muted)]'}>
                  {label}
                </span>
              </p>
            ))}
          </div>
          {record.handover_note && (
            <div className="mt-2">
              <Detail label="Handover note">{record.handover_note}</Detail>
            </div>
          )}
        </div>
      </div>

      {logging && (
        <TouchpointModal
          busy={panelBusy}
          onClose={() => setLogging(false)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => recordClientTouchpoint(record.cjn_no, payload, scope),
              'Contact logged');
            if (ok) setLogging(false);
          }}
        />
      )}

      {editing && (
        <JoiningEditModal
          row={record}
          busy={panelBusy}
          onClose={() => setEditing(false)}
          onSubmit={async (payload) => {
            const ok = await run(
              () => updateClientJoining(record.cjn_no, payload, scope),
              `${record.cjn_no} saved`);
            if (ok) setEditing(false);
          }}
        />
      )}
    </Modal>
  );
};

const TouchpointModal = ({ busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    contacted_on: '', channel: 'Call', at_risk: false, notes: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Modal
      title="Log contact"
      subtitle="Mark it at risk if anything in the conversation suggested they may not join."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy}
            onClick={() => onSubmit({
              contacted_on: form.contacted_on || undefined,
              channel: form.channel,
              at_risk: form.at_risk,
              notes: form.notes || undefined,
            })}>
            {busy ? 'Saving…' : 'Log'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="tp-when">When</label>
            <input id="tp-when" className={FIELD} type="date" value={form.contacted_on}
              onChange={set('contacted_on')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="tp-channel">Channel</label>
            <select id="tp-channel" className={FIELD} value={form.channel}
              onChange={set('channel')}>
              <option>Call</option>
              <option>Email</option>
              <option>WhatsApp</option>
              <option>In person</option>
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
          <input type="checkbox" checked={form.at_risk}
            onChange={(e) => setForm((f) => ({ ...f, at_risk: e.target.checked }))} />
          This joiner is at risk
        </label>
        <div>
          <label className={LABEL} htmlFor="tp-notes">Notes</label>
          <textarea id="tp-notes" className={TEXTAREA} rows={3} value={form.notes}
            onChange={set('notes')} />
        </div>
      </div>
    </Modal>
  );
};

const JoiningEditModal = ({ row, busy, onClose, onSubmit }) => {
  const [form, setForm] = useState(() => ({
    joining_date: row.joining_date ? String(row.joining_date).slice(0, 10) : '',
    client_requirements_ready: !!row.client_requirements_ready,
    background_check_result: row.background_check_result || '',
    culture_score: row.culture_score ?? '',
    handover_note: row.handover_note || '',
    candidate_file: !!row.candidate_file,
    scorecards: !!row.scorecards,
    interview_records: !!row.interview_records,
    verification_status: !!row.verification_status,
  }));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const check = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.checked }));

  return (
    <Modal
      title="Pre-boarding details"
      subtitle="Readiness on both sides, and the pack that closes the placement."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy}
            onClick={() => onSubmit({
              joining_date: form.joining_date || undefined,
              client_requirements_ready: form.client_requirements_ready,
              background_check_result: form.background_check_result || undefined,
              culture_score: form.culture_score === ''
                ? undefined : Number(form.culture_score),
              handover_note: form.handover_note || undefined,
              candidate_file: form.candidate_file,
              scorecards: form.scorecards,
              interview_records: form.interview_records,
              verification_status: form.verification_status,
            })}>
            {busy ? 'Saving…' : 'Save'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="je-date">Joining date</label>
            <input id="je-date" className={FIELD} type="date" value={form.joining_date}
              onChange={set('joining_date')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="je-culture">Culture score</label>
            <input id="je-culture" className={FIELD} type="number"
              value={form.culture_score} onChange={set('culture_score')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="je-bg">Background check result</label>
          <input id="je-bg" className={FIELD} value={form.background_check_result}
            onChange={set('background_check_result')} placeholder="Clear / Discrepancy" />
        </div>
        <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
          <input type="checkbox" checked={form.client_requirements_ready}
            onChange={check('client_requirements_ready')} />
          The client&apos;s side is ready for day one
        </label>

        <p className="pt-1 text-[10px] font-bold uppercase tracking-widest
          text-[var(--text-muted)]">Handover pack</p>
        <div className="grid grid-cols-2 gap-1.5">
          {HANDOVER.map(([key, label]) => (
            <label key={key}
              className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" checked={form[key]} onChange={check(key)} />
              {label}
            </label>
          ))}
        </div>
        <div>
          <label className={LABEL} htmlFor="je-note">Handover note</label>
          <textarea id="je-note" className={TEXTAREA} rows={3} value={form.handover_note}
            onChange={set('handover_note')} />
        </div>
      </div>
    </Modal>
  );
};

export default ClientJoinings;
