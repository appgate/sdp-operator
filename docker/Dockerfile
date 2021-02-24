FROM python:3.9-slim
ARG SPEC_VERSION
ENV SPEC_VERSION=$SPEC_VERSION
ENV LOG_LEVEL=INFO
RUN apt-get update && \
    apt-get install gcc libffi-dev --yes
COPY requirements.txt /root/
RUN python3 -m venv /root/venv && \
    /root/venv/bin/pip install -r /root/requirements.txt && \
    apt-get autoremove gcc --yes && \
    rm -r /root/.cache && rm /root/requirements.txt

COPY appgate /root/appgate/
COPY api_specs /root/appgate/api_specs/
COPY docker/assets/run.sh /root/run.sh
RUN chmod +x /root/run.sh
WORKDIR /root
ENTRYPOINT ["/root/run.sh"]
CMD ["run"]
