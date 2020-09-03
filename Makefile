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

docker-images: lint test $(SPEC_VERSIONS)

$(SPEC_VERSIONS):
	$(eval SPEC_VERSION := $(subst api_specs/,,$@))
	@echo "Building image for API version $(SPEC_VERSION)"
	docker build --build-arg SPEC_VERSION=$(SPEC_VERSION) -f docker/Dockerfile . -t appgate-operator:$(SPEC_VERSION) 
