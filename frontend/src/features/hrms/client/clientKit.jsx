import React, { useState } from 'react';
import { useHrms } from '../HrmsContext';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';
import { FIELD, LABEL, TEXTAREA } from '../internal/internalKit';
import { Building2 } from 'lucide-react';
import { CLIENT_TONE, ClientScopeContext } from './clientKit';

/**
 * HRMS ▸ Client Hiring ▸ shared pieces for the stage screens.
 *
 * Every client stage is the same shape: a list scoped to one tenant, a status, and a
 * small set of moves along a transition table where each move names its own capability
 * and some demand a reason. Writing that out five times invites five slightly different
 * readings of the same rules, so it lives here once and each screen declares its moves
 * as data.
 *
 * The declaration mirrors the server's table deliberately. It is NOT the authority — the
 * API re-checks every capability and every from-state — but a button the API would refuse
 * is a lie to whoever is looking at it, so the screen should not offer one.
 */

export const StatusChip = ({ status }) => (
  <Chip tone={CLIENT_TONE[status] || 'neutral'}>{status || '—'}</Chip>
);

/**
 * The moves available on one record.
 *
 * `moves` is a list of `{ id, label, tone, cap, from, remarks, reasonHint, fields }`. A
 * move shows only when the record is in a `from` state AND the viewer holds `cap` — the
 * same two conditions the server checks, in the same order, so the screen and the API
 * agree about what is possible.
 *
 * A few moves need more than a reason: confirming a joining needs the date somebody
 * actually started and their acknowledgement, recording an acceptance needs the date it
 * was received in writing. Those are declared as `fields` and collected in the same
 * dialog, because the alternative is a button that always fails with a 422 explaining
 * what it should have asked for.
 */
export const Moves = ({ row, moves, onAct, busy, statusKey = 'status' }) => {
  const { can } = useHrms();
  const [asking, setAsking] = useState(null);
  const status = row[statusKey];

  const available = moves.filter((m) =>
    (!m.from || m.from.includes(status)) && can(m.cap));

  if (!available.length) return null;

  return (
    <>
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {available.map((m) => (
          <Btn key={m.id} tone={m.tone || 'ghost'} disabled={busy}
            onClick={() => ((m.remarks || m.fields) ? setAsking(m) : onAct(m.id))}>
            {m.label}
          </Btn>
        ))}
      </div>
      {asking && (
        <MoveModal
          move={asking}
          busy={busy}
          onClose={() => setAsking(null)}
          onSubmit={async (payload) => {
            await onAct(asking.id, payload);
            setAsking(null);
          }}
        />
      )}
    </>
  );
};

/**
 * Collect whatever a move needs before it is sent: a reason, some fields, or both.
 *
 * The server rejects a return or a rejection that arrives with no reason, so the field is
 * required here too — a decision with no reason attached leaves whoever receives it
 * guessing at what to change. Declared `fields` are required the same way unless marked
 * optional, for the same reason: the API demands them, and finding that out by being
 * refused is a worse way to learn it than being asked.
 */
