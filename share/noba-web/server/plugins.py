"""Noba -- Formalized plugin system.

Plugins are Python scripts placed in ~/.config/noba/plugins/ (or the legacy
~/.config/noba-web/plugins/ directory).

Each plugin **must** export:
  - PLUGIN_NAME    (str)   -- human-readable name
  - PLUGIN_VERSION (str)   -- semver string, e.g. "1.0.0"
  - register(app, db)      -- called at load time; may add routes, cards, etc.

Each plugin **may** also export:
  - PLUGIN_ID          (str)  -- unique identifier (defaults to filename stem)
  - PLUGIN_ICON        (str)  -- FontAwesome class (default: "fa-puzzle-piece")
  - PLUGIN_DESCRIPTION (str)  -- short description for the UI
  - PLUGIN_INTERVAL    (int)  -- collection interval in seconds (default: 10)
  - REQUIRED_API_VERSION (int) -- minimum API version (default: 1)
  - collect()          -- returns dict of data for the dashboard card
  - render(data)       -- returns HTML string for the dashboard card body
  - setup()            -- called once at startup
  - teardown()         -- called on shutdown
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
from pathlib import Path

from .config import PLUGIN_API_VERSION

logger = logging.getLogger("noba")

PLUGIN_DIR = Path(os.environ.get(
    "NOBA_PLUGIN_DIR",
    os.path.expanduser("~/.config/noba/plugins"),
))

# Legacy directory -- checked as fallback
_LEGACY_PLUGIN_DIR = Path(os.path.expanduser("~/.config/noba-web/plugins"))

# File that tracks which plugins are disabled
_DISABLED_FILE = PLUGIN_DIR / ".disabled.json"


def _read_disabled() -> set[str]:
    """Read the set of disabled plugin IDs from disk."""
    try:
        if _DISABLED_FILE.is_file():
            data = json.loads(_DISABLED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
    except Exception:
        pass
    return set()


def _write_disabled(disabled: set[str]) -> None:
    """Persist the set of disabled plugin IDs to disk."""
    try:
        _DISABLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DISABLED_FILE.write_text(
            json.dumps(sorted(disabled), indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to write disabled plugins file: %s", e)


class Plugin:
    """Wrapper around a loaded plugin module."""

    def __init__(self, mod, path: str, *, enabled: bool = True) -> None:
        self.mod = mod
        self.path = path
        self.id: str = getattr(mod, "PLUGIN_ID", Path(path).stem)
        self.name: str = getattr(mod, "PLUGIN_NAME", self.id)
        self.version: str = getattr(mod, "PLUGIN_VERSION", "0.0.0")
        self.icon: str = getattr(mod, "PLUGIN_ICON", "fa-puzzle-piece")
        self.description: str = getattr(mod, "PLUGIN_DESCRIPTION", "")
        self.interval: int = getattr(mod, "PLUGIN_INTERVAL", 10)
        self.enabled: bool = enabled
        self.data: dict = {}
        self.html: str = ""
        self.error: str = ""

    def collect(self) -> None:
        if not self.enabled:
            return
        try:
            if hasattr(self.mod, "collect"):
                self.data = self.mod.collect() or {}
            if hasattr(self.mod, "render"):
                self.html = self.mod.render(self.data)
            self.error = ""
        except Exception as e:
            logger.error("Plugin %s collect error: %s", self.id, e)
            self.error = str(e)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "data": self.data,
            "html": self.html,
            "error": self.error,
        }

    def to_managed_dict(self) -> dict:
        """Extended dict for the plugin management UI."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "icon": self.icon,
            "description": self.description,
            "enabled": self.enabled,
            "error": self.error,
            "path": self.path,
        }


