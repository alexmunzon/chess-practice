# Native synthetic vision

This library takes encoded image bytes and returns a review-only square proposal. Its runtime uses Foundation, CoreGraphics, ImageIO and CryptoKit. The fixed classic-template features are bundled assets made from this project's original vector silhouettes. An iPhone caller needs no Python, Mac service, network or neural model for this recognizer.

It recognizes only the existing synthetic panel with four colored marks and known classic pieces. It does not recognize physical chess pieces or establish turn, rights, counters or repetition. Every result keeps `fen: null`, `guidanceAllowed: false` and `status: needs-human-review`. Native provenance is `pipelineVersion: native-visible-markers-v1` and `nativeImplementationVersion: swift-synthetic-pixels-v1`.

The local Swift package declares minimum iOS 16 and provides `try NativeSyntheticRecognizer.bundled()`; call `try recognizer.recognize(imageData: data)` after initialization. Mac CPU compilation/execution is tested. A direct iOS ARM64 typecheck uses SDK 26.2 with deployment target iOS 16.0; it does not build or install an app. This direct compile mode does not define `SWIFT_PACKAGE`, so the `Bundle.module` accessor and actual package resource copying remain unverified. A caller can supply the fixed asset `Data` explicitly through the tested `NativeSyntheticRecognizer(templateData:)` initializer. No iPhone device test was performed. The CLI below is a development runner, not an iPhone runtime dependency.

From the repository root:

```sh
swiftc -O -module-cache-path /tmp/chess-native-vision-module-cache \
  native/ChessCompanionVision/ImageDecoder.swift \
  native/ChessCompanionVision/PixelFeatures.swift \
  native/ChessCompanionVision/SyntheticRecognizer.swift \
  native/ChessCompanionVision/NativeVisionCLI.swift -o /tmp/chess-native-vision
python3 -B tests/native_vision.py
```

Run `/tmp/chess-native-vision --assets native/ChessCompanionVision/Assets/classic-templates-v1.json IMAGE.png`. Multiple image arguments produce one result per line. The library itself receives only image `Data`; it cannot read filenames, per-frame FEN or evaluator truth.

The recognizer preserves the frozen Python policy: tile RMSE 0.055, runner-up margin 0.012, border RMSE 0.045 and edge ratio 0.40. A binary acceptance score of 1 or 0 is not a calibrated probability. It rejects nonopaque, animated, unsupported or oversized input; valid images with unavailable geometry produce unknown-square placeholders. Input bounds are 8 MiB, 8,192 pixels per side and 25 million pixels total. JPEG/PNG/WebP support depends on native ImageIO; HEIC is outside this synthetic input contract.

The initial Mac replay of the existing 78-PNG corpus compared 4,992 squares with frozen Python: zero decision disagreements and matching geometry availability. Maximum numerical metric difference was approximately 3.61e-15. This is reused-data port conformance, not fresh held-out accuracy or iPhone speed evidence. Local preprocessing comparisons also matched Pillow bytes for 26 templates, four development tiles and six resize cases. ImageIO color-profile conversion/JPEG decoding parity with Pillow remains unverified.

Reproduce the corpus comparison, without reading evaluator truth:

```sh
python3 -B native/ChessCompanionVision/conformance.py \
  --binary /tmp/chess-native-vision --corpus PATH_TO_EXISTING_CORPUS \
  --out /tmp/chess-native-port-conformance.json
```

`export_fixed_templates.py` is a build-time source-to-asset utility. The phone does not execute it. Asset feature bytes are pinned to SHA256 `1dbebf15882b9ea926ac03b0a6ad7ac14092639ae142f53c4624df189d2e6fdb`; unsupported replacements fail closed. No third-party model weights or captured media are included.
