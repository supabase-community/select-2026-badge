"""Optional Profile accent adapter with a dependency-free fallback."""

import json
import sys


FALLBACK = (62, 207, 142)
PROFILE_PATH = "/profile.json"
PROFILE_APP = "/system/apps/badge"
SKIN_MODULES = (
    "skins.supabase",
    "skins.pixelstorm",
    "skins.filtered",
    "skins.animated",
)


def load_accent(path=PROFILE_PATH):
    inserted = False
    try:
        with open(path, "r") as source:
            profile = json.load(source)
        skin = int(profile.get("skin", 0)) % len(SKIN_MODULES)
        if PROFILE_APP not in sys.path:
            sys.path.insert(0, PROFILE_APP)
            inserted = True
        module = __import__(SKIN_MODULES[skin], None, None, ("ACCENT",), 0)
        accent = tuple(int(channel) for channel in module.ACCENT)
        if len(accent) != 3 or any(channel < 0 or channel > 255 for channel in accent):
            raise ValueError("invalid profile accent")
        return accent, SKIN_MODULES[skin].split(".")[-1]
    except (OSError, ValueError, TypeError, OverflowError, ImportError, AttributeError):
        return FALLBACK, "fallback"
    finally:
        if inserted and sys.path and sys.path[0] == PROFILE_APP:
            sys.path.pop(0)
