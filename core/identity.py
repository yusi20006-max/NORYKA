"""Channel-independent user identity and one-time pairing service.

Channel adapters must pass immutable platform account identifiers obtained
from a verified platform event. Display names, usernames, message payload
fields, and model/tool arguments are not identity evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from functools import wraps
from threading import RLock
from pathlib import Path
from typing import Mapping

from core.state_store import default_data_dir


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class IdentityContext:
    """Trusted identity resolved by the channel boundary, never by model input."""

    principal_id: str
    channel: str
    account_id: str
    is_owner: bool
    auth_method: str
    proof: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class ConversationContext:
    """Canonical conversation scope; its identifier is not an auth credential."""

    conversation_id: str
    principal_id: str
    channel: str


class IdentityService:
    """Persist owner bootstrap, linked accounts, pairings, and audit events.

    Audit history is bounded to the newest AUDIT_RETENTION_LIMIT records.

    `owners` is an explicit deployment-owned allowlist, for example
    {"telegram": {"123456789"}, "bale": {"998877"}}. An empty allowlist
    deliberately authenticates nobody as owner; first-sender bootstrap is
    never performed.
    """

    AUDIT_RETENTION_LIMIT = 10_000

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        owners: Mapping[str, set[str] | tuple[str, ...] | list[str]] | None = None,
        pairing_ttl_seconds: int = 600,
        clock=None,
    ):
        if pairing_ttl_seconds < 1:
            raise ValueError("pairing_ttl_seconds must be positive")
        self._lock = RLock()
        self.db_path = Path(db_path) if db_path else default_data_dir() / "state.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.owners = {
            self._identifier(channel, "channel"): frozenset(
                self._identifier(account, "account_id") for account in accounts
            )
            for channel, accounts in (owners or {}).items()
        }
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self._context_key = secrets.token_bytes(32)
        self._clock = clock or time.time
        self._conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @_synchronized
    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _identifier(value: str, field: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{field} must be a non-empty canonical string")
        if len(value) > 256:
            raise ValueError(f"{field} is too long")
        return value

    @staticmethod
    def _principal_id(channel: str, account_id: str) -> str:
        raw = f"{channel}\0{account_id}".encode("utf-8")
        return "channel:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _is_authorized_principal(self, principal_id: str) -> bool:
        return any(
            principal_id == self._principal_id(owner_channel, owner_account)
            for owner_channel, owner_accounts in self.owners.items()
            for owner_account in owner_accounts
        )

    def _context_proof(self, principal_id: str, channel: str, account_id: str,
                       is_owner: bool, auth_method: str, identity_version: str = "") -> str:
        separator = chr(0)
        message = separator.join((
            principal_id, channel, account_id, str(is_owner), auth_method, identity_version
        ))
        return hmac.new(self._context_key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def _make_context(self, principal_id: str, channel: str, account_id: str,
                      is_owner: bool, auth_method: str,
                      identity_version: str = "") -> IdentityContext:
        proof = self._context_proof(
            principal_id, channel, account_id, is_owner, auth_method, identity_version
        )
        return IdentityContext(principal_id, channel, account_id, is_owner, auth_method, proof)

    @_synchronized
    def verify_context(self, context: IdentityContext) -> bool:
        """Verify context integrity and re-check that its identity is still active."""
        if not isinstance(context, IdentityContext):
            return False
        if not isinstance(context.is_owner, bool):
            return False
        try:
            principal_id = self._identifier(context.principal_id, "principal_id")
            channel = self._identifier(context.channel, "channel")
            account_id = self._identifier(context.account_id, "account_id")
            auth_method = self._identifier(context.auth_method, "auth_method")
        except ValueError:
            return False
        if not isinstance(context.proof, str) or not context.proof:
            return False
        if context.is_owner:
            if (
                auth_method != "owner_allowlist"
                or account_id not in self.owners.get(channel, ())
                or principal_id != self._principal_id(channel, account_id)
            ):
                return False
            identity_version = ""
        else:
            if auth_method != "pairing" or not self._is_authorized_principal(principal_id):
                return False
            row = self._conn.execute(
                """SELECT identity_version FROM noryka_identity_links
                   WHERE channel=? AND account_id=? AND principal_id=?
                     AND revoked_at IS NULL""",
                (channel, account_id, principal_id),
            ).fetchone()
            if row is None:
                return False
            # A new pairing creates a new generation. Old contexts stay invalid
            # even if the same channel account is later paired again.
            identity_version = row["identity_version"]
        expected = self._context_proof(
            principal_id, channel, account_id, context.is_owner,
            auth_method, identity_version,
        )
        return hmac.compare_digest(context.proof, expected)

    def resolve_conversation(self, context: IdentityContext, channel_conversation_id: str) -> ConversationContext:
        """Create a stable conversation scope only from a verified identity context."""
        if not self.verify_context(context):
            raise PermissionError("verified identity context required")
        conversation = self._identifier(channel_conversation_id, "conversation_id")
        raw = (context.channel + chr(0) + conversation).encode("utf-8")
        identifier = "conversation:" + hashlib.sha256(raw).hexdigest()
        return ConversationContext(identifier, context.principal_id, context.channel)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS noryka_identity_links (
                channel TEXT NOT NULL,
                account_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                revoked_at REAL,
                identity_version TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (channel, account_id)
            );
            CREATE INDEX IF NOT EXISTS idx_noryka_identity_principal
                ON noryka_identity_links(principal_id);
            CREATE TABLE IF NOT EXISTS noryka_pairing_tokens (
                token_hash TEXT PRIMARY KEY,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                consumed_at REAL,
                revoked_at REAL
            );
            CREATE TABLE IF NOT EXISTS noryka_identity_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                channel TEXT,
                account_id TEXT,
                principal_id TEXT,
                occurred_at REAL NOT NULL,
                details TEXT NOT NULL DEFAULT ''
            );
            """
        )
        link_columns = {
            row["name"] for row in self._conn.execute(
                "PRAGMA table_info(noryka_identity_links)"
            )
        }
        if "identity_version" not in link_columns:
            self._conn.execute(
                "ALTER TABLE noryka_identity_links "
                "ADD COLUMN identity_version TEXT NOT NULL DEFAULT ''"
            )

    def _audit(self, event: str, *, channel: str | None = None,
               account_id: str | None = None, principal_id: str | None = None,
               details: str = "") -> None:
        self._conn.execute(
            """INSERT INTO noryka_identity_audit
               (event, channel, account_id, principal_id, occurred_at, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event, channel, account_id, principal_id, self._clock(), details[:256]),
        )
        self._conn.execute(
            """DELETE FROM noryka_identity_audit
               WHERE id NOT IN (
                   SELECT id FROM noryka_identity_audit
                   ORDER BY id DESC LIMIT ?
               )""",
            (self.AUDIT_RETENTION_LIMIT,),
        )

    @_synchronized
    def resolve_identity(self, channel: str, account_id: str) -> IdentityContext | None:
        """Resolve a principal from trusted channel-adapter identifiers only."""
        channel = self._identifier(channel, "channel")
        account_id = self._identifier(account_id, "account_id")
        principal = self._principal_id(channel, account_id)
        if account_id in self.owners.get(channel, ()):
            return self._make_context(principal, channel, account_id, True, "owner_allowlist")
        row = self._conn.execute(
            """SELECT principal_id, identity_version FROM noryka_identity_links
               WHERE channel=? AND account_id=? AND revoked_at IS NULL""",
            (channel, account_id),
        ).fetchone()
        if row is None or not self._is_authorized_principal(row["principal_id"]):
            self._audit("identity_denied", channel=channel, account_id=account_id)
            return None
        return self._make_context(
            row["principal_id"], channel, account_id, False, "pairing",
            row["identity_version"],
        )

    def require_identity(self, channel: str, account_id: str) -> IdentityContext:
        """Fail closed when an inbound channel account is not trusted or paired."""
        context = self.resolve_identity(channel, account_id)
        if context is None:
            raise PermissionError("unpaired or unauthorized channel account")
        return context

    @_synchronized
    def create_pairing_code(self, actor: IdentityContext) -> tuple[str, float]:
        """Create a one-time pairing code; only a configured owner may issue it."""
        self._require_owner(actor)
        token = secrets.token_urlsafe(32)
        now = self._clock()
        expires = now + self.pairing_ttl_seconds
        self._conn.execute(
            """INSERT INTO noryka_pairing_tokens
               (token_hash, created_by, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (self._token_hash(token), actor.principal_id, now, expires),
        )
        self._audit("pairing_code_created", principal_id=actor.principal_id)
        return token, expires

    @_synchronized
    def claim_pairing_code(self, token: str, channel: str, account_id: str) -> IdentityContext:
        """Atomically consume a valid code and bind one verified channel account."""
        channel = self._identifier(channel, "channel")
        account_id = self._identifier(account_id, "account_id")
        if not isinstance(token, str) or not token or len(token) > 256:
            raise PermissionError("invalid or expired pairing code")
        token_hash = self._token_hash(token)
        now = self._clock()
        principal = self._principal_id(channel, account_id)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                """SELECT * FROM noryka_pairing_tokens
                   WHERE token_hash=? AND consumed_at IS NULL AND revoked_at IS NULL
                     AND expires_at>?""",
                (token_hash, now),
            ).fetchone()
            if row is None:
                self._audit("pairing_code_rejected", channel=channel, account_id=account_id)
                self._conn.execute("COMMIT")
                raise PermissionError("invalid or expired pairing code")
            issuer_is_authorized = self._is_authorized_principal(row["created_by"])
            if not issuer_is_authorized:
                self._conn.execute(
                    "UPDATE noryka_pairing_tokens SET revoked_at=? WHERE token_hash=?",
                    (now, token_hash),
                )
                self._audit(
                    "pairing_code_issuer_unauthorized",
                    channel=channel,
                    account_id=account_id,
                    principal_id=row["created_by"],
                )
                self._conn.execute("COMMIT")
                raise PermissionError("pairing code issuer is no longer authorized")
            existing = self._conn.execute(
                """SELECT principal_id FROM noryka_identity_links
                   WHERE channel=? AND account_id=? AND revoked_at IS NULL""",
                (channel, account_id),
            ).fetchone()
            if existing is not None:
                self._audit("pairing_target_already_linked", channel=channel, account_id=account_id)
                self._conn.execute("COMMIT")
                raise PermissionError("channel account is already paired")
            self._conn.execute(
                "UPDATE noryka_pairing_tokens SET consumed_at=? WHERE token_hash=? AND consumed_at IS NULL",
                (now, token_hash),
            )
            self._conn.execute(
                """INSERT INTO noryka_identity_links
                   (channel, account_id, principal_id, created_at, revoked_at, identity_version)
                   VALUES (?, ?, ?, ?, NULL, ?)
                   ON CONFLICT(channel, account_id) DO UPDATE SET
                       principal_id=excluded.principal_id,
                       created_at=excluded.created_at,
                       revoked_at=NULL,
                       identity_version=excluded.identity_version""",
                (channel, account_id, row["created_by"], now, token_hash),
            )
            principal = row["created_by"]
            self._audit("identity_paired", channel=channel, account_id=account_id, principal_id=principal)
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return self._make_context(
            principal, channel, account_id, False, "pairing", token_hash
        )

    @_synchronized
    def revoke_pairing_code(self, actor: IdentityContext, token: str) -> None:
        """Revoke an unused code. Owner authority is revalidated at call time."""
        self._require_owner(actor)
        self._conn.execute(
            """UPDATE noryka_pairing_tokens SET revoked_at=?
               WHERE token_hash=? AND consumed_at IS NULL AND revoked_at IS NULL""",
            (self._clock(), self._token_hash(token)),
        )
        self._audit("pairing_code_revoked", principal_id=actor.principal_id)

    @_synchronized
    def unlink_account(self, actor: IdentityContext, channel: str, account_id: str) -> bool:
        """Owner-only revocation of a linked channel account."""
        self._require_owner(actor)
        channel = self._identifier(channel, "channel")
        account_id = self._identifier(account_id, "account_id")
        now = self._clock()
        cursor = self._conn.execute(
            """UPDATE noryka_identity_links SET revoked_at=?
               WHERE channel=? AND account_id=? AND revoked_at IS NULL""",
            (now, channel, account_id),
        )
        changed = cursor.rowcount > 0
        self._audit(
            "identity_unlinked" if changed else "identity_unlink_noop",
            channel=channel, account_id=account_id, principal_id=actor.principal_id,
        )
        return changed

    def _require_owner(self, actor: IdentityContext) -> None:
        if not isinstance(actor, IdentityContext) or not actor.is_owner:
            raise PermissionError("owner identity required")
        if not self.verify_context(actor):
            raise PermissionError("untrusted identity context")
        if actor.account_id not in self.owners.get(actor.channel, ()):
            raise PermissionError("owner identity is not present in the deployment allowlist")
        if actor.principal_id != self._principal_id(actor.channel, actor.account_id):
            raise PermissionError("owner identity is invalid")

    @_synchronized
    def audit_events(self) -> list[dict]:
        return [dict(row) for row in self._conn.execute(
            "SELECT * FROM noryka_identity_audit ORDER BY id"
        )]
