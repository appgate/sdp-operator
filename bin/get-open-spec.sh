#!/usr/bin/env bash

set -ex

for v in $(seq 18 22); do
    rm -f /tmp/openspecs-$v.zip
    wget https://github.com/appgate/sdp-api-specification/archive/refs/heads/version-$v.zip \
         -O /tmp/openspec-$v.zip
    unzip /tmp/openspec-$v.zip -d api_specs
    mv api_specs/sdp-api-specification-version-$v api_specs/v$v
    rm -rf api_specs/v$v/.github
    rm api_specs/v$v/README.md
    rm /tmp/openspec-$v.zip
done
