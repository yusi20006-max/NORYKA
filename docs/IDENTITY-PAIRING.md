# Identity and pairing boundary

## Trust model

NORYKA identity is resolved only at a trusted channel-adapter boundary. The
adapter must extract the immutable platform account identifier from a verified
Telegram/Bale update. Display names, usernames, message text, forwarded
metadata, model output, and tool arguments are never identity evidence.

The identity service accepts the channel name and canonical platform account
ID from that adapter and returns an immutable `IdentityContext` carrying a
process-local HMAC proof. `require_identity` fails closed for unpaired accounts. Downstream services can verify that proof; a caller
cannot create a trusted context merely by instantiating the dataclass. No
adapter exists in this phase; Telegram/Bale wiring belongs to Issue #8.

## Owner bootstrap

Owners are configured explicitly by deployment as a channel-to-account-ID
allowlist. An empty or missing allowlist authenticates no owner. There is no
first-sender-wins bootstrap and no automatic promotion of the first user.

Example application wiring (configuration is supplied by the deployment,
not by a chat request):

```python
identity = IdentityService(
    owners={"telegram": {"<verified-platform-account-id>"}}
)
```

Do not commit actual account IDs or other deployment secrets into the repo.

## Pairing

An authenticated owner creates a short-lived random pairing code. Only a
SHA-256 digest is persisted. The code is returned once, expires, and is
atomically consumed by the first successful claim. The newly paired channel
account is linked to the principal of the owner who issued the code, allowing
that owner's Telegram and Bale accounts to share one principal. A channel
adapter may call `claim_pairing_code` only after it has independently verified
the sender's platform account ID.

Pairing does not authorize privileged tools or side effects. It establishes
only the channel-account-to-principal association. Tool policy and operation
approvals remain in Issue #15.

## Persistence and audit

Identity links, pairing token hashes, and audit events use SQLite in the
existing user data directory (outside the checkout). Conversation scopes are
derived deterministically from the verified channel identity and the platform
conversation identifier; they are identifiers, not authorization credentials.
Revocation is retained as a timestamp for auditability; an explicitly re-paired account reactivates the existing link record. Pairing attempts are recorded without
persisting raw pairing codes.

## Security limitations

This module is a core service, not a complete Telegram/Bale authentication
integration. Until Issue #8 supplies verified adapters and runtime wiring,
there is no production channel identity enforcement. The service must not be
treated as an OS sandbox or as tool authorization.
