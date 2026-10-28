#!/bin/bash
# warm-cache partial extract: a handful of small files, and one big file
set -u
SMALL="application.ini dependentlibs.list firefox libmozsandbox.so libmozsqlite3.so libmozgtk.so liblgpllibs.so libmozwayland.so gfxtest"
for rep in 1 2 3 4 5; do
  for p in blocks stipple stored; do
    rm -rf pout; s=$(date +%s.%N); ./x.$p --onelf-extract pout $SMALL >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
    echo "small9 $p rep=$rep rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(du -sb pout | cut -f1)"
  done
done
for rep in 1 2 3; do
  for p in blocks stipple stored; do
    rm -rf pout; s=$(date +%s.%N); ./x.$p --onelf-extract pout libxul.so >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
    echo "libxul $p rep=$rep rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(du -sb pout | cut -f1)"
  done
done
rm -rf pout
uptime
