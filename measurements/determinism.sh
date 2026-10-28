#!/bin/bash
# is a larger stipple/blocks pack byte-identical across two runs of the same input?
set -u
O=./onelf-x86_64-linux
for spec in "dbeaver:/usr/lib/dbeaver:dbeaver" "firefox:/usr/lib/firefox:firefox"; do
  IFS=: read name dir cmd <<<"$spec"
  for payload in blocks stipple; do
    extra=""; [ $payload = stipple ] && extra="--payload stipple"
    $O pack $dir -o det.1 --command $cmd --level 19 $extra >/dev/null 2>&1; rc1=$?
    $O pack $dir -o det.2 --command $cmd --level 19 $extra >/dev/null 2>&1; rc2=$?
    if cmp -s det.1 det.2; then r=identical; else r="DIFFER first_diff=$(cmp det.1 det.2 | head -1)"; fi
    echo "$name $payload rc=$rc1,$rc2 bytes=$(stat -c %s det.1) $r"
    rm -f det.1 det.2
  done
done
