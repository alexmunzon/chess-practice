# ScreenOccupancy: Swift port of rectification + square reader v3 (experiment, not in the app)

**Conventions.** `--corners x,y,...` = 4 board corners exactly as `screen-board-detect` prints them: clockwise
(y down) from the corner nearest the image top-left, image pixel centres at integer coordinates. Corner i goes
to panel corner i of (64,64),(576,64),(576,576),(64,576) of a 640x640 panel (screen-upright, pieces as drawn;
panel pixel edges at integers). `--rotation R` = index of the detector corner that is a8 (the pipeline's
locked rotation, `rotate(corners, R)` = a8,h8,h1,a1). Occupancy and output `labels` are 64 chars in board
order a8..h8,...,a1..h1 (`SQUARES`, e/w/b, `.`/w/b/? out); internally `screen_from_a8(occ, R)` (`np.rot90(-R)`)
gives panel tile order, `screenLabels` is panel order. `--rotation auto` = the pipeline's 4-rotation start test
(accept only if exactly one rotation calibrates). Same as `scripts/recognition/screen_pipeline.py`.

## Python reader v3, step by step (v3.1, frozen sha256 c634a76d...926ee; all 39 policy constants in `policy`)
1. Rectify (screen_pipeline): DLT homography panel->image; k = clamp(ceil(side/512 - 0.05), 1, 3); k x k
   sub-samples at u + (s+0.5)/k, bilinear (x clipped to [0, w-1.001], floor), float32 sum, /k^2 + 0.5, truncate.
2. `_prepare`: raw panel and Pillow `GaussianBlur(1.0)` (extended box blur, 3 passes per axis, box radius 0.25).
3. Tiles 64x64 from (64,64). Masks: BORDER ring (3..7 px in), TOPBOT strips, WINDOW rows 8..57 x cols 12..51.
4. Calibrate: empty refs = median of BORDER|WINDOW pixels of stated-empty light/dark squares (>= 2 each);
   contrast = |lum(light - dark)| (lum .299/.587/.114), >= 10.
5. Local lighting per square: left/right strips (cols 3..7 / 56..60, rows 3..60) row medians - ref, running
   mean 7 rows; fit each row as k*ref + b*grey, |k| <= 0.20, b >= -0.25*contrast (exact active-set LSQ);
   offset = fitted lighting interpolated left->right; shift/step/side/unexplained in units of contrast.
6. Measure: fg = |tile - offset - ref| > 40 in WINDOW (share); border = same on TOPBOT; edges = |dlum/dx| >
   0.22*contrast (share in WINDOW). Fill: if fg >= 40 px, silhouette dilated 2 (4-nbr), holes filled, eroded
   2 (3x3 min), depth by repeated erosion (<= 19); core = depth >= max(2, maxdepth-3), weight depth-floor+1;
   rows >= 46 dropped; needs >= 40 core px.
7. Calibrate: fills of each colour (>= 2 squares); white ref = median of brighter half, black of darker half;
   separation >= 0.35*255; every square must pass the gates (local, saturation, border <= 0.20) and its stated
   cues (fg <= 0.03 & edge <= 0.005 empty; fg >= 0.08 & edge >= 0.015 piece); stated colour wins by >= 0.60 and
   averages >= 0.85 per colour; also boundary sharpness (median near/far step ratio at file boundaries), which
   must be finite and >= 0.05 (v3.1, CAL_SHARPNESS_MIN) or the start is rejected.
8. Classify: stored sharpness missing/NaN/infinite/< 0.05 -> all unknown (v3.1); per-channel gain/offset from BORDER medians (gain 0.33..3.0 else all unknown); sharpness < 0.4 x
   calibration -> all unknown; measure every square on the gain-corrected tile; gates: local shift > 0.60,
   step > 0.12, side > 0.40, unexplained > 0.30, saturation (> 5 % clipped unless calm <= 0.15 and ring <= 2 %),
   border > 0.20, a neighbour with a sharp lighting edge, cues disagree, colour share < 0.75 or median distance
   > 70. Confidence = min of scaled scores; any gate or < 0.5 -> unknown.

