# Public video candidates — November 11, 2026

These are source candidates, not an evaluation set. Connected Firecrawl search/page retrieval found the source and license pages without browser access. Initial ordinary downloads failed at DNS resolution. After explicit user approval, one additional bounded network-enabled download was attempted for each exact source URL; **both returned HTTP 403 Forbidden**. Those acquisition routes are closed, with no further retry or bypass. No media was acquired and no frames were inspected, labeled or scored; geometry suitability, canonical orientation and upstream model training overlap remain unknown.

The named authors and source URLs differ from this project's existing Staxringold, Bin im Garten and Michael Maggs photos and Tima Miroshnichenko/Yaroslav Shuraev videos. That establishes separation from those project sources only, not exclusion from upstream model training.

## Candidates and permissions

| Candidate | Published source facts | License | Inspection/acquisition |
| --- | --- | --- | --- |
| [Putting Chess Pieces In a Chessboard](https://www.pexels.com/video/putting-chess-pieces-in-a-chessboard-6058636/) by [Vlada Karpovich](https://www.pexels.com/@vlada-karpovich/) | Source page: Dec 2, 2020; 12 seconds; 1920×1080; 25 fps. Page describes an overhead arrangement of a physical board. | [Pexels License](https://www.pexels.com/license/). Free use/modification with restrictions including unaltered resale, implied endorsement, stock redistribution, offensive portrayal and trademark use. Not CC0. | Download failed. No actual frame inspection; an overhead description does not prove four visible corners or readable pieces. |
| [Joaquin Perkins blitz chess vs USCF expert](https://commons.wikimedia.org/wiki/File:Joaquin_Perkins_blitz_chess_vs_USCF_expert.webm) by Keleperkins, declared own work | Source page: May 9, 2014; 20.449 seconds; 800×480; 5,888,660 bytes. Real-game excerpt according to the page. | [CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/deed.en). Attribution, license link and change indication; distributed adaptations require the same or a compatible license. | Download failed. Lower published resolution may limit labeling; no frame inspection proves suitability. |

Exact published media links:

- [Pexels MP4](https://videos.pexels.com/video-files/6058636/6058636-hd_1920_1080_25fps.mp4), recovered from the source page's explicit file-url parameter; no external editor interaction or terms acceptance.
- [Commons original WebM](https://upload.wikimedia.org/wikipedia/commons/d/de/Joaquin_Perkins_blitz_chess_vs_USCF_expert.webm?utm_source=commons.wikimedia.org&utm_campaign=index&utm_content=original), linked by the Commons file page. Published SHA-1 `910919c9c3f442c85d1388f85576956ee4ffa320` has **not** been locally verified.

Pexels 6058632 is another clip by the same author and may be from the same shoot; do not treat it as an independent held-out source from 6058636 without evidence. It was not downloaded.

## Exact acquisition outcome

The first native attempt for each source returned `URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`. No cause beyond that DNS error was established. The user subsequently authorized the two exact downloads through a network-enabled command, bounded to 80 MiB per source and written outside the repository. That authorized follow-up made one attempt per URL and returned `HTTP Error 403: Forbidden` for both (Pexels 78.55 ms; Commons 196.82 ms). The reason for the server refusal was not diagnosed. No further retries, alternate URLs, browser fallback, authentication or restriction bypass followed.

The session's `recorded-input-2026-11-11/source-candidates.json` preserves curated source/license metadata and initial outcomes. The [approved acquisition record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/completion-build-2026-11-11/approved-media-acquisition.json) records the subsequent HTTP 403 results and exact requested URLs. There is no local media hash, inspected timestamp, frame, ground-truth label, recognition score or glasses result for either candidate. Successful metadata retrieval does not establish access to media bytes.

## Next evaluation boundary

The user has no physical chessboard, so the immediate path is [synthetic image/video development](SIMULATION_PLAN.md). The closed public-download routes do not block that work. They remain unavailable candidates for a separate future test of physical generalization; synthetic results cannot replace that evidence.

For any later accessible, lawfully usable real recording, hash the actual file and inspect fixed timestamps before classifier prediction. Include visible four-corner boards for geometry comparison and preserve partial/hand/motion frames separately as abstention challenges. Establish canonical orientation from visible evidence; otherwise mark it unknown. Freeze independently reviewed labels, corners, timestamps and source-level split before inference. Unknown or occluded squares stay unknown. Do not derive legal history from pixels or engine plausibility.

The original Apple Vision detector retains its previously recorded runtime failure and was **not retried** in this follow-up. The manual-corner photo workflow is now implemented and covered by software tests; that does not supply missing footage or validate recognition accuracy. If only manual-corner inference is run on future footage, label the automatic arm **not run**, not an abstention. Both automatic and annotated-corner arms must eventually use the same unchanged classifier/preprocessing for a valid geometry comparison. No model threshold has been tuned on these unacquired candidates.
