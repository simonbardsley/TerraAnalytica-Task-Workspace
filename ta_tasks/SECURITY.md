# Security and cloud-readiness notes

TA Tasks v0.5.0 remains a local QGIS plugin. Selecting `cloud` or `hybrid`
processing is intentionally feature-gated; this build makes no network calls and
configures no Git remotes.

## Implemented controls

- Workspace persistence rejects common credential patterns before writing Git history.
- Provider URIs are sanitised before hashing or persistence.
- Git commands use argument arrays, disable repository hooks, and never push.
- Audit entries are append-only and hash-chained; Git commits pin the current chain head.
- Tool learning stores only task/tool identifiers, aggregate counts, and UTC timestamps.
- Usage learning is project-local, independently clearable, and can be disabled.
- Corrupt project state falls back to a last-known-good copy; newer schemas open read-only.
- Participant failures and missing plugins are isolated during workspace restoration.

## SOC 2 readiness boundary

These controls support a future SOC 2 programme but do not constitute SOC 2
compliance or certification. Before offering a cloud service, the service boundary
must add and document at least:

1. tenant isolation and organisation-scoped authorisation (deny by default);
2. SSO/MFA support, service identities, short-lived credentials, and access reviews;
3. TLS in transit, managed encryption at rest, key rotation, and secrets management;
4. immutable central audit ingestion with actor, tenant, request, result, and correlation IDs;
5. retention, deletion, export, legal-hold, and backup/restore policies with tested evidence;
6. secure SDLC controls: reviews, dependency/SAST/secret scanning, signed releases, and SBOMs;
7. monitored availability, security alerts, incident response, and breach-notification runbooks;
8. vendor risk management, change management, disaster recovery, and periodic access evidence;
9. data classification, regional residency choices, subprocessor disclosure, and privacy consent;
10. independent readiness assessment followed by the appropriate SOC 2 examination.

Cloud APIs should accept stable opaque identifiers rather than filesystem paths or
raw provider URIs. The local client should queue bounded, idempotent events and
restore from versioned server responses without making network access part of the
core QGIS layout-restore transaction.