## Files and build (outputs outside the repo)
`OccupancyImage.swift` (ImageIO decode, raw bytes, no colour conversion = Pillow), `PanelRectifier.swift`,
`PillowBlur.swift` (bit-exact Pillow blur), `OccupancyReaderV3.swift` (the reader), `OccupancyJSON.swift`,
`OccupancySelfTest.swift`, `main.swift` (CLI), `conformance.py`. Reuses `../ScreenBoardVision/Homography.swift`.
```sh
B=/Users/alexmunzon/chess-builds/screen-occupancy-swift-2026-11-16
swiftc -O ../ScreenBoardVision/Homography.swift OccupancyImage.swift PanelRectifier.swift PillowBlur.swift \
  OccupancyReaderV3.swift OccupancyJSON.swift OccupancySelfTest.swift main.swift -o $B/bin/screen-occupancy
$B/bin/screen-occupancy --self-test        # 14 unit checks
$B/bin/screen-occupancy calibrate --image START.png --corners x,y,x,y,x,y,x,y --rotation auto --fen FEN --out cal.json
$B/bin/screen-occupancy classify --image F.png --corners ... --rotation R --calibration cal.json
$B/bin/screen-occupancy batch --jobs jobs.jsonl  # {"op":"calibrate"|"classify","id",...,"calibrationRef":id}
python3 -B native/ScreenOccupancy/conformance.py --binary $B/bin/screen-occupancy --out $B/conformance [--determinism|--controls]
xcrun --sdk iphoneos swiftc -typecheck -target arm64-apple-ios17.2 -module-cache-path $B/modcache-ios \
  ../ScreenBoardVision/Homography.swift OccupancyImage.swift PanelRectifier.swift PillowBlur.swift \
  OccupancyReaderV3.swift OccupancyJSON.swift OccupancySelfTest.swift   # iOS type-check (v3.1 run)
```
`--panel P.png` replaces image + corners (already rectified). Timings: decode, rectify, blur, classify, and
thread CPU time of rectify+classify. Calibration JSON has Python's keys (Python's file is accepted too).

## Deliberate deviations (results unchanged unless stated)
- Homography: ScreenBoardVision's normalised DLT instead of numpy SVD (same 4-point solution, ~1e-12 px).
- Rectify loops per pixel with sub-samples in Python's order (same float32 additions); blur only on the
  board + 3 px margin with a closed-form radius-0 path (self-test: equal to whole-panel Pillow blur there).
- `_fill_holes` as breadth-first flood capped at 256 steps (= Python's iterative growth); dot products and
  sums in plain order (numpy may use BLAS/pairwise: last-bit differences); output rounding half-away-from-0.

## Results (simulated pictures, true corners, development splits only; see REPORT in the build folder)
2026-11-16, Apple M1, `swiftc -O`, Swift 6.2.4. smoke/dev/smoke2/dev2: 56 start pictures, start decisions
identical 56/56; 1516 pictures, 97,024 squares, labels identical 100 % (0 Swift-unknown/Python-confident, 0
reverse, 0 confident-different); wrong vs truth 0 (Swift and Python); Swift on Python's panel + calibration:
0 differences. Panels: max 1 grey level on 1e-6 of pixels (homography last bits); calibrations identical.
Negative controls (4 dev starts x 11: square off, swapped colours, 3 wrong rotations, turned panel, hand,
glare): all rejected like Python. Determinism: 2 runs over dev byte-identical. Speed, dev 1920x1080 (load 12-18):
rectify+blur+classify median 31 ms, p95 67 ms wall (CPU 29 / 44); rectify 15 + classify 14 dominate; decode 44.

v3.1 rerun (2026-11-16, sharpness-reference fix, build in `chess-builds/classifier-v3-edgefix-2026-11-16/`): policy 39/39
equal; same 56 start decisions identical, 1516 pictures 100 % identical labels, 0 confident disagreements, 0 wrong.
Not verified: held-out data (never read), real camera footage, the app, an iPhone (iOS type-check only).
