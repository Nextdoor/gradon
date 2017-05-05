.PHONY: flake8 test tox

test: flake8
	py.test

tox:
	tox

flake8:
	flake8 .
