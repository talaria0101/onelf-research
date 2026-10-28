#!/bin/bash
# size + pack time: onelf 0.4.2 blocks vs stipple vs mkdwarfs vs tar|zstd
set -u
O=./onelf-x86_64-linux; M=./dwarfs-0.15.8-Linux-x86_64/bin/mkdwarfs
t() { local s=$(date +%s.%N); "$@" >/dev/null 2>>err.log; local rc=$?; local e=$(date +%s.%N); echo "rc=$rc secs=$(echo "$e-$s"|bc)"; return 0; }
for spec in chromium:chromium firefox:firefox dbeaver:dbeaver; do
  name=${spec%%:*}; cmd=${spec##*:}; dir=/usr/lib/$name
  echo "== $name raw_bytes=$(du -sb $dir | cut -f1)"
  for cfg in "blocks L19 64K|--level 19" "blocks L19 1M|--level 19 --block-size 1M" "stipple L19 default32M|--payload stipple --level 19" "stipple L19 1M|--payload stipple --level 19 --block-size 1M" "stipple L22 default32M|--payload stipple --level 22" "stipple store|--payload stipple --no-compress"; do
    label=${cfg%%|*}; args=${cfg#*|}
    r=$(t $O pack $dir -o out.onelf --command $cmd $args)
    echo "onelf $label $r bytes=$(stat -c %s out.onelf)"; rm -f out.onelf
  done
  r=$(t $M -i $dir -o out.dwarfs -C zstd:level=22 -S26 -B2 --no-progress); echo "mkdwarfs zstd22 -S26 -B2 $r bytes=$(stat -c %s out.dwarfs)"; rm -f out.dwarfs
  r=$(t $M -i $dir -o out.dwarfs -C zstd:level=19 -S26 -B2 --no-progress); echo "mkdwarfs zstd19 -S26 -B2 $r bytes=$(stat -c %s out.dwarfs)"; rm -f out.dwarfs
  echo "tar|zstd -19 bytes=$(tar cf - -C /usr/lib $name 2>/dev/null | zstd -19 -T0 -c | wc -c)"
done
