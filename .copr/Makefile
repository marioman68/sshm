# COPR "SCM" builds (build method: make_srpm) run:
#     make -f .copr/Makefile srpm outdir="<dir>" spec="<spec>"
# SRPM generation has network access, the RPM build does not: so this step makes the source tarball
# straight from the checkout plus a tarball of the Rust dependencies (packaging/vendor.py).
TOP     := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' $(TOP)/Cargo.toml | head -1)
outdir  ?= $(TOP)/dist
spec    ?= $(TOP)/packaging/sshm.spec

.PHONY: srpm tarball vendor deps check-version

deps:
	command -v rpmbuild >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1 || dnf -y install rpm-build cargo python3

tarball:
	mkdir -p "$(outdir)/src"
	tar -C "$(TOP)" --exclude=.git --exclude=./dist --exclude=./target --exclude=./legacy \
	    --transform 's,^\.,sshm-$(VERSION),' -czf "$(outdir)/src/sshm-$(VERSION).tar.gz" .

vendor: deps
	mkdir -p "$(outdir)/src"
	python3 "$(TOP)/packaging/vendor.py" "$(outdir)/src" "$(VERSION)"

check-version:
	@sv=$$(sed -n 's/^Version: *//p' "$(spec)"); [ "$$sv" = "$(VERSION)" ] || { echo "Version mismatch: Cargo.toml $(VERSION), $(spec) $$sv" >&2; exit 1; }

srpm: check-version deps tarball vendor
	rpmbuild -bs "$(spec)" --define "_sourcedir $(outdir)/src" --define "_srcrpmdir $(outdir)"
