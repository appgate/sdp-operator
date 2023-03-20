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

docker-run-image:
	docker build -f docker/Dockerfile -t sdp-operator .

docker-build-image:
	docker build -f docker/Dockerfile-build . -t sdp-operator-builder

docker-all: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder make all

docker-shell: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder bash

dump-crd: docker-run-image
	docker run -v ${PWD}:/build --rm -it --entrypoint bash sdp-operator ./run.sh --spec-directory /root/api_specs/$(VERSION) dump-crd --file /build/k8s/crd/templates/$(VERSION).yaml
	echo '{{ if eq .Values.version "$(VERSION)" }}' | cat - k8s/crd/templates/$(VERSION).yaml > temp && mv temp k8s/crd/templates/$(VERSION).yaml
	echo '{{ end }}' >> k8s/crd/templates/$(VERSION).yaml

# make dump-entities USER=admin PASSWORD=admin HOST=https://envy-10-97-166-2.devops:444 TAGS=builtin VERSION=v15 TAGS=builtin
dump-entities: docker-run-image
	docker run -v ${PWD}:/build -v ${HOME}/.kube:/root/.kube --rm -it \
		--env APPGATE_OPERATOR_USER=$(USER) \
		--env APPGATE_OPERATOR_PASSWORD=$(PASSWORD) \
		--env APPGATE_OPERATOR_HOST=$(HOST) \
		--env APPGATE_API_VERSION=$(VERSION) \
		--env APPGATE_OPERATOR_DEVICE_ID="5c12c58b-dd94-4aef-a477-ddbf2d661512" \
		--entrypoint bash sdp-operator \
		./run.sh --spec-directory /root/api_specs/$(VERSION) dump-entities --no-verify --directory /build/tmp --tags $(TAGS)

clean-cache:
	find appgate -name "__pycache__" -print | xargs rm -r $1

.PHONY: pip-compile
pip-compile: docker-build-image
	docker run --rm -it -v ${PWD}:/build sdp-operator-builder make _pip-compile

_pip-compile:
	$(PYTHON3) -m venv venv
	. venv/bin/activate && ${PYTHON3} -m pip install pip-tools && pip-compile requirements.in
	rm -rf venv

clean:
	rm -rf api_specs
