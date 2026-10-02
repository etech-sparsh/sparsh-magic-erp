"""HRMS > printable record documents (internal recruitment track, SOP §9).

SOP §9 lists nine templates. Four already existed as artifacts (the JD, the offer letter, the
appointment letter, the assessment). Five had data and no document:

    Internal Manpower Requisition Form
    Headcount & Budget Approval Note
    Reference Check Report
    Probation Review & Confirmation Record
    Personnel File Closure Note

-- One endpoint pattern, one PDF stack -------------------------------------------------------
`GET /{entity}/{business_no}/document` for all five, gated by the entity's EXISTING read
capability. Printing a record is reading it, so inventing a `document.generate` capability
would create a user who may read a probation review but not print it -- a distinction nobody
wants to explain.

Rendering uses ReportLab, which is already the ERP's PDF stack (app/assistant/export). There
is deliberately no second one: the offer and appointment letters are HTML pages the browser
prints, and adding WeasyPrint or wkhtmltopdf beside ReportLab to serve five forms would be
two stacks to keep patched for no gain.

-- Nothing is RE-ENTERED --------------------------------------------------------------------
Every name, date and figure on these forms is read from the record. There is no "enter the
approver's name" field anywhere, because a form where the signatory is typed in is a form
that can say somebody approved something they did not. What the record holds is what prints;
where the record holds nothing, the form prints a blank line rather than an invented value.

-- Generated on demand, never stored ---------------------------------------------------------
The PDF is built per request and handed back as a signed URL. Storing it would create a
second copy free to drift from the record -- the same reasoning `file_system_document` gives
for not minting a PDF of the appointment letter.
"""
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_DOCUMENT_GENERATED, COLL_REQUISITIONS, DOCUMENT_URL_TTL_SECONDS, ENTITY_DOCUMENT,
    PRINTABLE_DOCUMENTS, budget_status,
)
from app.services.hrms_audit_service import audit


def _fmt(value, *, blank: str = "________________") -> str:
    """A value a human can read, or a printed blank line.

    A blank line rather than an empty string, because on paper "we do not hold this" and
    "this field does not exist" look identical when both render as nothing.
    """
    if value is None or value == "":
        return blank
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M UTC")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if float(value) == int(value) else f"{value:,.2f}"
    return str(value)


# =============================================================
# The five forms — each returns (title, [(section, [(label, value)])])
# =============================================================
async def _requisition_form(company_id: str, doc: dict) -> tuple:
    return "Internal Manpower Requisition Form", [
        ("Position", [
            ("Requisition number", doc.get("request_no")),
            ("Designation", doc.get("designation_name")),
            ("Department", doc.get("department_name")),
            ("Vacancies", doc.get("vacancy")),
            ("Type", doc.get("requisition_type")),
            ("Employment type", doc.get("employment_type")),
            ("Work location", doc.get("work_location")),
            ("Required by", doc.get("required_date")),
            ("Urgency", doc.get("urgency_level")),
        ]),
        ("Requirement", [
            ("Experience required", doc.get("experience_required")),
            ("Qualification", doc.get("qualification")),
            ("Essential skills", doc.get("essential_skills")),
            ("Notes", doc.get("notes")),
        ]),
        ("Raised by", [
            ("Raised by", doc.get("created_by_name")),
            ("Raised on", doc.get("created_at")),
            ("Hiring manager", doc.get("assignee_name")),
        ]),
        ("Approval chain", [
            ("Current status", doc.get("approval_status")),
            ("HR verified by", doc.get("hr_reviewed_by_name")),
            ("HR verified on", doc.get("hr_reviewed_at")),
            ("HR remarks", doc.get("hr_remarks")),
            ("Replacement for", doc.get("replacement_for_name")),
            ("Reason", doc.get("replacement_reason")),
        ]),
    ]


async def _budget_note(company_id: str, doc: dict) -> tuple:
    """The Headcount & Budget Approval Note -- the SOP's own mandatory control on paper."""
    return "Headcount & Budget Approval Note", [
        ("Position", [
            ("Requisition number", doc.get("request_no")),
            ("Designation", doc.get("designation_name")),
            ("Department", doc.get("department_name")),
            ("Vacancies requested", doc.get("vacancy")),
        ]),
        ("Sanctioned strength at approval", [
            ("Sanctioned", (doc.get("sanction_snapshot") or {}).get("sanctioned")),
            ("Actual headcount", (doc.get("sanction_snapshot") or {}).get("actual")),
            ("Committed vacancies",
             (doc.get("sanction_snapshot") or {}).get("open_requisitions")),
            ("Over sanctioned strength",
             (doc.get("sanction_snapshot") or {}).get("is_over_sanction")),
        ]),
        ("Approved figures", [
            ("Approved headcount", doc.get("approved_headcount")),
            ("Salary band minimum", doc.get("approved_salary_band_min")),
            ("Salary band maximum", doc.get("approved_salary_band_max")),
            # Phase INT-2: whether these came from the standing band master or were typed.
            ("Band source", doc.get("band_source")),
            ("Standing band referenced", doc.get("band_master_no")),
            ("Budget status", budget_status(doc)),
        ]),
        ("Approved by", [
            ("Approved by", doc.get("budget_approved_by_name")),
            ("Approved on", doc.get("budget_approved_at")),
            ("Remarks", doc.get("budget_remarks_approver")),
            ("Escalation note", doc.get("escalation_note")),
        ]),
    ]


