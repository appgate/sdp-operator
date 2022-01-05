#!/usr/bin/env bash

set -ex

for v in 12 13 14 15 16; do
    rm -f /tmp/openspecs-$v.zip
    wget https://github.com/appgate/sdp-api-specification/archive/refs/heads/version-$v.zip \
         -O /tmp/openspec-$v.zip
done
