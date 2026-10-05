"""Exclusive durable request reservations for the study's single $5 ceiling."""

from __future__ import annotations

import asyncio
import base64
import copy
import ctypes
import hashlib
import json
import math
import os
import time
from pathlib import Path

CEILING = 5.0
MAX_OUTPUT = 4096
MAX_INPUT_BOUND = 262000
MODELS = {
    "luna": {"id": "gpt-6-luna", "effort": "none", "input": 0.10, "cached": 0.01, "write": 0.125, "output": 0.50},
    "nano5": {
        "id": "gpt-5-nano-2025-08-07",
        "effort": "minimal",
        "input": 0.05,
        "cached": 0.005,
        "write": 0.05,
        "output": 0.40,
    },
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _durable_replace(source, destination):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH.
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def save(path, value, *, exclusive=False):
    """Atomically replace mutable records; immutable artifacts use exclusive creation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _durable_replace(temporary, path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def token_count(text):
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(text, disallowed_special=()))


def credential():
    """Unprotect only the designated local DPAPI secret; never serialize errors/key."""
    if os.name != "nt":
        raise RuntimeError("The study credential requires Windows DPAPI.")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    encrypted = base64.b64decode((Path.home() / ".pasr-secrets" / "openai.dpapi").read_text().strip(), validate=True)
    buffer = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
    source, result = Blob(len(encrypted), buffer), Blob()
    unprotect = ctypes.windll.crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(Blob),
    ]
    unprotect.restype = ctypes.c_int
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    if not unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("DPAPI secret decryption failed.")
    try:
        key = ctypes.string_at(result.pbData, result.cbData).decode("utf-8").strip()
        if not key:
            raise RuntimeError("DPAPI secret is empty.")
        return key
    finally:
        ctypes.memset(result.pbData, 0, result.cbData)
        free(result.pbData)


class BudgetHalt(RuntimeError):
    def __init__(self, reason, charge=None, response=None):
        super().__init__(reason)
        self.reason, self.charge, self.response = reason, charge, response


class Budget:
    """One writer/process and one request at a time, including reservation and pacing.

    A crash leaves the reservation charged and blocks all subsequent paid calls.
    A recognized timeout retains its full reservation, fails that trajectory, and
    allows distinct requests that fit the remaining ceiling. No request is retried.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "spend_ledger.json"
        self._lock = asyncio.Lock()
        self._broken = False
        self._file = (self.root / "spend_ledger.lock").open("a+b")
        try:
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"\0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.record = (
                load(self.path)
                if self.path.exists()
                else {"ceiling_usd": CEILING, "requests": [], "recent_requests": {}}
            )
            if self.record.get("ceiling_usd") != CEILING:
                raise BudgetHalt("ledger_ceiling_mismatch")
            self._check()
        except BaseException:
            self._file.close()
            raise

    def _persist(self):
        try:
            save(self.path, self.record)
        except BaseException:
            self._broken = True
            raise

    def _check(self):
        if self._broken:
            raise BudgetHalt("ledger_persistence_failed")
        identities = [row["identity"] for row in self.record["requests"]]
        if len(set(identities)) != len(identities):
            raise BudgetHalt("duplicate_ledger_identity")
        for row in self.record["requests"]:
            charge, reserve = row["budget_charge_usd"], row["reserved_usd"]
            if not (math.isfinite(charge) and math.isfinite(reserve) and 0 <= charge <= reserve):
                raise BudgetHalt("ledger_charge_violation")
            if row["status"] != "complete" and charge != reserve:
                raise BudgetHalt("unresolved_reservation_was_reduced")
        if any(row["status"] not in {"complete", "timeout_reserved"} for row in self.record["requests"]):
            raise BudgetHalt("unresolved_usage_no_further_spending")
        if sum(row["budget_charge_usd"] for row in self.record["requests"]) > CEILING:
            raise BudgetHalt("global_ceiling_reached")

    def close(self):
        self._file.close()

    async def call(self, client, model, kwargs, identity):
        async with self._lock:
            self._check()
            if any(row["identity"] == identity for row in self.record["requests"]):
                raise BudgetHalt("request_identity_already_used")
            encoded = json.dumps(kwargs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            estimated_input = token_count(encoded)
            input_bound = 2 * estimated_input + 8192
            if input_bound > MAX_INPUT_BOUND:
                raise BudgetHalt("input_reservation_limit")
            reserve = (input_bound * max(model["input"], model["write"]) + MAX_OUTPUT * model["output"]) / 1e6
            spent = sum(row["budget_charge_usd"] for row in self.record["requests"])
            if spent + reserve > CEILING:
                raise BudgetHalt("global_ceiling_reached")
            rate_tokens = estimated_input + MAX_OUTPUT
            recent = self.record["recent_requests"].setdefault(model["id"], [])
            while True:
                now = time.time()
                recent[:] = [entry for entry in recent if now - entry["at"] < 60]
                if not recent or sum(entry["tokens"] for entry in recent) + rate_tokens <= 150000:
                    break
                await asyncio.sleep(max(0, 60.1 - (now - recent[0]["at"])))
            entry = {
                "identity": identity,
                "model": model["id"],
                "status": "reserved",
                "input_token_bound": input_bound,
                "reserved_usd": reserve,
                "budget_charge_usd": reserve,
                "published_rate_cost_usd": None,
                "cost_is_exact_published_rate": False,
                "usage": None,
                "request_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                "started_at": time.time(),
            }
            recent.append({"at": time.time(), "tokens": rate_tokens})
            self.record["requests"].append(entry)
            number = len(self.record["requests"]) - 1
            # Persist the full request before sending. No credential exists in kwargs.
            save(self.root / "requests" / f"{number:06d}.json", kwargs, exclusive=True)
            self._persist()
            try:
                response = await client.responses.create(**kwargs)
            except BaseException as exc:
                timed_out = isinstance(exc, TimeoutError) or type(exc).__name__ == "APITimeoutError"
                entry.update(
                    status="timeout_reserved" if timed_out else "failed_usage_unknown",
                    error_type=type(exc).__name__,
                    status_code=getattr(exc, "status_code", None),
                )
                self._persist()
                if not isinstance(exc, Exception):
                    raise
                raise BudgetHalt(
                    "timeout_usage_unknown" if timed_out else "provider_error_usage_unknown", copy.deepcopy(entry)
                ) from None
            raw = response.model_dump(mode="json")
            # Reservation remains unresolved if a disk failure prevents response persistence.
            save(self.root / "responses" / f"{number:06d}.json", raw, exclusive=True)
            usage = raw.get("usage")
            entry.update(response_id=raw.get("id"), service_tier=raw.get("service_tier"), usage=usage)
            if not isinstance(usage, dict):
                entry["status"] = "usage_missing"
                self._persist()
                raise BudgetHalt("usage_missing", copy.deepcopy(entry), response)
            details = usage.get("input_tokens_details") or {}
            inputs, outputs = usage.get("input_tokens"), usage.get("output_tokens")
            cached, writes = details.get("cached_tokens", 0), details.get("cache_write_tokens", 0)
            valid = all(type(value) is int and value >= 0 for value in (inputs, outputs, cached, writes))
            if not valid or not (cached + writes <= inputs <= input_bound and outputs <= MAX_OUTPUT):
                entry["status"] = "usage_bound_violation"
                self._persist()
                raise BudgetHalt("usage_bound_violation", copy.deepcopy(entry), response)
            known_writes = model["id"] != "gpt-6-luna" or "cache_write_tokens" in details
            tier_known = raw.get("service_tier") in (None, "default", "standard")
            if not tier_known:
                entry["status"] = "unpriced_service_tier"
                self._persist()
                raise BudgetHalt("unpriced_service_tier", copy.deepcopy(entry), response)
            input_cost = (
                (inputs - cached - writes) * model["input"] + writes * model["write"]
                if known_writes
                else (inputs - cached) * max(model["input"], model["write"])
            )
            cost = (input_cost + cached * model["cached"] + outputs * model["output"]) / 1e6
            if cost > reserve + 1e-12:
                entry["status"] = "price_bound_violation"
                self._persist()
                raise BudgetHalt("price_bound_violation", copy.deepcopy(entry), response)
            entry.update(
                status="complete",
                budget_charge_usd=cost,
                cost_is_exact_published_rate=known_writes,
                published_rate_cost_usd=cost if known_writes else None,
                cached_tokens=cached,
                cache_write_tokens=writes if known_writes else None,
            )
            self._persist()
            return response, copy.deepcopy(entry)
