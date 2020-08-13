FROM python:rc-slim
ADD appgate /root/appgate/
ADD requirements.txt /root/
RUN python3 -m venv /root/venv && \
    /root/venv/bin/pip install -r /root/requirements.txt
WORKDIR /root

ENTRYPOINT /root/venv/bin/python3 -m appgate
