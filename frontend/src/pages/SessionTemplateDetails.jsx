import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ArrowLeft, Copy, Pencil, Trash2, Plus, 
  CheckCircle2, XCircle, FileText, Target, 
  HelpCircle, ChevronDown, ListCheck, Send,
  Trash, Save, Trash2Icon, MessageSquare, 
  Layout, BookOpen, Settings
} from 'lucide-react';

const SessionTemplateDetails = () => {
    const { templateId } = useParams();
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();

    const [template, setTemplate] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('tasks');
    
    // Task State
    const [showTaskModal, setShowTaskModal] = useState(false);
    const [taskRows, setTaskRows] = useState([{ title: '', points: 0 }]);
    const [editTaskIdx, setEditTaskIdx] = useState(null);
    
    const [showQuizModal, setShowQuizModal] = useState(false);
    const [editQuizIdx, setEditQuizIdx] = useState(null);
    const [quizForm, setQuizForm] = useState({
        title: '', passing_score: 70, shuffle_questions: false,
        questions: [{ question_text: '', type: 'MCQ', options: ['', '', '', ''], correct_option_index: 0, marks: 1 }]
    });

    const fetchData = async () => {
        try {
            const res = await api.get(`/session-templates/${templateId}`);
            const data = res.data;
            setTemplate(data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    useEffect(() => { fetchData(); }, [templateId]);

    // Tasks 🚀
    const addTaskRow = () => setTaskRows([...taskRows, { title: '', points: 0 }]);
    const removeTaskRow = (idx) => setTaskRows(taskRows.filter((_, i) => i !== idx));
    const handleTaskChange = (idx, field, val) => {
        const newRows = [...taskRows];
        newRows[idx][field] = val;
        setTaskRows(newRows);
    };

    const handleSaveTasks = async () => {
        try {
            const filtered = taskRows.filter(t => t.title.trim() !== '');
            if (filtered.length === 0) return setShowTaskModal(false);

            let finalTasks;
            if (editTaskIdx !== null) {
                finalTasks = [...(template.tasks || [])];
                finalTasks[editTaskIdx] = filtered[0];
            } else {
                finalTasks = [...(template.tasks || []), ...filtered];
            }

            await api.post(`/session-templates/${templateId}/tasks`, finalTasks);
            setShowTaskModal(false);
            setEditTaskIdx(null);
            showSuccess(editTaskIdx !== null ? "Task updated" : "Learning tasks saved");
            fetchData();
        } catch (err) { showError('Failed to save tasks'); }
    };

    const handleEditTask = (idx) => {
        setEditTaskIdx(idx);
        setTaskRows([template.tasks[idx]]);
        setShowTaskModal(true);
    };

    const handleDeleteTask = async (idx) => {
        if (!window.confirm("Are you sure you want to delete this task?")) return;
        const newTasks = template.tasks.filter((_, i) => i !== idx);
        try {
            await api.post(`/session-templates/${templateId}/tasks`, newTasks);
            showSuccess("Task deleted");
            fetchData();
        } catch (err) { showError('Delete failed'); }
    };

    // Assessments 📝
    const addQuestion = () => setQuizForm({
        ...quizForm, questions: [...quizForm.questions, { question_text: '', type: 'MCQ', options: ['', '', '', ''], correct_option_index: 0, marks: 1 }]
    });
    
    const removeQuestion = (idx) => setQuizForm({
        ...quizForm, questions: quizForm.questions.filter((_, i) => i !== idx)
    });

    const handleQuizChange = (qIdx, field, val) => {
        const newQuestions = [...quizForm.questions];
        newQuestions[qIdx][field] = val;
        setQuizForm({ ...quizForm, questions: newQuestions });
    };

    const handleOptionChange = (qIdx, oIdx, val) => {
        const newQuestions = [...quizForm.questions];
        newQuestions[qIdx].options[oIdx] = val;
        setQuizForm({ ...quizForm, questions: newQuestions });
    };

    const handleEditAssessment = (idx) => {
        setEditQuizIdx(idx);
        setQuizForm(template.assessments[idx]);
        setShowQuizModal(true);
    };

    const handleSaveQuiz = async () => {
        try {
            let newAssessments;
            if (editQuizIdx !== null) {
                newAssessments = [...template.assessments];
                newAssessments[editQuizIdx] = quizForm;
            } else {
                newAssessments = [...(template.assessments || []), quizForm];
            }
            await api.post(`/session-templates/${templateId}/assessments`, newAssessments);
            setShowQuizModal(false);
            setEditQuizIdx(null);
            setQuizForm({
                title: '', passing_score: 70, shuffle_questions: false,
                questions: [{ question_text: '', type: 'MCQ', options: ['', '', '', ''], correct_option_index: 0, marks: 1 }]
            });
            showSuccess(editQuizIdx !== null ? "Quiz updated" : "Quiz library updated");
            fetchData();
        } catch (err) { showError('Failed to save quiz'); }
    };

    const handleDeleteAssessment = async (idx) => {
        const newAssessments = template.assessments.filter((_, i) => i !== idx);
        try {
            await api.post(`/session-templates/${templateId}/assessments`, newAssessments);
            showSuccess("Assessment deleted");
            fetchData();
        } catch (err) { showError('Delete failed'); }
    }

    if (loading) return <div className="py-20 text-center"><div className="w-8 h-8 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin mx-auto"></div></div>;
    if (!template) return <div className="py-20 text-center text-[var(--text-muted)]">Template not found</div>;

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center gap-4">
                <button onClick={() => navigate('/session-templates')} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] transition-all">
                    <ArrowLeft size={18} />
                </button>
                <div className="w-11 h-11 bg-[var(--accent-indigo-bg)] rounded-xl flex items-center justify-center text-[var(--accent-indigo)]">
                    <Copy size={22} />
                </div>
                <div>
                    <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">{template.title}</h1>
                    <p className="text-[12px] font-bold text-[var(--accent-orange)] uppercase tracking-wider">{template.topic}</p>
                </div>
            </div>

            {/* Info */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] p-6 rounded-2xl shadow-sm">
                <div className="flex items-start gap-4">
                    <div className="p-3 bg-[var(--input-bg)] rounded-xl text-[var(--text-muted)]"><FileText size={20} /></div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest block">Description</label>
                        <p className="text-[13px] text-[var(--text-main)] leading-relaxed font-medium">{template.description || 'No description provided.'}</p>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl w-fit shadow-sm">
                <button onClick={() => setActiveTab('tasks')} className={`px-5 py-2.5 rounded-lg text-[12px] font-bold transition-all flex items-center gap-2 ${activeTab === 'tasks' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                    <ListCheck size={16} /> Tasks ({template?.tasks?.length || 0})
                </button>
                <button onClick={() => setActiveTab('assessments')} className={`px-5 py-2.5 rounded-lg text-[12px] font-bold transition-all flex items-center gap-2 ${activeTab === 'assessments' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                    <Target size={16} /> Assessments ({template?.assessments?.length || 0})
                </button>
            </div>

            <AnimatePresence mode="wait">
                {activeTab === 'tasks' ? (
                    <motion.div key="tasks" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-4">
                        <div className="flex justify-between items-center px-1">
                            <h2 className="text-[14px] font-bold text-[var(--text-main)]">Learning Tasks</h2>
                            <button onClick={() => {
                                setEditTaskIdx(null);
                                setTaskRows([{ title: '', points: 0 }]);
                                setShowTaskModal(true);
                            }} className="h-8 px-3 bg-[var(--btn-primary)] text-white text-[11px] font-bold rounded-lg flex items-center gap-1.5 shadow-sm">
                                <Plus size={14} /> Add Tasks
                            </button>
                        </div>
                        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl overflow-hidden shadow-sm">
                            <table className="w-full">
                                <thead>
                                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                                        <th className="px-6 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">#</th>
                                        <th className="px-6 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Task Title</th>
                                        <th className="px-6 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Weightage/Points</th>
                                        <th className="px-6 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-[var(--border)]">
                                    {template?.tasks?.map((t, idx) => (
                                        <tr key={idx} className="hover:bg-[var(--table-hover)] transition-all">
                                            <td className="px-6 py-3 text-[12px] font-bold text-[var(--text-muted)]">{idx + 1}</td>
                                            <td className="px-6 py-3 text-[13px] font-bold text-[var(--text-main)]">{t.title}</td>
                                            <td className="px-6 py-3">
                                                <span className="px-2 py-0.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)] rounded-md text-[11px] font-bold">
                                                    {t.points} Points
                                                </span>
                                            </td>
                                            <td className="px-6 py-3 text-right">
                                                <div className="flex justify-end gap-1">
                                                    <button onClick={() => handleEditTask(idx)} className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-all">
                                                        <Pencil size={14} />
                                                    </button>
                                                    <button onClick={() => handleDeleteTask(idx)} className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-all">
                                                        <Trash size={14} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                    {(!template?.tasks || template.tasks.length === 0) && (
                                        <tr><td colSpan={4} className="px-6 py-12 text-center text-[var(--text-muted)] text-[13px]">No tasks defined yet. Click "Add Tasks" to start building.</td></tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </motion.div>
                ) : (
                    <motion.div key="assessments" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-4">
                        <div className="flex justify-between items-center px-1">
                            <h2 className="text-[14px] font-bold text-[var(--text-main)]">Module Quizzes</h2>
                            <button onClick={() => setShowQuizModal(true)} className="h-8 px-3 bg-[var(--btn-primary)] text-white text-[11px] font-bold rounded-lg flex items-center gap-1.5 shadow-sm">
                                <Plus size={14} /> Create Quiz
                            </button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {template?.assessments?.map((a, idx) => (
                                <div key={idx} className="bg-[var(--bg-card)] border border-[var(--border)] p-5 rounded-2xl group hover:border-[var(--accent-indigo-border)] transition-all shadow-sm">
                                    <div className="flex justify-between items-start mb-3">
                                        <div className="p-2 bg-[var(--accent-orange-bg)] rounded-lg text-[var(--accent-orange)]"><MessageSquare size={18} /></div>
                                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                                            <button onClick={() => handleEditAssessment(idx)} className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-all"><Pencil size={14} /></button>
                                            <button onClick={() => handleDeleteAssessment(idx)} className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-all"><Trash size={14} /></button>
                                        </div>
                                    </div>
                                    <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">{a.title}</h3>
                                    <div className="flex items-center gap-4 mt-3">
                                        <div className="flex flex-col">
                                            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Pass Score</span>
                                            <span className="text-[12px] font-bold text-[var(--accent-green)]">{a.passing_score}%</span>
                                        </div>
                                        <div className="flex flex-col">
                                            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Questions</span>
                                            <span className="text-[12px] font-bold text-[var(--text-main)]">{a.questions.length} Q's • {a.questions.reduce((acc, q) => acc + (q.marks || 1), 0)} Marks</span>
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {(!template?.assessments || template.assessments.length === 0) && (
                                <div className="col-span-full py-16 text-center bg-[var(--bg-card)] border border-[var(--border)] border-dashed rounded-2xl text-[var(--text-muted)] text-[13px]">No assessments created yet. Click "Create Quiz" to begin.</div>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* ─── Task Modal (Image Match) ─── */}
            <Modal isOpen={showTaskModal} onClose={() => { setShowTaskModal(false); setEditTaskIdx(null); }} title={editTaskIdx !== null ? "Edit Task" : "Add Task Templates"}>
                <div className="space-y-4">
                    <div className="max-h-[300px] overflow-y-auto space-y-4 pr-1 scrollbar-thin">
                        {taskRows.map((row, idx) => (
                            <div key={idx} className="flex gap-4 items-end">
                                <div className="flex-1 space-y-1">
                                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Task Title</label>
                                    <div className="relative">
                                        <input placeholder="e.g. Design Homepage" className="w-full px-4 py-2 bg-[var(--input-bg)] rounded-xl outline-none focus:ring-1 focus:ring-[var(--accent-indigo)] text-[13px] font-medium"
                                            value={row.title} onChange={(e) => handleTaskChange(idx, 'title', e.target.value)} />
                                    </div>
                                </div>
                                <div className="w-20 space-y-1">
                                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Points</label>
                                    <input type="number" className="w-full px-3 py-2 bg-[var(--input-bg)] rounded-xl outline-none text-center text-[13px] font-bold"
                                        value={row.points} onChange={(e) => handleTaskChange(idx, 'points', parseInt(e.target.value))} />
                                </div>
                                <button onClick={() => removeTaskRow(idx)} className="mb-1 p-2 text-red-500 hover:bg-red-50 rounded-lg transition-all"><Trash2 size={18} /></button>
                            </div>
                        ))}
                    </div>
                    <div className="pt-4 border-t border-[var(--border)] flex items-center justify-between">
                        <button onClick={addTaskRow} className="flex items-center gap-2 text-[12px] font-bold text-[var(--accent-green)] border border-[var(--accent-green)] px-3 py-1.5 rounded-lg hover:bg-[var(--accent-green-bg)] transition-all">
                            <Plus size={14} /> Add More Task
                        </button>
                        <div className="flex gap-3">
                            <button onClick={() => { setShowTaskModal(false); setEditTaskIdx(null); }} className="px-6 py-2 text-[13px] font-bold text-[var(--text-muted)] hover:text-red-500 transition-all font-inter">Cancel</button>
                            <button onClick={handleSaveTasks} className="px-8 py-2 bg-[var(--accent-green)] text-white rounded-xl text-[13px] font-bold shadow-lg shadow-green-500/20 hover:opacity-90 transition-all">
                                {editTaskIdx !== null ? "Update Task" : "Create Tasks"}
                            </button>
                        </div>
                    </div>
                </div>
            </Modal>

            {/* ─── Quiz Modal (Advanced Builder) ─── */}
            <Modal isOpen={showQuizModal} onClose={() => {
                setShowQuizModal(false);
                setEditQuizIdx(null);
                setQuizForm({
                    title: '', passing_score: 70, shuffle_questions: false,
                    questions: [{ question_text: '', type: 'MCQ', options: ['', '', '', ''], correct_option_index: 0, marks: 1 }]
                });
            }} title={editQuizIdx !== null ? "Edit Quiz Architecture" : "Create New Quiz"}>
                <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-2 scrollbar-thin">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <label className="text-[11px] font-bold text-[var(--text-main)]">Quiz Title</label>
                            <input placeholder="e.g. Module 1 Assessment" className="w-full px-3 py-2 border border-[var(--border)] rounded-md outline-none focus:border-[var(--accent-indigo)] text-[13px] bg-[var(--input-bg)]"
                                value={quizForm.title} onChange={e => setQuizForm({...quizForm, title: e.target.value})} />
                        </div>
                        <div className="space-y-1">
                            <label className="text-[11px] font-bold text-[var(--text-main)]">Passing Score (%)</label>
                            <input type="number" className="w-full px-3 py-2 border border-[var(--border)] rounded-md outline-none text-[13px] bg-[var(--input-bg)]"
                                value={quizForm.passing_score} onChange={e => setQuizForm({...quizForm, passing_score: parseInt(e.target.value)})} />
                        </div>
                    </div>
                    
                    <div className="flex flex-wrap items-center gap-4 p-3 border border-[var(--border)] rounded-md bg-[var(--input-bg)]">
                        <label className="flex items-center gap-3 cursor-pointer">
                            <input type="checkbox" checked={quizForm.shuffle_questions} onChange={e => setQuizForm({...quizForm, shuffle_questions: e.target.checked})} className="w-4 h-4 rounded accent-[var(--accent-indigo)]" />
                            <span className="text-[13px] font-bold text-[var(--text-main)]">Shuffle Question & Limit</span>
                        </label>
                        
                        <AnimatePresence>
                            {quizForm.shuffle_questions && (
                                <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="flex items-center gap-2 pl-4 border-l border-[var(--border)]">
                                    <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Questions to Show:</span>
                                    <input type="number" placeholder="5" className="w-16 px-2 py-1 bg-[var(--bg-card)] border border-[var(--border)] rounded text-[12px] font-black text-[var(--text-main)]"
                                        value={quizForm.questions_to_show || ''} onChange={e => setQuizForm({...quizForm, questions_to_show: parseInt(e.target.value)})} />
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>

                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-2 pt-6">
                        <h3 className="text-[13px] font-extrabold text-[var(--text-main)] uppercase tracking-tight flex items-center gap-2">
                             <ListCheck size={16} /> Questions Library
                        </h3>
                        <div className="flex gap-4">
                            <button onClick={() => {
                                const templateStr = "Question,Type(MCQ/Descriptive),Option1,Option2,Option3,Option4,CorrectIndex(0-3),ExpectedAnswer,Instruction,Marks\nWhat is React?,MCQ,Library,Framework,Language,DB,0,,,1";
                                const blob = new Blob([templateStr], { type: 'text/csv' });
                                const url = window.URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = 'quiz_template.csv';
                                a.click();
                            }} className="flex items-center gap-1.5 text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest hover:opacity-70 transition-all">
                                <FileText size={12} /> Template
                            </button>
                            <label className="flex items-center gap-1.5 text-[10px] font-black text-[var(--accent-orange)] uppercase tracking-widest hover:opacity-70 transition-all cursor-pointer">
                                <Send size={12} className="rotate-270" /> Import
                                <input type="file" hidden accept=".csv" onChange={(e) => {
                                    const file = e.target.files[0];
                                    if (!file) return;
                                    const reader = new FileReader();
                                    reader.onload = (event) => {
                                        const csv = event.target.result;
                                        const lines = csv.split(/\r?\n/).filter(l => l.trim() !== '');
                                        const imported = lines.slice(1).map(row => {
                                            // Robust CSV splitting handling quotes and empty fields
                                            const cols = [];
                                            let col = '';
                                            let inQuotes = false;
                                            for (let i = 0; i < row.length; i++) {
                                                const char = row[i];
                                                if (char === '"') inQuotes = !inQuotes;
                                                else if (char === ',' && !inQuotes) {
                                                    cols.push(col);
                                                    col = '';
                                                } else {
                                                    col += char;
                                                }
                                            }
                                            cols.push(col);

                                            const cleanCols = cols.map(c => c.trim().replace(/^"|"$/g, '').replace(/""/g, '"'));
                                            
                                            const type = (cleanCols[1] || 'MCQ').trim();
                                            const isMCQ = type.toUpperCase() === 'MCQ';

                                            return {
                                                question_text: cleanCols[0],
                                                type: isMCQ ? 'MCQ' : 'Descriptive',
                                                options: isMCQ ? [cleanCols[2], cleanCols[3], cleanCols[4], cleanCols[5]] : [null, null, null, null],
                                                correct_option_index: isMCQ ? (parseInt(cleanCols[6]) || 0) : 0,
                                                expected_answer: !isMCQ ? cleanCols[7] : '',
                                                instruction: !isMCQ ? cleanCols[8] : '',
                                                marks: parseInt(cleanCols[9]) || 1
                                            };
                                        });
                                        setQuizForm({ ...quizForm, questions: [...quizForm.questions, ...imported] });
                                    };
                                    reader.readAsText(file);
                                }} />
                            </label>
                            <button onClick={addQuestion} className="flex items-center gap-1.5 text-[11px] font-black text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] px-3 py-1 rounded-md hover:opacity-90 transition-all uppercase tracking-widest border border-[var(--accent-indigo-border)]">
                                <Plus size={14} /> Add Question
                            </button>
                        </div>
                    </div>

                    <div className="space-y-8 pt-4 pb-10">
                        {quizForm.questions.map((q, qIdx) => (
                            <div key={qIdx} className="p-5 border border-[var(--border)] rounded-2xl bg-[var(--bg-card)] space-y-5 relative group/q shadow-sm hover:shadow-md transition-all">
                                <div className="flex gap-4 items-start">
                                    <div className="flex-1 space-y-1.5">
                                        <div className="flex items-center justify-between">
                                            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Question {qIdx + 1}</span>
                                            <div className="flex items-center gap-4">
                                                <div className="flex items-center gap-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1">
                                                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Mark:</span>
                                                    <input type="number" className="w-10 bg-transparent border-none outline-none text-[11px] font-black text-[var(--accent-indigo)] text-center"
                                                        value={q.marks} onChange={e => handleQuizChange(qIdx, 'marks', parseInt(e.target.value))} />
                                                </div>
                                                <select className="px-3 py-1 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[11px] font-black text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
                                                    value={q.type} onChange={e => handleQuizChange(qIdx, 'type', e.target.value)}>
                                                    <option value="MCQ">MCQ</option>
                                                    <option value="Descriptive">Descriptive</option>
                                                </select>
                                                <button onClick={() => removeQuestion(qIdx)} className="p-1.5 bg-red-50 to-red-500 rounded-lg border border-red-100 text-red-500 hover:bg-red-500 hover:text-white transition-all shadow-sm">
                                                    <Trash size={14} />
                                                </button>
                                            </div>
                                        </div>
                                        <textarea rows={2} placeholder="Enter your question here..." className="w-full px-4 py-2 bg-[var(--input-bg)] rounded-xl outline-none focus:ring-1 focus:ring-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] resize-none"
                                            value={q.question_text} onChange={e => handleQuizChange(qIdx, 'question_text', e.target.value)} />
                                    </div>
                                </div>
                                
                                <AnimatePresence mode="wait">
                                    {q.type === 'MCQ' ? (
                                        <motion.div key="mcq" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} className="grid grid-cols-1 md:grid-cols-2 gap-3 pl-2">
                                            {[0, 1, 2, 3].map(oIdx => (
                                                <div key={oIdx} className={`flex items-center gap-3 p-2 group/opt border rounded-xl transition-all ${q.correct_option_index === oIdx ? 'border-green-500 bg-green-50/50' : 'border-[var(--border)] bg-[var(--input-bg)]'}`}>
                                                    <button onClick={() => handleQuizChange(qIdx, 'correct_option_index', oIdx)}
                                                        className={`w-6 h-6 rounded-full flex items-center justify-center transition-all ${q.correct_option_index === oIdx ? 'bg-green-500 text-white scale-110 shadow-lg shadow-green-200' : 'bg-[var(--bg-card)] border-2 border-[var(--border)] text-transparent hover:border-green-400'}`}>
                                                        <CheckCircle2 size={14} />
                                                    </button>
                                                    <input placeholder={`Option ${oIdx + 1}`} className="flex-1 bg-transparent border-none outline-none text-[13px] font-medium text-[var(--text-main)]"
                                                        value={q.options?.[oIdx] || ''} onChange={e => handleOptionChange(qIdx, oIdx, e.target.value)} />
                                                </div>
                                            ))}
                                        </motion.div>
                                    ) : (
                                        <motion.div key="descriptive" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} className="space-y-4 pl-2">
                                            <div className="space-y-1">
                                                <label className="text-[10px] font-black text-[var(--accent-orange)] uppercase tracking-widest pl-1">Expected Core Answer (Keywords)</label>
                                                <textarea rows={2} placeholder="Explain the key points you expect..." className="w-full px-4 py-2 bg-[var(--input-bg)] border border-dashed border-[var(--accent-orange-border)] rounded-xl outline-none text-[13px] font-medium text-[var(--text-main)] focus:bg-[var(--bg-card)]"
                                                    value={q.expected_answer || ''} onChange={e => handleQuizChange(qIdx, 'expected_answer', e.target.value)} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest pl-1">Instruction for Checker (AI)</label>
                                                <input placeholder="e.g. AI should check for specific tone and depth of explanation..." className="w-full px-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl outline-none text-[12px] italic text-[var(--text-main)] focus:bg-[var(--bg-card)] transition-all"
                                                    value={q.instruction || ''} onChange={e => handleQuizChange(qIdx, 'instruction', e.target.value)} />
                                            </div>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        ))}
                    </div>

                    <div className="sticky bottom-0 bg-[var(--bg-card)] border-t border-[var(--border)] py-4 flex justify-end gap-3 -mx-2 px-2 z-10 shadow-[0_-10px_20px_-10px_rgba(0,0,0,0.05)]">
                        <button onClick={() => setShowQuizModal(false)} className="px-6 py-2 text-[13px] font-black text-[var(--text-muted)] hover:text-red-500 uppercase tracking-widest transition-all">Cancel</button>
                        <button onClick={handleSaveQuiz} className="px-12 py-2 bg-[var(--btn-primary)] text-white rounded-xl text-[13px] font-black shadow-lg shadow-indigo-500/30 hover:opacity-90 uppercase tracking-widest transition-all">Save Library</button>
                    </div>
                </div>
            </Modal>
        </div>
    );
};

export default SessionTemplateDetails;
