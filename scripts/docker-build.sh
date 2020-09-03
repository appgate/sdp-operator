#!/bin/bash

apt-get update
apt-get install libffi-dev make gcc --yes
# cffi requires libffi 7 but python-slim only has 6 :/
ln -s /usr/lib/x86_64-linux-gnu/libffi.so.6 /usr/lib/x86_64-linux-gnu/libffi.so.7
if [ "$1" == "shell" ]; then
    bash
else
    cd /root && rm -rf virtualenv && make virtualenv && make all
fi
