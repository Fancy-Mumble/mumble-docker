#!/usr/bin/env python3
"""In-container driver for the Mumble server fuzz harnesses.

This runs *inside* the `mumble-fuzz` image (see ``Dockerfile.fuzz``) against the
mumble-server source tree bind-mounted at ``/src``.  It is not meant to be run
on the host directly - use ``python -m tools.dev_fuzz`` from the mumble-docker
repo, which builds the image and invokes this with the right mounts.

Subcommands:

    list                 list every available target
    rust  <target>       run a Rust cargo-fuzz target
    cpp   <target>       build + run a C++ libFuzzer target
    smoke                bounded run of every target (CI gate)
    all                  run every target for a fixed time budget each

Anything after ``--`` is passed straight through to libFuzzer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The mumble-server checkout is bind-mounted here by `tools.dev_fuzz`.
REPO_ROOT = Path(os.environ.get("FUZZ_REPO", "/src"))
RUST_DIR = REPO_ROOT / "3rdparty" / "mumble-plugin-host"
CPP_DIR = REPO_ROOT / "fuzzing" / "cpp"
CPP_BUILD_DIR = REPO_ROOT / "build-fuzz-cpp"
CORPUS_DIR = REPO_ROOT / "fuzzing" / "corpus"

RUST_TARGETS = [
    "fileserver_signing",
    "fileserver_jwt",
    "fileserver_access_mode",
    "fileserver_path_validate",
    "host_manifest",
    "host_zip",
    "host_targz",
]

# C++ target -> seed-corpus subdirectory under fuzzing/corpus.
CPP_TARGETS = {
    "fuzz_ssrf": "ssrf",
    "fuzz_opengraph": "opengraph",
    "fuzz_htmlfilter": "htmlfilter",
    "fuzz_protocol": "protocol",
}

# Iterations / time used for `--smoke` (fast, deterministic-ish pass for CI).
SMOKE_RUNS = "20000"
SMOKE_MAX_TOTAL_TIME = "60"  # seconds, hard cap


def run(cmd, **kwargs):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, **kwargs)


def cmd_list(_args):
    print("Rust targets (cargo-fuzz):")
    for t in RUST_TARGETS:
        print(f"  rust {t}")
    print("\nC++ targets (libFuzzer):")
    for t in CPP_TARGETS:
        print(f"  cpp  {t}")
    return 0


def libfuzzer_args(args):
    """Common libFuzzer CLI args derived from --smoke / passthrough."""
    extra = list(args.passthrough)
    if args.smoke:
        extra = [f"-runs={SMOKE_RUNS}", f"-max_total_time={SMOKE_MAX_TOTAL_TIME}"] + extra
    return extra


def cmd_rust(args):
    if args.target not in RUST_TARGETS:
        print(f"unknown rust target: {args.target}", file=sys.stderr)
        return 2
    if shutil.which("cargo") is None:
        print("cargo not found in image", file=sys.stderr)
        return 127
    # `+nightly` overrides the workspace's pinned stable toolchain, which
    # cargo-fuzz needs for the sanitizer build.
    cmd = ["cargo", "+nightly", "fuzz", "run", args.target]
    extra = libfuzzer_args(args)
    if extra:
        cmd += ["--"] + extra
    return run(cmd, cwd=RUST_DIR).returncode


def configure_and_build_cpp():
    env = dict(os.environ)
    env.setdefault("CC", "clang")
    env.setdefault("CXX", "clang++")
    CPP_BUILD_DIR.mkdir(exist_ok=True)
    configure = ["cmake", "-S", str(CPP_DIR), "-B", str(CPP_BUILD_DIR),
                 "-DCMAKE_BUILD_TYPE=Debug"]
    if shutil.which("ninja"):
        configure += ["-G", "Ninja"]
    rc = run(configure, env=env).returncode
    if rc != 0:
        return rc
    return run(["cmake", "--build", str(CPP_BUILD_DIR)], env=env).returncode


def find_cpp_binary(target):
    candidate = CPP_BUILD_DIR / target
    return candidate if candidate.exists() else None


def cmd_cpp(args):
    if args.target is not None and args.target not in CPP_TARGETS:
        print(f"unknown cpp target: {args.target}", file=sys.stderr)
        return 2
    rc = configure_and_build_cpp()
    if rc != 0 or args.build_only:
        return rc
    binary = find_cpp_binary(args.target)
    if binary is None:
        print(
            f"binary for {args.target} not built (its Qt6/protobuf deps may be "
            f"missing - see configure output above)",
            file=sys.stderr,
        )
        return 1
    corpus = CORPUS_DIR / CPP_TARGETS[args.target]
    corpus.mkdir(parents=True, exist_ok=True)
    cmd = [str(binary), str(corpus)] + libfuzzer_args(args)
    return run(cmd).returncode


def _run_every(extra_libfuzzer):
    """Run every target with ``extra_libfuzzer`` appended; return failures."""
    failures = []
    for t in RUST_TARGETS:
        ns = argparse.Namespace(target=t, smoke=False, passthrough=list(extra_libfuzzer))
        if cmd_rust(ns) != 0:
            failures.append(f"rust {t}")
    if configure_and_build_cpp() == 0:
        for t in CPP_TARGETS:
            if find_cpp_binary(t) is None:
                print(f"skipping cpp {t} (not built)")
                continue
            ns = argparse.Namespace(
                target=t, smoke=False, build_only=False, passthrough=list(extra_libfuzzer)
            )
            if cmd_cpp(ns) != 0:
                failures.append(f"cpp {t}")
    else:
        print("C++ harness build failed; skipping C++ targets", file=sys.stderr)
    return failures


def _report(failures, label):
    if failures:
        print(f"\n{label.upper()} FAILURES:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print(f"\n{label}: all targets passed")
    return 0


def cmd_smoke(_args):
    """Bounded CI gate: a few thousand iterations / <=60s per target."""
    return _report(
        _run_every([f"-runs={SMOKE_RUNS}", f"-max_total_time={SMOKE_MAX_TOTAL_TIME}"]),
        "smoke",
    )


def cmd_all(args):
    """Run every target for ``--time`` seconds each (default 300)."""
    return _report(_run_every([f"-max_total_time={args.time}"]), "all")


def main(argv):
    p = argparse.ArgumentParser(
        prog="fuzz_runner",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list available targets").set_defaults(func=cmd_list)

    pr = sub.add_parser("rust", help="run a Rust cargo-fuzz target")
    pr.add_argument("target")
    pr.add_argument("--smoke", action="store_true", help="bounded run then exit (CI)")
    pr.add_argument("passthrough", nargs="*", help="extra libFuzzer args")
    pr.set_defaults(func=cmd_rust)

    pc = sub.add_parser("cpp", help="build and run a C++ libFuzzer target")
    pc.add_argument("target", nargs="?", help="omit with --build-only to just compile")
    pc.add_argument("--smoke", action="store_true", help="bounded run then exit (CI)")
    pc.add_argument("--build-only", action="store_true", help="configure + build, do not run")
    pc.add_argument("passthrough", nargs="*", help="extra libFuzzer args")
    pc.set_defaults(func=cmd_cpp)

    sub.add_parser("smoke", help="bounded run of every target (CI)").set_defaults(func=cmd_smoke)

    pa = sub.add_parser("all", help="run every target for a fixed time budget each")
    pa.add_argument("--time", type=int, default=300,
                    help="seconds to spend on each target (default: 300)")
    pa.set_defaults(func=cmd_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
