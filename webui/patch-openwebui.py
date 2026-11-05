#!/usr/bin/env python3
"""Add the Sparknet console entries to an Open WebUI 0.12.x/0.13.x checkout.

The patch is deliberately tiny and idempotent: three pinned menu items that point
at the same-origin console. The console itself is served by nginx, so this script
does not add backend routes, a second auth system or a frontend fork.

Usage::

    webui/patch-openwebui.py --root /path/to/open-webui --apply
    webui/patch-openwebui.py --root /path/to/open-webui --check
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

SIDEBAR = Path("src/lib/components/layout/Sidebar.svelte")
MARKER = "sparknet-mesh"
ITEMS = ("sparknet-mesh", "sparknet-vectors", "sparknet-learning")


class PatchError(RuntimeError):
    pass


def patch(text: str) -> tuple[str, bool]:
    if MARKER in text:
        return text, False

    old_default = "const DEFAULT_PINNED_ITEMS = ['notes', 'workspace'];"
    new_default = (
        "const DEFAULT_PINNED_ITEMS = ['notes', 'workspace', 'sparknet-mesh', 'sparknet-vectors', 'sparknet-learning'];"
    )
    if old_default not in text:
        raise PatchError(
            "DEFAULT_PINNED_ITEMS anchor not found; this is not a supported Open WebUI 0.12.x/0.13.x checkout"
        )
    text = text.replace(old_default, new_default, 1)

    old_items = "$: pinnedItems = $settings?.pinnedMenuItems ?? DEFAULT_PINNED_ITEMS;"
    new_items = (
        "$: pinnedItems = [...new Set([...($settings?.pinnedMenuItems ?? DEFAULT_PINNED_ITEMS), "
        "'sparknet-mesh', 'sparknet-vectors', 'sparknet-learning'])];"
    )
    if old_items not in text:
        raise PatchError("pinnedItems anchor not found")
    text = text.replace(old_items, new_items, 1)

    old_visibility = "\t\t\tcase 'playground':\n\t\t\t\treturn $user?.role === 'admin';\n\t\t\tdefault:"
    new_visibility = (
        "\t\t\tcase 'playground':\n\t\t\t\treturn $user?.role === 'admin';\n"
        "\t\t\tcase 'sparknet-mesh':\n\t\t\t\treturn $user?.role === 'admin' || $user?.role === 'user';\n"
        "\t\t\tcase 'sparknet-vectors':\n\t\t\t\treturn $user?.role === 'admin' || $user?.role === 'user';\n"
        "\t\t\tcase 'sparknet-learning':\n\t\t\t\treturn $user?.role === 'admin';\n\t\t\tdefault:"
    )
    if old_visibility not in text:
        raise PatchError("isMenuItemVisible anchor not found")
    text = text.replace(old_visibility, new_visibility, 1)

    old_meta = "\t\t\tplayground: { label: $i18n.t('Playground'), href: '/playground', iconType: 'playground' }\n\t\t};"
    new_meta = (
        "\t\t\tplayground: { label: $i18n.t('Playground'), href: '/playground', iconType: 'playground' },\n"
        "\t\t\t'sparknet-mesh': { label: $i18n.t('Mesh'), href: '/sparknet-console/#mesh', iconType: 'sparknet' },\n"
        "\t\t\t'sparknet-vectors': { label: $i18n.t('Vectors'), "
        "href: '/sparknet-console/#vectors', iconType: 'sparknet' },\n"
        "\t\t\t'sparknet-learning': { label: $i18n.t('Learning'), "
        "href: '/sparknet-console/#learning', iconType: 'sparknet' }\n"
        "\t\t};"
    )
    if old_meta not in text:
        raise PatchError("getMenuItemMeta anchor not found")
    text = text.replace(old_meta, new_meta, 1)

    old_prefixes = "\t\tplayground: '/playground'\n\t};"
    new_prefixes = (
        "\t\tplayground: '/playground',\n"
        "\t\t'sparknet-mesh': '/sparknet-console',\n"
        "\t\t'sparknet-vectors': '/sparknet-console',\n"
        "\t\t'sparknet-learning': '/sparknet-console'\n"
        "\t};"
    )
    if old_prefixes not in text:
        raise PatchError("menuItemPathPrefixes anchor not found")
    text = text.replace(old_prefixes, new_prefixes, 1)

    icon_pattern = re.compile(
        r"(\{:else if itemId === 'playground'\}\s*<CodeIcon[^>]*/>\s*)(\{/if\})",
        re.MULTILINE,
    )
    icon_replacement = (
        r"\1{:else if itemId.startsWith('sparknet-')}\n"
        r"\t\t\t\t\t\t\t\t\t\t\t\t<WorkspaceIcon className=\"size-4\" strokeWidth=\"1.5\" />\n"
        r"\t\t\t\t\t\t\t\t\t\t\t\2"
    )
    patched, count = icon_pattern.subn(icon_replacement, text)
    if count == 0:
        raise PatchError("sidebar icon anchors not found")
    return patched, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="patch Open WebUI 0.12.x/0.13.x with the Sparknet console menu")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    path = args.root / SIDEBAR
    if not path.is_file():
        print(f"patch-openwebui: {path} not found", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    try:
        patched, changed = patch(text)
    except PatchError as exc:
        print(f"patch-openwebui: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print("patch-openwebui: already patched" if not changed else "patch-openwebui: not patched")
        return 0 if not changed else 1
    if not changed:
        print("patch-openwebui: already patched")
        return 0
    if not args.apply:
        print("patch-openwebui: dry-run; re-run with --apply")
        return 0
    shutil.copy2(path, path.with_suffix(path.suffix + ".sparknet.bak"))
    path.write_text(patched, encoding="utf-8")
    print(f"patch-openwebui: patched {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
