#!/bin/bash
set -u
O=./onelf-x86_64-linux; D=/usr/lib/firefox
SMALL="application.ini dependentlibs.list firefox libmozsandbox.so libmozsqlite3.so libmozgtk.so liblgpllibs.so libmozwayland.so gfxtest"
for bs in 1M 4M 8M; do
  s=$(date +%s.%N); $O pack $D -o y.$bs --command firefox --level 19 --payload stipple --block-size $bs >/dev/null 2>&1; rc=$?; e=$(date +%s.%N)
  echo "pack stipple bs=$bs rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(stat -c %s y.$bs)"
done
for rep in 1 2 3 4 5; do
  for bs in 1M 4M 8M; do
    rm -rf pout; s=$(date +%s.%N); ./y.$bs --onelf-extract pout $SMALL >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
    echo "small9 stipple bs=$bs rep=$rep rc=$rc secs=$(echo "$e-$s"|bc)"
  done
done
for bs in 1M 4M 8M; do
  rm -rf pout; s=$(date +%s.%N); ./y.$bs --onelf-extract pout >/dev/null 2>>x.err; rc=$?; e=$(date +%s.%N)
  echo "full stipple bs=$bs rc=$rc secs=$(echo "$e-$s"|bc)"
done
rm -rf pout y.*; uptime