class PluginManager:
    """Discovers, loads, and periodically collects data from plugins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plugins: list[Plugin] = []
        self._threads: list[threading.Thread] = []
        self._shutdown = threading.Event()
        self._app = None
        self._db = None

    def discover(self, app=None, db=None) -> None:
        """Scan plugin directories and load all valid plugins."""
        self._app = app
        self._db = db
        disabled = _read_disabled()

        dirs: list[Path] = []
        if PLUGIN_DIR.is_dir():
            dirs.append(PLUGIN_DIR)
        if _LEGACY_PLUGIN_DIR.is_dir() and _LEGACY_PLUGIN_DIR != PLUGIN_DIR:
            dirs.append(_LEGACY_PLUGIN_DIR)

        for plugin_dir in dirs:
            for f in sorted(plugin_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                self._load_plugin(f, disabled)

    def _load_plugin(self, f: Path, disabled: set[str]) -> None:
        """Load a single plugin file."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"noba_plugin_{f.stem}", str(f),
            )
            if not spec or not spec.loader:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            required = getattr(mod, "REQUIRED_API_VERSION", 1)
            if required > PLUGIN_API_VERSION:
                logger.warning(
                    "Plugin %s requires API v%d but server has v%d -- skipping",
                    f.name, required, PLUGIN_API_VERSION,
                )
                return

            plugin_id = getattr(mod, "PLUGIN_ID", f.stem)
            enabled = plugin_id not in disabled

            plugin = Plugin(mod, str(f), enabled=enabled)

            # Call setup() if present
            if hasattr(mod, "setup"):
                mod.setup()

            # Call register(app, db) if present -- the formalized interface
            if hasattr(mod, "register") and self._app is not None:
                try:
                    mod.register(self._app, self._db)
                except Exception as e:
                    logger.error("Plugin %s register error: %s", plugin_id, e)
                    plugin.error = f"register failed: {e}"

            with self._lock:
                # Avoid duplicates on reload
                self._plugins = [
                    p for p in self._plugins if p.id != plugin.id
                ]
                self._plugins.append(plugin)

            logger.info("Loaded plugin: %s (%s) enabled=%s", plugin.id, f.name, enabled)
        except Exception as e:
            logger.error("Failed to load plugin %s: %s", f.name, e)

    def start(self) -> None:
        """Start background collection threads for each enabled plugin."""
        with self._lock:
            for plugin in self._plugins:
                if not plugin.enabled:
                    continue
                if any(t.name == f"plugin-{plugin.id}" and t.is_alive()
                       for t in self._threads):
                    continue
                t = threading.Thread(
                    target=self._collect_loop,
                    args=(plugin,),
                    daemon=True,
                    name=f"plugin-{plugin.id}",
                )
                t.start()
                self._threads.append(t)

    def _collect_loop(self, plugin: Plugin) -> None:
        plugin.collect()  # initial collection
        while not self._shutdown.wait(plugin.interval):
            if not plugin.enabled:
                continue
            plugin.collect()

    def stop(self) -> None:
        self._shutdown.set()
        for plugin in self._plugins:
            if hasattr(plugin.mod, "teardown"):
                try:
                    plugin.mod.teardown()
                except Exception as e:
                    logger.error("Plugin %s teardown error: %s", plugin.id, e)

    def get_all(self) -> list[dict]:
        """Return card data for all enabled plugins (used by collector)."""
        with self._lock:
            return [p.to_dict() for p in self._plugins if p.enabled]

    def get_managed(self) -> list[dict]:
        """Return management data for all plugins (admin UI)."""
        with self._lock:
            return [p.to_managed_dict() for p in self._plugins]

    def get_ids(self) -> list[str]:
        with self._lock:
            return [p.id for p in self._plugins]

    @property
    def count(self) -> int:
        with self._lock:
            return len([p for p in self._plugins if p.enabled])

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a plugin by ID. Returns True if found."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    p.enabled = True
                    disabled = _read_disabled()
                    disabled.discard(plugin_id)
                    _write_disabled(disabled)
                    logger.info("Enabled plugin: %s", plugin_id)
                    return True
        return False

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a plugin by ID. Returns True if found."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    p.enabled = False
                    disabled = _read_disabled()
                    disabled.add(plugin_id)
                    _write_disabled(disabled)
                    logger.info("Disabled plugin: %s", plugin_id)
                    return True
        return False

    def reload(self) -> None:
        """Stop all plugins, clear state, and re-discover."""
        # Stop existing collection threads
        self._shutdown.set()
        for plugin in self._plugins:
            if hasattr(plugin.mod, "teardown"):
                try:
                    plugin.mod.teardown()
                except Exception as e:
                    logger.error("Plugin %s teardown error: %s", plugin.id, e)

        # Reset state
        self._shutdown = threading.Event()
        with self._lock:
            self._plugins = []
        self._threads = []

        # Re-discover and start
        self.discover(app=self._app, db=self._db)
        self.start()
        logger.info("Plugins reloaded")

    def get_available(self, catalog_url: str = "") -> list[dict]:
        """Fetch available plugins from a remote catalog."""
        if not catalog_url:
            return []
        try:
            import httpx  # noqa: PLC0415
            r = httpx.get(catalog_url, timeout=10)
            r.raise_for_status()
            plugins = r.json()
            if isinstance(plugins, list):
                return plugins
        except Exception as e:
            logger.error("Plugin catalog fetch failed: %s", e)
        return []

    def install_plugin(self, url: str, filename: str) -> bool:
        """Download a plugin file from URL to the plugin directory."""
        import re as _re  # noqa: PLC0415
        if not _re.match(r'^[a-zA-Z0-9_-]+\.py$', filename):
            return False
        try:
            import httpx  # noqa: PLC0415
            r = httpx.get(url, timeout=30)
            r.raise_for_status()
            dest = PLUGIN_DIR / filename
            PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_text(r.text, encoding="utf-8")
            logger.info("Installed plugin: %s", filename)
            return True
        except Exception as e:
            logger.error("Plugin install failed: %s", e)
            return False


# Singleton
plugin_manager = PluginManager()
