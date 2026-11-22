#!/bin/bash
# Packs LCA Wrench for Linux: dist/LCA-Wrench-Linux.tar.gz with the app as committed (default HEAD), install.sh,
# start.sh, the instructions and the licence. Nothing uncommitted, no tests, no venv. tar keeps the execute bits.
set -euo pipefail
cd "$(dirname "$0")"
REF="${1:-HEAD}"
# the scripts in linux/ from another commit: the CI packs v0.1.0, which had no Linux package, with today's scripts
SCRIPTS_REF="${LCA_WRENCH_SCRIPTS_REF:-$REF}"
SUFFIX=""
OUT="dist/linux/LCA-Wrench$SUFFIX"
TGZ="dist/LCA-Wrench$SUFFIX-Linux.tar.gz"
rm -rf dist/linux "$TGZ"
mkdir -p "$OUT"
EXTRA=()  # the licence, if the packed version has one (older commits do not)
git cat-file -e "$REF:LICENSE" 2>/dev/null && EXTRA+=(LICENSE)
git archive "$REF" lca_wrench requirements-lock.txt requirements-app.txt "${EXTRA[@]}" | tar -x -C "$OUT"
git archive "$SCRIPTS_REF" linux | tar -x -C "$OUT"
mv "$OUT"/linux/* "$OUT"/ && rmdir "$OUT/linux"
echo "$(git show "${REF}:lca_wrench/__init__.py" | sed -n 's/^__version__ = "\(.*\)"/\1/p') $(git rev-parse --short "$REF") $(git log -1 --format=%cs "$REF")" > "$OUT/VERSION"  # written to lca-wrench.log
# FILES.txt: every file of the package; the installer checks they are all there
(cd "$OUT" && find . -type f ! -name FILES.txt | sed 's|^\./||' | LC_ALL=C sort > FILES.txt)
chmod +x "$OUT/install.sh" "$OUT/start.sh"
tar -czf "$TGZ" -C dist/linux --owner=0 --group=0 "$(basename "$OUT")" 2>/dev/null || tar -czf "$TGZ" -C dist/linux "$(basename "$OUT")"
rm -rf dist/linux
echo "$TGZ ($(du -h "$TGZ" | cut -f1)) from $(git rev-parse --short "$REF")"
