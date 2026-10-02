import React, { useEffect, useRef, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Mic, Square, Trash2 } from 'lucide-react';

const formatTime = (secs) => `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;

// Record -> Stop -> preview/Save flow. onSave receives a File (audio/webm) that the
// caller attaches the same way as any other file (see TaskFormModal's handleFileChosen /
// pendingFiles), so a voice note is just a file that happens to come from the mic.
const VoiceNoteModal = ({ isOpen, onClose, onSave }) => {
  const [status, setStatus] = useState('idle'); // idle | recording | recorded
  const [seconds, setSeconds] = useState(0);
  const [audioUrl, setAudioUrl] = useState(null);
  const [error, setError] = useState('');

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const blobRef = useRef(null);

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  };

  const reset = () => {
    clearInterval(timerRef.current);
    stopTracks();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    blobRef.current = null;
    chunksRef.current = [];
    setSeconds(0);
    setStatus('idle');
    setError('');
  };

  useEffect(() => {
    if (!isOpen) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => () => { clearInterval(timerRef.current); stopTracks(); }, []);

  if (!isOpen) return null;

  const handleRecord = async () => {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        blobRef.current = blob;
        setAudioUrl(URL.createObjectURL(blob));
        setStatus('recorded');
        stopTracks();
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setStatus('recording');
      setSeconds(0);
      timerRef.current = setInterval(() => setSeconds(s => s + 1), 1000);
    } catch {
      setError('Microphone access denied or unavailable');
    }
  };

  const handleStop = () => {
    clearInterval(timerRef.current);
    mediaRecorderRef.current?.stop();
  };

  const handleDiscard = () => reset();

  const handleSave = () => {
    if (!blobRef.current) return;
    const file = new File([blobRef.current], `Voice Note ${new Date().toISOString().replace(/[:.]/g, '-')}.webm`, { type: 'audio/webm' });
    onSave(file);
    reset();
    onClose();
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-xs bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">Voice Note</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="px-6 py-8 flex flex-col items-center gap-4">
            <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${status === 'recording' ? 'bg-[var(--accent-red-bg,#fee2e2)]' : 'bg-[var(--accent-indigo-bg)]'}`}>
              <Mic size={26} className={status === 'recording' ? 'text-red-500' : 'text-[var(--accent-indigo)]'} />
            </div>

            {status === 'idle' && (
              <p className="text-center text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider">
                Click record to start<br />recording a voice memo
              </p>
            )}
            {status === 'recording' && (
              <p className="text-center text-[13px] font-black text-red-500 tracking-wider">{formatTime(seconds)}</p>
            )}
            {status === 'recorded' && (
              <audio className="w-full" controls src={audioUrl} />
            )}
            {error && <p className="text-center text-[10px] font-bold text-[var(--accent-red)]">{error}</p>}

            {status === 'idle' && (
              <button type="button" onClick={handleRecord}
                className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-full text-[11px] font-black uppercase tracking-widest shadow-lg">
                <Mic size={14} /> Record
              </button>
            )}
            {status === 'recording' && (
              <button type="button" onClick={handleStop}
                className="flex items-center gap-2 px-6 py-2.5 bg-red-500 text-white rounded-full text-[11px] font-black uppercase tracking-widest shadow-lg">
                <Square size={14} /> Stop
              </button>
            )}
            {status === 'recorded' && (
              <div className="flex items-center gap-2">
                <button type="button" onClick={handleDiscard}
                  className="flex items-center gap-1.5 px-4 py-2 border border-[var(--border)] text-[var(--text-muted)] rounded-xl text-[10px] font-black uppercase tracking-widest">
                  <Trash2 size={13} /> Discard
                </button>
                <button type="button" onClick={handleSave}
                  className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
                  Save
                </button>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default VoiceNoteModal;
