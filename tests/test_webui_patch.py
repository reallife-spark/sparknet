"""The Open WebUI sidebar patch is tiny, idempotent and fail-closed.

The test uses a synthetic 0.12.x Sidebar fragment. It proves the anchors, the
three menu entries and the second-run no-op without needing an Open WebUI
checkout in the repository.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATCH = ROOT / "webui" / "patch-openwebui.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("sparknet_patch_openwebui_test", PATCH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


patch = _load()

SIDEBAR = """<script>
	const DEFAULT_PINNED_ITEMS = ['notes', 'workspace'];
	$: pinnedItems = $settings?.pinnedMenuItems ?? DEFAULT_PINNED_ITEMS;
	$: isMenuItemVisible = (id) => {
		switch (id) {
			case 'notes':
				return true;
			case 'playground':
				return $user?.role === 'admin';
			default:
				return false;
		}
	};
	const getMenuItemMeta = (id) => {
		const items = {
			notes: { label: $i18n.t('Notes'), href: '/notes', iconType: 'note' },
			playground: { label: $i18n.t('Playground'), href: '/playground', iconType: 'playground' }
		};
		return items[id];
	};
	const menuItemPathPrefixes = {
		notes: '/notes',
		playground: '/playground'
	};
</script>
<a>
	{#if itemId === 'notes'}
		<NotesIcon className="size-4" strokeWidth="1.5" />
	{:else if itemId === 'playground'}
		<CodeIcon className="size-4" strokeWidth="1.5" />
	{/if}
</a>
<a>
	{#if itemId === 'notes'}
		<NotesIcon className="size-4" strokeWidth="1.5" />
	{:else if itemId === 'playground'}
		<CodeIcon className="size-4" strokeWidth="1.5" />
	{/if}
</a>
"""


def test_patch_adds_three_menu_items_and_is_idempotent() -> None:
    patched, changed = patch.patch(SIDEBAR)
    assert changed is True
    assert "sparknet-mesh" in patched
    assert "sparknet-vectors" in patched
    assert "sparknet-learning" in patched
    assert "/sparknet-console/#mesh" in patched
    assert patched.count("itemId.startsWith('sparknet-')") == 2
    assert patch.patch(patched)[1] is False


def test_patch_refuses_a_file_without_the_012_anchors() -> None:
    with pytest.raises(patch.PatchError):
        patch.patch("<script>const other = 1;</script>\n")
