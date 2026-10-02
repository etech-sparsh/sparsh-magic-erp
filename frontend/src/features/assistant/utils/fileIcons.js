import {
  FileText,
  FileSpreadsheet,
  Image as ImageIcon,
  FileAudio,
  FileVideo,
  FileCode,
  FileArchive,
  Presentation,
  File,
} from 'lucide-react';

const EXT_KIND = {
  // documents
  pdf: 'document', doc: 'document', docx: 'document', txt: 'document', md: 'document', rtf: 'document',
  // spreadsheets
  xls: 'spreadsheet', xlsx: 'spreadsheet', csv: 'spreadsheet',
  // presentations
  ppt: 'presentation', pptx: 'presentation',
  // images
  jpg: 'image', jpeg: 'image', png: 'image', webp: 'image', gif: 'image',
  // audio
  mp3: 'audio', wav: 'audio', aac: 'audio', ogg: 'audio', m4a: 'audio', flac: 'audio',
  // video
  mp4: 'video', mov: 'video', avi: 'video', mkv: 'video', webm: 'video',
  // archives
  zip: 'archive', rar: 'archive', '7z': 'archive',
};

const KIND_ICON = {
  document: FileText,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  image: ImageIcon,
  audio: FileAudio,
  video: FileVideo,
  code: FileCode,
  archive: FileArchive,
  other: File,
};

export function extOf(name = '') {
  return name.includes('.') ? name.split('.').pop().toLowerCase() : '';
}

export function kindOf(name = '') {
  const e = extOf(name);
  if (EXT_KIND[e]) return EXT_KIND[e];
  // Anything else recognised as text/code.
  return 'code';
}

/** Return the lucide icon component for a file name or explicit kind. */
export function iconForFile(nameOrKind = '') {
  const kind = KIND_ICON[nameOrKind] ? nameOrKind : kindOf(nameOrKind);
  return KIND_ICON[kind] || File;
}

export function formatSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
