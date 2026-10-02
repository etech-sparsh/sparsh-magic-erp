import React, { useCallback, useEffect, useState } from 'react';
import { FileCog, Search, Settings2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees, getLetterTemplates, saveLetterTemplate, previewLetter, generateLetter,
  listLetters, getLetter, issueLetter, reissueLetter,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, toneFor, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ HR Letter / Document Generator (BA/Functional Design §41, screen SM-HR-041).
 *
 * Offer and Appointment letters live elsewhere (they regenerate from the live offer/
 * appointment record). This screen is for every OTHER controlled letter — confirmation,
 * revision, warning, relieving, whatever HR needs — where the letter's own rendered content
 * IS the record, so it is generated once, stored, and immutable once issued.
 *
 * No canned templates ship with this screen (see the backend module's own docstring):
 * actual employee-correspondence wording is company- and jurisdiction-specific, so HR
 * authors it themselves in the Templates panel before generating anything.
 */

const EmployeePicker = ({ scope, value, onChange }) => {
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
      <input value={search} placeholder="Search by name or employee code…"
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

/** Parses a plain "Key: Value" per line box into extra_fields — the flexible escape hatch
 * for whatever a given template needs beyond the auto-derived employee facts. */
const parseExtraFields = (text) => {
  const out = {};
  for (const line of (text || '').split('\n')) {
    const idx = line.indexOf(':');
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim().toLowerCase().replace(/\s+/g, '_');
    const value = line.slice(idx + 1).trim();
    if (key && value) out[key] = value;
  }
  return out;
};

const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      const result = await fn();
      if (successMsg) showSuccess(successMsg);
      onDone(result);
      return result;
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const LetterBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [managingTemplates, setManagingTemplates] = useState(false);
  const [openLetterNo, setOpenLetterNo] = useState(null);

  const canManage = can(CAP.LETTER_MANAGE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listLetters({ ...scope, limit: 100 });
      setRows(data?.letters || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load correspondence.');
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
        <span className="block text-[11px] text-[var(--text-muted)]">{r.letter_no}</span>
      </>
    ) },
    { key: 'title', label: 'Letter', render: (r) => <span className="text-[var(--text-main)]">{r.title}</span> },
    { key: 'effective', label: 'Effective', render: (r) => (
      <span className="text-[var(--text-main)]">{day(r.merge_fields?.effective_date)}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={toneFor(r.status)}>{r.status}</Chip>
        <Btn tone="ghost" onClick={() => setOpenLetterNo(r.letter_no)}>Open</Btn>
      </div>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={FileCog}
        title="HR Letters"
        subtitle="Controlled employee correspondence — preview, generate, issue, reissue (SM-HR-041)."
        actions={canManage && (
          <div className="flex items-center gap-2">
            <Btn tone="ghost" onClick={() => setManagingTemplates(true)}>
              <Settings2 size={14} /> Templates
            </Btn>
            <Btn tone="primary" onClick={() => setGenerating(true)}>
              <FileCog size={14} /> New Letter
            </Btn>
          </div>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading correspondence…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns}
            renderCard={(r) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">{r.letter_no} · {r.title}</p>
                  </div>
                  <Chip tone={toneFor(r.status)}>{r.status}</Chip>
                </div>
                <Facts items={[{ label: 'Effective', value: day(r.merge_fields?.effective_date) }]} />
                <Btn tone="ghost" onClick={() => setOpenLetterNo(r.letter_no)}>Open</Btn>
              </div>
            )}
            keyOf={(r) => r.letter_no} />
        ) : (
          <HrmsEmpty icon={FileCog} title="No correspondence"
            hint="A letter you're not authorised to see simply does not appear here." />
        )
      )}

      {generating && (
        <GenerateModal scope={scope} onClose={() => setGenerating(false)}
          onDone={() => { setGenerating(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {managingTemplates && (
        <TemplatesModal scope={scope} onClose={() => setManagingTemplates(false)}
          showSuccess={showSuccess} showError={showError} />
      )}
      {openLetterNo && (
        <LetterDetailModal letterNo={openLetterNo} scope={scope} canManage={canManage}
          onClose={() => setOpenLetterNo(null)} onDone={() => load()}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const GenerateModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [templates, setTemplates] = useState([]);
  const [templateKey, setTemplateKey] = useState('');
  const [employee, setEmployee] = useState(null);
  const [effectiveDate, setEffectiveDate] = useState(new Date().toISOString().slice(0, 10));
  const [approverName, setApproverName] = useState('');
  const [approverDesignation, setApproverDesignation] = useState('');
  const [extraText, setExtraText] = useState('');
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [draft, setDraft] = useState(null);
  const { busy, run } = useSubmit(showSuccess, showError, () => {});

  useEffect(() => {
    // Depend on the company id specifically, not just mount: on a cold page load `scope`
    // resolves asynchronously (HrmsContext fetches it after mount), and firing once against
    // an empty scope would 400 silently and leave this list permanently empty — the same
    // race EmployeeProfile.jsx's departments/designations fetch hit earlier in this module.
    if (!scope.company_id) return;
    getLetterTemplates(scope)
      .then(({ data }) => setTemplates(data?.templates || []))
      .catch(() => setTemplates([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  const payload = () => ({
    template_key: templateKey, employee_code: employee?.employee_code,
    effective_date: effectiveDate, approver_name: approverName.trim() || undefined,
    approver_designation: approverDesignation.trim() || undefined,
    extra_fields: parseExtraFields(extraText),
  });

  const doPreview = async () => {
    if (!templateKey || !employee) { showError('Choose a template and an employee first.'); return; }
    setPreviewing(true);
    try {
      const { data } = await previewLetter(payload(), scope);
      setPreview(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not render a preview.');
    } finally {
      setPreviewing(false);
    }
  };

  const doGenerate = () => {
    if (!templateKey || !employee) { showError('Choose a template and an employee first.'); return; }
    run(async () => {
      const { data } = await generateLetter(
        { ...payload(), letter_no: draft?.letter_no }, scope);
      setDraft(data);
      return data;
    }, draft ? 'Draft updated.' : 'Draft generated.');
  };

  const doIssue = () => {
    if (!draft) return;
    run(async () => {
      await issueLetter(draft.letter_no, scope);
      return true;
    }, 'Letter issued.').then((ok) => { if (ok) onDone(); });
  };

  return (
    <Modal title="New Letter" labelledBy="letter-gen-title"
      subtitle="Preview, generate a draft, then issue." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>{draft ? 'Close' : 'Cancel'}</Btn>
          {!draft?.status && (
            <Btn onClick={doPreview} disabled={previewing || !templateKey || !employee}>
              {previewing ? 'Rendering…' : 'Preview'}
            </Btn>
          )}
          {draft?.status !== 'Draft' ? (
            <Btn tone="primary" onClick={doGenerate} disabled={busy || !templateKey || !employee}>
              {busy ? 'Working…' : 'Generate'}
            </Btn>
          ) : (
            <>
              <Btn onClick={doGenerate} disabled={busy}>{busy ? 'Working…' : 'Regenerate'}</Btn>
              <Btn tone="primary" onClick={doIssue} disabled={busy}>
                {busy ? 'Working…' : 'Issue'}
              </Btn>
            </>
          )}
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="letter-template">Template *</label>
        <select id="letter-template" value={templateKey} className={FIELD}
          onChange={(e) => setTemplateKey(e.target.value)}>
          <option value="">Select a template…</option>
          {templates.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
        </select>
        {!templates.length && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            No templates yet — an HR admin can author one under "Templates".
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="letter-effective">Effective Date</label>
          <input id="letter-effective" type="date" value={effectiveDate} className={FIELD}
            onChange={(e) => setEffectiveDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="letter-approver">Approver / Signatory</label>
          <input id="letter-approver" value={approverName} className={FIELD}
            placeholder="Name" onChange={(e) => setApproverName(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="letter-approver-desig">Approver Designation</label>
        <input id="letter-approver-desig" value={approverDesignation} className={FIELD}
          onChange={(e) => setApproverDesignation(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="letter-extra">Additional Details (one "Key: Value" per line)</label>
        <textarea id="letter-extra" rows={3} value={extraText} className={TEXTAREA}
          placeholder={'new_designation: Senior Analyst\nnew_ctc: 8,50,000'}
          onChange={(e) => setExtraText(e.target.value)} />
      </div>
      {preview && !draft && (
        <div className="rounded-lg border border-[var(--border)] p-3 max-h-52 overflow-y-auto">
          <p className={LABEL}>Preview</p>
          <p className="text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
            {preview.rendered_body}
          </p>
        </div>
      )}
      {draft && (
        <div className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <div className="flex items-center justify-between">
            <Chip tone={toneFor(draft.status)}>{draft.status}</Chip>
            <span className="text-[11px] text-[var(--text-muted)]">{draft.letter_no}</span>
          </div>
          {draft.url && (
            <a href={draft.url} target="_blank" rel="noreferrer"
              className="text-[12px] font-bold text-[var(--accent-indigo)]">
              View generated PDF
            </a>
          )}
        </div>
      )}
    </Modal>
  );
};

const TemplatesModal = ({ scope, onClose, showSuccess, showError }) => {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // {key, title, body, merge_fields, active} or {} for new

  const load = useCallback(async () => {
    if (!scope.company_id) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getLetterTemplates({ ...scope, include_inactive: true });
      setTemplates(data?.templates || []);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not load templates.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
    <Modal title="Letter Templates" labelledBy="letter-templates-title"
      subtitle="HR authors the wording — nothing is preloaded." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          <Btn tone="primary" onClick={() => setEditing({ key: '', title: '', body: '', merge_fields: [], active: true })}>
            New Template
          </Btn>
        </>
      )}
    >
      {loading ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
      ) : templates.length === 0 ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">No templates yet.</p>
      ) : (
        <div className="space-y-2">
          {templates.map((t) => (
            <button key={t.key} type="button" onClick={() => setEditing(t)}
              className="w-full flex items-center justify-between rounded-lg border
                border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--input-bg)]">
              <span className="text-[13px] font-semibold text-[var(--text-main)]">{t.title}</span>
              <Chip tone={t.active ? 'good' : 'neutral'}>{t.active ? 'Active' : 'Inactive'}</Chip>
            </button>
          ))}
        </div>
      )}
    </Modal>
    {/* A SIBLING, not nested inside the Modal above — see the identical note on
        LetterDetailModal/ReissueModal further down this file. */}
    {editing && (
        <TemplateEditor template={editing} scope={scope} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </>
  );
};

const TemplateEditor = ({ template, scope, onClose, onSaved, showSuccess, showError }) => {
  const [key, setKey] = useState(template.key || '');
  const [title, setTitle] = useState(template.title || '');
  const [body, setBody] = useState(template.body || '');
  const [mergeFields, setMergeFields] = useState((template.merge_fields || []).join(', '));
  const [active, setActive] = useState(template.active !== false);
  const { busy, run } = useSubmit(showSuccess, showError, onSaved);

  const submit = () => {
    if (!key.trim() || !title.trim() || !body.trim()) {
      showError('A template needs a key, a title and a body.');
      return;
    }
    run(() => saveLetterTemplate(key.trim(), {
      title: title.trim(), body,
      merge_fields: mergeFields.split(',').map((s) => s.trim()).filter(Boolean),
      active,
    }, scope), 'Template saved.');
  };

  return (
    <Modal title={template.key ? 'Edit Template' : 'New Template'} labelledBy="letter-template-editor-title"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="tpl-key">Key *</label>
        <input id="tpl-key" value={key} disabled={!!template.key} className={FIELD}
          placeholder="confirmation_letter" onChange={(e) => setKey(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="tpl-title">Title *</label>
        <input id="tpl-title" value={title} className={FIELD}
          onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="tpl-body">Body * — use {'{field_name}'} to merge</label>
        <textarea id="tpl-body" rows={8} value={body} className={TEXTAREA}
          onChange={(e) => setBody(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="tpl-fields">Merge field hints (comma separated)</label>
        <input id="tpl-fields" value={mergeFields} className={FIELD}
          placeholder="employee_name, designation, effective_date"
          onChange={(e) => setMergeFields(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active
      </label>
    </Modal>
  );
};

const LetterDetailModal = ({ letterNo, scope, canManage, onClose, onDone, showSuccess, showError }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reissuing, setReissuing] = useState(false);
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getLetter(letterNo, scope);
      setDetail(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this letter.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [letterNo]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <Modal title={letterNo} labelledBy="letter-detail-title" onClose={onClose}
        footer={(
          <>
            <Btn onClick={onClose}>Close</Btn>
            {canManage && detail?.status === 'Draft' && (
              <Btn tone="primary" disabled={busy}
                onClick={() => run(() => issueLetter(letterNo, scope), 'Letter issued.')}>
                {busy ? 'Working…' : 'Issue'}
              </Btn>
            )}
            {canManage && detail?.status === 'Issued' && (
              <Btn tone="primary" onClick={() => setReissuing(true)}>Reissue</Btn>
            )}
          </>
        )}
      >
        {loading && <HrmsLoading label="Loading letter…" />}
        {error && !loading && <HrmsError message={error} onRetry={load} />}
        {!loading && !error && detail && (
          <div className="space-y-4">
            <Chip tone={toneFor(detail.status)}>{detail.status}</Chip>
            <Facts items={[
              { label: 'Employee', value: detail.employee_name || detail.employee_code },
              { label: 'Letter', value: detail.title },
              { label: 'Effective', value: day(detail.merge_fields?.effective_date) },
              { label: 'Approver', value: detail.merge_fields?.approver_name },
              { label: 'Supersedes', value: detail.supersedes },
              { label: 'Superseded by', value: detail.superseded_by },
              { label: 'Reissue reason', value: detail.reason },
            ]} />
            {detail.url && (
              <a href={detail.url} target="_blank" rel="noreferrer"
                className="text-[12px] font-bold text-[var(--accent-indigo)]">
                View PDF
              </a>
            )}
            <div className="rounded-lg border border-[var(--border)] p-3 max-h-52 overflow-y-auto">
              <p className="text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">
                {detail.rendered_body}
              </p>
            </div>
          </div>
        )}
      </Modal>
      {/* A SIBLING of the Modal above, not nested inside its children — two overlays with the
          same fixed/z-[60] shell stack unpredictably (the outer one's footer can paint over
          the inner one's buttons) when one is nested inside the other's content area. */}
      {reissuing && (
        <ReissueModal letter={detail} scope={scope} onClose={() => setReissuing(false)}
          onDone={() => { setReissuing(false); load(); onDone(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </>
  );
};

const ReissueModal = ({ letter, scope, onClose, onDone, showSuccess, showError }) => {
  const [effectiveDate, setEffectiveDate] = useState(letter.merge_fields?.effective_date || '');
  const [approverName, setApproverName] = useState(letter.merge_fields?.approver_name || '');
  const [approverDesignation, setApproverDesignation] = useState(letter.merge_fields?.approver_designation || '');
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!reason.trim()) { showError('A reissue needs a reason.'); return; }
    run(() => reissueLetter(letter.letter_no, {
      template_key: letter.template_key, employee_code: letter.employee_code,
      effective_date: effectiveDate || undefined,
      approver_name: approverName.trim() || undefined,
      approver_designation: approverDesignation.trim() || undefined,
      extra_fields: {}, reason: reason.trim(),
    }, scope), 'Letter reissued.');
  };

  return (
    <Modal title="Reissue Letter" labelledBy="letter-reissue-title"
      subtitle="Supersedes this letter and issues a new version." onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Reissue'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="reissue-effective">Effective Date</label>
          <input id="reissue-effective" type="date" value={effectiveDate} className={FIELD}
            onChange={(e) => setEffectiveDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="reissue-approver">Approver</label>
          <input id="reissue-approver" value={approverName} className={FIELD}
            onChange={(e) => setApproverName(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="reissue-approver-desig">Approver Designation</label>
        <input id="reissue-approver-desig" value={approverDesignation} className={FIELD}
          onChange={(e) => setApproverDesignation(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="reissue-reason">Reason *</label>
        <textarea id="reissue-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

export default LetterBoard;
