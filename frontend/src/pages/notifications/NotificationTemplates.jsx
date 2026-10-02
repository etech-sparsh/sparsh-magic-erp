import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import {
  Mail, MessageCircle, RefreshCw, CheckCircle2, AlertTriangle, Info, Building2, Library,
} from 'lucide-react';
import { DashboardHero, HeroButton } from '../../features/tpms/common/dashboardKit';
import TemplateComposer from '../../components/whatsapp/TemplateComposer';
import MailTemplateAdmin from '../../features/tpms/admin/pages/MailTemplateAdmin';
import LeadershipWhatsApp from '../../features/tpms/admin/pages/LeadershipWhatsApp';
import CommTemplates from '../../features/hrms/internal/CommTemplates';
import { RequireHrms } from '../../features/hrms/HrmsGate';
import { useAuth } from '../../context/AuthContext';
import {
  checkMetaTemplate, deleteNotifyTemplate, getApprovedMetaTemplates, getNotifyModules,
  getNotifyTemplates, getReminderSchedule, saveMetaTemplate, setNotifyTemplateStatus,
  submitMetaTemplate, testMetaTemplate, upsertNotifyTemplate,
} from '../../services/notifyTemplatesApi';
import {
  canManageGeneralTemplates, canManageHrmsComms, canManageLeadershipInvite, canManageTpmsTemplates,
  canOpenNotificationTemplates, canSeeGeneralModule, isNotifyAdmin,
} from '../../utils/notifyTemplateAccess';
import {
  CHANNEL_META, EXTERNAL_MODULES, MODULE_ICON, MODULE_ORDER, errMsg, to12h, triggerState,
} from './ntConfig';
import { ConfirmDialog, Notice, Pill } from './NtUi';
import { PreviewModal } from './MessagePreview';
import TriggerList from './TriggerList';
import TemplateEditor from './TemplateEditor';
import MetaLibrary from './MetaLibrary';
import ReminderScheduleCard from './ReminderScheduleCard';
import TestSendModal from './TestSendModal';

/* ─────────────────────────────────────────────────────────────
   Notification Templates — every Email and WhatsApp template in the application, in one module.

     /notification-templates/email      every email, module by module
     /notification-templates/whatsapp   every WhatsApp message, module by module

   Both channels are edited from their own trigger row in the list below — neither view has a
   create button. "Meta templates" opens the Meta library in place: create, sync and check
   approval without leaving the page.

   Slug-keyed modules (Delegation, Checklist, Calendar, Sessions, reminders, To-Do, accounts) are
   edited here over the existing `notification_templates` rows. TPMS, Leadership Score and HRMS
   keep their own stores, so their existing screens are embedded as-is — nothing about how any
   module stores or sends a message changes.

   ?module=<key> selects the module, so an older address can land on one.
   ───────────────────────────────────────────────────────────── */

const COMPOSER_API = { checkMetaTemplate, saveMetaTemplate, submitMetaTemplate, testMetaTemplate };

const VIEWS = {
  email: { icon: Mail, title: 'Email Templates', subtitle: 'Every email the application sends, module by module' },
  whatsapp: { icon: MessageCircle, title: 'WhatsApp Templates', subtitle: 'Meta-approved WhatsApp messages for every module' },
};

const LIVE = ['sending', 'builtin', 'inheritedUnknown'];

const supportsChannel = (t, channel) => (t.channels || ['email', 'whatsapp']).includes(channel);

const channelsOf = (m) => (m.external
  ? m.channels
  : [...new Set((m.triggers || []).flatMap((t) => t.channels || ['email', 'whatsapp']))]);

const ModuleChip = ({ module, active, count, onClick }) => {
  const Icon = MODULE_ICON[module.key];
  return (
    <button type="button" onClick={onClick}
      className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-[12.5px] font-bold whitespace-nowrap transition-all ${
        active
          ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white shadow-sm'
          : 'bg-[var(--bg-card)] border-[var(--border)] text-[var(--text-main)] hover:border-[var(--accent-indigo-border)] hover:text-[var(--accent-indigo)]'}`}>
      {Icon && <Icon size={14} />}
      {module.label}
      {count && (
        <span className={`text-[10.5px] font-black px-1.5 py-0.5 rounded-md ${
          active ? 'bg-white/20 text-white' : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
          {count}
        </span>
      )}
    </button>
  );
};

