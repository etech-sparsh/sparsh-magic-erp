"""Company-level HRMS access control — the module's ONE authorization surface.

Mirrors app/utils/tpms_access.py in shape and defaults: HRMS is **opt-in per company**,
so a missing `hrms_enabled` flag means OFF and a company stays dark until an Admin /
Super Admin switches it on.

Three layers use this:
  • ensure_hrms_enabled()      — router guard; client-side users of a disabled company
                                 are refused. Internal staff always pass so they can
                                 administer and support across clients.
  • hrms_enabled_company_ids() — data-layer filter; disabled companies are excluded from
                                 every list, dashboard, report and aggregation.
  • hrms_tenant_company_ids()  — where HRMS records actually live. The fallback scope for
                                 internal staff when NO company has the toggle on, so
                                 administering a switched-off module is still possible.
  • can() / require_cap()      — the capability check every feature gate resolves through.

HRMS hires for Sparsh Magic only. The ERP's client companies are never party to it, so
there is no client-side scope anywhere in this module: a caller is either internal staff
or a user of the in-house tenant, and `company_id` is the only boundary.

── Why a capability check and not role strings ──────────────────────────────────
The source HRMS accumulated four overlapping authorization mechanisms with three
different "admin" role sets, a helper (`canAccessHrms`) whose name no longer matched
what it did, an accepted-but-never-created "MD" role, and a granted-but-unread
permission (BACKEND_ANALYSIS §7.3, Risk #13). Its own analysis calls this the highest
risk of "a gate being added in the wrong place".

Here there is exactly one path: resolve the caller to an HrmsRole, resolve that role to a
capability set, and ask `can(user, Cap.X)`. Adding a capability is a one-line change in
models/hrms.py; there is nowhere else for a gate to hide.
"""
from typing import Optional, Set

from bson import ObjectId
from fastapi import Depends, HTTPException

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.hrms import (
    CLIENT_ROLES, GOVERNANCE_TO_HRMS, INTERNAL_OWNER_ROLES, INTERNAL_STAFF_ROLES,
    ROLE_CAPABILITIES, TOGGLE_ROLES, Cap, CLIENT_TRACK_CAPS, CLIENT_DECISION_CAPS,
    CLIENT_OWNED_CAPS, CLIENT_TRACK_FLAG, HrmsRole,
)

MODULE_DISABLED_MESSAGE = (
    "The HRMS module is not enabled for your company. Please contact your administrator."
)
NO_ACCESS_MESSAGE = "You do not have access to the HRMS module."

# ─────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────
def is_internal_user(user: dict) -> bool:
    """Sparsh internal (staff collection) rather than a client-side user.

    Prefers the `_source_collection` stamp set by auth_controller.get_user_from_token,
    falls back to `tag`, then to the role — the same precedence auth_controller uses, so
    the two never disagree.
    """
    if not user:
        return False
    src = user.get("_source_collection")
    if src == "staff":
        return True
    if src == "learners":
        return False
    tag = user.get("tag")
    if tag == "staff":
        return True
    if tag == "learner":
        return False
    role = (user.get("role") or "").lower()
    return role in INTERNAL_OWNER_ROLES or role in INTERNAL_STAFF_ROLES


def is_client_side_user(user: dict) -> bool:
    return bool(user) and not is_internal_user(user)


def hrms_role(user: dict) -> Optional[HrmsRole]:
    """Resolve an ERP user to their HRMS role, or None if they have none.

    Internal:  superadmin              → ADMIN     (full owner)
               governance_role MD      → MD
               governance_role HR      → HR
               governance_role FINANCE → FINANCE   (the budget authority)
               governance_role HOD     → MANAGER   (hiring manager)
               no governance_role      → INTERNAL  (operator + support, reads only)
    Tenant:    clientadmin             → MD        (top of the company's ladder)
               governance_role as above, anything else → EMPLOYEE (self-service only)

    -- Why internal staff read `governance_role` too -----------------------------------
    HRMS hires for Sparsh Magic, and Sparsh's own people ARE staff accounts. Mapping every
    one of them to INTERNAL (reads only) left the approval chain unusable: INTERNAL holds
    no REQUISITION_REVIEW_HR, no REQUISITION_APPROVE_BUDGET and no SCORECARD_APPROVE, so
    only a superadmin could act -- and a superadmin could perform every step alone, which
    is the opposite of the separation of duties the SOP is built on. Worse, SCORECARD_APPROVE
    is gated on the MANAGER rung specifically, a rung no staff account could ever reach, so
    no requisition could be approved and nothing could be posted at all.

    Reading the same `governance_role` the tenant ladder already uses fixes that without a
    second mechanism: HR verifies, Management/Finance approves the budget, the hiring
    manager approves the scorecard. Staff with no governance role keep exactly the support
    access they had.
    """
    if not user:
        return None
    role = (user.get("role") or "").strip().lower()

    if is_internal_user(user):
        if role in INTERNAL_OWNER_ROLES:
            return HrmsRole.ADMIN
        governance = (user.get("governance_role") or "").strip().upper()
        return GOVERNANCE_TO_HRMS.get(governance, HrmsRole.INTERNAL)

    if role == "clientadmin":
        return HrmsRole.MD
    if role in CLIENT_ROLES:
        governance = (user.get("governance_role") or "").strip().upper()
        return GOVERNANCE_TO_HRMS.get(governance, HrmsRole.EMPLOYEE)
    return None


