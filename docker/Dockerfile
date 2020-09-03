FROM python:rc-slim
ARG SPEC_VERSION
ENV SPEC_VERSION=$SPEC_VERSION
ENV LOG_LEVEL=INFO
ADD requirements.txt /root/
RUN apt-get update && \
    apt-get install gcc libffi-dev --yes && \
    python3 -m venv /root/venv && \
    /root/venv/bin/pip install -r /root/requirements.txt && \
    apt-get autoremove gcc --yes
ADD appgate /root/appgate/
ADD api_specs /root/appgate/api_specs/
ADD docker/assets/run.sh /root/run.sh
RUN chmod +x /root/run.sh
WORKDIR /root
ENTRYPOINT ["/root/run.sh"]
CMD ["run"]
