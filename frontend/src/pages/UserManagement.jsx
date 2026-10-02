import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  Users, UserPlus, Search, Filter,
  MoreVertical, Shield, Mail, Phone,
  ChevronRight, BadgeCheck, XCircle, Clock,
  ArrowUpRight, Building2, UserCircle2,
  ChevronDown, Check, Network
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

// Lightweight inline searchable select used for the Reporting Manager picker.
// No reusable SearchableSelect exists in the repo, so this keeps markup/styling
// consistent with the surrounding form inputs.
const SearchableSelect = ({ options, value, onChange, placeholder = 'Select...' }) => {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const wrapRef = React.useRef(null);

    const selected = options.find(o => o.value === value);

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) {
                setOpen(false);
                setQuery('');
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const filtered = options.filter(o => {
        const q = query.toLowerCase();
        return (
            o.label.toLowerCase().includes(q) ||
            (o.subtitle || '').toLowerCase().includes(q)
        );
    });

    return (
        <div className="relative" ref={wrapRef}>
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between gap-2 bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold text-left"
            >
                <span className={`truncate ${selected ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}`}>
                    {selected ? selected.label : placeholder}
                </span>
                <ChevronDown size={16} className={`shrink-0 text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>

            {open && (
                <div className="absolute z-50 mt-2 w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden">
                    <div className="p-2 border-b border-[var(--border)]">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={14} />
                            <input
                                autoFocus
                                value={query}
                                onChange={e => setQuery(e.target.value)}
                                placeholder="Search manager..."
                                className="w-full pl-9 pr-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none"
                            />
                        </div>
                    </div>
                    <div className="max-h-52 overflow-y-auto no-scrollbar py-1">
                        {filtered.length === 0 && (
                            <div className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">No matches</div>
                        )}
                        {filtered.map(o => (
                            <button
                                type="button"
                                key={o.value || 'none'}
                                onClick={() => { onChange(o.value); setOpen(false); setQuery(''); }}
                                className="w-full flex items-center justify-between gap-2 px-4 py-2.5 text-left hover:bg-[var(--input-bg)] transition-colors"
                            >
                                <span className="min-w-0">
                                    <span className="block text-[13px] font-black text-[var(--text-main)] truncate">{o.label}</span>
                                    {o.subtitle && (
                                        <span className="block text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wide truncate">{o.subtitle}</span>
                                    )}
                                </span>
                                {o.value === value && <Check size={16} className="shrink-0 text-[var(--accent-indigo)]" />}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

const UserManagement = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [filterRole, setFilterRole] = useState('All');
    const [isSaving, setIsSaving] = useState(false);
    const [showAddModal, setShowAddModal] = useState(false);
    
    const canCreate = user?.role === 'superadmin' || user?.permissions?.users?.create;
    const _canRead = user?.role === 'superadmin' || user?.permissions?.users?.read;
    
    const initialStaffForm = {
        first_name: '', last_name: '', email: '', password: '',
        mobile: '', role: 'coach', is_active: true,
        session_type: 'Both', department: 'Other',
        reporting_manager: '', level: '',
        permissions: {
            batches: { create: false, read: true, update: false, delete: false },
            calendar: { create: false, read: true, update: false, delete: false },
            users: { create: false, read: true, update: false, delete: false },
            companies: { create: false, read: true, update: false, delete: false },
            logs: { create: false, read: true, update: false, delete: false },
            templates: { create: false, read: true, update: false, delete: false }
        }
    };
    const [staffForm, setStaffForm] = useState(initialStaffForm);
    const [managerOptions, setManagerOptions] = useState([]);


    const fetchData = async () => {
        try {
            const res = await api.get('/users');
            // Filter only internal Staff roles. Must match the roles the Add-Staff form can
            // create (coach/admin/staff/superadmin) — 'staff' ("Team Staff") was missing here,
            // so newly-added Team Staff users were saved but hidden from this list.
            const staffRoles = ['superadmin', 'admin', 'coach', 'staff'];
            const staff = res.data.filter(u => staffRoles.includes(u.role?.toLowerCase()));
            setUsers(staff);
        } catch (err) {
            console.error("Fetch staff error:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    // Fetch reporting-manager options for INTERNAL staff (no company_id => all active staff).
    const fetchManagerOptions = async () => {
        try {
            const res = await api.get('/users/reporting-manager-options');
            const opts = (res.data || []).map(m => ({
                value: m._id,
                label: m.full_name || m.email,
                subtitle: [m.role, m.designation].filter(Boolean).join(' • ')
            }));
            setManagerOptions([{ value: '', label: '— None —', subtitle: '' }, ...opts]);
        } catch (err) {
            console.error("Fetch reporting-manager options error:", err);
            setManagerOptions([{ value: '', label: '— None —', subtitle: '' }]);
        }
    };

    useEffect(() => {
        if (showAddModal) fetchManagerOptions();
    }, [showAddModal]);

    const filteredUsers = users.filter(u => {
        const matchesSearch = (u.full_name || u.name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                             (u.email || '').toLowerCase().includes(searchTerm.toLowerCase());
        const matchesRole = filterRole === 'All' || u.role?.toLowerCase() === filterRole.toLowerCase();
        return matchesSearch && matchesRole;
    });

    const handleAddStaff = async (e) => {
        e.preventDefault();
        setIsSaving(true);
        try {
            await api.post('/auth/register', staffForm);
            showSuccess("Staff registration successful. Email dispatched.");
            setShowAddModal(false);
            setStaffForm(initialStaffForm);
            fetchData();
        } catch (err) {
            if (err.response?.status !== 403) {
                showError(err.response?.data?.detail || "Registration failed");
            }
        } finally {
            setIsSaving(false);
        }
    };


    return (
        <div className="space-y-8 pb-10">
            {/* Header section */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                   <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Staff Management</h1>
                   <p className="text-[14px] text-[var(--text-muted)] font-bold italic">Oversee core team members, coaches, and system administrators.</p>
                </div>
                {canCreate && (
                    <button onClick={() => setShowAddModal(true)} className="flex items-center gap-2 px-6 py-3 bg-[var(--btn-primary)] text-white rounded-2xl text-[14px] font-black shadow-xl shadow-indigo-500/20 hover:scale-[1.02] transition-all active:scale-95">
                        <UserPlus size={18}/> Add New Staff
                    </button>
                )}
            </div>

            {/* Filters Bar */}
            <div className="flex flex-col md:flex-row items-center gap-4 bg-[var(--bg-card)] p-4 rounded-[24px] border border-[var(--border)] shadow-sm">
                <div className="relative w-full md:flex-1 group">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] transition-colors group-focus-within:text-[var(--accent-indigo)]" size={18} />
                    <input 
                        placeholder="Search by name or email..." 
                        className="w-full pl-12 pr-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[14px] font-bold text-[var(--text-main)] focus:border-[var(--accent-indigo)] outline-none transition-all"
                        value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
                    />
                </div>
                <div className="flex items-center gap-2 overflow-x-auto no-scrollbar w-full md:w-auto justify-start md:justify-end pb-1 md:pb-0">
                    {['All', 'Superadmin', 'Admin', 'Coach'].map(role => (
                        <button key={role} onClick={() => setFilterRole(role)}
                            className={`px-6 py-2.5 rounded-xl text-[12px] font-black transition-all border shrink-0 ${filterRole === role ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-lg shadow-indigo-200' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                            {role}
                        </button>
                    ))}
                </div>
            </div>

            {/* Staff Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <AnimatePresence>
                    {filteredUsers.map((u, i) => (
                        <motion.div 
                            layout initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                            key={u._id} onClick={() => navigate(`/admin/users/${u._id}`)}
                            className="bg-[var(--bg-card)] rounded-[28px] border border-[var(--border)] p-6 hover:shadow-2xl hover:shadow-black/5 hover:-translate-y-1 transition-all cursor-pointer group relative overflow-hidden"
                        >
                            <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-br from-[var(--accent-indigo)] to-transparent opacity-0 group-hover:opacity-10 transition-opacity rounded-bl-full" />
                            
                            <div className="flex items-start justify-between mb-6">
                                <div className="flex items-center gap-4">
                                    <div className="w-14 h-14 rounded-2xl bg-[var(--input-bg)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] group-hover:scale-110 transition-all overflow-hidden relative">
                                        <UserCircle2 size={32} />
                                        <div className={`absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-white ${u.is_active !== false ? 'bg-green-500' : 'bg-red-500'}`} />
                                    </div>
                                    <div>
                                        <h3 className="text-[16px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors">{u.full_name || u.name}</h3>
                                        <div className="flex items-center gap-1.5 p-0.5 rounded-lg text-[var(--accent-indigo)] text-[9px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] w-fit mt-1 px-2 border border-[var(--accent-indigo-border)]">
                                            <Shield size={10}/> {u.role}
                                        </div>
                                    </div>
                                </div>
                                <button className="p-2 text-[var(--text-muted)] hover:bg-[var(--input-bg)] rounded-xl transition-all"> <MoreVertical size={18}/> </button>
                            </div>

                            <div className="space-y-3 pt-4 border-t border-[var(--border)] border-dashed">
                                <div className="flex items-center gap-3 text-[var(--text-muted)] group-hover:text-[var(--text-main)] transition-colors">
                                    <Mail size={16} /> <span className="text-[12px] font-bold truncate">{u.email}</span>
                                </div>
                                <div className="flex items-center gap-3 text-[var(--text-muted)] group-hover:text-[var(--text-main)] transition-colors">
                                    <Phone size={16} /> <span className="text-[12px] font-bold">{u.mobile || 'No contact set'}</span>
                                </div>
                            </div>

                            <div className="mt-6 flex items-center justify-between">
                                <div className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                    <Clock size={12}/> Joined {new Date(u.created_at || Date.now()).toLocaleDateString([], { month: 'short', year: 'numeric' })}
                                </div>
                                <div className="p-2 bg-[var(--input-bg)] rounded-xl text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] group-hover:bg-[var(--accent-indigo-bg)] transition-all">
                                    <ChevronRight size={18} />
                                </div>
                            </div>
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            {loading && (
                <div className="flex flex-col items-center justify-center py-20 gap-4 opacity-50">
                    <div className="w-10 h-10 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                    <p className="font-black uppercase text-[12px] tracking-widest animate-pulse">Syncing Staff Records...</p>
                </div>
            )}

            {/* Registration Modal */}
            <AnimatePresence>
                {showAddModal && (
                    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowAddModal(false)} className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[650px] rounded-[40px] shadow-2xl relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[90vh]"
                        >
                            <div className="flex px-8 py-6 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-main)]">
                                 <h2 className="text-xl font-black text-[var(--text-main)]">Register New Team Member</h2>
                                 <button onClick={() => setShowAddModal(false)} className="p-2 text-[var(--text-muted)] hover:bg-gray-100 rounded-xl transition-all"> <XCircle size={24} /> </button>
                            </div>

                            <form onSubmit={handleAddStaff} className="p-8 overflow-y-auto no-scrollbar space-y-6">
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">First Name</label>
                                        <input required className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold" value={staffForm.first_name} onChange={e => setStaffForm({...staffForm, first_name: e.target.value})} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">Last Name</label>
                                        <input className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold" value={staffForm.last_name} onChange={e => setStaffForm({...staffForm, last_name: e.target.value})} />
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">Email Identity</label>
                                        <input required type="email" className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold" value={staffForm.email} onChange={e => setStaffForm({...staffForm, email: e.target.value})} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">Security Passcode</label>
                                        <input required type="password" placeholder="Min 8 characters" className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold" value={staffForm.password} onChange={e => setStaffForm({...staffForm, password: e.target.value})} />
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">Direct Contact</label>
                                        <input type="tel" className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-bold" value={staffForm.mobile} onChange={e => setStaffForm({...staffForm, mobile: e.target.value})} />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2">Strategic Role</label>
                                        <select className="w-full bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] text-[13px] font-black uppercase" value={staffForm.role} onChange={e => setStaffForm({...staffForm, role: e.target.value})}>
                                            <option value="coach">Coach</option>
                                            <option value="admin">Admin</option>
                                            <option value="staff">Team Staff</option>
                                            <option value="superadmin">SuperAdmin</option>
                                        </select>
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2 flex items-center gap-1.5">
                                            <Network size={12} className="text-[var(--accent-indigo)]" /> Reporting Manager
                                        </label>
                                        <SearchableSelect
                                            options={managerOptions}
                                            value={staffForm.reporting_manager}
                                            onChange={val => setStaffForm({ ...staffForm, reporting_manager: val })}
                                            placeholder="— None —"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase px-2 flex items-center gap-1.5">
                                            <Shield size={12} className="text-[var(--accent-indigo)]" /> Hierarchy Level
                                        </label>
                                        <input className="w-full bg-[var(--input-bg)] px-5 py-3 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="e.g. L1, L2, Manager" value={staffForm.level || ''} onChange={e => setStaffForm({ ...staffForm, level: e.target.value })} />
                                    </div>
                                </div>

                                <div className="space-y-3 bg-[var(--bg-main)] p-6 rounded-[28px] border border-dashed border-[var(--border)]">
                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2 group"> <BadgeCheck size={14} className="text-[var(--accent-indigo)]"/> Access Management (Scope)</label>
                                    <div className="space-y-4">
                                        {[
                                            { id: 'batches', label: 'Batch Access' },
                                            { id: 'calendar', label: 'Calendar Admin' },
                                            { id: 'users', label: 'User Management' },
                                            { id: 'companies', label: 'Company Oversight' },
                                            { id: 'logs', label: 'Log Access' },
                                            { id: 'templates', label: 'Template Designer' }
                                        ].map(mod => (
                                            <div key={mod.id} className="flex flex-col sm:flex-row sm:items-center justify-between p-3 gap-3 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] group">
                                                <span className="text-[11px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)]">{mod.label}</span>
                                                <div className="flex flex-wrap items-center gap-4">
                                                    {['create', 'read', 'update', 'delete'].map(action => (
                                                        <label key={action} className="flex items-center gap-1.5 cursor-pointer">
                                                            <input type="checkbox" 
                                                                checked={staffForm.permissions[mod.id]?.[action]} 
                                                                onChange={e => {
                                                                    const updated = { ...staffForm.permissions };
                                                                    updated[mod.id] = { ...updated[mod.id], [action]: e.target.checked };
                                                                    setStaffForm({ ...staffForm, permissions: updated });
                                                                }}
                                                                className="w-3.5 h-3.5 accent-[var(--accent-indigo)]"
                                                            />
                                                            <span className="text-[9px] font-black uppercase text-[var(--text-muted)]">{action[0]}</span>
                                                        </label>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="flex items-center justify-between pt-4 border-t border-[var(--border)]">
                                    <div className="flex items-center gap-3">
                                        <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                                        <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Auto-set to Active Status</span>
                                    </div>
                                    <button disabled={isSaving} className={`bg-[var(--btn-primary)] text-white px-10 py-3 rounded-2xl text-[13px] font-black shadow-2xl transition-all ${isSaving ? 'opacity-50' : 'hover:scale-[1.02] active:scale-[0.98]'}`}>
                                        {isSaving ? 'AUTHORIZING...' : 'AUTHORIZE REGISTRATION'}
                                    </button>
                                </div>
                            </form>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>

        </div>
    );
};

export default UserManagement;
