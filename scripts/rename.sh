#!/usr/bin/env bash
# Rename the working codename everywhere: ./scripts/rename.sh NEWNAME
set -euo pipefail
old=aspnext
new=${1:?usage: rename.sh NEWNAME}
[[ $new =~ ^[a-z][a-z0-9_]*$ ]] || { echo "name must be a lowercase python identifier" >&2; exit 2; }
cd "$(dirname "$0")/.."
git ls-files -z --cached --others --exclude-standard \
  | grep -zv -e '^pixi.lock$' -e '^scripts/rename.sh$' \
  | xargs -0 grep -lZ "$old" \
  | xargs -0 sed -i "s/$old/$new/g"
git mv "src/$old" "src/$new"
rm -f pixi.lock
echo "renamed $old -> $new; regenerate pixi.lock with 'pixi install'"
