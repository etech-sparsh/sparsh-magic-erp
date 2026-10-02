"""HRMS > the record-retention purge (internal recruitment track, SOP §13).

`retention_until` has been stamped and reported since the internal track shipped, and nothing
has ever deleted. This is the job that does -- and it is deliberately NOT a silent cron.

-- Three properties, each of which is why the previous phase declined to build this ----------

 1. A PURGE IS PROPOSED, THEN APPROVED.
    A dry run writes a `hrms_purge_batches` row listing counts by record type and the EXACT
    ids. Nothing happens until somebody with `retention.purge` (MD only) approves it with a
    typed signature -- the same standard probation confirmation holds, because both destroy
    or end something. An automated purge of employment records is a decision for the business
    and its auditors, not a side effect of a nightly job.

 2. IT REDACTS RATHER THAN HARD-DELETES.
    Every HRMS record is referenced by at least an audit row. Deleting the record and leaving
    the audit entry produces a trail full of dangling references, which proves nothing and
    is worse than keeping the data. So the id and the audit spine survive and the PII fields
    are cleared, stamped with `purged_at` and the batch number -- so a reader can tell "we
    purged this, on this date, under this approval" from "we lost this".

 3. IT NEVER TOUCHES LIVE WORK.
    An open requisition or an active employment is excluded whatever the dates say. A
    retention date is a floor for disposal, not an instruction to dispose -- and a candidate
    whose requisition is still open is not a historical record, however old their CV is.

-- The eligibility rule ---------------------------------------------------------------------
A record is eligible when ALL of these hold:

    it has a `retention_until` AND that date has passed
    it has not already been purged
    its requisition (if it has one) is not Open
    the person it concerns (if an employee) is not still employed

Anything with NO retention date is never eligible. An absent date means nobody computed one,
which is a gap to investigate rather than a licence to delete.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PURGE_APPROVED, AUDIT_PURGE_EXECUTED, AUDIT_PURGE_PROPOSED, COLL_CANDIDATES,
    COLL_EMPLOYEE_PROFILES, COLL_PURGE_BATCHES, COLL_REQUISITIONS, ENTITY_PURGE_BATCH,
    PAYABLE_STATUSES, PURGE_BATCH_FIELD, PURGE_MARKER_FIELD, PURGE_REDACT, PURGE_TARGETS,
    PurgeBatchStatus, ReqClosing,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text

# A single batch is bounded. A proposal listing forty thousand ids is one nobody reads, and
# an approval nobody read is not an approval.
MAX_BATCH_RECORDS = 5000


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "system")


# =============================================================
# Proposing
# =============================================================
async def _open_request_nos(company_id: str) -> set:
    """Requisitions still Open. Nothing attached to one is ever eligible."""
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "closing_status": ReqClosing.OPEN.value},
        {"request_no": 1}).to_list(20000)
    return {r["request_no"] for r in rows if r.get("request_no")}


async def _active_employee_ids(company_id: str) -> set:
    """Candidates who became employees who are still on the payroll.

    Read through PAYABLE_STATUSES rather than a literal "Active", so this and payroll agree
    about what "still employed" means -- somebody on notice or on long leave is still
    employed, and their file is not a historical record.
    """
    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id),
         "employment_status": {"$in": [s.value for s in PAYABLE_STATUSES]}},
        {"employee_code": 1, "uk": 1}).to_list(20000)
    out = set()
    for r in rows:
        for key in ("employee_code", "uk"):
            if r.get(key):
                out.add(str(r[key]))
    return out


async def propose(actor: Optional[dict], company_id: str, *,
                  as_of: str = None, dry_run: bool = True) -> dict:
    """Build a purge proposal. Writes NOTHING except the proposal itself.

    `dry_run=True` (the default, and what the script passes unless told otherwise) does not
    even write the proposal -- it returns the same payload so an operator can look before
    anything is recorded.
    """
    as_of = as_of or _today()
    open_reqs = await _open_request_nos(company_id)
    active = await _active_employee_ids(company_id)

    groups, total = [], 0
    for coll_name, id_field, retention_field, mode, fields in PURGE_TARGETS:
        rows = await get_collection(coll_name).find(
            {"company_id": str(company_id),
             # An absent retention date is NEVER eligible: it means nobody computed one,
             # which is a gap to investigate rather than a licence to delete.
             retention_field: {"$ne": None, "$lte": as_of},
             PURGE_MARKER_FIELD: None},
            {id_field: 1, "request_no": 1, "uk": 1, retention_field: 1}).to_list(20000)

        eligible, skipped_open, skipped_active = [], 0, 0
        for row in rows:
            if row.get("request_no") and row["request_no"] in open_reqs:
                skipped_open += 1
                continue
            if str(row.get("uk") or "") in active:
                skipped_active += 1
                continue
            identifier = row.get(id_field)
            if identifier:
                eligible.append(str(identifier))

        eligible = sorted(set(eligible))[:MAX_BATCH_RECORDS]
        total += len(eligible)
        groups.append({
            "collection": coll_name,
            "id_field": id_field,
            "mode": mode,
            "fields": list(fields),
            "count": len(eligible),
            # THE EXACT IDS. A proposal that says "412 candidates" and does not say which
            # is not something anybody can meaningfully approve.
            "ids": eligible,
            "skipped_open_requisition": skipped_open,
            "skipped_still_employed": skipped_active,
        })

    summary = _summarise(groups, as_of, total)
    payload = {
        "company_id": str(company_id),
        "as_of": as_of,
        "status": PurgeBatchStatus.PROPOSED.value,
        "groups": groups,
        "total_records": total,
        "summary": summary,
        "dry_run": bool(dry_run),
        "proposed_by": str((actor or {}).get("_id") or "") or None,
        "proposed_by_name": _actor_name(actor),
        "proposed_at": datetime.now(timezone.utc),
    }

    if dry_run:
        # Nothing is recorded. A dry run that wrote a row would leave a trail of proposals
        # nobody asked for, and the whole point of the default is that looking is free.
        payload["batch_no"] = None
        return payload

    now = datetime.now(timezone.utc)
    batch_no = await next_business_id("purge_batch", str(company_id), now.year)
    payload.update({"batch_no": batch_no, "created_at": now})
    await get_collection(COLL_PURGE_BATCHES).insert_one(dict(payload))
    await audit(actor, AUDIT_PURGE_PROPOSED, ENTITY_PURGE_BATCH, batch_no,
                f"{total} record(s) eligible as of {as_of}", company_id)
    return _out(payload)


def _summarise(groups: list, as_of: str, total: int) -> str:
    """A sentence a human can read before signing. Pure."""
    if not total:
        return (f"Nothing is eligible for disposal as of {as_of}. Records with no retention "
                f"date, records on an open requisition and records of people still employed "
                f"are never eligible.")
    lines = [f"{total} record(s) eligible for disposal as of {as_of}:"]
    for g in groups:
        if not g["count"]:
            continue
        lines.append(f'  {g["count"]:>5}  {g["collection"]}  ({g["mode"]}: '
                     f'{", ".join(g["fields"][:4])}'
                     f'{"..." if len(g["fields"]) > 4 else ""})')
    held = sum(g["skipped_open_requisition"] for g in groups)
    employed = sum(g["skipped_still_employed"] for g in groups)
    if held:
        lines.append(f"  {held} record(s) held back: their requisition is still open.")
    if employed:
        lines.append(f"  {employed} record(s) held back: the person is still employed.")
    lines.append("Redaction clears the personal fields and keeps the id and the audit "
                 "trail. It is not reversible.")
    return "\n".join(lines)


# =============================================================
# Read
# =============================================================
async def list_batches(company_id: str, *, status: str = None, limit: int = 50) -> dict:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    limit = max(1, min(int(limit or 50), 200))
    rows = await get_collection(COLL_PURGE_BATCHES).find(query).sort(
        "proposed_at", -1).to_list(limit)
    # The ID LISTS are omitted from the listing on purpose: a batch of five thousand ids in
    # every row of a table is a payload nobody wants and a screen nobody can render. The
    # detail endpoint returns them.
    out = []
    for r in rows:
        item = _out(r)
        item["groups"] = [{k: v for k, v in g.items() if k != "ids"}
                          for g in (item.get("groups") or [])]
        out.append(item)
    return {"purge_batches": out, "total": len(out),
            "awaiting_approval": sum(
                1 for r in out if r.get("status") == PurgeBatchStatus.PROPOSED.value)}


async def get_batch(company_id: str, batch_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_PURGE_BATCHES).find_one(
        {"batch_no": batch_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


# =============================================================
# Approving and executing
# =============================================================
async def approve_and_execute(actor: dict, company_id: str, batch_no: str,
                              payload: dict) -> dict:
    """Approve a proposal and carry it out.

    Approval and execution are ONE call on purpose, and it is the opposite of the split this
    module draws everywhere else. The reasoning is specific: an approved-but-unexecuted
    purge is a loaded gun sitting in a collection, and the gap between the two is a window
    in which the eligible set can change underneath the approval somebody signed.

    The signature is what makes this attributable. The ids were fixed when the proposal was
    written, so what executes is exactly what was approved -- a record that became eligible
    since is simply not in this batch.
    """
    coll = get_collection(COLL_PURGE_BATCHES)
    batch = await coll.find_one({"batch_no": batch_no, "company_id": str(company_id)})
    if not batch:
        raise HTTPException(status_code=404, detail="Purge batch not found.")
    if batch.get("status") != PurgeBatchStatus.PROPOSED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{batch_no} is "{batch.get("status")}". Only a proposed batch can be '
                    f"approved; run a fresh proposal if the situation has changed."))

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail=("Type your name to sign this. It destroys personal data permanently, "
                    "and it is not reversible."))

    now = datetime.now(timezone.utc)
    # Compare-and-swap on the proposed state: two approvers clicking at once must not both
    # execute, or every record would be redacted twice and the second pass would record a
    # purge of already-empty fields.
    claimed = await coll.update_one(
        {"batch_no": batch_no, "company_id": str(company_id),
         "status": PurgeBatchStatus.PROPOSED.value},
        {"$set": {"status": PurgeBatchStatus.APPROVED.value,
                  "approved_by": str(actor.get("_id") or ""),
                  "approved_by_name": _actor_name(actor),
                  "approved_at": now, "signature": signature,
                  "approval_remarks": clean_text(payload.get("remarks"), limit=2000)}})
    if getattr(claimed, "matched_count", 0) == 0:
        raise HTTPException(
            status_code=409,
            detail="This batch was decided by someone else. Reload and try again.")

    await audit(actor, AUDIT_PURGE_APPROVED, ENTITY_PURGE_BATCH, batch_no,
                f'{batch.get("total_records")} record(s) authorised for disposal',
                company_id)

    redacted = await _execute(company_id, batch, batch_no, now)

    await coll.update_one(
        {"batch_no": batch_no, "company_id": str(company_id)},
        {"$set": {"status": PurgeBatchStatus.EXECUTED.value,
                  "executed_at": now, "redacted": redacted,
                  "redacted_total": sum(redacted.values())}})
    await audit(actor, AUDIT_PURGE_EXECUTED, ENTITY_PURGE_BATCH, batch_no,
                "; ".join(f"{coll_name}: {n}" for coll_name, n in redacted.items())
                or "nothing to purge", company_id)
    return await get_batch(company_id, batch_no)


async def _execute(company_id: str, batch: dict, batch_no: str,
                   when: datetime) -> dict:
    """Carry out the redaction. Returns {collection: rows touched}.

    The fields are set to None rather than `$unset`. An absent field and a cleared one look
    identical to a reader but not to a query: `{"can_email": None}` still matches a purged
    row, so a later audit can find exactly what was emptied. `$unset` would make the purged
    record indistinguishable from one that never had the field.
    """
    done = {}
    for group in batch.get("groups") or []:
        ids = group.get("ids") or []
        if not ids:
            continue
        cleared = {field: None for field in group.get("fields") or []}
        cleared[PURGE_MARKER_FIELD] = when
        cleared[PURGE_BATCH_FIELD] = batch_no
        if group.get("mode") != PURGE_REDACT:
            # Only redaction is implemented. A hard delete is declared in the vocabulary so
            # a future decision to use it is a reviewable data change -- it is not something
            # this function should quietly start doing because a table said so.
            print(f'[WARN] HRMS purge: unsupported mode {group.get("mode")!r} on '
                  f'{group.get("collection")}; redacting instead.')
        result = await get_collection(group["collection"]).update_many(
            {"company_id": str(company_id), group["id_field"]: {"$in": ids}},
            {"$set": cleared})
        done[group["collection"]] = int(getattr(result, "modified_count", 0) or 0)
    return done
