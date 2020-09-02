.PHONY: lint all

all: lint test

virtualenv:
	python3 -m venv virtualenv
	./virtualenv/bin/pip install -r requirements-build.txt

lint:
	MYPYPATH=mypy-stubs ./virtualenv/bin/mypy appgate

test:
	./virtualenv/bin/python -m pytest tests

docker-image: lint test
	docker build -f docker/Dockerfile . -t appgate-operator
