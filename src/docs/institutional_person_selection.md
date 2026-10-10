# Institutional person selection

The common API separates a selectable identity from a NovaDesk login account.
IdentityPolicy.selection_requirement is server-owned: autofill (Accounts),
institutional (Printing), local_user, or both. New modules must register context
permissions and field whitelists; the browser never grants selection rights.
Responses add selectable, has_local_user, selection_requirement and rejection
reason. The shared JS handles capabilities without module-specific checks.

Printing requires a person from RRHH, AD, outsourced mapping or an existing local
source, with valid email in configured DIRECTORY_AD_DOMAIN and no known inactive
status. Explicit nonperson/technical/shared flags, reserved usernames/mailboxes
and service prefixes are rejected. AD additionally needs given/family names.
These conservative rules are not a definitive inventory of shared AD accounts;
ambiguous or incomplete person metadata needs institutional verification.
Accounts remains an account administration flow with its existing permissions
and autofill behavior; it neither gains login rights nor auto-creates accounts
from selections in other modules.

Migration printing.0018_printingdevice_responsible_identity adds an optional,
noneditable JSON snapshot. Apply the schema in the authorized deployment before
running the new code. It does not backfill or rewrite existing assignments.
Snapshot includes name, email, username, source and locator only. Existing
responsible_user remains optional; notes and imported names are preserved.
Signed short-lived selection references are re-read and validated on save;
snapshots are constructed server-side, never from posted personal attributes.
Removing selection explicitly clears both snapshot and FK. Opening edit does
not query sources or refresh stored data. Display prefers snapshot, with legacy
local-user fallback.

RRHH locator uses IdPersonal; AD uses the existing username/email locator;
outsourced mapping uses its existing key. Prefer institutional linked locators
over LOCAL. AD username/email and mapping keys can change: re-selection may be
needed after a rename. Stored name/email can become stale; no automatic refresh
is performed. resolve_persisted_identity re-reads the locator and can discover a
later local link using existing safe merge rules, without writing anything.
A module must explicitly decide when to persist such a link; email alone never
establishes that association. No role/permission changes or user creation.

Deploy schema and run collectstatic through the normal authorized deployment.
No production migration is performed by this implementation.
