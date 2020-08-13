FROM python:rc-slim
ADD appgate /root/appgate/
ADD requirements.txt /root/
RUN apt-get update && \
    apt-get install gcc --yes && \
    python3 -m venv /root/venv && \
    /root/venv/bin/pip install -r /root/requirements.txt && \
    apt-get autoremove gcc --yes
WORKDIR /root

ENTRYPOINT /root/venv/bin/python3 -m appgate
