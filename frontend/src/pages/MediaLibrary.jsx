import React, { useState, useEffect, useRef } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  UploadCloud, FileVideo, FileAudio, FileText, FileImage, File as FileIcon,
  Trash2, Download, Search, Loader2, X, Library, Folder, BarChart2,
  AlertTriangle, Copy, RefreshCw
} from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import { useUploadQueue } from '../context/UploadContext';
import MediaInsights from '../components/MediaInsights';
import UploadProgressDashboard from '../components/UploadProgressDashboard';

const MEDIA_TYPES = [
  { value: 'video', label: 'Video', icon: FileVideo },
  { value: 'audio', label: 'Audio', icon: FileAudio },
  { value: 'pdf', label: 'PDF', icon: FileText },
  { value: 'document', label: 'Document', icon: FileText },
  { value: 'image', label: 'Image', icon: FileImage },
  { value: 'other', label: 'Other', icon: FileIcon },
];

const UPLOAD_MEDIA_TYPES = MEDIA_TYPES.filter((t) =>
  ['video', 'audio', 'pdf', 'document', 'image', 'other'].includes(t.value)
);

const MEDIA_TYPE_FILE_RULES = {
  image: {
    extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp'],
    mimeTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
    mimePrefix: 'image/',
  },
  video: {
    extensions: ['mp4', 'mov', 'avi', 'mkv', 'webm'],
    mimeTypes: ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/avi', 'video/msvideo', 'video/x-matroska', 'application/x-matroska', 'video/webm'],
    mimePrefix: 'video/',
  },
  audio: {
    extensions: ['mp3', 'wav', 'aac', 'ogg', 'm4a', 'flac'],
    // .m4a is reported inconsistently by browsers (audio/x-m4a, audio/m4a,
    // audio/mp4 — or an empty type on Windows), hence the extra entries.
    mimeTypes: ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/aac', 'audio/aacp', 'audio/x-aac', 'audio/ogg', 'application/ogg', 'audio/x-m4a', 'audio/m4a', 'audio/mp4', 'audio/flac', 'audio/x-flac'],
    mimePrefix: 'audio/',
  },
  document: {
    extensions: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt'],
    mimeTypes: [
      'application/pdf',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.ms-powerpoint',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'text/plain',
    ],
  },
  pdf: {
    extensions: ['pdf'],
    mimeTypes: ['application/pdf'],
  },
};

const getFileExtension = (filename = '') =>
  filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';

const validateFileForMediaType = (file, mediaType) => {
  if (mediaType === 'other') return '';

  const rules = MEDIA_TYPE_FILE_RULES[mediaType];
  if (!rules) return `Please select Image, Video, Audio, or Document before uploading.`;

  const ext = getFileExtension(file.name);
  const mimeType = (file.type || '').toLowerCase();
  const validExtension = rules.extensions.includes(ext);
  // Extension is authoritative; the MIME type only blocks when the browser
  // sent a meaningful one that contradicts the category (it's often empty or
  // nonstandard, e.g. for .m4a on Windows).
  const validMime =
    !mimeType ||
    mimeType === 'application/octet-stream' ||
    rules.mimeTypes.includes(mimeType) ||
    (rules.mimePrefix && mimeType.startsWith(rules.mimePrefix));

  if (!validExtension || !validMime) {
    return `${file.name} is not a valid ${mediaType} file. Allowed extensions: ${rules.extensions.join(', ')}.`;
  }

  return '';
};

const typeMeta = (type) =>
  MEDIA_TYPES.find((t) => t.value === type) || MEDIA_TYPES[MEDIA_TYPES.length - 1];

const formatSize = (bytes) => {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
};

