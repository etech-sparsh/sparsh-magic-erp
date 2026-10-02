import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {
  Copy, Plus, Search, Trash2, Pencil, ExternalLink,
  MessageSquare, Hash, FileText, XCircle, LayoutGrid, List
} from 'lucide-react';

import { useAuth } from '../context/AuthContext';
import { motion } from 'framer-motion';

const SessionTemplateManagement = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();
    const [templates, setTemplates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [editTemplate, setEditTemplate] = useState(null);

    const [viewMode, setViewMode] = useState(() => localStorage.getItem('templatesViewMode') || 'card');
    
    useEffect(() => {
        localStorage.setItem('templatesViewMode', viewMode);
    }, [viewMode]);

    const [form, setForm] = useState({
        title: '', topic: '', description: ''
    });

    const canCreate = user?.role === 'superadmin' || user?.permissions?.templates?.create;
    const canUpdate = user?.role === 'superadmin' || user?.permissions?.templates?.update;
    const canDelete = user?.role === 'superadmin' || user?.permissions?.templates?.delete;

    const fetchData = async () => {
        try {
            const res = await api.get('/session-templates');
            setTemplates(res.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    useEffect(() => { fetchData(); }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editTemplate) {
                await api.put(`/session-templates/${editTemplate._id}`, form);
            } else {
                await api.post('/session-templates', form);
            }
            setShowCreate(false);
            setEditTemplate(null);
            setForm({ title: '', topic: '', description: '' });
            showSuccess(editTemplate ? "Template updated" : "Template created");
            fetchData();
        } catch (err) { showError('Failed to save template'); }
    };

    const handleDelete = async (id) => {
        try {
            await api.delete(`/session-templates/${id}`);
            showSuccess("Template deleted");
            fetchData();
        } catch (err) { showError('Delete failed'); }
    };

    const openEdit = (t) => {
        setEditTemplate(t);
        setForm({ title: t.title, topic: t.topic, description: t.description || '' });
        setShowCreate(true);
    };

    const filtered = templates.filter(t => 
        t.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        t.topic.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">Session Templates</h1>
                    <p className="text-[13px] text-[var(--text-muted)] font-medium">Define reusable session structures for your batches.</p>
                </div>
                {canCreate && (
                    <button onClick={() => { setEditTemplate(null); setForm({ title: '', topic: '', description: '' }); setShowCreate(true); }} 
                        className="h-10 px-4 bg-[var(--btn-primary)] hover:bg-[var(--btn-primary-hover)] text-white font-bold text-[13px] rounded-lg flex items-center gap-2 transition-all shadow-sm">
                        <Plus size={16} /> New Template
                    </button>
                )}
            </div>

            {/* Search */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] p-3 rounded-xl flex items-center gap-4 shadow-sm">
                <div className="flex-1 relative">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                    <input type="text" placeholder="Search templates by title or topic..." className="w-full pl-9 pr-4 h-9 bg-[var(--input-bg)] border border-transparent rounded-lg outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all"
                        value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} />
                </div>
                <div className="flex items-center gap-1 p-1 bg-[var(--bg-main)] rounded-lg border border-[var(--border)]">
                    <button onClick={() => setViewMode('card')}
                        className={`p-1.5 rounded-md transition-all ${viewMode === 'card' ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                        <LayoutGrid size={16} />
                    </button>
                    <button onClick={() => setViewMode('list')}
                        className={`p-1.5 rounded-md transition-all ${viewMode === 'list' ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                        <List size={16} />
                    </button>
                </div>
            </div>

            {/* Grid */}
            {loading ? (
                <div className="py-20 flex flex-col items-center justify-center">
                    <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
                </div>
            ) : viewMode === 'card' ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filtered.map(t => (
                        <motion.div key={t._id} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                            className="bg-[var(--bg-card)] border border-[var(--border)] p-5 rounded-2xl hover:border-[var(--accent-indigo-border)] transition-all group relative overflow-hidden shadow-sm">
                            <div className="flex items-start justify-between mb-4">
                                <div className="w-10 h-10 bg-[var(--accent-indigo-bg)] rounded-xl flex items-center justify-center text-[var(--accent-indigo)]">
                                    <Copy size={20} />
                                </div>
                                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                                    {canUpdate && <button onClick={() => openEdit(t)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all"><Pencil size={14} /></button>}
                                    {canDelete && <button onClick={() => handleDelete(t._id)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-md transition-all"><Trash2 size={14} /></button>}
                                </div>
                            </div>
                            <h3 className="text-[15px] font-bold text-[var(--text-main)] mb-1 tracking-tight">{t.title}</h3>
                            <div className="flex items-center gap-1.5 mb-3">
                                <Hash size={12} className="text-[var(--accent-orange)]" />
                                <span className="text-[11px] font-bold text-[var(--accent-orange)] uppercase tracking-wider">{t.topic}</span>
                            </div>
                            <p className="text-[12px] text-[var(--text-muted)] leading-relaxed line-clamp-3 mb-4">
                                {t.description || 'No description provided.'}
                            </p>
                            <div className="pt-4 border-t border-[var(--border)] flex items-center justify-between text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
                                <span>{new Date(t.created_at).toLocaleDateString()}</span>
                                <button onClick={() => navigate(`/session-templates/${t._id}`)} className="flex items-center gap-1 text-[var(--accent-indigo)] hover:underline"><ExternalLink size={10} /> View Details</button>
                            </div>
                        </motion.div>
                    ))}
                    {filtered.length === 0 && (
                         <div className="col-span-full py-20 text-center">
                            <XCircle size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
                            <p className="text-[13px] text-[var(--text-muted)]">No templates found.</p>
                        </div>
                    )}
                </div>
            ) : (
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl overflow-hidden shadow-sm">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="bg-[var(--bg-main)] border-b border-[var(--border)]">
                                    <th className="px-6 py-4 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Template Title</th>
                                    <th className="px-6 py-4 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Topic</th>
                                    <th className="px-6 py-4 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Created Date</th>
                                    <th className="px-6 py-4 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {filtered.map(t => (
                                    <tr key={t._id} className="hover:bg-[var(--bg-main)] transition-all group">
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 bg-[var(--accent-indigo-bg)] rounded-lg flex items-center justify-center text-[var(--accent-indigo)]">
                                                    <Copy size={14} />
                                                </div>
                                                <span className="text-[13px] font-bold text-[var(--text-main)]">{t.title}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-1.5">
                                                <Hash size={10} className="text-[var(--accent-orange)]" />
                                                <span className="text-[11px] font-bold text-[var(--accent-orange)] uppercase tracking-wider">{t.topic}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 text-[12px] text-[var(--text-muted)] font-medium">
                                            {new Date(t.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex items-center justify-end gap-2">
                                                <button onClick={() => navigate(`/session-templates/${t._id}`)} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Details"><ExternalLink size={14} /></button>
                                                {canUpdate && <button onClick={() => openEdit(t)} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="Edit"><Pencil size={14} /></button>}
                                                {canDelete && <button onClick={() => handleDelete(t._id)} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-md transition-all" title="Delete"><Trash2 size={14} /></button>}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {filtered.length === 0 && (
                                    <tr>
                                        <td colSpan="4" className="py-20 text-center">
                                            <XCircle size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
                                            <p className="text-[13px] text-[var(--text-muted)]">No templates found.</p>
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Modal */}
            <Modal isOpen={showCreate} onClose={() => setShowCreate(false)} title={editTemplate ? "Edit Template" : "Create New Session Template"}>
                <form onSubmit={handleSubmit} className="space-y-4 px-1">
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Title *</label>
                        <input required placeholder="e.g. Sales Foundations" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
                            value={form.title} onChange={e => setForm({...form, title: e.target.value})} />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Topic / Category *</label>
                        <input required placeholder="e.g. Sales, Mindset, Operations" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
                            value={form.topic} onChange={e => setForm({...form, topic: e.target.value})} />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Description</label>
                        <textarea rows={4} placeholder="Key talking points or objectives..." className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none resize-none"
                            value={form.description} onChange={e => setForm({...form, description: e.target.value})} />
                    </div>
                    <button type="submit" className="w-full py-2 bg-[var(--btn-primary)] text-white rounded-lg text-[13px] font-bold hover:bg-[var(--btn-primary-hover)] transition-all mt-2 shadow-sm">
                        {editTemplate ? "Save Changes" : "Create Template"}
                    </button>
                </form>
            </Modal>
        </div>
    );
};

export default SessionTemplateManagement;
