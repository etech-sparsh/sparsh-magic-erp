import React, { useCallback, useEffect, useState } from 'react';
import { HeartPulse, Settings2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getPulseConfig, savePulseConfig, getPulseSummary, listPulseSurveys, getPulseSurvey,
  submitPulseSurvey,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, toneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ 30/90-Day Pulse Survey (BA/Functional Design §22.4, screen SM-HR-058).
 *
 * Deliberately IDENTIFIABLE — unlike the existing (anonymous) induction/probation survey
 * module elsewhere in this app, a pulse response is shown per-employee here on purpose,
 * gated on the separate PULSE_READ/MANAGE/SUBMIT capabilities. See the backend Cap enum's
 * own comment for the reasoning.
 *
 * Surveys are issued automatically (a daily job anchored to date of joining); there is no
 * "create" action here — only configuring the questions, submitting one's own, and HR/MD
 * reviewing the completion-rate/average-score summary.
 */
const PulseSurveyBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  const [configuring, setConfiguring] = useState(false);
  const [openRow, setOpenRow] = useState(null);

  const canManage = can(CAP.PULSE_MANAGE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listPulseSurveys({ ...scope, limit: 100 });
      setRows(data?.surveys || []);
      if (canManage) {
        getPulseSummary(scope).then(({ data: s }) => setSummary(s)).catch(() => {});
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load pulse surveys.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, canManage]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
    ) },
    { key: 'milestone', label: 'Milestone', render: (r) => (
      <span className="text-[var(--text-main)]">{r.milestone}-day</span>
    ) },
    { key: 'average', label: 'Average', render: (r) => (
      <span className="text-[var(--text-main)]">{r.average != null ? r.average.toFixed(1) : '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <div className="flex gap-1.5">
          {r.follow_up_required && <Chip tone="bad">Follow-up</Chip>}
          <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        </div>
        <Btn tone="ghost" onClick={() => setOpenRow(r)}>Open</Btn>
      </div>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={HeartPulse}
        title="30/90-Day Surveys"
        subtitle="30/90-day onboarding check-ins, issued automatically from date of joining (SM-HR-058)."
        actions={canManage && (
          <Btn tone="ghost" onClick={() => setConfiguring(true)}>
            <Settings2 size={14} /> Questions
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {canManage && summary && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {['30', '90'].map((m) => (
            <div key={m} className="rounded-xl border border-[var(--border)] p-3.5">
              <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                {m}-Day Milestone
              </p>
              <div className="mt-2 flex items-baseline gap-4">
                <div>
                  <p className="text-[18px] font-bold text-[var(--text-main)]">
                    {summary[m]?.submitted ?? 0}/{summary[m]?.issued ?? 0}
                  </p>
                  <p className="text-[10.5px] text-[var(--text-muted)]">completed</p>
                </div>
                <div>
                  <p className="text-[18px] font-bold text-[var(--text-main)]">
                    {summary[m]?.average_score != null ? summary[m].average_score.toFixed(1) : '—'}
                  </p>
                  <p className="text-[10.5px] text-[var(--text-muted)]">avg score</p>
                </div>
                {summary[m]?.follow_ups_open > 0 && (
                  <Chip tone="bad">{summary[m].follow_ups_open} follow-up(s)</Chip>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {loading && <HrmsLoading label="Loading pulse surveys…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">{r.milestone}-day</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    {r.follow_up_required && <Chip tone="bad">Follow-up</Chip>}
                    <Chip tone={toneFor(r.status)}>{r.status}</Chip>
                  </div>
                </div>
                <Btn tone="ghost" onClick={() => setOpenRow(r)}>Open</Btn>
              </div>
            )}
            keyOf={(r) => `${r.employee_code}:${r.milestone}`} />
        ) : (
          <HrmsEmpty icon={HeartPulse} title="No pulse surveys yet"
            hint="Issued automatically once an employee reaches 30 or 90 days since joining." />
        )
      )}

      {configuring && (
        <ConfigModal scope={scope} onClose={() => setConfiguring(false)}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openRow && (
        <SurveyDetailModal row={openRow} scope={scope} can={can}
          onClose={() => setOpenRow(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const ConfigModal = ({ scope, onClose, showSuccess, showError }) => {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!scope.company_id) { setLoading(false); return; }
    getPulseConfig(scope)
      .then(({ data }) => setText((data?.questions || []).join('\n')))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load questions.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  const submit = async () => {
    const questions = text.split('\n').map((q) => q.trim()).filter(Boolean);
    if (!questions.length) { showError('At least one question is required.'); return; }
    setSaving(true);
    try {
      await savePulseConfig(questions, scope);
      showSuccess('Questions saved.');
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the questions.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Pulse Survey Questions" labelledBy="pulse-config-title"
      subtitle="One question per line — asked at both the 30-day and 90-day check-in."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={saving}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={saving || loading}>
            {saving ? 'Saving…' : 'Save'}
          </Btn>
        </>
      )}
    >
      {loading ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
      ) : (
        <textarea rows={6} value={text} className={TEXTAREA}
          onChange={(e) => setText(e.target.value)} />
      )}
    </Modal>
  );
};

const SurveyDetailModal = ({ row, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [scores, setScores] = useState({});
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getPulseSurvey(row.employee_code, row.milestone, scope);
      setDetail(data);
      if (data.status === 'Issued') {
        const { data: cfg } = await getPulseConfig(scope);
        setQuestions(cfg?.questions || []);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this survey.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.employee_code, row.milestone]);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    const answered = Object.keys(scores).length;
    if (!answered) { showError('Please answer at least one question.'); return; }
    setBusy(true);
    try {
      await submitPulseSurvey(row.employee_code, row.milestone, { scores, comment: comment.trim() || undefined }, scope);
      showSuccess('Survey submitted — thank you.');
      onDone();
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not submit this survey.');
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = can(CAP.PULSE_SUBMIT) && detail?.status === 'Issued';

  return (
    <Modal title={`${row.employee_name || row.employee_code} · ${row.milestone}-day`}
      labelledBy="pulse-detail-title" onClose={onClose}
      footer={canSubmit ? (
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Submitting…' : 'Submit'}</Btn>
        </>
      ) : <Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <HrmsLoading label="Loading…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && detail && (
        canSubmit ? (
          <div className="space-y-3">
            <p className="text-[12.5px] text-[var(--text-muted)]">
              Rate each question from 1 (poor) to 5 (excellent).
            </p>
            {questions.map((q) => (
              <div key={q}>
                <label className={LABEL}>{q}</label>
                <div className="flex gap-1.5">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button key={n} type="button"
                      onClick={() => setScores((s) => ({ ...s, [q]: n }))}
                      className={`h-9 w-9 rounded-lg border text-[13px] font-bold ${
                        scores[q] === n
                          ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]'
                          : 'border-[var(--border)] text-[var(--text-main)]'
                      }`}>
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <div>
              <label className={LABEL} htmlFor="pulse-comment">Anything else you'd like to share?</label>
              <textarea id="pulse-comment" rows={2} value={comment} className={TEXTAREA}
                onChange={(e) => setComment(e.target.value)} />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <Chip tone={toneFor(detail.status)}>{detail.status}</Chip>
            {detail.status === 'Submitted' ? (
              <>
                <Facts items={[
                  { label: 'Average', value: detail.average != null ? detail.average.toFixed(1) : '—' },
                  { label: 'Submitted', value: detail.submitted_at?.slice(0, 10) },
                ]} />
                {Object.entries(detail.scores || {}).map(([q, v]) => (
                  <div key={q} className="flex items-center justify-between text-[12.5px]">
                    <span className="text-[var(--text-main)]">{q}</span>
                    <span className="font-bold text-[var(--text-main)]">{v}</span>
                  </div>
                ))}
                {detail.comment && (
                  <p className="text-[12.5px] text-[var(--text-muted)] italic">"{detail.comment}"</p>
                )}
              </>
            ) : (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Waiting for the employee to complete this survey.
              </p>
            )}
          </div>
        )
      )}
    </Modal>
  );
};

export default PulseSurveyBoard;
