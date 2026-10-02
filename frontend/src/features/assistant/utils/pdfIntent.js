/**
 * Detects whether a user message is asking to export the current chat as a PDF,
 * in either English or (romanized/Devanagari) Hindi.
 *
 * Typo-tolerant: it accepts common misspellings/spacings of "pdf" (pf, pfd,
 * pd f, p d f, p.d.f, pdf file …) and also fires on a clear "download/create a
 * file of this chat" request that omits "pdf" entirely. It stays conservative
 * by pairing those cues with a chat-target so ordinary messages ("make this
 * chat shorter", "summarize the PDF I uploaded") aren't hijacked. The core chat
 * flow only diverts when this returns true.
 */

// "PDF" with common typos/spacings:
//   pdf, pf, pd f, p d f, p.d.f, p df  → the p…(d?)…f pattern
//   pfd                                → letters transposed
// Plus Devanagari forms (पीडीएफ / पीएफ / पी डी एफ).
const PDF_RE =
  /\b(p\s*\.?\s*d?\s*\.?\s*f|pfd)\b|पीडीएफ|पीएफ|पी\.?\s*डी?\.?\s*एफ/i;

// References the current chat / conversation (EN + romanized/Devanagari Hindi).
const CHAT_TARGET_RE =
  /\bchat\b|conversation|\bbaat\s?cheet\b|baatcheet|बातचीत|चैट|वार्तालाप/i;

// Export/create/download action (EN + romanized + Devanagari Hindi).
const ACTION_RE =
  /\b(make|create|generate|export|download|save|get|give|prepare)\b|bana\s?do|banado|banaa?o|banaye|banaiye|nikal\s?do|nikalo|de\s?do|chahiye|kar\s?do|karo|बना\s*दो|बनाओ|बनाइए|डाउनलोड|निकाल|दे\s*दो|चाहिए|करो|कर\s*दो/i;

// Strong "download" signal (enough on its own alongside a chat-target).
const DOWNLOAD_RE = /\bdownload\b|डाउनलोड/i;

// "file" mention (EN + Hindi spellings).
const FILE_RE = /\bfile\b|फ़?ाइल|फाईल/i;

/**
 * @param {string} text raw user message
 * @returns {boolean} true if the message means "export this chat as a PDF"
 */
export function isPdfExportIntent(text) {
  const t = (text || '').trim();
  if (!t || t.length > 200) return false; // long messages are almost never this command

  const hasPdf = PDF_RE.test(t);
  const hasChat = CHAT_TARGET_RE.test(t);
  const hasAction = ACTION_RE.test(t);
  const hasDownload = DOWNLOAD_RE.test(t);
  const hasFile = FILE_RE.test(t);

  // Explicit PDF (incl. typos) + either an action or a chat reference.
  if (hasPdf && (hasAction || hasChat)) return true;
  // "download current chat" — download is a strong enough export signal.
  if (hasChat && hasDownload) return true;
  // "create a file of the current chat" — action + file + chat target.
  if (hasChat && hasAction && hasFile) return true;
  return false;
}

export default isPdfExportIntent;
