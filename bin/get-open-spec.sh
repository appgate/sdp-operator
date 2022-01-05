#!/usr/bin/env bash

set -ex

VERSIONS="12 13 14 15 16"

rm -rf api_spec
mkdir api_spec
for v in 12 13 14 15 16; do
    rm -f /tmp/openspecs-$v.zip
    wget https://github.com/appgate/sdp-api-specification/archive/refs/heads/version-$v.zip \
         -O /tmp/openspec-$v.zip
    unzip /tmp/openspec-$v.zip -d api_spec
    mv api_spec/sdp-api-specification-version-$v api_spec/$v
    rm /tmp/openspec-$v.zip
done
