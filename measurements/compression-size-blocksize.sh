#!/bin/bash
O=./release/onelf
for bs in 262144 1048576 4194304; do
  $O pack /usr/lib/chromium -o ex.$bs --command chromium --level 19 --block-size $bs >/dev/null 2>&1; echo "chromium onelf level19 block-size=$bs rc=$? bytes=$(stat -c %s ex.$bs)"; rm -f ex.$bs
done
