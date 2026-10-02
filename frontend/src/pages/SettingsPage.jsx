import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import { canAccessTaskManagement, canManageTaskSettings } from '../utils/taskAccess';
import { Link } from 'react-router-dom';
import { ShieldCheck, Trash2, Mail, ToggleLeft as ToggleOff, ToggleRight as ToggleOn, UserCircle2, FolderTree, Tag, BellRing, ArrowRight } from 'lucide-react';
import { canOpenNotificationTemplates } from '../utils/notifyTemplateAccess';
import GeneralSection from '../components/settings/GeneralSection';
import MetaListSection from '../components/settings/MetaListSection';
import PasswordCard from '../components/settings/PasswordCard';
import NotificationSettings from '../components/settings/NotificationSettings';

const SettingsPage = () => {
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const [config, setConfig] = useState({ allow_backdate: false, exception_users: [] });
    /* Base URL every mailed link is built on. `effective_url`/`source` are what the server is
       ACTUALLY using right now — the stored value can be blank and still resolve, through the
       FRONTEND_URL environment variable or the local default, and that gap is exactly why a
       live deployment was mailing http://localhost:5173 links. */
    const [appUrl, setAppUrl] = useState({ frontend_url: '', effective_url: '', source: '', default_url: '' });
    const [savingUrl, setSavingUrl] = useState(false);
    const [newEmail, setNewEmail] = useState('');
    const [loading, setLoading] = useState(true);

    // Permission Checks
    const canUpdateSettings = user?.role === 'superadmin' || user?.permissions?.settings?.update;
    // Task settings (categories/tags) are internal-Sparsh-only, matching the module gate.
    const canAccessTasks = canAccessTaskManagement(user);
    const canManageMeta = canManageTaskSettings(user);
    const isSuperadmin = user?.role === 'superadmin';

    // Left-sidebar sections (role/permission filtered)
    const SECTIONS = [
        { key: 'general', label: 'General', icon: UserCircle2, visible: true },
        // Personal alert preferences are for everyone; the admin template editor below is
        // still permission-gated within the section itself.
        { key: 'notifications', label: 'Notifications', icon: Mail, visible: true },
        { key: 'security', label: 'Security', icon: ShieldCheck, visible: true },
        { key: 'categories', label: 'Categories', icon: FolderTree, visible: canAccessTasks },
        { key: 'tags', label: 'Tags', icon: Tag, visible: canAccessTasks },
    ].filter((s) => s.visible);

    const [section, setSection] = useState('general');

    useEffect(() => {
        const init = async () => {
            setLoading(true);
            try {
                const readSettings = user?.role === 'superadmin' || user?.permissions?.settings?.read;
                if (readSettings) {
                    const [backdate, url] = await Promise.all([
                        api.get('/settings/backdate-control'),
                        api.get('/settings/app-url'),
                    ]);
                    setConfig(backdate.data);
                    setAppUrl(url.data);
                }
            } catch (err) { console.error(err); }
            finally { setLoading(false); }
        };
        init();
    }, [user]);

    const handleSave = async () => {
        try {
            await api.put('/settings/backdate-control', config);
            showSuccess("Workflow settings deployed successfully.");
        } catch (error) { showError("Failed to deploy config."); }
    };

    const handleSaveAppUrl = async () => {
        setSavingUrl(true);
        try {
            const { data } = await api.put('/settings/app-url', { frontend_url: appUrl.frontend_url || '' });
            setAppUrl((prev) => ({ ...prev, effective_url: data.effective_url, source: data.source }));
            showSuccess('Application URL saved — new emails will use it.');
        } catch (error) {
            showError(error.response?.data?.detail || 'Could not save the application URL.');
        } finally {
            setSavingUrl(false);
        }
    };

    if (loading) return (
        <div className="h-[calc(100vh-56px)] flex items-center justify-center bg-[var(--bg-main)]">
            <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"/>
                <p className="text-[9px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.3em] animate-pulse">Loading Settings...</p>
            </div>
        </div>
    );

    // Reusable sidebar nav buttons (vertical desktop + horizontal mobile)
    const NavButton = ({ s, mobile }) => {
        const active = section === s.key;
        return (
            <button
                onClick={() => setSection(s.key)}
                className={`flex items-center gap-2.5 rounded-xl font-black uppercase tracking-widest transition-all shrink-0 ${
                    mobile ? 'px-3.5 py-2 text-[10px]' : 'w-full px-3.5 py-2.5 text-[11px]'
                } ${active
                    ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm'
                    : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}
            >
                <s.icon size={15} /> {s.label}
            </button>
        );
    };

    return (
        <div className="flex flex-col md:flex-row h-[calc(100vh-56px)] bg-[var(--bg-main)] overflow-hidden">
            {/* Left settings sidebar (desktop) */}
            <aside className="hidden md:flex w-60 shrink-0 border-r border-[var(--border)] bg-[var(--bg-card)] flex-col">
                <div className="p-5 border-b border-[var(--border)]">
                    <h1 className="text-lg font-black text-[var(--text-main)] tracking-tight">Settings</h1>
                    <p className="text-[11px] font-medium text-[var(--text-muted)]">Manage your workspace</p>
                </div>
                <nav className="p-3 space-y-1 overflow-y-auto no-scrollbar">
                    {SECTIONS.map((s) => <NavButton key={s.key} s={s} />)}
                </nav>
            </aside>

            {/* Mobile horizontal tabs */}
            <div className="md:hidden flex items-center gap-2 px-4 py-2.5 bg-[var(--bg-card)] border-b border-[var(--border)] overflow-x-auto no-scrollbar">
                {SECTIONS.map((s) => <NavButton key={s.key} s={s} mobile />)}
            </div>

            {/* Content */}
            <main className="flex-1 overflow-hidden flex flex-col">
                {section === 'notifications' ? (
                    <div className="flex-1 overflow-y-auto no-scrollbar p-6 space-y-6">
                        {/* Personal alert preferences — shown to every user (matches the design). */}
                        <NotificationSettings />

                        {/* Email & WhatsApp templates are managed in one module now. */}
                        {canOpenNotificationTemplates(user) && (
                            <Link to="/notification-templates/email"
                                className="group max-w-4xl mx-auto w-full flex items-center gap-4 p-5 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm hover:border-[var(--accent-indigo-border)] transition-all">
                                <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
                                    <BellRing size={20} />
                                </span>
                                <span className="flex-1 min-w-0">
                                    <span className="block text-[15px] font-bold text-[var(--text-main)] tracking-tight">Notification Templates</span>
                                    <span className="block text-[11.5px] font-medium text-[var(--text-muted)]">Email and WhatsApp templates for every module are managed in one place.</span>
                                </span>
                                <ArrowRight size={18} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] transition-colors shrink-0" />
                            </Link>
                        )}
                    </div>
                ) : (
                    <div className="flex-1 overflow-y-auto no-scrollbar p-6">
                        {section === 'general' && <GeneralSection onNavigateSection={setSection} />}

                        {section === 'security' && (
                            <div className="max-w-4xl mx-auto w-full space-y-5">
                                <PasswordCard />

                                {isSuperadmin && (
                                    <div className="space-y-4">
                                        <div>
                                            <h2 className="text-[15px] font-bold text-[var(--text-main)] tracking-tight">Application URL</h2>
                                            <p className="text-[11px] font-medium text-[var(--text-muted)] italic">
                                                The address emailed links point to — form links, reminders and invites.
                                            </p>
                                        </div>

                                        <div className="p-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] space-y-4 shadow-sm">
                                            <div className="space-y-1.5">
                                                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                                    Public address of this site
                                                </label>
                                                <div className="flex gap-2">
                                                    <input
                                                        value={appUrl.frontend_url || ''}
                                                        onChange={(e) => setAppUrl({ ...appUrl, frontend_url: e.target.value })}
                                                        disabled={!canUpdateSettings || savingUrl}
                                                        placeholder="https://erp.example.com"
                                                        className="flex-1 bg-[var(--input-bg)] border border-[var(--border)] px-3 py-2 rounded-xl text-[12px] font-medium outline-none focus:bg-[var(--bg-card)] focus:border-[var(--accent-indigo)] disabled:opacity-50"
                                                    />
                                                    {canUpdateSettings && (
                                                        <button
                                                            onClick={handleSaveAppUrl}
                                                            disabled={savingUrl}
                                                            className="bg-[var(--accent-indigo)] text-white px-6 rounded-xl font-black text-[10px] uppercase tracking-widest disabled:opacity-50"
                                                        >
                                                            {savingUrl ? 'Saving…' : 'Save URL'}
                                                        </button>
                                                    )}
                                                </div>
                                                <p className="text-[10px] font-medium text-[var(--text-muted)]">
                                                    Include http:// or https:// and no trailing slash. Leave blank to fall back to
                                                    the server's FRONTEND_URL environment variable.
                                                </p>
                                            </div>

                                            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[var(--border)]">
                                                <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mt-3">
                                                    Links are being built as
                                                </span>
                                                <code className="mt-3 text-[11px] font-bold text-[var(--text-main)] bg-[var(--input-bg)] border border-[var(--border)] px-2 py-1 rounded-lg break-all">
                                                    {appUrl.effective_url || '—'}/f/&lt;token&gt;
                                                </code>
                                                <span className={`mt-3 text-[9px] font-black uppercase tracking-widest px-2 py-1 rounded-full border ${
                                                    appUrl.source === 'settings'
                                                        ? 'text-[var(--accent-green)] bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]'
                                                        : 'text-amber-600 bg-amber-50 border-amber-200'}`}>
                                                    {appUrl.source === 'settings' ? 'from settings'
                                                        : appUrl.source === 'environment' ? 'from environment'
                                                        : 'development default'}
                                                </span>
                                            </div>

                                            {appUrl.source !== 'settings' && appUrl.effective_url === appUrl.default_url && (
                                                <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10.5px] font-bold text-amber-700">
                                                    <span>
                                                        Emails are going out with a localhost address, which only opens on the
                                                        machine running this server. Set the public address above.
                                                    </span>
                                                </div>
                                            )}
                                        </div>

                                        <div className="flex items-center justify-between pt-2">
                                            <div>
                                                <h2 className="text-[15px] font-bold text-[var(--text-main)] tracking-tight">System Permissions</h2>
                                                <p className="text-[11px] font-medium text-[var(--text-muted)] italic">Global overrides and security exception logic.</p>
                                            </div>
                                            {canUpdateSettings && (
                                                <button onClick={handleSave} className="bg-[var(--accent-indigo)] text-white px-6 py-2 rounded-xl font-black text-[11px] shadow-lg shadow-indigo-500/20 uppercase tracking-widest">
                                                    Save Config
                                                </button>
                                            )}
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            {/* Toggle Block */}
                                            <div className="p-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] flex items-center justify-between shadow-sm">
                                                <div className="space-y-1">
                                                    <h3 className="text-[13px] font-black text-[var(--text-main)]">Allow History Creation</h3>
                                                    <p className="text-[10px] font-medium text-[var(--text-muted)] max-w-sm">Enable session/task scheduling in the past.</p>
                                                </div>
                                                <div className="cursor-pointer" onClick={() => canUpdateSettings && setConfig({...config, allow_backdate: !config.allow_backdate})}>
                                                    {config.allow_backdate ? <ToggleOn size={32} className="text-[var(--accent-indigo)]" /> : <ToggleOff size={32} className="text-gray-200" />}
                                                </div>
                                            </div>

                                            {/* Exception Block */}
                                            <div className="p-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] space-y-4 shadow-sm">
                                                <div className="space-y-1">
                                                    <h3 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">Access Whitelist</h3>
                                                    <p className="text-[10px] font-medium text-[var(--text-muted)]">Users with permanent backdate permission.</p>
                                                </div>

                                                <div className="flex gap-2">
                                                    <input placeholder="Auth email..." value={newEmail} onChange={e => setNewEmail(e.target.value)} disabled={!canUpdateSettings}
                                                        className="flex-1 bg-[var(--input-bg)] border border-[var(--border)] px-3 py-2 rounded-xl text-[12px] font-medium outline-none focus:bg-[var(--bg-card)] focus:border-[var(--accent-indigo)] disabled:opacity-50" />
                                                    <button onClick={() => { if(newEmail) setConfig({...config, exception_users: [...config.exception_users, newEmail]}); setNewEmail(''); }}
                                                        disabled={!canUpdateSettings}
                                                        className="bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] px-4 rounded-xl font-black text-[10px] uppercase tracking-widest border border-[var(--accent-indigo-border)] disabled:opacity-50">
                                                        Authorize
                                                    </button>
                                                </div>

                                                <div className="space-y-2 max-h-40 overflow-y-auto no-scrollbar">
                                                    {config.exception_users.map(email => (
                                                        <div key={email} className="flex items-center justify-between p-2 bg-[var(--input-bg)] rounded-xl group border border-transparent">
                                                            <span className="text-[11px] font-bold text-[var(--text-main)]">{email}</span>
                                                            <button onClick={() => setConfig({...config, exception_users: config.exception_users.filter(e => e !== email)})} className="text-gray-300 hover:text-red-500 transition-all"><Trash2 size={12}/></button>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {section === 'categories' && (
                            <MetaListSection
                                title="Categories"
                                subtitle="Task categories used across the workspace."
                                endpoint="/task-categories"
                                icon={FolderTree}
                                canManage={canManageMeta}
                                label="Category"
                            />
                        )}

                        {section === 'tags' && (
                            <MetaListSection
                                title="Tags"
                                subtitle="Task tags used across the workspace."
                                endpoint="/task-tags"
                                icon={Tag}
                                canManage={canManageMeta}
                                label="Tag"
                            />
                        )}
                    </div>
                )}
            </main>

        </div>
    );
};

export default SettingsPage;
