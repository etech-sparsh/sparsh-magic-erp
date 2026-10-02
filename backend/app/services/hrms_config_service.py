"""HRMS ▸ per-company configuration (Phase INT-5, spec §42).

Sparsh Magic runs several entities under one group. Until this phase the module was
multi-company for its DATA -- every collection keyed on `company_id`, ids sequenced per
company, salary bands and communication templates already per company -- but not for its
RULES. The SLA targets, retention periods, probation duration, reminder tiers and score
bands were module constants, so a second entity would have shared one hard-coded rule set
with the first. `COLL_SETTINGS` had been declared and read by nothing since Phase 1.

-- An OVERLAY, not a replacement -----------------------------------------------------------
`config_for()` returns the module defaults with a company's overrides laid on top. Every
default is read from the constant that already shipped, so **a company with no settings row
behaves exactly as it did before this phase** -- no migration, nothing to backfill, and the
pre-INT-5 answer is reproduced key for key. A company overrides only what it disagrees with.

-- What is stored is what somebody CHOSE ----------------------------------------------------
Values equal to the default are stored anyway rather than pruned. Pruning would be tidier
and wrong: a company that deliberately set retention to 3 years would silently move if the
module default ever changed, and a compliance number nobody re-approved must not drift.
`reset_config()` is how a company goes back to following the default -- an explicit act.

-- No caching, deliberately ------------------------------------------------------------------
There is no cache in front of this and no TTL to reason about, because the module has no
caching layer anywhere else and a stale rule is worse than an extra indexed read. Callers
that resolve config inside a LOOP resolve it ONCE and pass the dict down (`sla_for`,
`sweep_open_breaches` and the scheduler all take an optional `config`), so the read count is
per request, not per record.

-- What is NOT configurable ------------------------------------------------------------------
No setting turns off the budget gate, the reference check, the scorecard approval or the
telephonic screen. Those are the controls the SOP is made of, and a deviation from one goes
through the exception log -- where it is attributable -- rather than through a settings
screen, where it would be silent. See the note above `CONFIG_SPEC` for the three keys that
were considered and deliberately left out.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CONFIG_RESET, AUDIT_CONFIG_UPDATED, COLL_SETTINGS,
    CONFIG_EMPLOYMENT_DOCS, CONFIG_HONOUR_HOLIDAYS, CONFIG_ONBOARD_DOC_TYPES,
    CONFIG_KIND_FLAG, CONFIG_KIND_FLAG_MAP, CONFIG_KIND_FLOAT_MAP,
    CONFIG_KIND_INT_LIST, CONFIG_KIND_INT_MAP,
    CONFIG_PROBATION_MONTHS, CONFIG_PROBATION_REMINDERS, CONFIG_RETENTION_YEARS,
    CONFIG_SCORE_BANDS, CONFIG_SLA_TARGET_DAYS, CONFIG_SPEC, ENTITY_CONFIG,
    config_spec, default_config,
)
from app.services.hrms_audit_service import audit


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────
async def raw_overrides(company_id: str) -> dict:
    """Only what this company has actually set. Empty when it follows every default."""
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    if not doc:
        return {}
    return {spec["key"]: doc[spec["key"]] for spec in CONFIG_SPEC if spec["key"] in doc}


async def config_for(company_id: str) -> dict:
    """The rules in force for this company: defaults, with its overrides laid on top.

    Maps are merged PER NAME, not replaced wholesale. A company that overrode the offer SLA
    keeps the shipped targets for the other three milestones -- replacing the whole map
    would mean overriding one number silently dropped the rest, and a missing SLA target
    reads as "no target" rather than as the omission it was.

    Lists are replaced whole, because a list IS the setting: merging reminder tiers would
    make removing one impossible.
    """
    resolved = default_config()
    stored = await raw_overrides(company_id)
    for spec in CONFIG_SPEC:
        key = spec["key"]
        if key not in stored:
            continue
        value = stored[key]
        if spec["kind"] in (CONFIG_KIND_INT_MAP, CONFIG_KIND_FLOAT_MAP):
            if isinstance(value, dict):
                resolved[key].update(value)
        elif spec["kind"] == CONFIG_KIND_FLAG:
            resolved[key] = bool(value)
        elif spec["kind"] == CONFIG_KIND_FLAG_MAP:
            # REPLACES rather than merges. Every other map has a closed set of names, so a
            # merge can only change values; this one is open, and a company that deletes a
            # document type has to see it disappear rather than come back from the default.
            if isinstance(value, dict):
                resolved[key] = {str(k): bool(v) for k, v in value.items()}
        else:
            resolved[key] = list(value)
    return resolved


async def describe(company_id: str) -> dict:
    """The settings screen's payload: the table, the resolved values, and what is overridden.

    `overridden` is returned per name rather than per key, so the UI can mark the one number
    a company changed instead of flagging the whole group as "customised".
    """
    resolved = await config_for(company_id)
    stored = await raw_overrides(company_id)
    settings = []
    for spec in CONFIG_SPEC:
        key = spec["key"]
        mine = stored.get(key)
        if spec["kind"] in (CONFIG_KIND_INT_LIST, CONFIG_KIND_FLAG,
                            CONFIG_KIND_FLAG_MAP):
            overridden = [] if mine is None else ["*"]
        else:
            overridden = sorted(mine) if isinstance(mine, dict) else []
        settings.append({
            "key": key,
            "label": spec["label"],
            "kind": spec["kind"],
            "note": spec.get("note"),
            "min": spec.get("min"),
            "max": spec.get("max"),
            "names": spec.get("names"),
            # Which names may be set to null (Phase INT-10: the optional Hold band). The
            # screen renders an explicit Off control for these and nothing else.
            "optional_names": spec.get("optional_names") or [],
            "max_entries": spec.get("max_entries"),
            "default": spec["default"](),
            "value": resolved[key],
            "overridden": overridden,
        })
    return {"company_id": str(company_id), "settings": settings,
            "follows_defaults": not stored}


# ─────────────────────────────────────────────────────────────
# Convenience readers
# ─────────────────────────────────────────────────────────────
# Each takes EITHER a company id or an already-resolved config, so a caller inside a loop can
# resolve once and a caller handling one record can stay a one-liner.
async def _resolved(company_or_config) -> dict:
    if isinstance(company_or_config, dict):
        return company_or_config
    return await config_for(company_or_config)


async def sla_target_days(company_or_config) -> dict:
    return (await _resolved(company_or_config))[CONFIG_SLA_TARGET_DAYS]


async def retention_years_for(company_or_config, record_type: str) -> int:
    """Years to keep `record_type`, for this company.

    Falls back to the module default for a record type the config does not name, so adding a
    new record type in a later phase cannot KeyError against a settings row written before
    it existed.
    """
    years = (await _resolved(company_or_config))[CONFIG_RETENTION_YEARS]
    if record_type in years:
        return int(years[record_type])
    return int(default_config()[CONFIG_RETENTION_YEARS][record_type])


async def probation_bounds(company_or_config) -> tuple:
    """(default, min, max) months."""
    months = (await _resolved(company_or_config))[CONFIG_PROBATION_MONTHS]
    return int(months["default"]), int(months["min"]), int(months["max"])


async def probation_reminder_tiers(company_or_config) -> list:
    return list((await _resolved(company_or_config))[CONFIG_PROBATION_REMINDERS])


async def score_bands_for(company_or_config) -> dict:
    return (await _resolved(company_or_config))[CONFIG_SCORE_BANDS]


async def onboarding_doc_types(company_or_config) -> dict:
    """This company's joining-document catalogue as {label: required?}."""
    return dict((await _resolved(company_or_config))[CONFIG_ONBOARD_DOC_TYPES])


