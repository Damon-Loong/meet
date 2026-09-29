"""Tenant-authenticated administrative memory views and corrections."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from summary.core.config import AuthorizedTenant, SettingsDeps
from summary.core.meeting_memory import allowed
from summary.core.personal_memory import PersonalMemory, Status
from summary.core.security import verify_tenant_api_key_v2

router = APIRouter(prefix="/personal-memory", tags=["personal-memory"])


def store(
    settings: SettingsDeps,
    tenant: Annotated[AuthorizedTenant, Depends(verify_tenant_api_key_v2)],
):
    """Reject foreign tenants and disabled features before opening any database."""
    if not settings.personal_memory_enabled or not allowed(settings, tenant.id):
        raise HTTPException(403, "Personal memory is not enabled for this tenant")
    return PersonalMemory(
        settings.meeting_memory_state_file, tenant.id, settings.document_timezone
    )


Store = Annotated[PersonalMemory, Depends(store)]


class PersonInput(BaseModel):
    """Explicit administrative alias/account mapping, never automatic fuzzy merge."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    account: str = Field(default="", max_length=200)
    person: str = Field(default="", max_length=64)


class Correction(BaseModel):
    """Full replacement fields plus revision and reason for an auditable correction."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(gt=0)
    person: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=600)
    status: Status
    deadline: str = Field(max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class Merge(BaseModel):
    """Require an explicit source, destination and administrative reason."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/people/merge")
def merge(body: Merge, memory: Store):
    """Combine explicitly confirmed duplicate people while retaining task evidence."""
    try:
        memory.merge(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "merged"}


@router.get("/people/{person}/history")
def identity_history(person: str, memory: Store):
    """Inspect administrative identity edits within this tenant."""
    with memory.db() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM pm_identity_events WHERE tenant=? AND person=? "
                "ORDER BY seq",
                (memory.tenant, person),
            )
        ]


@router.get("")
def snapshot(memory: Store):
    """List team profiles and current records, including unresolved proposals."""
    return {"people": memory.people(), "items": memory.items()}


@router.post("/people")
def person(body: PersonInput, memory: Store):
    """Create a profile or explicitly replace its display name and aliases."""
    if any(not a.strip() or len(a) > 100 for a in body.aliases):
        raise HTTPException(422, "Invalid alias")
    try:
        return {"id": memory.add_person(**body.model_dump())}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/items/{item}")
def correct(item: str, body: Correction, memory: Store):
    """Correct ownership/content or explicitly confirm completion with audit history."""
    try:
        memory.correct(item, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(404, "Unknown item") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "updated"}


@router.get("/items/{item}/history")
def history(item: str, memory: Store):
    """Show original quotes and all human corrections without cross-tenant leakage."""
    result = memory.audit(item)
    if not result:
        raise HTTPException(404, "Unknown item")
    return result
