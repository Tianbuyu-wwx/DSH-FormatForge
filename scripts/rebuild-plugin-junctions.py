# rebuild-plugin-junctions.py — OBSOLETE on DSH >= 0.2.0. Kept for reference.
#
# ---------------------------------------------------------------------------
# WHY THIS IS NO LONGER PART OF THE INSTALL PROCEDURE
#
# This script bridged peer dependencies (@deepseek-ai/dsh-tools,
# @deepseek-ai/dsh-skill-filesystem) with junctions inside the plugin package,
# because the pre-0.2.0 launcher could not resolve a peer for a `link:`-installed
# plugin: Node walked up from the plugin's real path and found nothing.
#
# DSH 0.2.0 installs peer-aware resolution for linked profile packages
# (dsh-app-boot: findInterceptionLayer() -> routeLinked()). At each ancestor
# `node_modules` position it reads the *current* directory's package.json
# `peerDependencies`; a peer name that exists in the runtime table is routed to
# the host's own bundled copy, and that check runs BEFORE the physical candidate
# at the same position. So declaring the peers in package.json is sufficient —
# no node_modules bridge, and a stale one is actively harmful (it shadows the
# host copy with whatever it points at).
#
# Junction dirs left over from this script were removed during the 0.2.0
# adaptation. Do NOT re-run this unless you are targeting a pre-0.2.0 host.
#
#   python scripts/rebuild-plugin-junctions.py            # only for dsh < 0.2.0
# ---------------------------------------------------------------------------
import _winapi
import contextlib
import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUR_BASE = os.path.join(REPO, "packages", "dsh-formatforge", "node_modules", "@deepseek-ai")
PROFILE_NAME = os.environ.get("FF_PROFILE", "desktop")
PROFILE = os.path.expandvars(rf"%USERPROFILE%\.dsh\profiles\{PROFILE_NAME}\node_modules")


def discover_sources() -> list[str]:
    sources = [
        # preferred: a sibling plugin that already ships verified junctions
        os.path.join(PROFILE, "dsh-hermes-link", "node_modules", "@deepseek-ai"),
        # fallback: profile-level hoisted copies (if the pnpm layout changes)
        os.path.join(PROFILE, "@deepseek-ai"),
        # fallback (2026-08-27): a host reinstall clears the old npx cache but
        # the newly fetched dsh web ships a fresh one that carries @deepseek-ai
        *sorted(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\npm-cache\_npx\*\node_modules\@deepseek-ai"))),
    ]
    return [s for s in sources if os.path.isdir(s)]


def find_source(name: str) -> str | None:
    for base in discover_sources():
        cand = os.path.join(base, name)
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "package.json")):
            return cand
    return None


def main() -> int:
    print(
        f"WARNING: this script is obsolete for DSH >= 0.2.0 (peer-aware linked\n"
        f"         resolution now handles these peers). Only run it for a pre-0.2.0 host.\n"
        f"         target profile: {PROFILE_NAME}\n"
    )
    ok = True
    os.makedirs(OUR_BASE, exist_ok=True)
    for name in ("dsh-tools", "dsh-skill-filesystem"):
        src = find_source(name)
        dst = os.path.join(OUR_BASE, name)
        if not src:
            print(f"[MISS] no resolvable source for {name}; check the dsh installation")
            ok = False
            continue
        with contextlib.suppress(OSError):
            os.rmdir(dst)
        _winapi.CreateJunction(src, dst)
        good = os.path.isfile(os.path.join(dst, "package.json"))
        print(f"[{'OK' if good else 'FAIL'}] {name} -> {src}")
        ok = ok and good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
