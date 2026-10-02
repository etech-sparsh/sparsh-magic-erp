import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
    ArrowLeft, Save, Sparkles, FileText, Plus, X, 
    Upload, FileUp, Database, Command, HelpCircle,
    CheckCircle2, AlertCircle, Trash2, Bot, Info, MessageSquare, Folders
} from 'lucide-react';

const GptEditor = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();
    const [loading, setLoading] = useState(id ? true : false);
    const [saving, setSaving] = useState(false);
    
    const [formData, setFormData] = useState({
        title: '',
        description: '',
        instruction: '',
        conversation_starters: [],
        knowledge_files: []
    });

    const [starterInput, setStarterInput] = useState('');
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [pendingFiles, setPendingFiles] = useState([]); // Files selected before project creation

    const fetchProject = async () => {
        try {
            const res = await api.get(`/gpt/projects/${id}`);
            setFormData(res.data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (id) fetchProject();
    }, [id]);

    const handleFileUpload = async (e, isPending = false) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        if (!id || isPending) {
            // Queue files for upload after save
            setPendingFiles(prev => [...prev, ...files]);
            return;
        }

        // Direct upload for existing project
        setUploading(true);
        setUploadProgress(0);
        
        let completedCount = 0;
        for (const file of files) {
            const uploadData = new FormData();
            uploadData.append('file', file);
            try {
                await api.post(`/gpt/projects/${id}/upload-knowledge`, uploadData, {
                    onUploadProgress: (progressEvent) => {
                        const fileProgress = (progressEvent.loaded / progressEvent.total) * 100;
                        // For simplicity, overall progress is (completed + current) / total
                        const overall = ((completedCount + (fileProgress / 100)) / files.length) * 100;
                        setUploadProgress(Math.round(overall));
                    }
                });
                completedCount++;
            } catch (err) {
                console.error("Upload failed for", file.name);
                showError(`Failed to upload ${file.name}`);
            }
        }
        setUploading(false);
        setUploadProgress(100);
        fetchProject();
        showSuccess("All files synchronized!");
    };

    const handleSave = async () => {
        if (!formData.title || !formData.instruction) {
            showError("Title and Instructions are required!");
            return;
        }

        setSaving(true);
        try {
            let projectId = id;
            if (id) {
                await api.patch(`/gpt/projects/${id}`, formData);
            } else {
                const res = await api.post('/gpt/projects', formData);
                projectId = res.data.id;
            }

            // Sync pending files if any
            if (pendingFiles.length > 0) {
                setUploading(true);
                for (const file of pendingFiles) {
                    const uploadData = new FormData();
                    uploadData.append('file', file);
                    await api.post(`/gpt/projects/${projectId}/upload-knowledge`, uploadData);
                }
                setUploading(false);
            }

            showSuccess(id ? "Engine Updated Successfully!" : "Engine Deployed Successfully!");
            navigate('/gpt');
        } catch (err) {
            console.error(err);
            showError("Failed to save engine.");
        } finally {
            setSaving(false);
        }
    };

    const removePendingFile = (idx) => {
        setPendingFiles(prev => prev.filter((_, i) => i !== idx));
    };

    if (loading) return <div className="flex justify-center p-20 animate-pulse text-[var(--accent-indigo)]">Gathering Intelligence...</div>;

    return (
        <div className="h-[calc(100vh-100px)] overflow-hidden flex flex-col bg-[var(--bg-main)]">
            {/* Header */}
            <div className="flex items-center justify-between px-10 py-5 bg-[var(--bg-card)] border-b border-[var(--border)] shrink-0">
                <div className="flex items-center gap-5">
                    <button onClick={() => navigate('/gpt')} className="p-2.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-xl hover:text-[var(--accent-indigo)] transition-all">
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">Engine Config</h1>
                        <p className="text-[10px] text-[var(--text-muted)] font-black uppercase tracking-widest opacity-60 italic">{id ? 'Modifying Active Neural Network' : 'Initializing New Core'}</p>
                    </div>
                </div>
                
                <button 
                    onClick={handleSave}
                    disabled={saving || uploading}
                    className="h-11 px-8 bg-[var(--accent-indigo)] text-white rounded-xl flex items-center gap-2 font-black uppercase text-[12px] tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg shadow-indigo-200"
                >
                    {saving || uploading ? (
                        <div className="flex items-center gap-2">
                             <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                             Processing...
                        </div>
                    ) : (
                        <><Save size={18} /> {id ? 'Update Engine' : 'Deploy Engine'}</>
                    )}
                </button>
            </div>

            <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-12">
                {/* Left Side: Form */}
                <div className="lg:col-span-8 overflow-y-auto no-scrollbar p-10 space-y-8">
                    
                    <div className="space-y-6">
                        <div className="relative group">
                            <input 
                                className="w-full bg-transparent border-b-2 border-[var(--border)] focus:border-[var(--accent-indigo)] py-3 text-2xl font-black text-[var(--text-main)] outline-none transition-all placeholder:text-[var(--text-muted)] group-focus-within:placeholder:opacity-30"
                                placeholder="e.g. HR Policy Engine"
                                value={formData.title}
                                onChange={e => setFormData({...formData, title: e.target.value})}
                            />
                            <div className="absolute right-0 bottom-3 text-[9px] font-black uppercase text-[var(--text-muted)] opacity-40">Identifier</div>
                        </div>
                        
                        <div className="relative group">
                             <input 
                                className="w-full bg-transparent border-b border-[var(--border)] focus:border-[var(--accent-indigo)] py-2 text-[13px] font-bold text-[var(--text-muted)] outline-none transition-all placeholder:text-[var(--text-muted)] opacity-80"
                                placeholder="Briefly describe what this agent does..."
                                value={formData.description}
                                onChange={e => setFormData({...formData, description: e.target.value})}
                            />
                             <div className="absolute right-0 bottom-2 text-[8px] font-black uppercase text-[var(--text-muted)] opacity-40">Purpose Scope</div>
                        </div>
                    </div>

                    {/* Instructions */}
                    <div className="space-y-3">
                        <div className="flex items-center justify-between px-1">
                            <h3 className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.2em] flex items-center gap-2">
                                <Info size={14} /> Neural Instructions
                            </h3>
                            <span className="px-2 py-0.5 bg-[var(--input-bg)] border border-[var(--border)] text-[8px] font-black text-[var(--text-muted)] rounded-md uppercase tracking-widest">Logic Tier 1</span>
                        </div>
                        <textarea 
                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-6 text-[13px] font-medium text-[var(--text-main)] h-56 focus:border-[var(--accent-indigo)] outline-none transition-all resize-none leading-relaxed shadow-sm placeholder:text-[var(--text-muted)] placeholder:italic"
                            placeholder="How should this AI behave? (Tone, constraints, knowledge priority...)"
                            value={formData.instruction}
                            onChange={e => setFormData({...formData, instruction: e.target.value})}
                        />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                        {/* Conversation Starters */}
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="text-[11px] font-black text-emerald-500 uppercase tracking-widest flex items-center gap-2">
                                    <MessageSquare size={14} /> User Starters
                                </h3>
                            </div>
                            <div className="space-y-3">
                                <form onSubmit={(e) => { e.preventDefault(); if (starterInput.trim()) { setFormData({...formData, conversation_starters: [...formData.conversation_starters, starterInput]}); setStarterInput(''); } }} className="relative">
                                    <input 
                                        className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-xl py-3 pl-4 pr-10 text-[12px] font-bold text-[var(--text-main)] outline-none focus:border-emerald-400 transition-all placeholder:text-[var(--text-muted)]"
                                        placeholder="Add starter..."
                                        value={starterInput}
                                        onChange={e => setStarterInput(e.target.value)}
                                    />
                                    <button type="submit" className="absolute right-2 top-2 p-1.5 bg-emerald-500 text-white rounded-lg active:scale-90 transition-all">
                                        <Plus size={14} />
                                    </button>
                                </form>
                                <div className="space-y-2 max-h-40 overflow-y-auto no-scrollbar">
                                    {formData.conversation_starters.map((starter, idx) => (
                                        <div key={idx} className="flex items-center justify-between gap-2 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[11px] font-bold text-[var(--text-main)] group">
                                            <span className="truncate">{starter}</span>
                                            <button onClick={() => setFormData({...formData, conversation_starters: formData.conversation_starters.filter((_, i) => i !== idx)})} className="text-red-400 opacity-0 group-hover:opacity-100 transition-all">
                                                <X size={12} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Knowledge Base */}
                        <div className="space-y-4">
                            <h3 className="text-[11px] font-black text-amber-500 uppercase tracking-widest flex items-center gap-2">
                                <Database size={14} /> Training Data
                            </h3>
                            
                            <div className="space-y-3">
                                <div className="flex flex-col gap-2 max-h-40 overflow-y-auto no-scrollbar">
                                    {/* Existing Files */}
                                    {formData.knowledge_files.map((file, idx) => (
                                        <div key={`exist-${idx}`} className="flex items-center justify-between gap-2 px-3 py-2 bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 rounded-xl text-[10px] font-black group">
                                            <div className="flex items-center gap-2 truncate">
                                                <CheckCircle2 size={12} className="shrink-0" /> <span className="truncate">{file.name}</span>
                                            </div>
                                            <button 
                                                onClick={async () => {
                                                    if (window.confirm(`Are you sure you want to remove ${file.name}?`)) {
                                                        try {
                                                            await api.delete(`/gpt/projects/${id}/knowledge/${file.id}`);
                                                            showSuccess("Knowledge removed.");
                                                            fetchProject();
                                                        } catch (err) {
                                                            showError("Failed to remove knowledge.");
                                                        }
                                                    }
                                                }}
                                                className="text-red-500 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                            >
                                                <X size={12} />
                                            </button>
                                        </div>
                                    ))}
                                    {/* Selected but not yet uploaded */}
                                    {pendingFiles.map((file, idx) => (
                                        <div key={`pend-${idx}`} className="flex items-center justify-between gap-2 px-3 py-2 bg-amber-500/10 text-amber-600 border border-amber-500/20 rounded-xl text-[10px] font-black group">
                                            <div className="flex items-center gap-2 truncate">
                                                <FileUp size={12} className="shrink-0" /> <span className="truncate">{file.name}</span>
                                            </div>
                                            <button onClick={() => removePendingFile(idx)} className="text-red-500 opacity-0 group-hover:opacity-100 transition-all shrink-0">
                                                <X size={12} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                                
                                <div className="grid grid-cols-2 gap-3">
                                    <label className="cursor-pointer group flex-1">
                                        <input 
                                            type="file" 
                                            multiple 
                                            accept="*"
                                            className="hidden" 
                                            disabled={uploading}
                                            onChange={(e) => handleFileUpload(e, !id)} 
                                        />
                                        <div className="w-full h-full py-6 border-2 border-dashed border-[var(--border)] hover:border-[var(--accent-indigo)] hover:bg-[var(--input-bg)] transition-all rounded-2xl flex flex-col items-center justify-center gap-2 relative overflow-hidden">
                                             {uploading && (
                                                <div className="absolute inset-0 bg-white/80 z-20 flex flex-col items-center justify-center">
                                                    <div className="w-8 h-8 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                                                    <p className="text-[10px] font-black text-[var(--accent-indigo)] mt-2">{uploadProgress}%</p>
                                                </div>
                                             )}
                                             <div className="p-2 bg-[var(--input-bg)] text-[var(--accent-indigo)] rounded-lg group-hover:scale-110 transition-all">
                                                 <FileUp size={16} />
                                             </div>
                                             <p className="text-[9px] font-black text-[var(--text-main)] uppercase tracking-widest text-center px-2">Select Files</p>
                                        </div>
                                    </label>

                                    <label className="cursor-pointer group flex-1">
                                        <input 
                                            type="file" 
                                            multiple 
                                            webkitdirectory="true"
                                            className="hidden" 
                                            disabled={uploading}
                                            onChange={(e) => handleFileUpload(e, !id)} 
                                        />
                                        <div className="w-full h-full py-6 border-2 border-dashed border-[var(--border)] hover:border-amber-500/50 hover:bg-amber-50 transition-all rounded-2xl flex flex-col items-center justify-center gap-2 relative overflow-hidden">
                                             {uploading && (
                                                <div className="absolute inset-0 bg-white/80 z-20 flex flex-col items-center justify-center">
                                                    <div className="w-8 h-8 border-4 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
                                                    <p className="text-[10px] font-black text-amber-500 mt-2">{uploadProgress}%</p>
                                                </div>
                                             )}
                                             <div className="p-2 bg-amber-50 text-amber-500 rounded-lg group-hover:scale-110 transition-all">
                                                 <Folders size={16} />
                                             </div>
                                             <p className="text-[9px] font-black text-[var(--text-main)] uppercase tracking-widest text-center px-2">Select Folder</p>
                                        </div>
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Side: Preview */}
                <div className="lg:col-span-4 bg-[var(--bg-card)] border-l border-[var(--border)] flex flex-col items-center justify-center p-8 relative overflow-hidden">
                    <div className="absolute inset-0 pointer-events-none opacity-10">
                         <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--accent-indigo)] blur-[80px] rounded-full translate-x-1/2 -translate-y-1/2"></div>
                    </div>
                    
                    <motion.div 
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className="flex flex-col items-center text-center space-y-6 z-10"
                    >
                        <div className="relative">
                            <div className="w-28 h-28 bg-gradient-to-br from-[var(--accent-indigo)] to-[var(--accent-indigo-hover)] rounded-[32px] shadow-2xl flex items-center justify-center transform rotate-3 border-4 border-[var(--bg-card)]">
                                 <Bot size={56} className="text-white" />
                            </div>
                        </div>

                        <div className="space-y-2">
                             <h2 className="text-2xl font-black text-[var(--text-main)] italic uppercase">
                                {formData.title || 'DRAFT_CORE'}
                             </h2>
                             <p className="text-[12px] text-[var(--text-muted)] font-bold max-w-[220px] leading-relaxed italic opacity-80">
                                {formData.description || 'Define your project scope to preview the neural identity here.'}
                             </p>
                        </div>
                        
                        <div className="pt-6 flex flex-col items-center gap-4">
                             <div className="flex -space-x-3">
                                 {[1,2,3,4].map(i => (
                                     <div key={i} className="w-10 h-10 rounded-xl border-2 border-[var(--bg-card)] bg-[var(--input-bg)] flex items-center justify-center">
                                         <div className="w-full h-full bg-[var(--accent-indigo)] opacity-[0.05]"></div>
                                     </div>
                                 ))}
                             </div>
                        </div>
                    </motion.div>
                </div>
            </div>
        </div>
    );
};

export default GptEditor;