# ─────────────────────────────────────────────────────────────
# Company module toggle
# ─────────────────────────────────────────────────────────────
async def is_hrms_enabled(company_id: str) -> bool:
    """Whether HRMS is available to a company.

    TWO conditions, both required:

      * `hrms_enabled` — the per-company opt-in switch. A missing flag means OFF.
      * `is_internal`  — this is the ONE company the ERP is operated in-house by.

    HRMS is an internal recruitment and HR system, not a module sold to the ERP's client
    companies. `hrms_enabled` alone used to be the whole test, which meant a client
    company was one toggle away from the entire module -- including payroll and personal
    data. Requiring `is_internal` as well makes that impossible rather than merely
    unlikely: flipping the toggle on a client company now grants nothing, so a mistaken
    or malicious enable is inert.

    This is THE gate. `ensure_hrms_enabled` below is the only caller that matters, and it
    guards the entire `/api/hrms` router as a dependency, so there is no HRMS endpoint
    that can be reached without passing through here.
    """
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("hrms_enabled", False)) and bool(company.get("is_internal", False))


async def client_track_company(company_id: str) -> bool:
    """Whether this company may reach HRMS as a CLIENT, not as the operator.

    The second door, deliberately separate from `is_hrms_enabled`. A client company needs
    the same per-company opt-in, and must NOT be the in-house tenant -- the two are mutually
    exclusive by construction, so a company can never be both operator and client.

    Passing this admits the caller to the module. What they may then do is decided entirely
    by CLIENT_TRACK_CAPS, which starts empty.
    """
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return (bool(company.get("hrms_enabled", False))
            and not bool(company.get("is_internal", False)))


async def ensure_hrms_enabled(current_user: dict, company_id: str = None) -> None:
    """Raise 403 when a client-side user's company has HRMS switched off.

    Internal staff always pass: they administer HRMS across clients, and the data layer
    (hrms_enabled_company_ids) already excludes disabled companies from what they see.
    `company_id` defaults to the caller's own company, which is the case that matters —
    a client user can only ever act within it.
    """
    if is_internal_user(current_user):
        return

    # A client-side caller is judged on THEIR OWN company, never on one they name.
    #
    # This used to read `company_id or current_user["company_id"]`, honouring a
    # `?company_id=` from the query string. That let any client-company user pass the
    # in-house company's id and clear the gate -- the data layer still pinned them to
    # their own company via `scope_company_id`, so they saw nothing, but they got 200s
    # from a module that is supposed to answer them 403. The entitlement is a property of
    # who they are, not of the company they ask about, so the parameter is ignored here.
    target = str(current_user.get("company_id") or "")
    if await is_hrms_enabled(target):
        return

    # -- Client Hiring ------------------------------------------------------------------
    # A client company with the module switched on is admitted to the CLIENT TRACK ONLY.
    # The flag is stamped here, on the request's own user object, and `capabilities_for`
    # narrows everything they hold to CLIENT_TRACK_CAPS from this point on.
    #
    # Stamped on the way through so it is set for every admitted client request, and never
    # for internal staff, who returned above.
    if await client_track_company(target):
        current_user[CLIENT_TRACK_FLAG] = True
        return

    # Their own company has HRMS off, and that is the end of it.
    raise HTTPException(status_code=403, detail=MODULE_DISABLED_MESSAGE)


