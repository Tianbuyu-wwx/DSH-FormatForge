# Rebuild peer-dependency junctions for dsh-formatforge (run as needed).
#
# Why: this package is installed into dsh web via `link:`, so Node cannot resolve
# its peer deps (@deepseek-ai/dsh-tools, @deepseek-ai/dsh-skill-filesystem) from
# the profile's hoisted node_modules. Junctions inside the package bridge the gap.
# They are environment-specific artifacts (gitignored) and get wiped by git clean /
# pnpm reinstalls — rerun this script then:
#   python scripts/rebuild-plugin-junctions.py
import os
import sys
import _winapi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUR_BASE = os.path.join(REPO, "packages", "dsh-formatforge", "node_modules", "@deepseek-ai")
PROFILE = os.path.expandvars(r"%USERPROFILE%\.dsh\profiles\web\node_modules")

SOURCES = [
    # preferred: hermes-link already ships verified junctions to the npx cache
    os.path.join(PROFILE, "dsh-hermes-link", "node_modules", "@deepseek-ai"),
    # fallback: profile-level hoisted copies (if pnpm layout changes)
    os.path.join(PROFILE, "@deepseek-ai"),
]


def find_source(name: str) -> str | None:
    for base in SOURCES:
        cand = os.path.join(base, name)
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "package.json")):
            return cand
    return None


def main() -> int:
    ok = True
    os.makedirs(OUR_BASE, exist_ok=True)
    for name in ("dsh-tools", "dsh-skill-filesystem"):
        src = find_source(name)
        dst = os.path.join(OUR_BASE, name)
        if not src:
            print(f"[MISS] no resolvable source for {name}; check dsh web install")
            ok = False
            continue
        try:
            os.rmdir(dst)
        except OSError:
            pass
        _winapi.CreateJunction(src, dst)
        good = os.path.isfile(os.path.join(dst, "package.json"))
        print(f"[{'OK' if good else 'FAIL'}] {name} -> {src}")
        ok = ok and good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
