#!/bin/bash
# warm-cache extract time and verify time, blocks vs stipple, firefox tree
set -u
O=./onelf-x86_64-linux; D=/usr/lib/firefox
$O pack $D -o x.blocks --command firefox --level 19 >/dev/null 2>&1; echo "pack blocks rc=$?"
$O pack $D -o x.stipple --command firefox --level 19 --payload stipple >/dev/null 2>&1; echo "pack stipple rc=$?"
$O pack $D -o x.stored --command firefox --payload stipple --no-compress >/dev/null 2>&1; echo "pack stipple-stored rc=$?"
ls -l x.blocks x.stipple x.stored
for rep in 1 2 3; do
  for p in blocks stipple stored; do
    rm -rf xout
    s=$(date +%s.%N); ./x.$p --onelf-extract xout >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
    echo "extract $p rep=$rep rc=$rc secs=$(echo "$e-$s"|bc) files=$(find xout -type f | wc -l)"
    rm -rf xout
  done
done
for rep in 1 2 3; do
  for p in blocks stipple stored; do
    s=$(date +%s.%N); $O verify x.$p >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
    echo "verify $p rep=$rep rc=$rc secs=$(echo "$e-$s"|bc)"
  done
done
uptime
