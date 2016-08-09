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
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################
from datetime import datetime, timedelta
from dateutil.parser import parse as date_parse
import pytz
import string
from urllib import unquote

from pylons import app_globals as g

from r2.config.extensions import api_type
from . import hooks
from .utils import randstr, to_epoch_milliseconds

LOID_COOKIE = "loid"
LOID_CREATED_COOKIE = "loidcreated"
# how long the cookie should last, by default.
EXPIRES_RELATIVE = timedelta(days=2 * 365)

GLOBAL_VERSION = 0
LOID_LENGTH = 18
LOID_CHARSPACE = string.uppercase + string.lowercase + string.digits


def to_isodate(d):
    """Generate an ISO-8601 datestamp.

    Python's `isoformat` isn't actually perfectly ISO.  This more closely
    matches the format we were getting in JS

    :param d: datetime with timezone
    :type d: :py:class:`datetime.datetime`
    :rtype: str
    """
    d = d.astimezone(pytz.UTC)
    milliseconds = ("%06d" % d.microsecond)[0:3]
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + milliseconds + "Z"


def from_isodate(dstr):
    """Extract a datetime from an ISO-8601 datestamp.

    dateutil.parse does this but it won't actually guarantee that the result
    has a timezone

    :param str dstr: datestamp in ISO-8601 format
    :rtype: :py:class:`datetime.datetime`
    """
    d = date_parse(dstr)
    # the dstr may not actually have a timezone (though we generate them with
    # one).  If it doesn't, the parsed date won't either!
    if d.tzinfo is None:
        d = pytz.UTC.localize(d)
    return d


def ensure_unquoted(cookie_str):
    """Keep unquoting.  Never surrender.

    Some of the cookies issued in the first version of this patch ended up
    doubly quote()d.  As a preventative measure, unquote several times.
    [This could be a while loop, because every iteration will cause the str
    to at worst get shorter and at best stay the same and break the loop.  I
    just don't want to replace an escaping error with a possible infinite
    loop.]

    :param str cookie_str: Cookie string.
    """
    for _ in range(3):
        new_str = unquote(cookie_str)
        if new_str == cookie_str:
            return new_str
        cookie_str = new_str


class LoId(object):
    """Container for holding and validating logged out ids.

    The primary accessor functions for this class are:

     * :py:meth:`load` to pull the ``LoId`` out of the request cookies
     * :py:meth:`save` to save an ``LoId`` to cookies
     * :py:meth:`to_dict` to serialize this object's data to the event pipe
    """

    def __init__(
        self,
        request,
        context,
        loid=None,
        new=None,
        version=GLOBAL_VERSION,
        created=None,
        serializable=True
    ):
        self.context = context
        self.request = request

        # is this a newly generated ID?
        self.new = new
        # the unique ID
        self.loid = loid and str(loid)
        # When was this loid created
        self.created = created or datetime.now(pytz.UTC)

        self.version = version

        # should this be persisted as cookie?
        self.serializable = serializable
        # should this be re-written-out even if it's not new.
        self.dirty = new

    def _trigger_event(self, action):
        g.events.loid_event(
            loid=self,
            action_name=action,
            request=self.request,
            context=self.context,
        )

    @classmethod
    def _create(cls, request, context):
        """Create and return a new logged out id and timestamp.

        This also triggers an loid_event in the event pipeline.

        :param request: current :py:module:`pylons` request object
        :param context: current :py:module:`pylons` context object
        :rtype: :py:class:`LoId`
        :returns: new ``LoId``
        """
        loid = cls(
            request=request,
            context=context,
            new=True,
            loid=randstr(LOID_LENGTH, LOID_CHARSPACE),
        )
        loid._trigger_event("create_loid")
        return loid

    @classmethod
    def load(cls, request, context, create=True):
        """Load loid (and timestamp) from cookie or optionally create one.

        :param request: current :py:module:`pylons` request object
        :param context: current :py:module:`pylons` context object
        :param bool create: On failure to load from a cookie,
        :rtype: :py:class:`LoId`
        """
        stub = cls(request, context, serializable=False)

        # for ineligible content/requests, set unserializable loid.
        if not cls.is_eligible(request, context):
            stub._trigger_event("ineligible_loid")
            return stub

        # attempt cookie loading
        loid = request.cookies.get(LOID_COOKIE)
        if loid:
            # future-proof to v1 id tracking which is dot separated fields
            loid, _, _ = unquote(loid).partition(".")
            try:
                created = ensure_unquoted(
                    request.cookies.get(LOID_CREATED_COOKIE, ""))
                created = from_isodate(created)
            except ValueError:
                created = None
            return cls(
                request,
                context,
                new=False,
                loid=loid,
                version=0,
                created=created,
            )
        # no existing cookie, so make a new one if we are allowed to
        elif create:
            return cls._create(request, context)

        # no cookie and can't make one, so send the unserializable stub
        else:
            stub._trigger_event("stub_loid")
            return stub

    def save(self, **cookie_attrs):
        """Write to cookie if serializable and dirty (generally new).

        :param dict cookie_attrs: additional cookie attrs.
        """
        if self.serializable and self.dirty:
            expires = datetime.utcnow() + EXPIRES_RELATIVE
            for (name, value) in (
                (LOID_COOKIE, self.loid),
                (LOID_CREATED_COOKIE, to_isodate(self.created)),
            ):
                d = cookie_attrs.copy()
                d.setdefault("expires", expires)
                self.context.cookies.add(name, value, **d)

    def to_dict(self, prefix=None):
        """Serialize LoId, generally for use in the event pipeline."""
        if not self.serializable:
            return {}

        d = {
            "loid": self.loid,
            "loid_created": to_epoch_milliseconds(self.created),
            "loid_new": self.new,
            "loid_version": self.version,
        }
        hook = hooks.get_hook("loid.to_dict")
        hook.call(loid=self, data=d)
        if prefix:
            d = {"{}{}".format(prefix, k): v for k, v in d.iteritems()}

        return d

    @classmethod
    def is_eligible(cls, request, context):
        # bots don't need loids
        if request.parsed_agent.bot:
            return False

        # known mobile apps don't need an loid (they won't use them anyway)
        if request.parsed_agent.app_name:
            return False

        # content pages should generate a cookie
        if context.render_style in ("html", "mobile", "compact"):
            return True

        return context.render_style.startswith(api_type())
