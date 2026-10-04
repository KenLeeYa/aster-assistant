# Public publication and product experience plan

Status: review plan. Do not publish the current Git history or tracked reports without a file-by-file public disclosure review. Keep the existing proprietary LICENSE: the intended public repository is source-visible, and visibility grants no open-source reuse rights. Do not accept outside contributions until contribution terms are explicit. Third-party code must retain its own notices and compatible terms.

## Publication gate

The current tree tracks `reports/` with hardware inventory, device QA, package receipts, scans, and environment evidence. Earlier commits can retain removed material. Build a clean publication history from an allowlisted source snapshot rather than pushing this repository's history to a public remote. Exclude `reports/`, `docs/specs/`, `IMPLEMENTATION_STATUS.md`, `MANUAL_ACTIONS.md`, `runtime/`, `backups/`, dumps, logs, generated packages, local configs, model files, credentials, tokens, and user content. Review all included files for personal paths, addresses, tokens, device identifiers, and license conflicts; run a full-history secret scan against only the clean publication history. Retain the original local history separately. A draft PR is appropriate only after the public base exists and the sanitized branch passes review.

Initial filename-level review found 30 tracked report files and one tracked original prompt specification. A scoped, path-only pattern screen of tracked non-report files flagged eight files for manual review; it did not display matching content and is not a full secret scan. No publication snapshot has yet passed review. Do not treat `.gitignore` or a prior private-repository scan as evidence that a new public history is clean.

The existing CI already uses hosted Ubuntu runners, read-only token permission and pinned action SHAs. It now cancels superseded runs. Keep PR checks without write credentials, use no self-hosted or large runners by default, and add retention limits only to any future uploaded artifacts. Never run untrusted PR code in a privileged `pull_request_target` workflow.

## UX information architecture

The current Command Center already has conversation, project, calendar, memory, approvals, and status surfaces. Evolve these instead of adding a second UI framework:

| Screen | Minimum behavior | Failure state |
| --- | --- | --- |
| Overview | Core, database, model, WSL and device health; resource use; next action | Show stale timestamp and recovery guidance, never a false green state |
| Conversation | Text/PTT state, transcript review, playback, interrupt, cancel | Preserve draft; show whether the request was accepted or stopped |
| Runs | Step progress, source references, recover/cancel, bounded retry | Distinguish failed, cancelled, waiting for approval, and unknown outcome |
| Approvals | Exact action, target, side effects, expiry, device, approve/deny | Expire and invalidate on state/action change; never auto-approve |
| Memory | Source, confidence, scope, edit/delete/export | Warn about downstream use and record supersession/audit |
| Connections | Model placement, resource profile, paired devices, revoke | Disable unavailable capability and explain the prerequisite |
| Settings | Local/cloud routing, consent, tool risk tiers, backups | Cloud remains off until explicit, specific consent |

Use Taiwan Traditional Chinese by default, semantic labels, visible keyboard focus, screen-reader status announcements, and equivalent keyboard and touch controls. A voice-only path cannot approve consequential actions. Show the local/cloud route and data destination before a request is sent.

## Selective upstream lessons

OpenClaw suggests channel/task boundaries and scheduled work; Open WebUI suggests accessible model and conversation visibility; Agent Zero suggests isolation of risky execution; Letta suggests provenance and memory editing. These are design references, not code or wholesale dependencies. Keep one Core policy/approval/audit path. Any plugin must be versioned, signed or hash-pinned, allowlisted by capability, disabled by default, and subject to result sanitization. Add idempotent jobs, bounded backoff, timeout/quotas, redacted observability, backup/restore rehearsal, and update rollback before claiming unattended operation.
