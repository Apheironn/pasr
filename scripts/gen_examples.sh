#!/usr/bin/env bash
# Regenerate examples/*.md from real pinned checkouts. Deterministic; safe to re-run.
#
#   bash scripts/gen_examples.sh
#
# Clones each pinned repo (shallow) into .eval-checkouts/ if missing, then runs `pasr`
# and captures the verbatim output. Requires `pasr` on PATH (pip install -e .) or a
# .venv, plus git.
set -euo pipefail
export PYTHONIOENCODING=utf-8
cd "$(git rev-parse --show-toplevel)"

PASR="$(command -v pasr || true)"
[ -z "$PASR" ] && [ -x .venv/Scripts/pasr.exe ] && PASR="$PWD/.venv/Scripts/pasr.exe"
[ -z "$PASR" ] && [ -x .venv/bin/pasr ] && PASR="$PWD/.venv/bin/pasr"
[ -z "$PASR" ] && { echo "pasr not found (pip install -e . or activate .venv)"; exit 1; }

CO="$PWD/.eval-checkouts"
OUT="$PWD/examples"
mkdir -p "$CO" "$OUT"

checkout () {  # $1 owner/repo  $2 pin
  local name; name="$(basename "$1")"
  local dir="$CO/$name"
  if [ ! -d "$dir/.git" ]; then
    git init -q "$dir"
    git -C "$dir" remote add origin "https://github.com/$1"
  fi
  git -C "$dir" fetch -q --depth 1 origin "$2"
  git -C "$dir" checkout -q -f FETCH_HEAD
}

show_cmd () {  # copy-pasteable `pasr ...` line, quoting args with spaces
  printf 'pasr'
  for a in "$@"; do
    case "$a" in *" "*) printf ' "%s"' "$a" ;; *) printf ' %s' "$a" ;; esac
  done
  printf '\n'
}

emit () {  # $1 outfile  $2 title  $3 owner/repo  $4 full-sha  $5.. pasr-args
  local out="$OUT/$1" title="$2" slug="$3" pin="$4"; shift 4
  local name short; name="$(basename "$slug")"; short="${pin:0:9}"
  checkout "$slug" "$pin"
  {
    echo "# $title"
    echo
    echo "Repo: [\`$slug\`](https://github.com/$slug) at \`$short\`. Reproduce from a clean checkout:"
    echo
    echo '```bash'
    echo "git clone https://github.com/$slug && git -C $name checkout $pin && cd $name"
    show_cmd "$@"
    echo '```'
    echo
    echo '```text'
    ( cd "$CO/$name" && "$PASR" "$@" ) | sed 's/[[:space:]]*$//'
    echo '```'
  } > "$out"
  echo "  wrote $(basename "$out")"
}

emit 01-requests-redirects.md \
  'requests — "how are redirects resolved and followed"' \
  psf/requests 0e322af87745eff34caffe4df68456ebc20d9068 \
  explain "how are redirects resolved and followed" src --budget 3000 --no-write

emit 02-httpx-connection-pool.md \
  'httpx — "how does the connection pool decide to open a new connection"' \
  encode/httpx 26d48e0634e6ee9cdc0533996db289ce4b430177 \
  explain "how does the connection pool decide to open a new connection" httpx --budget 3000 --no-write

emit 03-attrs-slots.md \
  'attrs — "how are class slots built when slots is true"' \
  python-attrs/attrs 6771a04893780166e4b7826b63599f43ac30d00a \
  explain "how are class slots built when slots is true" src --budget 3000 --no-write

emit 04-packaging-trace.md \
  'packaging — trace a helper'"'"'s dependency closure' \
  pypa/packaging 929fd4b1410ac7ef61ef3f45b2f5d7e87711a9b5 \
  trace _parse_letter_version src --max-depth 3

emit 05-starlette-honest-signal.md \
  'starlette — PASR flags when it is the wrong tool' \
  encode/starlette 8d0cff820f89b5d5b19677246293513a9d1c952c \
  explain "list all the middleware classes provided across the whole package" starlette --budget 3000 --no-write

echo "done."
