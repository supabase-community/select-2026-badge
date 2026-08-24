# BadgeLink /system/lib install (OWNER-DECISIONS #1) -- do not remove
import sys as _bl_sys
_bl_sys.path.append("/system/lib")
try:
    import network_runtime as _bl_network_runtime
    try:
        _bl_display = display
    except NameError:
        _bl_display = None
    def _bl_push_factory(_bl_loop, _bl_sink, _bl_enabled):
        from realtime.client import (
            BACKOFF_RESET_ON_FIRST_JOIN as _bl_backoff_reset,
            RealtimeClient as _bl_realtime_client)
        return _bl_network_runtime.device_push_factory(
            _bl_loop, _bl_sink, _bl_enabled,
            _bl_realtime_client, _bl_backoff_reset)
    _bl_network_runtime.install(
        run_function=run, badge_api=badge, rtc_device=rtc,
        display_api=_bl_display,
        push_factory=_bl_push_factory)
except Exception as _bl_network_error:
    print("BADGELINK_NETWORK boot=offline error={}".format(
        _bl_network_error.__class__.__name__))

# Eat the wakeup button press to prevent it leaking into the menu
badge.poll()

# We expect a launcher menu to be at /system/apps/menu
# (temporarily auto-launching the world app for rasteriser testing)
app_to_launch = launch("/system/apps/menu")

# Stopping in Thonny can cause launch("/system/apps/menu") to return None
if app_to_launch is not None:

    # Poster is selected by a held-level threshold. Its update consumes only
    # press edges, so an already-held key cannot leak into it. Every ordinary
    # app keeps the factory drain unchanged.
    if app_to_launch != "/system/apps/poster":
        while badge.pressed() or badge.held() or badge.released():
            badge.poll()

    launch(app_to_launch)

# Catch any exit and reset back to the launcher
reset()
