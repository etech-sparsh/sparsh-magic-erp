import React, { useCallback, useEffect, useState } from 'react';
import { Mail } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getCommTemplates, updateCommTemplate, getCommunications,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from './internalKit.jsx';

/**
 * HRMS ▸ candidate communications (Annexure C).
 *
 * Four commitments both SOPs make to applicants: acknowledge every application, keep them
 * updated, tell them when they are out, and put the offer terms in writing beforehand.
 *
 * -- Two templates here are not messages ------------------------------------------------
 * `consent_equal_opportunity` and `consent_data_use` are the wording the PUBLIC APPLICATION
 * FORM shows (SOP §11). They live here, rather than in code, for one specific reason: legal
 * must be able to change that wording without a deploy. The screen labels them so nobody
 * edits them thinking they are emails.
 *
 * -- Which fire automatically, and which do not ------------------------------------------
 * Shown per template, because "did the candidate hear from us" is answered differently for
 * each. `offer_summary` is deliberately manual: writing to somebody about money is a
 * decision, not a side effect of a status change.
 *
 * -- The log is append-only ---------------------------------------------------------------
 * Nothing on this screen edits a sent message. "We told them on the 4th" is a fact about
 * the past.
 */

// Descriptions only. WHICH templates are automatic comes from the server (`t.automatic`,
// stamped from AUTO_COMM_EVENTS), because a local list drifted once: interview_scheduled
// went automatic in Phase INT-10 and this screen kept calling it manual.
const AUTOMATIC = {
  application_acknowledged: 'Fires automatically when an application arrives.',
  rejection_closure: 'Fires automatically on the reject screening action.',
  interview_scheduled: 'Fires automatically when an interview is scheduled or moved.',
};

const MANUAL = {
  offer_summary: 'Sent by hand from the offer board, before the formal letter.',
  stage_update: 'Sent by hand when there is something worth saying.',
  preboarding_checkin: 'Sent by hand during pre-boarding.',
};

const CONSENT = {
  consent_equal_opportunity:
    'Shown on the public application form. Not a message — this is the wording applicants tick.',
  consent_data_use:
    'Shown on the public application form. Not a message — this is the wording applicants tick.',
};

