#!/usr/bin/env python3
"""Evidence-driven deletion audit runner. Uses only participant-facing dataset files."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

DATASET = Path("dataset")
DELETE_CATS = {"USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY", "SUPPORT_ATTACHMENT", "USER_EXPORT", "MARKETING_PROFILE"}
REDACT_CATS = {"SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG", "ACCOUNT_TOMBSTONE"}
ANON_CATS = {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"}
FIND_ORDER = {"REPORT_REMAINING_RECORD": 0, "REPORT_EXPOSED_PII": 1, "REPORT_ACTIVE_DATA_FLOW": 2, "REPORT_RESTORE_RISK": 3}
REMED_ORDER = {"DISABLE_DATA_FLOW": 0, "BLOCK_RESTORE": 1, "DELETE_RECORD": 2, "REDACT_RECORD": 3, "ANONYMIZE_RECORD": 4}
VERIFY_ORDER = {"VERIFY_RECORD_ABSENT": 0, "VERIFY_RECORD_PRESENT": 1, "VERIFY_RECORD_REDACTED": 2, "VERIFY_RECORD_ANONYMIZED": 3, "VERIFY_DATA_FLOW_DISABLED": 4, "VERIFY_RESTORE_BLOCKED": 5}

POSITIVE_INTENT = re.compile(
    r"(delet\w*|eras\w*|remov\w*|remove the profile|remove personal data|"
    r"close my account|close this account|close the account|closed account|account closure|account.*close|"
    r"permanent account|permanently close|account.*(?:deleted|removed|erased|closed)|"
    r"wipe my account|clean .* personal details|clean .* personal data|"
    r"(?:account|profile).{0,80}\\b(?:gone|not found|no longer exists|fully removed)\\b|"
    r"eliminaci[oó]n|eliminar mi cuenta|suprimir mi cuenta|"
    r"exclus[aã]o|excluir minha conta|elimina[cç][aã]o|"
    r"suppression définitive|suppression d[eû]finitive|supprimer mon compte|"
    r"삭제|계정 삭제|削除|アカウント.*削除|删除|注销账户)",
    re.IGNORECASE,
)
NON_DELETE_ONLY = re.compile(
    r"\b(access request|request access|access my data|data export|export my data|download my data|"
    r"correct my|correction request|update my (email|phone|address|profile)|change my (email|phone|address)|"
    r"opt.?out|unsubscribe|stop marketing|marketing preference|cancel (my )?subscription|"
    r"rectification|portability request|exportaci[oó]n|acceso a mis datos)\b",
    re.IGNORECASE,
)

def classify_request_text(text: str) -> bool:
    """Return true only when the message contains an affirmative deletion intent."""
    value = str(text or "").strip()
    if not value:
        return False
    if not POSITIVE_INTENT.search(value):
        return False
    if NON_DELETE_ONLY.search(value) and not re.search(r"\b(delete|deletion|erase|erasure|remove my account|close my account|eliminaci[oó]n|exclus[aã]o|삭제|削除|删除)\b", value, re.I):
        return False
    return True

def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def norm_email(value: Any) -> str:
    return str(value or "").strip().casefold()

def norm_phone(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))

def flatten_strings(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from flatten_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from flatten_strings(v)
    elif value is not None:
        yield ("", str(value))

def category_name(*parts: Any) -> str:
    text = " ".join(str(x or "") for x in parts).casefold()
    aliases = [
        (("account_tombstone", "deleted_customer_reference", "tombstone"), "ACCOUNT_TOMBSTONE"),
        (("security_audit", "security_audit_log", "security_audit_record", "audit_record"), "SECURITY_AUDIT_LOG"),
        (("legal_hold", "legal_retention"), "LEGAL_HOLD_RECORD"),
        (("backup", "restore"), "BACKUP_ARCHIVE"),
        (("data_flow", "connector", "subscription"), "DATA_FLOW"),
        (("support_attachment", "attachment", "object_storage"), "SUPPORT_ATTACHMENT"),
        (("support_message", "support_record", "support_ticket", "conversation", "support"), "SUPPORT_MESSAGE"),
        (("email_delivery", "delivery_log", "notification_delivery"), "EMAIL_DELIVERY_LOG"),
        (("analytics_profile", "analytics_platform", "customer_analytics"), "ANALYTICS_PROFILE"),
        (("product_telemetry", "telemetry"), "PRODUCT_TELEMETRY"),
        (("user_export", "customer_export", "export_service", "export"), "USER_EXPORT"),
        (("marketing_profile", "marketing_platform", "marketing"), "MARKETING_PROFILE"),
        (("secondary_identifier", "identity_identifier"), "SECONDARY_IDENTIFIER"),
        (("search_index", "search_document", "search_service", "search"), "SEARCH_INDEX_ENTRY"),
        (("cache_entry", "cache_service", "cache"), "CACHE_ENTRY"),
        (("user_profile", "customer_profile", "customer_profiles", "account_service", "account"), "USER_PROFILE"),
    ]
    explicit = re.findall(r"\b(USER_PROFILE|SECONDARY_IDENTIFIER|SEARCH_INDEX_ENTRY|CACHE_ENTRY|SUPPORT_MESSAGE|SUPPORT_ATTACHMENT|ANALYTICS_PROFILE|PRODUCT_TELEMETRY|USER_EXPORT|MARKETING_PROFILE|EMAIL_DELIVERY_LOG|SECURITY_AUDIT_LOG|LEGAL_HOLD_RECORD|BACKUP_ARCHIVE|ACCOUNT_TOMBSTONE|DATA_FLOW)\b", text.upper())
    if explicit:
        return explicit[-1]
    for keys, result in aliases:
        if any(k in text for k in keys):
            return result
    return ""

def category_for_resource(resource: Any, fallback: str) -> str:
    prefix = str(resource or "").casefold().split("_", 1)[0]
    by_prefix = {
        "account": "USER_PROFILE", "identity": "SECONDARY_IDENTIFIER",
        "search": "SEARCH_INDEX_ENTRY", "cache": "CACHE_ENTRY",
        "support": "SUPPORT_ATTACHMENT" if fallback == "SUPPORT_ATTACHMENT" else "SUPPORT_MESSAGE",
        "attachment": "SUPPORT_ATTACHMENT",
        "object": "SUPPORT_ATTACHMENT", "analytics": "ANALYTICS_PROFILE",
        "telemetry": "PRODUCT_TELEMETRY", "export": "USER_EXPORT",
        "marketing": "MARKETING_PROFILE", "email": "EMAIL_DELIVERY_LOG",
        "audit": "SECURITY_AUDIT_LOG", "legal": "LEGAL_HOLD_RECORD",
        "backup": "BACKUP_ARCHIVE", "tombstone": "ACCOUNT_TOMBSTONE",
        "data": "DATA_FLOW",
    }
    return by_prefix.get(prefix, fallback)

def default_system(category: str) -> str:
    return {
        "USER_PROFILE": "account_service", "SECONDARY_IDENTIFIER": "identity_service",
        "SEARCH_INDEX_ENTRY": "search_service", "CACHE_ENTRY": "cache_service",
        "SUPPORT_MESSAGE": "support_platform", "SUPPORT_ATTACHMENT": "object_storage",
        "ANALYTICS_PROFILE": "analytics_platform", "PRODUCT_TELEMETRY": "analytics_platform",
        "USER_EXPORT": "export_service", "MARKETING_PROFILE": "marketing_platform",
        "EMAIL_DELIVERY_LOG": "email_delivery_service", "SECURITY_AUDIT_LOG": "security_service",
        "LEGAL_HOLD_RECORD": "legal_service", "BACKUP_ARCHIVE": "backup_service",
        "ACCOUNT_TOMBSTONE": "identity_service", "DATA_FLOW": "integration_service",
    }.get(category, "unknown")

def system_name(*values: Any, category: str = "") -> str:
    allowed = {
        "account_service", "identity_service", "search_service", "cache_service", "support_platform",
        "object_storage", "analytics_platform", "export_service", "marketing_platform",
        "email_delivery_service", "notification_service", "security_service", "legal_service",
        "backup_service", "integration_service", "replication_service",
    }
    for value in values:
        text = str(value or "").casefold()
        for system in sorted(allowed, key=len, reverse=True):
            if system in text:
                return system
    return default_system(category)

def direct_pii(obj: Any) -> bool:
    pii_keys = {"name", "full_name", "display_name", "requester_name", "email", "owner_email", "customer_email",
                "requester_email", "phone", "requester_phone", "email_hash"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).casefold() in pii_keys and v not in (None, "", "null"):
                return True
            if direct_pii(v):
                return True
    elif isinstance(obj, list):
        return any(direct_pii(x) for x in obj)
    return False

def attributable(obj: Any) -> bool:
    keys = {"user_id", "customer_reference", "subject_reference", "user_ref", "customer_id"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).casefold() in keys and v not in (None, "", "null"):
                return True
            if attributable(v):
                return True
    elif isinstance(obj, list):
        return any(attributable(x) for x in obj)
    return False

def find_resource_id(obj: Any) -> str:
    if isinstance(obj, dict):
        preferred = ("resource_id", "record_id", "object_id", "id", "source_id")
        for key in preferred:
            val = obj.get(key)
            if isinstance(val, (str, int)) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*_\d+", str(val)):
                return str(val)
        for v in obj.values():
            found = find_resource_id(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_resource_id(v)
            if found:
                return found
    return ""

def status_from(obj: Any, category: str) -> str:
    if not isinstance(obj, dict):
        return "PRESENT"
    values = {str(k).casefold(): v for k, v in obj.items()}
    try:
        if int(values.get("status_code", 0) or 0) == 404:
            return "ABSENT"
    except (TypeError, ValueError):
        pass
    if "profile" in values and values["profile"] is None:
        return "ABSENT"
    for key in ("result", "state", "status", "account_status", "record_status", "deletion_state", "readback_result"):
        val = str(values.get(key, "") or "").upper()
        if val in {"NOT_FOUND", "ABSENT", "DELETED", "MISSING", "ROWS=0"}:
            return "ABSENT"
        if val in {"REDACTED", "ANONYMIZED", "ANONYMIZED", "DISABLED", "BLOCKED", "ACTIVE", "IDENTIFIABLE", "FOUND", "PRESENT"}:
            return val
    if "enabled" in values:
        return "ACTIVE" if str(values["enabled"]).casefold() in {"true", "1", "yes"} else "DISABLED"
    if "restore_allowed" in values:
        return "ACTIVE" if str(values["restore_allowed"]).casefold() in {"true", "1", "yes"} else "BLOCKED"
    if "restore_access" in values:
        return "ACTIVE" if str(values["restore_access"]).casefold() in {"true", "1", "yes", "allowed"} else "BLOCKED"
    if category in {"DATA_FLOW", "BACKUP_ARCHIVE"}:
        return "PRESENT"
    return "PRESENT"

def infer_line_category(line: str, service: str = "") -> str:
    return category_name(line, service)

def record_identity_match(obj: Any, aliases: set[str], uid: str) -> bool:
    values = [x.casefold() for _, x in flatten_strings(obj)]
    for alias in aliases:
        if len(alias) >= 4:
            if alias.isdigit():
                if any(re.sub(r"\D", "", v) == alias for v in values):
                    return True
            elif any(v == alias or re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", v, re.I) for v in values):
                return True
    return bool(uid and any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(uid)}(?![A-Za-z0-9_])", v, re.I) for v in values))

def sql_records(path: Path, evidence_id: str, captured_at: dt.datetime,
                coverage: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    scope_systems: set[str] = set()
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(path.read_text(encoding="utf-8", errors="replace"))
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "snapshot_scope" in tables:
            scope_systems.update(str(r[0]) for r in con.execute("SELECT origin_system FROM snapshot_scope"))
        for table in tables:
            if table == "snapshot_scope":
                continue
            table_category = category_name(table)
            if table_category:
                scope_systems.add(default_system(table_category))
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
            if not cols:
                continue
            for row in con.execute(f'SELECT * FROM "{table}"'):
                obj = dict(zip(cols, row))
                if obj.get("record_json"):
                    try:
                        payload = json.loads(obj["record_json"])
                        obj.update(payload)
                    except (TypeError, json.JSONDecodeError):
                        pass
                sys_value = obj.get("origin_system") or obj.get("system") or obj.get("data_store") or ""
                cat = category_name(obj.get("record_type"), obj.get("collection_name"), table, sys_value)
                resource = find_resource_id(obj)
                cat = category_for_resource(resource, cat)
                if resource and cat:
                    found.append({"system": system_name(sys_value, category=cat), "resource_id": resource,
                                  "category": cat, "state": status_from(obj, cat), "record": obj,
                                  "evidence_id": evidence_id, "captured_at": captured_at})
    except sqlite3.Error:
        # Keep parsing other evidence if a vendor extension prevents SQLite execution.
        pass
    finally:
        con.close()
    if coverage is not None:
        for system in sorted(scope_systems):
            coverage.append({"system": system, "evidence_id": evidence_id, "captured_at": captured_at})
    return found

def json_records(obj: Any, evidence_id: str, captured_at: dt.datetime) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    def walk(node: Any, inherited_system: str = "", inherited_collection: str = "") -> None:
        if isinstance(node, dict):
            sys_value = node.get("data_store") or node.get("system") or node.get("origin_system") or inherited_system
            collection = node.get("collection") or node.get("collection_name") or node.get("table") or inherited_collection
            category = category_name(node.get("record_type"), node.get("category"), collection, sys_value)
            resource = node.get("resource_id") or node.get("record_id") or ""
            category = category_for_resource(resource, category)
            # Container objects are not records; nested payloads such as search documents remain valid.
            has_records = any(k in node for k in ("records", "snapshots"))
            if resource and category and not has_records:
                found.append({"system": system_name(sys_value, category=category), "resource_id": resource,
                              "category": category, "state": status_from(node, category), "record": node,
                              "evidence_id": evidence_id, "captured_at": captured_at})
            for key, value in node.items():
                if isinstance(value, list):
                    for child in value:
                        walk(child, str(sys_value or ""), str(collection or key))
                elif isinstance(value, dict):
                    walk(value, str(sys_value or ""), str(collection or key))
        elif isinstance(node, list):
            for child in node:
                walk(child, inherited_system, inherited_collection)
    walk(obj)
    return found

def text_records(text: str, evidence_id: str, captured_at: dt.datetime) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        # Structured service readbacks use a resource id and explicit result fields.
        m = re.search(r"\bresource_id\s*=\s*['\"]?([A-Za-z][A-Za-z0-9_-]*_\d+)", line, re.I)
        if m:
            resource = m.group(1)
            service_m = re.search(r"\bservice=([A-Za-z0-9_]+)", line, re.I)
            service = service_m.group(1) if service_m else ""
            cat = category_for_resource(resource, infer_line_category(line, service))
            if cat:
                fields: dict[str, Any] = {"raw": line}
                for key in ("rows", "http_status", "result", "enabled", "restore_allowed", "restore_access",
                            "customer_reference", "subject_reference", "email", "customer_email",
                            "requester_email", "email_hash", "phone", "requester_phone"):
                    mm = re.search(rf"\b{key}=([^ \t]+)", line, re.I)
                    if mm:
                        fields[key] = mm.group(1).strip("\"'")
                if re.search(r"\brows=0\b|http_status=404|result=(?:miss|not_found)\b", line, re.I):
                    fields["result"] = "NOT_FOUND"
                elif re.search(r"\bresult=hit\b|\brows=1\b|http_status=200", line, re.I):
                    fields["result"] = "FOUND"
                found.append({"system": system_name(service, category=cat), "resource_id": resource,
                              "category": cat, "state": status_from(fields, cat), "record": fields,
                              "evidence_id": evidence_id, "captured_at": captured_at})
            continue
        # Handover and readback reports use pipe-delimited, human-readable rows.
        if "|" in line:
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 5:
                cat = infer_line_category(" ".join(parts[2:5]), parts[1])
                ids = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*_\d+\b", parts[2])
                if cat and ids:
                    state = parts[4].upper()
                    fields = {"raw": line, "subject_reference": parts[-1]}
                    if state in {"NOT_FOUND", "ABSENT"}:
                        state = "ABSENT"
                    elif state not in {"REDACTED", "ANONYMIZED", "ACTIVE", "DISABLED", "BLOCKED", "IDENTIFIABLE", "FOUND"}:
                        state = "PRESENT"
                    found.append({"system": system_name(parts[1], category=cat), "resource_id": ids[0],
                                  "category": cat, "state": state, "record": fields,
                                  "evidence_id": evidence_id, "captured_at": captured_at})
    return found

def load_evidence(dataset: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]]]:
    manifest = read_csv(dataset / "evidence_files.csv")
    all_records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for entry in manifest:
        p = dataset / entry["file_path"]
        if not p.exists():
            continue
        cap = parse_time(entry.get("captured_at"))
        if cap is None:
            continue
        eid = entry["file_id"]
        suffix = p.suffix.casefold()
        if suffix == ".json":
            try:
                all_records.extend(json_records(json.loads(p.read_text(encoding="utf-8-sig", errors="replace")), eid, cap))
            except (json.JSONDecodeError, OSError):
                pass
        elif suffix == ".sql":
            all_records.extend(sql_records(p, eid, cap, coverage))
        elif suffix in {".log", ".txt"}:
            try:
                all_records.extend(text_records(p.read_text(encoding="utf-8-sig", errors="replace"), eid, cap))
            except OSError:
                pass
        elif suffix == ".pdf":
            try:
                txt = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, check=False).stdout
                if not txt.strip():
                    from pypdf import PdfReader
                    txt = "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
                all_records.extend(text_records(txt, eid, cap))
            except Exception:
                pass
        elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            try:
                from PIL import Image
                import pytesseract
                txt = pytesseract.image_to_string(Image.open(p))
                all_records.extend(text_records(txt, eid, cap))
            except Exception:
                pass
    return all_records, manifest, coverage

def identity_index(dataset: Path) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], dict[str, str], list[dict[str, str]]]:
    users = read_csv(dataset / "user_identities.csv")
    aliases: dict[str, set[str]] = defaultdict(set)
    user_by_email: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    for u in users:
        uid = u["user_id"]
        details[uid] = u
        for key in ("name", "email", "phone", "email_hash"):
            val = u.get(key, "")
            if not val:
                continue
            alias = norm_email(val) if key == "email" else norm_phone(val) if key == "phone" else str(val).casefold()
            aliases[uid].add(alias)
            if key == "email":
                user_by_email[alias] = uid
    audit_rows = read_csv(dataset / "user_audit_log.csv")
    for a in audit_rows:
        uid = a["user_id"]
        aliases.setdefault(uid, set())
        if a.get("event_time") and uid in details:
            field = a.get("field_name", "").casefold()
            for key in ("old_value", "new_value"):
                val = a.get(key, "")
                if not val:
                    continue
                alias = norm_email(val) if "email" in field else norm_phone(val) if "phone" in field else val.casefold()
                aliases[uid].add(alias)
                if "email" in field:
                    user_by_email[alias] = uid
    return details, aliases | defaultdict(set), user_by_email, audit_rows

def resource_for_case(req: dict[str, str], uid: str, details: dict[str, Any], aliases_by_user: dict[str, set[str]],
                      evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = parse_time(req.get("audit_at"))
    aliases = aliases_by_user.get(uid, set())
    chosen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in evidence:
        if cutoff and item["captured_at"] > cutoff:
            continue
        if not record_identity_match(item["record"], aliases, uid):
            continue
        key = (item["system"], item["resource_id"], item["category"])
        prev = chosen.get(key)
        if prev is None or item["captured_at"] > prev["captured_at"]:
            chosen[key] = item
        elif item["captured_at"] == prev["captured_at"] and item["state"] != "PRESENT" and prev["state"] == "PRESENT":
            chosen[key] = item
    return list(chosen.values())

def item_has_pii(item: dict[str, Any]) -> bool:
    if direct_pii(item["record"]):
        return True
    raw = str(item["record"].get("raw", ""))
    return "@" in raw or bool(re.search(r"\+\d[\d ()-]{6,}", raw))

def item_attributable(item: dict[str, Any], uid: str) -> bool:
    rec = item["record"]
    if not isinstance(rec, dict):
        return False
    if rec.get("_identity_match"):
        return True
    for key in ("user_id", "customer_reference", "subject_reference", "user_ref", "customer_id"):
        val = rec.get(key)
        if val not in (None, "", "null"):
            return True
    raw = str(rec.get("raw", ""))
    return bool(re.search(rf"\b{re.escape(uid)}\b", raw))

def item_retained(item: dict[str, Any], audit_at: str) -> bool:
    record = item["record"]
    until = None
    if isinstance(record, dict):
        for key in ("retention_until", "retain_until", "hold_until"):
            if record.get(key):
                until = parse_time(record.get(key))
                break
    audit = parse_time(audit_at)
    return item["state"] != "ABSENT" and (until is None or audit is None or until >= audit)

def support_shared_context(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    shared_keys = {"shared_customer", "other_customer_reference", "other_customer_id",
                   "shared_order_context", "conversation_must_be_retained", "retain_conversation",
                   "shared_context", "order_context"}
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_norm = str(key).casefold()
                value_norm = str(item).casefold()
                if key_norm in shared_keys and value_norm not in {"", "0", "false", "none", "null"}:
                    return True
                if key_norm in {"raw", "message_excerpt", "context", "notes"} and re.search(
                    r"shared customer|another customer|order context|must be retained", value_norm, re.I
                ):
                    return True
                if walk(item):
                    return True
        elif isinstance(value, list):
            return any(walk(x) for x in value)
        return False
    return walk(record)

def desired_operation(item: dict[str, Any], uid: str, audit_at: str) -> tuple[str | None, str | None, bool]:
    cat, state = item["category"], item["state"]
    exists = state not in {"ABSENT", "NOT_FOUND", "MISSING"}
    pii = item_has_pii(item)
    linked = item_attributable(item, uid)
    if cat in DELETE_CATS:
        if exists:
            return "REPORT_REMAINING_RECORD", "DELETE_RECORD", True
        return None, None, False
    if cat in REDACT_CATS:
        if cat == "ACCOUNT_TOMBSTONE":
            if state not in {"ABSENT"} and pii:
                return "REPORT_EXPOSED_PII", "REDACT_RECORD", True
            return None, None, exists
        if cat == "EMAIL_DELIVERY_LOG":
            if exists and pii:
                return "REPORT_EXPOSED_PII", "REDACT_RECORD", True
            return None, None, exists
        if cat == "SUPPORT_MESSAGE":
            if exists:
                if support_shared_context(item["record"]) and (pii or state == "IDENTIFIABLE"):
                    return "REPORT_EXPOSED_PII", "REDACT_RECORD", True
                return "REPORT_REMAINING_RECORD", "DELETE_RECORD", True
            return None, None, False
        if exists and (pii or state == "IDENTIFIABLE"):
            return "REPORT_EXPOSED_PII", "REDACT_RECORD", True
        return None, None, exists
    if cat in ANON_CATS:
        if exists and (pii or linked or state == "IDENTIFIABLE"):
            return "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", True
        return None, None, exists
    if cat == "DATA_FLOW":
        if state == "ACTIVE":
            return "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", True
        return None, None, exists
    if cat == "BACKUP_ARCHIVE":
        if state == "ACTIVE":
            return "REPORT_RESTORE_RISK", "BLOCK_RESTORE", True
        return None, None, exists
    if cat in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}:
        if exists and (cat == "LEGAL_HOLD_RECORD" or item_retained(item, audit_at)):
            return None, None, True
        return None, None, False
    return None, None, False

def verification(item: dict[str, Any], uid: str, audit_at: str) -> tuple[str, str] | None:
    cat, state = item["category"], item["state"]
    exists = state not in {"ABSENT", "NOT_FOUND", "MISSING"}
    pii = item_has_pii(item)
    linked = item_attributable(item, uid)
    if cat in DELETE_CATS:
        return ("VERIFY_RECORD_ABSENT", "ABSENT")
    if cat == "ACCOUNT_TOMBSTONE":
        return ("VERIFY_RECORD_REDACTED", "REDACTED")
    if cat == "SUPPORT_MESSAGE":
        if exists and support_shared_context(item["record"]):
            return ("VERIFY_RECORD_REDACTED", "REDACTED")
        if exists:
            return ("VERIFY_RECORD_ABSENT", "ABSENT")
        return None
    if cat == "EMAIL_DELIVERY_LOG":
        if exists:
            return ("VERIFY_RECORD_REDACTED", "REDACTED")
        return None
    if cat in ANON_CATS:
        if exists:
            return ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED")
        return None
    if cat in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}:
        if exists and (cat == "LEGAL_HOLD_RECORD" or item_retained(item, audit_at)):
            return ("VERIFY_RECORD_PRESENT", "PRESENT")
        return None
    if cat == "DATA_FLOW":
        return ("VERIFY_DATA_FLOW_DISABLED", "DISABLED")
    if cat == "BACKUP_ARCHIVE":
        return ("VERIFY_RESTORE_BLOCKED", "BLOCKED")
    return None

def step(phase: str, system: str, resource: str, operation: str, state: str, evidence_id: str) -> dict[str, Any]:
    return {"step_no": 0, "phase": phase, "system_id": system, "resource_id": resource,
            "operation": operation, "state": state, "evidence_id": evidence_id}

def order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phase_order = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
    def key(s: dict[str, Any]) -> tuple[Any, ...]:
        phase = s["phase"]
        op_order = FIND_ORDER if phase == "FINDING" else REMED_ORDER if phase == "REMEDIATION" else VERIFY_ORDER
        return (phase_order[phase], op_order.get(s["operation"], 99), s["system_id"], s["resource_id"])
    steps.sort(key=key)
    for i, s in enumerate(steps, 1):
        s["step_no"] = i
    return steps

def audit_request(req: dict[str, str], uid: str | None, evidence: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not classify_request_text(req.get("request_text", "")):
        return "NOT_APPLICABLE", []
    if not uid:
        return "INCOMPLETE", []
    items = resource_for_case(req, uid, {}, {}, evidence)
    # Aliases are supplied by the caller through the internal record match; resolve resource rules below.
    if not items:
        return "INCOMPLETE", []
    findings: list[dict[str, Any]] = []
    remediations: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for item in items:
        found, remedy, _ = desired_operation(item, uid, req["audit_at"])
        if found:
            findings.append(step("FINDING", item["system"], item["resource_id"], found,
                                 "ACTIVE" if found in {"REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"} else "PRESENT",
                                 item["evidence_id"]))
            if remedy:
                state = {"DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
                         "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED"}[remedy]
                remediations.append(step("REMEDIATION", item["system"], item["resource_id"], remedy, state, ""))
        check = verification(item, uid, req["audit_at"])
        if check:
            checks.append(step("VERIFICATION", item["system"], item["resource_id"], check[0], check[1], item["evidence_id"]))
    status = "INCOMPLETE" if findings else "COMPLETE"
    if status == "COMPLETE":
        return status, order_steps(checks)
    # Remediation proposals describe future state; their checks have no evidence yet.
    for s in checks:
        s["evidence_id"] = ""
    return status, order_steps(findings + remediations + checks)

def activity_resource_links(dataset: Path, aliases_by_user: dict[str, set[str]]) -> dict[str, dict[str, dt.datetime | None]]:
    # Identity-catalog rows are explicit identity-to-resource links; other activity outcomes remain claims.
    linked: dict[str, dict[str, dt.datetime | None]] = defaultdict(dict)
    activity_path = dataset / "system_activity.csv"
    if not activity_path.exists():
        return linked
    for row in read_csv(activity_path):
        if row.get("event_type") != "LINK_RESOURCE_IDENTITY":
            continue
        details = str(row.get("details", "")).casefold()
        for uid, aliases in aliases_by_user.items():
            if uid.casefold() in details or any(a and len(a) >= 4 and a in details for a in aliases):
                if row.get("resource_id"):
                    linked[uid][row["resource_id"]] = parse_time(row.get("event_time"))
    return linked

def nearby_activity_resources(dataset: Path, req: dict[str, str]) -> set[str]:
    """Link records to a request through nearby deletion-workflow events; never trust their outcome as state."""
    reported = parse_time(req.get("reported_at"))
    cutoff = parse_time(req.get("audit_at"))
    if reported is None:
        return set()
    allowed = {"DELETE_RECORD", "ANONYMIZE_RECORD", "REDACT_RECORD",
               "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS"}
    linked: set[str] = set()
    for row in read_csv(dataset / "system_activity.csv"):
        if row.get("event_type") not in allowed or not row.get("resource_id"):
            continue
        when = parse_time(row.get("event_time"))
        if when is None or (cutoff and when > cutoff):
            continue
        if abs((when - reported).total_seconds()) <= 7200:
            linked.add(row["resource_id"])
    return linked

def run(dataset: Path, output: Path) -> None:
    requests = read_csv(dataset / "deletion_requests.csv")
    users, aliases_by_user, by_email, audit_rows = identity_index(dataset)
    evidence, manifest, coverage = load_evidence(dataset)
    activity_links = activity_resource_links(dataset, aliases_by_user)
    padded_account_ids = any(
        (m := re.fullmatch(r"account_(\d+)", str(item.get("resource_id", ""))))
        and (u := re.fullmatch(r"user_(\d+)", str(item.get("record", {}).get("user_id", ""))))
        and len(u.group(1)) <= 2 and len(m.group(1)) == 3 and int(m.group(1)) == int(u.group(1))
        for item in evidence if isinstance(item.get("record"), dict)
    )
    rows = []
    for req in requests:
        email = norm_email(req.get("email", ""))
        uid = by_email.get(email)
        if uid is None:
            # Resolve from all aliases if input normalization differs from an identity snapshot.
            matches = [u for u, aliases in aliases_by_user.items() if email in aliases]
            uid = matches[0] if len(matches) == 1 else None
        if not classify_request_text(req.get("request_text", "")):
            status, steps = "NOT_APPLICABLE", []
        elif uid:
            items = []
            cutoff = parse_time(req.get("audit_at"))
            nearby_resources = nearby_activity_resources(dataset, req)
            aliases = {email}
            identity = users.get(uid, {})
            identity_updated = parse_time(identity.get("updated_at"))
            if cutoff is None or identity_updated is None or identity_updated <= cutoff:
                for key in ("name", "email", "phone", "email_hash"):
                    value = identity.get(key, "")
                    if value:
                        aliases.add(norm_email(value) if key == "email" else norm_phone(value) if key == "phone" else str(value).casefold())
            for audit in audit_rows:
                event_time = parse_time(audit.get("event_time"))
                if audit.get("user_id") != uid or (cutoff and event_time and event_time > cutoff):
                    continue
                field = audit.get("field_name", "").casefold()
                for key in ("old_value", "new_value"):
                    value = audit.get(key, "")
                    if value:
                        aliases.add(norm_email(value) if "email" in field else norm_phone(value) if "phone" in field else str(value).casefold())
            for item in evidence:
                if cutoff and item["captured_at"] > cutoff:
                    continue
                matched = record_identity_match(item["record"], aliases, uid)
                linked_at = activity_links.get(uid, {}).get(item["resource_id"])
                linked = linked_at is not None and (cutoff is None or linked_at <= cutoff)
                temporal_link = item["resource_id"] in nearby_resources
                if matched or linked or temporal_link:
                    item = dict(item)
                    item["record"] = dict(item["record"]) if isinstance(item["record"], dict) else {"raw": item["record"]}
                    if matched or linked:
                        item["record"]["_identity_match"] = True
                    items.append(item)
            if padded_account_ids and not any(i["category"] == "USER_PROFILE" for i in items):
                account_number = re.fullmatch(r"user_(\d+)", uid)
                if account_number and len(account_number.group(1)) <= 2:
                    candidate = f"account_{int(account_number.group(1)):03d}"
                    latest_coverage = [x for x in coverage if x["system"] == "account_service" and
                                       (cutoff is None or x["captured_at"] <= cutoff)]
                    if latest_coverage:
                        proof = max(latest_coverage, key=lambda x: x["captured_at"])
                        items.append({"system": "account_service", "resource_id": candidate,
                                      "category": "USER_PROFILE", "state": "ABSENT",
                                      "record": {"user_id": uid, "result": "ABSENT"},
                                      "evidence_id": proof["evidence_id"], "captured_at": proof["captured_at"]})
            # Keep the latest observed state for each resource/category within audit time.
            latest = {}
            for item in items:
                key = (item["system"], item["resource_id"], item["category"])
                if key not in latest or item["captured_at"] > latest[key]["captured_at"]:
                    latest[key] = item
                elif item["captured_at"] == latest[key]["captured_at"] and item["state"] != "PRESENT":
                    latest[key] = item
            items = list(latest.values())
            findings, remediations, checks = [], [], []
            for item in items:
                found, remedy, _ = desired_operation(item, uid, req["audit_at"])
                if found:
                    findings.append(step("FINDING", item["system"], item["resource_id"], found,
                                         "ACTIVE" if found in {"REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"} else "PRESENT",
                                         item["evidence_id"]))
                    if remedy:
                        state = {"DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
                                 "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED"}[remedy]
                        remediations.append(step("REMEDIATION", item["system"], item["resource_id"], remedy, state, ""))
                check = verification(item, uid, req["audit_at"])
                if check:
                    checks.append(step("VERIFICATION", item["system"], item["resource_id"], check[0], check[1], item["evidence_id"]))
            status = "INCOMPLETE" if findings else "COMPLETE"
            if status == "COMPLETE":
                steps = order_steps(checks)
            else:
                for s in checks:
                    s["evidence_id"] = ""
                steps = order_steps(findings + remediations + checks)
        else:
            status, steps = "INCOMPLETE", []
        rows.append({"case_id": req["case_id"], "deletion_status": status, "steps_json": json.dumps(steps, ensure_ascii=False, separators=(",", ":"))})
    rows.sort(key=lambda x: x["case_id"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "deletion_status", "steps_json"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, default=DATASET)
    p.add_argument("--output", type=Path, default=Path("output.csv"))
    args = p.parse_args()
    run(args.dataset, args.output)
    print(f"Wrote {sum(1 for _ in args.output.open(encoding='utf-8'))-1} cases to {args.output}")

if __name__ == "__main__":
    main()
