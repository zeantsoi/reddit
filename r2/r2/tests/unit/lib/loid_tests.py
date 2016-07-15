from datetime import datetime
from mock import MagicMock, ANY, call
import pytz
from urllib import quote

from pylons import app_globals as g

from r2.tests import RedditTestCase
from r2.lib import hooks
from r2.lib.loid import LoId, LOID_COOKIE, LOID_CREATED_COOKIE, isodate
from r2.lib.utils import to_epoch_milliseconds


class LoidTests(RedditTestCase):
    def setUp(self):
        super(LoidTests, self).setUp()
        self.mock_eventcollector()
        self.autopatch(hooks, "get_hook")
        self.patch_liveconfig("events_collector_loid_sample_rate", 1.0)

        self.context = MagicMock(name="context")
        self.context.render_style = "html"

        self.request = MagicMock(name="request")
        self.request.cookies = {}
        self.request.parsed_agent.app_name = None
        self.request.parsed_agent.bot = False

    def make_event_payload(self):
        return {
            'user_id': self.context.user._id,
            'user_name': self.context.user.name,
            'user_features': self.context.user.user_features,

            'request_url': self.request.fullpath,
            'domain': self.request.host,
            'geoip_country': self.context.location,
            'oauth2_client_id': self.context.oauth2_client._id,
            'oauth2_client_app_type': self.context.oauth2_client.app_type,
            'oauth2_client_name': self.context.oauth2_client.name,
            'referrer_domain': self.domain_mock(),
            'referrer_url': self.request.headers.get(),
            'user_agent': self.request.user_agent,
            'user_agent_parsed': self.request.parsed_agent.to_dict(),
            'obfuscated_data': {
                'client_ip': self.request.ip,
            }
        }

    def assert_loid(self, create=True, new=True):
        loid = LoId.load(self.request, self.context, create=create)
        self.assertIsNotNone(loid.loid)
        self.assertIsNotNone(loid.created)
        self.assertIs(loid.new, new)

        loid.save()

        if not new:
            self.assertFalse(bool(self.context.cookies.add.called))
            g.events.queue_production.assert_item_count(0)
        else:
            self.context.cookies.add.assert_has_calls([
                call(
                    LOID_COOKIE,
                    quote(loid.loid),
                    expires=ANY,
                ),
                call(
                    LOID_CREATED_COOKIE,
                    isodate(loid.created),
                    expires=ANY,
                )
            ])
            payload = self.make_event_payload()
            payload.update({
                'loid_new': True,
                'loid': loid.loid,
                'loid_created': to_epoch_milliseconds(loid.created),
                'loid_version': 0,
            })
            g.events.queue_production.assert_event_item(
                dict(
                    event_topic="loid_events",
                    event_type="ss.create_loid",
                    payload=payload,
                )
            )

    def assert_no_loid(self, create=True, kind="ineligible_loid"):
        loid = LoId.load(self.request, self.context, create=create)
        self.assertFalse(loid.new)
        self.assertFalse(loid.serializable)
        loid.save()
        self.assertFalse(bool(self.context.cookies.add.called))
        payload = self.make_event_payload()
        g.events.queue_production.assert_event_item(
            dict(
                event_topic="loid_events",
                event_type="ss.%s" % kind,
                payload=payload,
            )
        )

    def make_returning_cookies(self):
        return {
            LOID_COOKIE: "foo",
            LOID_CREATED_COOKIE: isodate(datetime.now(pytz.UTC)),
        }

    def test_ftue_autocreate(self):
        self.assert_loid()

    def test_ftue_nocreate(self):
        self.assert_no_loid(create=False, kind="stub_loid")

    def test_returning(self):
        self.request.cookies = {
            LOID_COOKIE: "foo", LOID_CREATED_COOKIE: "bar"
        }
        self.assert_loid(new=False)

    def test_ftue_ineligible(self):
        self.context.render_style = "xml"
        self.assert_no_loid(kind="ineligible_loid")

    def test_returning_ineligible(self):
        self.context.render_style = "xml"
        self.request.cookies = self.make_returning_cookies()
        self.assert_no_loid(kind="ineligible_loid")

    def test_ftue_bot(self):
        self.request.parsed_agent.bot = True
        self.assert_no_loid(kind="ineligible_loid")

    def test_returning_bot(self):
        self.request.parsed_agent.bot = True
        self.request.cookies = self.make_returning_cookies()
        self.assert_no_loid(kind="ineligible_loid")