const CommTemplates = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [templates, setTemplates] = useState([]);
  const [log, setLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);

  const canEdit = can(CAP.COMM_TEMPLATE_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const [tplRes, logRes] = await Promise.all([
        getCommTemplates({ ...scope, include_inactive: true }),
        getCommunications(scope),
      ]);
      setTemplates(tplRes.data?.templates || []);
      setLog(logRes.data?.communications || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the templates.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const describe = (key) => AUTOMATIC[key] || MANUAL[key] || CONSENT[key] || '';

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Mail}
        title="Candidate communications"
        subtitle="What we say to applicants, and the record of when we said it."
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading templates…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <section className="space-y-3">
            <h2 className="text-[11px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Templates
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {templates.map((t) => (
                <div key={t.key}
                  className="rounded-xl border border-[var(--border)]
                    bg-[var(--bg-card)] p-4 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold text-[13px] text-[var(--text-main)]
                        break-words">
                        {t.subject}
                      </p>
                      <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                        {t.key}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <Chip tone={t.active ? 'good' : 'neutral'}>
                        {t.active ? 'active' : 'off'}
                      </Chip>
                      {t.consent
                        ? <Chip tone="accent">consent wording</Chip>
                        : t.automatic
                          ? <Chip tone="accent">automatic</Chip>
                          : <Chip>manual</Chip>}
                    </div>
                  </div>
                  {describe(t.key) && (
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      {describe(t.key)}
                    </p>
                  )}
                  <p className="text-[12px] text-[var(--text-muted)] line-clamp-3
                    whitespace-pre-line">
                    {t.body}
                  </p>
                  {canEdit && (
                    <Btn onClick={() => setEditing(t)}>Edit wording</Btn>
                  )}
                </div>
              ))}
            </div>
            {!templates.length && (
              <HrmsEmpty icon={Mail} title="No templates"
                hint="They are seeded the first time this screen is opened." />
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-[11px] font-bold uppercase tracking-widest
              text-[var(--text-muted)]">
              Sent
            </h2>
            {log.length ? (
              <RecordList
                rows={log}
                keyOf={(r) => `${r.candidate_uk}-${r.template_key}-${r.sent_at}`}
                columns={[
                  {
                    key: 'who',
                    label: 'Candidate',
                    render: (r) => (
                      <>
                        <span className="font-semibold text-[var(--text-main)]">
                          {r.candidate_name}
                        </span>
                        <span className="block text-[11px] text-[var(--text-muted)]">
                          {r.candidate_uk}
                        </span>
                      </>
                    ),
                  },
                  { key: 'template', label: 'Message', render: (r) => r.template_key },
                  {
                    key: 'status',
                    label: 'Status',
                    render: (r) => (
                      <>
                        <Chip tone={r.status === 'Sent' ? 'good'
                          : r.status === 'Failed' ? 'bad' : 'neutral'}>
                          {r.status}
                        </Chip>
                        {r.automatic && <Chip>auto</Chip>}
                      </>
                    ),
                  },
                  { key: 'when', label: 'Sent', render: (r) => day(r.sent_at) },
                  { key: 'by', label: 'By', render: (r) => r.sent_by_name },
                ]}
                renderCard={(r) => (
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-semibold text-[13px] text-[var(--text-main)]">
                        {r.candidate_name}
                      </p>
                      <Chip tone={r.status === 'Sent' ? 'good'
                        : r.status === 'Failed' ? 'bad' : 'neutral'}>
                        {r.status}
                      </Chip>
                    </div>
                    <Facts items={[
                      { label: 'Message', value: r.template_key },
                      { label: 'Sent', value: day(r.sent_at) },
                      { label: 'By', value: r.sent_by_name },
                    ]} />
                    {r.reason && (
                      <p className="text-[11.5px] text-[var(--text-muted)]">{r.reason}</p>
                    )}
                  </div>
                )}
              />
            ) : (
              <HrmsEmpty icon={Mail} title="Nothing sent yet"
                hint="Acknowledgements fire on application; rejection notes fire on the reject action." />
            )}
          </section>
        </>
      )}

      {editing && (
        <EditModal
          template={editing}
          busy={busy}
          isConsent={!!CONSENT[editing.key]}
          onClose={() => setEditing(null)}
          onSubmit={async (payload) => {
            setBusy(true);
            try {
              await updateCommTemplate(editing.key, payload, scope);
              showSuccess('Wording updated.');
              setEditing(null);
              load();
            } catch (err) {
              showError(err?.response?.data?.detail
                || 'The template could not be updated.');
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
};

const EditModal = ({ template, busy, isConsent, onClose, onSubmit }) => {
  const [subject, setSubject] = useState(template.subject || '');
  const [body, setBody] = useState(template.body || '');
  const [active, setActive] = useState(!!template.active);

  return (
    <Modal
      title={isConsent ? 'Edit the consent wording' : 'Edit the message'}
      subtitle={template.key}
      labelledBy="comm-edit"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !subject.trim() || !body.trim()}
            onClick={() => onSubmit({ subject, body, active })}>
            Save
          </Btn>
        </>
      )}
    >
      {isConsent && (
        <p className="text-[12px] text-[var(--accent-orange)]">
          This is the text applicants read and tick on the public application form. It is
          not sent to anybody — changing it changes what people are agreeing to.
        </p>
      )}

      <div>
        <label className={LABEL} htmlFor="comm-subject">
          {isConsent ? 'Heading' : 'Subject'} *
        </label>
        <input id="comm-subject" className={FIELD} value={subject}
          onChange={(e) => setSubject(e.target.value)} />
      </div>

      <div>
        <label className={LABEL} htmlFor="comm-body">
          {isConsent ? 'Statement' : 'Body'} *
        </label>
        <textarea id="comm-body" rows={12} className={TEXTAREA} value={body}
          onChange={(e) => setBody(e.target.value)} />
        {!!(template.variables || []).length && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Placeholders you can use: {template.variables.map((v) => `{${v}}`).join(', ')}.
            An unknown one renders as itself rather than breaking the message.
          </p>
        )}
      </div>

      <label className="flex items-center gap-2.5 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={active}
          onChange={(e) => setActive(e.target.checked)} />
        Active
      </label>
      {!active && (
        <p className="text-[11px] text-[var(--text-muted)]">
          Switched off, this is skipped rather than sent — and the skip is recorded in the
          log with its reason, so a silence is still accounted for.
        </p>
      )}
    </Modal>
  );
};

export default CommTemplates;
