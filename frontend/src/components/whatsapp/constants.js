/**
 * TPMS ▸ WhatsApp template library — shared vocabulary, limits and text helpers.
 *
 * Every constant here mirrors what the Cloud API accepts (and what
 * backend/app/models/tpms.py stores), so the composer can warn about a problem before the
 * payload is ever built. The backend re-checks all of it — this half is for fast feedback,
 * never the authority.
 */

export const CATEGORIES = [
  { id: 'UTILITY', label: 'UTILITY', hint: 'Order updates, reminders, account notices. Cheapest and easiest to approve.' },
  { id: 'MARKETING', label: 'MARKETING', hint: 'Offers, announcements, anything promotional. Recipients can opt out.' },
  { id: 'AUTHENTICATION', label: 'AUTHENTICATION', hint: 'One-time passcodes only. Meta writes the copy — you set the expiry.' },
];

export const HEADER_FORMATS = [
  { id: 'NONE', label: 'None' },
  { id: 'TEXT', label: 'Text' },
  { id: 'IMAGE', label: 'Image' },
  { id: 'VIDEO', label: 'Video' },
  { id: 'DOCUMENT', label: 'Document' },
];
export const MEDIA_HEADERS = ['IMAGE', 'VIDEO', 'DOCUMENT'];

export const BUTTON_TYPES = [
  { id: 'QUICK_REPLY', label: 'Quick Reply' },
  { id: 'URL', label: 'URL' },
  { id: 'PHONE_NUMBER', label: 'Call' },
];

export const VARIABLE_STYLES = [
  { id: 'numbered', label: 'Numbered — {{1}}, {{2}}' },
  { id: 'named', label: 'Named — {{customer_name}}' },
];

/** Meta's locale codes. `en` and `en_US` are distinct templates on the WABA. */
export const LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'en_US', label: 'English (US)' },
  { id: 'en_GB', label: 'English (UK)' },
  { id: 'hi', label: 'Hindi' },
  { id: 'mr', label: 'Marathi' },
  { id: 'gu', label: 'Gujarati' },
  { id: 'bn', label: 'Bengali' },
  { id: 'ta', label: 'Tamil' },
  { id: 'te', label: 'Telugu' },
  { id: 'kn', label: 'Kannada' },
  { id: 'ml', label: 'Malayalam' },
  { id: 'pa', label: 'Punjabi' },
  { id: 'ur', label: 'Urdu' },
  { id: 'ar', label: 'Arabic' },
  { id: 'es', label: 'Spanish' },
  { id: 'fr', label: 'French' },
  { id: 'de', label: 'German' },
  { id: 'pt_BR', label: 'Portuguese (BR)' },
  { id: 'id', label: 'Indonesian' },
  { id: 'ja', label: 'Japanese' },
  { id: 'zh_CN', label: 'Chinese (Simplified)' },
];

export const LIMITS = {
  body: 1024,
  footer: 60,
  header: 60,
  buttonText: 25,
  maxButtons: 10,
  maxUrlButtons: 2,
  maxPhoneButtons: 1,
};

/** DRAFT is ours; the rest are Meta's own status vocabulary. */
export const STATUS_TONE = {
  DRAFT: 'muted',
  PENDING: 'orange',
  APPROVED: 'green',
  REJECTED: 'red',
  PAUSED: 'orange',
  IN_APPEAL: 'orange',
  DISABLED: 'red',
  PENDING_DELETION: 'muted',
  DELETED: 'muted',
};

/** Statuses whose definition we still own, so the row can be edited and resubmitted. */
export const EDITABLE_STATUSES = ['DRAFT', 'REJECTED'];

export const TEMPLATE_NAME_RE = /^[a-z0-9_]+$/;
const VAR_RE = /\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g;

/** Every {{token}} in order of appearance, duplicates included. */
export const extractVariables = (text) => [...String(text || '').matchAll(VAR_RE)].map((m) => m[1]);

/** The distinct variables a piece of copy declares. Numbered ones come back sorted so
 *  {{2}} written before {{1}} still yields ['1','2'] and the gap check stays meaningful. */
