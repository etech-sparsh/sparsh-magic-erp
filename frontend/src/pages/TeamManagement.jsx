import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
  Users, UserPlus, Search, Filter, 
  MoreVertical, Shield, Mail, Phone,
  ChevronRight, BadgeCheck, XCircle, Clock,
  ArrowUpRight, Building2, UserCircle2,
  Download, Upload, FileSpreadsheet, X, Eye
} from 'lucide-react';
import { useNotification } from '../context/NotificationContext';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

const TeamManagement = () => {
    const navigate = useNavigate();
    const { user: currentUser } = useAuth();
    const { showSuccess, showError } = useNotification();
    const [members, setMembers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [showAddModal, setShowAddModal] = useState(false);
    const [showImportModal, setShowImportModal] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [importing, setImporting] = useState(false);
    
    const initialMemberForm = {
        first_name: '', last_name: '', email: '', password: '',
        mobile: '', role: 'clientuser', is_active: true,
        designation: '', department: '', session_type: 'Both', level: ''
    };
    const [memberForm, setMemberForm] = useState(initialMemberForm);

    const fetchData = async () => {
        if (!currentUser?.company_id) return;
        setLoading(true);
        try {
            const res = await api.get(`/companies/${currentUser.company_id}/users`);
            setMembers(res.data);
        } catch (err) {
            console.error("Fetch team error:", err);
            showError("Failed to synchronize team data");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, [currentUser]);

    const filteredMembers = members.filter(u => {
        const matchesSearch = (u.full_name || u.name || u.first_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                             (u.email || '').toLowerCase().includes(searchTerm.toLowerCase());
        return matchesSearch;
    });

    const handleAddMember = async (e) => {
        e.preventDefault();
        setIsSaving(true);
        try {
            await api.post(`/companies/${currentUser.company_id}/users/bulk`, [memberForm]);
            showSuccess("Team member added successfully");
            setShowAddModal(false);
            setMemberForm(initialMemberForm);
            fetchData();
        } catch (err) {
            if (err.response?.status !== 403) {
                showError(err.response?.data?.detail || "Registration failed");
            }
        } finally {
            setIsSaving(false);
        }
    };

    const handleExportTemplate = async () => {
        try {
            const response = await api.get(`/companies/${currentUser.company_id}/users/template`, {
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `team_template_${currentUser.company_id}.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            showSuccess("Neural Template Downloaded");
        } catch (err) {
            showError("Template generation failed");
        }
    };

    const handleImportXLSX = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        setImporting(true);
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            await api.post(`/companies/${currentUser.company_id}/users/import`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            showSuccess("Bulk synchronization complete!");
            setShowImportModal(false);
            fetchData();
        } catch (err) {
            showError("Data ingestion failed");
        } finally {
            setImporting(false);
        }
    };

    const isClientUser = currentUser?.role === 'clientuser';

    return (
        <div className="space-y-8 pb-10">
            {/* Header section */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div>
                   <h1 className="text-4xl font-black text-[var(--text-main)] tracking-tight italic uppercase">Team Ecosystem</h1>
                   <p className="text-[14px] text-[var(--text-muted)] font-bold italic opacity-70">Manage your company's workforce and digital access.</p>
                </div>
                {!isClientUser && (
                    <div className="flex flex-wrap items-center gap-3">
                        <button onClick={handleExportTemplate} className="flex items-center gap-2 px-5 py-3 bg-[var(--input-bg)] text-[var(--text-main)] rounded-2xl text-[12px] font-black border border-[var(--border)] hover:bg-white transition-all">
                            <Download size={16}/> Export Template
                        </button>
                        <button onClick={() => setShowImportModal(true)} className="flex items-center gap-2 px-5 py-3 bg-[var(--input-bg)] text-[var(--text-main)] rounded-2xl text-[12px] font-black border border-[var(--border)] hover:bg-white transition-all">
                            <Upload size={16}/> Import Template
                        </button>
                        <button onClick={() => setShowAddModal(true)} className="flex items-center gap-2 px-7 py-3 bg-black text-white rounded-2xl text-[13px] font-black shadow-2xl hover:scale-105 transition-all active:scale-95">
                            <UserPlus size={18}/> Add New Member
                        </button>
                    </div>
                )}
            </div>

            {/* Interactive Filters Bar */}
            <div className="bg-[var(--bg-card)] p-4 rounded-[32px] border border-[var(--border)] shadow-sm">
                <div className="relative group">
                    <Search className="absolute left-5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] transition-colors group-focus-within:text-[var(--accent-indigo)]" size={20} />
                    <input 
                        placeholder="Search team members..." 
                        className="w-full pl-14 pr-6 py-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-[20px] text-[15px] font-bold text-[var(--text-main)] focus:border-[var(--accent-indigo)] outline-none transition-all"
                        value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
                    />
                </div>
            </div>

            {/* Team Grid - COMPACT VERSION */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                <AnimatePresence>
                    {filteredMembers.map((u, i) => (
                        <motion.div 
                            layout initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                            key={u._id}
                            className="bg-[var(--bg-card)] rounded-[32px] border border-[var(--border)] p-5 hover:shadow-xl transition-all group relative overflow-hidden flex flex-col h-full"
                        >
                            <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-indigo)] opacity-0 group-hover:opacity-[0.03] transition-opacity rounded-bl-full" />
                            
                            <div className="flex items-start justify-between mb-5">
                                <div className="flex items-center gap-3">
                                    <div className="w-12 h-12 rounded-[18px] bg-[var(--input-bg)] border-2 border-white shadow-md flex items-center justify-center text-[var(--accent-indigo)] group-hover:scale-110 transition-all overflow-hidden relative flex-shrink-0">
                                        <UserCircle2 size={28} strokeWidth={1} />
                                        <div className={`absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-white ${u.is_active !== false ? 'bg-green-500' : 'bg-red-500'}`} />
                                    </div>
                                    <div className="min-w-0">
                                        <h3 className="text-[15px] font-black text-[var(--text-main)] leading-tight">{u.full_name || `${u.first_name} ${u.last_name}`}</h3>
                                        <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest mt-0.5">{u.designation || 'Specialist'}</p>
                                    </div>
                                </div>
                                <div className="p-1.5 bg-[var(--input-bg)] rounded-xl text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] transition-all">
                                    <BadgeCheck size={16}/>
                                </div>
                            </div>

                            <div className="space-y-3 flex-1">
                                <div className="p-3 bg-[var(--input-bg)] rounded-2xl space-y-2">
                                    <div className="flex items-center gap-2 text-[var(--text-muted)]">
                                        <Mail size={14} /> <span className="text-[11px] font-black">{u.email}</span>
                                    </div>
                                    <div className="flex items-center gap-2 text-[var(--text-muted)]">
                                        <Phone size={14} /> <span className="text-[11px] font-black">{u.mobile || 'No Contact'}</span>
                                    </div>
                                </div>
                                <div className="flex items-center gap-1.5 flex-wrap">
                                    <span className="px-2 py-0.5 bg-gray-50 text-[var(--text-muted)] border border-gray-100 rounded text-[8px] font-black uppercase tracking-widest">{u.department || 'General'}</span>
                                    <span className="px-2 py-0.5 bg-indigo-50 text-[var(--accent-indigo)] border border-indigo-100 rounded text-[8px] font-black uppercase tracking-widest">{u.session_type || 'Both'}</span>
                                    <span className="px-2 py-0.5 bg-purple-50 text-purple-600 border border-purple-100 rounded text-[8px] font-black uppercase tracking-widest">{u.level ? `L: ${u.level}` : 'L: —'}</span>
                                </div>
                            </div>

                            <div className="mt-5 pt-4 border-t border-[var(--border)] border-dashed flex items-center justify-between">
                                <div className="flex flex-col">
                                    <span className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-60">Joined</span>
                                    <span className="text-[10px] font-black text-[var(--text-main)] truncate max-w-[60px]">{new Date(u.created_at || Date.now()).toLocaleDateString([], { month: 'short', year: '2-digit' })}</span>
                                </div>
                                <button 
                                    onClick={() => navigate(`/members/${u._id}`)}
                                    className="px-4 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest hover:scale-105 active:scale-95 transition-all flex items-center gap-1.5"
                                >
                                    <Eye size={12} /> Details
                                </button>
                            </div>
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            {loading && (
                <div className="flex flex-col items-center justify-center py-32 gap-6 opacity-30">
                    <div className="w-12 h-12 border-[6px] border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin" />
                    <p className="font-black uppercase text-[14px] tracking-[0.2em] italic">Synthesizing Team Grid...</p>
                </div>
            )}

            {!loading && filteredMembers.length === 0 && (
                <div className="py-40 flex flex-col items-center gap-4 opacity-20 italic">
                    <Users size={64} />
                    <p className="text-xl font-black uppercase tracking-widest">No lifeforms detected in this sector.</p>
                </div>
            )}

            {/* Registration Modal */}
            <AnimatePresence>
                {showAddModal && (
                    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowAddModal(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[650px] max-h-[90vh] rounded-[40px] shadow-2xl relative overflow-hidden flex flex-col border border-white/20"
                        >
                            <div className="px-8 py-5 border-b border-[var(--border)] flex items-center justify-between bg-[var(--bg-main)]">
                                 <div>
                                     <h2 className="text-xl font-black text-[var(--text-main)] italic uppercase">Register New Member</h2>
                                     <p className="text-[11px] font-bold text-[var(--text-muted)]">Create a new profile in your company registry.</p>
                                 </div>
                                 <button onClick={() => setShowAddModal(false)} className="p-2 text-[var(--text-muted)] hover:bg-gray-100 rounded-xl transition-all"> <X size={20} /> </button>
                             </div>

                             <form onSubmit={handleAddMember} className="p-8 overflow-y-auto space-y-5 scrollbar-thin scrollbar-thumb-gray-200">
                                 <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">First Name</label>
                                         <input required className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="e.g. Alan" value={memberForm.first_name} onChange={e => setMemberForm({...memberForm, first_name: e.target.value})} />
                                     </div>
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Last Name</label>
                                         <input className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="e.g. Turing" value={memberForm.last_name} onChange={e => setMemberForm({...memberForm, last_name: e.target.value})} />
                                     </div>
                                 </div>

                                 <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Work Email *</label>
                                         <input required type="email" className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="name@domain.com" value={memberForm.email} onChange={e => setMemberForm({...memberForm, email: e.target.value})} />
                                     </div>
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Mobile Number</label>
                                         <input className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="9876543210" value={memberForm.mobile} onChange={e => setMemberForm({...memberForm, mobile: e.target.value})} />
                                     </div>
                                 </div>

                                 <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Temp Password *</label>
                                         <input required type="password" placeholder="Set temporary password..." className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" value={memberForm.password} onChange={e => setMemberForm({...memberForm, password: e.target.value})} />
                                     </div>
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Designation</label>
                                         <input className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="e.g. Manager" value={memberForm.designation} onChange={e => setMemberForm({...memberForm, designation: e.target.value})} />
                                     </div>
                                 </div>

                                 <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Session Type</label>
                                         <select className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" value={memberForm.session_type} onChange={e => setMemberForm({...memberForm, session_type: e.target.value})}>
                                             <option value="Both">Both</option>
                                             <option value="Core">Core</option>
                                             <option value="Support">Support</option>
                                             <option value="None">None</option>
                                         </select>
                                     </div>
                                     <div className="space-y-1.5">
                                         <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Department</label>
                                         <select className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" value={memberForm.department} onChange={e => setMemberForm({...memberForm, department: e.target.value})}>
                                             <option value="">Select Department</option>
                                             <option value="HOD">HOD</option>
                                             <option value="Manager">Manager</option>
                                             <option value="Implementor">Implementor</option>
                                             <option value="EA">EA</option>
                                             <option value="MD">MD</option>
                                             <option value="HR">HR</option>
                                             <option value="Other">Other</option>
                                         </select>
                                     </div>
                                 </div>

                                 <div className="space-y-1.5">
                                     <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Level</label>
                                     <input className="w-full bg-[var(--input-bg)] px-5 py-2.5 rounded-2xl border border-[var(--border)] text-[14px] font-black focus:border-[var(--accent-indigo)] outline-none" placeholder="e.g. L1, L2, Manager" value={memberForm.level} onChange={e => setMemberForm({...memberForm, level: e.target.value})} />
                                 </div>

                                 <div className="flex items-center justify-between pt-6 border-t border-[var(--border)]">
                                     <div className="flex items-center gap-3 opacity-60">
                                         <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-sm shadow-emerald-200" />
                                         <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Immediate Activation Enabled</span>
                                     </div>
                                     <button disabled={isSaving} className={`bg-black text-white px-10 py-3.5 rounded-[20px] text-[13px] font-black shadow-2xl transition-all ${isSaving ? 'opacity-50' : 'hover:scale-[1.02] active:scale-[0.98]'}`}>
                                         {isSaving ? 'ADDING...' : 'ADD MEMBER'}
                                     </button>
                                 </div>
                             </form>\n                        </motion.div>
                    </div>
                )}
            </AnimatePresence>

            {/* Import Modal */}
            <AnimatePresence>
                {showImportModal && (
                    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowImportModal(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[500px] rounded-[48px] shadow-2xl relative overflow-hidden flex flex-col border border-white/20 p-12 text-center"
                        >
                            <div className="w-20 h-20 bg-indigo-50 text-[var(--accent-indigo)] rounded-3xl flex items-center justify-center mx-auto mb-6">
                                <FileSpreadsheet size={40} />
                            </div>
                            <h2 className="text-2xl font-black text-[var(--text-main)] italic uppercase mb-2">Bulk Neural Ingestion</h2>
                            <p className="text-[13px] font-bold text-[var(--text-muted)] mb-8">Upload your populated XLSX template to sync the entire team registry instantly.</p>
                            
                            <label className="w-full bg-[var(--input-bg)] border-2 border-dashed border-[var(--border)] rounded-[32px] p-10 flex flex-col items-center justify-center cursor-pointer hover:border-[var(--accent-indigo)] hover:bg-white transition-all group">
                                <input type="file" className="hidden" accept=".xlsx" onChange={handleImportXLSX} disabled={importing} />
                                <Upload size={32} className="text-[var(--text-muted)] mb-3 group-hover:text-[var(--accent-indigo)] group-hover:scale-110 transition-all" />
                                <span className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest group-hover:text-[var(--accent-indigo)]">
                                    {importing ? 'Processing Data...' : 'Drop XLSX Node File'}
                                </span>
                            </label>

                            <button onClick={() => setShowImportModal(false)} className="mt-8 text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest hover:text-[var(--accent-red)] transition-all">Abort Synchronization</button>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default TeamManagement;
