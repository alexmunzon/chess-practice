# Chess Practice development instructions

The user pivoted the glasses practice project from blackjack to chess on November 10, 2026. Preserve ../blackjack-practice and its experimental worktrees. This repository contains the new chess prototype.

Keep the app for private, consensual practice. Current scope is local software, tests, prerecorded public images and simulated observations. No deployment, push, new spending, credentials, developer accounts, live camera/microphone/Bluetooth or physical glasses operations are included in this milestone.

Require human confirmation of complete position and historical game state. Board pixels alone cannot establish turn, castling, en passant or repetition history. Position changes, uncertain observations and interruptions must invalidate guidance. Never claim perfect play or hardware validation from bounded engine or synthetic tests.

Use project-local pinned official-registry dependencies and preserve notices. Keep evaluation source provenance; do not include licensed source media/derivatives in delivered code. Browser screenshots of this project's own UI are acceptable test evidence. Do not ship Stockfish binaries until corresponding-source delivery obligations are verified.

Run npm test after changes. Run the separate macOS calibration tests when modifying vision code. Keep actual recognition, manual setup and synthetic labeled observations clearly distinguished. Consult docs/PLAN.md, docs/VERIFICATION.md and docs/REUSE.md for current scope and known limits.

Use the existing bounded build/test/review/checkpoint process recorded in docs/WORKFLOW.md. Read HANDOFF.md before resuming, keep one active task packet there, and save evidence and unresolved issues before stopping. Do not install an autonomous controller or self-restarting agent loop.