export const orderedVariables = (text, style) => {
  const seen = new Set();
  const out = [];
  extractVariables(text).forEach((t) => { if (!seen.has(t)) { seen.add(t); out.push(t); } });
  if (style === 'numbered') out.sort((a, b) => Number(a) - Number(b));
  return out;
};

/** 'numbered' | 'named' | 'mixed' | null. Meta rejects 'mixed' outright. */
export const detectStyle = (text) => {
  const tokens = extractVariables(text);
  if (!tokens.length) return null;
  const numbered = tokens.some((t) => /^\d+$/.test(t));
  const named = tokens.some((t) => !/^\d+$/.test(t));
  if (numbered && named) return 'mixed';
  return numbered ? 'numbered' : 'named';
};

/** The next variable token to insert, given what the copy already uses. */
export const nextVariableToken = (text, style) => {
  if (style === 'named') return '{{variable_name}}';
  const used = orderedVariables(text, 'numbered').map(Number).filter((n) => !Number.isNaN(n));
  return `{{${used.length ? Math.max(...used) + 1 : 1}}}`;
};

/**
 * The problems Meta would reject the template for, phrased for the person fixing them.
 * Deliberately the same rule set as meta_whatsapp_service.validate_template — this copy just
 * runs on every keystroke so nothing is a surprise at submit time.
 */
