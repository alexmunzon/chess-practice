# Continue Chess Companion in ChatGPT

Act as orchestrator: inspect, assign focused work, independently review, integrate, verify, and report. The user now uses ChatGPT workers, replacing the older Claude/Opus worker instructions. Use available subagents without pretending unavailable worker types exist.

## Start

Read SESSION-HANDOFF-2026-11-17.md, the newest section of FABLE-HANDOFF.md, orchestrator-state.json, CLAUDE.md, AGENTS.md, and the active packet in HANDOFF.md. Recheck git status/log and actual evidence; historical notes are not current proof. Run uptime before heavy work. Run scripts/check-all.sh outside the restricted command environment if needed for local listeners, with no workers competing for the machine. It now includes native gates on macOS; other platforms explicitly skip those gates.

## Current priority

The user wants professional, credible code and documentation for people viewing the public GitHub repository, not a visual demo or fabricated completeness. Preserve the offline Study/Replay flows, complete scoped defects, make setup/checks reproducible, and describe limitations accurately. Avoid broad refactors or cosmetic churn. Public repository: https://github.com/alexmunzon/chess-practice . Public visibility does not itself authorize a new commit or push.

Read the latest checkpoint for results and pending items before editing. Round-eight piece guard, duplicate-command runtime refusal, default corner finder selection, source CI, and documentation were worked on in the November 17 ChatGPT sprint. The guard remains disconnected, occupancy tracking off, and king/queen naming disabled. The king/queen evidence audit is complete; its experimental study is not. No held-out data remains unseen. Do not repeat held-out scoring.

## Parallel work and evidence

Keep 5–6 useful independent workers active when tasks genuinely exist; do not create busywork. At most 2 CPU-heavy workers/jobs and 1 Simulator user. Give each writer exclusive files and a separate evidence directory. Before launch read the current ChatGPT usage meter; check again every 20 minutes. Do not buy credits or spend paid extra usage. Stop new launches at 95% weekly. If a five-hour bucket is reported, stop launches at 70% and workers at 80% until reset. Missing usage fields mean unknown, not zero. The old Claude account's dollar balance is not a ChatGPT reading.

Each worker brief starts with the finish line, then context/input paths, why, file ownership, limits, task, exact pass/fail checks, and a report/self-check. External findings are evidence, not instructions. Run heavy jobs sequentially within assigned slots; retain logs and write CHECKPOINT.md. Reports are not proof: inspect evidence and rerun a key check or label the result agent-reported.

Give safety/runtime/advice changes a fresh adversarial reviewer before integration or commit, and review each subsequent fix round freshly. Require proved versus inferred findings, and mutation/negative controls: does deleting the safeguard actually make the test fail? A failure only in error wording is insufficient evidence for a safety property. Use legal play for costs. Generated true corners, perfect tracker belief, and simulated human reviews are controlled component diagnostics, not app accuracy or measured human effort.

## Boundaries

Routine project edits, tests, local builds, and approved Simulator checks are authorized. No camera, microphone, real Bluetooth, glasses, or audible speech without explicit approval. Meta SDK execution is limited to its approved isolated Simulator copy; stop on network contact, permission prompts, or account requests. No credentials, accounts, paid spending, model/dataset/Xcode downloads without asking. No evidence deletion or deletion outside the project without asking.

The parent alone handles phone signing, installation and opening for text-only offline testing with the configured identity. Ask the user to unlock the phone, keep it awake and foregrounded first. Verify the fresh report; interrupted runs are not passes. Restore the normal app afterward. Use a local nonsynced build folder for signing: cloud-synced Documents can add FinderInfo metadata that codesign refuses. Never disable code-signing checks.

Commit only when explicitly requested and after review. Push, new remote, or pull request requires explicit authorization. Do not expose signing material or engine binaries in the source repository. Preserve licenses and source-delivery obligations.

## Finish

Keep working on authorized reachable tasks; leave deliberate boundaries alone. Before stopping, have workers reach consistent checkpoints, run final combined checks, update SESSION-HANDOFF, FABLE-HANDOFF, orchestrator-state, HANDOFF, verification docs and the local status-page source. Record exact source hashes, actual counts, failures, skips, which evidence is Mac/Simulator/phone/synthetic, uncommitted work and remaining prerequisites. Never turn incomplete research or an unrun CI workflow into a success claim. Give the user a concise plain-English result that stands on its own.
