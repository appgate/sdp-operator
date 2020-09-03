.PHONY: lint all
SPEC_VERSIONS := $(wildcard api_specs/*)

.PHONY: $(SPEC_VERSIONS)

all: lint test

virtualenv:
	python3 -m venv virtualenv
	./virtualenv/bin/pip install -r requirements-build.txt

lint:
	MYPYPATH=mypy-stubs ./virtualenv/bin/mypy appgate

test:
	./virtualenv/bin/python -m pytest tests

docker-all:
	docker run --rm -it -v ${PWD}:/root python:rc-slim /root/scripts/docker-build.sh

docker-shell:
	docker run --rm -it -v ${PWD}:/root python:rc-slim /root/scripts/docker-build.sh shell

docker-images: docker-all $(SPEC_VERSIONS)

$(SPEC_VERSIONS):
	$(eval SPEC_VERSION := $(subst api_specs/,,$@))
	@echo "Building image for API version $(SPEC_VERSION)"
	docker build --build-arg SPEC_VERSION=$(SPEC_VERSION) -f docker/Dockerfile . -t appgate-operator:$(SPEC_VERSION) 
