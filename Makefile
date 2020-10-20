.PHONY: lint all
SPEC_VERSIONS := $(wildcard api_specs/*)
PYTHON3=python3.9

.PHONY: $(SPEC_VERSIONS)

all: lint test

lint:
	MYPYPATH=mypy-stubs $(PYTHON3) -m mypy appgate

test:
	$(PYTHON3) -m pytest tests

docker-build-image:
	docker build -f docker/Dockerfile-build . -t appgate-operator-builder

docker-all: docker-build-image
	docker run --rm -it -v ${PWD}:/build appgate-operator-builder make all

docker-shell: docker-build-image
	docker run --rm -it -v ${PWD}:/build appgate-operator-builder bash

docker-images: docker-all $(SPEC_VERSIONS)

$(SPEC_VERSIONS):
	$(eval SPEC_VERSION := $(subst api_specs/,,$@))
	@echo "Building image for API version $(SPEC_VERSION)"
	docker build --build-arg SPEC_VERSION=$(SPEC_VERSION) -f docker/Dockerfile . -t appgate-operator:$(SPEC_VERSION)

clean:
