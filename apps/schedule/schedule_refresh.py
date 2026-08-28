"""One-open conditional refresh state machine for the offline Schedule app."""

from schedule_model import (
    CACHE_PATH,
    OVERRIDE_PATH,
    ScheduleNormalizer,
    canonical_artifact_id,
    save_network_cache,
)


STATE_WAITING = "waiting"
STATE_VALIDATE = "validate"
STATE_NORMALIZE = "normalize"
STATE_FINALIZE = "finalize"
STATE_PERSIST = "persist"
STATE_BUILD = "build"
STATE_LAYOUT = "layout"
STATE_DONE = "done"
STATE_FAILED = "failed"


def validate_response(value, have_artifact_id=None):
    """Validate the scalar RPC object and return its exact semantic parts.

    The transport has already enforced its 8,192-byte stop before JSON decode.
    This boundary therefore owns shape and identity: accepting an array, an
    extra key or a payload whose inner UUID differs would make a cache look
    current when it is not.
    """

    if not isinstance(value, dict):
        raise ValueError("schedule RPC must return one object")
    changed = value.get("changed")
    if type(changed) is not bool:
        raise ValueError("schedule RPC changed flag must be boolean")
    expected_keys = (
        {"badge_artifact_id", "changed", "payload"}
        if changed else {"badge_artifact_id", "changed"}
    )
    if set(value) != expected_keys:
        raise ValueError("schedule RPC keys differ from contract")
    artifact_id = canonical_artifact_id(value.get("badge_artifact_id"))
    have = (
        canonical_artifact_id(have_artifact_id)
        if have_artifact_id is not None else None
    )
    if not changed:
        # With no cached UUID the SQL function cannot truthfully answer
        # unchanged. Requiring the echo also catches a response applied to the
        # wrong open after a future transport change.
        if have is None or artifact_id != have:
            raise ValueError("unchanged identity does not match cached artifact")
        return False, artifact_id, None, None

    if have is not None and artifact_id == have:
        raise ValueError("changed response reused cached artifact identity")
    payload = value.get("payload")
    validation = ScheduleNormalizer(payload)
    if validation.event.get("source_artifact_id") != artifact_id:
        raise ValueError("inner and outer artifact identities differ")
    return True, artifact_id, payload, validation


