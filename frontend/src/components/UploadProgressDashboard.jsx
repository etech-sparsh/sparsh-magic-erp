import React, { useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
  UploadCloud, CheckCircle2, AlertCircle, XCircle, Play, Pause, 
  Trash2, X, ChevronUp, ChevronDown 
} from 'lucide-react';
import { useUploadQueue } from '../context/UploadContext';

const UploadProgressDashboard = () => {
  const { queue, cancelUpload, resumeUpload, clearCompleted } = useUploadQueue();
  const [isMinimized, setIsMinimized] = useState(false);

  if (queue.length === 0) return null;

  const totalFiles = queue.length;
  const completed = queue.filter(q => q.status === 'completed').length;
  const failed = queue.filter(q => q.status === 'failed').length;
  const uploading = queue.filter(q => q.status === 'uploading').length;
  const queued = queue.filter(q => q.status === 'queued').length;
  const processing = queue.filter(q => q.status === 'processing').length;
  const cancelled = queue.filter(q => q.status === 'cancelled').length;
  
  const activeCount = uploading + processing + queued;
  const doneCount = completed + failed + cancelled;

  // Calculate overall progress across all files based on file sizes
  const totalBytes = queue.reduce((acc, q) => acc + (q.size || 0), 0);
  const uploadedBytes = queue.reduce((acc, q) => {
    if (q.status === 'completed') return acc + (q.size || 0);
    if (q.progress && q.size) return acc + (q.size * (q.progress / 100));
    return acc;
  }, 0);
  const overallProgress = totalBytes > 0 ? Math.round((uploadedBytes / totalBytes) * 100) : 0;

  return (
    <div className={`fixed bottom-24 right-6 z-[60] flex flex-col items-end transition-all duration-300 ${isMinimized ? 'translate-y-4' : ''}`}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-[380px] bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[600px]"
      >
        {/* Header */}
        <div 
          onClick={() => setIsMinimized(!isMinimized)}
          className="p-4 bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-3">
            {activeCount > 0 ? (
              <UploadCloud size={20} className="animate-bounce" />
            ) : (
              <CheckCircle2 size={20} />
            )}
            <div>
              <h3 className="font-bold text-sm">
                {activeCount > 0 ? `Uploading ${completed}/${totalFiles}` : 'Uploads Complete'}
              </h3>
              <p className="text-[10px] opacity-80">
                {overallProgress}% Overall Progress
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="p-1 rounded-lg hover:bg-black/10 transition-colors">
              {isMinimized ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          </div>
        </div>

        {/* Overall Progress Bar */}
        <div className="h-1.5 w-full bg-black/20">
          <div 
            className="h-full bg-emerald-400 transition-all duration-500"
            style={{ width: `${overallProgress}%` }}
          />
        </div>

        {/* Content */}
        <AnimatePresence>
          {!isMinimized && (
            <motion.div 
              initial={{ height: 0 }}
              animate={{ height: 'auto' }}
              exit={{ height: 0 }}
              className="flex-1 overflow-y-auto"
            >
              <div className="p-4 space-y-3">
                {doneCount > 0 && activeCount === 0 && (
                  <button 
                    onClick={clearCompleted}
                    className="w-full py-2 mb-2 text-xs font-semibold rounded-xl bg-[var(--input-bg)] border border-[var(--border)] hover:bg-[var(--border)] transition-colors"
                  >
                    Clear Completed
                  </button>
                )}

                {queue.map(upload => (
                  <div key={upload.id} className="bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-3 flex flex-col gap-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-[var(--text-main)] truncate" title={upload.name}>
                          {upload.name}
                        </p>
                        <p className="text-[10px] text-[var(--text-muted)] truncate">
                          {upload.fileName}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {upload.status === 'uploading' && (
                          <button onClick={() => cancelUpload(upload.id)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]">
                            <Pause size={14} />
                          </button>
                        )}
                        {(upload.status === 'failed' || upload.status === 'cancelled') && (
                          <button onClick={() => resumeUpload(upload.id)} className="text-[var(--text-muted)] hover:text-emerald-500">
                            <Play size={14} />
                          </button>
                        )}
                        {(upload.status === 'queued' || upload.status === 'uploading' || upload.status === 'failed' || upload.status === 'cancelled') && (
                          <button onClick={() => cancelUpload(upload.id)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]">
                            <X size={14} />
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-[var(--border)] h-1.5 rounded-full overflow-hidden">
                        <div 
                          className={`h-full transition-all duration-300 ${
                            upload.status === 'failed' ? 'bg-red-500' :
                            upload.status === 'completed' ? 'bg-emerald-500' :
                            'bg-[var(--sidebar-active-bg)]'
                          }`}
                          style={{ width: `${upload.progress || 0}%` }}
                        />
                      </div>
                      <span className="text-[10px] font-bold w-8 text-right text-[var(--text-main)]">
                        {upload.progress || 0}%
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px]">
                      <span className={`font-semibold uppercase tracking-wider ${
                        upload.status === 'failed' ? 'text-red-500' :
                        upload.status === 'completed' ? 'text-emerald-500' :
                        upload.status === 'cancelled' ? 'text-orange-500' :
                        'text-[var(--text-muted)]'
                      }`}>
                        {upload.status} {upload.retries > 0 ? `(Retry ${upload.retries})` : ''}
                      </span>
                      {upload.error && <span className="text-red-500 truncate max-w-[150px]" title={upload.error}>{upload.error}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
};

export default UploadProgressDashboard;
