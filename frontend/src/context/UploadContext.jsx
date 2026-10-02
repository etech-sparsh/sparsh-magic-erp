import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import api from '../services/api';
import { useNotification } from './NotificationContext';

const UploadContext = createContext(null);

const MAX_CONCURRENT = 5;
const MAX_PARALLEL_CHUNKS = 3;
const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB
const MAX_RETRIES = 3;

const MEDIA_TYPE_FILE_RULES = {
  image: {
    extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp'],
    mimeTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
  },
  video: {
    extensions: ['mp4', 'mov', 'avi', 'mkv', 'webm'],
    mimeTypes: ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/avi', 'video/msvideo', 'video/x-matroska', 'application/x-matroska', 'video/webm'],
  },
  audio: {
    extensions: ['mp3', 'wav', 'aac', 'ogg', 'm4a', 'flac'],
    // .m4a is reported inconsistently by browsers (audio/x-m4a, audio/m4a, audio/mp4).
    mimeTypes: ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/aac', 'audio/aacp', 'audio/x-aac', 'audio/ogg', 'application/ogg', 'audio/x-m4a', 'audio/m4a', 'audio/mp4', 'audio/flac', 'audio/x-flac'],
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
};

const getFileExtension = (filename = '') =>
  filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';

const validateFileForMediaType = (file, mediaType) => {
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
    rules.mimeTypes.includes(mimeType);

  if (!validExtension || !validMime) {
    return `${file.name} is not a valid ${mediaType} file. Allowed extensions: ${rules.extensions.join(', ')}.`;
  }

  return '';
};

// IndexedDB Helper
const DB_NAME = 'MediaUploadQueueDB';
const STORE_NAME = 'UploadQueue';

const openDB = () => {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
};

const saveToDB = async (upload) => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(upload);
    return new Promise((resolve) => {
      tx.oncomplete = resolve;
    });
  } catch (err) {
    console.warn('IDB Save Error:', err);
  }
};

const saveManyToDB = async (uploads) => {
  if (!uploads.length) return;

  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);

    uploads.forEach(upload => {
      store.put(upload);
    });

    return new Promise((resolve) => {
      tx.oncomplete = resolve;
    });
  } catch (err) {
    console.warn('IDB Batch Save Error:', err);
  }
};

const loadFromDB = async () => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const request = store.getAll();
    return new Promise((resolve) => {
      request.onsuccess = () => resolve(request.result || []);
    });
  } catch (err) {
    console.warn('IDB Load Error:', err);
    return [];
  }
};

const removeFromDB = async (id) => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    return new Promise((resolve) => {
      tx.oncomplete = resolve;
    });
  } catch (err) {
    console.warn('IDB Delete Error:', err);
  }
};

