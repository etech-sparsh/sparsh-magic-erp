import React, { useCallback, useEffect, useState } from 'react';
import { GitBranch, Search, ShieldAlert, UserX, Clock4 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import BoardTabs from '../common/BoardTabs';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees, getDesignations,
  initiateMovement, getMovements, actOnMovement,
  createDisciplineCase, getDisciplineCases, getDisciplineCase,
  addDisciplineInvestigationNote, recordDisciplineRecommendation, decideDisciplineCase,
  closeDisciplineCase,
  getAbscondingPolicy, saveAbscondingPolicy, flagAbscondingCase, getAbscondingCases,
  getAbscondingCase, logAbscondingContact, sendAbscondingWarning, absconderFinalAction,
  getRetirementPolicy, saveRetirementPolicy, getUpcomingRetirements,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Employee Movements & Discipline (BA/Functional Design §7.16, §7.17, §7.19, §7.20).
 *
 * Four tabs over four related but distinct workflows, the same shape AttendanceBoard and
 * LeaveBoard already use for the same reason: none of these is a single case with its own
 * URL worth a separate route. Retirement/Demise/Missing (§7.20) is deliberately the
 * thinnest tab — it is a read-only alert, because the BA doc itself says the retirement age
 * is unconfirmed and the rest of that workflow already runs through Exit Management.
 */

const TABS = ['Movements', 'Discipline', 'Absconding', 'Retirement Alerts'];

const MOVEMENT_TYPES = ['Promotion', 'Transfer', 'Manager Change', 'Designation Change',
  'Grade Change', 'Location Change', 'Compensation Change'];
const DESIGNATION_TYPES = new Set(['Promotion', 'Designation Change']);

const DISCIPLINE_CATEGORIES = ['Misconduct', 'Attendance', 'Insubordination', 'Harassment',
  'POSH', 'Policy Violation', 'Other'];
const POSH_CATEGORIES = new Set(['Harassment', 'POSH']);

const EmployeePicker = ({ scope, value, onChange, placeholder }) => {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (!debounced.trim() || value) return;
    let live = true;
    Promise.resolve().then(() => { if (live) setSearching(true); });
    getEmployees({ ...scope, search: debounced, limit: 8 })
      .then(({ data }) => { if (live) setOptions(data?.employees || []); })
      .catch(() => { if (live) setOptions([]); })
      .finally(() => { if (live) setSearching(false); });
    return () => { live = false; };
  }, [debounced, value, scope]);

  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border
        border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
        <span className="text-[13px] text-[var(--text-main)] truncate">
          {value.name} <span className="text-[var(--text-muted)]">({value.employee_code})</span>
        </span>
        <button type="button" onClick={() => { onChange(null); setSearch(''); }}
          className="text-[11px] font-bold text-[var(--accent-indigo)] shrink-0">
          Change
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
      <input value={search} placeholder={placeholder || 'Search by name or employee code…'}
        className={`${FIELD} pl-8`} onChange={(e) => setSearch(e.target.value)} />
      {(searching || options.length > 0) && (
        <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg
          border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
          {searching && <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Searching…</p>}
          {!searching && options.map((o) => (
            <button key={o.user_id} type="button"
              onClick={() => { onChange(o); setOptions([]); }}
              className="block w-full text-left px-3 py-2 text-[12.5px] hover:bg-[var(--input-bg)]">
              <span className="text-[var(--text-main)]">{o.name}</span>
              <span className="block text-[11px] text-[var(--text-muted)]">
                {o.employee_code} · {o.designation || '—'} · {o.employment_status}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      const res = await fn();
      if (successMsg) showSuccess(successMsg);
      onDone(res);
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const MovementsBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState('Movements');

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={GitBranch}
        title="Employee Movements & Discipline"
        subtitle="Promotions, transfers and compensation changes; discipline, absconding and retirement alerts."
      />
      <HrmsScopeBar />

      <BoardTabs tabs={TABS} value={tab} onChange={setTab} label="Movements sections" />

      {tab === 'Movements' && (
        <MovementsTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Discipline' && (
        <DisciplineTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Absconding' && (
        <AbscondingTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Retirement Alerts' && (
        <RetirementTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ── Movements tab ──
const MovementsTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [proposing, setProposing] = useState(false);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getMovements({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load movements.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.move_no} · {r.movement_type}</span>
      </>
    ) },
    { key: 'change', label: 'Change', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.current_value || '—'} → {r.proposed_value}
      </span>
    ) },
    { key: 'effective', label: 'Effective', render: (r) => (
      <span className="text-[var(--text-main)]">{day(r.effective_date)}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.MOVEMENT_APPROVE) && r.status === 'Pending' && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.move_no} · {r.movement_type}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Change', value: `${r.current_value || '—'} → ${r.proposed_value}` },
        { label: 'Effective', value: day(r.effective_date) },
        { label: 'Reason', value: r.reason },
      ]} />
      {can(CAP.MOVEMENT_APPROVE) && r.status === 'Pending' && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.MOVEMENT_INITIATE) && (
          <Btn tone="primary" onClick={() => setProposing(true)}>
            <GitBranch size={14} /> Propose Movement
          </Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading movements…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.move_no} />
        ) : (
          <HrmsEmpty icon={GitBranch} title="No movements recorded yet" />
        )
      )}
      {proposing && (
        <ProposeMovementModal scope={scope} onClose={() => setProposing(false)}
          onDone={() => { setProposing(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <MovementActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const ProposeMovementModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [movementType, setMovementType] = useState(MOVEMENT_TYPES[0]);
  const [designations, setDesignations] = useState([]);
  const [designationId, setDesignationId] = useState('');
  const [newManager, setNewManager] = useState(null);
  const [freeValue, setFreeValue] = useState('');
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    if (DESIGNATION_TYPES.has(movementType) && designations.length === 0) {
      getDesignations(scope)
        .then(({ data }) => setDesignations(data?.designations || []))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [movementType]);

  const toValue = () => {
    if (DESIGNATION_TYPES.has(movementType)) return designationId;
    if (movementType === 'Manager Change') return newManager?.user_id;
    return freeValue;
  };

  const submit = () => {
    const value = toValue();
    if (!employee || !value) { showError('Select the employee and the proposed value.'); return; }
    run(() => initiateMovement({
      employee_code: employee.employee_code, movement_type: movementType,
      to_value: value, effective_date: effectiveDate, reason: reason.trim() || undefined,
    }, scope), 'Movement proposed.');
  };

  return (
    <Modal title="Propose Movement" labelledBy="move-title"
      subtitle="The current value is looked up automatically; only the change and reason are entered here."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Propose'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="move-type">Movement Type *</label>
        <select id="move-type" value={movementType} className={FIELD}
          onChange={(e) => { setMovementType(e.target.value); setDesignationId(''); setNewManager(null); setFreeValue(''); }}>
          {MOVEMENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      {DESIGNATION_TYPES.has(movementType) && (
        <div>
          <label className={LABEL} htmlFor="move-designation">Proposed Designation *</label>
          <select id="move-designation" value={designationId} className={FIELD}
            onChange={(e) => setDesignationId(e.target.value)}>
            <option value="">— select —</option>
            {designations.map((d) => <option key={d._id || d.id} value={d._id || d.id}>{d.name}</option>)}
          </select>
        </div>
      )}
      {movementType === 'Manager Change' && (
        <div>
          <label className={LABEL}>New Reporting Manager *</label>
          <EmployeePicker scope={scope} value={newManager} onChange={setNewManager}
            placeholder="Search for the new manager…" />
        </div>
      )}
      {!DESIGNATION_TYPES.has(movementType) && movementType !== 'Manager Change' && (
        <div>
          <label className={LABEL} htmlFor="move-value">
            {movementType === 'Compensation Change' ? 'Proposed Monthly Salary *' : 'Proposed Value *'}
          </label>
          <input id="move-value" value={freeValue} className={FIELD}
            type={movementType === 'Compensation Change' ? 'number' : 'text'}
            onChange={(e) => setFreeValue(e.target.value)} />
        </div>
      )}
      <div>
        <label className={LABEL} htmlFor="move-date">Effective Date *</label>
        <input id="move-date" type="date" value={effectiveDate} className={FIELD}
          onChange={(e) => setEffectiveDate(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="move-reason">Reason</label>
        <textarea id="move-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

const MovementActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const act = (approved) => run(
    () => actOnMovement(row.move_no, { approved, remarks: remarks.trim() || undefined }, scope),
    approved ? `${row.move_no} approved.` : `${row.move_no} rejected.`);

  return (
    <Modal title={`Act on ${row.move_no}`} labelledBy="move-act-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => act(false)} disabled={busy}>Reject</Btn>
          <Btn tone="primary" onClick={() => act(true)} disabled={busy}>
            {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Employee', value: row.employee_name || row.employee_code },
        { label: 'Type', value: row.movement_type },
        { label: 'Change', value: `${row.current_value || '—'} → ${row.proposed_value}` },
        { label: 'Effective', value: day(row.effective_date) },
      ]} />
      <div>
        <label className={LABEL} htmlFor="move-act-remarks">Remarks</label>
        <textarea id="move-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Discipline tab ──
const DisciplineTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [openCaseNo, setOpenCaseNo] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getDisciplineCases({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load discipline cases.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'case', label: 'Case', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.case_no}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.category}</span>
      </>
    ) },
    { key: 'confidentiality', label: 'Confidentiality', render: (r) => (
      <Chip tone={attLeaveToneFor(r.confidentiality_level)}>{r.confidentiality_level}</Chip>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenCaseNo(r.case_no)}>Open</Btn>
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.case_no}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.category}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Chip tone={attLeaveToneFor(r.confidentiality_level)}>{r.confidentiality_level}</Chip>
      <Btn tone="ghost" onClick={() => setOpenCaseNo(r.case_no)}>Open</Btn>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.DISCIPLINE_MANAGE) && (
          <Btn tone="primary" onClick={() => setCreating(true)}>
            <ShieldAlert size={14} /> Create Case
          </Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading discipline cases…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.case_no} />
        ) : (
          <HrmsEmpty icon={ShieldAlert} title="No discipline cases"
            hint="Restricted (POSH/Harassment) cases outside your access simply do not appear here." />
        )
      )}
      {creating && (
        <CreateCaseModal scope={scope} onClose={() => setCreating(false)}
          onDone={() => { setCreating(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openCaseNo && (
        <CaseDetailModal caseNo={openCaseNo} scope={scope} can={can}
          onClose={() => setOpenCaseNo(null)}
          onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const CreateCaseModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [category, setCategory] = useState(DISCIPLINE_CATEGORIES[0]);
  const [respondent, setRespondent] = useState(null);
  const [complainant, setComplainant] = useState(null);
  const [description, setDescription] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!respondent || !description.trim()) {
      showError('Select the respondent and describe the case.');
      return;
    }
    const persons = [{ employee_code: respondent.employee_code, role: 'Respondent' }];
    if (complainant) persons.push({ employee_code: complainant.employee_code, role: 'Complainant' });
    run(() => createDisciplineCase({
      category, persons_involved: persons, description: description.trim(),
    }, scope), 'Case created.');
  };

  return (
    <Modal title="Create Discipline Case" labelledBy="disc-create-title"
      subtitle={POSH_CATEGORIES.has(category)
        ? 'POSH/Harassment cases are always Restricted — visible only to those with POSH access.'
        : 'Standard confidentiality — visible to Discipline access holders.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !respondent}>
            {busy ? 'Working…' : 'Create'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="disc-category">Category *</label>
        <select id="disc-category" value={category} className={FIELD}
          onChange={(e) => setCategory(e.target.value)}>
          {DISCIPLINE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div>
        <label className={LABEL}>Respondent *</label>
        <EmployeePicker scope={scope} value={respondent} onChange={setRespondent} />
      </div>
      <div>
        <label className={LABEL}>Complainant (optional)</label>
        <EmployeePicker scope={scope} value={complainant} onChange={setComplainant} />
      </div>
      <div>
        <label className={LABEL} htmlFor="disc-description">Description *</label>
        <textarea id="disc-description" rows={3} value={description} className={TEXTAREA}
          onChange={(e) => setDescription(e.target.value)} />
      </div>
    </Modal>
  );
};

const CaseDetailModal = ({ caseNo, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [note, setNote] = useState('');
  const [recommendation, setRecommendation] = useState('');
  const [outcome, setOutcome] = useState('Warning');
  const [decisionRemarks, setDecisionRemarks] = useState('');
  const [retention, setRetention] = useState('3 years');
  // Reload from the GET rather than trusting the mutation's own response shape (`run` hands
  // back the raw axios response, not its unwrapped `.data`) — the same reload-after-write
  // pattern AttendanceBoard/LeaveBoard use throughout, so `detail` is never a step behind.
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getDisciplineCase(caseNo, scope);
      setDetail(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this case.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseNo]);

  useEffect(() => { load(); }, [load]);

  return (
    <Modal title={caseNo} labelledBy="disc-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading case…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && detail && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Chip tone={attLeaveToneFor(detail.confidentiality_level)}>{detail.confidentiality_level}</Chip>
            <Chip tone={attLeaveToneFor(detail.status)}>{detail.status}</Chip>
          </div>
          <Facts items={[
            { label: 'Category', value: detail.category },
            { label: 'Description', value: detail.description },
            { label: 'Persons Involved', value: (detail.persons_involved || [])
              .map((p) => `${p.name || p.employee_code} (${p.role})`).join(', ') },
            { label: 'Recommendation', value: detail.recommendation },
            { label: 'Outcome', value: detail.outcome },
          ]} />

          {detail.status !== 'Closed' && can(CAP.DISCIPLINE_MANAGE) && (
            <>
              <div>
                <label className={LABEL} htmlFor="disc-note">Investigation Note</label>
                <div className="flex gap-2">
                  <textarea id="disc-note" rows={2} value={note} className={TEXTAREA}
                    onChange={(e) => setNote(e.target.value)} />
                  <Btn disabled={busy || !note.trim()} onClick={() => run(
                    () => addDisciplineInvestigationNote(caseNo, { note: note.trim() }, scope),
                    'Note added.')}>Add</Btn>
                </div>
              </div>
              <div>
                <label className={LABEL} htmlFor="disc-recommendation">Recommendation</label>
                <div className="flex gap-2">
                  <textarea id="disc-recommendation" rows={2} value={recommendation}
                    className={TEXTAREA} onChange={(e) => setRecommendation(e.target.value)} />
                  <Btn disabled={busy || !recommendation.trim()} onClick={() => run(
                    () => recordDisciplineRecommendation(
                      caseNo, { recommendation: recommendation.trim() }, scope),
                    'Recommendation recorded.')}>Record</Btn>
                </div>
              </div>
            </>
          )}

          {['Under Investigation', 'Recommendation Recorded'].includes(detail.status)
            && can(CAP.DISCIPLINE_DECIDE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Management Decision</p>
              <select value={outcome} className={FIELD} onChange={(e) => setOutcome(e.target.value)}>
                {['Warning', 'Censure', 'Show Cause', 'Termination', 'No Action', 'Other'].map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
              <textarea rows={2} value={decisionRemarks} className={TEXTAREA}
                placeholder="Remarks" onChange={(e) => setDecisionRemarks(e.target.value)} />
              <Btn tone="primary" disabled={busy} onClick={() => run(
                () => decideDisciplineCase(caseNo,
                  { outcome, remarks: decisionRemarks.trim() || undefined }, scope),
                'Decision recorded.')}>
                {busy ? 'Working…' : 'Record Decision'}
              </Btn>
            </div>
          )}

          {detail.status === 'Decided' && can(CAP.DISCIPLINE_MANAGE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Close Case</p>
              <input value={retention} className={FIELD} placeholder="Retention classification"
                onChange={(e) => setRetention(e.target.value)} />
              <Btn tone="primary" disabled={busy} onClick={() => run(
                () => closeDisciplineCase(caseNo, { retention_classification: retention }, scope),
                'Case closed.')}>
                {busy ? 'Working…' : 'Close Case'}
              </Btn>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

// ── Absconding tab ──
const AbscondingTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [flagging, setFlagging] = useState(false);
  const [openCaseNo, setOpenCaseNo] = useState(null);
  const [editingPolicy, setEditingPolicy] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [{ data }, { data: pol }] = await Promise.all([
        getAbscondingCases({ ...scope, limit: 100 }), getAbscondingPolicy(scope),
      ]);
      setRows(data || []);
      setPolicy(pol);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load absconding cases.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.case_no} · since {day(r.flagged_date)}</span>
      </>
    ) },
    { key: 'contacts', label: 'Contacts', render: (r) => (
      <span className="text-[var(--text-main)]">{(r.contact_attempts || []).length}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenCaseNo(r.case_no)}>Open</Btn>
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.case_no} · since {day(r.flagged_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Btn tone="ghost" onClick={() => setOpenCaseNo(r.case_no)}>Open</Btn>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-[var(--text-muted)]">
          {policy ? `Flag after ${policy.unexplained_absence_days} unexplained day(s); each
          warning window is ${policy.warning_window_days} day(s).` : ''}
        </p>
        <div className="flex gap-2">
          {can(CAP.ABSCONDING_MANAGE) && (
            <Btn tone="ghost" onClick={() => setEditingPolicy(true)}>Edit Policy</Btn>
          )}
          {can(CAP.ABSCONDING_MANAGE) && (
            <Btn tone="primary" onClick={() => setFlagging(true)}>
              <UserX size={14} /> Flag Absconding
            </Btn>
          )}
        </div>
      </div>
      {loading && <HrmsLoading label="Loading absconding cases…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.case_no} />
        ) : (
          <HrmsEmpty icon={UserX} title="No absconding cases" />
        )
      )}
      {flagging && (
        <FlagAbscondingModal scope={scope} onClose={() => setFlagging(false)}
          onDone={() => { setFlagging(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openCaseNo && (
        <AbscondingDetailModal caseNo={openCaseNo} scope={scope} can={can}
          onClose={() => setOpenCaseNo(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
      {editingPolicy && (
        <AbscondingPolicyModal policy={policy} scope={scope} onClose={() => setEditingPolicy(false)}
          onDone={() => { setEditingPolicy(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const AbscondingPolicyModal = ({ policy, scope, onClose, onDone, showSuccess, showError }) => {
  const [absenceDays, setAbsenceDays] = useState(policy?.unexplained_absence_days ?? 3);
  const [windowDays, setWindowDays] = useState(policy?.warning_window_days ?? 7);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => run(() => saveAbscondingPolicy({
    unexplained_absence_days: Number(absenceDays), warning_window_days: Number(windowDays),
  }, scope), 'Absconding policy saved.');

  return (
    <Modal title="Absconding Policy" labelledBy="absc-policy-title"
      subtitle="§7.19 — adjustable defaults, not a frozen rule." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="absc-pol-days">Unexplained Absence Days (before flagging)</label>
        <input id="absc-pol-days" type="number" min="1" value={absenceDays} className={FIELD}
          onChange={(e) => setAbsenceDays(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="absc-pol-window">Warning Window (days)</label>
        <input id="absc-pol-window" type="number" min="1" value={windowDays} className={FIELD}
          onChange={(e) => setWindowDays(e.target.value)} />
      </div>
    </Modal>
  );
};

const FlagAbscondingModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [flaggedDate, setFlaggedDate] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee) { showError('Select the employee.'); return; }
    run(() => flagAbscondingCase({
      employee_code: employee.employee_code, flagged_date: flaggedDate,
      notes: notes.trim() || undefined,
    }, scope), 'Absconding case flagged.');
  };

  return (
    <Modal title="Flag Absconding" labelledBy="absc-flag-title"
      subtitle="3 consecutive unexplained working days without acceptable communication (§7.19)."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Flag'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="absc-date">Unexplained Since *</label>
        <input id="absc-date" type="date" value={flaggedDate} className={FIELD}
          onChange={(e) => setFlaggedDate(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="absc-notes">Notes</label>
        <textarea id="absc-notes" rows={2} value={notes} className={TEXTAREA}
          onChange={(e) => setNotes(e.target.value)} />
      </div>
    </Modal>
  );
};

const AbscondingDetailModal = ({ caseNo, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [method, setMethod] = useState('Call');
  const [outcome, setOutcome] = useState('');
  const [finalRemarks, setFinalRemarks] = useState('');
  // Reload from the GET rather than trusting the mutation's own response shape (`run` hands
  // back the raw axios response, not its unwrapped `.data`) — the same reload-after-write
  // pattern AttendanceBoard/LeaveBoard use throughout, so `detail` is never a step behind.
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getAbscondingCase(caseNo, scope);
      setDetail(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this case.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseNo]);

  useEffect(() => { load(); }, [load]);

  const openStatuses = ['Flagged', 'First Warning Sent', 'Second Warning Sent', 'Final Action'];

  return (
    <Modal title={caseNo} labelledBy="absc-detail-title" onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading case…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && detail && (
        <div className="space-y-4">
          <Chip tone={attLeaveToneFor(detail.status)}>{detail.status}</Chip>
          <Facts items={[
            { label: 'Employee', value: detail.employee_name || detail.employee_code },
            { label: 'Unexplained Since', value: day(detail.flagged_date) },
            { label: 'Contact Attempts', value: (detail.contact_attempts || []).length },
            { label: 'Linked Separation', value: detail.linked_sep_no },
          ]} />

          {openStatuses.includes(detail.status) && can(CAP.ABSCONDING_MANAGE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Log Contact Attempt</p>
              <select value={method} className={FIELD} onChange={(e) => setMethod(e.target.value)}>
                {['Call', 'Email', 'Letter', 'Other'].map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <input value={outcome} className={FIELD} placeholder="Outcome"
                onChange={(e) => setOutcome(e.target.value)} />
              <Btn disabled={busy} onClick={() => run(
                () => logAbscondingContact(caseNo, { method, outcome: outcome.trim() || undefined }, scope),
                'Contact attempt logged.')}>
                {busy ? 'Working…' : 'Log Contact'}
              </Btn>
            </div>
          )}

          {detail.status === 'Flagged' && can(CAP.ABSCONDING_MANAGE) && (
            <Btn disabled={busy} onClick={() => run(
              () => sendAbscondingWarning(caseNo, 'First', {}, scope), 'First Warning sent.')}>
              Send First Warning
            </Btn>
          )}
          {detail.status === 'First Warning Sent' && can(CAP.ABSCONDING_MANAGE) && (
            <Btn disabled={busy} onClick={() => run(
              () => sendAbscondingWarning(caseNo, 'Second', {}, scope), 'Second Warning sent.')}>
              Send Second Warning
            </Btn>
          )}

          {['Second Warning Sent', 'Final Action'].includes(detail.status)
            && can(CAP.ABSCONDING_DECIDE) && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <p className={LABEL}>Final Action</p>
              <textarea rows={2} value={finalRemarks} className={TEXTAREA} placeholder="Remarks"
                onChange={(e) => setFinalRemarks(e.target.value)} />
              <div className="flex gap-2">
                <Btn disabled={busy} onClick={() => run(
                  () => absconderFinalAction(caseNo,
                    { resolution: 'Returned to Work', remarks: finalRemarks.trim() || undefined }, scope),
                  'Marked returned to work.')}>
                  Returned to Work
                </Btn>
                <Btn tone="danger" disabled={busy} onClick={() => run(
                  () => absconderFinalAction(caseNo,
                    { resolution: 'Converted to Separation', remarks: finalRemarks.trim() || undefined }, scope),
                  'Converted to a separation case.')}>
                  Convert to Separation
                </Btn>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

// ── Retirement Alerts tab ──
const RetirementTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingPolicy, setEditingPolicy] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [{ data: upcoming }, { data: pol }] = await Promise.all([
        getUpcomingRetirements(scope), getRetirementPolicy(scope),
      ]);
      setRows(upcoming || []);
      setPolicy(pol);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load retirement alerts.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      {policy && !policy.policy_confirmed && (
        <div className="rounded-xl border border-[var(--accent-orange-bg)] bg-[var(--accent-orange-bg)]
          p-3.5 text-[12px] text-[var(--accent-orange)]">
          Retirement age ({policy.retirement_age}) is an adjustable DEFAULT, not the client's
          confirmed policy — §7.20 leaves the exact age unconfirmed.
        </div>
      )}
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-[var(--text-muted)]">
          Alerting {policy?.alert_months_ahead ?? '—'} months ahead of a {policy?.retirement_age ?? '—'}-year
          retirement age.
        </p>
        {can(CAP.MOVEMENT_APPROVE) && (
          <Btn tone="ghost" onClick={() => setEditingPolicy(true)}>Edit Policy</Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading retirement alerts…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList
            rows={rows}
            columns={[
              { key: 'who', label: 'Employee', render: (r) => (
                <span className="font-semibold text-[var(--text-main)]">{r.display_name || r.employee_code}</span>
              ) },
              { key: 'dob', label: 'Date of Birth', render: (r) => <span>{day(r.date_of_birth)}</span> },
              { key: 'retirement', label: 'Retirement Date', align: 'right',
                render: (r) => <span className="font-semibold">{day(r.retirement_date)}</span> },
            ]}
            renderCard={(r) => (
              <Facts items={[
                { label: 'Employee', value: r.display_name || r.employee_code },
                { label: 'Date of Birth', value: day(r.date_of_birth) },
                { label: 'Retirement Date', value: day(r.retirement_date) },
              ]} />
            )}
            keyOf={(r) => r.employee_code}
          />
        ) : (
          <HrmsEmpty icon={Clock4} title="No upcoming retirements in the alert window" />
        )
      )}
      {editingPolicy && (
        <RetirementPolicyModal policy={policy} scope={scope} onClose={() => setEditingPolicy(false)}
          onDone={() => { setEditingPolicy(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const RetirementPolicyModal = ({ policy, scope, onClose, onDone, showSuccess, showError }) => {
  const [age, setAge] = useState(policy?.retirement_age ?? 60);
  const [months, setMonths] = useState(policy?.alert_months_ahead ?? 6);
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => run(() => saveRetirementPolicy({
    retirement_age: Number(age), alert_months_ahead: Number(months),
  }, scope), 'Retirement policy saved.');

  return (
    <Modal title="Retirement Alert Policy" labelledBy="ret-policy-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="ret-age">Retirement Age</label>
        <input id="ret-age" type="number" min="1" value={age} className={FIELD}
          onChange={(e) => setAge(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="ret-months">Alert Months Ahead</label>
        <input id="ret-months" type="number" min="1" value={months} className={FIELD}
          onChange={(e) => setMonths(e.target.value)} />
      </div>
    </Modal>
  );
};

export default MovementsBoard;
