#!/bin/bash
# size vs tree size: four trees from 0.4 MB to 142 MB, many small files
set -u
O=./onelf-x86_64-linux; M=./dwarfs-0.15.8-Linux-x86_64/bin/mkdwarfs
for spec in "smoke:/workspace/m/smoke/app:bin/run" "zoneinfo:/usr/share/zoneinfo:UTC" "python3.14:/usr/lib/python3.14:os.py" "icons:/usr/share/icons:Papirus-Dark/index.theme"; do
  IFS=: read name dir cmd <<<"$spec"
  echo "== $name files=$(find $dir -type f | wc -l) raw_bytes=$(du -sb $dir | cut -f1)"
  for cfg in "blocks L19 64K|--level 19" "stipple L19 default32M|--payload stipple --level 19" "stipple L19 1M|--payload stipple --level 19 --block-size 1M"; do
    label=${cfg%%|*}; args=${cfg#*|}
    s=$(date +%s.%N); $O pack $dir -o out.onelf --command $cmd $args >/dev/null 2>>err.log; rc=$?; e=$(date +%s.%N)
    echo "onelf $label rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(stat -c %s out.onelf)"; rm -f out.onelf
  done
  s=$(date +%s.%N); $M -i $dir -o out.dwarfs -C zstd:level=22 -S26 -B2 --no-progress >/dev/null 2>>err.log; rc=$?; e=$(date +%s.%N)
  echo "mkdwarfs zstd22 -S26 -B2 rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(stat -c %s out.dwarfs)"; rm -f out.dwarfs
done
uptime