export const UploadProvider = ({ children }) => {
  const [queue, setQueue] = useState([]);
  const { showError } = useNotification();
  const activeProcessing = useRef(new Set());
  const abortControllers = useRef(new Map());

  // Load from DB on mount
  useEffect(() => {
    const init = async () => {
      const stored = await loadFromDB();
      if (stored && stored.length > 0) {
        // Any interrupted uploads mark as 'queued' so they resume
        const resumed = stored.map(u => ({
          ...u,
          status: (u.status === 'uploading' || u.status === 'processing') ? 'queued' : u.status
        }));
        setQueue(resumed);
      }
    };
    init();
  }, []);

  // Effect to process queue automatically
  useEffect(() => {
    processQueue();
  }, [queue]); // eslint-disable-line react-hooks/exhaustive-deps

  const processQueue = () => {
    const uploadingCount = activeProcessing.current.size;
    if (uploadingCount >= MAX_CONCURRENT) return;

    // Find next pending items
    const pending = queue.filter(u => u.status === 'queued' && !activeProcessing.current.has(u.id));
    
    // Start up to the max concurrent limit
    const toStart = pending.slice(0, MAX_CONCURRENT - uploadingCount);
    toStart.forEach(u => {
      startUpload(u.id);
    });
  };

  const updateUploadState = (id, updates, { persist = true } = {}) => {
    setQueue(prev => {
      const updated = prev.map(u => {
        if (u.id === id) {
          const newU = { ...u, ...updates };
          if (persist) saveToDB(newU);
          return newU;
        }
        return u;
      });
      return updated;
    });
  };

  const createUploadItem = (file, form, currentFolder) => {
    const id = `${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    return {
      id,
      file, // Native File object stores perfectly in IndexedDB
      fileName: file.name,
      size: file.size,
      media_type: form.media_type,
      name: form.name.trim() || file.name,
      description: form.description || '',
      folder: currentFolder,
      progress: 0,
      status: 'queued',
      uploadedChunks: [],
      s3UploadId: null,
      s3Key: null,
      retries: 0
    };
  };

  const enqueueFiles = async (uploads) => {
    const invalidUpload = uploads.find(({ file, form }) =>
      validateFileForMediaType(file, form.media_type)
    );

    if (invalidUpload) {
      const message = validateFileForMediaType(invalidUpload.file, invalidUpload.form.media_type);
      showError(message);
      throw new Error(message);
    }

    const newUploads = uploads.map(({ file, form, currentFolder }) =>
      createUploadItem(file, form, currentFolder)
    );

    await saveManyToDB(newUploads);
    setQueue(prev => [...prev, ...newUploads]);
    return newUploads.map(upload => upload.id);
  };

  const enqueueFile = async (file, form, currentFolder) => {
    const [id] = await enqueueFiles([{ file, form, currentFolder }]);
    return id;
  };

  const startUpload = async (id) => {
    activeProcessing.current.add(id);
    updateUploadState(id, { status: 'uploading' });

    // Retrieve full item
    const uploadItem = await loadFromDB().then(db => db.find(u => u.id === id));
    if (!uploadItem || !uploadItem.file) {
      activeProcessing.current.delete(id);
      updateUploadState(id, { status: 'failed', error: 'File data lost from local cache' });
      return;
    }

    const { file, s3UploadId, s3Key, uploadedChunks } = uploadItem;
    let currentUploadId = s3UploadId;
    let currentKey = s3Key;
    const completedParts = [...(uploadedChunks || [])];
    
    const abortController = new AbortController();
    abortControllers.current.set(id, abortController);

    try {
      // 1. Initialize Multipart Upload if not already done
      if (!currentUploadId || !currentKey) {
        const startFd = new FormData();
        startFd.append('filename', file.name);
        startFd.append('content_type', file.type || 'application/octet-stream');
        startFd.append('media_type', uploadItem.media_type);
        
        const { data: startData } = await api.post('/media/chunk/start', startFd);
        currentUploadId = startData.upload_id;
        currentKey = startData.key;
        updateUploadState(id, { s3UploadId: currentUploadId, s3Key: currentKey });
      }

      // 2. Upload Chunks
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
      if (totalChunks === 0) throw new Error("Empty file");

      const uploadPart = async (chunkIndex) => {
        if (abortController.signal.aborted) throw new Error("Cancelled");
        
        const partNumber = chunkIndex + 1;
        // Skip already uploaded parts
        if (completedParts.some(p => p.PartNumber === partNumber)) return;

        const start = chunkIndex * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);

        let chunkRetries = 0;
        let chunkUploaded = false;

        while (!chunkUploaded && chunkRetries < MAX_RETRIES) {
          if (abortController.signal.aborted) throw new Error("Cancelled");
          try {
            const chunkFd = new FormData();
            chunkFd.append('upload_id', currentUploadId);
            chunkFd.append('key', currentKey);
            chunkFd.append('part_number', partNumber);
            chunkFd.append('file', new File([chunk], file.name, { type: file.type || 'application/octet-stream' }));

            const { data: partData } = await api.post('/media/chunk/upload', chunkFd, {
              signal: abortController.signal
            });

            if (!completedParts.some(p => p.PartNumber === partData.PartNumber)) {
              completedParts.push({ ETag: partData.ETag, PartNumber: partData.PartNumber });
            }
            chunkUploaded = true;
            
            // Update progress
            const progress = Math.round((completedParts.length / totalChunks) * 100);
            updateUploadState(id, { progress, uploadedChunks: completedParts });
            
          } catch (chunkErr) {
            if (abortController.signal.aborted) throw new Error("Cancelled");
            chunkRetries++;
            if (chunkRetries >= MAX_RETRIES) throw new Error(`Failed to upload chunk ${partNumber}`);
            await new Promise(r => setTimeout(r, 1000 * chunkRetries)); // exponential backoff
          }
        }
      };

      const chunkIndexes = Array.from({ length: totalChunks }, (_, i) => i)
        .filter(i => !completedParts.some(p => p.PartNumber === i + 1));
      let nextChunkIndex = 0;

      const workers = Array.from(
        { length: Math.min(MAX_PARALLEL_CHUNKS, chunkIndexes.length) },
        async () => {
          while (nextChunkIndex < chunkIndexes.length) {
            const chunkIndex = chunkIndexes[nextChunkIndex];
            nextChunkIndex += 1;
            await uploadPart(chunkIndex);
          }
        }
      );

      await Promise.all(workers);

      // 3. Complete Upload
      if (abortController.signal.aborted) throw new Error("Cancelled");
      updateUploadState(id, { status: 'processing', progress: 100 });
      
      const completeFd = new FormData();
      completeFd.append('upload_id', currentUploadId);
      completeFd.append('key', currentKey);
      completeFd.append('parts', JSON.stringify(completedParts));
      completeFd.append('media_type', uploadItem.media_type);
      completeFd.append('name', uploadItem.name);
      completeFd.append('description', uploadItem.description);
      completeFd.append('folder', uploadItem.folder || '/');
      completeFd.append('tags', ''); // Can append tags later if needed
      completeFd.append('size', file.size);
      completeFd.append('original_filename', file.name);
      completeFd.append('content_type', file.type || '');

      await api.post('/media/chunk/complete', completeFd);

      updateUploadState(id, { status: 'completed' }, { persist: false });
      activeProcessing.current.delete(id);
      abortControllers.current.delete(id);
      removeFromDB(id); // Clean up IDB
      
    } catch (err) {
      if (err.message === "Cancelled") {
        updateUploadState(id, {
          status: 'cancelled',
          s3UploadId: null,
          s3Key: null,
          uploadedChunks: [],
        });
      } else {
        const retries = (uploadItem.retries || 0) + 1;
        if (retries < MAX_RETRIES) {
          updateUploadState(id, { status: 'queued', retries }); // auto-requeue
        } else {
          updateUploadState(id, { status: 'failed', error: err.message });
        }
      }
      activeProcessing.current.delete(id);
      abortControllers.current.delete(id);
    }
  };

  const cancelUpload = async (id) => {
    const controller = abortControllers.current.get(id);
    if (controller) {
      controller.abort();
    }
    
    const u = await loadFromDB().then(db => db.find(x => x.id === id));
    if (u && u.s3UploadId && u.s3Key) {
      const fd = new FormData();
      fd.append('upload_id', u.s3UploadId);
      fd.append('key', u.s3Key);
      api.post('/media/chunk/abort', fd).catch(() => {});
    }

    updateUploadState(id, {
      status: 'cancelled',
      s3UploadId: null,
      s3Key: null,
      uploadedChunks: [],
    });
    activeProcessing.current.delete(id);
  };

  const resumeUpload = (id) => {
    updateUploadState(id, { status: 'queued', retries: 0 });
  };

  const clearCompleted = () => {
    setQueue(prev => {
      const removable = prev.filter(u => u.status === 'completed' || u.status === 'cancelled');
      removable.forEach(u => removeFromDB(u.id));
      return prev.filter(u => u.status !== 'completed' && u.status !== 'cancelled');
    });
  };

  return (
    <UploadContext.Provider value={{ queue, enqueueFile, enqueueFiles, cancelUpload, resumeUpload, clearCompleted }}>
      {children}
    </UploadContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useUploadQueue = () => useContext(UploadContext);
