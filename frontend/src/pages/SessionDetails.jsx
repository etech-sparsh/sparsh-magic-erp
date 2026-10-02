import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import {
    ArrowLeft, Calendar as CalendarIcon, Clock, Link as LinkIcon,
    Video, UserCheck, Activity, UploadCloud, 
    FileUp, PlusCircle, Trash2, Ban, ListTodo, HelpCircle, AlertCircle,
    CheckCircle, FileText, Bot, Eye, FileQuestion, BookOpen,
    Target, ChevronRight, X, Users2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { motion } from 'framer-motion';

const SessionDetails = () => {
    const { sessionId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();

    const [session, setSession] = useState(null);
    const [loading, setLoading] = useState(true);
    const [completing, setCompleting] = useState(false);

    const role = user?.role?.toLowerCase();
    const isStaff = ['superadmin', 'admin', 'coach', 'staff'].includes(role);

    const [gptProjects, setGptProjects] = useState([]);
    const [updatingGpt, setUpdatingGpt] = useState(false);

    // Attendance State
    const [attendees, setAttendees] = useState([]);
    const [attendanceMarks, setAttendanceMarks] = useState({});
    const [showAttendanceModal, setShowAttendanceModal] = useState(false);
    const [savingAttendance, setSavingAttendance] = useState(false);

    const fetchSessionData = async () => {
        try {
            const requests = [
                api.get(`/calendar/events/${sessionId}`),
                api.get('/gpt/projects')
            ];
            if (isStaff) requests.splice(1, 0, api.get('/users?active_only=true'));

            const results = await Promise.all(requests);
            const ev = results[0].data;
            const usersData = isStaff ? results[1].data : [];
            const gptRes = results[isStaff ? 2 : 1];
            setGptProjects(gptRes.data);

            // ─── CURRICULUM SYNC: Linked Template Logic ───
            // Handle both possible field names and ensure string conversion if it's a mongo object
            const rawTemplateId = ev.session_template_id || ev.template_id;
            const tId = (typeof rawTemplateId === 'object' && rawTemplateId?.$oid) ? rawTemplateId.$oid : rawTemplateId;

            if (tId) {
                console.log(`[SessionDetails] Linking Curriculum Template: ${tId}`);
                try {
                    const tempRes = await api.get(`/session-templates/${tId}`);
                    ev.template_tasks = tempRes.data.tasks || [];
                    ev.assessments = tempRes.data.assessments || [];
                    console.log(`[SessionDetails] Sync Success: Found ${ev.template_tasks.length} tasks and ${ev.assessments.length} assessments.`);
                } catch (tErr) {
                    console.error("[SessionDetails] Curriculum Sync Failure:", tErr);
                }
            } else {
                console.warn("[SessionDetails] No Template ID detected on session document.");
            }

            setSession(ev);

            if (isStaff) {
                const assignedIds = ev.assigned_member_ids || [];
                const filteredUsers = usersData.filter(u => assignedIds.includes(u._id || u.id));
                setAttendees(filteredUsers);

                if (ev.attendance) {
                    setAttendanceMarks(ev.attendance);
                } else {
                    const initialMarks = {};
                    filteredUsers.forEach(u => initialMarks[u._id || u.id] = false);
                    setAttendanceMarks(initialMarks);
                }
            } else if (ev.attendance) {
                setAttendanceMarks(ev.attendance);
            }

        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSessionData();
    }, [sessionId]);

    // ─── Background Status Polling ───
    useEffect(() => {
        // If any resource is still processing, poll every 5 seconds
        const isProcessing = session?.resources?.some(r => r.status === 'processing');
        
        if (isProcessing) {
            const interval = setInterval(() => {
                console.log("Polling background resource status...");
                fetchSessionData();
            }, 5000);
            return () => clearInterval(interval);
        }
    }, [session?.resources]);

    const handleSaveAttendance = async () => {
        setSavingAttendance(true);
        try {
            await api.post(`/calendar/events/${sessionId}/attendance`, {
                attendees: attendanceMarks
            });
            setShowAttendanceModal(false);
            showSuccess("Attendance marked! Emails sent in the background.");
            fetchSessionData(); // Refresh to ensure we have the latest payload
        } catch (err) {
            console.error(err);
            showError("Failed to submit attendance.");
        } finally {
            setSavingAttendance(false);
        }
    };

    // Upload States
    const [uploadModalType, setUploadModalType] = useState(null); // 'content' or 'resource'
    const [uploadSource, setUploadSource] = useState('upload'); // 'upload' or 'library'
    const [uploadFile, setUploadFile] = useState(null);
    const [resourceType, setResourceType] = useState('pdf');
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);

    // Media Library States
    const [mediaItems, setMediaItems] = useState([]);
    const [selectedMediaId, setSelectedMediaId] = useState('');
    const [mediaSearchText, setMediaSearchText] = useState('');
    const [loadingMedia, setLoadingMedia] = useState(false);

    const openUploadModal = (type) => {
        setUploadModalType(type);
        setUploadSource('upload');
        setUploadFile(null);
        setSelectedMediaId('');
        setMediaSearchText('');
        setUploadProgress(0);
        if (mediaItems.length === 0) fetchMediaItems();
    };

    const fetchMediaItems = async () => {
        setLoadingMedia(true);
        try {
            const { data } = await api.get('/media', { params: { include_url: false } });
            setMediaItems(data);
        } catch (err) {
            console.error('Failed to load media library', err);
        } finally {
            setLoadingMedia(false);
        }
    };

    useEffect(() => {
        if (uploadModalType && uploadSource === 'library') {
            fetchMediaItems();
        }
    }, [uploadModalType, uploadSource]);

    const handleUploadSubmit = async () => {
        // ─── Add by reference from the Media Library ───
        if (uploadSource === 'library') {
            if (!selectedMediaId) return showError("Please select a file from the library.");
            setUploading(true);
            try {
                if (uploadModalType === 'resource') {
                    await api.post(`/calendar/events/${sessionId}/add-resource-from-media`, {
                        media_id: selectedMediaId,
                        resource_type: resourceType,
                    });
                } else {
                    await api.post(`/calendar/events/${sessionId}/add-content-from-media`, {
                        media_id: selectedMediaId,
                    });
                }
                showSuccess("Added from Media Library!");
                setUploadModalType(null);
                setSelectedMediaId('');
                setMediaSearchText('');
                fetchSessionData();
            } catch (err) {
                console.error(err);
                showError("Failed to add: " + (err.response?.data?.detail || "Unknown error"));
            } finally {
                setUploading(false);
            }
            return;
        }

        // ─── Upload a brand new file ───
        if (!uploadFile) return showError("Please select a file first.");
        setUploading(true);
        setUploadProgress(0);
        const formData = new FormData();
        formData.append('file', uploadFile);

        try {
            const config = {
                headers: { 'Content-Type': 'multipart/form-data' },
                onUploadProgress: (progressEvent) => {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    setUploadProgress(percentCompleted);
                }
            };

            if (uploadModalType === 'resource') {
                formData.append('resource_type', resourceType);
                await api.post(`/calendar/events/${sessionId}/upload-resource`, formData, config);
            } else {
                await api.post(`/calendar/events/${sessionId}/upload-content`, formData, config);
            }
            showSuccess("Upload successful!");
            setUploadModalType(null);
            setUploadFile(null);
            setUploadProgress(0);
            fetchSessionData();
        } catch (err) {
            console.error(err);
            const msg = err.response?.data?.detail || "Upload failed.";
            showError("Upload failed: " + msg);
        } finally {
            setUploading(false);
        }
    };

    const handleMarkCompleted = async () => {
        if (!window.confirm("Are you sure you want to mark this session as completed? This will update the attendance records and lock the session status.")) return;

        setCompleting(true);
        try {
            await api.patch(`/calendar/events/${sessionId}/complete`);
            showSuccess("Session marked as completed successfully!");
            fetchSessionData();
        } catch (err) {
            console.error(err);
            showError("Failed to mark session as completed: " + (err.response?.data?.detail || err.message));
        } finally {
            setCompleting(false);
        }
    };

    const toggleGptProject = async (pid) => {
        setUpdatingGpt(true);
        try {
            const currentProjects = session.gpt_projects || [];
            const isLinked = currentProjects.some(p => p.id === pid);
            let updatedProjects;
            
            if (isLinked) {
                updatedProjects = currentProjects.filter(p => p.id !== pid);
            } else {
                const selected = gptProjects.find(p => p.id === pid);
                if (!selected) return;
                updatedProjects = [...currentProjects, { id: selected.id, title: selected.title }];
            }

            await api.patch(`/calendar/events/${sessionId}`, {
                gpt_projects: updatedProjects
            });
            showSuccess("GPT projects updated successfully");
            fetchSessionData();
        } catch (err) {
            console.error(err);
            showError("Failed to update GPT projects");
        } finally {
            setUpdatingGpt(false);
        }
    };

    const handleLearnerUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            await api.post(`/calendar/events/${sessionId}/learner-upload`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            showSuccess(`"${file.name}" uploaded successfully!`);
            fetchSessionData();
        } catch (err) {
            showError("Failed to upload content");
        } finally {
            setUploading(false);
        }
    };

    const handleToggleTask = async (taskIdx) => {
        try {
            await api.post(`/companies/sessions/${sessionId}/tasks/toggle`, { 
                task_index: taskIdx 
            });
            showSuccess("Neural milestone updated!");
            fetchSessionData();
        } catch (err) {
            showError("Failed to sync task progress");
        }
    };
    
    const handleDeleteContent = async (contentId) => {
        if (!window.confirm("Are you sure you want to permanently delete this content?")) return;
        try {
            await api.delete(`/calendar/events/${sessionId}/contents/${contentId}`);
            showSuccess("Content removed successfully");
            fetchSessionData();
        } catch (err) {
            showError("Failed to remove content");
        }
    };

    const handleDeleteResource = async (resourceId, isProcessing = false) => {
        if (!window.confirm(`Are you sure you want to ${isProcessing ? 'cancel the processing and ' : ''}delete this resource?`)) return;
        try {
            await api.delete(`/calendar/events/${sessionId}/resources/${resourceId}`);
            showSuccess(isProcessing ? "Processing cancelled" : "Resource removed successfully");
            fetchSessionData();
        } catch (err) {
            showError("Failed to remove resource");
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
            </div>
        );
    }

    if (!session) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-[var(--text-muted)] space-y-4">
                <AlertCircle size={48} className="opacity-50" />
                <p className="text-xl font-bold tracking-tight">Session not found.</p>
                <button onClick={() => navigate(-1)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg font-bold text-[13px]">Go Back</button>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto space-y-8 pb-20 relative">
            {/* Header */}
            <div className="flex items-start justify-between">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate(-1)} className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <span className="px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center gap-1.5">
                                <Activity size={12} /> {session.type || 'Session'}
                            </span>
                            <span className={`px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest ${session.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : 'bg-orange-50 text-orange-600'}`}>
                                {session.status || 'Scheduled'}
                            </span>
                        </div>
                        <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight uppercase italic">{session.title}</h1>
                    </div>
                </div>

                <div className="flex gap-3">
                    {/* Common Join Button */}
                    {session.meeting_link && session.status !== 'completed' && (
                        <a 
                            href={session.meeting_link} 
                            target="_blank" 
                            rel="noreferrer" 
                            onClick={async () => {
                                try { await api.post(`/calendar/events/${sessionId}/track-join`); } catch(_e){ /* ignore tracking errors */ }
                            }}
                            className="flex items-center gap-2 h-10 px-6 bg-blue-600 text-white rounded-xl text-[12px] font-black hover:bg-blue-700 transition-all shadow-lg active:scale-95 uppercase tracking-widest"
                        >
                            <Video size={16} /> Join
                        </a>
                    )}
                    <div className="hidden sm:flex flex-col items-end border-l border-[var(--border)] pl-4 ml-2">
                        <div className="flex items-center gap-1.5 text-[11px] font-black text-[var(--text-main)] uppercase italic tracking-tighter">
                            <CalendarIcon size={12} className="text-[var(--accent-indigo)]" /> {new Date(session.start).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] font-bold text-[var(--text-muted)] uppercase">
                             {new Date(session.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                    </div>
                    {isStaff && (
                        <>
                            {session.status !== 'completed' && (
                                <button
                                    onClick={handleMarkCompleted}
                                    disabled={completing}
                                    className="flex items-center gap-2 h-10 px-5 bg-indigo-600 text-white border border-indigo-700 rounded-xl text-[13px] font-black hover:bg-indigo-700 transition-all shadow-md active:scale-95 disabled:opacity-50"
                                >
                                    {completing ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div> : <CheckCircle size={16} />}
                                    Mark Completed
                                </button>
                            )}
                            <button onClick={() => setShowAttendanceModal(true)} className="flex items-center gap-2 h-10 px-5 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-[13px] font-black hover:bg-emerald-500 hover:text-white transition-all shadow-sm">
                                <UserCheck size={16} /> Mark Attendance
                            </button>
                        </>
                    )}
                </div>
            </div>

            {/* Content Details */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                {/* Left Card: Core Info */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] p-6 rounded-[24px] shadow-sm">
                        <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4 border-b border-[var(--border)] pb-3">Session Technical Brief</h3>

                        <div className="grid grid-cols-2 gap-4 mb-4">
                            <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-transparent">
                                <span className="flex items-center gap-2 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-1"><CalendarIcon size={12} /> Full Date</span>
                                <p className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">
                                    {new Date(session.start).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
                                </p>
                            </div>
                            <div className="p-3 bg-[var(--input-bg)] rounded-xl border border-transparent">
                                <span className="flex items-center gap-2 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-1"><Clock size={12} /> Execution Window</span>
                                <p className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">
                                    {new Date(session.start).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}
                                    {session.end && ` — ${new Date(session.end).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}`}
                                </p>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <span className="flex items-center gap-2 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-1">Operational Instructions</span>
                            {session.additional_details ? (
                                <p className="text-[13px] leading-relaxed text-[var(--text-main)] bg-white border border-[var(--border)] p-4 rounded-xl whitespace-pre-wrap font-medium">
                                    {session.additional_details}
                                </p>
                            ) : (
                                <p className="text-[13px] italic text-[var(--text-muted)] opacity-60">No additional instructions provided for this session.</p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Right Card: Participants & Settings */}
                <div className="space-y-6">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] p-6 rounded-[24px] shadow-sm">
                        <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-6 flex items-center gap-2"><Users2 size={16} /> Scope</h3>

                        <div className="space-y-5">
                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Delegated To (Departments)</label>
                                <div className="flex flex-wrap gap-2">
                                    {session.assigned_departments?.length > 0 ? (
                                        session.assigned_departments.map((d, i) => <span key={i} className="px-3 py-1 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[11px] font-bold">{d}</span>)
                                    ) : <span className="text-[12px] text-[var(--text-muted)] italic">N/A</span>}
                                </div>
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Type</label>
                                <p className="text-[13px] font-bold text-[var(--text-main)]">{session.session_type || 'General'}</p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Priority Segment</label>
                                <p className={`text-[13px] font-black ${session.priority === 'High' || session.priority === 'Urgent' ? 'text-red-500' : 'text-[var(--text-main)]'}`}>{session.priority || 'Normal'}</p>
                            </div>

                            {isStaff ? (
                                <div className="space-y-2 pt-4 border-t border-[var(--border)]">
                                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                                        <Bot size={14} className="text-[var(--accent-indigo)]" /> Linked GPT Projects
                                    </label>
                                    <div className="flex flex-wrap gap-2 mb-2">
                                        {(session.gpt_projects || []).map(p => (
                                            <div key={p.id} className="flex items-center gap-2 px-2 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-md text-[11px] font-bold border border-[var(--accent-indigo-border)]">
                                                {p.title}
                                                <button onClick={() => toggleGptProject(p.id)} disabled={updatingGpt}>
                                                    <X size={12} />
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                    <select
                                        value=""
                                        onChange={(e) => toggleGptProject(e.target.value)}
                                        disabled={updatingGpt}
                                        className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] disabled:opacity-50"
                                    >
                                        <option value="">Add GPT Project...</option>
                                        {gptProjects.filter(p => !(session.gpt_projects || []).some(x => x.id === p.id)).map(p => (
                                            <option key={p.id} value={p.id}>{p.title}</option>
                                        ))}
                                    </select>
                                </div>
                            ) : (session.gpt_projects || []).length > 0 && (
                                <div className="space-y-2 pt-4 border-t border-[var(--border)]">
                                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                                        <Bot size={14} className="text-[var(--accent-indigo)]" /> Neural Engines Available
                                    </label>
                                    <div className="flex flex-wrap gap-2">
                                        {session.gpt_projects.map(p => (
                                            <button 
                                                key={p.id}
                                                onClick={() => navigate(`/gpt/chat?project=${p.id}`)}
                                                className="px-3 py-1 bg-white border border-[var(--accent-indigo-border)] text-[var(--accent-indigo)] rounded-md text-[11px] font-black uppercase tracking-tight hover:bg-[var(--accent-indigo-bg)] transition-all flex items-center gap-1.5"
                                            >
                                                <Bot size={12} /> {p.title}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Uploaded Materials rendering */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4">
                {/* Content - Downloadable */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                            <UploadCloud size={16} className="text-[var(--accent-indigo)]" /> Shared Content
                        </h3>
                        {isStaff && (
                            <button onClick={() => openUploadModal('content')} className="px-3 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-lg text-[9px] font-black uppercase tracking-widest border border-[var(--accent-indigo-border)] hover:bg-[var(--accent-indigo)] hover:text-white transition-all">
                                Upload New
                            </button>
                        )}
                    </div>
                    <div className="space-y-2">
                        {session.contents && session.contents.length > 0 ? (
                            session.contents.map((item, idx) => (
                                <div key={idx} className="flex items-center justify-between p-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl group/item">
                                    <span className="text-[12px] font-bold text-[var(--text-main)] truncate max-w-[200px]">{item.name}</span>
                                    <div className="flex items-center gap-2">
                                        <a href={item.url} target="_blank" rel="noreferrer" download className="px-3 py-1.5 bg-blue-50 text-blue-700 text-[10px] font-black uppercase rounded-lg hover:bg-blue-100 transition-colors">
                                            Download
                                        </a>
                                        {isStaff && (
                                            <button 
                                                onClick={() => handleDeleteContent(item.id)}
                                                className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover/item:opacity-100"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No content uploaded yet.</p>
                        )}
                    </div>
                </div>

                {/* Resources - View Only */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                            <FileUp size={16} className="text-amber-500" /> Executive Resources
                        </h3>
                        {isStaff && (
                            <button onClick={() => openUploadModal('resource')} className="px-3 py-1 bg-amber-50 text-amber-600 rounded-lg text-[9px] font-black uppercase tracking-widest border border-amber-200 hover:bg-amber-500 hover:text-white transition-all">
                                <PlusCircle size={10} className="inline mr-1" /> Add Source
                            </button>
                        )}
                    </div>
                    <div className="space-y-2">
                        {session.resources && session.resources.length > 0 ? (
                            session.resources.map((item, idx) => (
                                <div key={idx} className="flex flex-col bg-[var(--input-bg)] border border-[var(--border)] rounded-xl overflow-hidden group/item">
                                    <div className="flex items-center justify-between p-3 border-b border-transparent">
                                        <div className="flex flex-col flex-1 min-w-0">
                                            <span className="text-[12px] font-bold text-[var(--text-main)] truncate max-w-[180px]">{item.name}</span>
                                            <div className="flex items-center gap-2 mt-0.5">
                                                <span className="text-[9px] font-black uppercase text-amber-600">
                                                    {item.system_type} {item.status === 'processing' && `— Processing... ${item.progress || 0}%`}
                                                    {item.status === 'failed' && '— Failed'}
                                                </span>
                                                {item.status === 'processing' && (
                                                    <div className="flex-1 max-w-[100px] h-1 bg-amber-100 rounded-full overflow-hidden">
                                                        <div className="h-full bg-amber-500 transition-all duration-500" style={{ width: `${item.progress || 0}%` }}></div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {item.status === 'processing' ? (
                                                <>
                                                    <div className="w-5 h-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
                                                    {isStaff && (
                                                        <button 
                                                            onClick={() => handleDeleteResource(item.id, true)}
                                                            className="flex items-center gap-1.5 px-2 py-1 bg-red-50 text-red-500 rounded-lg text-[9px] font-black uppercase tracking-widest hover:bg-red-500 hover:text-white transition-all ml-2"
                                                            title="Cancel Process"
                                                        >
                                                            <Ban size={12} /> Cancel
                                                        </button>
                                                    )}
                                                </>
                                            ) : item.status === 'failed' ? (
                                                <div className="flex items-center gap-2">
                                                    <AlertCircle size={16} className="text-red-500" />
                                                    {isStaff && (
                                                        <button onClick={() => handleDeleteResource(item.id)} className="p-1.5 text-red-400 hover:text-red-600">
                                                            <Trash2 size={14} />
                                                        </button>
                                                    )}
                                                </div>
                                            ) : (
                                                <>
                                                    <button onClick={() => navigate(`/sessions/${sessionId}/resource/${item.id}`)} className="px-3 py-1.5 bg-gray-200 text-gray-700 text-[10px] font-black uppercase rounded-lg hover:bg-gray-300 transition-colors">
                                                        View Content
                                                    </button>
                                                    {isStaff && (
                                                        <button 
                                                            onClick={() => handleDeleteResource(item.id)}
                                                            className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover/item:opacity-100"
                                                        >
                                                            <Trash2 size={14} />
                                                        </button>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No resources uploaded yet.</p>
                        )}
                    </div>
                </div>
                {/* Session Learning Tasks */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm overflow-hidden flex flex-col">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                                <ListTodo size={16} className="text-emerald-500" /> Session Tasks
                            </h3>
                            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-tighter mt-1">Curriculum Benchmarks</p>
                        </div>
                        <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full uppercase tracking-widest">
                            {session.template_tasks?.length || 0} Total
                        </span>
                    </div>
                    <div className="space-y-2 flex-1 overflow-y-auto max-h-[350px] no-scrollbar">
                        {session.template_tasks && session.template_tasks.length > 0 ? (
                            session.template_tasks.map((task, idx) => {
                                const isDone = (session.session_tasks || []).find(t => t.index === idx)?.is_done;
                                return (
                                    <div 
                                        key={idx} 
                                        onClick={() => isStaff ? null : handleToggleTask(idx)}
                                        className={`group flex items-center justify-between p-4 border rounded-2xl transition-all ${isStaff ? 'cursor-default' : 'cursor-pointer hover:border-emerald-500/30'} ${isDone ? 'bg-emerald-50 border-emerald-100' : 'bg-[var(--input-bg)] border-transparent'}`}
                                    >
                                        <div className="flex flex-col">
                                            <span className={`text-[13px] font-black uppercase tracking-tight ${isDone ? 'text-emerald-700' : 'text-[var(--text-main)]'}`}>{task.title}</span>
                                            <div className="flex items-center gap-2 mt-1">
                                                <span className="text-[9px] font-bold uppercase text-[var(--text-muted)] opacity-60 flex items-center gap-1">
                                                    <Target size={10} /> {task.points} Training Points
                                                </span>
                                                {isDone && <span className="text-[9px] font-black text-emerald-600 uppercase tracking-widest flex items-center gap-1">• <CheckCircle size={10}/> Authenticated</span>}
                                            </div>
                                        </div>
                                        {!isStaff && (
                                            <div className={`w-8 h-8 rounded-xl flex items-center justify-center transition-all ${isDone ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-200' : 'bg-white border-2 border-gray-100 group-hover:border-emerald-500'}`}>
                                                {isDone ? <CheckCircle size={14} /> : <div className="w-2 h-2 rounded-full bg-gray-200"></div>}
                                            </div>
                                        )}
                                        {isStaff && isDone && (
                                            <div className="w-8 h-8 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center">
                                                <CheckCircle size={16} />
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        ) : (
                            <div className="flex flex-col items-center justify-center p-12 opacity-40 italic border-2 border-dashed border-gray-100 rounded-2xl">
                                <ListTodo size={32} className="mb-2 text-gray-400" />
                                <p className="text-[10px] font-black uppercase tracking-widest">No Curriculum Tasks</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Session Assessments (Quizzes) */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm flex flex-col">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest flex items-center gap-2">
                                <FileQuestion size={16} className="text-purple-500" /> Knowledge Checks
                            </h3>
                            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-tighter mt-1">Quality Assessments</p>
                        </div>
                        <span className="text-[10px] font-bold text-purple-600 bg-purple-50 px-2 py-0.5 rounded-full uppercase tracking-widest">
                             {session.assessments?.length || 0} Active
                        </span>
                    </div>
                    <div className="space-y-3 flex-1 overflow-y-auto max-h-[350px] no-scrollbar">
                        {session.assessments && session.assessments.length > 0 ? (
                            session.assessments.map((quiz, idx) => (
                                <div 
                                    key={idx} 
                                    className="flex items-center gap-4 p-4 bg-[var(--input-bg)] border border-transparent rounded-2xl transition-all group"
                                >
                                    <div className="w-12 h-12 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center transition-transform shadow-sm">
                                        <BookOpen size={20} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-[13px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{quiz.title}</p>
                                        <div className="flex items-center gap-3 mt-1">
                                            <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase flex items-center gap-1">
                                                <Target size={10} /> Passing: {quiz.passing_score}%
                                            </p>
                                            <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase flex items-center gap-1">
                                                <Clock size={10} /> {quiz.questions?.length || 0} Questions
                                            </p>
                                        </div>
                                    </div>
                                    <button 
                                        onClick={() => navigate(`/assessment/${sessionId}/${idx}`)} 
                                        className="p-3 rounded-2xl bg-white border border-gray-100 text-purple-600 hover:bg-purple-600 hover:text-white transition-all shadow-sm"
                                        title={isStaff ? "Audit Content" : "Initiate Verification"}
                                    >
                                        <Eye size={18} />
                                    </button>
                                </div>
                            ))
                        ) : (
                            <div className="flex flex-col items-center justify-center p-12 opacity-40 italic border-2 border-dashed border-gray-100 rounded-2xl">
                                <HelpCircle size={32} className="mb-2 text-gray-400" />
                                <p className="text-[10px] font-black uppercase tracking-widest">No Assessments Linked</p>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Submissions Section (Moved for clarity if still needed, but hiding for now as per "in place of" request) */}
            {(session.learner_contents || []).length > 0 && isStaff && (
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm">
                    <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-6 flex items-center gap-2">
                        <UploadCloud size={20} className="text-purple-500" /> Historical Deliverables
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {session.learner_contents.map((item, idx) => (
                            <a 
                                key={idx} 
                                href={item.url} 
                                target="_blank" 
                                rel="noreferrer"
                                className="flex items-center gap-3 p-4 bg-white border border-[var(--border)] rounded-2xl hover:border-purple-500 hover:shadow-sm transition-all group"
                            >
                                <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center group-hover:bg-purple-600 group-hover:text-white transition-all">
                                    <FileText size={18} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="text-[13px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{item.name}</p>
                                    <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase truncate">
                                        {item.uploader_name} • {new Date(item.uploaded_at).toLocaleDateString()}
                                    </p>
                                </div>
                            </a>
                        ))}
                    </div>
                </div>
            )}

            {/* Attendance Modal Overlay */}
            {showAttendanceModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowAttendanceModal(false)} />
                    <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative bg-[var(--bg-card)] border border-[var(--border)] w-full max-w-xl rounded-3xl shadow-2xl p-8 flex flex-col max-h-[85vh]">
                        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
                            <h2 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2">
                                <UserCheck className="text-[var(--accent-indigo)]" /> Manage Attendance
                            </h2>
                            <button onClick={() => setShowAttendanceModal(false)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors p-1 bg-[var(--input-bg)] rounded-lg">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="flex-1 overflow-y-auto no-scrollbar mb-6 border border-[var(--border)] rounded-2xl bg-[var(--input-bg)] p-2">
                            {attendees.length > 0 ? (
                                <div className="space-y-1">
                                    {attendees.map(u => {
                                        const uid = u._id || u.id;
                                        const isPresent = attendanceMarks[uid] || false;
                                        return (
                                            <div key={uid} className={`flex items-center justify-between p-3 rounded-xl border transition-all ${isPresent ? 'bg-emerald-50 border-emerald-200 shadow-sm' : 'bg-white border-transparent hover:border-gray-200'}`}>
                                                <div className="flex flex-col">
                                                    <span className={`text-[13px] font-black ${isPresent ? 'text-emerald-800' : 'text-[var(--text-main)]'}`}>{u.full_name || u.first_name || u.email}</span>
                                                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase">{u.department || 'No Dept'}</span>
                                                </div>
                                                <label className="flex items-center gap-2 cursor-pointer">
                                                    <span className={`text-[10px] font-black uppercase ${isPresent ? 'text-emerald-600' : 'text-gray-400'}`}>{isPresent ? 'Present' : 'Absent'}</span>
                                                    <input type="checkbox" checked={isPresent} onChange={e => setAttendanceMarks({ ...attendanceMarks, [uid]: e.target.checked })} className="w-5 h-5 accent-emerald-500 rounded-lg cursor-pointer" />
                                                </label>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center p-10 text-[var(--text-muted)] opacity-70">
                                    <Users2 size={32} className="mb-2" />
                                    <p className="text-[12px] font-bold uppercase tracking-widest">No assigned attendees found.</p>
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-3 pt-4 border-t border-[var(--border)]">
                            <button onClick={() => setShowAttendanceModal(false)} className="px-6 py-2.5 bg-[var(--input-bg)] text-[var(--text-muted)] rounded-xl text-[12px] font-black border border-[var(--border)] hover:bg-gray-100 transition-colors">
                                Cancel
                            </button>
                            <button onClick={handleSaveAttendance} disabled={savingAttendance} className="px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[12px] font-black hover:opacity-90 transition-all flex items-center gap-2 shadow-lg disabled:opacity-50">
                                {savingAttendance ? 'Saving...' : 'Save & Send Notifications'}
                            </button>
                        </div>
                    </motion.div>
                </div>
            )}

            {/* Upload Modal */}
            {uploadModalType && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setUploadModalType(null)} />
                    <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative bg-[var(--bg-card)] border border-[var(--border)] w-full max-w-md rounded-3xl shadow-2xl p-8 flex flex-col">
                        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
                            <h2 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2">
                                {uploadModalType === 'resource' ? <FileUp className="text-amber-500" /> : <UploadCloud className="text-[var(--accent-indigo)]" />}
                                Upload {uploadModalType === 'resource' ? 'Resource' : 'Content'}
                            </h2>
                            <button onClick={() => setUploadModalType(null)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors p-1 bg-[var(--input-bg)] rounded-lg">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="space-y-6 flex-1">
                            {/* Source toggle: upload a new file OR pick one already in the Media Library */}
                            <div className="grid grid-cols-2 gap-2 p-1 bg-[var(--input-bg)] rounded-2xl border border-[var(--border)]">
                                <button
                                    type="button"
                                    onClick={() => setUploadSource('upload')}
                                    className={`py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${uploadSource === 'upload' ? 'bg-[var(--accent-indigo)] text-white shadow' : 'text-[var(--text-muted)]'}`}
                                >
                                    Upload New
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setUploadSource('library')}
                                    className={`py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-all ${uploadSource === 'library' ? 'bg-[var(--accent-indigo)] text-white shadow' : 'text-[var(--text-muted)]'}`}
                                >
                                    From Library
                                </button>
                            </div>

                            {uploadModalType === 'resource' && (
                                <div className="space-y-2">
                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Resource Format</label>
                                    <select value={resourceType} onChange={e => setResourceType(e.target.value)}
                                        className="w-full bg-[var(--input-bg)] px-4 py-3 border border-[var(--border)] rounded-[16px] text-sm font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all">
                                        <option value="video">Video</option>
                                        <option value="audio">Audio</option>
                                        <option value="pdf">PDF Document</option>
                                        <option value="excel">Excel Sheet</option>
                                        <option value="other">Other</option>
                                    </select>
                                    {uploadSource === 'library' && (
                                        <p className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
                                            Audio/Video resources are auto-transcribed after adding.
                                        </p>
                                    )}
                                </div>
                            )}

                            {uploadSource === 'library' ? (
                                <div className="space-y-2">
                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Select From Media Library</label>
                                    {loadingMedia ? (
                                        <p className="text-[12px] text-[var(--text-muted)] italic py-2">Loading library…</p>
                                    ) : mediaItems.length === 0 ? (
                                        <p className="text-[12px] text-[var(--text-muted)] italic py-2">No files in the Media Library yet.</p>
                                    ) : (
                                        <div className="relative">
                                            <input
                                                list="media-library-options"
                                                value={mediaSearchText}
                                                onChange={e => {
                                                    const val = e.target.value;
                                                    setMediaSearchText(val);
                                                    const match = mediaItems.find(m =>
                                                        m.name === val ||
                                                        `${m.name} (${m.media_type})` === val ||
                                                        m._id === val
                                                    );
                                                    if (match) {
                                                        setSelectedMediaId(match._id);
                                                        if (uploadModalType === 'resource' && match.media_type) {
                                                            setResourceType(match.media_type);
                                                        }
                                                    } else {
                                                        setSelectedMediaId('');
                                                    }
                                                }}
                                                placeholder="Choose a file or type to search…"
                                                className="w-full bg-[var(--input-bg)] px-4 py-3 border border-[var(--border)] rounded-[16px] text-sm font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all"
                                            />
                                            <datalist id="media-library-options">
                                                {mediaItems.map(m => (
                                                    <option key={m._id} value={`${m.name} (${m.media_type})`}>
                                                        {m.name}
                                                    </option>
                                                ))}
                                            </datalist>
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Select File</label>
                                    <input type="file" onChange={e => setUploadFile(e.target.files[0])}
                                        className="w-full bg-[var(--input-bg)] px-4 py-3 border border-dashed border-[var(--border)] rounded-[16px] text-sm font-bold text-[var(--text-muted)] outline-none focus:border-[var(--accent-indigo)] transition-all
                                            file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-[11px] file:font-black file:uppercase file:bg-[var(--accent-indigo-bg)] file:text-[var(--accent-indigo)] hover:file:opacity-90" />
                                </div>
                            )}

                            {uploading && uploadSource === 'upload' && (
                                <div className="space-y-2 pt-2">
                                    <div className="flex justify-between items-center text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                        <span>Server Transfer Progress</span>
                                        <span>{uploadProgress}%</span>
                                    </div>
                                    <div className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-full h-2.5 overflow-hidden">
                                        <div className="bg-[var(--accent-indigo)] h-2.5 rounded-full transition-all duration-300 ease-out" style={{ width: `${uploadProgress}%` }}></div>
                                    </div>
                                    {uploadProgress === 100 && <p className="text-[10px] text-emerald-600 font-bold text-center mt-1">Finalizing with backend...</p>}
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-3 pt-6 border-t border-[var(--border)] mt-6">
                            <button onClick={() => setUploadModalType(null)} className="px-6 py-2.5 bg-[var(--input-bg)] text-[var(--text-muted)] rounded-xl text-[12px] font-black border border-[var(--border)] hover:bg-gray-100 transition-colors">
                                Cancel
                            </button>
                            <button onClick={handleUploadSubmit} disabled={uploading} className="px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[12px] font-black hover:opacity-90 transition-all flex items-center gap-2 shadow-lg disabled:opacity-50">
                                {uploading ? 'Processing...' : (uploadSource === 'library' ? 'Add From Library' : 'Upload File')}
                            </button>
                        </div>
                    </motion.div>
                </div>
            )}
        </div>
    );
};

export default SessionDetails;
