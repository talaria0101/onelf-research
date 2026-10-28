#!/bin/bash
# size comparison on three real app trees. onelf 0.4.1 vs mkdwarfs 0.15.8 vs tar|zstd
set -u
O=./release/onelf; M=./dwarfs-0.15.8-Linux-x86_64/bin/mkdwarfs
for spec in chromium:chromium firefox:firefox dbeaver:dbeaver; do
  name=${spec%%:*}; cmd=${spec##*:}; dir=/usr/lib/$name
  raw=$(du -sb $dir | cut -f1)
  echo "== $name raw_bytes=$raw"
  rm -f out.*
  s=$(date +%s.%N); $O pack $dir -o out.onelf19 --command $cmd --level 19 >/dev/null 2>out.err19; rc=$?; e=$(date +%s.%N)
  echo "onelf level19 64KiB rc=$rc bytes=$(stat -c %s out.onelf19) secs=$(echo "$e-$s"|bc)"
  $O pack $dir -o out.onelf22 --command $cmd --level 22 >/dev/null 2>&1; echo "onelf level22 rc=$? bytes=$(stat -c %s out.onelf22)"
  $O pack $dir -o out.onelf19d --command $cmd --level 19 --dict >/dev/null 2>&1; echo "onelf level19+dict rc=$? bytes=$(stat -c %s out.onelf19d 2>/dev/null)"
  s=$(date +%s.%N); $M -i $dir -o out.dwarfs22 -C zstd:level=22 -S26 -B2 --no-progress >/dev/null 2>out.errd; rc=$?; e=$(date +%s.%N)
  echo "mkdwarfs zstd22 -S26 -B2 rc=$rc bytes=$(stat -c %s out.dwarfs22) secs=$(echo "$e-$s"|bc)"
  $M -i $dir -o out.dwarfs19 -C zstd:level=19 -S26 -B2 --no-progress >/dev/null 2>&1; echo "mkdwarfs zstd19 -S26 -B2 rc=$? bytes=$(stat -c %s out.dwarfs19)"
  echo "tar|zstd -19 bytes=$(tar cf - -C /usr/lib $name 2>/dev/null | zstd -19 -T0 -c | wc -c)"
done
