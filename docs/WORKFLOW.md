# Bounded project workflow

This records the build → test → independent review → fix/retest → checkpoint process already used by this project. It adds no controller, service, software dependency, scheduled task or background agent loop.

## Build-session ownership

The user-started chess build session is the primary owner. It makes routine implementation and testing decisions and continues authorized build → test → fix work toward the agreed usable milestone. No dot, supervising session, controller, operation lease or external acceptance is required between steps. Independent review is a focused quality check, not a separate execution owner or approval authority. Ask the user only for genuinely missing permissions, material product decisions or information that cannot be established from available evidence. Existing scoped runtime and device approvals remain unchanged.

## One active task packet

Read `AGENTS.md`, `HANDOFF.md`, `docs/PLAN.md` and the relevant evidence before changing code. Inspect Git status; preserve all existing dirty work and the adjacent blackjack project. Keep one active packet in `HANDOFF.md` with:

- **Goal:** one concrete behavior or verification result.
- **Relevant files:** exact modules and evidence needed; give workers separate write ownership.
- **Constraints:** architecture, uncertainty/history rules, permission boundaries and what is outside this packet.
- **Acceptance tests:** reproducible commands and what each result would establish.
- **Stop condition:** the bounded result, an unresolved external dependency, or the user's request to checkpoint.

## Execute and review

1. Inspect the implementation and prior measured results. Do not retest an unchanged failure or overwrite historical evidence merely to produce a cleaner report.
2. Build the smallest change in the packet. Keep generated engine assets, native binaries and media outside the source checkout. No automatic installation, browser/device operation, deployment or permission change follows from a source edit.
3. Run affected tests and required project checks. Run `npm test` after code changes; retain the user's authorization boundary for its local HTTP listeners. Use existing direct Swift commands where recorded; do not disable SwiftPM's sandbox to bypass the known manifest failure. Label mocks, synthetic recognition, Mac WebKit execution, iOS compilation and hardware tests separately.
4. Request independent review of the changed code, tests and evidence. Give a fresh worker the packet and relevant files when a new context would reduce confusion. Review does not authorize runtime/browser/device actions. Record concrete findings or “no remaining concrete finding,” and distinguish read-only review from executed checks.
5. Fix actionable findings and rerun affected checks. Broaden testing only for a new change, failure or unresolved concern. If a required external action needs authorization, first prepare the exact reviewable command/artifact; then ask once for that action and retain the answer's scope.
6. Checkpoint: update `HANDOFF.md`, current verification docs, Git status/diff check, source/artifact hashes and saved command/log paths. State unfinished verification and the next bounded packet. Do not claim completion of the live product from a successful software checkpoint.

## Stop without an automatic restart

At a completed packet, save a concise checkpoint and continue the next already-authorized step toward the agreed milestone in the same build session. Stop for completion of that milestone, a genuine unresolved external dependency or approval boundary, or a user request to stop; do not require the dot to relay routine next-step decisions. Do not create an automation, self-restarting loop, agent timer, watcher or controller to resume work. A later user instruction resumes from the saved handoff. Existing application freshness/watchdog code is product behavior, not an agent automation.

Current active/next packet and exact evidence paths live in `HANDOFF.md`; this file is the process, not a second task queue.