async def _reference_report(company_id: str, doc: dict) -> tuple:
    return "Reference Check Report", [
        ("Candidate", [
            ("Reference number", doc.get("ref_no")),
            ("Candidate", doc.get("candidate_name")),
            ("Candidate id", doc.get("uk")),
            ("Requisition", doc.get("request_no")),
        ]),
        ("Referee", [
            ("Name", doc.get("referee_name")),
            ("Designation", doc.get("referee_designation")),
            ("Organisation", doc.get("referee_organisation")),
            ("Relationship to candidate", doc.get("relationship")),
            ("Contact", doc.get("referee_contact")),
        ]),
        ("The check", [
            ("Mode", doc.get("mode")),
            ("Checked on", doc.get("checked_on")),
            ("Responses", doc.get("responses")),
            ("Outcome", doc.get("outcome")),
            ("Remarks", doc.get("remarks")),
        ]),
        ("Recorded by", [
            ("Recorded by", doc.get("checked_by_name") or doc.get("created_by_name")),
            ("Recorded on", doc.get("created_at")),
            ("Keep until", doc.get("retention_until")),
        ]),
    ]


async def _probation_record(company_id: str, doc: dict) -> tuple:
    return "Probation Review & Confirmation Record", [
        ("Employee", [
            ("Probation number", doc.get("prb_no")),
            ("Employee code", doc.get("employee_code")),
            ("Name", doc.get("employee_name")),
            ("Requisition", doc.get("request_no")),
        ]),
        ("The probation term", [
            ("Started on", doc.get("started_on")),
            ("Duration (months)", doc.get("duration_months")),
            ("Ends on", doc.get("ends_on")),
            ("Extensions", doc.get("extension_count") or 0),
            ("Extended to", doc.get("extended_to")),
        ]),
        ("The decision", [
            ("Outcome", doc.get("outcome")),
            ("Rating (1-5, against the position scorecard)", doc.get("rating")),
            ("Remarks", doc.get("remarks")),
            ("Notes", doc.get("notes")),
        ]),
        ("Signed", [
            ("Decided by", doc.get("confirmed_by_name")),
            ("Decided on", doc.get("confirmed_at")),
            ("Signature", doc.get("signature")),
            ("Keep until", doc.get("retention_until")),
        ]),
    ]


async def _personnel_file_note(company_id: str, doc: dict) -> tuple:
    return "Personnel File Closure Note", [
        ("Employee", [
            ("Employee code", doc.get("employee_code")),
            ("Name", doc.get("display_name") or doc.get("full_name")),
            ("Department", doc.get("department_name")),
            ("Designation", doc.get("designation_name")),
            ("Joined on", doc.get("joined_on")),
        ]),
        ("Probation", [
            ("Probation record", doc.get("probation_prb_no")),
            ("Outcome", doc.get("probation_status")),
            ("Ended on", doc.get("probation_ends_on")),
            ("Confirmed on", doc.get("probation_confirmed_at")),
        ]),
        ("Closure", [
            ("File closed", doc.get("personnel_file_closed")),
            ("Closed on", doc.get("personnel_file_closed_at")),
            ("Closure note", doc.get("personnel_file_closure_note")),
        ]),
    ]


BUILDERS = {
    "requisition":    _requisition_form,
    "budget-note":    _budget_note,
    "reference":      _reference_report,
    "probation":      _probation_record,
    "personnel-file": _personnel_file_note,
}