async def internal_company_id() -> Optional[str]:
    """The ONE company this ERP is operated in-house by, or None if it is not set up yet.

    `is_internal` is not settable through any route (see models/company.py), so this is a
    fact about the deployment rather than something a user can flip. Callers use it to ask
    "am I looking at Sparsh Magic's own tenant, or a client's".
    """
    try:
        doc = await get_collection("companies").find_one({"is_internal": True}, {"_id": 1})
    except Exception as e:
        print(f"[WARN] HRMS internal-company lookup failed: {e}")
        return None
    return str(doc["_id"]) if doc else None


async def tenant_identity_source(company_id: str) -> tuple:
    """Which identity collection holds a tenant's people, and how to select them.

    Sparsh Magic's OWN staff live in `staff` and carry NO `company_id`: they are the
    platform's operators, not members of any company in the Companies list. Every other
    company's people are its `learners`, keyed by `company_id`.

    Anything asking "is this user a member of this company" -- an assignee, a reporting
    manager, an interviewer, a panel or committee member -- must resolve through here.
    A hard-coded `learners` lookup answers "no" for every one of Sparsh's own employees,
    which is exactly the bug this replaced.
    """
    if company_id and str(company_id) == (await internal_company_id() or ""):
        return "staff", {}
    return "learners", {"company_id": str(company_id)}


async def tenant_member(company_id: str, user_id, projection: dict = None) -> Optional[dict]:
    """One user of this tenant by id, or None. See `tenant_identity_source`."""
    from bson.errors import InvalidId
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    source, base = await tenant_identity_source(company_id)
    return await get_collection(source).find_one({**base, "_id": oid}, projection)


async def hrms_enabled_company_ids() -> set:
    """Ids of every company HRMS is available to — the data-layer filter.

    Mirrors `is_hrms_enabled` exactly: both `hrms_enabled` AND `is_internal`. Aggregations
    intersect against this, so a client company can never appear in an HRMS list,
    dashboard, report, filter dropdown or rollup even if its toggle was somehow set.

    In practice this resolves to at most one id. It stays a set because every caller
    already treats it as one, and because a set of one is the honest shape for "whichever
    companies qualify" rather than a special case that reads as a bug.
    """
    docs = await get_collection("companies").find(
        {"hrms_enabled": True, "is_internal": True}, {"_id": 1}
    ).to_list(5000)
    return {str(d["_id"]) for d in docs}


# Collections whose rows mean "the HRMS module has been used in this company". Deliberately
# a short list of the things only a TENANT owns -- a client company is named inside a
# requisition's `client_id`, never as the `company_id` of one, so this cannot mistake a
# client for the operator.
HRMS_TENANT_COLLECTIONS = ("hrms_requisitions", "hrms_employee_profiles", "hrms_settings")


async def hrms_tenant_company_ids() -> set:
    """Companies that actually hold HRMS records, whether or not the module is switched on.

    Used for ONE thing: giving Sparsh internal staff somewhere to stand when no company has
    the toggle enabled.

    `ensure_hrms_enabled` has always let internal staff through -- they administer the
    module and support it across clients, so the toggle was never meant to gate them. But
    the company SELECTOR listed only enabled companies, so with everything switched off they
    landed inside a module with nothing to select and every endpoint answering
    "company_id is required". The toggle governs whether a company's OWN users can reach
    HRMS; it was never supposed to lock out the people who administer it.

    Reading the data rather than a flag is deliberate. There is no "this is the operator"
    marker on a company, and inventing one would be a second source of truth to keep in
    step. Where the requisitions and employee records actually live is not an opinion.

    Fails closed: an empty set on any error, so a broken read narrows access and never
    widens it.
    """
    found: set = set()
    for name in HRMS_TENANT_COLLECTIONS:
        try:
            for cid in await get_collection(name).distinct("company_id"):
                if cid:
                    found.add(str(cid))
        except Exception as e:
            print(f"[WARN] HRMS tenant lookup failed on {name}: {e}")
    return found


def can_toggle_module(user: dict) -> bool:
    """Only Admin / Super Admin may switch HRMS on or off for a company. Matches the
    TPMS toggle rule exactly."""
    return bool(user) and (user.get("role") or "").lower() in TOGGLE_ROLES


