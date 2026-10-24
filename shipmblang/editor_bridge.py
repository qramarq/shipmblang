"""Small JSON bridge between the Ratatui app and the existing notes database."""
from __future__ import annotations

import argparse
from datetime import date
import json
import sys

from .notebook_store import NotebookStore, default_database


def handle(store: NotebookStore, request: dict) -> dict:
    action = request.get("action")
    if action == "list":
        return {"ok": True, "entries": store.list(str(request.get("query", ""))),
                "now": store.now(), "theme": store.get_pref("theme", "dark")}
    if action == "get":
        entry = store.get(str(request.get("id", "")))
        return {"ok": True, "entry": entry}
    if action == "timeline":
        entry_id = str(request.get("id", ""))
        return {"ok": True, "messages": store.messages(entry_id), "now": store.now()}
    if action == "append":
        detail = request.get("detail", "")
        if not isinstance(detail, str):
            detail = json.dumps(detail or {}, ensure_ascii=False)
        parent = request.get("parent_id") or None
        message = store.add_message(
            entry_id=str(request.get("id") or request.get("entry_id") or ""),
            role=str(request.get("role", "user")),
            kind=str(request.get("kind", "message")),
            body=str(request.get("body", "")),
            detail=detail,
            parent_id=parent,
            status=request.get("status"),
        )
        return {"ok": True, "message": message, "entries": store.list("")}
    if action == "read":
        store.mark_read(str(request.get("id", "")))
        return {"ok": True}
    if action == "pin":
        store.set_pinned(str(request.get("id", "")), bool(request.get("pinned")))
        return {"ok": True, "entries": store.list("")}
    if action == "preference":
        key = str(request.get("key", "theme"))
        if "value" in request:
            store.set_pref(key, str(request.get("value", "")))
        return {"ok": True, "value": store.get_pref(key, "")}
    if action == "save":
        document = request.get("document")
        if not isinstance(document, str):
            document = json.dumps(document or {"version": 2, "images": []}, ensure_ascii=False)
        entry_id = store.save(
            entry_id=request.get("id") or None,
            title=str(request.get("title", "Untitled note")),
            entry_date=str(request.get("entry_date") or date.today().isoformat()),
            journal=str(request.get("journal", "")),
            program=str(request.get("program", "")),
            document=document,
        )
        return {"ok": True, "entry": store.get(entry_id)}
    if action == "delete":
        store.delete(str(request.get("id", "")))
        return {"ok": True}
    if action == "backup":
        store.backup(str(request.get("destination", "")))
        return {"ok": True}
    raise ValueError("Unknown editor database action.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(default_database()))
    args = parser.parse_args()
    store = None
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Editor request must be a JSON object.")
        store = NotebookStore(args.database)
        response = handle(store, request)
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    finally:
        if store is not None:
            store.close()
    json.dump(response, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    if not response.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