const MediaLibrary = () => {
  const { showSuccess, showError } = useNotification();
  const { enqueueFiles, queue } = useUploadQueue();
  const fileInputRef = useRef(null);
  const conflictResolverRef = useRef(null);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({ media_type: 'video', name: '', description: '' });
  const [file, setFile] = useState(null);
  const [selectedFileCount, setSelectedFileCount] = useState(0);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Active upload tracking
  const activeCount = queue.filter(q => q.status === 'uploading' || q.status === 'queued' || q.status === 'processing').length;
  const isUploadDisabled = isSubmitting || activeCount > 0 || (!file && (!fileInputRef.current || !fileInputRef.current._filesToProcess?.length));

  const totalBytes = queue.reduce((acc, q) => acc + (q.size || 0), 0);
  const uploadedBytes = queue.reduce((acc, q) => {
    if (q.status === 'completed') return acc + (q.size || 0);
    if (q.progress && q.size) return acc + (q.size * (q.progress / 100));
    return acc;
  }, 0);
  const overallProgress = totalBytes > 0 ? Math.round((uploadedBytes / totalBytes) * 100) : (queue.length > 0 && queue.every(q => q.status === 'completed') ? 100 : 0);

  // New folder, tag, and insights dashboard states
  const [currentFolder, setCurrentFolder] = useState('/');
  const [folders, setFolders] = useState([]);
  const [selectedTag, setSelectedTag] = useState('');
  const [activeTab, setActiveTab] = useState('library');
  const [conflictModal, setConflictModal] = useState(null);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/media');
      setItems(data);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load media library');
    } finally {
      setLoading(false);
    }
  };

  const fetchFolders = async () => {
    try {
      const { data } = await api.get('/media/ai/folders');
      setFolders(data);
    } catch (err) {
      console.warn("Failed to fetch folders:", err);
    }
  };

  useEffect(() => {
    fetchItems();
    fetchFolders();
  }, []);

  // The upload manager runs in a separate context, so completed uploads don't
  // land in this list on their own. Re-fetch whenever an upload finishes.
  const prevCompletedCount = useRef(0);
  useEffect(() => {
    const completedCount = queue.filter((u) => u.status === 'completed').length;
    if (completedCount > prevCompletedCount.current) {
      fetchItems();
      fetchFolders();
    }
    prevCompletedCount.current = completedCount;
  }, [queue]);

  const setSelectedFiles = (selectedFiles) => {
    // For high volume uploads, support multiple files
    if (!selectedFiles.length) return;

    const invalidFile = selectedFiles.find((selected) => validateFileForMediaType(selected, form.media_type));
    if (invalidFile) {
      showError(validateFileForMediaType(invalidFile, form.media_type));
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
        fileInputRef.current._filesToProcess = [];
      }
      setFile(null);
      setSelectedFileCount(0);
      return;
    }
    
    // Process the first file for form preview, others will be queued directly
    setFile(selectedFiles[0]);
    setSelectedFileCount(selectedFiles.length);

    // Store all files in a temp attribute if multiple selected
    if (selectedFiles.length > 1) {
       fileInputRef.current._filesToProcess = selectedFiles;
       showSuccess(`Selected ${selectedFiles.length} files for upload. Submit to start queue.`);
    } else {
       fileInputRef.current._filesToProcess = [selectedFiles[0]];
    }

    setForm((prev) => ({
      ...prev,
      name: prev.name || selectedFiles[0].name.replace(/\.[^/.]+$/, ''),
    }));
  };

  const handleFileChange = (e) => {
    setSelectedFiles(Array.from(e.target.files || []));
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDraggingFiles(false);
    setSelectedFiles(Array.from(e.dataTransfer.files || []));
  };

  const openConflictModal = (fileToProcess, existingFile) => {
    return new Promise((resolve) => {
      conflictResolverRef.current = resolve;
      setConflictModal({
        fileName: fileToProcess.name,
        size: fileToProcess.size,
        existing: existingFile,
      });
    });
  };

  const resolveConflictModal = (choice) => {
    if (conflictResolverRef.current) {
      conflictResolverRef.current(choice);
      conflictResolverRef.current = null;
    }
    setConflictModal(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isUploadDisabled) return;

    setIsSubmitting(true);
    try {
      const filesToUpload = fileInputRef.current?._filesToProcess || (file ? [file] : []);
      
      if (filesToUpload.length === 0) {
        showError('Please choose a file to upload');
        setIsSubmitting(false);
        return;
      }
      if (filesToUpload.length === 1 && !form.name.trim()) {
        showError('Please enter a name');
        setIsSubmitting(false);
        return;
      }

      const invalidFile = filesToUpload.find((selected) => validateFileForMediaType(selected, form.media_type));
      if (invalidFile) {
        showError(validateFileForMediaType(invalidFile, form.media_type));
        setIsSubmitting(false);
        return;
      }

      const uploadBatch = [];

      for (let i = 0; i < filesToUpload.length; i++) {
          let fileToProcess = filesToUpload[i];
          // Only use the form name for the first file if multiple selected
          const formToUpload = i === 0 ? { ...form } : { media_type: form.media_type, name: fileToProcess.name, description: '' };

          // Additive Duplicate Detection check before calling upload API
          try {
            const { data: dupCheck } = await api.get(`/media/ai/check-duplicate?filename=${encodeURIComponent(fileToProcess.name)}&size=${fileToProcess.size}`);
            if (dupCheck.duplicate) {
              const choice = await openConflictModal(fileToProcess, dupCheck.existing);
              if (!choice || choice === 'skip') {
                continue;
              }

              if (choice === 'replace') {
                await api.delete(`/media/${dupCheck.existing.id}`);
              } else {
                const nameParts = fileToProcess.name.split('.');
                const ext = nameParts.pop();
                const baseName = nameParts.join('.');
                const newFileName = `${baseName}_copy_${Date.now()}.${ext}`;
                fileToProcess = new File([fileToProcess], newFileName, { type: fileToProcess.type });
                formToUpload.name = `${formToUpload.name.trim()} (Copy)`;
              }
            }
          } catch (err) {
            console.warn("Duplicate check error:", err);
          }

          uploadBatch.push({ file: fileToProcess, form: formToUpload, currentFolder });
      }

      if (uploadBatch.length === 0) {
        showError('No files were added to the upload queue');
        setIsSubmitting(false);
        return;
      }

      // Add the whole batch at once so the upload manager can start files in parallel.
      try {
        await enqueueFiles(uploadBatch);
      } catch {
        setIsSubmitting(false);
        return;
      }
      
      showSuccess(`${uploadBatch.length} file(s) added to the background upload queue.`);

      // Clear form state immediately for the next upload
      setForm({ media_type: 'video', name: '', description: '' });
      setFile(null);
      setSelectedFileCount(0);
      if (fileInputRef.current) {
          fileInputRef.current.value = '';
          fileInputRef.current._filesToProcess = [];
      }
    } catch (err) {
      console.error(err);
      showError('Upload submission failed');
    } finally {
      setIsSubmitting(false);
    }
  };


  /* Delete is irreversible and the files are large re-uploads, so it asks first — but with
     the file NAMED, which a browser confirm() cannot do. `deleteError` is shown inside the
     dialog rather than as a toast: the toast would be hidden behind the overlay. */
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const askDelete = (item) => {
    setPendingDelete(item);
    setDeleteError('');
  };

  const closeDeleteModal = () => {
    if (deleting) return;          // never vanish mid-request
    setPendingDelete(null);
    setDeleteError('');
  };

  const handleDelete = async () => {
    const item = pendingDelete;
    if (!item) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api.delete(`/media/${item._id}`);
      setItems((prev) => prev.filter((i) => i._id !== item._id));
      showSuccess(`Deleted "${item.name || item.file_name || 'file'}"`);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err.response?.data?.detail || 'Delete failed. The file is still in your library.');
    } finally {
      setDeleting(false);
    }
  };

  useEffect(() => {
    if (!pendingDelete) return undefined;
    const onKey = (e) => { if (e.key === 'Escape' && !deleting) closeDeleteModal(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pendingDelete, deleting]);   // eslint-disable-line react-hooks/exhaustive-deps

  /* Searching looks through the WHOLE library, not just the folder you happen to be
     standing in. The folder filter used to be AND-ed with the search, so a video uploaded
     into a folder was invisible from Root — you had to already know which folder it was in
     to find it, which is the opposite of what a search bar is for. With a query typed the
     folder scope is lifted; clear the query and you are back in the folder you were browsing.

     Matching covers the data a video actually carries — name, description, file name, folder
     and tags — so a partial file name or a tag finds it too. */
  const q = search.trim().toLowerCase();
  const searching = q.length > 0;

  const filtered = items
    .filter((i) => {
      const matchesType = filter === 'all' || i.media_type === filter;
      const matchesSearch = !searching || [
        i.name, i.description, i.file_name, i.folder, ...(i.tags || []),
      ].some((v) => String(v || '').toLowerCase().includes(q));
      const matchesFolder = searching || (i.folder || '/') === currentFolder;
      const matchesTag = !selectedTag || (i.tags && i.tags.includes(selectedTag));
      return matchesType && matchesSearch && matchesFolder && matchesTag;
    })
    .sort((a, b) => new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0));

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]">
            <Library size={22} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">Media Library</h1>
            <p className="text-sm text-[var(--text-muted)]">
              Upload videos, audio, PDFs and any file type. Other modules reference these uploads.
            </p>
          </div>
        </div>

        {/* View/Insights Toggle */}
        <div className="flex bg-[var(--input-bg)] p-1 rounded-xl border border-[var(--border)] w-fit self-end sm:self-auto">
          <button
            onClick={() => setActiveTab('library')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'library'
                ? 'bg-[var(--bg-card)] text-[var(--text-main)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            Library
          </button>
          <button
            onClick={() => setActiveTab('insights')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
              activeTab === 'insights'
                ? 'bg-[var(--bg-card)] text-[var(--text-main)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            <BarChart2 size={13} />
            AI Insights
          </button>
        </div>
      </div>

      {activeTab === 'insights' ? (
        <MediaInsights />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Upload form column */}
          <div className="lg:col-span-1 space-y-4 sticky top-6">
            <motion.form
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              onSubmit={handleSubmit}
              className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-5 h-fit space-y-4"
            >
            <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-muted)]">
              Upload File
            </h2>

            <div>
              <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Type</label>
              <select
                value={form.media_type}
                onChange={(e) => setForm({ ...form, media_type: e.target.value })}
                className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
              >
                {UPLOAD_MEDIA_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Onboarding walkthrough"
                className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Description</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
                placeholder="Optional description"
                className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">File</label>
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setIsDraggingFiles(true);
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDraggingFiles(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setIsDraggingFiles(false);
                }}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-lg p-5 text-center cursor-pointer transition-colors ${
                  isDraggingFiles
                    ? 'border-[var(--sidebar-active-bg)] bg-[var(--sidebar-active-bg)]/10'
                    : 'border-[var(--border)] hover:border-[var(--sidebar-active-bg)]'
                }`}
              >
                <UploadCloud size={24} className="mx-auto text-[var(--text-muted)] mb-2" />
                {file ? (
                  <div className="flex items-center justify-center gap-2 text-sm text-[var(--text-main)]">
                    <span className="truncate max-w-[180px]">
                      {selectedFileCount > 1 ? `${selectedFileCount} files selected` : file.name}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setFile(null);
                        setSelectedFileCount(0);
                        if (fileInputRef.current) {
                          fileInputRef.current.value = '';
                          fileInputRef.current._filesToProcess = [];
                        }
                      }}
                      className="text-[var(--accent-red)]"
                    >
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm font-semibold text-[var(--text-main)]">Drop files here or click to choose</p>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">Any file type, any batch size</p>
                  </div>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={MEDIA_TYPE_FILE_RULES[form.media_type]?.extensions.map((ext) => `.${ext}`).join(',')}
                onChange={handleFileChange}
                className="hidden"
              />
            </div>

            {/* Batch Upload Progress Bar */}
            {queue.length > 0 && (
              <div className="p-3.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl space-y-2.5">
                <div className="flex items-center justify-between text-xs font-bold">
                  <span className="text-[var(--text-main)] flex items-center gap-1.5 truncate">
                    <UploadCloud size={14} className={activeCount > 0 ? "animate-bounce text-[var(--accent-indigo)]" : "text-emerald-500"} />
                    {activeCount > 0 ? `Uploading (${queue.length - activeCount}/${queue.length})` : 'Upload Batch Complete'}
                  </span>
                  <span className="text-[var(--accent-indigo)] font-black">{overallProgress}%</span>
                </div>

                <div className="w-full bg-[var(--border)] rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-[var(--accent-indigo)] h-full transition-all duration-300 ease-out"
                    style={{ width: `${overallProgress}%` }}
                  />
                </div>

                <div className="max-h-36 overflow-y-auto space-y-2 pt-1 scrollbar-thin pr-1">
                  {queue.map((item) => (
                    <div key={item.id} className="text-[11px] space-y-1">
                      <div className="flex items-center justify-between font-semibold text-[var(--text-muted)]">
                        <span className="truncate max-w-[170px]" title={item.name}>{item.name}</span>
                        <span className={`font-bold ${item.status === 'completed' ? 'text-emerald-500' : item.status === 'failed' ? 'text-red-500' : 'text-[var(--accent-indigo)]'}`}>
                          {item.status === 'completed' ? '✓ Done' : item.status === 'failed' ? 'Failed' : `${item.progress || 0}%`}
                        </span>
                      </div>
                      <div className="w-full bg-[var(--border)] rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full transition-all duration-200 ${item.status === 'completed' ? 'bg-emerald-500' : item.status === 'failed' ? 'bg-red-500' : 'bg-[var(--accent-indigo)]'}`}
                          style={{ width: `${item.status === 'completed' ? 100 : (item.progress || 0)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={isUploadDisabled}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-semibold text-sm disabled:opacity-50 hover:opacity-90 transition-all cursor-pointer disabled:cursor-not-allowed"
            >
              {isSubmitting || activeCount > 0 ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Uploading ({activeCount} remaining)...</span>
                </>
              ) : (
                <>
                  <UploadCloud size={16} />
                  <span>Upload</span>
                </>
              )}
            </button>
          </motion.form>
        </div>

        <div className="lg:col-span-2 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search all folders by name, tag or file"
                className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
              />
            </div>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none"
            >
              <option value="all">All types</option>
              {MEDIA_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Folder Navigation & Tag Breadcrumbs */}
          <div className="flex items-center justify-between flex-wrap gap-2 py-1.5 px-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-xs font-semibold text-[var(--text-muted)]">
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                onClick={() => {
                  setCurrentFolder('/');
                  setSelectedTag('');
                }}
                className={`hover:text-[var(--text-main)] ${currentFolder === '/' ? 'text-[var(--text-main)] font-bold' : ''}`}
              >
                Root
              </button>
              {currentFolder !== '/' && (
                <>
                  <span>/</span>
                  <span className="text-[var(--text-main)] font-bold">{currentFolder.replace(/^\//, '')}</span>
                </>
              )}
              {selectedTag && (
                <div className="flex items-center gap-1 bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] px-2 py-0.5 rounded-full text-[10px]">
                  <span>Tag: {selectedTag}</span>
                  <button onClick={() => setSelectedTag('')} className="hover:opacity-80">
                    <X size={10} />
                  </button>
                </div>
              )}
            </div>

            {searching ? (
              <span className="text-[10px] text-[var(--sidebar-active-bg)] uppercase tracking-wider font-bold">
                Searching all folders · {filtered.length} result{filtered.length === 1 ? '' : 's'}
              </span>
            ) : currentFolder === '/' && folders.length > 0 && (
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{folders.length} Folder(s) available</span>
            )}
          </div>

          {/* Virtual Folders Grid — hidden while searching, when the hits below span folders. */}
          {!searching && currentFolder === '/' && folders.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {folders.map((f) => (
                <div
                  key={f.id}
                  onClick={() => setCurrentFolder(f.name)}
                  className="flex items-center gap-3 p-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl cursor-pointer hover:border-[var(--sidebar-active-bg)] transition-colors group"
                >
                  <div className="p-2.5 rounded-lg bg-[var(--input-bg)] text-amber-500 group-hover:bg-amber-500/10 transition-colors">
                    <Folder size={18} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-bold text-[var(--text-main)] truncate">{f.name.replace(/^\//, '')}</p>
                    <p className="text-[9px] text-[var(--text-muted)] mt-0.5">Click to view</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-20 text-[var(--text-muted)]">
              <Loader2 size={22} className="animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded-2xl">
              <Library size={32} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">
                {searching
                  ? `No media matches “${search.trim()}” anywhere in the library.`
                  : 'No files yet in this view.'}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <AnimatePresence>
                {filtered.map((item) => {
                  const meta = typeMeta(item.media_type);
                  const Icon = meta.icon;
                  return (
                    <motion.div
                      key={item._id}
                      layout
                      initial={{ opacity: 0, scale: 0.97 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.97 }}
                      className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex gap-3"
                    >
                      <div className="p-2.5 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] h-fit">
                        <Icon size={20} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-sm font-semibold text-[var(--text-main)] truncate">{item.name}</h3>
                          <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] bg-[var(--input-bg)] px-2 py-0.5 rounded-full whitespace-nowrap">
                            {meta.label}
                          </span>
                        </div>
                        {item.description && (
                          <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">{item.description}</p>
                        )}
                        <p className="text-[11px] text-[var(--text-muted)] mt-1 truncate">
                          {item.file_name}{item.size ? ` · ${formatSize(item.size)}` : ''}
                        </p>
                        {/* Where the hit lives — only worth showing when the results are not
                            all from the folder already named in the breadcrumb. */}
                        {searching && (item.folder || '/') !== '/' && (
                          <button
                            type="button"
                            onClick={() => { setSearch(''); setCurrentFolder(item.folder); }}
                            title="Open this folder"
                            className="inline-flex items-center gap-1 mt-1.5 text-[9px] font-bold uppercase tracking-wider text-[var(--text-muted)] bg-[var(--input-bg)] border border-[var(--border)] px-1.5 py-0.5 rounded-full hover:text-[var(--text-main)] transition-colors"
                          >
                            <Folder size={9} /> {String(item.folder).replace(/^\//, '')}
                          </button>
                        )}

                        {/* Display custom tags */}
                        {item.tags && item.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {item.tags.map((t) => (
                              <span
                                key={t}
                                onClick={() => setSelectedTag(t)}
                                className="cursor-pointer hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-active-text)] text-[9px] bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] px-1.5 py-0.5 rounded-full transition-colors"
                              >
                                #{t}
                              </span>
                            ))}
                          </div>
                        )}

                        <div className="flex items-center gap-3 mt-2.5">
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--sidebar-active-text)]"
                          >
                            <Download size={13} /> Open
                          </a>
                          <button
                            onClick={() => askDelete(item)}
                            className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--accent-red)]"
                          >
                            <Trash2 size={13} /> Delete
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
      )}

      <AnimatePresence>
        {conflictModal && (
          <motion.div
            className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 px-4 py-6 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-labelledby="file-conflict-title"
              initial={{ opacity: 0, y: 18, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98 }}
              transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              className="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-2xl"
            >
              <div className="flex items-start gap-4 border-b border-[var(--border)] px-6 py-5">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-600">
                  <AlertTriangle size={24} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 id="file-conflict-title" className="text-lg font-bold text-[var(--text-main)]">
                    File Already Exists
                  </h2>
                  <p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">
                    A file with this name is already available in your media library.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => resolveConflictModal('skip')}
                  className="rounded-lg p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]"
                  aria-label="Close conflict dialog"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="space-y-4 px-6 py-5">
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-xs font-bold uppercase text-amber-700">Conflicting file</p>
                  <p className="mt-1 truncate text-sm font-semibold text-slate-900" title={conflictModal.fileName}>
                    {conflictModal.fileName}
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-3">
                    <p className="text-[10px] font-bold uppercase text-[var(--text-muted)]">New upload</p>
                    <p className="mt-1 text-sm font-semibold text-[var(--text-main)]">{formatSize(conflictModal.size)}</p>
                  </div>
                  <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-3">
                    <p className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Existing file</p>
                    <p className="mt-1 truncate text-sm font-semibold text-[var(--text-main)]" title={conflictModal.existing?.name || conflictModal.existing?.file_name}>
                      {conflictModal.existing?.name || conflictModal.existing?.file_name || 'Media library file'}
                    </p>
                  </div>
                </div>

                <p className="text-sm leading-6 text-[var(--text-muted)]">
                  Choose how you want to handle this upload.
                </p>
              </div>

              <div className="flex flex-col-reverse gap-2 border-t border-[var(--border)] bg-[var(--input-bg)] px-6 py-4 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => resolveConflictModal('skip')}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-2.5 text-sm font-semibold text-[var(--text-main)] transition-colors hover:bg-[var(--border)]"
                >
                  Skip
                </button>
                <button
                  type="button"
                  onClick={() => resolveConflictModal('replace')}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100"
                >
                  <RefreshCw size={16} />
                  Replace
                </button>
                <button
                  type="button"
                  onClick={() => resolveConflictModal('both')}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--sidebar-active-bg)] px-4 py-2.5 text-sm font-semibold text-[var(--sidebar-active-text)] shadow-sm transition-opacity hover:opacity-90"
                >
                  <Copy size={16} />
                  Keep Both
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pendingDelete && (
          <motion.div
            className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 px-4 py-6 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={closeDeleteModal}
          >
            <motion.div
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="delete-media-title"
              initial={{ opacity: 0, y: 18, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98 }}
              transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-md overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-2xl"
            >
              <div className="flex items-start gap-4 border-b border-[var(--border)] px-6 py-5">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-red-100 text-[var(--accent-red)]">
                  <Trash2 size={22} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 id="delete-media-title" className="text-lg font-bold text-[var(--text-main)]">
                    Delete this file?
                  </h2>
                  <p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">
                    It is removed from the library for everyone. This cannot be undone.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={closeDeleteModal}
                  disabled={deleting}
                  className="rounded-lg p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] disabled:opacity-40"
                  aria-label="Close delete dialog"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="px-6 py-5 space-y-3">
                <div className="flex items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3">
                  <FileIcon size={16} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-[var(--text-main)] break-words">
                      {pendingDelete.name || pendingDelete.file_name}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--text-muted)] truncate">
                      {pendingDelete.file_name}
                      {pendingDelete.size ? ` · ${formatSize(pendingDelete.size)}` : ''}
                    </p>
                  </div>
                </div>

                {deleteError && (
                  <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-[var(--accent-red)]">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <span>{deleteError}</span>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-6 py-4">
                <button
                  type="button"
                  onClick={closeDeleteModal}
                  disabled={deleting}
                  className="inline-flex items-center justify-center rounded-lg border border-[var(--border)] px-4 py-2.5 text-sm font-semibold text-[var(--text-muted)] transition-colors hover:bg-[var(--input-bg)] disabled:opacity-40"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--accent-red)] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {deleting ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                  {deleting ? 'Deleting…' : 'Delete File'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <UploadProgressDashboard />
    </div>
  );
};

export default MediaLibrary;