export const MoveModal = ({ move, busy, onClose, onSubmit }) => {
  const fields = move.fields || [];
  const [remarks, setRemarks] = useState('');
  const [values, setValues] = useState(() => Object.fromEntries(
    fields.map((f) => [f.name, f.type === 'checkbox' ? false : ''])));

  const set = (name, value) => setValues((v) => ({ ...v, [name]: value }));

  const missing = fields.some((f) => f.optional
    ? false
    : (f.type === 'checkbox' ? !values[f.name] : !String(values[f.name] || '').trim()));
  const reasonMissing = move.remarks && remarks.trim().length < 3;
  const blocked = missing || reasonMissing;

  return (
    <Modal
      title={move.label}
      subtitle={move.reasonHint
        || 'This is recorded against the file and shown to whoever picks it up next.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone={move.tone === 'danger' ? 'danger' : 'primary'}
            disabled={busy || blocked}
            onClick={() => onSubmit({
              ...values,
              ...(move.remarks ? { remarks: remarks.trim() } : {}),
            })}>
            {busy ? 'Saving…' : move.label}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        {fields.map((f) => (f.type === 'checkbox' ? (
          <label key={f.name}
            className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
            <input type="checkbox" checked={!!values[f.name]}
              onChange={(e) => set(f.name, e.target.checked)} />
            {f.label}
          </label>
        ) : (
          <div key={f.name}>
            <label className={LABEL} htmlFor={`move-${f.name}`}>{f.label}</label>
            <input
              id={`move-${f.name}`}
              className={FIELD}
              type={f.type || 'text'}
              value={values[f.name]}
              onChange={(e) => set(f.name, e.target.value)}
            />
            {f.hint && (
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">{f.hint}</p>
            )}
          </div>
        )))}

        {move.remarks && (
          <div>
            <label className={LABEL} htmlFor="move-remarks">Reason</label>
            <textarea
              id="move-remarks"
              className={TEXTAREA}
              rows={4}
              autoFocus={!fields.length}
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="Say what needs to change, or why this was not accepted."
            />
          </div>
        )}

        {blocked && (
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {reasonMissing && !missing
              ? 'A reason is required for this action.'
              : 'Every field above is required for this action.'}
          </p>
        )}
      </div>
    </Modal>
  );
};

/** A labelled read-only value, for the detail panels. */
export const Detail = ({ label, children, span }) => (
  <div className={span ? 'col-span-2' : ''}>
    <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </p>
    <div className="mt-0.5 text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
      {children ?? '—'}
    </div>
  </div>
);

/**
 * The line that explains whose turn it is.
 *
 * The PRO-fit flow alternates between Sparsh and the client, and the single most common
 * question on any of these screens is "am I waiting on them, or are they waiting on me".
 */
export const WhoseMove = ({ children }) => (
  <p className="text-[11.5px] text-[var(--text-muted)]">{children}</p>
);

/**
 * Pick which client company a Client Hiring screen is showing.
 *
 * Only Sparsh staff see a control: a client-side user is pinned to their own company by
 * the server, so a selector would be a dropdown with one entry and no purpose. They get
 * the name as a plain label instead, which answers "whose data am I looking at" without
 * implying it can be changed.
 */
export const ClientCompanyBar = ({ clients, picked, onPick, isInternal, anyEnabled }) => {
  if (!isInternal) return null;

  if (!anyEnabled && !clients.length) {
    return (
      <p className="text-[12px] text-[var(--accent-orange)]">
        No client company has HRMS switched on yet, so there is nothing here to show.
        Switching one on from Companies is what lets their people raise a requirement.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Building2 size={14} className="text-[var(--text-muted)]" />
      <span className="text-[10px] font-bold uppercase tracking-widest
        text-[var(--text-muted)]">Client</span>
      <select value={picked} onChange={(e) => onPick(e.target.value)}
        className="h-9 px-2.5 rounded-lg border border-[var(--border)]
          bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]
          max-w-[280px]">
        {clients.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}{c.enabled ? '' : ' (module off)'}
          </option>
        ))}
      </select>
    </div>
  );
};

/** Pins every Client Hiring panel below it to one client company. See ClientScopeContext. */
export const ClientScopeProvider = ({ companyId, children }) => (
  <ClientScopeContext.Provider
    value={React.useMemo(
      () => (companyId ? { company_id: companyId } : {}), [companyId])}>
    {children}
  </ClientScopeContext.Provider>
);

/**
 * The heading a stage panel uses when it is embedded in the workspace.
 *
 * The full HrmsPageHeader belongs to a page; repeating it inside a panel that already sits
 * under one would give the screen two titles and two rows of buttons.
 */
export const PanelHeader = ({ title, subtitle, actions }) => (
  <div className="flex flex-wrap items-start justify-between gap-2">
    <div className="min-w-0">
      <p className="text-[15px] font-bold text-[var(--text-main)]">{title}</p>
      {subtitle && (
        <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>
      )}
    </div>
    {actions}
  </div>
);
