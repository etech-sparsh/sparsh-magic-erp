import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FolderOpen, Upload, Check, X, Clock, ShieldCheck, ShieldX, Download, History, Link as LinkIcon,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getDocumentChecklist, getDocumentTypes, uploadDocument, setDocumentStatus,
  getDocumentUrl, getDocuments,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ the per-person document panel (Phase 11-R, Item 2).
 *
 * ONE component, TWO mount points: the Documents tab on an employee profile and the one on
 * a candidate's journey. Writing it once is the point — two near-identical panels would
 * drift, and the one that drifts is the one that shows a stale status.
 *
 * It renders the CHECKLIST, not just the documents held. A type with nothing against it
 * shows as Pending — an absence, stated, rather than a row that simply is not there, which
 * is the question this module exists to answer.
 *
 * Files already attached elsewhere (a candidate's resume, onboarding KYC scans) appear as
 * read-only "linked" rows. They are surfaced, never copied — see hrms_document_service.
 */

const MAX_MB = 15;

const STATUS_TONE = {
  Pending: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Uploaded: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  'Under Review': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Verified: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Rejected: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Expired: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

/** Read a File into the base64 shape the public/authenticated upload endpoints expect.
 *  The size is checked BEFORE the read so a huge file is refused without being loaded into
 *  memory — the same ordering the server applies to the declared length. */
const readFile = (file) => new Promise((resolve, reject) => {
  if (file.size > MAX_MB * 1024 * 1024) {
    reject(new Error(`That file is larger than ${MAX_MB} MB.`));
    return;
  }
  const reader = new FileReader();
  reader.onload = () => resolve({
    name: file.name,
    mime_type: file.type || 'application/octet-stream',
    data: String(reader.result).split(',')[1] || '',
  });
  reader.onerror = () => reject(new Error('That file could not be read.'));
  reader.readAsDataURL(file);
});

const DocumentPanel = ({ ownerType, ownerId, ownerName }) => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [checklist, setChecklist] = useState(null);
  const [held, setHeld] = useState([]);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(null);
  const [rejecting, setRejecting] = useState(null);
  const [remarks, setRemarks] = useState('');
  const fileInput = useRef(null);
  const pendingType = useRef(null);

  const canWrite = can(CAP.DOCUMENT_WRITE);
  const canVerify = can(CAP.DOCUMENT_VERIFY);

  const load = useCallback(async () => {
    if (!ownerId) return;
    setLoading(true);
    setError(null);
    try {
      const params = { ...scope, owner_type: ownerType, owner_id: ownerId };
      const [{ data: list }, { data: docs }, { data: typeList }] = await Promise.all([
        getDocumentChecklist(params),
        getDocuments(params),
        getDocumentTypes({ ...scope, applies_to: ownerType }),
      ]);
      setChecklist(list);
      setHeld(docs?.documents || []);
      setTypes(typeList?.document_types || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load documents.');
    } finally {
      setLoading(false);
    }
  }, [companyId, ownerType, ownerId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const pickFile = (typeId, docNo) => {
    pendingType.current = { typeId, docNo };
    fileInput.current?.click();
  };

  const onFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    const target = pendingType.current;
    if (!file || !target) return;

    setUploading(target.typeId);
    try {
      const payload = {
        owner_type: ownerType,
        owner_id: ownerId,
        type_id: target.typeId,
        file: await readFile(file),
      };
      // A doc_no means "add a version to this document" rather than "create a new one".
      // Correcting a blurry scan must not become a second competing row.
      if (target.docNo) payload.doc_no = target.docNo;
      await uploadDocument(payload, scope);
      showSuccess(target.docNo ? 'A new version was added.' : 'The document was uploaded.');
      load();
    } catch (err) {
      showError(err?.message || err?.response?.data?.detail || 'The upload failed.');
    } finally {
      setUploading(null);
    }
  };

  const decide = async (docNo, status, note) => {
    try {
      await setDocumentStatus(docNo, { status, remarks: note }, scope);
      showSuccess(`Marked ${status.toLowerCase()}.`);
      setRejecting(null);
      setRemarks('');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the document.');
    }
  };

  const open = async (docNo) => {
    try {
      const { data } = await getDocumentUrl(docNo, scope);
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open the document.');
    }
  };

  if (loading) return <HrmsLoading label="Loading documents…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  const items = checklist?.items || [];
  const linked = checklist?.linked || [];
  const byDocNo = Object.fromEntries(held.map((d) => [d.doc_no, d]));
  const outstanding = checklist?.mandatory_outstanding ?? 0;

  return (
    <div className="space-y-4">
      <input ref={fileInput} type="file" className="hidden" onChange={onFile} />

      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {ownerName || checklist?.owner_name || ownerId}
          </p>
          <p className="text-[12px] text-[var(--text-muted)]">
            {checklist?.mandatory_total ?? 0} mandatory document(s)
            {outstanding > 0 && (
              <span className="text-[var(--accent-red)] font-semibold">
                {' '}— {outstanding} still outstanding
              </span>
            )}
          </p>
        </div>
      </div>

      {items.length === 0 && (
        <HrmsEmpty
          icon={FolderOpen}
          title="No document types configured"
          hint="Add document types under HRMS ▸ Document Types to build a checklist."
        />
      )}

      {items.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[720px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Document</th>
                <th className="text-left px-4 py-2.5">Status</th>
                <th className="text-left px-4 py-2.5">Expires</th>
                <th className="text-left px-4 py-2.5">Version</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const doc = item.doc_no ? byDocNo[item.doc_no] : null;
                return (
                  <tr key={item.type_id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-2.5">
                      <span className="font-semibold text-[var(--text-main)]">{item.type_name}</span>
                      {item.mandatory && (
                        <span className="ml-2 text-[10px] font-bold uppercase tracking-wider text-[var(--accent-red)]">
                          Required
                        </span>
                      )}
                      <span className="block text-[11px] text-[var(--text-muted)]">{item.category}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-bold ${STATUS_TONE[item.status] || ''}`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-muted)]">
                      {item.expiry_date || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-muted)]">
                      {item.current_version ? `v${item.current_version}` : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1.5">
                        {item.doc_no && (
                          <button
                            type="button"
                            onClick={() => open(item.doc_no)}
                            title="Open"
                            className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)]"
                          >
                            <Download size={13} />
                          </button>
                        )}
                        {canWrite && (
                          <button
                            type="button"
                            onClick={() => pickFile(item.type_id, item.doc_no)}
                            disabled={uploading === item.type_id}
                            title={item.doc_no ? 'Upload a new version' : 'Upload'}
                            className="h-7 px-2.5 rounded-lg border border-[var(--border)] flex items-center gap-1 text-[11px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-40"
                          >
                            <Upload size={12} />
                            {item.doc_no ? 'New version' : 'Upload'}
                          </button>
                        )}
                        {canVerify && item.doc_no && item.status !== 'Verified' && (
                          <button
                            type="button"
                            onClick={() => decide(item.doc_no, 'Verified')}
                            title="Verify"
                            className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-green,var(--accent-indigo))]"
                          >
                            <ShieldCheck size={13} />
                          </button>
                        )}
                        {canVerify && item.doc_no && item.status !== 'Rejected' && (
                          <button
                            type="button"
                            onClick={() => { setRejecting(item); setRemarks(''); }}
                            title="Reject"
                            className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]"
                          >
                            <ShieldX size={13} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {linked.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-2">
          <div className="flex items-center gap-2">
            <LinkIcon size={14} className="text-[var(--text-muted)]" />
            <p className="text-[12.5px] font-bold text-[var(--text-main)]">
              Files attached elsewhere
            </p>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Surfaced read-only from the application and onboarding records. They are not
            copied here — the original stays the single source.
          </p>
          <ul className="space-y-1.5 pt-1">
            {linked.map((row, i) => (
              <li key={`${row.s3_key || row.file_name}-${i}`} className="flex items-center gap-2 text-[12.5px]">
                <span className="font-semibold text-[var(--text-main)]">{row.type_name}</span>
                <span className="text-[var(--text-muted)]">{row.file_name || '—'}</span>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] ml-auto">
                  {row.origin}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {rejecting && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">
              Reject {rejecting.type_name}
            </h2>
            <p className="text-[12.5px] text-[var(--text-muted)]">
              A reason is required — it is what the person is told so they can correct it.
            </p>
            <textarea
              className="w-full h-24 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
              placeholder="What is wrong with this document?"
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRejecting(null)}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => decide(rejecting.doc_no, 'Rejected', remarks)}
                disabled={!remarks.trim()}
                className="h-9 px-4 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                Reject document
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DocumentPanel;
