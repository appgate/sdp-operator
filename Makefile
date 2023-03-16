.PHONY: lint all
PYTHON3=python3.10

all: api_specs lint test

.PHONY: api_specs
api_specs:
	@./bin/get-open-spec.sh
	@./bin/unzip-open-spec.sh

lint:
	MYPYPATH=mypy-stubs $(PYTHON3) -m mypy --cache-dir=/dev/null appgate tests

.PHONY: fmt
fmt:
	black appgate tests

.PHONY: check-fmt
check-fmt:
	black --check --diff appgate tests

test:
	$(PYTHON3) -m pytest -p no:cacheprovider tests

dump-crd:
	docker build -f docker/Dockerfile -t localhost:5000/sdp-operator .
	docker run -v ${PWD}:/build --rm -it --entrypoint bash localhost:5000/sdp-operator ./run.sh --spec-directory /root/api_specs/$(VERSION) dump-crd --file /build/k8s/crd/templates/$(VERSION).yaml
	echo '{{ if eq .Values.version "$(VERSION)" }}' | cat - k8s/crd/templates/$(VERSION).yaml > temp && mv temp k8s/crd/templates/$(VERSION).yaml
	echo '{{ end }}' >> k8s/crd/templates/$(VERSION).yaml

docker-build-image:
	docker build -f docker/Dockerfile-build . -t sdp-operator-builder

docker-all: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder make all

docker-shell: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder bash

clean-cache:
	find appgate -name "__pycache__" -print | xargs rm -r $1

.PHONY: pip-compile
pip-compile:
	rm -rf venv
	${PYTHON3} -m venv venv
	. venv/bin/activate && ${PYTHON3} -m pip install pip-tools && pip-compile requirements.in

clean:
	rm -rf api_specs
