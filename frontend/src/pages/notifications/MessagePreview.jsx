import React, { useEffect, useRef, useState } from 'react';
import { Eye, Info } from 'lucide-react';
import WhatsappPreview from '../../components/whatsapp/WhatsappPreview';
import { Modal, ModalHeader, Notice } from './NtUi';
import { fillSample, looksLikeHtml, sampleFor } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   Previews — what the recipient reads, with sample details in place of the real ones.

   An HTML email renders inside a sandboxed frame (no scripts, no same-origin access), so a
   template body can never run anything inside this app. WhatsApp reuses the composer's own
   chat bubble, so a message is judged the way the handset shows it.

   The frame is given the width an email is actually built for and then SHRUNK to fit
   whatever space the preview has. Email HTML is laid out on fixed-width tables — 600px is
   the convention — so a narrower frame does not reflow it, it clips it: the banner runs off
   the left, table cells are cut in half and the reader is left dragging a horizontal
   scrollbar to read one sentence. Shrinking shows the whole message, in proportion, the way
   the recipient will see it.

   Shrunk with `zoom`, NOT `transform: scale()`. A transform paints the frame at full size
   and then resamples that bitmap, which leaves every letter soft and slightly smeared. Zoom
   changes the size things are laid out at, so glyphs are rasterised once at their final size
   and the text stays as sharp as the rest of the page.
   ───────────────────────────────────────────────────────────── */

// What email HTML is authored against, and how much of it to show before scrolling.
const EMAIL_WIDTH = 640;
const EMAIL_HEIGHT = 560;

/** Zoom factor that fits `EMAIL_WIDTH` into the element's own width (never magnified). */
const useFitScale = (enabled) => {
  const ref = useRef(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return undefined;
    // Rounded to whole percents: a sub-pixel change on every resize frame would re-zoom the
    // frame constantly for a difference nobody can see.
    const fit = () => setScale(
      Math.round(Math.min(1, (el.clientWidth || EMAIL_WIDTH) / EMAIL_WIDTH) * 100) / 100);
    fit();
    // The preview sits in a resizable modal column, so a one-off measurement goes stale the
    // moment the window changes width.
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [enabled]);

  return [ref, scale];
};

export const EmailPreview = ({ subject, body }) => {
  const html = looksLikeHtml(body);
  const filledBody = fillSample(body);
  const filledSubject = fillSample(subject);
  const [fitRef, scale] = useFitScale(html);
  return (
    <div className="rounded-2xl border border-[var(--border)] overflow-hidden bg-[var(--bg-card)] shadow-sm">
      <div className="px-4 py-3 border-b border-[var(--border)] space-y-2" style={{ background: 'var(--input-bg)' }}>
        <div className="flex items-center gap-2.5">
          <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-black text-white shrink-0"
            style={{ background: 'var(--accent-indigo)' }}>
            S
          </span>
          <div className="min-w-0 leading-tight">
            <p className="text-[12px] font-bold truncate">Sparsh Notifications</p>
            <p className="text-[11px] text-[var(--text-muted)] truncate">to {sampleFor('name')}</p>
          </div>
        </div>
        <p className="text-[14px] font-extrabold leading-snug break-words">
          {filledSubject || <span className="text-[var(--text-muted)] font-semibold">No subject yet</span>}
        </p>
      </div>
      {html ? (
        // The frame keeps the dimensions an email is written for; `zoom` lays those out
        // smaller so the whole message fits the space, with the text still rendered sharply
        // at its final size. The zoomed frame already occupies width × zoom, so the box only
        // has to match its height.
        <div ref={fitRef} className="w-full overflow-hidden bg-white"
          style={{ height: Math.round(EMAIL_HEIGHT * scale) }}>
          <iframe title="Email preview" sandbox="" srcDoc={filledBody}
            style={{
              width: EMAIL_WIDTH, height: EMAIL_HEIGHT, border: 0, background: '#fff', zoom: scale,
            }} />
        </div>
      ) : (
        <div className="px-4 py-4 text-[13px] leading-relaxed whitespace-pre-wrap break-words min-h-[180px]">
          {filledBody || <span className="text-[var(--text-muted)]">Your message appears here</span>}
        </div>
      )}
    </div>
  );
};

/**
 * `template` — an approved Meta template (from /meta-templates/approved), or null for the
 * backup text. `bodyFields` — the detail mapped to each numbered blank, in order.
 */
export const WhatsAppMessagePreview = ({ template, bodyFields = [], fallbackBody = '' }) => {
  const blank = { header_format: 'NONE', header_text: '', header_examples: [], buttons: [], footer: '' };
  const form = template
    ? {
      ...blank,
      category: template.category || 'UTILITY',
      body: template.body || '',
      body_examples: (template.body_variables || []).map((_, i) => (bodyFields[i] ? sampleFor(bodyFields[i]) : '')),
    }
    : { ...blank, category: 'UTILITY', body: fillSample(fallbackBody), body_examples: [] };
  return (
    <WhatsappPreview form={form}
      bodyVariables={template ? template.body_variables || [] : []} headerVariables={[]}
      caption={template ? `Approved template · ${template.name}` : 'Backup text'} />
  );
};

/** Read-only preview of a saved template, opened from a list row. */
export const PreviewModal = ({ title, subtitle, channel, row, approved = [], onClose }) => {
  const template = channel === 'whatsapp' && row?.meta_template_name
    ? approved.find((t) => t.name === row.meta_template_name) || null
    : null;
  const heldByMeta = channel === 'whatsapp' && !!row?.meta_template_name && !template;
  return (
    <Modal onClose={onClose} width={channel === 'email' ? 'max-w-2xl' : 'max-w-lg'}>
      <ModalHeader icon={Eye} title={title} subtitle={subtitle} onClose={onClose} />
      <div className="px-5 py-4 space-y-3 overflow-y-auto">
        {channel === 'email' ? (
          <EmailPreview subject={row?.subject} body={row?.body} />
        ) : heldByMeta ? (
          <Notice tone="orange" icon={Info}>
            This sends the Meta template <b className="font-mono">{row.meta_template_name}</b>. Its
            approved wording is held by Meta, so it can't be shown here.
          </Notice>
        ) : (
          <WhatsAppMessagePreview template={template} bodyFields={row?.meta_params || []} fallbackBody={row?.body} />
        )}
        <p className="text-[11px] text-[var(--text-muted)]">Sample details are shown in place of the real ones.</p>
      </div>
    </Modal>
  );
};
