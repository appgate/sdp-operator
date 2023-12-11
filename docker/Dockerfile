FROM python:3.11-slim

WORKDIR /appgate
USER root

COPY requirements.txt /appgate

RUN apt-get update && \
    apt-get install git --yes && \
    apt-get remove curl && \
    apt-get clean && \
    apt-get autoclean && \
    dpkg -r --force-all apt apt-get && \
    dpkg -r --force-all debconf dpkg && \
    python3 -m venv /appgate/venv && \
    /appgate/venv/bin/pip install --upgrade pip && \
    /appgate/venv/bin/pip install -r /appgate/requirements.txt && \
    rm /appgate/requirements.txt

COPY appgate /appgate/appgate/
COPY api_specs /appgate/api_specs
COPY docker/assets/run.sh /appgate/run.sh
RUN chmod +x /appgate/run.sh

RUN useradd appgate --uid 1000 --user-group --create-home
USER appgate

ENTRYPOINT ["/appgate/run.sh"]
