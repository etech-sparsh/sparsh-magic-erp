import React from 'react';

/**
 * HRMS ▸ the offer letter itself.
 *
 * Shared by the internal preview and the public candidate page, so what HR proof-reads is
 * byte-for-byte what the candidate reads. Two separate renderings would drift, and the one
 * that drifts is the one somebody signs.
 *
 * Deliberately styled in fixed light colours rather than the ERP's theme variables: this is
 * a document. It must look identical in dark mode, in print, and in a PDF, and
 * `print-color-adjust: exact` keeps the accent bars when printed.
 */
const OfferPaper = ({ offer, signature, showResponse = true }) => {
  if (!offer) return null;

  const inr = (n) =>
    typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : (n || '—');

  return (
    <div
      className="bg-white text-slate-900 mx-auto"
      style={{
        maxWidth: '760px',
        padding: '48px 56px',
        fontFamily: 'Georgia, "Times New Roman", serif',
        printColorAdjust: 'exact',
        WebkitPrintColorAdjust: 'exact',
      }}
    >
      <div style={{ height: 6, background: '#0f172a', marginBottom: 4 }} />
      <div style={{ height: 2, background: '#94a3b8', marginBottom: 32 }} />

      <div className="flex items-start justify-between gap-6 mb-10">
        <div>
          <p className="text-[19px] font-bold tracking-tight">
            {offer.company_name || 'Letter of Offer'}
          </p>
          <p className="text-[12px] text-slate-500 mt-0.5">Letter of Employment Offer</p>
        </div>
        <div className="text-right text-[11.5px] text-slate-500">
          <p className="font-mono">{offer.offer_no}</p>
          {offer.sent_at && (
            <p>{new Date(offer.sent_at).toLocaleDateString(undefined,
              { day: 'numeric', month: 'long', year: 'numeric' })}</p>
          )}
        </div>
      </div>

      <p className="text-[14.5px] mb-1">Dear {offer.candidate_name},</p>
      <p className="text-[15px] font-bold mb-5">
        Offer of employment — {offer.designation}
      </p>

      <div className="text-[14px] leading-[1.75] whitespace-pre-wrap mb-8">
        {offer.content}
      </div>

      <table className="w-full text-[13.5px] mb-9" style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {[
            ['Position', offer.designation],
            ['Location', offer.location],
            ['Annual CTC', inr(offer.ctc)],
            ['Proposed joining date', offer.joining_date],
          ].filter(([, v]) => v).map(([label, value]) => (
            <tr key={label}>
              <td style={{ padding: '7px 0', borderBottom: '1px solid #e2e8f0', width: '45%' }}
                className="text-slate-500">
                {label}
              </td>
              <td style={{ padding: '7px 0', borderBottom: '1px solid #e2e8f0' }}
                className="font-bold">
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-end justify-between gap-8 mt-12">
        <div>
          <p className="text-[13.5px] mb-6">Yours sincerely,</p>
          <div style={{ borderTop: '1px solid #0f172a', width: 200, paddingTop: 6 }}>
            <p className="text-[13px] font-bold">{signature || offer.signature || '—'}</p>
            <p className="text-[11px] text-slate-500">Authorised signatory</p>
          </div>
        </div>

        {showResponse && offer.candidate_signature && (
          <div>
            <p className="text-[13.5px] mb-6">Accepted by,</p>
            <div style={{ borderTop: '1px solid #0f172a', width: 200, paddingTop: 6 }}>
              <p className="text-[13px] font-bold">{offer.candidate_signature}</p>
              <p className="text-[11px] text-slate-500">
                {offer.responded_at
                  ? new Date(offer.responded_at).toLocaleDateString()
                  : 'Candidate'}
              </p>
            </div>
          </div>
        )}
      </div>

      <div style={{ height: 2, background: '#94a3b8', marginTop: 40, marginBottom: 4 }} />
      <div style={{ height: 6, background: '#0f172a' }} />
    </div>
  );
};

export default OfferPaper;
