.PHONY: lint all
SPEC_VERSIONS := $(wildcard api_specs/*)
PYTHON3=python3.9

.PHONY: $(SPEC_VERSIONS)

all: lint test

lint:
	MYPYPATH=mypy-stubs $(PYTHON3) -m mypy --cache-dir=/dev/null appgate

.PHONY: fmt
fmt:
	black appgate tests

.PHONY: check-fmt
check-fmt:
	black --check --diff appgate tests

test:
	$(PYTHON3) -m pytest -p no:cacheprovider tests

docker-build-image:
	docker build -f docker/Dockerfile-build . -t sdp-operator-builder

docker-all: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder make all

docker-shell: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder bash

docker-images: docker-all $(SPEC_VERSIONS)

clean-cache:
	find appgate -name "__pycache__" -print | xargs rm -r $1

$(SPEC_VERSIONS): clean-cache
	$(eval SPEC_VERSION := $(subst api_specs/,,$@))
	@echo "Building image for API version $(SPEC_VERSION)"
	@docker build --build-arg SPEC_VERSION=$(SPEC_VERSION) -f docker/Dockerfile . -t sdp-operator:$(SPEC_VERSION)

clean:
