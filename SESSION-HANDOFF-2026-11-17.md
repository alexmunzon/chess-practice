# Verified build checkpoint — 17 November 2026

Prepared 17:18 Madrid. User priority: credible, professional code for the public GitHub repository. All workers have finished and written checkpoints. The user explicitly requested committing/pushing all progress after tests; publication follows this verified checkpoint. Git history and remote main are authoritative for the resulting commit.

## Completed

- Piece guard round eight: completed and independently reviewed as an unconnected component. Claimed-empty squares require empty evidence; claimed-occupied squares cannot read empty; refusal preserves the baseline. The combined guard suite passes 36/36. Kings/queens still cannot be identified; the guard remains disconnected.
- Native runtime: duplicate top-level command keys are refused and revoke tracker trust, including escaped keys. Fresh adversarial review accepted the fix. Actual compiled app-adapter setting checks replace the former source-text test. Native gates pass 26/26 and now run from check-all on macOS.
- Corner finder: reviewed round two is the default; original remains selectable. Explicit custom detectors work without private default binaries and report their own provenance. Pipeline tests pass 51/51. All four development reruns match earlier explicit-round-two results: 376/376 JSON files after excluding timing/debug paths. No new accuracy claim or held-out scoring.
- Freshness simulation: 16/16 tests, fresh independent review, parent rerun 1,211/1,211 gate/counter cases and 4/4 injected defects caught. Simulation only; no real-glasses validation.
- Public repository: clear README, setup prerequisites, pinned Python test dependencies, least-privilege GitHub source-check workflow with immutable action pins, portable native check outputs, corrected plan/verification/engine explanations. No visual redesign remains.

## Verification

Parent's final scripts/check-all.sh: **12/12 suites passed** on the frozen reviewed source. npm: 397 tests, 389 pass, 0 fail, 8 skip. The v4 reader retains one expected failure for its documented limitation. Parent also checked 4/4 main-command dispatch/failure-propagation cases, 12/12 CI configuration/metadata cases, and relative documentation targets.

Real iPhone: updated self-test and normal builds compiled. Final text-only run passed **34/34**, with zero speech requests; normal updated app restored. One earlier launched run was interrupted by inactivity and is not a pass. An earlier signing attempt failed before installation because cloud-folder Finder metadata contaminated the generated bundle; hash-verified temporary copies resolved it. The build wrapper also had an empty-array shell error after the self-test build; corrected, then normal build compiled. These failures remain in the evidence.

Mac reviewers: guard 295/295 contracts and 5/5 injected defects; 12/12 legal-capture image cases versus 0/12 refusals on old code. Runtime 26/26 expanded checks with 24 added edge cases, plus bypass mutation caught; builder 4/4 mutants caught. Corner 4/4 independent checks and 3/3 mutations. Parent reran guard contracts and corner CLI checks. Image diagnostics use generated true/jittered corners and simulated review: not physical-board or observed human-effort evidence. Legal-play component cost remains 50/320 withholds (21 king, 20 queen, 7 castling, 2 queen promotions), 50/50 simulated re-baselines accepted.

## Remaining limits and decisions

Keep occupancy tracking off, piece guard disconnected and king/queen naming disabled. King/queen evidence audit is complete; the experimental study remains incomplete and its oracle-corner/constructed-swap numbers are not app accuracy. Lens correction, motion blur and fresh generalization claims need new appropriate inputs. No unused held-out set remains. Simulator engine freezes are parked with cause unresolved; they are not established slow searches or a load-caused bug. No camera, microphone, Bluetooth, real glasses or audible speech was used. Hosted Linux CI is separate from local tests; inspect GitHub Actions after publication. No engine/app binaries or signing material belong in the public repository.

Evidence root: /Users/alexmunzon/Documents/Codex/2026-11-17/pr/work
- final-check/summary.log and per-suite logs; final-native/run.txt
- guard-build/, guard-review/, parent-guard-check/
- runtime-build/, runtime-review/
- corner-default/development-summary.json and corner-review/
- freshness-review/, parent-freshness-check/
- phone-build/phone-run3.log and phone-run3-evidence/
- kq-study/DECISION.md; ui-polish/REPORT.txt; check-all-contract/results.json

All older handoff sections are historical; this checkpoint supersedes their pending-state claims. No jobs remain running. Future commits/pushes require their own user authorization.
