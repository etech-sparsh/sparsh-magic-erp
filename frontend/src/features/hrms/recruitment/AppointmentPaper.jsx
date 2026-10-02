import React from 'react';

/**
 * HRMS ▸ the appointment letter itself (Phase 11-R, Item 3).
 *
 * Built from OfferPaper, and shared by the internal preview and the public candidate page
 * for the same reason: what HR proof-reads must be byte-for-byte what the candidate reads.
 * Two renderings would drift, and the one that drifts is the one somebody acknowledges.
 *
 * Deliberately styled in fixed light colours rather than the ERP's theme variables — this
 * is a DOCUMENT. It must look identical in dark mode, in print and in a PDF, and
 * `print-color-adjust: exact` keeps the rules when printed.
 */
const AppointmentPaper = ({ appointment, signature, showAcknowledgement = true }) => {
  if (!appointment) return null;

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
            {appointment.company_name || 'Letter of Appointment'}
          </p>
          <p className="text-[12px] text-slate-500 mt-0.5">Letter of Appointment</p>
        </div>
        <div className="text-right text-[11.5px] text-slate-500">
          <p className="font-mono">{appointment.appointment_no}</p>
          {appointment.sent_at && (
            <p>{new Date(appointment.sent_at).toLocaleDateString(undefined,
              { day: 'numeric', month: 'long', year: 'numeric' })}</p>
          )}
        </div>
      </div>

      <p className="text-[14.5px] mb-1">Dear {appointment.candidate_name},</p>
      <p className="text-[15px] font-bold mb-5">
        Appointment — {appointment.designation}
      </p>

      <div className="text-[14px] leading-[1.75] whitespace-pre-wrap mb-8">
        {appointment.content}
      </div>

      <table className="w-full text-[13.5px] mb-9" style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {[
            ['Position', appointment.designation],
            ['Department', appointment.department],
            ['Location', appointment.location],
            ['Annual CTC', appointment.ctc != null ? inr(appointment.ctc) : null],
            ['Date of joining', appointment.joining_date],
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
          <p className="text-[13.5px] mb-6">For and on behalf of the company,</p>
          <div style={{ borderTop: '1px solid #0f172a', width: 200, paddingTop: 6 }}>
            <p className="text-[13px] font-bold">
              {signature || appointment.signature || '—'}
            </p>
            <p className="text-[11px] text-slate-500">Authorised signatory</p>
          </div>
        </div>

        {showAcknowledgement && appointment.acknowledgement_signature && (
          <div>
            <p className="text-[13.5px] mb-6">Acknowledged by,</p>
            <div style={{ borderTop: '1px solid #0f172a', width: 200, paddingTop: 6 }}>
              <p className="text-[13px] font-bold">
                {appointment.acknowledgement_signature}
              </p>
              <p className="text-[11px] text-slate-500">
                {appointment.acknowledged_at
                  ? new Date(appointment.acknowledged_at).toLocaleDateString()
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

export default AppointmentPaper;
