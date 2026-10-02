import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
    CheckCircle2, AlertCircle, ArrowRight, ArrowLeft, 
    Zap, Brain, Clock, ChevronRight, X, Layout, BookOpen, Send
} from 'lucide-react';

const AssessmentPlayer = () => {
    const { sessionId, quizIndex } = useParams();
    const navigate = useNavigate();
    useAuth();
    const { showSuccess, showError } = useNotification();

    const [quiz, setQuiz] = useState(null);
    const [loading, setLoading] = useState(true);
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [answers, setAnswers] = useState({}); // { questionIndex: answer }
    const [completed, setCompleted] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [result, setResult] = useState(null);

    // Prevent navigation away
    useEffect(() => {
        const handleBeforeUnload = (e) => {
            if (!completed) {
                e.preventDefault();
                e.returnValue = '';
            }
        };
        window.addEventListener('beforeunload', handleBeforeUnload);
        return () => window.removeEventListener('beforeunload', handleBeforeUnload);
    }, [completed]);

    useEffect(() => {
        fetchQuiz();
    }, [sessionId, quizIndex]); // eslint-disable-line react-hooks/exhaustive-deps

    const fetchQuiz = async () => {
        try {
            const res = await api.get(`/calendar/events/${sessionId}`);
            const session = res.data;
            
            // Get assessments from either session or its template
            let assessments = session.assessments || [];
            if (session.session_template_id && assessments.length === 0) {
                const tempRes = await api.get(`/session-templates/${session.session_template_id}`);
                assessments = tempRes.data.assessments || [];
            }

            const activeQuiz = assessments[quizIndex];
            if (!activeQuiz) {
                showError("Assessment not found");
                navigate(-1);
                return;
            }

            // Shuffle if enabled
            let questions = activeQuiz.questions.map((q, idx) => ({ ...q, originalIndex: idx }));
            if (activeQuiz.shuffle_questions) {
                questions = questions.sort(() => Math.random() - 0.5);
                if (activeQuiz.questions_to_show) {
                    questions = questions.slice(0, activeQuiz.questions_to_show);
                }
            }

            setQuiz({ ...activeQuiz, questions });
        } catch (err) {
            showError("Failed to synchronize assessment data");
            navigate(-1);
        } finally {
            setLoading(false);
        }
    };

    const handleAnswer = (qIdx, answer) => {
        setAnswers(prev => ({ ...prev, [qIdx]: answer }));
    };

    const _canSubmit = quiz?.questions?.every((_, idx) => answers[idx] !== undefined) || true;

    const handleSubmit = async () => {
        setSubmitting(true);
        try {
            const payload = {
                answers, // Send raw answers for server-side AI grading
                question_indices: quiz.questions.map(q => q.originalIndex),
                completed_at: new Date().toISOString()
            };

            const res = await api.post(`/calendar/events/${sessionId}/assessments/${quizIndex}/submit`, payload);
            
            setResult(res.data.result);
            setCompleted(true);
            showSuccess("Assessment synchronized successfully");
        } catch (err) {
            showError("Cloud synchronization failed");
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) return (
        <div className="fixed inset-0 bg-[var(--bg-main)] flex flex-col items-center justify-center gap-4 z-[9999]">
            <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
            <p className="text-[12px] font-black text-[var(--accent-indigo)] uppercase tracking-widest animate-pulse">Syncing Assessment Module...</p>
        </div>
    );

    if (completed && result) {
        return (
            <div className="min-h-screen bg-[var(--bg-main)] flex items-center justify-center p-6">
                <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="max-w-2xl w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-10 text-center shadow-2xl relative overflow-hidden">
                    <div className={`absolute top-0 left-0 w-full h-2 ${result.passed ? 'bg-emerald-500' : 'bg-orange-500'}`} />
                    
                    <div className={`w-24 h-24 rounded-full mx-auto mb-8 flex items-center justify-center ${result.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-orange-50 text-orange-600'}`}>
                        {result.passed ? <CheckCircle2 size={48} /> : <AlertCircle size={48} />}
                    </div>

                    <h2 className="text-3xl font-black text-[var(--text-main)] italic uppercase tracking-tighter mb-2">Assessment Concluded</h2>
                    <p className="text-[12px] font-bold text-[var(--text-muted)] uppercase tracking-[0.2em] mb-10">{quiz.title}</p>

                    <div className="grid grid-cols-2 gap-4 mb-10">
                        <div className="bg-[var(--input-bg)] p-6 rounded-3xl border border-[var(--border)]">
                            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest block mb-1">Final Score</span>
                            <p className={`text-2xl font-black ${result.passed ? 'text-emerald-600' : 'text-orange-600'}`}>{result.score}/{result.total_marks}</p>
                        </div>
                        <div className="bg-[var(--input-bg)] p-6 rounded-3xl border border-[var(--border)]">
                            <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest block mb-1">Status</span>
                            <p className={`text-2xl font-black italic uppercase ${result.passed ? 'text-emerald-600' : 'text-orange-600'}`}>
                                {result.passed ? 'Qualified' : 'Re-Attempt Required'}
                            </p>
                        </div>
                    </div>

                    <button onClick={() => navigate('/company-portal')} className="w-full h-14 bg-black text-white rounded-[24px] font-black uppercase tracking-widest hover:scale-105 active:scale-95 transition-all shadow-xl">
                        "End Quiz"/Sumbit
                    </button>
                </motion.div>
            </div>
        );
    }

    const currentQuestion = quiz.questions[currentQuestionIndex];

    return (
        <div className="fixed inset-0 bg-[var(--bg-main)] z-[9999] overflow-y-auto no-scrollbar">
            {/* Header / Distraction Free Top Bar */}
            <div className="h-20 border-b border-[var(--border)] bg-black/5 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-50">
                <div className="flex items-center gap-6">
                    <div className="px-3 py-1 bg-black text-white rounded-lg text-[10px] font-black uppercase tracking-widest border border-white/20">Assessment Node</div>
                    <h3 className="text-[14px] font-black text-[var(--text-main)] uppercase tracking-tight truncate max-w-sm">{quiz.title}</h3>
                </div>
                
                <div className="flex items-center gap-8">
                    <div className="flex flex-col items-end">
                        <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Global Progress</span>
                        <div className="w-48 h-1.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-full mt-1.5 overflow-hidden">
                            <motion.div 
                                initial={{ width: 0 }} 
                                animate={{ width: `${((currentQuestionIndex + 1) / quiz.questions.length) * 100}%` }} 
                                className="h-full bg-[var(--accent-indigo)]" 
                            />
                        </div>
                    </div>
                </div>
            </div>

            <div className="max-w-3xl mx-auto py-12 px-6">
                <AnimatePresence mode="wait">
                    <motion.div 
                        key={currentQuestionIndex}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        transition={{ duration: 0.2 }}
                        className="space-y-8"
                    >
                        {/* Question Label */}
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-black text-white flex items-center justify-center font-black text-sm">
                                {currentQuestionIndex + 1}
                            </div>
                            <div className="h-px flex-1 bg-[var(--border)] opacity-20" />
                            <div className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-3 py-1 bg-[var(--input-bg)] rounded-lg">
                                {currentQuestion?.marks || 1} Points
                            </div>
                        </div>

                        {/* Question Text */}
                        <div className="space-y-2">
                             <span className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">Question Segment</span>
                             <h1 className="text-xl md:text-2xl font-black text-[var(--text-main)] uppercase tracking-tight leading-snug">
                                {currentQuestion.question_text}
                             </h1>
                        </div>

                        {/* Interaction Area */}
                        <div className="space-y-4">
                            {currentQuestion.type === 'MCQ' ? (
                                <div className="grid grid-cols-1 gap-3">
                                    {(currentQuestion.options || []).map((opt, oIdx) => (
                                        <button
                                            key={oIdx}
                                            onClick={() => handleAnswer(currentQuestionIndex, oIdx)}
                                            className={`group relative p-5 rounded-2xl text-left border-2 transition-all flex items-center gap-4 ${answers[currentQuestionIndex] === oIdx 
                                                ? 'bg-black text-white border-black shadow-lg translate-x-1' 
                                                : 'bg-[var(--bg-card)] border-[var(--border)] text-[var(--text-main)] hover:border-[var(--accent-indigo)]'}`}
                                        >
                                            <div className={`shrink-0 w-7 h-7 rounded-lg flex items-center justify-center font-black text-[11px] transition-all ${answers[currentQuestionIndex] === oIdx ? 'bg-white text-black' : 'bg-[var(--input-bg)]'}`}>
                                                {String.fromCharCode(65 + oIdx)}
                                            </div>
                                            <span className="text-[13px] font-bold uppercase tracking-tight">{opt}</span>
                                            {answers[currentQuestionIndex] === oIdx && (
                                                <div className="absolute right-5">
                                                    <CheckCircle2 size={18} />
                                                </div>
                                            )}
                                        </button>
                                    ))}
                                </div>
                            ) : (
                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 shadow-sm">
                                    <textarea 
                                        rows={6}
                                        placeholder="Formulate your detailed response here..."
                                        className="w-full bg-transparent border-none outline-none text-[15px] font-medium text-[var(--text-main)] resize-none no-scrollbar placeholder:opacity-20"
                                        value={answers[currentQuestionIndex] || ''}
                                        onChange={(e) => handleAnswer(currentQuestionIndex, e.target.value)}
                                    />
                                    <div className="flex items-center gap-2 mt-4 pt-4 border-t border-[var(--border)] text-[9px] font-black text-orange-500 uppercase tracking-widest">
                                        <Brain size={12} /> AI Assisted Keyword Validation Active
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Navigation Footer */}
                        <div className="pt-8 border-t border-[var(--border)] flex items-center justify-between gap-4">
                            <button 
                                onClick={() => setCurrentQuestionIndex(prev => Math.max(0, prev - 1))}
                                disabled={currentQuestionIndex === 0}
                                className="flex-1 h-12 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] rounded-xl flex items-center justify-center gap-2 text-[11px] font-black uppercase tracking-widest hover:bg-[var(--input-bg)] disabled:opacity-0 transition-all"
                            >
                                <ArrowLeft size={14} /> Previous
                            </button>

                            {currentQuestionIndex === quiz.questions.length - 1 ? (
                                <button 
                                    onClick={handleSubmit}
                                    disabled={submitting}
                                    className="flex-[1.5] h-12 bg-[var(--accent-green)] text-white rounded-xl flex items-center justify-center gap-2 text-[11px] font-black uppercase tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg disabled:opacity-50"
                                >
                                    {submitting ? 'Syncing...' : <><Send size={15} /> Finish & Submit</>}
                                </button>
                            ) : (
                                <button 
                                    onClick={() => setCurrentQuestionIndex(prev => prev + 1)}
                                    className="flex-1 h-12 bg-black text-white rounded-xl flex items-center justify-center gap-2 text-[11px] font-black uppercase tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg"
                                >
                                    Next <ArrowRight size={14} />
                                </button>
                            )}
                        </div>
                    </motion.div>
                </AnimatePresence>
            </div>
        </div>
    );
};

export default AssessmentPlayer;
