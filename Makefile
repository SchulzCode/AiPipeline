.PHONY: test web-check validate

test:
	python -m pytest -q

web-check:
	cd web && npm run lint && npm run build

validate: test
	python -m compileall -q src
