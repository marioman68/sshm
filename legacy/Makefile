VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/sshm/__init__.py)
RUN := PYTHONPATH=src python3

.PHONY: help run gui tray test lint fmt install uninstall dist zip srpm release-notes bump version tidy clean

help:
	@echo "make run        terminal UI from the source tree"
	@echo "make gui        desktop app from the source tree"
	@echo "make test       run the test suite"
	@echo "make lint       ruff"
	@echo "make install    user install (~/.local) via install.sh"
	@echo "make dist       source tarball for packaging (dist/sshm-$(VERSION).tar.gz)"
	@echo "make zip        dist/sshm-$(VERSION).zip of the source tree"
	@echo "make bump BUMP=patch NOTE='what changed'   bump version (major|minor|patch|X.Y.Z)"
	@echo "make version    print the current version"
	@echo "make srpm       source RPM via the same path COPR uses"

run:
	$(RUN) -m sshm

gui:
	$(RUN) -m sshm.gui.app --gui

tray:
	$(RUN) -m sshm.gui.app --tray

test:
	python3 -m pytest

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests

install:
	./install.sh

uninstall:
	./install.sh --uninstall

dist: tidy
	mkdir -p dist
	tar --transform 's,^,sshm-$(VERSION)/,' -czf dist/sshm-$(VERSION).tar.gz \
		--exclude='__pycache__' --exclude='.pytest_cache' --exclude='dist' \
		src tests packaging scripts .copr install.sh pyproject.toml Makefile README.md CHANGELOG.md LICENSE
	@echo "dist/sshm-$(VERSION).tar.gz"

zip: tidy
	mkdir -p dist
	cd .. && zip -qr $(CURDIR)/dist/sshm-$(VERSION).zip $(notdir $(CURDIR)) \
		-x '*/__pycache__/*' '*/.pytest_cache/*' '*/.ruff_cache/*' '*/dist/*' '*.egg-info/*'
	@echo "dist/sshm-$(VERSION).zip"

bump:
	@test -n "$(BUMP)" || (echo "usage: make bump BUMP=patch|minor|major|X.Y.Z NOTE='...'"; exit 2)
	python3 scripts/bump_version.py $(BUMP) "$(or $(NOTE),Maintenance release)"

version:
	@echo $(VERSION)

srpm:
	$(MAKE) -f .copr/Makefile srpm outdir=$(CURDIR)/dist

release-notes:
	@python3 scripts/release_notes.py $(VERSION)

tidy:
	rm -rf build .pytest_cache .ruff_cache src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean: tidy
	rm -rf dist
