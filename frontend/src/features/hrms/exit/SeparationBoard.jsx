import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { UserMinus, Search } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getSeparations, initiateSeparation, getEmployees } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, toneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Exit Management (BA/Functional Design §7.18, §22.2, §7.21).
 *
 * One list, filtered to what is still open by default — a company runs this screen to see
 * who is leaving right now, not to browse everyone who ever has. Closed/withdrawn cases stay
 * one filter away rather than gone, the same reasoning Probation's Overdue/Due-soon/Decided
 * split follows.
 *
 * The employee picker in the Initiate modal is a debounced search over the SAME directory
 * screen EmployeeDirectory already queries — no new endpoint, and the two screens can never
 * disagree about who exists.
 */

const EXIT_TYPES = ['Resignation', 'Termination', 'Retirement', 'Absconding', 'Demise',
  'Missing', 'End of Contract'];

const OPEN_STAGES = ['Initiated', 'Notice in Progress', 'Handover & Clearance',
  'F&F Pending', 'F&F Approved'];

const SeparationBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showClosed, setShowClosed] = useState(false);
  const [initiating, setInitiating] = useState(false);

  const canInitiate = can(CAP.SEPARATION_INITIATE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getSeparations({ ...scope, limit: 200 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load separations.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const visible = rows.filter((r) => (showClosed ? true : OPEN_STAGES.includes(r.stage)));
  // How many the "open only" default is currently hiding — surfaced on the checkbox and,
  // when it's the whole reason the list looks empty, on the empty state's own action button.
  // Without this a fully-closed board reads as "no data" rather than "filtered", which is
  // exactly the confusion this screen kept causing.
  const closedCount = rows.length - rows.filter((r) => OPEN_STAGES.includes(r.stage)).length;

  const columns = [
    { key: 'who', label: 'Employee',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.employee_code} · {r.sep_no}
          </span>
        </>
      ) },
    { key: 'type', label: 'Exit Type',
      render: (r) => <span className="text-[var(--text-main)]">{r.exit_type}</span> },
    { key: 'notice', label: 'Notice / LWD',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">
            {day(r.final_lwd || r.recommended_lwd || r.calculated_lwd)}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.calculated_notice_days} day{r.calculated_notice_days === 1 ? '' : 's'} notice
            {!r.final_lwd && r.recommended_lwd ? ' · pending approval' : ''}
          </span>
        </>
      ) },
    { key: 'stage', label: 'Stage', align: 'right',
      render: (r) => (
        <div className="flex flex-col items-end gap-1.5">
          <Chip tone={toneFor(r.stage)}>{r.stage}</Chip>
          <Link to={`/hrms/separations/${r.sep_no}`}>
            <Btn tone="ghost">Open</Btn>
          </Link>
        </div>
      ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {r.employee_name || r.employee_code}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            {r.employee_code} · {r.sep_no}
          </p>
        </div>
        <Chip tone={toneFor(r.stage)}>{r.stage}</Chip>
      </div>
      <Facts items={[
        { label: 'Exit Type', value: r.exit_type },
        { label: 'LWD', value: day(r.final_lwd || r.recommended_lwd || r.calculated_lwd) },
        { label: 'Notice', value: `${r.calculated_notice_days}d` },
      ]} />
      <Link to={`/hrms/separations/${r.sep_no}`}>
        <Btn tone="ghost">Open case</Btn>
      </Link>
    </div>
  );

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={UserMinus}
        title="Exit Management"
        subtitle="Resignation, notice, handover, clearance and Full & Final Settlement."
        actions={canInitiate && (
          <Btn tone="primary" onClick={() => setInitiating(true)}>
            <UserMinus size={14} /> Initiate Exit
          </Btn>
        )}
      />
      <HrmsScopeBar />

      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
          <input type="checkbox" checked={showClosed}
            onChange={(e) => setShowClosed(e.target.checked)} />
          Show closed / withdrawn cases
          {!loading && closedCount > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-[var(--input-bg)] text-[11px] font-bold text-[var(--text-muted)]">
              {closedCount}
            </span>
          )}
        </label>
      </div>

      {loading && <HrmsLoading label="Loading separations…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        visible.length ? (
          <RecordList rows={visible} columns={columns} renderCard={renderCard}
            keyOf={(r) => r.sep_no} />
        ) : (
          <HrmsEmpty
            icon={UserMinus}
            title={showClosed ? 'No separations recorded yet'
              : `No open separations${closedCount ? ` — ${closedCount} closed` : ''}`}
            hint={showClosed
              ? 'Initiate one when an employee resigns, retires, or is separated.'
              : closedCount
                ? 'Every case here has already been closed or withdrawn.'
                : 'Nothing has been initiated yet.'}
            action={!showClosed && closedCount > 0 && (
              <Btn onClick={() => setShowClosed(true)}>Show the {closedCount} closed case{closedCount === 1 ? '' : 's'}</Btn>
            )}
          />
        )
      )}

      {initiating && (
        <InitiateModal
          scope={scope}
          onClose={() => setInitiating(false)}
          onDone={(sepNo) => { setInitiating(false); load(); return sepNo; }}
          showSuccess={showSuccess} showError={showError}
        />
      )}
    </div>
  );
};