# =============================================================
# Rendering
# =============================================================
def _render_pdf(*, company_name: str, title: str, business_no: str,
                sections: list, generated_by: str) -> bytes:
    """Build the PDF. ReportLab Platypus, matching app/assistant/export/pdf_generator.

    Long values wrap and sections flow across pages, because a reference-check response is
    sometimes three sentences and sometimes three paragraphs, and a form that silently
    truncates the long one is a form that loses the interesting answer.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle("hrms_body", parent=styles["BodyText"], fontSize=9,
                          leading=12.5)
    label = ParagraphStyle("hrms_label", parent=body, textColor=colors.HexColor("#555555"))
    heading = ParagraphStyle("hrms_heading", parent=styles["Heading2"], fontSize=11,
                             spaceBefore=10, spaceAfter=4,
                             textColor=colors.HexColor("#1f2937"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"{title} — {business_no}", author=company_name or "Sparsh Magic")

    # The letterhead. The company name comes from the companies record, never from a
    # request parameter -- a printable form that can be made to carry any letterhead is a
    # forgery kit.
    flow = [
        Paragraph(f"<b>{company_name or 'Sparsh Magic'}</b>",
                  ParagraphStyle("hrms_head", parent=styles["Heading1"], fontSize=14)),
        Paragraph(title, ParagraphStyle("hrms_sub", parent=styles["Heading2"],
                                        fontSize=12, spaceAfter=2)),
        Paragraph(f"Reference: <b>{business_no}</b>", body),
        Spacer(1, 6 * mm),
    ]

    for section_title, rows in sections:
        flow.append(Paragraph(section_title, heading))
        table_rows = [[Paragraph(f"{name}", label), Paragraph(_fmt(value), body)]
                      for name, value in rows]
        table = Table(table_rows, colWidths=[60 * mm, 105 * mm])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
        ]))
        flow.append(table)

    flow += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"Generated from the HRMS record on "
            f'{datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")} by '
            f"{generated_by}. Every figure above is read from the record; nothing on this "
            f"form was re-entered.",
            ParagraphStyle("hrms_foot", parent=body, fontSize=7.5,
                           textColor=colors.HexColor("#6b7280"))),
    ]
    doc.build(flow)
    return buffer.getvalue()


# =============================================================
# The one endpoint pattern
# =============================================================
async def generate(actor: dict, company_id: str, entity: str,
                   business_no: str) -> dict:
    """Render one record as a PDF and return a signed URL to it.

    `entity` is an ALLOW-LIST key, never a collection name. Mapping a URL segment straight
    onto a collection would let a caller print any collection in the database -- the same
    trap REPORT_ENTITIES exists to close on the reports endpoint.
    """
    spec = PRINTABLE_DOCUMENTS.get(entity)
    if not spec:
        raise HTTPException(
            status_code=404,
            detail=(f"There is no printable document for '{entity}'. Available: "
                    f"{', '.join(sorted(PRINTABLE_DOCUMENTS))}."))
    title, collection, id_field, _cap = spec

    doc = await get_collection(collection).find_one(
        {id_field: business_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{business_no} not found.")

    # The budget note is a VIEW of the requisition, so it shares the collection but must
    # only print once the gate it documents has actually cleared. Printing an approval note
    # for an unapproved budget would produce a document asserting something untrue.
    if entity == "budget-note" and not doc.get("budget_approved_at"):
        raise HTTPException(
            status_code=409,
            detail=(f"{business_no}'s budget has not been approved yet, so there is no "
                    f"approval note to print."))

    company_name = await _company_name(company_id)
    _title, sections = await BUILDERS[entity](company_id, doc)
    pdf = _render_pdf(
        company_name=company_name, title=_title or title, business_no=business_no,
        sections=sections,
        generated_by=(actor.get("full_name") or actor.get("email") or "an HRMS user"))

    url, key = await _store(pdf, entity, business_no)
    await audit(actor, AUDIT_DOCUMENT_GENERATED, ENTITY_DOCUMENT, business_no,
                f"{_title or title} generated", company_id)
    return {
        "entity": entity,
        "business_no": business_no,
        "title": _title or title,
        "url": url,
        "s3_key": key,
        "expires_in": DOCUMENT_URL_TTL_SECONDS,
        "generated_at": datetime.now(timezone.utc),
    }


async def _company_name(company_id: str) -> str:
    """The letterhead name, from the companies record. Never from a request."""
    try:
        from bson import ObjectId
        row = await get_collection("companies").find_one(
            {"_id": ObjectId(str(company_id))}, {"name": 1, "company_name": 1})
        return (row or {}).get("name") or (row or {}).get("company_name") or ""
    except Exception:
        return ""


async def _store(pdf: bytes, entity: str, business_no: str) -> tuple:
    """Put the PDF where a signed URL can reach it.

    Uploaded rather than streamed so the response shape matches
    `GET /documents/{doc_no}/url` -- one way to hand a caller a document, not two. The object
    is a fresh key per generation and is never recorded in the document register: it is a
    print of a record, not a record of its own.
    """
    from app.services.s3_service import get_signed_url, upload_file_to_s3_with_key
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"hrms_{entity}_{business_no}_{stamp}.pdf"
    try:
        result = upload_file_to_s3_with_key(io.BytesIO(pdf), filename, "application/pdf")
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"The document could not be generated right now. ({e})")
    key = result.get("key") if isinstance(result, dict) else None
    if not key:
        raise HTTPException(
            status_code=503, detail="The document could not be generated right now.")
    return get_signed_url(key, expires_in=DOCUMENT_URL_TTL_SECONDS), key
