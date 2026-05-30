"""
Aevus — Notes & Journal API Routes
Operator notes per asset and immutable audit journal.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteCreate(BaseModel):
    asset_id: str
    note: str
    author: str = "Operator"


class NoteUpdate(BaseModel):
    note: str


class JournalCreate(BaseModel):
    asset_id: str
    entry: str
    author: str = "Operator"
    category: str = "general"


# ── Notes ──


@router.post("")
async def create_note(payload: NoteCreate):
    """Add a note to an asset."""
    from src.main import app_state

    note_id = app_state.db.add_note(payload.asset_id, payload.note, payload.author)
    # Also log to journal
    app_state.db.add_journal_entry(
        payload.asset_id,
        f"Note added: {payload.note[:100]}",
        payload.author,
        "note",
    )
    return {"status": "ok", "note_id": note_id}


@router.get("/{asset_id}")
async def list_notes(asset_id: str):
    """List all notes for an asset."""
    from src.main import app_state

    return app_state.db.list_notes(asset_id)


@router.put("/{note_id}")
async def update_note(note_id: int, payload: NoteUpdate):
    """Update an existing note."""
    from src.main import app_state

    ok = app_state.db.update_note(note_id, payload.note)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "ok"}


@router.delete("/{note_id}")
async def delete_note(note_id: int):
    """Delete a note."""
    from src.main import app_state

    ok = app_state.db.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "ok"}


# ── Journal ──

journal_router = APIRouter(prefix="/journal", tags=["journal"])


@journal_router.post("")
async def create_journal_entry(payload: JournalCreate):
    """Add an immutable journal entry."""
    from src.main import app_state

    entry_id = app_state.db.add_journal_entry(payload.asset_id, payload.entry, payload.author, payload.category)
    return {"status": "ok", "entry_id": entry_id}


@journal_router.get("")
async def list_journal(asset_id: str | None = None, category: str | None = None, limit: int = 100):
    """List journal entries with optional filters."""
    from src.main import app_state

    return app_state.db.list_journal(asset_id, category, limit)
