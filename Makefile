.PHONY: test check demo clean help

PYTHON ?= python3

help:
	@echo "make test   - run the unittest suite"
	@echo "make check  - byte-compile every source file"
	@echo "make demo   - build and summarise the bundled fixture package"
	@echo "make clean  - remove caches and generated output"

test:
	$(PYTHON) -m unittest discover -s tests -q

check:
	$(PYTHON) -m py_compile graphwright/*.py tests/test_graphwright.py
	@echo "all sources compile"

demo:
	$(PYTHON) -m graphwright show --path tests/fixtures/sample
	@echo
	$(PYTHON) -m graphwright callees Engine.run --path tests/fixtures/sample

clean:
	rm -rf build dist *.egg-info graph.json
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
