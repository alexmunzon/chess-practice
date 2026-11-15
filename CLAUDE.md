# Chess Practice (Claude orchestration notes)

Home of the project since 2026-11-15: `/Users/alexmunzon/chess-practice`. It was copied from
`/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice`, which is left untouched as a
backup. Older docs still cite that Codex path and Codex evidence folders; those citations are
historical records and stay as written. Evidence folders under `/Users/alexmunzon/Documents/Codex/`
are read-only history.

Read first: `AGENTS.md` (safety and scope rules, still binding), `HANDOFF.md` (the last section is
the active task packet), `docs/WORKFLOW.md`, `docs/PLAN.md`, `docs/VERIFICATION.md`.

## Check command

```sh
npm test
```

Expected: 0 failures (184 pass, 2 opt-in skipped as of 2026-11-15). It opens local listeners on 127.0.0.1, so it fails with `listen EPERM`
inside the command sandbox; that is the sandbox, not the code.

## Phone install

The app was signed and installed on Alex's iPhone 17 (iOS 27.2) on 2026-11-15; see
`docs/PHONE_INSTALLATION.md`. Signed and unsigned copies plus evidence live outside the repo in
`/Users/alexmunzon/chess-builds/iphone-2026-11-15/`. The free provisioning profile expires
2026-11-22; after that the app will not open until it is re-signed and reinstalled with
`native/ChessCompanionApp/signing/sign_and_install.sh`.

## Ownership

Fable orchestrates: plan, priorities, integration and review. Subagents get one focused task and
their own files to write. Most of the work is uncommitted on `main` (one commit only), so a git
worktree would be missing nearly everything; until a checkpoint commit exists, isolate agents by
giving each a separate new directory to own, and keep build outputs outside the repo.

Alex's instruction (2026-11-15): run several subagents in parallel on Opus 5.5 at medium effort.
Every brief follows five parts: (1) goal and limits, (2) "done" as pass/fail checks, (3) small
tasks each with a success check, (4) do the work, run the checks, fix failures inside the agreed
scope, (5) report the result, the check output and anything not verified.

## Standing boundaries

- No push, deploy or distribution. No commit unless Alex asks.
- Agents never enter credentials, create accounts, spend money or change permanent settings.
- Approved: Simulator testing; inspecting the connected iPhone and existing signing setup; signing,
  installing and opening the private offline app for text-only testing with an already configured
  identity.
- Not approved: camera, microphone, Bluetooth, glasses capture, audible speech.
- Generated binaries and engine assets stay outside the repo.