/** §7.18 step 137. Notice is calculated server-side from status + designation level — this
 *  form only captures WHO, WHY and WHEN, never the notice figure itself. */
const InitiateModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);
  const [employee, setEmployee] = useState(null);
  const [exitType, setExitType] = useState('Resignation');
  const [resignationDate, setResignationDate] = useState(
    new Date().toISOString().slice(0, 10));
  const [proposedLwd, setProposedLwd] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!debounced.trim() || employee) { setOptions([]); return; }
    let live = true;
    setSearching(true);
    getEmployees({ ...scope, search: debounced, limit: 8 })
      .then(({ data }) => { if (live) setOptions(data?.employees || []); })
      .catch(() => { if (live) setOptions([]); })
      .finally(() => { if (live) setSearching(false); });
    return () => { live = false; };
  }, [debounced, employee, scope]);

  const submit = async () => {
    if (!employee) {
      showError('Search for and select the departing employee.');
      return;
    }
    setBusy(true);
    try {
      const { data } = await initiateSeparation({
        employee_code: employee.employee_code,
        exit_type: exitType,
        resignation_date: resignationDate || undefined,
        proposed_lwd: proposedLwd || undefined,
        reason: reason.trim() || undefined,
      }, scope);
      showSuccess(
        `${data.sep_no} opened — calculated notice ${data.calculated_notice_days} day`
        + `${data.calculated_notice_days === 1 ? '' : 's'} (LWD ${day(data.calculated_lwd)}).`);
      onDone(data.sep_no);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not initiate this separation.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Initiate Exit" labelledBy="sep-init-title"
      subtitle="Notice is calculated automatically from employment status and designation level."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Initiate'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="sep-employee">Employee *</label>
        {employee ? (
          <div className="flex items-center justify-between gap-2 rounded-lg border
            border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
            <span className="text-[13px] text-[var(--text-main)] truncate">
              {employee.name} <span className="text-[var(--text-muted)]">({employee.employee_code})</span>
            </span>
            <button type="button" onClick={() => { setEmployee(null); setSearch(''); }}
              className="text-[11px] font-bold text-[var(--accent-indigo)] shrink-0">
              Change
            </button>
          </div>
        ) : (
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input id="sep-employee" value={search} placeholder="Search by name or employee code…"
              className={`${FIELD} pl-8`} onChange={(e) => setSearch(e.target.value)} />
            {(searching || options.length > 0) && (
              <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg
                border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
                {searching && (
                  <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Searching…</p>
                )}
                {!searching && options.map((o) => (
                  <button key={o.user_id} type="button"
                    onClick={() => { setEmployee(o); setOptions([]); }}
                    className="block w-full text-left px-3 py-2 text-[12.5px]
                      hover:bg-[var(--input-bg)]">
                    <span className="text-[var(--text-main)]">{o.name}</span>
                    <span className="block text-[11px] text-[var(--text-muted)]">
                      {o.employee_code} · {o.designation || '—'} · {o.employment_status}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div>
        <label className={LABEL} htmlFor="sep-type">Exit Type *</label>
        <select id="sep-type" value={exitType} className={FIELD}
          onChange={(e) => setExitType(e.target.value)}>
          {EXIT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="sep-date">Resignation / Event Date</label>
          <input id="sep-date" type="date" value={resignationDate} className={FIELD}
            onChange={(e) => setResignationDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="sep-lwd">Proposed LWD</label>
          <input id="sep-lwd" type="date" value={proposedLwd} className={FIELD}
            onChange={(e) => setProposedLwd(e.target.value)} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Leave blank to use the calculated notice date.
          </p>
        </div>
      </div>

      <div>
        <label className={LABEL} htmlFor="sep-reason">Reason</label>
        <textarea id="sep-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

export default SeparationBoard;
