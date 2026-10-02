import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
    ShieldCheck, Search, User, Building2, 
    Trash2, Plus, ArrowLeft, Bot, 
    CheckCircle2, AlertCircle, X, Info
} from 'lucide-react';

const GptAccessControl = () => {
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();
    const [projects, setProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState(null);
    const [permissions, setPermissions] = useState([]);
    const [loading, setLoading] = useState(true);
    
    // Grant Modal State
    const [showGrantModal, setShowGrantModal] = useState(false);
    const [entityType, setEntityType] = useState('user'); // 'user' or 'company'
    const [searchTerm, setSearchTerm] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const fetchData = async () => {
        try {
            const res = await api.get('/gpt/projects');
            setProjects(res.data);
            if (res.data.length > 0 && !selectedProject) {
                setSelectedProject(res.data[0]);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const fetchPermissions = async () => {
        if (!selectedProject) return;
        try {
            const res = await api.get(`/gpt/permissions?project_id=${selectedProject.id}`);
            setPermissions(res.data);
        } catch (err) {
            console.error(err);
        }
    };

    useEffect(() => { fetchData(); }, []);
    useEffect(() => { fetchPermissions(); }, [selectedProject]);

    // Search Logic
    useEffect(() => {
        const delayDebounceFn = setTimeout(() => {
            if (searchTerm.length > 2) {
                performSearch();
            } else {
                setSearchResults([]);
            }
        }, 500);
        return () => clearTimeout(delayDebounceFn);
    }, [searchTerm, entityType]);

    const performSearch = async () => {
        setIsSearching(true);
        try {
            const endpoint = entityType === 'user' ? '/users' : '/companies';
            const res = await api.get(endpoint);
            const term = searchTerm.toLowerCase();
            const filtered = res.data.filter(item => {
                if (entityType === 'user') {
                    return (item.full_name?.toLowerCase().includes(term) || item.email?.toLowerCase().includes(term));
                }
                return item.name?.toLowerCase().includes(term);
            });
            setSearchResults(filtered.slice(0, 10));
        } catch (err) {
            console.error(err);
        } finally {
            setIsSearching(false);
        }
    };

    const handleGrant = async (item) => {
        setSubmitting(true);
        try {
            await api.post('/gpt/permissions/grant', {
                project_id: selectedProject.id,
                entity_id: item._id || item.id,
                entity_type: entityType,
                name: entityType === 'user' ? (item.full_name || item.email) : item.name,
                email: item.email || ''
            });
            showSuccess(`Access granted to ${entityType === 'user' ? (item.full_name || item.email) : item.name}`);
            setShowGrantModal(false);
            setSearchTerm('');
            setSearchResults([]);
            fetchPermissions();
        } catch (err) {
            showError("Failed to grant permission");
        } finally {
            setSubmitting(false);
        }
    };

    const handleRevoke = async (permId) => {
        try {
            await api.delete(`/gpt/permissions/${permId}`);
            showSuccess("Access override revoked");
            fetchPermissions();
        } catch (err) {
            showError("Revoke failed");
        }
    };

    if (loading) return (
        <div className="flex items-center justify-center py-32">
            <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
        </div>
    );

    return (
        <div className="max-w-6xl mx-auto space-y-6 pb-20 px-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate('/gpt')} className="p-2.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight flex items-center gap-2 uppercase italic">
                            <ShieldCheck className="text-[var(--accent-indigo)]" size={24} /> Neural Access Control
                        </h1>
                        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-bold uppercase tracking-widest opacity-60">Manual override management for project-level intelligences.</p>
                    </div>
                </div>
                
                <div className="flex items-center gap-3">
                    <select 
                        value={selectedProject?.id || ''} 
                        onChange={(e) => setSelectedProject(projects.find(p => p.id === e.target.value))}
                        className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2 text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] min-w-[200px]"
                    >
                        {projects.map(p => (
                            <option key={p.id} value={p.id}>{p.title}</option>
                        ))}
                    </select>
                    <button 
                        onClick={() => setShowGrantModal(true)}
                        className="h-10 px-6 bg-[var(--accent-indigo)] text-white rounded-xl flex items-center gap-2 font-black uppercase text-[10px] tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg"
                    >
                        <Plus size={14} /> Grant Access
                    </button>
                </div>
            </div>

            {/* Permissions List */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden shadow-sm">
                <div className="px-8 py-6 border-b border-[var(--border)] flex items-center justify-between bg-indigo-50/10">
                    <div>
                        <h3 className="text-sm font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                            <Bot size={16} className="text-[var(--accent-indigo)]" /> {selectedProject?.title} <span className="text-[10px] text-[var(--text-muted)] lowercase font-medium">— active overrides</span>
                        </h3>
                    </div>
                    <div className="flex items-center gap-1.5 px-3 py-1 bg-emerald-50 text-emerald-600 rounded-lg border border-emerald-100">
                        <CheckCircle2 size={12} />
                        <span className="text-[9px] font-black uppercase tracking-widest">{permissions.length} Overrides Active</span>
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="bg-[var(--input-bg)] border-b border-[var(--border)] uppercase">
                                <th className="px-8 py-4 text-[9px] font-black tracking-widest text-[var(--text-muted)]">Authorized Entity</th>
                                <th className="px-8 py-4 text-[9px] font-black tracking-widest text-[var(--text-muted)]">Access Level</th>
                                <th className="px-8 py-4 text-[9px) font-black tracking-widest text-[var(--text-muted)]">Granted On</th>
                                <th className="px-8 py-4 text-[9px] font-black tracking-widest text-[var(--text-muted)] text-right">Operations</th>
                            </tr>
                        </thead>
                        <tbody>
                            {permissions.length > 0 ? (
                                permissions.map((perm) => (
                                    <tr key={perm.id} className="border-b border-[var(--border)] last:border-0 hover:bg-gray-50/50 transition-all group">
                                        <td className="px-8 py-4">
                                            <div className="flex items-center gap-3">
                                                <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${perm.entity_type === 'user' ? 'bg-blue-50 text-blue-600' : 'bg-amber-50 text-amber-600'}`}>
                                                    {perm.entity_type === 'user' ? <User size={18} /> : <Building2 size={18} />}
                                                </div>
                                                <div>
                                                    <p className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">{perm.name}</p>
                                                    <p className="text-[10px] text-[var(--text-muted)] font-bold">{perm.email || 'Corporate Access'}</p>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-8 py-4">
                                            <span className={`px-2.5 py-1 rounded-md text-[9px] font-black uppercase tracking-widest border ${perm.entity_type === 'user' ? 'bg-blue-50 text-blue-700 border-blue-100' : 'bg-amber-50 text-amber-700 border-amber-100'}`}>
                                                {perm.entity_type === 'user' ? 'Member Override' : 'Company Override'}
                                            </span>
                                        </td>
                                        <td className="px-8 py-4">
                                            <p className="text-[11px] font-bold text-[var(--text-muted)]">
                                                {new Date(perm.granted_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                                            </p>
                                        </td>
                                        <td className="px-8 py-4 text-right">
                                            <button 
                                                onClick={() => handleRevoke(perm.id)}
                                                className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all"
                                                title="Revoke Permission"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </td>
                                    </tr>
                                ))
                            ) : (
                                <tr>
                                    <td colSpan="4" className="px-8 py-16 text-center">
                                        <div className="flex flex-col items-center opacity-40">
                                            <Bot size={40} className="mb-3 text-[var(--text-muted)]" />
                                            <p className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest italic">No Manual Overrides Provisioned</p>
                                            <p className="text-[10px] text-[var(--text-muted)] font-bold mt-1">Default status-based locking is in effect for all users.</p>
                                        </div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Info Box */}
            <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 flex gap-4">
                <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
                    <Info size={20} />
                </div>
                <div>
                    <h4 className="text-[13px] font-black text-blue-900 uppercase tracking-tight">How Manual Overrides Work</h4>
                    <p className="text-[11px] text-blue-700 font-medium leading-relaxed mt-1">
                        Manual overrides bypass the standard status-based locking (Batch/Quarter/Session completion). 
                        Granting access to a **Member** enables it only for them. Granting to a **Company** enables 
                        access for every team member in that company regardless of their individual progress.
                    </p>
                </div>
            </div>

            {/* Grant Access Modal */}
            {showGrantModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowGrantModal(false)} />
                    <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative bg-[var(--bg-card)] border border-[var(--border)] w-full max-w-lg rounded-3xl shadow-2xl p-8 flex flex-col">
                        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
                            <h2 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2 uppercase italic tracking-tight">
                                <Plus className="text-[var(--accent-indigo)]" /> Grant Neural Access
                            </h2>
                            <button onClick={() => setShowGrantModal(false)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors p-1 bg-[var(--input-bg)] rounded-lg">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="space-y-6">
                            <div className="flex p-1 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] w-fit mx-auto">
                                <button onClick={() => setEntityType('user')} className={`px-5 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${entityType === 'user' ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>Individual Member</button>
                                <button onClick={() => setEntityType('company')} className={`px-5 py-2 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${entityType === 'company' ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>Entire Company</button>
                            </div>

                            <div className="relative">
                                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] opacity-50" size={18} />
                                <input 
                                    type="text"
                                    placeholder={entityType === 'user' ? "Search member by name or email..." : "Search company by name..."}
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    className="w-full h-12 pl-12 pr-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl focus:border-[var(--accent-indigo)] outline-none transition-all font-bold text-sm tracking-tight"
                                />
                                {isSearching && <div className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>}
                            </div>

                            <div className="space-y-2 max-h-[300px] overflow-y-auto no-scrollbar pr-2">
                                {searchResults.length > 0 ? (
                                    searchResults.map(item => (
                                        <button 
                                            key={item._id || item.id}
                                            onClick={() => handleGrant(item)}
                                            disabled={submitting}
                                            className="w-full flex items-center justify-between p-4 bg-[var(--input-bg)] border border-transparent rounded-2xl hover:border-[var(--accent-indigo)] hover:bg-white transition-all group text-left"
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${entityType === 'user' ? 'bg-blue-50 text-blue-600' : 'bg-amber-50 text-amber-600'} group-hover:scale-110 transition-transform`}>
                                                    {entityType === 'user' ? <User size={18} /> : <Building2 size={18} />}
                                                </div>
                                                <div>
                                                    <p className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">{entityType === 'user' ? (item.full_name || item.email) : item.name}</p>
                                                    <p className="text-[10px] text-[var(--text-muted)] font-bold">{item.email || item.industry || 'No email'}</p>
                                                </div>
                                            </div>
                                            <div className="w-8 h-8 rounded-full bg-white border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] group-hover:bg-[var(--accent-indigo)] group-hover:text-white transition-all">
                                                <Plus size={16} />
                                            </div>
                                        </button>
                                    ))
                                ) : searchTerm.length > 2 ? (
                                    <div className="text-center py-10 opacity-50">
                                        <AlertCircle className="mx-auto mb-2" size={24} />
                                        <p className="text-[11px] font-bold uppercase tracking-widest">No matching results found</p>
                                    </div>
                                ) : (
                                    <div className="text-center py-10 opacity-30 italic">
                                        <p className="text-[10px] font-bold uppercase tracking-widest">Type to search for entities...</p>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="mt-8 pt-6 border-t border-[var(--border)] text-center">
                            <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-[0.2em] mb-4">Target Inheritance: <span className="text-[var(--accent-indigo)]">{selectedProject?.title}</span></p>
                            <button onClick={() => setShowGrantModal(false)} className="px-8 py-2.5 text-[var(--text-muted)] font-black text-[12px] uppercase tracking-widest hover:text-[var(--text-main)] transition-colors">Close Portal</button>
                        </div>
                    </motion.div>
                </div>
            )}
        </div>
    );
};

export default GptAccessControl;