class ScheduleRefresh:
    """Advance one bounded refresh phase per rendered application frame.

    A transport callback only calls :meth:`receive`; it never validates, writes
    flash or lays out rows.  The app then calls :meth:`advance` at the start of
    later frames while continuing to draw the old view.  A returned ``swap``
    event is the sole point at which the caller replaces the visible globals.
    """

    def __init__(self, current_schedule, current_view, display_source,
                 cached_schedule, view_factory, cache_path=CACHE_PATH,
                 save_fn=save_network_cache):
        self.current_schedule = current_schedule
        self.current_view = current_view
        self.display_source = display_source
        self.cached_schedule = cached_schedule
        self.view_factory = view_factory
        self.cache_path = cache_path
        self.save_fn = save_fn
        self.have_artifact_id = (
            cached_schedule["event"].get("source_artifact_id")
            if cached_schedule is not None else None
        )
        self.manual_override = display_source == OVERRIDE_PATH
        self.state = STATE_WAITING
        self.requested = False
        self.response = None
        self.artifact_id = None
        self.payload = None
        self.normalized = None
        self.validation = None
        self.pending_view = None
        self.error = None
        self.failure_reported = False

    def request_once(self, network):
        """Ask the installed service once for this Schedule-open object."""

        if self.requested:
            return False
        self.requested = True
        requester = getattr(network, "request_schedule_refresh", None)
        if not callable(requester):
            self.state = STATE_FAILED
            self.error = "network service has no schedule refresh seam"
            return False
        try:
            accepted = requester(self.have_artifact_id, self.receive)
        except Exception as error:  # a stale /system/lib must remain offline-safe
            self.state = STATE_FAILED
            self.error = "schedule request failed: {}".format(error)
            return False
        if not accepted:
            # The service retains the open request until it can queue on a live
            # socket. False here means the seam itself refused it, not merely
            # that Wi-Fi has not associated yet.
            self.state = STATE_FAILED
            self.error = "schedule request was refused"
            return False
        return True

    def receive(self, ok, data):
        """Transport callback: stage one answer and do no expensive work."""

        if self.state != STATE_WAITING:
            return
        if not ok:
            self.state = STATE_FAILED
            self.error = "schedule request failed"
            return
        self.response = data
        self.state = STATE_VALIDATE

    def _fail(self, error):
        self.error = "{}: {}".format(type(error).__name__, error)
        self._release_objects()
        self.state = STATE_FAILED
        self.failure_reported = True
        return {"kind": "failed", "error": self.error}

    def _release_objects(self):
        """Drop graph roots once globals or flash own everything still needed.

        The decoded payload and validator each reference the complete agenda,
        and the controller otherwise also retains the old and new views after a
        swap. On the badge heap those duplicate graph roots outlive the request,
        so completion must be an explicit ownership handoff rather than waiting
        for a controller that lives until app exit to be collected.
        """

        self.response = None
        self.payload = None
        self.validation = None
        self.normalized = None
        self.pending_view = None
        self.cached_schedule = None
        self.current_schedule = None
        self.current_view = None

    def advance(self):
        """Run at most one validate/write/build/row/swap phase."""

        try:
            if self.state == STATE_FAILED:
                if not self.failure_reported:
                    self.failure_reported = True
                    return {"kind": "failed", "error": self.error}
                return None
            if self.state in (STATE_WAITING, STATE_DONE):
                return None
            if self.state == STATE_VALIDATE:
                changed, artifact_id, payload, validation = validate_response(
                    self.response, self.have_artifact_id)
                self.response = None
                self.artifact_id = artifact_id
                if not changed:
                    self.state = STATE_DONE
                    result = {"kind": "verified", "artifact_id": artifact_id}
                    self._release_objects()
                    return result
                self.payload = payload
                self.validation = validation
                self.state = STATE_NORMALIZE
                return None
            if self.state == STATE_NORMALIZE:
                if self.validation.step():
                    self.state = STATE_FINALIZE
                return None
            if self.state == STATE_FINALIZE:
                self.normalized = self.validation.finish()
                self.state = STATE_PERSIST
                return None
            if self.state == STATE_PERSIST:
                # The saver validates again at the flash boundary.  That is not
                # redundant: tests and future callers may invoke it without the
                # RPC validator, and only the rename makes this last-good.
                self.normalized = self.save_fn(
                    self.payload, self.artifact_id, path=self.cache_path,
                    validation=self.validation)
                self.cached_schedule = self.normalized
                self.have_artifact_id = self.artifact_id
                if self.manual_override:
                    self.state = STATE_DONE
                    result = {"kind": "cached", "artifact_id": self.artifact_id}
                    self._release_objects()
                    return result
                # Flash now owns the bare payload and the normalized schedule is
                # sufficient to construct the replacement. Drop the raw graph
                # before layout allocates its second cache.
                self.payload = None
                self.validation = None
                self.cached_schedule = None
                self.state = STATE_BUILD
                return None
            if self.state == STATE_BUILD:
                self.pending_view = self.view_factory(self.normalized)
                self.pending_view.begin_layout_cache()
                self.state = STATE_LAYOUT
                return None
            if self.state == STATE_LAYOUT:
                if not self.pending_view.build_layout_step():
                    return None
                self.pending_view.adopt_navigation(self.current_view)
                self.state = STATE_DONE
                result = {
                    "kind": "swap",
                    "artifact_id": self.artifact_id,
                    "schedule": self.normalized,
                    "view": self.pending_view,
                    "source": self.cache_path,
                }
                self._release_objects()
                return result
        except Exception as error:  # offline content must survive any refresh fault
            return self._fail(error)
        return self._fail(ValueError("unknown schedule refresh state"))
