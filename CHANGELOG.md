# Changelog

User-facing changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project does not use semantic version tags yet.

## Unreleased

### Changed

- The map has a third basemap: **Vector** tiles (CARTO Dark Matter). Unlike the two Esri rasters it is geometry and labels, so coastlines and place names stay sharp however far you zoom instead of upscaling imagery — and it is the lightest of the three, so a slow connection now opens the console on it, with a `Slow link` hint explaining the choice. Every basemap remains one click away, and a failed fetch returns you to the imagery with the reason shown on the button.
- The map's view controls (Satellite/Terrain, Globe view, Fly to AOI, Reset orbit, Auto-rotate) now sit in one bottom-left column directly under the day/hotspot readout instead of in a separate cluster, and the column is lifted by the measured height of the Esri attribution notice so the two can never overlap — including when the notice wraps to several lines on a narrow window. The notice also paints above the map chrome.
- Dragging, rotating and zooming the map is cheaper on every basemap: the canvas render ratio is capped at 1.5× (1× on a low-end device), MSAA and tile crossfades are off, expired tiles are no longer re-validated mid-gesture, and repeated world copies are not drawn.
- The map now measures its own frame rate while you drag, zoom or rotate it. If a gesture is genuinely not keeping up, it drops to a 1× canvas and hides the detection points for the rest of that gesture, then restores full detail the moment you stop — so a slow machine stays responsive without ever showing you a permanently degraded map.
- Backend cold start is ~2.5 s faster and the baseline process ~87 MB lighter: scipy and scikit-learn now import on first clustering use instead of at module load.
- Repository layout follows the documented standard — reference docs moved into `docs/` ([index](docs/README.md)), decisions recorded in `docs/decisions/`, and the checks CI runs are available locally as `scripts/check.sh` / `check.bat`.

### Added

- A **Docker image**: `docker build -t pyro-harmony . && docker run --rm -p 8000:8000 pyro-harmony`. One process, one port, nothing else to install — the console is built inside the image and served by the same server that answers the API, which now also accepts the browser's `/api/...` calls directly and runs as a non-root user with a `/meta` healthcheck.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `.editorconfig`, and the `docs/decisions/` ADR series.
