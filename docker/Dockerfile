FROM python:3.11-slim

WORKDIR /appgate
USER root

RUN apt-get update && \
    apt-get install gcc libffi-dev git --yes

COPY requirements.txt /appgate

RUN python3 -m venv /appgate/venv && \
    /appgate/venv/bin/pip install --upgrade pip && \
    /appgate/venv/bin/pip install -r /appgate/requirements.txt

RUN apt-get clean autoclean & \
    apt-get autoremove --yes & \
    rm -rf /var/lib/{apt,dpkg,cache,log}/ & \
    rm /appgate/requirements.txt

COPY appgate /appgate/appgate/
COPY api_specs /appgate/api_specs
COPY docker/assets/run.sh /appgate/run.sh
RUN chmod +x /appgate/run.sh

RUN useradd appgate --uid 1000 --user-group
USER appgate

ENTRYPOINT ["/appgate/run.sh"]
