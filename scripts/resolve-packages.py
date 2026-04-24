#!/usr/bin/env python3
"""
Resolve Python package dependencies and generate a site-packages allowlist.

Reads:  package-requirements.txt (top-level packages)
Writes: package-allowlist.txt (directory/file names to copy from site-packages)

Usage:
    python resolve-packages.py [--source <conda_env_dir>] [--site-packages <path>]
"""

import argparse
import importlib.metadata
import re
import sys
from pathlib import Path

# ── Package name normalization ──────────────────────────────────────

def norm(name: str) -> str:
    """Normalize a package name for comparison (PEP 503)."""
    return re.sub(r'[-_.]+', '-', name).strip().lower()


# ── Requirements parsing ────────────────────────────────────────────

def parse_requirements(req_file: Path) -> list[tuple[str, set[str]]]:
    """Parse requirements file → list of (package_name, {extras})."""
    packages = []
    for line in req_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^([a-zA-Z0-9_.-]+)(?:\[([^\]]+)\])?', line)
        if m:
            name = m.group(1)
            extras = {e.strip() for e in m.group(2).split(',')} if m.group(2) else set()
            packages.append((name, extras))
    return packages


# ── Dependency resolution ───────────────────────────────────────────

def find_dist(name: str):
    """Find a distribution by trying multiple name forms."""
    for candidate in [name, name.lower(), name.replace('_', '-')]:
        try:
            return importlib.metadata.distribution(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def get_core_requires(name: str) -> list[str]:
    """Get only non-conditional (core) requires of a package."""
    dist = find_dist(name)
    if dist is None:
        return []
    result = []
    for req_str in (dist.requires or []):
        # Skip extra-conditional requires
        if 'extra ==' in req_str:
            continue
        # Extract package name (before version specs / extras / semicolons)
        dep_part = req_str.split(';')[0]
        dep_name = re.split(r'[\[><=!]', dep_part)[0].strip()
        if dep_name:
            result.append(dep_name)
    return result


def resolve_full(requirements: list[tuple[str, set[str]]]) -> set[str]:
    """Resolve the complete dependency tree.

    Two-stage approach:
      Stage 1: Expand extras → direct extra dependency packages.
               e.g. agno[openai] → openai
      Stage 2: For every discovered package (from stage 1 + top-level),
               recursively resolve core deps only.

    This avoids cascading extras from transitive dependencies.
    """
    all_packages = set()

    def collect_core(name: str):
        """Recursively collect core deps of a package."""
        n = norm(name)
        if n in all_packages:
            return
        all_packages.add(n)
        for dep in get_core_requires(name):
            collect_core(dep)

    for name, extras in requirements:
        # Stage 1: expand extras → direct deps
        dist = find_dist(name)
        if dist:
            for req_str in (dist.requires or []):
                m = re.search(r';\s*extra\s*==\s*["\'](\w+)["\']', req_str)
                if m and m.group(1) in extras:
                    dep_part = req_str.split(';')[0]
                    dep_name = re.split(r'[\[><=!]', dep_part)[0].strip()
                    if dep_name:
                        collect_core(dep_name)

        # Stage 2: resolve core deps of the top-level package itself
        collect_core(name)

    return all_packages


# ── Site-packages mapping ───────────────────────────────────────────

def build_allowlist(resolved: set[str], site_packages: Path) -> list[str]:
    """Map resolved package names to actual site-packages directories/files."""
    # Build: norm_package_name → set of dirs/files from dist-info metadata
    pkg_to_dirs: dict[str, set[str]] = {}

    for dist_info in sorted(site_packages.glob('*.dist-info')):
        # Package name from dist-info dir: {name}-{version}.dist-info
        raw_name = dist_info.name[: -len('.dist-info')]
        # Split off version: take everything before the last '-version' segment
        parts = raw_name.rsplit('-', 1)
        pkg_name_raw = parts[0] if len(parts) == 2 else raw_name
        n = norm(pkg_name_raw)

        if n not in resolved:
            continue

        dirs: set[str] = set()
        dirs.add(dist_info.name)

        # top_level.txt is the most reliable source
        tl = dist_info / 'top_level.txt'
        if tl.exists():
            for line in tl.read_text(encoding='utf-8').splitlines():
                top = line.strip().split('/')[0]
                if top:
                    dirs.add(top)
        else:
            # Fallback: parse RECORD
            record = dist_info / 'RECORD'
            if record.exists():
                for line in record.read_text(encoding='utf-8').splitlines():
                    path = line.split(',')[0].strip()
                    top = path.split('/')[0]
                    if top and not top.startswith('.'):
                        dirs.add(top)

        if n in pkg_to_dirs:
            pkg_to_dirs[n] |= dirs
        else:
            pkg_to_dirs[n] = dirs

    # Collect all dirs/files
    allowlist = set()
    matched_pkgs = set()
    for n, dirs in pkg_to_dirs.items():
        allowlist.update(dirs)
        matched_pkgs.add(n)

    # Report unmatched
    unmatched = resolved - matched_pkgs
    if unmatched:
        print("  WARNING: packages not found in site-packages:", file=sys.stderr)
        for u in sorted(unmatched):
            print(f"    {u}", file=sys.stderr)

    return sorted(allowlist)


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate package allowlist for build')
    parser.add_argument('--source', type=Path,
                        help='Conda env directory (auto-detected from sys.executable if omitted)')
    parser.add_argument('--site-packages', type=Path,
                        help='Site-packages path (auto-detected if omitted)')
    parser.add_argument('--requirements', type=Path,
                        default=Path(__file__).parent / 'package-requirements.txt',
                        help='Requirements file (default: scripts/package-requirements.txt)')
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).parent / 'package-allowlist.txt',
                        help='Output allowlist file (default: scripts/package-allowlist.txt)')
    args = parser.parse_args()

    # Resolve paths
    if args.site_packages:
        sp = args.site_packages
    elif args.source:
        sp = args.source / 'Lib' / 'site-packages'
    else:
        sp = Path(sys.executable).parent.parent / 'Lib' / 'site-packages'

    if not sp.exists():
        print(f"ERROR: site-packages not found: {sp}", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).parent
    req_file = args.requirements
    out_file = args.output

    if not req_file.exists():
        print(f"ERROR: requirements file not found: {req_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Site-packages: {sp}")
    print(f"Requirements:  {req_file}")

    # Parse top-level requirements
    requirements = parse_requirements(req_file)
    print(f"\nTop-level requirements:")
    for name, extras in requirements:
        extra_str = f"[{','.join(sorted(extras))}]" if extras else ""
        print(f"  {name}{extra_str}")

    # Resolve full dependency tree
    resolved = resolve_full(requirements)
    print(f"\nResolved: {len(resolved)} packages (transitive)")

    # Map to site-packages dirs
    allowlist = build_allowlist(resolved, sp)
    print(f"Allowlist: {len(allowlist)} directories/files\n")

    # Write output
    out_file.write_text('\n'.join(allowlist) + '\n', encoding='utf-8')
    print(f"Written to: {out_file}")
    print("\nItems:")
    for item in allowlist:
        print(f"  {item}")


if __name__ == '__main__':
    main()
