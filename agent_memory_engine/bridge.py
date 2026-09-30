"""Versioned JSON-lines bridge for local application adapters."""
from __future__ import annotations

import base64
import json
import sys
from dataclasses import asdict
from typing import TextIO

from .managed import MemoryEngine, MemoryModel
from .storage.sqlite_secure import SQLiteMemoryStore

PROTOCOL_VERSION = 1


class Bridge:
    def __init__(self, model: MemoryModel | None = None):
        self.model = model
        self.store: SQLiteMemoryStore | None = None
        self.engine: MemoryEngine | None = None

    def handle(self, request: dict) -> dict:
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
                raise ValueError("unsupported protocol version")
            op = request.get("op")
            args = request.get("args", {})
            if not isinstance(args, dict):
                raise ValueError("args must be an object")
            if op == "health":
                result = {"ready": self.engine is not None}
            elif op == "init":
                if self.engine is not None:
                    raise ValueError("bridge already initialized")
                key = base64.b64decode(args["key"], validate=True)
                self.store = SQLiteMemoryStore(args["path"], key)
                self.engine = MemoryEngine(self.store, self.model)
                result = {"ready": True}
            else:
                if self.engine is None or self.store is None:
                    raise RuntimeError("bridge is not initialized")
                if op == "create_candidate":
                    result = asdict(self.engine.create_candidate(**args))
                elif op == "propose":
                    result = [asdict(item) for item in self.engine.propose(**args)]
                elif op == "approve":
                    result = asdict(self.engine.approve(args["id"]))
                elif op == "reject":
                    result = asdict(self.engine.reject(args["id"]))
                elif op == "revise":
                    result = asdict(self.engine.revise(args["id"], args["content"]))
                elif op == "edit_candidate":
                    candidate_id = args["id"]
                    result = asdict(self.engine.edit_candidate(
                        candidate_id, **{k: v for k, v in args.items() if k != "id"}
                    ))
                elif op == "find_exact_duplicates":
                    result = [asdict(item) for item in self.engine.find_exact_duplicates(args["id"])]
                elif op == "retrieve":
                    result = [asdict(item) for item in self.engine.retrieve(**args)]
                elif op == "get":
                    item = self.store.get(args["id"])
                    result = asdict(item) if item else None
                elif op == "list":
                    result = [asdict(item) for item in self.store.list()]
                elif op == "delete":
                    result = {"deleted": self.engine.delete(args["id"])}
                elif op == "import_legacy":
                    result = self.engine.import_legacy(args["path"])
                elif op == "shutdown":
                    self.store.close()
                    self.store = None
                    self.engine = None
                    result = {"ready": False}
                else:
                    raise ValueError("unknown operation")
            return {"version": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result}
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
            return {
                "version": PROTOCOL_VERSION, "id": request_id, "ok": False,
                "error": {"code": type(error).__name__, "message": str(error)},
            }
        except Exception:
            # Database, authentication, and adapter errors must not print content.
            return {
                "version": PROTOCOL_VERSION, "id": request_id, "ok": False,
                "error": {"code": "InternalError", "message": "request failed"},
            }


def serve(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout,
          model: MemoryModel | None = None) -> None:
    bridge = Bridge(model)
    for line in input_stream:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            request = {}
        response = bridge.handle(request)
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()
        if isinstance(request, dict) and request.get("op") == "shutdown" and response["ok"]:
            break


if __name__ == "__main__":
    serve()