# ─────────────────────────────────────────────────────────────
# Capabilities
# ─────────────────────────────────────────────────────────────
def capabilities_for(user: dict) -> Set[Cap]:
    """Every capability this user holds.

    ADMIN holds everything implicitly — deliberately resolved as "all of Cap" rather than
    a maintained list, so a capability added in a later phase can never accidentally lock
    the module owner out of their own system.

    """
    role = hrms_role(user)
    if role is None:
        return set()
    if role == HrmsRole.ADMIN:
        caps = set(Cap)
    else:
        caps = set(ROLE_CAPABILITIES.get(role, set()))

    # -- Client Hiring ------------------------------------------------------------------
    # A caller from a client company holds EXACTLY the client-track set, and their ladder
    # role inside their own company is discarded rather than intersected.
    #
    # Intersecting was the first attempt and it was wrong twice over. It could only ever
    # take capabilities away, so a client could never be GRANTED the client-track ones at
    # all; and it made what a client could do depend on an internal ladder that has no
    # meaning for them -- a client's "MD" is not Sparsh's MD, and mapping one onto the
    # other is the category error this whole separation exists to avoid.
    #
    # Replacing is also the stronger guarantee. There is exactly one set of capabilities a
    # client-side caller can hold, it is declared in one place, and it cannot grow because
    # somebody widened an internal role. ADMIN is replaced too: a client company's own
    # owner is still a client company's user, and "owner of my tenant" must never mean
    # "owner of Sparsh Magic's recruitment system".
    if user.get(CLIENT_TRACK_FLAG):
        return set(CLIENT_TRACK_CAPS)

    # -- The five client-owned decisions ------------------------------------------------
    # Everything above decides what this Sparsh caller may DO. This last step decides what
    # they may not DECIDE, and it is deliberately the last thing that happens.
    #
    # PRO-fit's value rests on five decisions being genuinely the client's: the scorecard
    # approval, the CV verdict, the selection after interview, the offer release and the
    # joining confirmation. Leaving them out of ROLE_CAPABILITIES was not enough, because
    # ADMIN resolves to "every member of Cap" a few lines above -- so a Sparsh superadmin
    # was offered "Approve" on a scorecard sitting with the client, and could release the
    # client's own employment contract.
    #
    # ADMINISTRATIVE ACCESS AND DECISION AUTHORITY ARE DIFFERENT THINGS. A superadmin keeps
    # every read, every write, every review and every share -- they administer, support and
    # troubleshoot the whole track exactly as before. They simply cannot cast the client's
    # five votes. Subtracting here rather than at a route means a new endpoint, a widened
    # role or a future admin branch cannot reacquire them by accident, and a direct API
    # call fails the same way the button's absence implies.
    #
    # CLIENT_OWNED_CAPS goes the same way for the same reason, but for the client's own
    # WORK rather than their decisions: on PRO-fit the requirement originates with the
    # client (SOP section 7 step 1), so raising and amending their Need Mapping and
    # Manpower Requisition forms is theirs. Sparsh's move on a requisition is the
    # feasibility review, which is a different capability and stays with Sparsh. A
    # supplier who could raise the client's requirement could also set its salary range --
    # the figure that supplier is later measured against, and the one the client is asked
    # to approve deviations from.
    return caps - CLIENT_DECISION_CAPS - CLIENT_OWNED_CAPS


def can(user: dict, capability: Cap) -> bool:
    """THE authorization question. Every HRMS gate — route, service or UI hint — resolves
    through this and nothing else."""
    return capability in capabilities_for(user)


def require_cap(capability: Cap):
    """FastAPI dependency factory enforcing one capability.

    Usage:  @router.get("/x", dependencies=[Depends(require_cap(Cap.AUDIT_READ))])
       or:  async def handler(user: dict = Depends(require_cap(Cap.AUDIT_READ)))
    Returns the user so the second form works.
    """
    async def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if not can(current_user, capability):
            raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)
        return current_user
    return _checker


# ─────────────────────────────────────────────────────────────
# Scoping
# ─────────────────────────────────────────────────────────────
def scope_company_id(user: dict, requested: str = None) -> Optional[str]:
    """The company a request should operate on.

    A client-side user is pinned to their own company — a requested id is ignored rather
    than honoured, so a crafted query string can never reach another tenant. Internal
    staff may target any company (or all, when `requested` is None).
    """
    if is_internal_user(user):
        return requested or None
    return str(user.get("company_id") or "") or None


def company_filter(user: dict, requested: str = None) -> dict:
    """A ready-made Mongo filter fragment applying tenant scoping.

    Returns `{}` for an internal user with no specific company (they see everything the
    data layer allows), otherwise `{"company_id": <scoped id>}`.
    """
    scoped = scope_company_id(user, requested)
    return {"company_id": scoped} if scoped else {}
