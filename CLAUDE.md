# Chess Practice (Claude orchestration notes)

Home of the project since 2026-11-15: `/Users/alexmunzon/chess-practice`. It was copied from
`/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice`, which is left untouched as a
backup. Older docs still cite that Codex path and Codex evidence folders; those citations are
historical records and stay as written. Evidence folders under `/Users/alexmunzon/Documents/Codex/`
are read-only history.

Read first: `FABLE-HANDOFF.md` (current state, in-flight work, backlog, how to run a session and
the worker brief template), then `AGENTS.md` (safety and scope rules, still binding),
`docs/PLAN.md`, `docs/VERIFICATION.md`. `HANDOFF.md` is the long append-only evidence log.
`NEXT-SESSION-PROMPT.md` is the prompt Alex pastes to start a new orchestrator session.

## Check command

```sh
scripts/check-all.sh
```

It runs `npm test` and the Python recognition tests and ends with "n of m suites passed"
(`--quick` runs only `npm test`). Status that a new session should read first and then re-check
is in `orchestrator-state.json`.

`npm test` on its own is the Node suite. Expected: 0 failures (346 tests, 338 pass, 8 skipped as of 2026-11-16 04:42; the count rises as
new test files land). It opens local listeners on 127.0.0.1, so it fails with `listen EPERM`
inside the command sandbox; that is the sandbox, not the code.

`npm test` does not run the Python tests. After touching recognition code also run:

```sh
python3 -B tests/screen_pipeline.py
python3 -B tests/occupancy_classifier_v3.py
python3 -B tests/occupancy_classifier_v4.py
python3 -B tests/occupancy_classifier.py
python3 -B tests/screen_game_scenes.py
python3 -B tests/mock_glasses_video.py
python3 -B tests/mock_glasses_frame_age.py
```

## Phone install

The app was signed and installed on Alex's iPhone 17 (iOS 27.2) on 2026-11-15; see
`docs/PHONE_INSTALLATION.md`. Signed and unsigned copies plus evidence live outside the repo in
`/Users/alexmunzon/chess-builds/iphone-2026-11-15/`. The free provisioning profile expires
2026-11-22; after that the app will not open until it is re-signed and reinstalled with
`native/ChessCompanionApp/signing/sign_and_install.sh`.

## Ownership

Fable orchestrates: plan, priorities, integration and review. Subagents get one focused task and
their own files to write. Work is committed on `main` in checkpoints (latest `46ce560`, 2026-11-16),
but workers usually have uncommitted files in flight, so a git worktree would miss those; isolate
agents by giving each its own files or directory to own, never two writers on one file, and keep
build outputs outside the repo. Only one worker at a time uses the iOS Simulator, and heavy render
or engine jobs are capped at 2 processes each: on 2026-11-15 a load average of 250+ made Simulator
engine deadlines fail.

Session rules from the 2026-11-16 process review (details in `FABLE-HANDOFF.md`): keep 5-6 workers
busy, at most 2 CPU-heavy and 1 on the Simulator; on every worker report launch each backlog item
whose inputs exist and whose files are free; give every safety module its own adversarial reviewer
before wiring it in, committing it or quoting its numbers; report every run as "n of m passed";
scoring may use only what the app knows at runtime; refresh docs last.

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
