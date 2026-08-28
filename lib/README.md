# `lib/`: the network runtime

This is BadgeLink, the library the badge installs to `/system/lib`. `tools/build.py` compiles every `.py` here and writes the result there, and copies `ca/` verbatim. It is not an app and it has no tile: apps reach it through the one `sys.path.append("/system/lib")` line in `main.py`.

The layout is the badge's, not a source tree's. Modules are FLAT and imported by bare name, which is why they are here by basename rather than in nested directories.

- **27 modules**, flat.
- **2 packages**: `aiohttp`, `realtime`. These stay directories because their members are named `__init__.py` and `client.py`, which only a package keeps apart.
- **3 trust anchors** under `ca/`, loaded by path, not imported.

Whether this ships at all is one roster key: `system_lib.ship` in `apps-roster.json`. `main.py` keeps its guarded import either way, so a package built without this directory is a working offline badge rather than a broken one. `NETWORKING.md` is the honest account of what the radio costs and what it is for.
