import tempfile
import unittest
from pathlib import Path

from core.identity import IdentityContext, IdentityService


class IdentityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "state.sqlite3"
        self.now = [1000.0]
        self.service = IdentityService(
            self.db,
            owners={"telegram": {"owner-100"}},
            pairing_ttl_seconds=30,
            clock=lambda: self.now[0],
        )
        self.owner = self.service.resolve_identity("telegram", "owner-100")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_owner_requires_explicit_allowlist(self):
        self.assertTrue(self.owner.is_owner)
        self.assertIsNone(self.service.resolve_identity("telegram", "first-sender"))
        with self.assertRaises(PermissionError):
            self.service.require_identity("telegram", "first-sender")
        self.assertIsNone(self.service.resolve_identity("bale", "owner-100"))

    def test_non_owner_cannot_create_pairing_code(self):
        forged = IdentityContext(
            self.owner.principal_id, "telegram", "owner-100", True, "owner_allowlist"
        )
        with self.assertRaises(PermissionError):
            self.service.create_pairing_code(forged)
        self.assertFalse(self.service.verify_context(forged))

    def test_pairing_code_is_one_time_and_persists(self):
        code, expires = self.service.create_pairing_code(self.owner)
        self.assertEqual(expires, 1030.0)
        linked = self.service.claim_pairing_code(code, "telegram", "user-200")
        self.assertFalse(linked.is_owner)
        self.assertEqual(linked.auth_method, "pairing")
        self.assertEqual(linked.principal_id, self.owner.principal_id)
        conversation_a = self.service.resolve_conversation(linked, "group-9")
        conversation_b = self.service.resolve_conversation(linked, "group-9")
        self.assertEqual(conversation_a, conversation_b)
        self.assertEqual(conversation_a.principal_id, self.owner.principal_id)
        with self.assertRaises(PermissionError):
            self.service.resolve_conversation(
                IdentityContext("forged", "telegram", "user-200", False, "pairing"),
                "group-9",
            )
        self.assertEqual(
            self.service.resolve_identity("telegram", "user-200"), linked
        )
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(code, "bale", "replay-user")
        self.service.close()
        self.service = IdentityService(
            self.db, owners={"telegram": {"owner-100"}}, clock=lambda: self.now[0]
        )
        self.assertEqual(
            self.service.resolve_identity("telegram", "user-200"), linked
        )

    def test_pairing_code_is_rejected_if_issuer_is_removed_from_owner_allowlist(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self.service.close()
        self.service = IdentityService(
            self.db, owners={}, clock=lambda: self.now[0]
        )
        with self.assertRaisesRegex(PermissionError, "issuer is no longer authorized"):
            self.service.claim_pairing_code(code, "bale", "untrusted-after-owner-removal")
        self.assertIsNone(
            self.service.resolve_identity("bale", "untrusted-after-owner-removal")
        )
        events = [event["event"] for event in self.service.audit_events()]
        self.assertIn("pairing_code_issuer_unauthorized", events)

    def test_paired_context_is_invalidated_when_its_owner_is_removed(self):
        code, _ = self.service.create_pairing_code(self.owner)
        linked = self.service.claim_pairing_code(code, "bale", "linked-device")
        self.service.owners = {}
        self.assertFalse(self.service.verify_context(linked))
        self.assertIsNone(self.service.resolve_identity("bale", "linked-device"))

    def test_owner_context_is_invalidated_when_owner_is_removed(self):
        self.assertTrue(self.service.verify_context(self.owner))
        self.service.owners = {}
        self.assertFalse(self.service.verify_context(self.owner))
        with self.assertRaises(PermissionError):
            self.service.create_pairing_code(self.owner)

    def test_owner_can_revoke_unused_pairing_code(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self.service.revoke_pairing_code(self.owner, code)
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(code, "bale", "revoked-user")
        self.assertIsNone(self.service.resolve_identity("bale", "revoked-user"))

    def test_allowlisted_owner_account_cannot_claim_another_owners_pairing_code(self):
        self.service.owners = {
            "telegram": frozenset({"owner-100", "owner-101"})
        }
        code, _ = self.service.create_pairing_code(self.owner)
        with self.assertRaisesRegex(
            PermissionError, "allowlisted owner accounts cannot claim pairing codes"
        ):
            self.service.claim_pairing_code(code, "telegram", "owner-101")

        resolved_owner = self.service.resolve_identity("telegram", "owner-101")
        self.assertTrue(resolved_owner.is_owner)
        self.assertEqual(
            resolved_owner.principal_id,
            self.service._principal_id("telegram", "owner-101"),
        )

        # Rejection happens before token consumption; a genuine non-owner can
        # still use the one-time code issued by owner-100.
        linked = self.service.claim_pairing_code(code, "bale", "linked-user")
        self.assertEqual(linked.principal_id, self.owner.principal_id)
        self.assertTrue(self.service.verify_context(linked))

    def test_pairing_code_expires(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self.now[0] += 31
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(code, "telegram", "late-user")
        self.assertIsNone(self.service.resolve_identity("telegram", "late-user"))

    def test_pairing_context_is_rejected_when_its_account_becomes_allowlisted(self):
        code, _ = self.service.create_pairing_code(self.owner)
        paired = self.service.claim_pairing_code(code, "telegram", "promoted-user")
        self.assertEqual(paired.principal_id, self.owner.principal_id)
        # 1. The existing context is accepted under the original state.
        self.assertTrue(self.service.verify_context(paired))
        # 2. The account is added to the owner allowlist afterwards.
        self.service.owners = {"telegram": frozenset({"owner-100", "promoted-user"})}
        authoritative = self.service.resolve_identity("telegram", "promoted-user")
        self.assertTrue(authoritative.is_owner)
        self.assertEqual(
            authoritative.principal_id,
            self.service._principal_id("telegram", "promoted-user"),
        )
        # 3. The stale pre-transition pairing context is now rejected
        #    server-side (verification path), before any adapter use.
        self.assertFalse(self.service.verify_context(paired))
        with self.assertRaises(PermissionError):
            self.service.resolve_conversation(paired, "group-9")
        with self.assertRaises(PermissionError):
            self.service.create_pairing_code(paired)
        # 4. No silent ownership transfer and no unrelated record changes:
        #    the promoted account resolves to its OWN owner principal (not the
        #    stale paired principal), and owner-100 keeps its principal.
        self.assertNotEqual(authoritative.principal_id, paired.principal_id)
        owner = self.service.resolve_identity("telegram", "owner-100")
        self.assertTrue(owner.is_owner)
        self.assertEqual(owner.principal_id, self.owner.principal_id)
        # 5. A newly issued, legitimate context under current policy verifies.
        fresh = self.service.resolve_identity("telegram", "promoted-user")
        self.assertTrue(self.service.verify_context(fresh))
        self.assertTrue(fresh.is_owner)
        # 6. Unaffected paired accounts keep their existing behavior.
        code2, _ = self.service.create_pairing_code(self.owner)
        unaffected = self.service.claim_pairing_code(code2, "bale", "device-2")
        self.assertTrue(self.service.verify_context(unaffected))
        self.assertEqual(
            self.service.resolve_identity("bale", "device-2").principal_id,
            self.owner.principal_id,
        )

    def test_verify_context_rejects_malformed_context_proofs_safely(self):
        code, _ = self.service.create_pairing_code(self.owner)
        paired = self.service.claim_pairing_code(code, "telegram", "user-240")
        # 1. A valid ASCII proof is accepted.
        self.assertTrue(self.service.verify_context(paired))
        # 2-6. Malformed proofs must be rejected through the normal
        #       invalid-proof path (False), never by raising TypeError or any
        #       unexpected exception — including non-ASCII input, wrong types,
        #       empty values, wrong lengths, and invalid representations.
        malformed_proofs = (
            "π" * 64,                     # non-ASCII, same length
            "a" * 60 + "π" * 4,           # non-ASCII suffix
            b"x" * 64,                    # wrong type: bytes
            12345,                        # wrong type: int
            None,                         # wrong type: None
            "",                           # empty
            "a" * 63,                     # malformed length
            "a" * 65,                     # malformed length
            "z" * 64,                     # invalid hex representation
            "g" * 63 + "0",               # invalid hex representation
            "A" * 64,                     # well-formed but incorrect proof
        )
        for index, malformed in enumerate(malformed_proofs):
            with self.subTest(index=index, kind=type(malformed).__name__):
                forged = IdentityContext(
                    paired.principal_id, paired.channel, paired.account_id,
                    False, "pairing", proof=malformed,
                )
                self.assertFalse(self.service.verify_context(forged))
                with self.assertRaises(PermissionError):
                    self.service.resolve_conversation(forged, "group-9")
        # The still-valid context remains verifiable after malformed attempts.
        self.assertTrue(self.service.verify_context(paired))

    def test_pairing_code_cannot_be_reused_for_an_already_linked_account(self):
        code, _ = self.service.create_pairing_code(self.owner)
        first = self.service.claim_pairing_code(code, "telegram", "user-200")
        second_code, _ = self.service.create_pairing_code(self.owner)
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(second_code, "telegram", "user-200")
        # The rejected claim left the original link untouched.
        resolved = self.service.resolve_identity("telegram", "user-200")
        self.assertEqual(resolved.principal_id, self.owner.principal_id)
        self.assertEqual(resolved, first)
        # The rejection must not consume the one-time code; a legitimate
        # different account can still claim it.
        other = self.service.claim_pairing_code(second_code, "bale", "user-202")
        self.assertEqual(other.principal_id, self.owner.principal_id)

    def test_revocation_unlinks_account(self):
        code, _ = self.service.create_pairing_code(self.owner)
        linked = self.service.claim_pairing_code(code, "bale", "user-300")
        self.assertEqual(linked.principal_id, self.owner.principal_id)
        self.assertTrue(self.service.unlink_account(self.owner, "bale", "user-300"))
        self.assertFalse(self.service.verify_context(linked))
        self.assertIsNone(self.service.resolve_identity("bale", "user-300"))
        self.assertFalse(self.service.unlink_account(self.owner, "bale", "user-300"))
        replacement_code, _ = self.service.create_pairing_code(self.owner)
        replacement = self.service.claim_pairing_code(replacement_code, "bale", "user-300")
        self.assertEqual(replacement.principal_id, self.owner.principal_id)
        self.assertFalse(self.service.verify_context(linked))
        self.assertTrue(self.service.verify_context(replacement))
        self.assertIsNotNone(self.service.resolve_identity("bale", "user-300"))

    def test_non_owner_cannot_unlink_or_revoke_pairing(self):
        code, _ = self.service.create_pairing_code(self.owner)
        user = self.service.claim_pairing_code(code, "telegram", "user-200")
        with self.assertRaises(PermissionError):
            self.service.unlink_account(user, "telegram", "owner-100")
        next_code, _ = self.service.create_pairing_code(self.owner)
        with self.assertRaises(PermissionError):
            self.service.revoke_pairing_code(user, next_code)

    def test_pairing_secrets_are_not_stored_in_plaintext(self):
        code, _ = self.service.create_pairing_code(self.owner)
        stored = self.service._conn.execute(
            "SELECT token_hash FROM noryka_pairing_tokens"
        ).fetchone()["token_hash"]
        self.assertNotEqual(stored, code)
        self.assertEqual(len(stored), 64)

    def test_identity_inputs_must_be_canonical_platform_ids(self):
        with self.assertRaises(ValueError):
            self.service.resolve_identity("telegram", " user-1")
        with self.assertRaises(ValueError):
            self.service.resolve_identity("", "user-1")

    def test_audit_retention_is_bounded_for_repeated_denials(self):
        self.service.AUDIT_RETENTION_LIMIT = 3
        for index in range(7):
            self.service.resolve_identity("telegram", f"untrusted-{index}")
        events = self.service.audit_events()
        self.assertEqual(len(events), 3)
        self.assertEqual(
            [event["account_id"] for event in events],
            ["untrusted-4", "untrusted-5", "untrusted-6"],
        )

    def test_audit_retention_keeps_exactly_the_default_10000_records(self):
        """With the default AUDIT_RETENTION_LIMIT, the table holds exactly 10,000 rows."""
        conn = self.service._conn
        # Seed 10,000 historical audit rows in one transaction (past records).
        conn.execute("BEGIN")
        conn.executemany(
            """INSERT INTO noryka_identity_audit
               (event, channel, account_id, principal_id, occurred_at, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                ("pairing_code_created", None, None, None, 900.0 + index, "")
                for index in range(10_000)
            ],
        )
        conn.execute("COMMIT")
        self.assertEqual(len(self.service.audit_events()), 10_000)
        # Three more audited denials must each retain the exact newest window.
        for index in range(3):
            self.assertIsNone(self.service.resolve_identity("telegram", f"flood-{index}"))
        events = self.service.audit_events()
        self.assertEqual(len(events), self.service.AUDIT_RETENTION_LIMIT)
        self.assertEqual(events[0]["id"], 4)
        self.assertEqual(events[-1]["id"], 10_003)
        self.assertEqual(events[-1]["event"], "identity_denied")

    def test_audit_prune_keeps_exactly_the_newest_window_with_non_contiguous_ids(self):
        """The prune keeps the newest N rows even when ids are not contiguous.

        This pins the cutoff-by-position implementation: a max_id-derived
        cutoff (max_id - limit) would silently retain fewer rows once ids stop
        being contiguous.
        """
        # Accumulate rows with a large retention limit so ids stay 1..7.
        self.service.AUDIT_RETENTION_LIMIT = 100
        for index in range(7):
            self.service.resolve_identity("telegram", f"untrusted-{index}")
        # Delete two middle rows to simulate a future feature removing rows
        # between the oldest end and the retained window.
        self.service._conn.execute("DELETE FROM noryka_identity_audit WHERE id IN (5, 6)")
        self.service.AUDIT_RETENTION_LIMIT = 3
        self.assertIsNone(self.service.resolve_identity("telegram", "untrusted-new"))
        events = self.service.audit_events()
        self.assertEqual(
            [event["id"] for event in events],
            [4, 7, 8],
            "prune must retain exactly the three newest rows even with gaps in ids",
        )

    def _break_audit(self, service: IdentityService) -> None:
        def _broken_audit(*args, **kwargs):
            raise OSError("simulated audit storage failure")

        service._audit = _broken_audit

    def _restore_audit(self, service: IdentityService) -> None:
        if "_audit" in service.__dict__:
            del service.__dict__["_audit"]

    def test_audit_failure_rolls_back_create_pairing_code(self):
        self._break_audit(self.service)
        with self.assertRaisesRegex(OSError, "simulated audit storage failure"):
            self.service.create_pairing_code(self.owner)
        self.assertFalse(self.service._conn.in_transaction)
        tokens = self.service._conn.execute(
            "SELECT COUNT(*) AS n FROM noryka_pairing_tokens"
        ).fetchone()["n"]
        self.assertEqual(tokens, 0, "token insert must roll back when its audit write fails")
        self.assertEqual(self.service.audit_events(), [])
        # The same token hash must be reusable: insert was fully undone.
        self._restore_audit(self.service)
        code, _ = self.service.create_pairing_code(self.owner)
        linked = self.service.claim_pairing_code(code, "telegram", "user-200")
        self.assertEqual(linked.principal_id, self.owner.principal_id)

    def test_audit_failure_rolls_back_revoke_pairing_code(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self._break_audit(self.service)
        with self.assertRaisesRegex(OSError, "simulated audit storage failure"):
            self.service.revoke_pairing_code(self.owner, code)
        self.assertFalse(self.service._conn.in_transaction)
        # The revocation must be undone: the code is still claimable.
        self._restore_audit(self.service)
        linked = self.service.claim_pairing_code(code, "bale", "user-211")
        self.assertEqual(linked.principal_id, self.owner.principal_id)

    def test_audit_failure_rolls_back_unlink_account(self):
        code, _ = self.service.create_pairing_code(self.owner)
        linked = self.service.claim_pairing_code(code, "bale", "user-212")
        self._break_audit(self.service)
        with self.assertRaisesRegex(OSError, "simulated audit storage failure"):
            self.service.unlink_account(self.owner, "bale", "user-212")
        self.assertFalse(self.service._conn.in_transaction)
        # The unlink must be undone: the account is still paired and trusted.
        self._restore_audit(self.service)
        self.assertTrue(self.service.verify_context(linked))
        resolved = self.service.resolve_identity("bale", "user-212")
        self.assertEqual(resolved.principal_id, self.owner.principal_id)
        # A later real unlink still works and returns False for a no-op twice.
        self.assertTrue(self.service.unlink_account(self.owner, "bale", "user-212"))
        self.assertFalse(self.service.unlink_account(self.owner, "bale", "user-212"))
        events = [
            event["event"] for event in self.service.audit_events()
            if event["event"].startswith("identity_unlink")
        ]
        self.assertEqual(events, ["identity_unlinked", "identity_unlink_noop"])

    def test_audit_records_pairing_and_rejections(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self.service.claim_pairing_code(code, "telegram", "user-200")
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(code, "telegram", "user-201")
        events = [event["event"] for event in self.service.audit_events()]
        self.assertIn("pairing_code_created", events)
        self.assertIn("identity_paired", events)
        self.assertIn("pairing_code_rejected", events)


if __name__ == "__main__":
    unittest.main()
