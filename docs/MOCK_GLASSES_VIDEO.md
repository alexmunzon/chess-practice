# Mock-glasses test video (Phase 2 of MOCK_DEVICE_KIT_PLAN.md, 2026-11-15)

Turns this project's own synthetic frames into the only format Meta's simulated glasses accept:
HEVC in .mp4, tag `hvc1`, yuv420p, portrait 720x1280 (or 504x896), 30 fps, no audio track. Each
source frame (manifest play order, interruption frames included) is held 2 s (`--hold`), scaled to
a centred square board, with neutral gray (128) bands above and below. Videos stay outside the repo.

## Frame-index code ("nonce")

Both bands carry the same 16x4 grid of black/white blocks (40 px at 720 wide, i.e. width/18, so
20 px after a 360x640 downscale), well clear of the board. Row 0 is a start pattern (BWBW...),
row 3 a stop pattern (WBWB...), rows 1-2 hold 16 Manchester bits (1 = black,white; 0 =
white,black): the 8-bit source frame index, then its CRC-8 (poly 0x07, init 0xFF). The reader
samples each block's centre and abstains on any gray block, broken pair, bad start/stop, bad CRC
or top/bottom disagreement, so blur, a 50/50 blend or a torn frame gives "no reading", not a
wrong index. The index is the number in the source file name (frame-026 is 26).

## Commands

```sh
O=/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15/phase2
python3 -B scripts/simulation/make-mock-glasses-video.py --all "$O"      # 4 videos, libx265
python3 -B scripts/simulation/verify-mock-glasses-video.py "$O/replay-14.mp4" \
  /Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/sequence/replay-manifest.json \
  [--downscale 360x640] [--avfoundation] [--json report.json]
python3 -B tests/mock_glasses_video.py     # opt-in; prints SKIP without ffmpeg or frames
```

Verifier PASS = every decoded frame has a valid nonce equal to the slot's source index
(slot = frame / (fps x hold)), board mean absolute error <= 6 (0-255) against the scaled source
PNG, nearer to it than to any other distinct source (count of pixels off by > 48, since one
moved piece shifts global MAE only 0.1-0.3), frame count exact, hevc/hvc1/yuv420p, no audio.
Hold-boundary frames are reported separately. Tests: heavy blur, 50/50 blends, flipped CRC/data
bits, one corrupted copy and a torn frame are rejected; a blur sweep never yields a wrong index;
wrong-order and right-nonce-wrong-board videos fail.

## Measured

Encoder `libx265` (crf 20, keyint 60). Two `--all` runs gave byte-identical files (SHA-256 in
`$O/SHA256SUMS.txt`; replay-14 `cf99c666…`, special-game `051666c9…`). VideoToolbox not used.
All 8 checks PASS (2 games x 720x1280/504x896 x native/360x640): 900 and 1680 frames, board MAE
<= 1.8 native, <= 2.8 at 360x640; AVFoundation reads each as `hvc1`, 30 fps, 0 audio tracks, all
frames decoded. Evidence: `$O/reports/` (verify.log, per-video JSON, probe.json, tests.log).
The special game plays 0..20, 26, 21, 22, 27, 23..25 (28 slots, 56 s); replay-14 is 15 slots, 30 s.

## Limits

`ffprobe` is not installed here; the verifier falls back to ffmpeg's stream banner plus its own
MP4 box walk (handler, sample-entry fourcc, sample count). `--downscale` scales at decode time
(bilinear), no re-encode. Meta's mock kit acceptance is untested until Phase 3/4. Synthetic only.
