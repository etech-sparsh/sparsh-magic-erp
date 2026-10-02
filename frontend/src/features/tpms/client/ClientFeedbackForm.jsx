import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Save, RefreshCw, User, ClipboardList, CheckCircle2, Lock } from 'lucide-react';
import { DashboardHero, Section } from '../common/dashboardKit';
import { useNotification } from '../../../context/NotificationContext';
import { useAuth } from '../../../context/AuthContext';
import { getFormDefinitions, getFeedback, submitFeedback } from '../../../services/tpmsFormsApi';

/**
 * Client-side Yes/No checklist (Implementation Update Feedback), self-service.
 *
 * Every client-side user submits their OWN response — no company/MD selectors. Partial
 * submission is preserved: previously-saved answers come back locked with a YES/NO tag;
 * a slot is submitted only if ticked OR has a remark. The backend scopes to the caller.
 */

const defaultPeriod = (now) => {
  const d = now || new Date();
  const mon = d.toLocaleString('en-US', { month: 'short' }).toLowerCase();
  return `${mon}${String(d.getFullYear()).slice(-2)}`;
};

// Convert a ?period= query value to the form's token format. A 'YYYY-MM' value
// (from "My Forms") is mapped to the same "jul26" token defaultPeriod() emits;
// a value already in the form's format is accepted as-is. Blank/unknown → null.
const periodFromParam = (raw) => {
  const v = (raw || '').trim();
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})$/.exec(v);
  if (m) return defaultPeriod(new Date(Number(m[1]), Number(m[2]) - 1, 1));
  return v;
};