export const validateTemplate = (form) => {
  const errors = [];
  const name = (form.name || '').trim();
  if (!name) errors.push('Template name is required.');
  else if (!TEMPLATE_NAME_RE.test(name)) {
    errors.push('Template name may only contain lowercase letters, numbers and underscores.');
  }
  if (!(form.language || '').trim()) errors.push('Language is required.');

  if (form.category === 'AUTHENTICATION') {
    const mins = form.code_expiration_minutes;
    if (mins !== '' && mins != null && (Number.isNaN(Number(mins)) || Number(mins) < 1 || Number(mins) > 90)) {
      errors.push('Code expiry must be between 1 and 90 minutes.');
    }
    return errors;
  }

  const style = form.variable_style || 'numbered';

  // ── header ──
  if (form.header_format === 'TEXT') {
    const text = (form.header_text || '').trim();
    if (!text) errors.push('A text header needs header text.');
    else if (text.length > LIMITS.header) errors.push(`Header text must be ${LIMITS.header} characters or fewer.`);
    const vars = extractVariables(text);
    if (vars.length > 1) errors.push('A header may contain at most one variable.');
    if (vars.length && !(form.header_examples || []).some((e) => String(e || '').trim())) {
      errors.push('Give a sample value for the header variable.');
    }
    const found = detectStyle(text);
    if (found === 'mixed' || (found && found !== style)) {
      errors.push('The header uses a different variable style from the body — Meta rejects a mix.');
    }
  } else if (MEDIA_HEADERS.includes(form.header_format)) {
    if (!(form.header_media_url || '').trim() && !(form.header_handle || '').trim()) {
      errors.push(`A ${form.header_format.toLowerCase()} header needs a public URL to a sample file.`);
    }
  }

  // ── body ──
  const body = (form.body || '').trim();
  if (!body) {
    errors.push('Body is required.');
  } else {
    if (body.length > LIMITS.body) errors.push(`Body must be ${LIMITS.body} characters or fewer.`);
    const found = detectStyle(body);
    if (found === 'mixed') {
      errors.push('The body mixes {{1}} and {{named}} variables — pick one style.');
    } else if (found && found !== style) {
      errors.push(`The body uses ${found} variables but the template is set to ${style}.`);
    } else {
      const vars = orderedVariables(body, style);
      if (vars.length) {
        if (/^\{\{/.test(body) || /\}\}$/.test(body)) {
          errors.push('The body cannot start or end with a variable — Meta requires text around every parameter.');
        }
        if (/\}\}\s*\{\{/.test(body)) {
          errors.push('Two variables cannot sit next to each other — put some text between them.');
        }
        if (style === 'numbered') {
          const expected = vars.map((_, i) => String(i + 1));
          if (vars.join(',') !== expected.join(',')) {
            errors.push(`Numbered variables must run 1, 2, 3 … with no gaps — found ${vars.map((v) => `{{${v}}}`).join(', ')}.`);
          }
        } else {
          const bad = vars.filter((v) => !/^[a-z][a-z0-9_]*$/.test(v));
          if (bad.length) errors.push(`Named variables must be lowercase words starting with a letter — fix ${bad.map((v) => `{{${v}}}`).join(', ')}.`);
        }
        const examples = form.body_examples || [];
        if (vars.some((_, i) => !String(examples[i] || '').trim())) {
          errors.push('Give a sample value for every body variable.');
        }
      }
    }
  }

  // ── footer ──
  const footer = (form.footer || '').trim();
  if (footer.length > LIMITS.footer) errors.push(`Footer must be ${LIMITS.footer} characters or fewer.`);
  if (footer && extractVariables(footer).length) errors.push('Footers cannot contain variables.');

  // ── buttons ──
  const buttons = form.buttons || [];
  if (buttons.length > LIMITS.maxButtons) errors.push(`A template may have at most ${LIMITS.maxButtons} buttons.`);
  const seen = new Set();
  let urls = 0;
  let phones = 0;
  buttons.forEach((b, i) => {
    const text = (b.text || '').trim();
    if (!text) errors.push(`Button ${i + 1}: label is required.`);
    else if (text.length > LIMITS.buttonText) errors.push(`Button ${i + 1}: label must be ${LIMITS.buttonText} characters or fewer.`);
    if (text && seen.has(text.toLowerCase())) errors.push(`Button ${i + 1}: two buttons cannot share the label “${text}”.`);
    seen.add(text.toLowerCase());

    if (b.type === 'URL') {
      urls += 1;
      const url = (b.url || '').trim();
      if (!url) errors.push(`Button ${i + 1}: a URL button needs a URL.`);
      else if (!/^https?:\/\//i.test(url)) errors.push(`Button ${i + 1}: the URL must start with http:// or https://.`);
      const vars = extractVariables(url);
      if (vars.length > 1) errors.push(`Button ${i + 1}: a URL may contain at most one variable, at the end.`);
      else if (vars.length && !url.trim().endsWith('}}')) errors.push(`Button ${i + 1}: a URL variable must be the last part of the URL.`);
      if (vars.length && !(b.url_example || '').trim()) errors.push(`Button ${i + 1}: give a sample full URL.`);
    } else if (b.type === 'PHONE_NUMBER') {
      phones += 1;
      const phone = (b.phone_number || '').trim();
      if (!phone) errors.push(`Button ${i + 1}: a call button needs a phone number.`);
      else if (!/^\+?\d{6,20}$/.test(phone)) errors.push(`Button ${i + 1}: use international format, e.g. +919876543210.`);
    }
  });
  if (urls > LIMITS.maxUrlButtons) errors.push(`At most ${LIMITS.maxUrlButtons} URL buttons are allowed.`);
  if (phones > LIMITS.maxPhoneButtons) errors.push(`At most ${LIMITS.maxPhoneButtons} call button is allowed.`);

  return errors;
};

/** A blank composer form — also the shape the modal resets to. */
export const EMPTY_TEMPLATE = {
  name: '',
  language: 'en',
  category: 'UTILITY',
  variable_style: 'numbered',
  header_format: 'NONE',
  header_text: '',
  header_examples: [],
  header_media_url: '',
  header_handle: '',
  body: '',
  body_examples: [],
  footer: '',
  buttons: [],
  add_security_recommendation: true,
  code_expiration_minutes: '',
};

/** Seed the composer from a stored library row, or a blank when adding. */
export const seedTemplate = (row) => (row ? {
  ...EMPTY_TEMPLATE,
  ...row,
  language: row.language || 'en',
  category: row.category || 'UTILITY',
  variable_style: row.variable_style || 'numbered',
  header_format: row.header_format || 'NONE',
  header_text: row.header_text || '',
  header_examples: row.header_examples || [],
  header_media_url: row.header_media_url || '',
  header_handle: row.header_handle || '',
  body: row.body || '',
  body_examples: row.body_examples || [],
  footer: row.footer || '',
  buttons: (row.buttons || []).map((b) => ({
    type: b.type || 'QUICK_REPLY',
    text: b.text || '',
    url: b.url || '',
    url_example: b.url_example || '',
    phone_number: b.phone_number || '',
  })),
  code_expiration_minutes: row.code_expiration_minutes ?? '',
} : { ...EMPTY_TEMPLATE });
