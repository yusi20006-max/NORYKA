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

    def test_pairing_code_cannot_be_reused_for_an_already_linked_account(self):
        code, _ = self.service.create_pairing_code(self.owner)
        self.service.claim_pairing_code(code, "telegram", "user-200")
        second_code, _ = self.service.create_pairing_code(self.owner)
        with self.assertRaises(PermissionError):
            self.service.claim_pairing_code(second_code, "telegram", "user-200")
        self.assertIsNone(self.service.resolve_identity("telegram", "user-201"))

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
