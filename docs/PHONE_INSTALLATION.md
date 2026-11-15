# iPhone installation — November 15, 2026

All five kit stages completed: preflight, provision, sign, install and launch. The installed app is Chess Companion 0.1.0, build 1 (`local.chesscompanion.offlinestudy`) on the actual iPhone 17 running iOS 27.2 (24B119). After approving developer trust, Alex confirmed it opens and stays open. He then reported closing/swiping it away, consistent with its absence from the later process list; no crash was established. Launch verification is based on the accepted CLI request plus Alex's direct observation, not a positive process-list match.

## What changed

Alex signed into Xcode himself and explicitly approved the Personal Team labelled Peter Munzon (FBYX5879MJ) for registering this phone/app and creating the development certificate/profile. Automatic provisioning created a valid Apple Development identity. Initial profile creation failed because Xcode's iOS platform package was not installed. Installing the official iOS26.2 + iOS26.3.1 Simulator package made the exact phone destination available. Provisioning then succeeded without recreating the certificate.

The actual profile passed 40 binding/resource checks. The signed copy passed 29 product checks, including actual certificate fingerprint, signed entitlements, embedded profile and all resources. The unsigned original was preserved. Phone inventory succeeded before installation (no existing chess bundle) and afterward (exact installed app/version). Initial launch was denied by iOS security; after Alex confirmed developer trust, launch was accepted and Alex confirmed sustained opening.

## Artifacts and evidence

Persistent private output: `/Users/alexmunzon/chess-builds/iphone-2026-11-15/`.

- `unsigned/ChessCompanion.app`: unchanged prepared original.
- `signing/ChessCompanion.app`: exact verified signed artifact installed on the phone.
- `signing/profile.mobileprovision` and `entitlements.plist`: actual development provisioning material; no private signing key is copied.
- `evidence/journal.json`: stages, approvals, outcomes and limitations.
- `evidence/profile-validation.json`, `signed-product-validation.json`: binding/resource checks and hashes.
- `evidence/install.log`, `apps-before-install.json`, `apps-after-install.json`: actual installation evidence.
- `evidence/launch.log`, `launch-after-trust.log`: denied and accepted launch requests, preserved separately.
- `evidence/attempt1-provision.log`, `attempt1-provision2.log`, `provision-driver-attempt2.log`: initial failures and successful retry evidence.

The profile expires **November 22, 2026 at 15:22 Europe/Madrid**. Renewal uses the same kit and existing Xcode account. Preserve the unsigned copy; verify current target/identity/profile before signing and installing again. Temporary execution output is also retained at `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-phone-signing-js8mq6y8/`.

## Next phone acceptance

In Chess Companion: select a position, explicitly start the local engine, read the board, inspect the proposals, supply/load complete FEN, check all five review groups, validate and analyze. Exercise all four playable fixtures plus obstruction, invalid input, review revocation, reset and background/position switching. Record actual phone responsiveness and outcomes.

This operation verifies installation and user-observed opening, not physical-phone recognition/engine end-to-end acceptance, performance, exact in-flight switch behavior, glasses capture, capture-age accuracy or audible speech. Those remain separate. No app source change, commit, push, distribution, private-key export, camera/microphone/Bluetooth or audible-output action occurred. A crash-file query found no matching top-level Chess Companion filenames; it does not rule out other termination logs.
