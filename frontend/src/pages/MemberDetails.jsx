import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import {
  UserCircle2, Shield, Mail, Phone, Clock,
  ChevronLeft, Edit3, Trash2, CheckCircle2,
  XCircle, History, Zap,
  Lock, Settings2, Save, X, Building2,
  Activity, Award, Layout, BookOpen, Search, ChevronDown, Layers
} from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';

// Searchable "Reporting Manager" select. `value` is a manager _id ('' = none).
const ManagerSelect = ({ value, managers, onChange }) => {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const ref = useRef(null);
    const selected = managers.find((m) => m._id === value || m.email === value);
    const filtered = managers.filter((m) =>
        `${m.full_name || ''} ${m.email || ''} ${m.designation || ''} ${m.role || ''}`
            .toLowerCase()
            .includes(query.toLowerCase())
    );

    useEffect(() => {
        const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    return (
        <div className="relative" ref={ref}>
            <button type="button" onClick={() => setOpen((o) => !o)}
                className="w-full bg-[var(--input-bg)] p-3 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)] flex items-center justify-between gap-2 text-left">
                <span className={selected || value ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}>
                    {selected ? selected.full_name : (value || '— None —')}
                </span>
                <ChevronDown size={14} className="text-[var(--text-muted)] shrink-0" />
            </button>
            {open && (
                <div className="absolute z-20 mt-2 w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden">
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border)]">
                        <Search size={14} className="text-[var(--text-muted)] shrink-0" />
                        <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search managers..."
                            className="w-full bg-transparent text-[12px] font-black outline-none" />
                    </div>
                    <div className="max-h-56 overflow-y-auto py-1">
                        <div onClick={() => { onChange(''); setOpen(false); setQuery(''); }}
                            className={`px-4 py-2.5 text-[12px] font-black cursor-pointer hover:bg-[var(--input-bg)] ${!value ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}>
                            — None —
                        </div>
                        {filtered.map((m) => (
                            <div key={m._id} onClick={() => { onChange(m._id); setOpen(false); setQuery(''); }}
                                className={`px-4 py-2.5 cursor-pointer hover:bg-[var(--input-bg)] ${value === m._id ? 'bg-[var(--accent-indigo-bg)]' : ''}`}>
                                <div className="text-[12px] font-black text-[var(--text-main)]">{m.full_name}</div>
                                <div className="text-[10px] font-bold text-[var(--text-muted)] truncate">
                                    {[m.designation || m.role, m.email].filter(Boolean).join(' • ')}
                                </div>
                            </div>
                        ))}
                        {filtered.length === 0 && (
                            <div className="px-4 py-3 text-[11px] font-black text-[var(--text-muted)] italic">No matches</div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

const MemberDetails = () => {
    const { userId } = useParams();
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [isEditing, setIsEditing] = useState(false);
    const [editForm, setEditForm] = useState({});
    const [activity, setActivity] = useState({ learnings: [], attendance: [], activities: [] });
    // reporting_manager holds a user _id; resolve to a name via the manager-options
    // endpoint scoped to this member's company.
    const [managers, setManagers] = useState([]);

    // ─── Fetching Logic ───
    const fetchData = async () => {
        try {
            const res = await api.get(`/users/${userId}`);
            setUser(res.data);
            setEditForm(res.data);
            
            // Try fetching activity log
            const actRes = await api.get(`/users/${userId}/activity`);
            setActivity(actRes.data);
        } catch (err) {
            console.error("Fetch user error:", err);
            showError("Member profile synchronization failed");
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { fetchData(); }, [userId]);

    useEffect(() => {
        if (!user?.company_id) { setManagers([]); return; }
        api.get('/users/reporting-manager-options', { params: { company_id: user.company_id, exclude: userId } })
            .then((res) => setManagers(Array.isArray(res.data) ? res.data : []))
            .catch(() => setManagers([]));
    }, [user?.company_id, userId]);

    const reportingManagerName =
        (user?.reporting_manager && (
            managers.find((m) => m._id === user.reporting_manager || m.email === user.reporting_manager)?.full_name || user.reporting_manager
        )) || '—';

    // ─── Update Logic ───
    const handleUpdate = async () => {
        try {
            const payload = { 
                ...editForm, 
                reporting_manager: editForm.reporting_manager || null,
                level: editForm.level || null 
            };
            await api.put(`/users/${userId}`, payload);
            setIsEditing(false);
            showSuccess("Neural profile updated");
            fetchData();
        } catch (err) { showError("Synchronization failed"); }
    };

    const handleToggleStatus = async () => {
        try {
            const newStatus = !user.is_active;
            await api.patch(`/users/${userId}/status`, { is_active: newStatus });
            showSuccess(`Node ${newStatus ? 'Activated' : 'Suspended'}`);
            fetchData();
        } catch (err) { 
            showError(err.response?.data?.detail || "Status toggle failed"); 
        }
    };

    const handleDelete = async () => {
        if (!window.confirm("Are you sure you want to terminate this node's access?")) return;
        try {
            await api.delete(`/users/${userId}`);
            showSuccess("Node removed from network");
            navigate('/team');
        } catch (err) { showError("Termination failed"); }
    };

    if (loading) return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 opacity-40">
            <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin" />
            <p className="font-black uppercase text-[12px] tracking-widest">Generating Digital Profile...</p>
        </div>
    );
    if (!user) return null;

    return (
        <div className="max-w-[1400px] mx-auto space-y-6 pb-10 px-4">
            {/* Header: More Integrated */}
            <div className="flex items-center justify-between py-2 border-b border-[var(--border)]">
                <button onClick={() => navigate('/team')} className="group flex items-center gap-2 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                    <ChevronLeft size={16} className="group-hover:-translate-x-0.5 transition-transform" /> Back to Team
                </button>
                <div className="flex items-center gap-2">
                    <button onClick={handleDelete} className="p-2.5 bg-red-50 text-[var(--accent-red)] border border-red-100 rounded-xl hover:bg-red-100 transition-all"> <Trash2 size={16}/></button>
                    <button onClick={() => setIsEditing(!isEditing)} className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-[12px] font-black transition-all shadow-lg ${isEditing ? 'bg-red-500 text-white' : 'bg-black text-white'}`}>
                        {isEditing ? <><X size={14}/> Cancel</> : <><Edit3 size={14}/> Modify Node</>}
                    </button>
                </div>
            </div>

            {/* Main Profile Grid - Compacted */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Left Column: Essential Profile */}
                <div className="lg:col-span-8 space-y-6">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-br from-[var(--accent-indigo)] to-transparent opacity-[0.03] rounded-bl-full group-hover:scale-110 transition-transform duration-1000" />
                        
                        <div className="flex flex-col md:flex-row items-center md:items-start gap-8 relative z-10">
                           <div className="w-32 h-32 rounded-[24px] bg-white border-2 border-[var(--input-bg)] shadow-xl flex items-center justify-center text-[var(--accent-indigo)] overflow-hidden relative shrink-0">
                               <UserCircle2 size={90} strokeWidth={1} />
                               <div className={`absolute bottom-3 right-3 w-5 h-5 rounded-full border-[3px] border-white shadow-lg ${user.is_active !== false ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                           </div>
                           
                           <div className="flex-1 space-y-4 text-center md:text-left">
                               <div className="space-y-2">
                                    {isEditing ? (
                                        <div className="space-y-3">
                                            <input className="text-2xl font-black bg-[var(--input-bg)] rounded-2xl px-6 py-3 w-full outline-none border-2 border-transparent focus:border-[var(--accent-indigo)] transition-all"
                                                value={editForm.full_name} onChange={e => setEditForm({...editForm, full_name: e.target.value})} placeholder="Node Name" />
                                            <div className="grid grid-cols-2 gap-3">
                                                <input className="bg-[var(--input-bg)] px-4 py-2.5 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)] transition-all" value={editForm.designation} onChange={e => setEditForm({...editForm, designation: e.target.value})} placeholder="Designation" />
                                                <input className="bg-[var(--input-bg)] px-4 py-2.5 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)] transition-all" value={editForm.department} onChange={e => setEditForm({...editForm, department: e.target.value})} placeholder="Department" />
                                            </div>
                                        </div>
                                    ) : (
                                        <>
                                            <div className="flex items-center justify-between">
                                                <h1 className="text-3xl font-black text-[var(--text-main)] italic uppercase leading-none">{user.full_name || user.name}</h1>
                                                <button 
                                                    onClick={handleToggleStatus}
                                                    className={`px-4 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all ${user.is_active !== false ? 'bg-rose-50 text-rose-500 border-rose-100 hover:bg-rose-500 hover:text-white' : 'bg-emerald-50 text-emerald-500 border-emerald-100 hover:bg-emerald-500 hover:text-white'}`}
                                                >
                                                    {user.is_active !== false ? 'Deactivate Node' : 'Activate Node'}
                                                </button>
                                            </div>
                                            <div className="flex flex-wrap justify-center md:justify-start gap-2 text-[11px] font-black uppercase tracking-widest">
                                                <span className="flex items-center gap-1.5 text-[var(--accent-indigo)] bg-indigo-50 px-3 py-1 rounded-lg border border-indigo-100"><Shield size={14}/> {user.role}</span>
                                                <span className={`flex items-center gap-1.5 px-3 py-1 rounded-lg border ${user.is_active !== false ? 'text-emerald-600 bg-emerald-50 border-emerald-100' : 'text-rose-600 bg-rose-50 border-rose-100'}`}>
                                                    {user.is_active !== false ? <CheckCircle2 size={14}/> : <XCircle size={14}/>} 
                                                    {user.is_active !== false ? 'Active' : 'Offline'}
                                                </span>
                                                <span className="flex items-center gap-1.5 text-[var(--text-muted)] bg-gray-50 px-3 py-1 rounded-lg border border-gray-100"><Building2 size={14}/> {user.department || 'General'}</span>
                                            </div>
                                        </>
                                    )}
                               </div>
                               
                               {!isEditing && (
                                   <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                                       <div className="bg-white/50 backdrop-blur-sm p-4 rounded-[20px] border border-[var(--border)] space-y-1 group/card hover:bg-[var(--accent-indigo)] transition-all">
                                           <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] group-hover/card:text-white/60">Digital Identity</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-black text-[14px] group-hover/card:text-white truncate"><Mail size={16} className="text-[var(--accent-indigo)] group-hover/card:text-white shrink-0" /> {user.email}</div>
                                       </div>
                                       <div className="bg-white/50 backdrop-blur-sm p-4 rounded-[20px] border border-[var(--border)] space-y-1 group/card hover:bg-black transition-all">
                                           <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] group-hover/card:text-white/60">Neural Link</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-black text-[14px] group-hover/card:text-white"><Phone size={16} className="text-black group-hover/card:text-white shrink-0" /> {user.mobile || 'Identity Pending'}</div>
                                       </div>
                                       <div className="bg-white/50 backdrop-blur-sm p-4 rounded-[20px] border border-[var(--border)] space-y-1 group/card hover:bg-[var(--accent-indigo)] transition-all">
                                           <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] group-hover/card:text-white/60">Reporting Manager</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-black text-[14px] group-hover/card:text-white truncate"><UserCircle2 size={16} className="text-[var(--accent-indigo)] group-hover/card:text-white shrink-0" /> {reportingManagerName}</div>
                                       </div>
                                       <div className="bg-white/50 backdrop-blur-sm p-4 rounded-[20px] border border-[var(--border)] space-y-1 group/card hover:bg-black transition-all">
                                           <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] group-hover/card:text-white/60">Hierarchy Level</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-black text-[14px] group-hover/card:text-white truncate"><Layers size={16} className="text-black group-hover/card:text-white shrink-0" /> {user.level || '—'}</div>
                                       </div>
                                   </div>
                               )}
                               
                               {isEditing && (
                                   <div className="space-y-4 pt-4">
                                       <div className="grid grid-cols-2 gap-3">
                                           <input className="bg-[var(--input-bg)] p-3 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)]" placeholder="Email Node" value={editForm.email || ''} onChange={e => setEditForm({...editForm, email: e.target.value})} />
                                           <input className="bg-[var(--input-bg)] p-3 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)]" placeholder="Neural Link" value={editForm.mobile || ''} onChange={e => setEditForm({...editForm, mobile: e.target.value})} />
                                       </div>
                                       <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
                                           <div className="space-y-1.5">
                                               <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em]">Reporting Manager</label>
                                               <ManagerSelect
                                                   value={editForm.reporting_manager || ''}
                                                   managers={managers}
                                                   onChange={(val) => setEditForm({ ...editForm, reporting_manager: val })}
                                               />
                                           </div>
                                           <div className="space-y-1.5">
                                               <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em]">Hierarchy Level</label>
                                               <input className="bg-[var(--input-bg)] p-3 rounded-xl text-[12px] font-black border-2 border-transparent focus:border-[var(--accent-indigo)] w-full outline-none" placeholder="e.g. L1, L2, Manager" value={editForm.level || ''} onChange={e => setEditForm({...editForm, level: e.target.value})} />
                                           </div>
                                       </div>
                                       <button onClick={handleUpdate} className="w-full bg-black text-white py-4 rounded-2xl font-black flex items-center justify-center gap-2 tracking-[0.1em] uppercase text-[12px] transition-all shadow-xl"> <Save size={16}/> Sync Registry </button>
                                   </div>
                               )}
                           </div>
                        </div>
                    </div>

                    {/* Stats/Activity Section - Compacted Row */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm">
                            <h3 className="text-base font-black text-[var(--text-main)] mb-6 flex items-center gap-2 uppercase tracking-tight"><Activity size={18} className="text-emerald-500"/> Performance</h3>
                            <div className="space-y-4">
                                <div className="p-4 bg-emerald-50/50 rounded-2xl flex items-center justify-between border border-emerald-100/50">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-emerald-100 text-emerald-600 rounded-xl flex items-center justify-center"> <Award size={20} /> </div>
                                        <div>
                                            <p className="text-[12px] font-black text-emerald-900 leading-none">Learning Quota</p>
                                        </div>
                                    </div>
                                    <span className="text-xl font-black text-emerald-600">88%</span>
                                </div>
                                <div className="p-4 bg-blue-50/50 rounded-2xl flex items-center justify-between border border-blue-100/50">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center"> <Layout size={20} /> </div>
                                        <div>
                                            <p className="text-[12px] font-black text-blue-900 leading-none">Modules Explored</p>
                                        </div>
                                    </div>
                                    <span className="text-xl font-black text-blue-600">12</span>
                                </div>
                            </div>
                        </div>

                        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm">
                            <h3 className="text-base font-black text-[var(--text-main)] mb-6 flex items-center gap-2 uppercase tracking-tight"><BookOpen size={18} className="text-indigo-500"/> Assignments</h3>
                            <div className="space-y-3 max-h-[160px] overflow-y-auto no-scrollbar">
                                {activity.learners?.length > 0 ? activity.learners.map((l, i) => (
                                    <div key={i} className="flex items-center justify-between p-3 bg-[var(--input-bg)] rounded-xl group hover:bg-white transition-colors">
                                        <p className="text-[11px] font-black text-[var(--text-main)] italic uppercase line-clamp-1">{l.title || 'Module'}</p>
                                        <span className="text-[9px] font-black text-[var(--accent-indigo)] px-1.5 py-0.5 bg-indigo-50 rounded-md shrink-0">{l.score}%</span>
                                    </div>
                                )) : (
                                    <div className="py-6 text-center opacity-20 italic">
                                        <Clock size={24} className="mx-auto mb-1" />
                                        <p className="text-[9px] font-black uppercase">No active data</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Column: Insights & Activity Log */}
                <div className="lg:col-span-4 space-y-6">
                    <div className="bg-black text-white rounded-[32px] p-6 shadow-xl relative overflow-hidden group">
                        <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/10 to-transparent pointer-events-none" />
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-black tracking-tight uppercase italic underline decoration-indigo-500 decoration-2 underline-offset-4">Node Insights</h3>
                            <Zap size={24} className="text-indigo-400 group-hover:scale-125 transition-transform duration-500" />
                        </div>
                        <p className="text-[12px] font-medium opacity-60 leading-relaxed mb-8">Performance optimization and behavioral consistency within the ecosystem.</p>
                        
                        <div className="space-y-4 pt-4 border-t border-white/10">
                            <div className="flex items-center justify-between">
                                <span className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40">Auth</span>
                                <span className="text-[11px] font-black text-indigo-400">JWT SECURED</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40">Sync</span>
                                <span className="text-[11px] font-black text-emerald-400">ACTIVE</span>
                            </div>
                        </div>
                    </div>

                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm">
                        <h3 className="text-base font-black text-[var(--text-main)] mb-6 flex items-center gap-2 uppercase tracking-tight"><History size={16} className="text-[var(--accent-indigo)]"/> Neural Log</h3>
                        <div className="space-y-6 relative ml-3 border-l-2 border-[var(--border)] border-dashed pl-6 pb-2">
                             {activity.activities?.length > 0 ? activity.activities.map((act, i) => (
                                <div key={i} className="relative group">
                                    <div className="absolute -left-[31px] top-1.5 w-3 h-3 bg-white border-[3px] border-[var(--accent-indigo)] rounded-full z-10 group-hover:scale-125 transition-all shadow-md" />
                                    <div className="space-y-0.5">
                                        <p className="text-[12px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors leading-tight">{act.action}</p>
                                        <p className="text-[9px] font-bold text-[var(--text-muted)] opacity-50 uppercase">{new Date(act.timestamp).toLocaleDateString()}</p>
                                    </div>
                                </div>
                             )) : (
                                <div className="py-10 text-center opacity-10 italic -ml-6">
                                    <Clock size={24} className="mx-auto mb-1" />
                                    <p className="text-[9px] font-black uppercase">No logs</p>
                                </div>
                             )}
                        </div>
                        <button className="w-full mt-4 py-3 bg-[var(--input-bg)] rounded-2xl text-[10px] font-black text-[var(--text-muted)] hover:text-black hover:bg-white border border-transparent hover:border-[var(--border)] transition-all uppercase tracking-widest">Behavioral Audit</button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MemberDetails;
