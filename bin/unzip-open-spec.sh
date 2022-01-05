#!/usr/bin/env bash

set -ex

VERSIONS="12 13 14 15 16"
for v in 12 13 14 15 16; do
    unzip /tmp/openspec-$v.zip -d api_spec
    mv api_spec/sdp-api-specification-version-$v api_spec/v$v
    rm api_spec/v$v/.*
    rm api_spec/v$v/README.md
    rm /tmp/openspec-$v.zip
done