async def employment_documents(company_or_config) -> dict:
    """The documents a new joiner signs with their appointment letter, {label: required?}."""
    return dict((await _resolved(company_or_config))[CONFIG_EMPLOYMENT_DOCS])


async def honours_holidays(company_or_config) -> bool:
    """Whether SLA maths skips this company's holidays as well as weekends."""
    return bool((await _resolved(company_or_config))[CONFIG_HONOUR_HOLIDAYS])


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────
def _number(value, spec: dict, *, label: str):
    kind = spec["kind"]
    # Checked before the cast: bool is a subclass of int, so `True` would otherwise sail
    # through as 1 and set an SLA target from a checkbox somebody sent by mistake.
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    unit = "number" if kind == CONFIG_KIND_FLOAT_MAP else "whole number"
    try:
        parsed = float(value) if kind == CONFIG_KIND_FLOAT_MAP else int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a {unit}.")
    low, high = spec["min"], spec["max"]
    if not low <= parsed <= high:
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be between {low:g} and {high:g}. Got {parsed:g}.")
    return parsed


def _validate_map(key: str, spec: dict, value) -> dict:
    if not isinstance(value, dict) or not value:
        example = spec["names"][0]
        raise HTTPException(
            status_code=422,
            detail=(f'"{key}" expects an object of named values, for example '
                    f'{example} = {spec["default"]()[example]!r}.'))
    permitted = set(spec["names"])
    unknown = sorted(set(value) - permitted)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(f'"{key}" has no setting called {", ".join(unknown)}. '
                    f'Valid: {", ".join(spec["names"])}.'))
    # ── Phase INT-10 ── a name the spec marks optional may be switched OFF with null. Only
    # those names: a null anywhere else is a mistake, not a choice, and is refused.
    optional = set(spec.get("optional_names") or [])
    out = {}
    for name, raw in value.items():
        if raw is None and name in optional:
            out[name] = None
            continue
        if raw is None:
            raise HTTPException(
                status_code=422,
                detail=f'"{key}.{name}" cannot be switched off. Only '
                       f'{", ".join(sorted(optional)) or "nothing"} may be set to null.')
        out[name] = _number(raw, spec, label=f'"{key}.{name}"')
    return out


