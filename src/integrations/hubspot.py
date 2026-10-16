"""
Aevus -- outbound HubSpot event push for the Door 1 access workflow.

Direction is strictly OUTBOUND: the backend pushes access events (requested,
approved, provisioned, first_login) to HubSpot so Norman can work the deal.
HubSpot is never in the login or provisioning path and never grants access.

Behavior contract:

* No-op without ``HUBSPOT_PRIVATE_APP_TOKEN`` (dev/test). Also a no-op, with a
  warning, if the pipeline stage is not configured: we refuse to create a deal
  without an explicit pipeline AND stage so it can never fall into the default
  pipeline.
* Best effort and non-blocking: every failure is caught and logged; this module
  never raises into the caller, so a HubSpot outage cannot fail provisioning.
  Callers schedule it as a background task.
* Idempotent: contacts upsert by email, companies dedupe by domain, and an
  existing deal for the contact in the target pipeline is reused, not duplicated.
* Free-mail domains never create or attach a Company (that would pile every Gmail
  prospect onto a "gmail.com" company record).
* Only standard HubSpot properties are written (the API rejects unknown ones).
  The event itself is recorded as a Note on the deal and contact.

Required private-app scopes (read-only on the CRM beyond what we create):
  crm.objects.contacts.read / .write
  crm.objects.companies.read / .write
  crm.objects.deals.read / .write
Notes are created via the CRM notes object under the same contact/company/deal
write scopes; verify in a HubSpot sandbox when the token is minted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger()

HUBSPOT_API = "https://api.hubapi.com"
EVENTS = ("requested", "approved", "provisioned", "first_login")

# HubSpot-defined association type ids.
_ASSOC_DEAL_TO_CONTACT = 3
_ASSOC_DEAL_TO_COMPANY = 5
_ASSOC_NOTE_TO_CONTACT = 202
_ASSOC_NOTE_TO_DEAL = 214


@dataclass(frozen=True)
class AccessEvent:
    """One access-workflow event to mirror into HubSpot."""

    event: str
    request_id: str
    email: str
    name: str = ""
    company: str = ""
    phone: str = ""
    job_title: str = ""
    domain_class: str = "business"  # "business" | "free_mail"
    detail: str = ""


def hubspot_enabled() -> bool:
    """True when a private-app token is configured."""
    return bool(settings.hubspot_private_app_token)


def _assoc(to_id: str, type_id: int) -> dict[str, Any]:
    return {"to": {"id": to_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(None, 1)
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


async def _request(client: httpx.AsyncClient, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    """One HubSpot call with a single retry on 429/5xx. Raises on final failure."""
    last: httpx.Response | None = None
    for attempt in range(2):
        last = await client.request(method, path, json=body)
        if last.status_code not in (429, 500, 502, 503, 504):
            break
        if attempt == 0:
            import asyncio

            await asyncio.sleep(1.0)
    assert last is not None
    last.raise_for_status()
    return last.json() if last.content else {}


async def _upsert_contact(client: httpx.AsyncClient, ev: AccessEvent) -> str:
    first, last = _split_name(ev.name)
    props = {"email": ev.email, "firstname": first, "lastname": last, "phone": ev.phone, "jobtitle": ev.job_title}
    if ev.company:
        props["company"] = ev.company
    props = {k: v for k, v in props.items() if v}
    res = await _request(
        client,
        "POST",
        "/crm/v3/objects/contacts/batch/upsert",
        {"inputs": [{"idProperty": "email", "id": ev.email, "properties": props}]},
    )
    return str(res["results"][0]["id"])


async def _find_or_create_company(client: httpx.AsyncClient, ev: AccessEvent) -> str | None:
    """Dedupe by email domain. Returns None for free-mail (no company is attached)."""
    if ev.domain_class != "business":
        return None
    domain = ev.email.rsplit("@", 1)[1]
    found = await _request(
        client,
        "POST",
        "/crm/v3/objects/companies/search",
        {"filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}], "limit": 1},
    )
    if found.get("results"):
        return str(found["results"][0]["id"])  # existing record (e.g. Norman's base): never overwrite it
    created = await _request(
        client,
        "POST",
        "/crm/v3/objects/companies",
        {"properties": {"name": ev.company or domain, "domain": domain}},
    )
    return str(created["id"])


async def _find_or_create_deal(
    client: httpx.AsyncClient, ev: AccessEvent, contact_id: str, company_id: str | None
) -> str:
    pipeline = settings.hubspot_pipeline_id
    found = await _request(
        client,
        "POST",
        "/crm/v3/objects/deals/search",
        {
            "filterGroups": [
                {
                    "filters": [
                        {"propertyName": "pipeline", "operator": "EQ", "value": pipeline},
                        {"propertyName": "associations.contact", "operator": "EQ", "value": contact_id},
                    ]
                }
            ],
            "limit": 1,
        },
    )
    if found.get("results"):
        return str(found["results"][0]["id"])  # attach to the existing deal; Norman owns stage movement
    associations = [_assoc(contact_id, _ASSOC_DEAL_TO_CONTACT)]
    if company_id:
        associations.append(_assoc(company_id, _ASSOC_DEAL_TO_COMPANY))
    created = await _request(
        client,
        "POST",
        "/crm/v3/objects/deals",
        {
            "properties": {
                "dealname": f"{ev.company or ev.email.rsplit('@', 1)[1]} - Aevus Comms demo access",
                # Always explicit: never rely on the account's default pipeline.
                "pipeline": pipeline,
                "dealstage": settings.hubspot_dealstage_id,
                "hubspot_owner_id": settings.hubspot_owner_id,
            },
            "associations": associations,
        },
    )
    return str(created["id"])


async def _add_note(client: httpx.AsyncClient, ev: AccessEvent, contact_id: str, deal_id: str) -> None:
    body = f"Aevus access event: {ev.event} (request {ev.request_id}, {ev.domain_class} domain)."
    if ev.detail:
        body += f" {ev.detail}"
    await _request(
        client,
        "POST",
        "/crm/v3/objects/notes",
        {
            "properties": {"hs_note_body": body, "hs_timestamp": int(time.time() * 1000)},
            "associations": [_assoc(contact_id, _ASSOC_NOTE_TO_CONTACT), _assoc(deal_id, _ASSOC_NOTE_TO_DEAL)],
        },
    )


async def push_access_event(ev: AccessEvent) -> bool:
    """Mirror one access event into HubSpot. Never raises. True only if fully pushed."""
    if not hubspot_enabled():
        return False  # no token: dev/test no-op
    if ev.event not in EVENTS:
        logger.warning("hubspot_push_skipped", reason="unknown_event", access_event=ev.event)
        return False
    if not settings.hubspot_dealstage_id or not settings.hubspot_pipeline_id or not settings.hubspot_owner_id:
        logger.warning("hubspot_push_skipped", reason="pipeline_stage_or_owner_unset", access_event=ev.event)
        return False
    try:
        async with httpx.AsyncClient(
            base_url=HUBSPOT_API,
            headers={"Authorization": f"Bearer {settings.hubspot_private_app_token}"},
            timeout=settings.hubspot_timeout_seconds,
        ) as client:
            contact_id = await _upsert_contact(client, ev)
            company_id = await _find_or_create_company(client, ev)
            deal_id = await _find_or_create_deal(client, ev, contact_id, company_id)
            await _add_note(client, ev, contact_id, deal_id)
        logger.info("hubspot_push_ok", access_event=ev.event, request_id=ev.request_id)
        return True
    except Exception as exc:  # noqa: BLE001 - best effort by design; must never break provisioning
        # Log the exception type only: HTTP errors can echo request bodies (PII).
        logger.warning("hubspot_push_failed", access_event=ev.event, request_id=ev.request_id, error=type(exc).__name__)
        return False
