#!/usr/bin/env python3
"""Bundle the Rust dependencies for an offline RPM build (COPR builders have no network).

    packaging/vendor.py OUTDIR VERSION   ->  OUTDIR/sshm-VERSION-vendor.tar.xz

`cargo vendor` pulls in every platform's crates (~900 MB, mostly Windows/macOS). Crates that no Linux target
uses are reduced to their Cargo.toml plus an empty lib.rs so cargo can still resolve the lock file, which
keeps the tarball small. The real Linux dependencies are vendored untouched, checksums and all.
"""
import json, os, pathlib, shutil, subprocess, sys, tarfile, tomllib

TARGETS = ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "powerpc64le-unknown-linux-gnu", "s390x-unknown-linux-gnu"]

def main() -> None:
    out, version = pathlib.Path(sys.argv[1]).resolve(), sys.argv[2]
    root = pathlib.Path(__file__).resolve().parent.parent
    work = out / "vendor-work"
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    vendor = work / "vendor"
    subprocess.run(["cargo", "vendor", "--locked", "--versioned-dirs", str(vendor)], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    used = set()
    for t in TARGETS:
        tree = subprocess.run(["cargo", "tree", "--locked", "--target", t, "-e", "normal,build", "--prefix", "none", "--format", "{p}"],
                              cwd=root, check=True, capture_output=True, text=True).stdout
        for line in tree.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("v"):
                used.add(f"{parts[0]}-{parts[1][1:]}")
    stubbed = 0
    for d in sorted(vendor.iterdir()):
        if d.name in used:
            continue
        manifest = d / "Cargo.toml"
        meta = tomllib.loads(manifest.read_text())
        checksum = json.loads((d / ".cargo-checksum.json").read_text())
        keep = manifest.read_text()
        shutil.rmtree(d); d.mkdir()
        (d / "Cargo.toml").write_text(keep)
        lib = meta.get("lib", {}).get("path", "src/lib.rs")
        (d / lib).parent.mkdir(parents=True, exist_ok=True); (d / lib).write_text("")
        bs = meta.get("package", {}).get("build")
        if isinstance(bs, str):
            (d / bs).parent.mkdir(parents=True, exist_ok=True); (d / bs).write_text("fn main() {}\n")
        (d / ".cargo-checksum.json").write_text(json.dumps({"files": {}, "package": checksum.get("package")}))
        stubbed += 1
    tar = out / f"sshm-{version}-vendor.tar.xz"
    with tarfile.open(tar, "w:xz") as tf:
        tf.add(vendor, arcname="vendor")
    shutil.rmtree(work)
    print(f"{tar}  ({len(used)} crates vendored, {stubbed} non-Linux crates stubbed, {tar.stat().st_size // 1048576} MB)")

if __name__ == "__main__":
    main()
