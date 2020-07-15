.PHONY: lint all

all: lint

virtualenv:
	python3 -m venv virtualenv
	./virtualenv/bin/pip install -r requirements

lint:
	MYPYPATH=mypy-stubs ./virtualenv/bin/mypy appgate
