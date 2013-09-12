PYPI_URL = http://pypi.python.org/pypi
tarball = `ls -1rt ./dist/*.tar* | tail -1`

test: tox-command
	@tox

dist: README.rst
	python setup.py sdist --formats=bztar
	@echo
	@echo 'Use `make publish` to publish to PyPI.'
	@echo
	@echo Tarball for manual distribution:
	@echo $(tarball)

publish: README.rst
	python setup.py sdist --formats=bztar,zip upload -r $(PYPI_URL)

publish-test: README.rst
	python setup.py register -r $(PYPI_URL)
	python setup.py sdist --formats=bztar,zip upload -r $(PYPI_URL)

# Set a test PYPI_URL for the publish-test target.
publish-test : PYPI_URL = https://testpypi.python.org/pypi

install:
	python setup.py install

clean:
	rm -fr __pycache__ build dist .tox
	rm -f *.pyc MANIFEST .coverage .in_virtualenv.py

README.rst: README.rst.in jeni.py bin/build_rst.py
	@python bin/build_rst.py README.rst.in > README.rst

tox-command: virtualenv
	@which tox >/dev/null 2>&1 || pip install tox

virtualenv: .in_virtualenv.py
	@python $<

.in_virtualenv.py: Makefile
	@echo '# Generated by Makefile, written by rduplain.'             >  $@
	@echo 'import sys'                                                >> $@
	@echo 'if hasattr(sys, "real_prefix"):'                           >> $@
	@echo '    sys.exit(0)'                                           >> $@
	@echo 'else:'                                                     >> $@
	@echo '    sys.stderr.write("Use a virtualenv, 2.7 or 3.2+.\\n")' >> $@
	@echo '    sys.exit(1)'                                           >> $@

.PHONY: dist
