#!/usr/bin/env bash
# Back up a directory to a dated archive, keep the newest few and verify the result.

set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-k keep] [-x pattern] SOURCE DESTINATION

  -k keep      number of archives to keep (default 7)
  -x pattern   exclude files matching the pattern; may be repeated
USAGE
}

keep=7
excludes=()

while getopts ":k:x:h" option; do
  case "$option" in
    k) keep="$OPTARG" ;;
    x) excludes+=("--exclude=$OPTARG") ;;
    h) usage; exit 0 ;;
    :) echo "Option -$OPTARG needs a value" >&2; exit 2 ;;
    *) usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

source_dir="${1%/}"
destination="${2%/}"

if [[ ! -d "$source_dir" ]]; then
  echo "Source directory not found: $source_dir" >&2
  exit 1
fi
if ! [[ "$keep" =~ ^[0-9]+$ ]] || [[ "$keep" -lt 1 ]]; then
  echo "The number of archives to keep must be a positive integer" >&2
  exit 2
fi

mkdir -p "$destination"
name="$(basename "$source_dir")"
stamp="$(date +%Y%m%d-%H%M%S)"
archive="$destination/$name-$stamp.tar.gz"
log="$destination/$name-backup.log"

log_line() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$log"
}

cleanup() {
  local status=$?
  if [[ $status -ne 0 && -f "$archive" ]]; then
    rm -f "$archive"
    log_line "backup failed with status $status; partial archive removed"
  fi
}
trap cleanup EXIT

required_kb="$(du -sk "$source_dir" | cut -f1)"
available_kb="$(df -Pk "$destination" | awk 'NR == 2 { print $4 }')"
if (( required_kb > available_kb )); then
  log_line "not enough space: need ${required_kb} kB, have ${available_kb} kB"
  exit 1
fi

log_line "archiving $source_dir to $archive"
tar -czf "$archive" "${excludes[@]}" -C "$(dirname "$source_dir")" "$name"

if ! tar -tzf "$archive" > /dev/null; then
  log_line "verification failed for $archive"
  exit 1
fi
sha256sum "$archive" > "$archive.sha256"
log_line "created $(du -h "$archive" | cut -f1) archive with $(tar -tzf "$archive" | wc -l) entries"

mapfile -t old < <(ls -1t "$destination"/"$name"-*.tar.gz | tail -n +"$((keep + 1))")
for file in "${old[@]}"; do
  rm -f "$file" "$file.sha256"
  log_line "removed old archive $(basename "$file")"
done

log_line "done; ${#old[@]} old archives removed, $keep kept at most"
