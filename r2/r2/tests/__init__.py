# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import os
import sys
import Queue
from unittest import TestCase
from mock import patch

import baseplate.events
import pkg_resources
import paste.fixture
import paste.script.appinstall
from paste.deploy import loadapp


__all__ = ['RedditTestCase']

here_dir = os.path.dirname(os.path.abspath(__file__))
conf_dir = os.path.dirname(os.path.dirname(here_dir))

sys.path.insert(0, conf_dir)
pkg_resources.working_set.add_entry(conf_dir)
pkg_resources.require('Paste')
pkg_resources.require('PasteScript')

_app_context = False

# on case-insensitive file systems, Captcha gets masked by
# r2.lib.captcha which is also in sys.path.  This import ensures
# that the subsequent import is already in sys.modules, sidestepping
# the issue
try:
    from Captcha import Base
except ImportError:
    with patch.object(
        sys, "path",
        [x for x in sys.path if not x.endswith("r2/r2/lib")]
    ):
        from Captcha import Base

from pylons import app_globals as g


def assert_same_dict(data, expected_data, prefix=None):
    prefix = prefix or []
    for k in set(data.keys() + expected_data.keys()):
        current_prefix = prefix + [k]
        want = expected_data.get(k)
        got = data.get(k)
        if isinstance(want, dict) and isinstance(got, dict):
            assert_same_dict(got, want, prefix=current_prefix)
        elif got != want:
            raise AssertionError(
                "Mismatch for %s: %r != %r" % (
                    ".".join(current_prefix), got, want
                )
            )


class MockEventQueue(object):
    """An event-queue replacement, suitable for unit tests.

    Besides providing a mock `queue` for storing all received events, this
    class provides a set of handy assert-style functions for checking what
    was previously queued.
    """
    def __init__(self):
        self.queue = []

    def put(self, event):
        with patch("json.dumps", lambda x: x):
            event_as_dict = event.serialize()
        self.queue.append(event_as_dict)

    def assert_item_count(self, count=None):
        """Assert that `count` items have been enqueued.

        If count is none, just asserts that at least one item has been added
        to that queue
        """
        if count is None:
            assert self.queue, "no events in queue"
        else:
            assert len(self.queue) == count, \
                "expected %d events in queue, saw %d" % (count, len(self.queue))

    def assert_event_item(self, expected_data):
        self.assert_item_count(count=1)

        data = self.queue[0]

        # and do they have a timestamp, uuid, and payload?
        assert data.pop("event_ts", None) is not None, "event_ts is missing"
        assert data.pop("uuid", None) is not None, "uuid is missing"
        # there is some variability, but this should at least be present
        assert "event_topic" in data, "event_topic is missing"

        # these prints are for debgging when the subsequent assert fails
        print "GOT: ", data
        print "WANT:", expected_data
        assert_same_dict(data, expected_data)



class RedditTestCase(TestCase):
    """Base Test Case for tests that require the app environment to run.

    App startup does take time, so try to use unittest.TestCase directly when
    this isn't necessary as it'll save time.

    """
    if not _app_context:
        # the event queues want to create posix message queues, this is bad in
        # testing. mock this out now, and we'll clean the mock state every test
        baseplate.events.EventQueue = Queue.Queue

        wsgiapp = loadapp('config:test.ini', relative_to=conf_dir)
        test_app = paste.fixture.TestApp(wsgiapp)

        # this is basically what 'paster run' does (see r2/commands.py)
        test_response = test_app.get("/_test_vars")
        request_id = int(test_response.body)
        test_app.pre_request_hook = lambda self: \
            paste.registry.restorer.restoration_end()
        test_app.post_request_hook = lambda self: \
            paste.registry.restorer.restoration_begin(request_id)
        paste.registry.restorer.restoration_begin(request_id)

        _app_context = True

    def __init__(self, *args, **kwargs):
        TestCase.__init__(self, *args, **kwargs)

    assert_same_dict = staticmethod(assert_same_dict)

    def autopatch(self, obj, attr, *a, **kw):
        """Helper method to patch an object and automatically cleanup."""
        p = patch.object(obj, attr, *a, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def patch_g(self, **kw):
        """Helper method to patch attrs on pylons.g.

        Since we do this all the time.  autpatch g with the provided kw.
        """
        for k, v in kw.iteritems():
            self.autopatch(g, k, v, create=not hasattr(g, k))

    def patch_liveconfig(self, k, v):
        """Helper method to patch g.live_config (with cleanup)."""
        def cleanup(orig=g.live_config[k]):
            g.live_config[k] = orig
        g.live_config[k] = v
        self.addCleanup(cleanup)
