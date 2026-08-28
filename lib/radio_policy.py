"""BadgeLink's explicit connected-session Wi-Fi power-management policy."""


def disable_power_save(wlan, wlan_type):
    """Apply PM_NONE, verify driver readback, and return the prior PM value."""

    if not hasattr(wlan_type, "PM_NONE"):
        raise RuntimeError("network.WLAN.PM_NONE is unavailable")
    original = int(wlan.config("pm"))
    requested = int(wlan_type.PM_NONE)
    wlan.config(pm=requested)
    applied = int(wlan.config("pm"))
    if applied != requested:
        try:
            wlan.config(pm=original)
        except Exception:
            pass
        raise RuntimeError("PM_NONE readback mismatch: {} != {}".format(applied, requested))
    return original, applied


def restore_power_management(wlan, original):
    """Restore and verify the exact PM value captured before the session."""

    original = int(original)
    wlan.config(pm=original)
    restored = int(wlan.config("pm"))
    if restored != original:
        raise RuntimeError("Wi-Fi PM restore mismatch: {} != {}".format(restored, original))
    return restored
