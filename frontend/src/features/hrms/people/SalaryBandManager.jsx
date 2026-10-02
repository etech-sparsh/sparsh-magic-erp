import React, { useCallback, useEffect, useState } from 'react';
import { Scale, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getSalaryBands, createSalaryBand, updateSalaryBand,
  getDepartments, getDesignations,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ the standing salary-band master (Annexure C).
 *
 * "Pre-define standard salary bands per role/grade with Finance annually, so individual
 * requisitions don't need a fresh budget discussion each time."
 *
 * -- The screen says what the table IS, because the distinction is easy to lose ----------
 * These bands PRE-FILL the budget gate. They are not what an offer is checked against — that
 * is the band stamped on the requisition when its budget was approved. So editing a band
 * here cannot retroactively legalise (or criminalise) an offer approved last month, and the
 * page states that outright rather than leaving somebody to discover it.
 *
 * -- Figures are not editable; a band is superseded ---------------------------------------
 * There is deliberately no way to change a published band's numbers. Publishing a new band
 * for the same position supersedes the old one and records the succession, so what Finance
 * agreed last year still reads as what Finance agreed last year.
 *
 * Admin-only in the nav (`salary_band.write` is Finance and the MD); HR reads.
 */

const money = (value, currency) => {
  if (value == null) return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${currency || ''} ${n.toLocaleString()}`.trim();
};

const SalaryBandManager = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('Active');
  const [publishing, setPublishing] = useState(false);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.SALARY_BAND_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getSalaryBands({ ...scope, status: status || undefined });
      setRows(data?.salary_bands || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the salary bands.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status]);

  useEffect(() => { load(); }, [load]);

  const retire = async (band) => {
    setBusy(true);
    try {
      await updateSalaryBand(band.band_no, { status: 'Retired' }, scope);
      showSuccess(`${band.band_no} retired.`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'The band could not be retired.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    {
      key: 'position',
      label: 'Position',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.designation_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.department_name}{r.grade ? ` · grade ${r.grade}` : ''}
          </span>
        </>
      ),
    },
    {
      key: 'band',
      label: 'Band',
      render: (r) => (
        <span className="text-[var(--text-main)]">
          {money(r.min, r.currency)} – {money(r.max, r.currency)}
        </span>
      ),
    },
    {
      key: 'effective',
      label: 'Effective',
      render: (r) => (
        <>
          {day(r.effective_from)}
          {r.effective_to && (
            <span className="block text-[11px] text-[var(--text-muted)]">
              to {day(r.effective_to)}
            </span>
          )}
        </>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      render: (r) => (
        <Chip tone={r.status === 'Active' ? 'good' : 'neutral'}>{r.status}</Chip>
      ),
    },
    { key: 'by', label: 'Agreed by', render: (r) => r.approved_by_name },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => (canWrite && r.status === 'Active' ? (
        <Btn disabled={busy} onClick={() => retire(r)}>Retire</Btn>
      ) : null),
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Scale}
        title="Salary bands"
        subtitle="Standing bands agreed with Finance, so an individual requisition does not need a fresh budget discussion."
        actions={canWrite && (
          <Btn tone="primary" onClick={() => setPublishing(true)}>
            <Plus size={14} /> Publish a band
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {/* The one thing about this table that is genuinely counter-intuitive, said up front. */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)]
        px-4 py-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          These bands <strong className="text-[var(--text-main)]">pre-fill</strong> the
          budget-approval form. They are not what an offer is checked against — that is the
          band stamped on the requisition when its budget was approved. Changing a band here
          never changes a requisition that was already approved.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <label className={LABEL} htmlFor="band-status">Status</label>
        <select id="band-status" className={`${FIELD} w-auto`} value={status}
          onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="Active">Active</option>
          <option value="Superseded">Superseded</option>
          <option value="Retired">Retired</option>
        </select>
      </div>

      {loading && <HrmsLoading label="Loading salary bands…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Scale}
          title="No salary bands yet"
          hint="Publish one per role and grade so the budget gate has a figure to offer the approver."
        />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.band_no}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-[13px] text-[var(--text-main)]">
                    {r.designation_name}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    {r.department_name}{r.grade ? ` · grade ${r.grade}` : ''}
                  </p>
                </div>
                <Chip tone={r.status === 'Active' ? 'good' : 'neutral'}>{r.status}</Chip>
              </div>
              <Facts items={[
                { label: 'Band', value: `${money(r.min, r.currency)} – ${money(r.max, r.currency)}` },
                { label: 'From', value: day(r.effective_from) },
                { label: 'Agreed by', value: r.approved_by_name },
              ]} />
              {canWrite && r.status === 'Active' && (
                <Btn disabled={busy} onClick={() => retire(r)}>Retire</Btn>
              )}
            </div>
          )}
        />
      )}

      {publishing && (
        <PublishModal
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          onClose={() => setPublishing(false)}
          onDone={() => {
            setPublishing(false);
            load();
            showSuccess('Band published. Any previous band for this position is superseded.');
          }}
          onError={showError}
        />
      )}
    </div>
  );
};

const PublishModal = ({ scope, busy, setBusy, onClose, onDone, onError }) => {
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [form, setForm] = useState({
    department_id: '', designation_id: '', grade: '',
    min: '', max: '', currency: 'INR', effective_from: '', notes: '',
  });

  useEffect(() => {
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || data || []))
      .catch(() => setDepartments([]));
    getDesignations(scope)
      .then(({ data }) => setDesignations(data?.designations || data || []))
      .catch(() => setDesignations([]));
  }, [scope]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const ready = form.department_id && form.designation_id && form.min && form.max;

  const submit = async () => {
    setBusy(true);
    try {
      await createSalaryBand({
        ...form,
        min: Number(form.min),
        max: Number(form.max),
        effective_from: form.effective_from || undefined,
        grade: form.grade || undefined,
      }, scope);
      onDone();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The band could not be published.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Publish a salary band"
      subtitle="An existing active band for the same position is superseded, not overwritten."
      labelledBy="band-publish"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !ready} onClick={submit}>Publish</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="band-dept">Department *</label>
        <select id="band-dept" className={FIELD} value={form.department_id}
          onChange={set('department_id')}>
          <option value="">Choose a department</option>
          {departments.map((d) => (
            <option key={d.id || d._id} value={d.id || d._id}>{d.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={LABEL} htmlFor="band-desig">Designation *</label>
        <select id="band-desig" className={FIELD} value={form.designation_id}
          onChange={set('designation_id')}>
          <option value="">Choose a designation</option>
          {designations.map((d) => (
            <option key={d.id || d._id} value={d.id || d._id}>{d.name}</option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="band-min">Minimum *</label>
          <input id="band-min" type="number" min="0" className={FIELD}
            value={form.min} onChange={set('min')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="band-max">Maximum *</label>
          <input id="band-max" type="number" min="0" className={FIELD}
            value={form.max} onChange={set('max')} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="band-grade">Grade</label>
          <input id="band-grade" className={FIELD} value={form.grade}
            onChange={set('grade')} placeholder="Your own grade label, if you use one" />
        </div>
        <div>
          <label className={LABEL} htmlFor="band-from">Effective from</label>
          <input id="band-from" type="date" className={FIELD} value={form.effective_from}
            onChange={set('effective_from')} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="band-notes">Notes</label>
        <textarea id="band-notes" rows={3} className={TEXTAREA} value={form.notes}
          onChange={set('notes')}
          placeholder="What this band reflects — a market review, an annual settlement." />
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        The figures cannot be edited after publishing. If they change, publish a new band —
        this one is superseded and the requisitions approved against it keep citing what was
        actually agreed.
      </p>
    </Modal>
  );
};

export default SalaryBandManager;
