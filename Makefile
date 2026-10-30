PYTHON ?= python3

.PHONY: reproduce data weights benchmark test lint

# Regenerate every Week 4 table and figure from the saved split and weights.
# Missing weights are retrained (about 2 h on an Apple M4) rather than faked.
reproduce: data weights benchmark test

data:
	$(PYTHON) -m week4.download
	$(PYTHON) -m week4.denpar
	$(PYTHON) -m week4.denpar_split

weights:
	PYTHON=$(PYTHON) ./week4/train_all.sh
	$(PYTHON) -m week4.weights_manifest --check

benchmark:
	$(PYTHON) -m week4.benchmark
	$(PYTHON) -m week4.reproduce

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check week4 week3/pbl_calculator.py
	$(PYTHON) -m mypy --strict week3/pbl_calculator.py
