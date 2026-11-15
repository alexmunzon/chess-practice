# Glasses SDK research — November 15, 2026

Web research by a subagent (no downloads or sign-ups). Claims are the agent's reading of the linked pages; not re-verified by the orchestrator.

## Meta DAT research for Ray-Ban Meta Gen 1 live capture (checked 2026-11-15)

**Short answer:** Gen 1 is officially supported, and **1.0.1 is still the newest release**, so the pin is current. The 1.0.1 iOS changelog says "No developer-facing changes." The biggest finding is about timing. Each video frame carries a timestamp from the **glasses' clock**, and the SDK does not convert it to the phone's clock. Meta documents no way to tell how old a frame is in phone time, so the app has to measure that itself. The issue where streaming silences phone audio is **still open with no fix**.

### 1. Device support and setup
- Ray-Ban Meta "Gen 1 and Gen 2" are listed as supported. Meta also says "capability availability varies by device," and neither page lists Gen 1 limits ([FAQ](https://developers.meta.com/wearables/faq/), [Setup](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/getting-started-toolkit)).
- Minimum versions for DAT 1.0.1: **Meta AI app V292** and **glasses firmware V128** ([version dependencies](https://wearables.developer.meta.com/docs/version-dependencies)). This page was readable this time; the local notes say it was login-gated before. It also warns that some capabilities are turned on per user from Meta's side, so the app can get `CAPABILITY_DENIED` even with the right versions.
- Regions: full capabilities only in "AI glasses supported countries," and the page does not list them ([FAQ](https://developers.meta.com/wearables/faq/)).
- Developer Mode is switched on in the Meta AI app, not on the glasses: Settings > App Info, tap the version number 5 times, turn on the toggle ([Setup](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/getting-started-toolkit)).
- In Developer Mode, "Registration always allowed": with no Meta app ID (or app ID 0), the SDK skips its app-identity check. Registration needs an internet connection and the Meta AI app installed. The wearer approves the app inside Meta AI with "Allow once" or "Allow always" ([permissions skill](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/plugins/mwdat-ios/skills/permissions-registration/SKILL.md)).
- **Unclear:** the standalone-photo guide says the app needs "Camera approval in Wearables Developer Center" ([camera-capture](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/plugins/mwdat-ios/skills/camera-capture/SKILL.md)). I could not confirm whether that also applies to video streaming in Developer Mode.
- Costs: Meta mentions no fees. A free Apple account ("Personal Team") can install on up to 3 devices, and the signing expires after 7 days ([Apple](https://developer.apple.com/support/compare-memberships/)).

### 2. Video stream facts
- Sizes are 720x1280, 504x896 and 360x640. Frame rates are 2/7/15/24/30. The default is raw frames, medium size, 30 FPS ([camera-streaming](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/plugins/mwdat-ios/skills/camera-streaming/SKILL.md)).
- The stream travels over Bluetooth. When bandwidth is short, the SDK lowers size first, then frame rate, never below 15 FPS. Meta says lower settings give *better* image quality because there is less compression (same source).
- Two formats: raw frames (decoded for you) or compressed HEVC (`hvc1`). Raw frames pause when the app goes to the background; HEVC keeps running ([changelog 0.5.0](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/CHANGELOG.md)).
- Battery and heat show up only as errors (`thermalHot`, `batteryLow`, `peakPowerLimit`) with no thresholds given ([1.0.1 interface](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/1.0.1/MWDATCamera.xcframework/ios-arm64/MWDATCamera.framework/Modules/MWDATCamera.swiftmodule/arm64-apple-ios.swiftinterface)).
- Maximum session length: **not found**.

### 3. Timestamps (key question)
- In 1.0.1, `VideoFrame` exposes only the standard iOS frame container (`sampleBuffer`). There is no separate capture-time or latency field. Audio frames have a `presentationTimeStamp`, and still photos carry a `timestamp` date (same interface file).
- Meta, Oct 20, 2026: both audio and video timestamps "come from the glasses' clock and are not rebased on the phone." Neither marks when the phone received or decoded the frame. Meta was "still confirming" which moment the video timestamp marks ([#347](https://github.com/facebook/meta-wearables-dat-ios/issues/347)).
- The same issue (DAT 1.0.0, open) measured audio timestamps about 200 ms later than video. Meta called it a real bug and said any fix will be announced in release notes.
- There is **no documented way** to bound frame age against the phone's clock. Your current design (`unknownDAT(mediaPTS:)`, no conversion to phone time) matches the documentation.
- No glasses-to-phone latency figure was found from Meta or from developer measurements.
- Freshness hazards reported by developers:
  - On 0.9.0, video could silently stop arriving while every status still showed healthy ([#287](https://github.com/facebook/meta-wearables-dat-ios/issues/287)). Meta says the root cause is fixed in 1.0.0/1.0.1, but decode failures still raise no error.
  - On Android, frames queued up during a microphone-route pause and played back late ([Android #159](https://github.com/facebook/meta-wearables-dat-android/issues/159)).

### 4. Audio while the camera streams
- [#358](https://github.com/meta/meta-wearables-dat-ios/issues/358) is **open**, with no fix version. It was reported on Gen 2, DAT 1.0.1, over Wi-Fi.
  - Meta (Oct 22): the SDK has no API for playing sounds on the glasses, and the glasses themselves decide to pause phone audio.
  - Suggested workarounds: phone vibration, the in-stream photo's shutter chime, and double-tap input.
- [#256](https://github.com/meta/meta-wearables-dat-ios/issues/256) is **open**. Meta (Aug 12) confirmed that pausing phone audio and never resuming it is a bug, and there is no fix yet. The report says "Ray-Ban Meta" without a generation.
- Meta's known-issues page also lists: on **iPhone 17 with iOS 26**, calls routed to the glasses (the two-way headset mode) may have no audio in either direction ([known issues](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/knownissues)). That matches the owner's phone family; the owner is on iOS 27.2, which the note does not mention.

### 5. Still photo vs video stream
- Two still-photo paths exist:
  - In-stream `capturePhoto` returns a JPEG or HEIC while the stream keeps running.
  - Standalone `camera.photo` offers sizes small/medium/large/full and quality low/medium/high. It is **experimental**: allowed for development and beta, not production. It cannot run while a stream is active ([camera-capture](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/plugins/mwdat-ios/skills/camera-capture/SKILL.md)).
- Pixel sizes for the photo options: **not found**.
- Reported timings: an in-stream photo took about 1.3 s, and 7–8 s over Bluetooth Classic ([#358](https://github.com/meta/meta-wearables-dat-ios/issues/358)). On 0.9.0, an in-stream photo during a raw stream froze video ([#287](https://github.com/facebook/meta-wearables-dat-ios/issues/287)).
- Known issue: camera capture fails after updating to firmware v128 on Dev/Beta ([known issues](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/knownissues)).
- Whether a photo reads a chess board better than stream frames: not documented. A stream frame is at most 720x1280, so a full-size photo is likely sharper, but that is my inference and untested.

### 6. Limitations, mock device, terms
- Mock Device Kit ([iOS guide](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/testing-mdk-ios)) can:
  - pair a mock Ray-Ban Meta;
  - feed a video file or image as the camera;
  - simulate power, wearing and folding (folding ends the stream) and touchpad taps;
  - run in Simulator UI tests.
- Mock Device Kit limits:
  - The guide does not cover latency, connection drops or audio.
  - 1.0.0 added mock battery and heat setters ([changelog](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/CHANGELOG.md)).
  - Meta's FAQ says it can simulate permissions ([FAQ](https://developers.meta.com/wearables/faq/)).
- Other reported failures:
  - A stream can sit waiting for the glasses forever.
  - One tap on the glasses touchpad pauses the stream.
  - Streams started while the glasses are off the face pause until worn ([debugging](https://raw.githubusercontent.com/meta/meta-wearables-dat-ios/main/plugins/mwdat-ios/skills/debugging/SKILL.md)).
  - Stream starts get refused after minutes of use. This was on Optics (Gen 3) glasses ([#375](https://github.com/meta/meta-wearables-dat-ios/issues/375)), not Gen 1.
- Acceptable Use Policy (updated Sep 22, 2026) bans:
  - bypassing or obscuring the recording LED;
  - covert recording;
  - identifying people by face or voice ([AUP](https://wearables.developer.meta.com/acceptable-use-policy)).
- Meta reviews apps and can revoke access "without prior notice" ([acceptable use](https://wearables.developer.meta.com/llms.txt?product=all&version=1.0&document=products/dat/sections/guides/acceptable-use)). Nothing found about games or real-time assistance.

### 7. Owner checklist (before a first glasses test)
**Free, no glasses needed:**
1. Build and run against Mock Device Kit in Simulator with a recorded board video: test pausing, folding, permission denial and discarding stale results.

**Free, with glasses:**
2. In Meta AI, check the glasses firmware (≥V128) and the app version (≥V292). Mind the v128 camera known issue.
3. Turn on Developer Mode in Meta AI.
4. Sign the build with a free Apple account; it must be reinstalled every 7 days.
5. Approve the app in Meta AI ("Allow once").
6. Test the stream, then the audio: does speech play while streaming, and after the stream stops?

**Possibly paid:**
- The Apple Developer Program, only if the free signing limits or background modes block the test. The price is not verified.

### Not verified
- Apple Developer Program price (about $99/year, from memory).
- Whether background modes and the accessory protocol work with free Apple signing.
- Whether Developer Mode camera streaming needs Developer Center approval or a Meta account.
- Pixel sizes of photo resolutions, and Gen 1 camera specs.
- Supported countries.
- Any glasses-to-phone latency figure.
- Max session length.
- Gen 1 behaviour for #358/#256.
- Whether Gen 1 supports the Wi-Fi transport.
- Whether 1.0.1 fixes the 200 ms timestamp offset (#347 tested 1.0.0).
- iOS 27 compatibility.
