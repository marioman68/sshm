# COPR "SCM" builds (build method: make_srpm) run:
#     make -f .copr/Makefile srpm outdir="<dir>" spec="<spec>"
# Builds the source tarball straight from the checkout, so every push/tag can
# build without uploading anything. Also used by CI to test the spec.
TOP     := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' $(TOP)/src/sshm/__init__.py)
outdir  ?= $(TOP)/dist
spec    ?= $(TOP)/packaging/sshm.spec

.PHONY: srpm tarball

tarball:
	mkdir -p "$(outdir)/src"
	tar -C "$(TOP)" --exclude=.git --exclude=dist --exclude=__pycache__ --exclude=.pytest_cache \
	    --exclude=.ruff_cache --exclude='*.egg-info' --exclude=build \
	    --transform 's,^\.,sshm-$(VERSION),' -czf "$(outdir)/src/sshm-$(VERSION).tar.gz" .
	@echo "$(outdir)/src/sshm-$(VERSION).tar.gz"

srpm: tarball
	command -v rpmbuild >/dev/null 2>&1 || dnf -y install rpm-build
	rpmbuild -bs "$(spec)" --define "_sourcedir $(outdir)/src" --define "_srcrpmdir $(outdir)"
