import React from 'react';
import { ExternalLink, FileText, Image as ImageIcon, Phone, Reply, Video } from 'lucide-react';

import { MEDIA_HEADERS } from './constants';

/* ─────────────────────────────────────────────────────────────
   Live WhatsApp preview for the template composer.

   Renders the message the way the handset will: WhatsApp's own markup (*bold*, _italic_,
   ~strike~, ```mono```), the header/footer/button chrome, and the sample values standing in
   for {{variables}} so the copy can be read as a sentence rather than a template.

   The surrounding chat frame is deliberate — a bubble floating on a plain card reads as a
   form field, while the same bubble on a conversation reads as a message, which is the thing
   actually being judged before it goes to Meta.
   ───────────────────────────────────────────────────────────── */

/* WhatsApp's four inline markers, most-greedy first so ``` wins over the single-char ones. */
const MARKERS = [
  { open: '```', close: '```', tag: 'code' },
  { open: '*', close: '*', tag: 'b' },
  { open: '_', close: '_', tag: 'i' },
  { open: '~', close: '~', tag: 's' },
];

const MONO = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '0.92em' };

/**
 * Text → React nodes, applying WhatsApp formatting recursively so *bold with _italic_ inside*
 * renders correctly. Returns nodes (never HTML), so nothing the admin types can inject markup.
 */
const renderFormatted = (text, keyPrefix = 'f') => {
  const source = String(text ?? '');
  if (!source) return null;

  for (const { open, close, tag } of MARKERS) {
    const start = source.indexOf(open);
    if (start === -1) continue;
    const end = source.indexOf(close, start + open.length);
    // A marker with nothing between it is literal text, not formatting.
    if (end === -1 || end === start + open.length) continue;

    const before = source.slice(0, start);
    const inner = source.slice(start + open.length, end);
    const after = source.slice(end + close.length);
    const Tag = tag;
    return [
      renderFormatted(before, `${keyPrefix}b`),
      <Tag key={`${keyPrefix}-${start}`} style={tag === 'code' ? MONO : undefined}>
        {renderFormatted(inner, `${keyPrefix}i`)}
      </Tag>,
      renderFormatted(after, `${keyPrefix}a`),
    ];
  }

  // No markers left — emit the plain text, keeping line breaks the admin typed.
  return source.split('\n').map((line, i, all) => (
    <React.Fragment key={`${keyPrefix}-l${i}`}>
      {line}
      {i < all.length - 1 && <br />}
    </React.Fragment>
  ));
};

/**
 * Swap {{1}} / {{name}} for the sample values, so the preview reads like a real message.
 * A variable with no sample yet keeps its token — seeing {{2}} is the clearest signal that
 * an example is still missing.
 */
const fillVariables = (text, variables, examples) => {
  let out = String(text ?? '');
  (variables || []).forEach((v, i) => {
    const sample = String((examples || [])[i] ?? '').trim();
    if (!sample) return;
    out = out.split(`{{${v}}}`).join(sample);
  });
  return out;
};

const MEDIA_ICON = { IMAGE: ImageIcon, VIDEO: Video, DOCUMENT: FileText };
const BUTTON_ICON = { URL: ExternalLink, PHONE_NUMBER: Phone, QUICK_REPLY: Reply };

