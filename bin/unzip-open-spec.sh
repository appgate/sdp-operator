#!/usr/bin/env bash

set -ex
mkdir api_specs
for v in $(seq 12 20); do
    unzip /tmp/openspec-$v.zip -d api_specs
    mv api_specs/sdp-api-specification-version-$v api_specs/v$v
    rm -rf api_specs/v$v/.github
    rm api_specs/v$v/README.md
    rm /tmp/openspec-$v.zip
done