// `lockedPeriod` / `onSubmitted` are supplied when this form is opened from a mailed
// assignment link (/f/<token>): the period comes from the assignment rather than a query
// param, and the callback lets the caller mark that assignment submitted. Both are
// optional — rendered any other way the component behaves exactly as before.
const ClientFeedbackForm = ({ formType, icon, lockedPeriod = '', onSubmitted }) => {
  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();

  const companyId = user?.company_id || '';
  const selfId = String(user?._id || user?.id || '');
  const selfName = user?.full_name || [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email || 'Me';

  const [definition, setDefinition] = useState(null);
  const [loadingDefs, setLoadingDefs] = useState(true);
  // Pre-fill the period from a deep-link: `period` ("My Forms") or `MID` (the CID/EID/MID
  // params a notification link carries, spec §11). Falls back to the current month.
  const [period, setPeriod] = useState(
    () => lockedPeriod || periodFromParam(searchParams.get('period') || searchParams.get('MID')) || defaultPeriod());

  const [saved, setSaved] = useState({});      // { question_id: {checked, remark, question} } (locked)
  const [draft, setDraft] = useState({});      // { question_id: {checked, remark} } (editable)
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const questions = definition?.questions || [];

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoadingDefs(true);
      try {
        const res = await getFormDefinitions();
        if (!alive) return;
        setDefinition((res.data?.definitions || []).find((d) => d.form_type === formType) || null);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form configuration');
      } finally {
        if (alive) setLoadingDefs(false);
      }
    })();
    return () => { alive = false; };
  }, [formType, showError]);

  const refreshSaved = React.useCallback(async () => {
    if (!companyId || !period.trim() || !definition || definition.available === false) { setSaved({}); return; }
    setLoadingSaved(true);
    try {
      const res = await getFeedback(formType, { company_id: companyId, period: period.trim(), md_id: selfId });
      setSaved(res.data?.answers || {});
      setDraft({});
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load saved answers');
    } finally {
      setLoadingSaved(false);
    }
  }, [formType, companyId, selfId, period, definition, showError]);

  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  const setChecked = (qid, checked) => setDraft((p) => ({ ...p, [qid]: { ...(p[qid] || {}), checked } }));
  const setRemark = (qid, remark) => setDraft((p) => ({ ...p, [qid]: { ...(p[qid] || {}), remark } }));

  const editableQuestions = questions.filter((q) => saved[String(q.id)] == null);
  const answeredInDraft = editableQuestions.filter((q) => {
    const d = draft[String(q.id)] || {};
    return d.checked || (d.remark || '').trim();
  }).length;

  const handleSubmit = async () => {
    if (!companyId) return showError('Your account has no company assigned. Contact your administrator.');
    if (!period.trim()) return showError('Please enter the month / period');

    const answers = editableQuestions
      .map((q) => {
        const d = draft[String(q.id)] || {};
        return { question_id: String(q.id), question: q.title, checked: !!d.checked, remark: (d.remark || '').trim() };
      })
      .filter((a) => a.checked || a.remark);

    if (!answers.length) return showError('Tick a box or add a remark before submitting.');

    setSaving(true);
    try {
      const res = await submitFeedback(formType, {
        company_id: companyId,
        period: period.trim(),
        md_id: selfId,
        md_name: selfName,
        answers,
      });
      showSuccess(res.data?.message || 'Feedback recorded');
      // Tell the assignment link (if this was opened from one) that it is done.
      onSubmitted?.();
      await refreshSaved();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to submit feedback');
    } finally {
      setSaving(false);
    }
  };

  if (loadingDefs) {
    return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading form…</div>;
  }

  const title = definition?.title || 'Implementation Update Feedback';

  if (definition && definition.available === false) {
    return (
      <div className="space-y-5">
        <DashboardHero icon={icon || ClipboardList} title={title} subtitle="This form is not configured yet." />
        <Section title="Awaiting questions" icon={ClipboardList}>
          <div className="px-5 py-10 text-center text-[13px] text-[var(--text-muted)]">
            The questions for “{title}” haven't been added yet. Once the list is provided
            they'll appear here automatically — no further setup needed.
          </div>
        </Section>
      </div>
    );
  }

  const highlight = `${selfName}${period ? ` · ${period}` : ''}`;
  const totalQ = questions.length;
  const savedCount = Object.keys(saved).length;
  const ready = companyId && period.trim();

  return (
    <div className="space-y-5">
      <DashboardHero icon={icon || ClipboardList} title={title} highlight={highlight} subtitle={definition?.description}>
        <button
          onClick={handleSubmit}
          disabled={saving || !ready}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all disabled:opacity-60"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Submitting…' : 'Submit'}
        </button>
      </DashboardHero>

      <Section title="Submission Details" icon={User}>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Month / Period</label>
            <input type="text" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="e.g. jul26"
              readOnly={!!lockedPeriod} disabled={!!lockedPeriod}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
          </div>
          <div className="flex items-end">
            <div className="text-[12px] text-[var(--text-muted)]">
              {savedCount > 0 && (
                <span className="inline-flex items-center gap-1.5 mr-3 text-[var(--accent-green)] font-semibold">
                  <Lock size={12} /> {savedCount} already saved (locked)
                </span>
              )}
              {loadingSaved ? 'Loading…' : `${answeredInDraft} / ${editableQuestions.length} to answer · ${totalQ} total`}
            </div>
          </div>
        </div>
      </Section>

      {ready && questions.map((q, i) => {
        const qid = String(q.id);
        const lock = saved[qid];
        const locked = lock != null;
        const d = draft[qid] || {};
        return (
          <Section key={qid} title={`${i + 1}. ${q.title}`} subtitle={q.desc || undefined}
            icon={locked ? CheckCircle2 : ClipboardList} tone={locked ? 'green' : 'navy'}>
            <div className="px-5 py-4 space-y-3">
              {locked ? (
                <div className="flex items-center gap-3">
                  <span className={`text-[12px] font-bold px-2.5 py-1 rounded-full ${lock.checked ? 'text-[var(--accent-green)] bg-[var(--accent-green-bg)]' : 'text-[var(--accent-red)] bg-[var(--accent-red-bg)]'}`}>
                    {lock.checked ? 'YES' : 'NO'}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-[var(--text-muted)]"><Lock size={12} /> saved</span>
                </div>
              ) : (
                <label className="inline-flex items-center gap-2.5 cursor-pointer select-none">
                  <input type="checkbox" checked={!!d.checked} onChange={(e) => setChecked(qid, e.target.checked)}
                    className="w-[22px] h-[22px] accent-[var(--accent-indigo)] cursor-pointer" />
                  <span className="text-[13px] font-semibold">{d.checked ? 'Yes' : 'Tick for Yes'}</span>
                </label>
              )}
              <div>
                <div className="text-[11px] text-[var(--text-muted)] mb-1">Remark (optional)</div>
                <textarea rows={2} disabled={locked}
                  value={locked ? (lock.remark || '') : (d.remark || '')}
                  onChange={(e) => setRemark(qid, e.target.value)}
                  placeholder={locked ? '' : 'Add a note…'}
                  className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] outline-none focus:border-[var(--accent-indigo)] disabled:opacity-70 resize-y" />
              </div>
            </div>
          </Section>
        );
      })}
    </div>
  );
};

export default ClientFeedbackForm;
