import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import {
    Layers, ChevronRight, CheckCircle2, Calendar,
    Target, Bot, UploadCloud, Plus, FileText,
    Download, ExternalLink, BookOpen, Zap, AlertTriangle, Circle, CheckCircle, Info, Sparkles, Brain, Eye, Lock
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const CompanyPortal = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const companyId = user?.company_id;

    const [trainingPath, setTrainingPath] = useState([]);
    const [fetchingPath, setFetchingPath] = useState(true);

    // Redirect staff away from Training Roadmap
    useEffect(() => {
        const role = user?.role?.toLowerCase();
        const isStaff = ['superadmin', 'admin', 'coach', 'staff'].includes(role);
        if (isStaff) {
            navigate('/');
        }
    }, [user, navigate]);
    const [selectedSessionId, setSelectedSessionId] = useState(null);
    const [sessionTasks, setSessionTasks] = useState([]);
    const [fetchingTasks, setFetchingTasks] = useState(false);
    const [expandedBatches, setExpandedBatches] = useState({});
    const [expandedQuarters, setExpandedQuarters] = useState({});

    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        if (companyId) {
            fetchPath();
        }
    }, [companyId]);

    const fetchPath = async () => {
        setFetchingPath(true);
        try {
            const res = await api.get(`/companies/${companyId}/training-path`);
            setTrainingPath(res.data);

            // Auto expand first batch/quarter if available
            if (res.data.length > 0) {
                const firstBatch = res.data[0];
                setExpandedBatches({ [firstBatch.id]: true });
                if (firstBatch.quarters?.length > 0) {
                    setExpandedQuarters({ [firstBatch.quarters[0].id]: true });
                }
            }
        } catch (err) {
            showError("Failed to fetch training roadmap");
        } finally {
            setFetchingPath(false);
        }
    };

    const fetchSessionTasks = async (sid) => {
        setFetchingTasks(true);
        setSelectedSessionId(sid);
        try {
            // 1. Fetch the base event data (for resources, content, etc.)
            const res = await api.get(`/calendar/events/${sid}`);
            const ev = res.data;

            // 2. Fetch company-specific merged tasks & progress
            try {
                const tasksRes = await api.get(`/companies/${companyId}/sessions/${sid}/tasks`);
                ev.session_tasks = tasksRes.data;
                setSessionTasks(tasksRes.data);
            } catch (pErr) {
                console.error("Progress fetch error:", pErr);
                setSessionTasks(ev.session_tasks || []);
            }

            // 3. Sync template assessments if linked (for Knowledge Checks)
            if (ev.session_template_id) {
                try {
                    const tempRes = await api.get(`/session-templates/${ev.session_template_id}`);
                    ev.template_assessments = tempRes.data.assessments || [];
                } catch (tErr) {
                    console.error("Template Sync Error:", tErr);
                }
            }

            // Update training path with full session data
            setTrainingPath(prev => prev.map(batch => ({
                ...batch,
                quarters: batch.quarters.map(q => ({
                    ...q,
                    sessions: q.sessions.map(s => s.id === sid ? { ...s, ...ev } : s)
                }))
            })));
        } catch (err) {
            showError("Neural link synchronization failed");
        } finally {
            setFetchingTasks(false);
        }
    };

    const handleToggleTask = async (taskIdx) => {
        try {
            await api.patch(`/companies/${companyId}/sessions/${selectedSessionId}/tasks/${taskIdx}/toggle`);
            setSessionTasks(prev => prev.map(t => t.index === taskIdx ? { ...t, is_done: !t.is_done } : t));
            showSuccess("Neural milestone updated!");
        } catch (err) {
            showError("Failed to sync progress");
        }
    };

    const handleLearnerUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            await api.post(`/calendar/events/${selectedSessionId}/learner-upload`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            showSuccess(`"${file.name}" synchronized with cloud!`);
            fetchPath(); // Refresh path to get new contents
        } catch (err) {
            showError("Cloud synchronization failed");
        } finally {
            setUploading(false);
        }
    };

    const getSession = (sid) => {
        return trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === sid);
    };

    if (!companyId) return (
        <div className="flex flex-col items-center justify-center py-32 opacity-50 space-y-4">
            <AlertTriangle size={48} />
            <p className="font-black uppercase tracking-widest text-[12px]">No Company Link Detected</p>
        </div>
    );

    return (
        <div className="max-w-7xl mx-auto space-y-8 animate-in fade-in duration-700 pb-20 px-4">
            {/* Header & AI Insight Hybrid Section */}
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
                <div>
                    <h1 className="text-4xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none flex items-center gap-4">
                        Productivity Learning Roadmap
                        <div className="w-2 h-2 rounded-full bg-[var(--accent-indigo)] animate-pulse hidden md:block"></div>
                    </h1>
                    <p className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-[0.2em] mt-2 max-w-md">
                        Strategic Pulse for {user?.company_name || 'Your organization'}
                    </p>
                </div>

                {/* Unique Pattern for AI Unlocking */}
                <div className="relative overflow-hidden bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-[28px] p-6 lg:max-w-md group transition-all hover:shadow-2xl hover:shadow-indigo-500/10 hover:-translate-y-1">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-indigo)] opacity-[0.05] rounded-full -mr-16 -mt-16 group-hover:scale-150 transition-transform duration-[2000ms]"></div>
                    <div className="relative z-10 flex gap-4">
                        <div className="w-12 h-12 rounded-[18px] bg-white border border-[var(--accent-indigo-border)] flex items-center justify-center text-[var(--accent-indigo)] shrink-0 shadow-sm">
                            <Zap size={24} className="fill-[var(--accent-indigo)]" />
                        </div>
                        <div>
                            <h4 className="text-[12px] font-black text-indigo-900 uppercase tracking-tight flex items-center gap-2">
                                AI Engine Unlocking
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping"></span>
                            </h4>
                            <p className="text-[10px] text-indigo-700 font-bold leading-relaxed mt-1 opacity-80">
                                Complete sessions to activate associated Neural Knowledge Engines. Access overrides granted by coaches for high-priority training.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Compact Navigation: Batches & Quarters */}
            <div className="space-y-4">
                {/* Batches Row */}
                <div className="flex items-center gap-4">
                    <div className="shrink-0 flex items-center gap-2 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest border-r border-[var(--border)] pr-4">
                        <Layers size={14} /> Batches
                    </div>
                    <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1 px-1">
                        {fetchingPath ? (
                            <div className="flex gap-2">
                                {[1, 2, 3].map(i => <div key={i} className="w-32 h-10 bg-[var(--input-bg)] rounded-xl animate-pulse"></div>)}
                            </div>
                        ) : trainingPath.map(batch => (
                            <button
                                key={batch.id}
                                onClick={() => {
                                    setExpandedBatches({ [batch.id]: true });
                                    if (batch.quarters?.length > 0) {
                                        setExpandedQuarters({ [batch.quarters[0].id]: true });
                                    }
                                }}
                                className={`shrink-0 px-6 py-2.5 rounded-xl text-[12px] font-black uppercase tracking-tight transition-all border ${expandedBatches[batch.id]
                                    ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-lg shadow-indigo-500/20 scale-[1.05]'
                                    : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)] hover:text-[var(--text-main)]'}`}
                            >
                                {batch.name}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Quarters Row (Conditional based on active batch) */}
                {Object.keys(expandedBatches).length > 0 && trainingPath.find(b => expandedBatches[b.id])?.quarters?.length > 0 && (
                    <div className="flex items-center gap-4 animate-in slide-in-from-top-2 duration-300">
                        <div className="shrink-0 flex items-center gap-2 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest border-r border-[var(--border)] pr-4">
                            <Target size={14} /> Quarters
                        </div>
                        <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1 px-1">
                            {trainingPath.find(b => expandedBatches[b.id])?.quarters.map(quarter => (
                                <button
                                    key={quarter.id}
                                    onClick={() => setExpandedQuarters({ [quarter.id]: true })}
                                    className={`shrink-0 px-5 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all border ${expandedQuarters[quarter.id]
                                        ? 'bg-[var(--accent-orange)] text-white border-[var(--accent-orange)] shadow-lg shadow-orange-500/20'
                                        : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)] hover:bg-white hover:text-[var(--accent-orange)]'}`}
                                >
                                    {quarter.name}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start pt-4">
                {/* Sessions Grid (Now on the left, but compact) */}
                <div className="lg:col-span-4 space-y-4">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden shadow-sm">
                        <div className="p-5 border-b border-[var(--border)] bg-indigo-50/5 flex items-center justify-between">
                            <h3 className="text-[11px] font-black text-[var(--text-main)] uppercase tracking-[0.15em] flex items-center gap-2">
                                <Zap size={14} className="text-[var(--accent-indigo)]" /> Quarter Timeline
                            </h3>
                            {Object.keys(expandedQuarters).length > 0 && (
                                <span className="text-[9px] font-black text-[var(--accent-orange)] uppercase px-2 py-0.5 bg-orange-50 rounded-lg">
                                    {trainingPath.flatMap(b => b.quarters).find(q => expandedQuarters[q.id])?.name}
                                </span>
                            )}
                        </div>

                        <div className="p-3 space-y-2 max-h-[60vh] overflow-y-auto no-scrollbar">
                            {fetchingPath ? (
                                <div className="py-20 flex flex-col items-center gap-2 opacity-40">
                                    <div className="w-6 h-6 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                                    <span className="text-[10px] font-black uppercase tracking-widest">Refreshing Neural Link...</span>
                                </div>
                            ) : Object.keys(expandedQuarters).length > 0 ? (
                                (trainingPath.flatMap(b => b.quarters).find(q => expandedQuarters[q.id])?.sessions || []).map(session => (
                                    <button
                                        key={session.id}
                                        onClick={() => fetchSessionTasks(session.id)}
                                        className={`w-full flex items-center gap-3 p-4 rounded-2xl transition-all text-left ${selectedSessionId === session.id
                                            ? 'bg-white shadow-xl border border-[var(--accent-indigo-border)] text-[var(--accent-indigo)] scale-[1.02]'
                                            : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}
                                    >
                                        <div className={`w-2.5 h-2.5 rounded-full ${selectedSessionId === session.id ? 'bg-[var(--accent-indigo)] animate-pulse' : 'bg-[var(--border)]'}`}></div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-[12px] font-black uppercase tracking-tighter truncate leading-tight">{session.title}</p>
                                            <p className="text-[9px] font-bold opacity-60 flex items-center gap-1.5 mt-1">
                                                <Calendar size={10} /> {new Date(session.start).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })} • {session.type || 'Session'}
                                            </p>
                                        </div>
                                        {session.status === 'completed' && <CheckCircle2 size={16} className="text-[var(--accent-green)]" />}
                                    </button>
                                ))
                            ) : (
                                <div className="py-20 text-center opacity-30 italic">
                                    <Layers size={40} className="mx-auto mb-4" />
                                    <p className="text-[10px] font-black uppercase tracking-widest">Select a Batch & Quarter<br />to initialize path</p>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Quick Support / Reminder Block */}
                    <div className="bg-gradient-to-br from-indigo-600 to-violet-700 rounded-[32px] p-6 text-white shadow-xl shadow-indigo-500/10">
                        <BookOpen size={20} className="mb-4 opacity-80" />
                        <h4 className="text-[13px] font-black uppercase tracking-tight">Curriculum Continuity</h4>
                        <p className="text-[10px] font-medium leading-relaxed mt-2 opacity-90">
                            Your training roadmap is dynamically optimized based on batch performance and AI engine feedback.
                        </p>
                        <button className="w-full mt-4 py-2.5 bg-white/10 hover:bg-white/20 border border-white/20 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all">
                            View Syllabus
                        </button>
                    </div>
                </div>

                {/* Right Column: Active Session Details */}
                <div className="lg:col-span-8">
                    <AnimatePresence mode="wait">
                        {fetchingTasks ? (
                            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-24 flex flex-col items-center justify-center gap-4 text-center">
                                <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                                <p className="text-[12px] font-black text-[var(--accent-indigo)] uppercase tracking-widest animate-pulse">Synchronizing Neural data...</p>
                            </motion.div>
                        ) : selectedSessionId ? (
                            <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                                {/* Compact Session Card */}
                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-8 shadow-sm relative overflow-hidden group">
                                    <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--accent-indigo)] opacity-[0.03] rounded-full -mr-32 -mt-32 group-hover:scale-150 transition-transform duration-[2000ms]"></div>
                                    <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
                                        <div>
                                            <div className="flex items-center gap-3 mb-4">
                                                <div className="px-3 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-lg text-[10px] font-black uppercase tracking-widest border border-[var(--accent-indigo-border)]">Strategic Node</div>
                                                <div className={`px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest border ${getSession(selectedSessionId)?.status === 'completed' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'}`}>
                                                    {getSession(selectedSessionId)?.status}
                                                </div>
                                            </div>
                                            <h2 className="text-3xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none mb-3">
                                                {getSession(selectedSessionId)?.title}
                                            </h2>
                                            <div className="flex flex-wrap items-center gap-6 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                                <span className="flex items-center gap-2"><Calendar size={14} className="text-indigo-400" /> {new Date(getSession(selectedSessionId)?.start).toLocaleDateString('en-IN', { weekday: 'long', day: '2-digit', month: 'long' })}</span>
                                                <span className="flex items-center gap-2"><Target size={14} className="text-orange-400" /> Quarter Milestone</span>
                                            </div>
                                        </div>
                                        {getSession(selectedSessionId)?.meeting_link && (
                                            <a
                                                href={getSession(selectedSessionId)?.meeting_link}
                                                target="_blank"
                                                rel="noreferrer"
                                                onClick={async () => {
                                                    try { await api.post(`/calendar/events/${selectedSessionId}/track-join`); } catch (_e) { /* ignore tracking errors */ }
                                                }}
                                                className="shrink-0 h-14 px-8 bg-black text-white rounded-[22px] flex items-center gap-3 text-[13px] font-black uppercase tracking-widest hover:scale-105 active:scale-95 transition-all shadow-xl hover:shadow-indigo-500/20"
                                            >
                                                Join Neural Link
                                            </a>
                                        )}
                                    </div>
                                </div>

                                {(() => {
                                    const isLocked = getSession(selectedSessionId)?.status !== 'completed';
                                    const LockedOverlay = ({ title }) => (
                                        <div className="absolute inset-0 bg-slate-50/80 backdrop-blur-[4px] z-10 flex flex-col items-center justify-center p-6 text-center animate-in fade-in zoom-in-95 duration-500 rounded-[32px]">
                                            <div className="w-14 h-14 rounded-2xl bg-white border border-[var(--border)] shadow-2xl flex items-center justify-center text-[var(--accent-indigo)] mb-4 scale-110">
                                                <Lock size={24} />
                                            </div>
                                            <h5 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-[0.1em] mb-1">{title} Locked</h5>
                                            <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-tight leading-relaxed max-w-[150px]">
                                                Mark this session as completed to unlock neural assets.
                                            </p>
                                        </div>
                                    );

                                    return (
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                            {/* Session Tasks */}
                                            <div className="relative">
                                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col shadow-sm">
                                                    <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-emerald-50/10">
                                                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                                            <CheckCircle2 size={16} className="text-[var(--accent-green)]" /> Session Tasks
                                                        </h4>
                                                        <div className="text-[10px] font-black text-[var(--accent-green)] bg-[var(--accent-green-bg)] px-3 py-1 rounded-[10px]">
                                                            {sessionTasks.filter(t => t.is_done).length}/{sessionTasks.length} DONE
                                                        </div>
                                                    </div>
                                                    <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                                                        {sessionTasks.length > 0 ? sessionTasks.map(task => (
                                                            <div
                                                                key={task.index}
                                                                onClick={() => !isLocked && handleToggleTask(task.index)}
                                                                className={`flex items-start gap-3 p-4 rounded-[20px] border transition-all cursor-pointer group ${task.is_done ? 'bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]' : 'bg-[var(--input-bg)] border-transparent hover:border-[var(--accent-indigo)]'}`}
                                                            >
                                                                <div className={`mt-0.5 w-5 h-5 rounded-[8px] flex items-center justify-center transition-all ${task.is_done ? 'bg-[var(--accent-green)] text-white' : 'bg-white border-2 border-[var(--border)]'}`}>
                                                                    {task.is_done ? <CheckCircle size={14} /> : <Circle size={14} className="opacity-10" />}
                                                                </div>
                                                                <div className="flex-1 min-w-0">
                                                                    <p className={`text-[12px] font-black uppercase tracking-tight transition-all ${task.is_done ? 'text-[var(--accent-green)] line-through opacity-60' : 'text-[var(--text-main)]'}`}>
                                                                        {task.label || task.title || 'Neural Milestone'}
                                                                    </p>
                                                                    {task.is_done && task.completed_by && (
                                                                        <p className="text-[9px] font-black text-[var(--accent-green)] uppercase tracking-tighter mt-1 opacity-80">
                                                                            Done by: {task.completed_by}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        )) : (
                                                            <div className="py-16 text-center opacity-30 italic">
                                                                <Bot size={32} className="mx-auto mb-2" />
                                                                <p className="text-[10px] font-black uppercase tracking-widest">No custom tasks linked</p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                {isLocked && <LockedOverlay title="Session Tasks" />}
                                            </div>

                                            {/* Knowledge Checks */}
                                            <div className="relative">
                                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col shadow-sm">
                                                    <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-purple-50/10">
                                                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                                            <Brain size={16} className="text-purple-500" /> Knowledge Checks
                                                        </h4>
                                                        <div className="text-[10px] font-black text-purple-600 bg-purple-50 px-3 py-1 rounded-[10px]">
                                                            {getSession(selectedSessionId)?.template_assessments?.length || 0} ACTIVE
                                                        </div>
                                                    </div>
                                                    <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                                                        {getSession(selectedSessionId)?.template_assessments?.length > 0 ? (
                                                            getSession(selectedSessionId).template_assessments.map((quiz, idx) => (
                                                                <div key={idx} className="flex items-center gap-4 p-4 bg-[var(--input-bg)] border border-transparent hover:border-purple-500/30 rounded-2xl transition-all group cursor-pointer" onClick={() => !isLocked && navigate(`/assessment/${selectedSessionId}/${idx}`)}>
                                                                    <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center group-hover:scale-110 transition-transform shadow-sm">
                                                                        <BookOpen size={18} />
                                                                    </div>
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-[12px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{quiz.title}</p>
                                                                        <div className="flex items-center gap-3 mt-1">
                                                                            <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-tight">Passing: {quiz.passing_score}%</p>
                                                                            <p className="text-[9px] font-black text-[var(--accent-indigo)] uppercase tracking-tight">• {quiz.questions.reduce((acc, q) => acc + (q.marks || 1), 0)} Total Marks</p>
                                                                        </div>
                                                                    </div>
                                                                    <ChevronRight size={16} className="text-purple-400" />
                                                                </div>
                                                            ))
                                                        ) : (
                                                            <div className="py-16 text-center opacity-30 italic">
                                                                <Brain size={32} className="mx-auto mb-2" />
                                                                <p className="text-[10px] font-black uppercase tracking-widest">No Knowledge Checks linked</p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                {isLocked && <LockedOverlay title="Knowledge Checks" />}
                                            </div>

                                            {/* Executive Resources */}
                                            <div className="relative">
                                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col shadow-sm">
                                                    <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-amber-50/10">
                                                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                                            <Sparkles size={16} className="text-amber-500" /> Executive Resources
                                                        </h4>
                                                        <div className="text-[10px] font-black text-amber-600 bg-amber-50 px-3 py-1 rounded-[10px]">
                                                            {getSession(selectedSessionId)?.resources?.length || 0} ITEMS
                                                        </div>
                                                    </div>
                                                    <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                                                        {getSession(selectedSessionId)?.resources?.length > 0 ? (
                                                            getSession(selectedSessionId).resources.map((r) => (
                                                                <div key={r.id} className="flex items-center gap-4 p-4 bg-[var(--input-bg)] border border-transparent hover:border-amber-500/30 rounded-2xl transition-all group cursor-pointer" onClick={() => !isLocked && navigate(`/sessions/${selectedSessionId}/resource/${r.id}`)}>
                                                                    <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center group-hover:scale-110 transition-transform shadow-sm">
                                                                        <Eye size={18} />
                                                                    </div>
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-[12px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{r.name}</p>
                                                                        <p className="text-[9px] font-black text-amber-600 uppercase mt-1">Intelligence View</p>
                                                                    </div>
                                                                    <ChevronRight size={16} className="text-amber-400" />
                                                                </div>
                                                            ))
                                                        ) : (
                                                            <div className="py-16 text-center opacity-30 italic">
                                                                <Sparkles size={32} className="mx-auto mb-2" />
                                                                <p className="text-[10px] font-black uppercase tracking-widest">No Intelligence Data</p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                {isLocked && <LockedOverlay title="Executive Resources" />}
                                            </div>

                                            {/* Shared Content */}
                                            <div className="relative">
                                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col shadow-sm">
                                                    <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-blue-50/10">
                                                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                                            <BookOpen size={16} className="text-blue-500" /> Shared Content
                                                        </h4>
                                                        <div className="text-[10px] font-black text-blue-600 bg-blue-50 px-3 py-1 rounded-[10px]">
                                                            {getSession(selectedSessionId)?.contents?.length || 0} ASSETS
                                                        </div>
                                                    </div>
                                                    <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                                                        {getSession(selectedSessionId)?.contents?.length > 0 ? (
                                                            getSession(selectedSessionId).contents.map((c, i) => (
                                                                <a key={i} href={!isLocked ? c.url : undefined} target="_blank" rel="noopener noreferrer"
                                                                    onClick={() => {
                                                                        if (isLocked) return;
                                                                        api.post(`/calendar/events/${selectedSessionId}/resources/${c.id || i}/view`).catch(e => { });
                                                                    }}
                                                                    className={`flex items-center gap-4 p-4 bg-[var(--input-bg)] border border-transparent hover:border-blue-500/30 rounded-2xl transition-all group ${isLocked ? 'cursor-default' : 'cursor-pointer'}`}>
                                                                    <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center group-hover:scale-110 transition-transform shadow-sm">
                                                                        <Download size={18} />
                                                                    </div>
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-[12px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{c.name}</p>
                                                                        <p className="text-[9px] font-black text-blue-600 uppercase mt-1">Downloadable</p>
                                                                    </div>
                                                                    <Download size={14} className="text-blue-400" />
                                                                </a>
                                                            ))
                                                        ) : (
                                                            <div className="py-16 text-center opacity-30 italic">
                                                                <BookOpen size={32} className="mx-auto mb-2" />
                                                                <p className="text-[10px] font-black uppercase tracking-widest">No Shared Assets</p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                {isLocked && <LockedOverlay title="Shared Content" />}
                                            </div>
                                        </div>
                                    );
                                })()}

                                {/* Content Upload (Full Width) */}
                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col shadow-sm">
                                    <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-indigo-50/10">
                                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                                            <UploadCloud size={16} className="text-[var(--accent-indigo)]" /> Submissions
                                        </h4>
                                        <label className={`h-9 px-4 rounded-[12px] flex items-center gap-2 text-[10px] font-black uppercase tracking-widest cursor-pointer transition-all ${uploading ? 'bg-gray-100 text-gray-400' : 'bg-black text-white hover:opacity-95'}`}>
                                            {uploading ? '...' : <><Plus size={14} /> Submit</>}
                                            <input type="file" className="hidden" disabled={uploading} onChange={handleLearnerUpload} />
                                        </label>
                                    </div>

                                    <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                                        {(getSession(selectedSessionId)?.learner_contents || []).length > 0 ? (
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                {getSession(selectedSessionId)?.learner_contents.map(content => (
                                                    <a
                                                        href={content.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        key={content.id}
                                                        className="flex items-center gap-3 p-4 bg-white border border-[var(--border)] rounded-[20px] hover:border-[var(--accent-indigo)] hover:shadow-lg transition-all group"
                                                    >
                                                        <div className="w-10 h-10 rounded-[14px] bg-[var(--input-bg)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] group-hover:bg-[var(--accent-indigo-bg)] transition-colors">
                                                            <FileText size={20} />
                                                        </div>
                                                        <div className="flex-1 min-w-0">
                                                            <p className="text-[12px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{content.name}</p>
                                                            <p className="text-[9px] text-[var(--text-muted)] font-black mt-1 opacity-60 uppercase">
                                                                {new Date(content.uploaded_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                                                            </p>
                                                        </div>
                                                        <Download size={14} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)]" />
                                                    </a>
                                                ))}
                                            </div>
                                        ) : (
                                            <div className="py-10 text-center opacity-30 italic">
                                                <UploadCloud size={32} className="mx-auto mb-2" />
                                                <p className="text-[10px] font-black uppercase tracking-widest">No submissions yet</p>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </motion.div>
                        ) : (
                            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-40 text-center flex flex-col items-center">
                                <div className="w-20 h-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-[28px] flex items-center justify-center mb-6 text-[var(--text-muted)] opacity-20">
                                    <Zap size={40} />
                                </div>
                                <h3 className="text-2xl font-black text-[var(--text-main)] uppercase italic tracking-tighter mb-2">Initialize <span className="text-[var(--accent-indigo)]">Neural Node</span></h3>
                                <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-widest max-w-sm mx-auto opacity-50 leading-relaxed">
                                    Select a session from your timeline to synchronize tasks, download intelligence resources, and manage submissions.
                                </p>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>
        </div>
    );
};

export default CompanyPortal;
