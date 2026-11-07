PYTHON ?= python3

.DEFAULT_GOAL := build

.PHONY: build test
build:
	$(PYTHON) -m compileall -q custom_components tests
	$(PYTHON) -c 'from custom_components.tecnoalarm.client.auth import Cipher, algorithms, CFB'

test: build
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
