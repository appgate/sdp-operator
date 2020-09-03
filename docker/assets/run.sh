#!/bin/bash

/root/venv/bin/python3 -m appgate \
		       -l ${LOG_LEVEL:-INFO} \
		       --spec-directory /root/appgate/api_specs/$SPEC_VERSION \
		       $@
