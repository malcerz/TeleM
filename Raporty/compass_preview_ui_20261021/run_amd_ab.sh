#!/usr/bin/env bash
# A/B AMD export: A = baseline 5d69840 tree (scratch export, same runtime via
# junctions), B = current HEAD. Identical arguments; isolated APPDATA dirs.
set -u
# Real interpreter, not the py launcher: the launcher reads LOCALAPPDATA and
# would install a fresh Python into the isolated temp dir.
PY=/c/Users/Malcerz/AppData/Local/Python/pythoncore-3.14-64/python.exe
REPO=/c/_DEV/SportCamHUD
BASE="$1"
OUT=$REPO/Raporty/compass_preview_ui_20261021/amd
mkdir -p "$OUT"
run() {
  tag=$1; root=$2
  tmp=$(mktemp -d)
  echo "=== $tag root=$root $(date +%T)"
  ( cd "$root" && APPDATA="$tmp/appdata" LOCALAPPDATA="$tmp/local" "$PY" Raporty/compass_preview_ui_20261021/run_hybrid_harness.py \
      --test-amd-export --mode queue --video "F:\GoPro\2026-10-16\GX010380.MP4" \
      --fit "F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit" \
      --layout Raporty/compass_preview_ui_20261021/layout_user_hybrid.json \
      --bitrate 40M --quality QUALITY --codec hevc --frames 2400 \
      --output "$(cygpath -w "$OUT/$tag.mp4")" --result-json "$(cygpath -w "$OUT/$tag.json")" \
      > "$OUT/$tag.stdout.log" 2>&1 )
  echo "exit $? $(date +%T)"
}
run A1 "$BASE"
run B1 "$REPO"
run A2 "$BASE"
run B2 "$REPO"
echo ALLDONE
