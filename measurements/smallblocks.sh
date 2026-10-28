#!/bin/bash
# stipple image block size below 1M: size, pack time, warm decode of 9 small files, full extract
set -u
O=./onelf-x86_64-linux
SMALL="application.ini dependentlibs.list firefox libmozsandbox.so libmozsqlite3.so libmozgtk.so liblgpllibs.so libmozwayland.so gfxtest"
for tree in firefox:firefox chromium:chromium; do
  name=${tree%%:*}; cmd=${tree##*:}
  for bs in 64K 128K 256K 512K 1M; do
    s=$(date +%s.%N); $O pack /usr/lib/$name -o sb.pkg --command $cmd --level 19 --payload stipple --block-size $bs >/dev/null 2>&1; rc=$?; e=$(date +%s.%N)
    echo "$name pack stipple bs=$bs rc=$rc secs=$(echo "$e-$s"|bc) bytes=$(stat -c %s sb.pkg)"
    if [ $name = firefox ]; then
      for rep in 1 2 3 4 5; do
        rm -rf pout; s=$(date +%s.%N); ./sb.pkg --onelf-extract pout $SMALL >/dev/null 2>&1; rc=$?; e=$(date +%s.%N)
        echo "small9 stipple bs=$bs rep=$rep rc=$rc secs=$(echo "$e-$s"|bc)"
      done
      rm -rf pout; s=$(date +%s.%N); ./sb.pkg --onelf-extract pout >/dev/null 2>&1; rc=$?; e=$(date +%s.%N)
      echo "full stipple bs=$bs rc=$rc secs=$(echo "$e-$s"|bc)"; rm -rf pout
    fi
    rm -f sb.pkg
  done
done
uptime