def _validate_flag_map(key: str, value) -> dict:
    """An OPEN {label: required?} map — the caller names the entries.

    Stored as given rather than merged with the default, so removing an entry removes it.
    """
    if not isinstance(value, dict) or not value:
        raise HTTPException(
            status_code=422,
            detail=f'"{key}" expects at least one entry, as {{"PAN card": true}}.')
    if len(value) > 30:
        raise HTTPException(
            status_code=422,
            detail=f'"{key}" allows at most 30 entries. Each one is an upload task a new '
                   f"hire has to complete.")
    out = {}
    for name, required in value.items():
        label = str(name).strip()
        if not label or len(label) > 120:
            raise HTTPException(
                status_code=422,
                detail=f'"{key}" has a document name that is empty or longer than 120 '
                       f"characters.")
        if not isinstance(required, bool):
            raise HTTPException(
                status_code=422,
                detail=f'"{key}.{label}" is required or not. Send true or false.')
        out[label] = required
    return out


def _validate_list(key: str, spec: dict, value) -> list:
    if not isinstance(value, (list, tuple)) or not value:
        raise HTTPException(
            status_code=422,
            detail=f'"{key}" expects a non-empty list, for example {spec["default"]()}.')
    limit = spec.get("max_entries")
    if limit and len(value) > limit:
        raise HTTPException(
            status_code=422,
            detail=(f'"{key}" allows at most {limit} entries. Each one is a separate email '
                    f"to the same person about the same review."))
    parsed = [_number(v, spec, label=f'"{key}"') for v in value]
    if parsed != sorted(set(parsed), reverse=True):
        raise HTTPException(
            status_code=422,
            detail=(f'"{key}" must be in descending order with no repeats. Got {parsed}. '
                    f"A tier that repeats or climbs cannot fire once each."))
    return parsed


def _assert_descending(key: str, merged: dict, order: list) -> None:
    """Band floors must strictly descend in the order the table names them.

    Checked against the MERGED result, not the payload: overriding one floor can invert the
    order against floors the company never touched, and a "Consider" band that starts above
    "Strong" makes every score land in the wrong one.
    """
    # A switched-off band (None) takes no part in the ordering.
    values = [merged[name] for name in order if merged.get(name) is not None]
    if values != sorted(set(values), reverse=True):
        pairs = ", ".join(f"{n} {merged[n]:g}" for n in order
                          if merged.get(n) is not None)
        raise HTTPException(
            status_code=422,
            detail=(f'"{key}" floors must descend in the order {" > ".join(order)}. '
                    f"With this change they would be: {pairs}."))


def _assert_probation_bounds(merged: dict) -> None:
    low, default, high = merged["min"], merged["default"], merged["max"]
    if not low <= default <= high:
        raise HTTPException(
            status_code=422,
            detail=(f"Probation min ({low}) <= default ({default}) <= max ({high}) does not "
                    f"hold. A default outside its own bounds is a duration nobody can "
                    f"actually open a review with."))


