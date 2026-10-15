#!/usr/bin/env bash
# Fetch real FIRMS exports into .data/ -- the open global feeds, which need no MAP_KEY.
#
# Every file is downloaded to `<name>.part` and only moved into place once its byte count
# matches the server's Content-Length, because FIRMS serves these slowly (~100 KB/s from this
# machine) and a killed transfer otherwise leaves a truncated CSV that still looks like a file.
#
#   bash scripts/fetch_firms_feeds.sh [window]     # window defaults to 7d
set -uo pipefail
cd "$(dirname "$0")/.."
BASE="https://firms.modaps.eosdis.nasa.gov/data/active_fire"
WINDOW="${1:-7d}"
DEST=".data"
mkdir -p "$DEST"

# product path, remote file prefix, local FIRMS-shaped name
FEEDS=(
  "modis-c6.1/csv/MODIS_C6_1_Global_${WINDOW}.csv|M-C61|fire_nrt_M-C61_700001.csv"
  "suomi-viirs-c2/csv/SUOMI_VIIRS_C2_Global_${WINDOW}.csv|SV-C2|fire_nrt_SV-C2_700002.csv"
  "noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_${WINDOW}.csv|J1V-C2|fire_nrt_J1V-C2_700003.csv"
  "noaa-20-viirs-c2/csv/J2_VIIRS_C2_Global_${WINDOW}.csv|J2V-C2|fire_nrt_J2V-C2_700004.csv"
)

for spec in "${FEEDS[@]}"; do
  IFS="|" read -r path product name <<<"$spec"
  url="$BASE/$path"
  want=$(curl -sIL -m 90 "$url" | tr -d '\r' | awk '/^[Cc]ontent-[Ll]ength/ {v=$2} END {print v}')
  echo "== $name (want ${want:-unknown} bytes)"
  ok=0
  for attempt in 1 2 3; do
    curl -sL -m 1800 --retry 3 --retry-delay 10 -o "$DEST/$name.part" "$url"
    code=$?
    have=$(stat -c%s "$DEST/$name.part" 2>/dev/null || echo 0)
    if [ -n "$want" ] && [ "$have" = "$want" ]; then
      mv "$DEST/$name.part" "$DEST/$name"
      echo "   attempt $attempt: complete, $have bytes -> $name"
      ok=1
      break
    fi
    echo "   attempt $attempt: curl=$code, $have of ${want:-?} bytes"
  done
  [ "$ok" = 1 ] || echo "   INCOMPLETE after 3 attempts: $name"
done
echo "=== on disk ==="
ls -la "$DEST"
echo "DONE"
