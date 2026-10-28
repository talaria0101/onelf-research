#!/bin/bash
# how much of package v2 is reusable from v1 when one small file changed?
# zstd --patch-from size = bytes of v2 not found in v1 (any offset). Not the onelf updater itself.
set -u
O=./onelf-x86_64-linux
rm -rf t1 t2; cp -r /usr/lib/python3.14 t1; cp -r t1 t2; echo "# changed" >> t2/os.py
for cfg in "blocks|--level 19" "blocks-dict|--level 19 --dict" "stipple32M|--payload stipple --level 19" "stipple64K|--payload stipple --level 19 --block-size 64K" "stipple1M|--payload stipple --level 19 --block-size 1M" "stipple-stored|--payload stipple --no-compress"; do
  label=${cfg%%|*}; args=${cfg#*|}
  $O pack t1 -o v1 --command os.py $args >/dev/null 2>&1; r1=$?
  $O pack t2 -o v2 --command os.py $args >/dev/null 2>&1; r2=$?
  zstd -q -19 --long=27 --patch-from=v1 v2 -o v2.patch -f 2>/dev/null; rc=$?
  echo "$label rc=$r1,$r2,$rc v1=$(stat -c %s v1) v2=$(stat -c %s v2) patch_from_v1=$(stat -c %s v2.patch)"
  rm -f v1 v2 v2.patch
done
rm -rf t1 t2