def validate(company_config: dict, payload: dict) -> dict:
    """Validate a PATCH against the config already in force. Returns the values to store.

    Cross-field rules are checked against the MERGED result rather than the payload, so
    changing one number cannot leave the group inconsistent -- the same rule the reference
    and telephonic services follow when an edit flips an outcome.
    """
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="No settings to update.")

    unknown = sorted(set(payload) - {s["key"] for s in CONFIG_SPEC})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(f'Unknown setting(s): {", ".join(unknown)}. '
                    f'Valid: {", ".join(s["key"] for s in CONFIG_SPEC)}.'))

    out = {}
    for key, value in payload.items():
        spec = config_spec(key)
        if spec["kind"] == CONFIG_KIND_FLAG:
            if not isinstance(value, bool):
                raise HTTPException(
                    status_code=422,
                    detail=f'"{key}" is on or off. Send true or false.')
            out[key] = value
            continue

        if spec["kind"] == CONFIG_KIND_INT_LIST:
            out[key] = _validate_list(key, spec, value)
            continue

        if spec["kind"] == CONFIG_KIND_FLAG_MAP:
            out[key] = _validate_flag_map(key, value)
            continue

        clean = _validate_map(key, spec, value)
        merged = {**company_config[key], **clean}
        if key == CONFIG_SCORE_BANDS:
            _assert_descending(key, merged, spec["names"])
        elif key == CONFIG_PROBATION_MONTHS:
            _assert_probation_bounds(merged)
        # Stored MERGED, not just the changed names: the row is meant to read as "the rules
        # this company has adopted", and a row holding one number out of four cannot be
        # reviewed without also holding the defaults in your head.
        out[key] = merged
    return out


# ─────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────
def _describe_change(before: dict, after: dict) -> str:
    """What actually changed, for the audit line. Only the values that moved."""
    parts = []
    for key, value in after.items():
        old = before.get(key)
        if isinstance(value, dict):
            for name, new in value.items():
                if not isinstance(old, dict) or old.get(name) != new:
                    parts.append(f"{key}.{name}: {(old or {}).get(name)!r} -> {new!r}")
        elif old != value:
            parts.append(f"{key}: {old!r} -> {value!r}")
    return "; ".join(parts) or "no effective change"


async def update_config(actor: dict, company_id: str, payload: dict) -> dict:
    """Apply an override. Validated against what is already in force."""
    before = await config_for(company_id)
    clean = validate(before, payload)

    now = datetime.now(timezone.utc)
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {**clean,
                  "updated_at": now,
                  "updated_by": str((actor or {}).get("_id") or "") or None,
                  "updated_by_name": (actor or {}).get("full_name")
                  or (actor or {}).get("email")},
         "$setOnInsert": {"company_id": str(company_id), "created_at": now}},
        upsert=True)

    await audit(actor, AUDIT_CONFIG_UPDATED, ENTITY_CONFIG, str(company_id),
                _describe_change(before, clean), company_id)
    return await describe(company_id)


async def reset_config(actor: dict, company_id: str, keys: Optional[list] = None) -> dict:
    """Stop overriding some or all settings, and follow the module default again.

    An explicit act, because storing a value equal to the default is NOT the same as
    following it: the stored one stays where it was put if the default ever moves, and this
    is how a company says it no longer wants that.
    """
    valid = {s["key"] for s in CONFIG_SPEC}
    if keys:
        unknown = sorted(set(keys) - valid)
        if unknown:
            raise HTTPException(
                status_code=422, detail=f'Unknown setting(s): {", ".join(unknown)}.')
        targets = list(keys)
    else:
        targets = sorted(valid)

    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    if not doc:
        # Already following every default. Not an error -- the caller asked for a state the
        # company is in, and refusing would make "reset" fail exactly when it is a no-op.
        return await describe(company_id)

    held = [k for k in targets if k in doc]
    if held:
        await get_collection(COLL_SETTINGS).update_one(
            {"company_id": str(company_id)},
            {"$unset": {k: "" for k in held},
             "$set": {"updated_at": datetime.now(timezone.utc),
                      "updated_by": str((actor or {}).get("_id") or "") or None}})
    await audit(actor, AUDIT_CONFIG_RESET, ENTITY_CONFIG, str(company_id),
                ", ".join(held) or "nothing was overridden", company_id)
    return await describe(company_id)
