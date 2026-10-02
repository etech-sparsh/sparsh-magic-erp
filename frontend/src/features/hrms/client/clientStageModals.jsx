import React, { useState } from 'react';
import { FIELD, LABEL, TEXTAREA } from '../internal/internalKit';
import { Btn, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Client Hiring ▸ the forms the assessment and interview stages collect.
 *
 * Extracted because they are now reached from TWO places and must not drift: the candidate
 * journey (everything about one person, in context) and the Assessment / Interview boards
 * (everything at one stage, across people). The internal track has the same two views of
 * the same work; what it does not have is two copies of the form.
 */

const Field = ({ id, label, ...rest }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    <input id={id} className={FIELD} {...rest} />
  </div>
);


const AssessmentModal = ({ busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    title: '', instructions: '', due_on: '', max_score: 5,
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Modal
      title="Issue an assessment"
      subtitle="The Talent Fit Assessment, marked against the approved Position Scorecard."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !form.title.trim()}
            onClick={() => onSubmit({
              title: form.title.trim(),
              instructions: form.instructions || undefined,
              due_on: form.due_on || undefined,
              max_score: Number(form.max_score) || 5,
            })}>
            {busy ? 'Saving…' : 'Issue'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <Field id="as-title" label="Title" value={form.title} onChange={set('title')} />
        <div className="grid grid-cols-2 gap-3">
          <Field id="as-due" label="Due on" type="date" value={form.due_on}
            onChange={set('due_on')} />
          <Field id="as-max" label="Out of" type="number" value={form.max_score}
            onChange={set('max_score')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="as-inst">Instructions</label>
          <textarea id="as-inst" className={TEXTAREA} rows={3}
            value={form.instructions} onChange={set('instructions')} />
        </div>
      </div>
    </Modal>
  );
};

const ScoreModal = ({ row, busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    score: row.score ?? '', result: row.result || 'Pass',
    evaluator_notes: row.evaluator_notes || '',
    submission_reference: row.submission_reference || '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Modal
      title={`Score ${row.cas_no}`}
      subtitle="Measured against the scorecard the client approved, not against the other candidates."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || form.score === ''}
            onClick={() => onSubmit({
              score: Number(form.score),
              result: form.result,
              evaluator_notes: form.evaluator_notes || undefined,
              submission_reference: form.submission_reference || undefined,
            })}>
            {busy ? 'Saving…' : 'Save score'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field id="sc-score" label={`Score (out of ${row.max_score ?? 5})`}
            type="number" value={form.score} onChange={set('score')} />
          <div>
            <label className={LABEL} htmlFor="sc-result">Result</label>
            <select id="sc-result" className={FIELD} value={form.result}
              onChange={set('result')}>
              <option>Pass</option>
              <option>Fail</option>
            </select>
          </div>
        </div>
        <Field id="sc-ref" label="Submission reference" value={form.submission_reference}
          onChange={set('submission_reference')} placeholder="Link or file reference" />
        <div>
          <label className={LABEL} htmlFor="sc-notes">Evaluator notes</label>
          <textarea id="sc-notes" className={TEXTAREA} rows={3}
            value={form.evaluator_notes} onChange={set('evaluator_notes')} />
        </div>
      </div>
    </Modal>
  );
};

const InterviewModal = ({ busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    scheduled_at: '', mode: 'Virtual', meeting_link: '', panel: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Modal
      title="Schedule the interview"
      subtitle="Sparsh conducts it and shares the recording; the selection is the client's."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy || !form.scheduled_at}
            onClick={() => onSubmit({
              scheduled_at: new Date(form.scheduled_at).toISOString(),
              mode: form.mode,
              meeting_link: form.meeting_link || undefined,
              panel: form.panel
                ? form.panel.split(',').map((p) => p.trim()).filter(Boolean)
                : [],
            })}>
            {busy ? 'Saving…' : 'Schedule'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <Field id="iv-when" label="When" type="datetime-local" value={form.scheduled_at}
          onChange={set('scheduled_at')} />
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="iv-mode">Mode</label>
            <select id="iv-mode" className={FIELD} value={form.mode} onChange={set('mode')}>
              <option>Virtual</option>
              <option>In person</option>
              <option>Telephonic</option>
            </select>
          </div>
          <Field id="iv-link" label="Meeting link" value={form.meeting_link}
            onChange={set('meeting_link')} />
        </div>
        <Field id="iv-panel" label="Panel" value={form.panel} onChange={set('panel')}
          placeholder="Names, comma separated" />
      </div>
    </Modal>
  );
};

const OutcomeModal = ({ row, busy, onClose, onSubmit }) => {
  const [form, setForm] = useState({
    role_fit: row.role_fit ?? '', communication: row.communication ?? '',
    technical_depth: row.technical_depth ?? '', culture_fit: row.culture_fit ?? '',
    outcome: row.outcome || 'Recommend', recording_link: row.recording_link || '',
    panel_notes: row.panel_notes || '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const num = (v) => (v === '' ? undefined : Number(v));
  return (
    <Modal
      title="Record the interview"
      subtitle="The recording link is what the client watches, so capture it here before sharing."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" disabled={busy}
            onClick={() => onSubmit({
              role_fit: num(form.role_fit),
              communication: num(form.communication),
              technical_depth: num(form.technical_depth),
              culture_fit: num(form.culture_fit),
              outcome: form.outcome,
              recording_link: form.recording_link || undefined,
              panel_notes: form.panel_notes || undefined,
            })}>
            {busy ? 'Saving…' : 'Save'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-4 gap-2.5">
          <Field id="oc-role" label="Role fit" type="number" value={form.role_fit}
            onChange={set('role_fit')} />
          <Field id="oc-comm" label="Comms" type="number" value={form.communication}
            onChange={set('communication')} />
          <Field id="oc-tech" label="Technical" type="number" value={form.technical_depth}
            onChange={set('technical_depth')} />
          <Field id="oc-cult" label="Culture" type="number" value={form.culture_fit}
            onChange={set('culture_fit')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="oc-outcome">Panel outcome</label>
          <select id="oc-outcome" className={FIELD} value={form.outcome}
            onChange={set('outcome')}>
            <option>Recommend</option>
            <option>Do Not Recommend</option>
          </select>
        </div>
        <Field id="oc-rec" label="Recording link" value={form.recording_link}
          onChange={set('recording_link')} />
        <div>
          <label className={LABEL} htmlFor="oc-notes">Panel notes</label>
          <textarea id="oc-notes" className={TEXTAREA} rows={3}
            value={form.panel_notes} onChange={set('panel_notes')} />
        </div>
      </div>
    </Modal>
  );
};

export { AssessmentModal, ScoreModal, InterviewModal, OutcomeModal };