const NotificationTemplates = ({ view: requestedView = 'email' }) => {
  const view = requestedView === 'whatsapp' ? 'whatsapp' : 'email';
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();

  const allowed = canOpenNotificationTemplates(user);
  const general = canManageGeneralTemplates(user);
  const admin = isNotifyAdmin(user);

  const [catalogue, setCatalogue] = useState(null);
  const [loading, setLoading] = useState(general);
  const [rows, setRows] = useState([]);
  // undefined = not loaded yet · array = the approved library · null = not readable here
  const [approved, setApproved] = useState(undefined);
  const [schedule, setSchedule] = useState(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [libraryOpen, setLibraryOpen] = useState(false);
  const [editor, setEditor] = useState(null);           // { moduleKey, slug, channel }
  const [preview, setPreview] = useState(null);         // { title, subtitle, channel, row }
  const [toggleTarget, setToggleTarget] = useState(null);
  const [toggling, setToggling] = useState(false);
  const [testTarget, setTestTarget] = useState(null);
  const [composer, setComposer] = useState(null);       // { editing }
  const [libraryKey, setLibraryKey] = useState(0);

  const access = catalogue?.access || {};
  // One set of templates for everybody. The only remaining scope is a client account the
  // server pins to its own company — nothing on this page chooses one.
  const lockedCompany = access.company_id || null;
  const viewingCompany = lockedCompany;

  const flash = useCallback((msg) => { setNotice(msg); setError(''); }, []);
  const fail = useCallback((msg) => { setError(msg); setNotice(''); }, []);

  // ── Catalogue: modules, events, placeholders ──
  useEffect(() => {
    if (!allowed || !general) return undefined;
    let cancelled = false;
    getNotifyModules()
      .then(({ data }) => { if (!cancelled) setCatalogue(data || null); })
      .catch((e) => { if (!cancelled) fail(errMsg(e, 'Could not load the notification catalogue.')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [allowed, general, fail]);

  useEffect(() => {
    if (!admin) return;
    getReminderSchedule().then(({ data }) => setSchedule(data || null)).catch(() => setSchedule(null));
  }, [admin]);

  const loadApproved = useCallback(async () => {
    if (!admin) return;
    try {
      const { data } = await getApprovedMetaTemplates();
      setApproved(Array.isArray(data?.templates) ? data.templates : []);
    } catch {
      setApproved(null);
    }
  }, [admin]);
  useEffect(() => { loadApproved(); }, [loadApproved]);

  const loadRows = useCallback(async () => {
    if (!catalogue) return;
    try {
      const own = await getNotifyTemplates(
        viewingCompany ? { scope: 'company', company_id: viewingCompany } : { scope: 'staff' });
      setRows(own?.data?.templates || []);
    } catch (e) {
      fail(errMsg(e, 'Could not load templates.'));
    }
  }, [catalogue, viewingCompany, fail]);
  useEffect(() => { loadRows(); }, [loadRows]);

  const rowMap = useMemo(() => new Map(rows.map((r) => [r.slug, r])), [rows]);
  const approvedNames = useMemo(
    () => (Array.isArray(approved) ? new Set(approved.map((t) => t.name)) : null), [approved]);

  // Every module this user may manage, in one fixed order.
  const modules = useMemo(() => {
    const generalModules = (catalogue?.modules || [])
      .filter((m) => canSeeGeneralModule(user, m.key) && !(m.staff_only && viewingCompany));
    const list = [];
    MODULE_ORDER.forEach((key) => {
      const found = generalModules.find((m) => m.key === key);
      if (found) list.push(found);
      else if (key === 'tpms' && canManageTpmsTemplates(user)) list.push(EXTERNAL_MODULES.tpms);
      else if (key === 'leadership' && canManageLeadershipInvite(user)) list.push(EXTERNAL_MODULES.leadership);
      else if (key === 'hrms' && canManageHrmsComms(user)) list.push(EXTERNAL_MODULES.hrms);
    });
    generalModules.filter((m) => !MODULE_ORDER.includes(m.key)).forEach((m) => list.push(m));
    return list;
  }, [catalogue, user, viewingCompany]);

  const viewModules = useMemo(() => modules.filter((m) => channelsOf(m).includes(view)), [modules, view]);
  const requestedModule = params.get('module');
  const current = viewModules.find((m) => m.key === requestedModule) || viewModules[0] || null;

  const stateFor = useCallback((module, trigger, channel) => triggerState({
    module, trigger, channel,
    row: rowMap.get(`${trigger.slug}_${channel}`),
    emailRow: rowMap.get(`${trigger.slug}_email`),
    approved: approvedNames,
    locked: !!lockedCompany,
  }), [rowMap, approvedNames, lockedCompany]);

  const scheduleText = useCallback((t) => {
    if (t.schedule !== 'daily_sweep') return '';
    return schedule
      ? `Sent once a day at ${to12h(schedule.hour, schedule.minute)} IST`
      : 'Sent once a day by the reminder run';
  }, [schedule]);

  const canEdit = !!(access.can_create || access.can_update);

  const selectModule = (key) => {
    const next = new URLSearchParams(params);
    next.set('module', key);
    setParams(next, { replace: true });
  };

  const openEditor = (module, trigger, channel) => setEditor({ moduleKey: module.key, slug: trigger.slug, channel });

  const refresh = () => {
    loadRows();
    loadApproved();
    setLibraryKey((k) => k + 1);
  };

  const countFor = (m) => {
    if (m.external || !catalogue) return null;
    const list = m.triggers.filter((t) => supportsChannel(t, view));
    const live = list.filter((t) => LIVE.includes(stateFor(m, t, view).key)).length;
    return `${live}/${list.length}`;
  };

  // ── Editor ──
  const editorModule = editor ? modules.find((m) => m.key === editor.moduleKey && !m.external) || null : null;
  const editorTrigger = editorModule?.triggers.find((t) => t.slug === editor?.slug) || null;
  const editorRow = editor ? rowMap.get(`${editor.slug}_${editor.channel}`) || null : null;
  const editorApproved = admin && approved !== null ? (approved || []) : null;
  const scopeLabel = lockedCompany ? 'Your company' : 'Every company';

  const saveTemplate = async (payload) => {
    const res = await upsertNotifyTemplate({
      ...payload,
      scope: viewingCompany ? 'company' : 'staff',
      company_id: viewingCompany || undefined,
    });
    setEditor(null);
    flash(res?.data?.note || `Saved the ${payload.channel === 'whatsapp' ? 'WhatsApp' : 'email'} template for "${payload.name}".`);
    await loadRows();
  };

  const removeTemplate = async (row) => {
    await deleteNotifyTemplate(row._id);
    setEditor(null);
    flash('Template removed.');
    await loadRows();
  };

  const applyToggle = async () => {
    if (!toggleTarget) return;
    setToggling(true);
    const turnOn = toggleTarget.row.is_active === false;
    try {
      await setNotifyTemplateStatus(toggleTarget.row._id, turnOn);
      flash(`"${toggleTarget.trigger.label}" ${CHANNEL_META[toggleTarget.channel].label} is ${turnOn ? 'on' : 'off'}.`);
      setToggleTarget(null);
      await loadRows();
    } catch (e) {
      fail(errMsg(e, 'Could not change the status.'));
      setToggleTarget(null);
    } finally {
      setToggling(false);
    }
  };

  const openLibrary = () => {
    setNotice('');
    setError('');
    setLibraryOpen(true);
  };

  const onComposerSaved = async (message) => {
    setComposer(null);
    flash(message);
    setLibraryKey((k) => k + 1);
    await loadApproved();
  };

  if (!allowed) return <Navigate to="/" replace />;

  const V = VIEWS[view];
  const meta = catalogue?.meta;

  let content;
  if (loading) {
    content = <p className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading templates…</p>;
  } else if (!current) {
    content = (
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-5 py-14 text-center space-y-1">
        <p className="text-[14px] font-bold">Nothing to manage here</p>
        <p className="text-[12.5px] text-[var(--text-muted)]">
          None of the modules you manage send {view === 'whatsapp' ? 'WhatsApp messages' : 'emails'}.
        </p>
      </div>
    );
  } else if (current.key === 'tpms') {
    content = (
      <MailTemplateAdmin key={view} embedded channel={view === 'whatsapp' ? 'whatsapp' : 'mail'} />
    );
  } else if (current.key === 'leadership') {
    content = <LeadershipWhatsApp embedded />;
  } else if (current.key === 'hrms') {
    content = <RequireHrms><CommTemplates /></RequireHrms>;
  } else {
    content = (
      <div className="space-y-5">
        <TriggerList module={current} channel={view} stateFor={stateFor} scheduleText={scheduleText}
          canEdit={canEdit} canToggle={!!access.can_toggle}
          onEdit={(t, ch) => openEditor(current, t, ch)}
          onPreview={(t, ch, row) => setPreview({
            title: t.label, subtitle: `${current.label} · ${CHANNEL_META[ch].label}`, channel: ch, row,
          })}
          onToggle={(row, t, ch) => setToggleTarget({ row, trigger: t, channel: ch })} />
        {/* One clock governs Delegation's four recurring reminders, on every channel. */}
        {current.key === 'delegation' && admin && schedule && (
          <ReminderScheduleCard schedule={schedule} onSaved={setSchedule} onNotice={flash} onError={fail} />
        )}
      </div>
    );
  }

  const showScopePicker = !!current && !current.external && general;

  return (
    <div className="space-y-5 pb-16">
      <DashboardHero icon={V.icon} title={V.title} subtitle={V.subtitle}>
        {view === 'whatsapp' && admin && (
          <HeroButton icon={Library} onClick={openLibrary}>Meta templates</HeroButton>
        )}
        <HeroButton icon={RefreshCw} onClick={refresh}>Refresh</HeroButton>
      </DashboardHero>

      {view === 'whatsapp' && admin && meta && !(meta.configured && meta.sending_configured) && (
        <Notice tone="orange" icon={Info}>
          {meta.configured
            ? <><b>WhatsApp sending is not configured.</b> Approved templates cannot be delivered until WHATSAPP_PHONE_NUMBER_ID is set on the server.</>
            : <><b>WhatsApp is not connected.</b> Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_BUSINESS_ACCOUNT_ID on the server to submit templates and read their approval.</>}
        </Notice>
      )}

      {/* Module picker */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-3 space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2 px-1">
          <p className="text-[10.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">Module</p>
          {/* Every company sends the same message, so there is nothing to scope. The only
              badge left is for a client account the server pins to its own company. */}
          {showScopePicker && lockedCompany && (
            <Pill icon={Building2} tone="indigo" label="Templates for your company" />
          )}
        </div>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-0.5">
          {viewModules.map((m) => (
            <ModuleChip key={m.key} module={m} active={current?.key === m.key} count={countFor(m)}
              onClick={() => selectModule(m.key)} />
          ))}
        </div>
      </div>

      {notice && <Notice tone="green" icon={CheckCircle2}>{notice}</Notice>}
      {error && <Notice tone="red" icon={AlertTriangle}>{error}</Notice>}

      {content}

      <AnimatePresence>
        {editor && editorModule && editorTrigger && (
          <TemplateEditor key={`${editor.slug}-${editor.channel}-${viewingCompany || 'default'}-${editorRow?._id || 'new'}`}
            module={editorModule} trigger={editorTrigger} channel={editor.channel}
            row={editorRow} scopeLabel={scopeLabel} approved={editorApproved}
            scheduleText={scheduleText(editorTrigger)}
            canSave={editorRow ? !!access.can_update : !!access.can_create}
            canDelete={!!access.can_delete} canTest={admin}
            onClose={() => setEditor(null)} onSave={saveTemplate} onDelete={removeTemplate}
            onTest={(row) => setTestTarget(row)}
            onNewMetaTemplate={admin ? () => setComposer({ editing: null }) : undefined} />
        )}
        {preview && (
          <PreviewModal key="preview" {...preview} approved={Array.isArray(approved) ? approved : []}
            onClose={() => setPreview(null)} />
        )}
        {toggleTarget && (
          <ConfirmDialog key="toggle" busy={toggling}
            tone={toggleTarget.row.is_active === false ? 'green' : 'orange'}
            title={toggleTarget.row.is_active === false ? 'Turn this message on?' : 'Turn this message off?'}
            confirmLabel={toggleTarget.row.is_active === false ? 'Turn on' : 'Turn off'}
            body={toggleTarget.row.is_active === false
              ? <><b>{toggleTarget.trigger.label}</b> will start sending this {CHANNEL_META[toggleTarget.channel].label} message again.</>
              : <><b>{toggleTarget.trigger.label}</b> will stop sending this {CHANNEL_META[toggleTarget.channel].label} message. Everything else keeps working — only the message is stopped.</>}
            onCancel={() => setToggleTarget(null)} onConfirm={applyToggle} />
        )}
        {testTarget && <TestSendModal key="test" target={testTarget} onClose={() => setTestTarget(null)} />}
        {/* The library sits below the composer in this list so a template opened from it
            appears on top. */}
        {libraryOpen && (
          <MetaLibrary key="meta-library" refreshKey={libraryKey} notice={notice} error={error}
            onClose={() => setLibraryOpen(false)} onOpenComposer={(row) => setComposer({ editing: row })}
            onNotice={flash} onError={fail} onChanged={loadApproved} />
        )}
        {composer && (
          <TemplateComposer key={composer.editing?._id || 'new-meta-template'} editing={composer.editing}
            api={COMPOSER_API} onClose={() => setComposer(null)} onSaved={onComposerSaved} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default NotificationTemplates;
