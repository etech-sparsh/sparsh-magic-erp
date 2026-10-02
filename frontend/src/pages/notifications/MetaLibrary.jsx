import React, { useCallback, useEffect, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import {
  BadgeCheck, RefreshCw, Plus, Pencil, Eye, Trash2, CheckCircle2, AlertTriangle,
} from 'lucide-react';
import { TableShell, Td, Th, Pager, usePaged } from '../../features/tpms/common/dashboardKit';
import { EDITABLE_STATUSES, STATUS_TONE } from '../../components/whatsapp/constants';
import { deleteMetaTemplate, getMetaTemplates, syncMetaTemplates } from '../../services/notifyTemplatesApi';
import { Button, ConfirmDialog, Modal, ModalHeader, Notice, Pill } from './NtUi';
import { errMsg } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   Meta templates — the approved WhatsApp wording notifications are sent with, opened in place
   from the WhatsApp page.

   The definitions live on the WhatsApp Business Account, so there is ONE library for the whole
   application (Delegation, Checklist, Calendar, TPMS …). Authoring uses the shared composer;
   Meta reviews asynchronously and never calls back, so approval is picked up with Sync.
   ───────────────────────────────────────────────────────────── */

const STATUS_TABS = [
  { id: '', label: 'All' },
  { id: 'APPROVED', label: 'Approved' },
  { id: 'PENDING', label: 'Pending' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'REJECTED', label: 'Rejected' },
];

const STEPS = [
  'Create the template',
  'Meta reviews it — press Sync to see the result',
  'Once Approved, pick it when you set a trigger',
];

const MetaLibrary = ({ refreshKey, notice, error, onClose, onOpenComposer, onNotice, onError, onChanged }) => {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [target, setTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getMetaTemplates(status);
      setRows(Array.isArray(data?.templates) ? data.templates : []);
    } catch (e) {
      onError(errMsg(e, 'Could not load the Meta templates.'));
    } finally {
      setLoading(false);
    }
  }, [status, onError]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const paged = usePaged(rows, 8);

  const sync = async () => {
    setSyncing(true);
    try {
      const { data } = await syncMetaTemplates();
      const bits = [];
      if (data?.total != null) bits.push(`${data.total} read from Meta`);
      if (data?.updated) bits.push(`${data.updated} updated`);
      if (data?.imported) bits.push(`${data.imported} imported`);
      onNotice(`Synced with Meta${bits.length ? ` — ${bits.join(', ')}` : ''}.`);
      await load();
      onChanged?.();
    } catch (e) {
      onError(errMsg(e, 'Could not reach Meta.'));
    } finally {
      setSyncing(false);
    }
  };

  const remove = async () => {
    if (!target) return;
    setDeleting(true);
    try {
      await deleteMetaTemplate(target._id);
      setTarget(null);
      onNotice('Template deleted.');
      await load();
      onChanged?.();
    } catch (e) {
      onError(errMsg(e, 'Could not delete the template.'));
      setTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <Modal onClose={onClose} width="max-w-5xl">
        <ModalHeader icon={BadgeCheck} tone="green" title="Meta templates"
          subtitle="Approved WhatsApp wording — one library for every module" onClose={onClose} />

        <div className="px-5 py-3 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {STATUS_TABS.map((s) => (
              <button key={s.id || 'all'} type="button" onClick={() => setStatus(s.id)}
                className={`px-3 py-1.5 rounded-lg text-[11.5px] font-bold transition-colors ${
                  status === s.id
                    ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                    : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                {s.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" icon={RefreshCw} busy={syncing} onClick={sync}>
              {syncing ? 'Syncing…' : 'Sync with Meta'}
            </Button>
            <Button size="sm" icon={Plus} onClick={() => onOpenComposer(null)}>Create Meta template</Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="px-5 pt-4 pb-1 space-y-3">
            <ol className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {STEPS.map((text, i) => (
                <li key={text} className="flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--text-muted)]">
                  <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10.5px] font-black text-white shrink-0"
                    style={{ background: 'var(--accent-green)' }}>
                    {i + 1}
                  </span>
                  {text}
                </li>
              ))}
            </ol>
            {notice && <Notice tone="green" icon={CheckCircle2}>{notice}</Notice>}
            {error && <Notice tone="red" icon={AlertTriangle}>{error}</Notice>}
          </div>

          {loading && !rows.length ? (
            <p className="px-5 py-12 text-center text-[12.5px] font-bold text-[var(--text-muted)]">Loading…</p>
          ) : !rows.length ? (
            <div className="px-5 py-12 text-center space-y-1">
              <p className="text-[13px] font-bold">No templates{status ? ` with status ${status.toLowerCase()}` : ''}</p>
              <p className="text-[12px] text-[var(--text-muted)]">
                Create one and submit it to Meta, or sync to pull in templates already approved on your business account.
              </p>
            </div>
          ) : (
            <div className="pt-3">
              <TableShell minWidth={760}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-y border-[var(--border)]">
                    <Th>Template</Th><Th align="center">Category</Th><Th align="center">Language</Th>
                    <Th align="center">Status</Th><Th align="right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {paged.pageRows.map((t) => {
                    const st = (t.status || 'DRAFT').toUpperCase();
                    const editable = EDITABLE_STATUSES.includes(st);
                    return (
                      <tr key={t._id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors align-top">
                        <Td>
                          <div className="font-bold font-mono text-[12.5px] break-all">{t.name}</div>
                          <div className="text-[11.5px] text-[var(--text-muted)] mt-0.5 max-w-[380px] truncate" title={t.body || ''}>
                            {t.body || '—'}
                          </div>
                          {st === 'REJECTED' && t.rejected_reason && (
                            <div className="text-[11px] text-[var(--accent-red)] mt-1 max-w-[380px]">{t.rejected_reason}</div>
                          )}
                        </Td>
                        <Td align="center"><Pill label={t.meta_category || t.category || '—'} tone="indigo" /></Td>
                        <Td align="center" className="font-medium text-[var(--text-muted)]">{t.language}</Td>
                        <Td align="center"><Pill label={st} tone={STATUS_TONE[st] || 'muted'} /></Td>
                        <Td align="right">
                          <div className="inline-flex items-center gap-1.5">
                            <Button variant="outline" size="sm" icon={editable ? Pencil : Eye} onClick={() => onOpenComposer(t)}>
                              {editable ? 'Edit' : 'View'}
                            </Button>
                            <Button variant="danger" size="sm" icon={Trash2} onClick={() => setTarget(t)}
                              aria-label="Delete template" title="Delete template" />
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
              <Pager {...paged} label="templates" />
            </div>
          )}
        </div>
      </Modal>

      <AnimatePresence>
        {target && (
          <ConfirmDialog key="delete-meta" title="Delete this Meta template?" confirmLabel="Delete" busy={deleting}
            body={<>
              <b className="font-mono">{target.name}</b> is removed from the WhatsApp Business Account as
              well as from here, which cannot be undone. Any notification still using it — in any
              module — will stop sending on WhatsApp.
            </>}
            onCancel={() => setTarget(null)} onConfirm={remove} />
        )}
      </AnimatePresence>
    </>
  );
};

export default MetaLibrary;
