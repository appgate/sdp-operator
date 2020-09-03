.PHONY: lint all
SPEC_VERSIONS := $(wildcard api_specs/*)

.PHONY: $(SPEC_VERSIONS)

all: lint test

virtualenv:
	python3 -m venv virtualenv
	./virtualenv/bin/pip install -r requirements-build.txt

lint: virtualenv
	MYPYPATH=mypy-stubs ./virtualenv/bin/mypy appgate

test: virtualenv
	./virtualenv/bin/python -m pytest tests

docker-build-image:
	docker build -f docker/Dockerfile-build . -t appgate-operator-builder

docker-all: docker-build-image
	docker run --rm -it -v ${PWD}:/root appgate-operator-builder make all

docker-shell: docker-build-image
	docker run --rm -it -v ${PWD}:/root appgate-operator-builder bash

docker-images: docker-all $(SPEC_VERSIONS)

$(SPEC_VERSIONS):
	$(eval SPEC_VERSION := $(subst api_specs/,,$@))
	@echo "Building image for API version $(SPEC_VERSION)"
	docker build --build-arg SPEC_VERSION=$(SPEC_VERSION) -f docker/Dockerfile . -t appgate-operator:$(SPEC_VERSION)

clean:
	rm -r virtualenv