/** The chat-bubble body — shared by the composer and any read-only preview. */
export const WhatsappBubble = ({ form, bodyVariables = [], headerVariables = [] }) => {
  const isAuth = form.category === 'AUTHENTICATION';
  const body = isAuth
    ? '<#> 123456 is your verification code.'
    : fillVariables(form.body, bodyVariables, form.body_examples);
  const headerText = fillVariables(form.header_text, headerVariables, form.header_examples);
  const MediaIcon = MEDIA_ICON[form.header_format];
  const buttons = isAuth
    ? [{ type: 'QUICK_REPLY', text: (form.buttons?.[0]?.text || '').trim() || 'Copy code' }]
    : (form.buttons || []);
  const footer = isAuth
    ? (form.code_expiration_minutes
      ? `This code expires in ${form.code_expiration_minutes} minutes.`
      : '')
    : (form.footer || '');

  return (
    <div className="relative">
      {/* Incoming-bubble tail. A business template arrives as an incoming message, so the
          tail belongs on the left — the same side the handset draws it. */}
      <span className="absolute -left-[7px] top-0 w-0 h-0"
        style={{
          borderRight: '8px solid var(--bg-card)',
          borderBottom: '9px solid transparent',
        }} />
      <div className="rounded-xl rounded-tl-none shadow-sm overflow-hidden"
        style={{ background: 'var(--bg-card)' }}>
        {/* media header — the handset shows the file itself; this stands in for it */}
        {MediaIcon && MEDIA_HEADERS.includes(form.header_format) && (
          <div className="flex flex-col items-center justify-center gap-1.5 h-24 m-1.5 mb-0 rounded-lg"
            style={{ background: 'var(--input-bg)', color: 'var(--text-muted)' }}>
            <MediaIcon size={22} />
            <span className="text-[10px] font-bold uppercase tracking-widest">
              {form.header_format.toLowerCase()}
            </span>
          </div>
        )}

        <div className="px-2.5 py-2 space-y-1.5">
          {form.header_format === 'TEXT' && headerText && (
            <p className="text-[13px] font-extrabold leading-snug break-words">
              {renderFormatted(headerText, 'h')}
            </p>
          )}

          <p className="text-[13px] leading-relaxed whitespace-pre-wrap break-words"
            style={{ color: body ? 'var(--text-main)' : 'var(--text-muted)' }}>
            {body ? renderFormatted(body, 'b') : 'Your message appears here'}
          </p>

          {footer && (
            <p className="text-[11px] leading-snug break-words" style={{ color: 'var(--text-muted)' }}>
              {footer}
            </p>
          )}

          <p className="text-[10px] text-right tabular-nums leading-none pt-0.5"
            style={{ color: 'var(--text-muted)' }}>
            12:00
          </p>
        </div>

        {buttons.length > 0 && (
          <div className="border-t" style={{ borderColor: 'var(--border)' }}>
            {buttons.map((b, i) => {
              const Icon = BUTTON_ICON[b.type] || Reply;
              return (
                <div key={i}
                  className="flex items-center justify-center gap-1.5 px-3 py-2 text-[12.5px] font-bold border-b last:border-b-0"
                  style={{ color: 'var(--accent-indigo)', borderColor: 'var(--border)' }}>
                  <Icon size={13} />
                  <span className="truncate">{b.text || 'Button'}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * The preview column: a small chat window with the template rendered as the incoming message.
 * `caption` labels what is being shown (e.g. the category), and the textured backdrop is what
 * makes the bubble read as a message rather than another panel in the form.
 */
const WhatsappPreview = ({ form, bodyVariables, headerVariables, caption }) => (
  <div className="rounded-2xl overflow-hidden border shadow-sm"
    style={{ borderColor: 'var(--border)' }}>
    {/* chat header */}
    <div className="flex items-center gap-2 px-3 py-2.5"
      style={{ background: 'var(--accent-green)', color: '#fff' }}>
      <span className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-black shrink-0"
        style={{ background: 'rgba(255,255,255,0.25)' }}>
        S
      </span>
      <div className="min-w-0">
        <p className="text-[12px] font-bold leading-tight truncate">Your business</p>
        <p className="text-[10px] leading-tight" style={{ color: 'rgba(255,255,255,0.8)' }}>
          {caption || 'WhatsApp Business'}
        </p>
      </div>
    </div>

    {/* conversation */}
    <div className="relative px-3 py-4 pl-4 min-h-[190px]" style={{ background: 'var(--input-bg)' }}>
      <div className="absolute inset-0 pointer-events-none opacity-40" style={{
        backgroundImage: 'radial-gradient(circle at 1px 1px, var(--border) 1px, transparent 0)',
        backgroundSize: '14px 14px',
      }} />
      <div className="relative">
        <WhatsappBubble form={form} bodyVariables={bodyVariables} headerVariables={headerVariables} />
      </div>
    </div>
  </div>
);

export default WhatsappPreview;
