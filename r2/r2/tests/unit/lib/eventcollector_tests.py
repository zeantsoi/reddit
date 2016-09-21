#!/usr/bin/env python
# coding=utf-8
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

from collections import defaultdict
import datetime
import unittest

import mock
import pytz
from pylons import app_globals as g
from pylons import Request, Response
from mock import MagicMock, Mock, PropertyMock

from r2.tests import RedditTestCase
from r2.models import Account, Comment, FakeAccount, Link, Subreddit
from r2.lib import hooks
from r2.lib.eventcollector import EventQueue
from r2.tests import MockEventQueue
from r2 import models


FAKE_DATE = datetime.datetime(2005, 6, 23, 3, 14, 0, tzinfo=pytz.UTC)


class TestEventCollector(RedditTestCase):

    def setUp(self):
        super(TestEventCollector, self).setUp()
        self.mock_eventcollector()
        self.autopatch(hooks, "get_hook")

    def test_vote_event(self):
        self.patch_liveconfig("events_collector_vote_sample_rate", 1.0)
        enum_name = "foo"
        enum_note = "bar"
        notes = "%s(%s)" % (enum_name, enum_note)
        initial_vote = MagicMock(is_upvote=True, is_downvote=False,
                                 is_automatic_initial_vote=True,
                                 previous_vote=None,
                                 date=FAKE_DATE,
                                 data={"rank": MagicMock()},
                                 name="initial_vote",
                                 effects=MagicMock(
                                     note_codes=[enum_name],
                                     serializable_data={"notes": notes}))
        g.events.vote_event(initial_vote)

        g.events.queue_production.assert_event_item(
            dict(
                event_topic="vote_server",
                event_type="server_vote",
                payload={
                    'vote_direction': 'up',
                    'target_type': 'magicmock',
                    'target_age_seconds': initial_vote.thing._age.total_seconds(),
                    'target_rank': initial_vote.data['rank'],
                    'sr_id': initial_vote.thing.subreddit_slow._id,
                    'sr_name': initial_vote.thing.subreddit_slow.name,
                    'target_fullname': initial_vote.thing._fullname,
                    'target_name': initial_vote.thing.name,
                    'target_id': initial_vote.thing._id,
                    'details_text': notes,
                    'process_notes': enum_name,
                    'auto_self_vote': True,
                }
            )
        )

    def test_vote_event_with_prev(self):
        self.patch_liveconfig("events_collector_vote_sample_rate", 1.0)
        upvote = MagicMock(name="upvote",
                           is_automatic_initial_vote=False,
                           date=FAKE_DATE,
                           data={"rank": MagicMock()})
        upvote.previous_vote = MagicMock(name="previous_vote",
                                         date=FAKE_DATE,
                                         is_upvote=False, is_downvote=True)
        g.events.vote_event(upvote)

        g.events.queue_production.assert_event_item(
            dict(
                event_topic="vote_server",
                event_type="server_vote",
                payload={
                    'vote_direction': 'up',
                    'target_type': 'magicmock',
                    'target_age_seconds': upvote.thing._age.total_seconds(),
                    'target_rank': upvote.data['rank'],
                    'sr_id': upvote.thing.subreddit_slow._id,
                    'sr_name': upvote.thing.subreddit_slow.name,
                    'target_fullname': upvote.thing._fullname,
                    'target_name': upvote.thing.name,
                    'target_id': upvote.thing._id,
                    'prev_vote_ts': self.created_ts_mock,
                    'prev_vote_direction': 'down',
                }
            )
        )

    def test_submit_event(self):
        self.patch_liveconfig("events_collector_submit_sample_rate", 1.0)
        new_link = MagicMock(name="new_link", _date=FAKE_DATE)
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.submit_event(new_link, context=context, request=request)

        g.events.queue_production.assert_event_item(
            dict(
                event_topic="submit_events",
                event_type="ss.submit",
                payload={
                    'domain': request.host,
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'user_neutered': new_link.author_slow._spam,
                    'post_id': new_link._id,
                    'post_fullname': new_link._fullname,
                    'post_title': new_link.title,
                    'post_type': "self",
                    'post_body': new_link.selftext,
                    'sr_id': new_link.subreddit_slow._id,
                    'sr_name': new_link.subreddit_slow.name,
                    'geoip_country': context.location,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    }
                }
            )
        )

    def test_sr_created_event(self):
        sr = MagicMock(name="new_subreddit", _date=FAKE_DATE)
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        base_url = '/some/path'
        g.events.sr_created_event(sr, context=context, request=request,
                                  base_url=base_url)

        g.events.queue_production.assert_event_item(
            dict(
                event_topic="subreddit_create_events",
                event_type="ss.subreddit_created",
                payload={
                    'sr_id': sr._id,
                    'sr_name': sr.name,
                    'sr_type': sr.type,
                    'base_url': base_url,
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_neutered': sr.author_slow._spam,
                    'domain': request.host,
                    'geoip_country': context.location,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_features': context.user.user_features,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    }
                }
            )
        )

    def test_report_event_link(self):
        self.patch_liveconfig("events_collector_report_sample_rate", 1.0)

        target = MagicMock(name="target")
        target.__class__ = Link
        target._deleted = False
        target.author_slow._deleted = False

        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.report_event(
            target=target, context=context, request=request
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': "ss.report",
                'event_topic': 'report_events',
                'payload': {
                    'process_notes': "CUSTOM",
                    'target_fullname': target._fullname,
                    'target_name': target.name,
                    'target_title': target.title,
                    'target_type': "self",
                    'target_author_id': target.author_slow._id,
                    'target_author_name': target.author_slow.name,
                    'target_id': target._id,
                    'target_age_seconds': target._age.total_seconds(),
                    'target_created_ts': self.created_ts_mock,
                    'domain': request.host,
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'referrer_url': request.headers.get(),
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'session_referrer_domain': self.domain_mock(),
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    }
                }
            }
        )

    def test_mod_event(self):
        self.patch_liveconfig("events_collector_mod_sample_rate", 1.0)
        mod = MagicMock(name="mod")
        modaction = MagicMock(name="modaction", date=FAKE_DATE)
        subreddit = MagicMock(name="subreddit")
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.mod_event(
            modaction, subreddit, mod, context=context, request=request
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': modaction.action,
                'event_topic': 'mod_events',
                'payload': {
                    'sr_id': subreddit._id,
                    'sr_name': subreddit.name,
                    'domain': request.host,
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'referrer_url': request.headers.get(),
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'session_referrer_domain': self.domain_mock(),
                    'details_text': modaction.details_text,
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    }
                }
            }
        )

    def test_quarantine_event(self):
        self.patch_liveconfig("events_collector_quarantine_sample_rate", 1.0)
        event_type = MagicMock(name="event_type")
        subreddit = MagicMock(name="subreddit")
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.quarantine_event(
            event_type, subreddit, context=context, request=request
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': event_type,
                'event_topic': 'quarantine',
                "payload": {
                    'domain': request.host,
                    'referrer_domain': self.domain_mock(),
                    'verified_email': context.user.email_verified,
                    'user_id': context.user._id,
                    'sr_name': subreddit.name,
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'sr_id': subreddit._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    }
                }
            }
        )

    def test_modmail_event(self):
        self.patch_liveconfig("events_collector_modmail_sample_rate", 1.0)
        message = MagicMock(name="message", _date=FAKE_DATE)
        first_message = MagicMock(name="first_message")
        message_cls = self.autopatch(models, "Message")
        message_cls._byID.return_value = first_message
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.modmail_event(
            message, context=context, request=request
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': "ss.send_message",
                'event_topic': "message_events",
                "payload": {
                    'domain': request.host,
                    'referrer_domain': self.domain_mock(),
                    'user_id': message.author_slow._id,
                    'user_name': message.author_slow.name,
                    'user_features': context.user.user_features,
                    'message_id': message._id,
                    'message_fullname': message._fullname,
                    'message_kind': "modmail",
                    'first_message_fullname': first_message._fullname,
                    'first_message_id': first_message._id,
                    'sender_type': "moderator",
                    'is_third_party': True,
                    'third_party_metadata': "mailgun",
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'sr_id': message.subreddit_slow._id,
                    'sr_name': message.subreddit_slow.name,
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    },
                },
            }
        )

    def test_message_event(self):
        self.patch_liveconfig("events_collector_modmail_sample_rate", 1.0)
        message = MagicMock(name="message", _date=FAKE_DATE)
        first_message = MagicMock(name="first_message")
        message_cls = self.autopatch(models, "Message")
        message_cls._byID.return_value = first_message
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"
        g.events.message_event(
            message, context=context, request=request
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': "ss.send_message",
                'event_topic': "message_events",
                "payload": {
                    'domain': request.host,
                    'referrer_domain': self.domain_mock(),

                    'user_id': message.author_slow._id,
                    'user_name': message.author_slow.name,
                    'user_features':  context.user.user_features,

                    'message_id': message._id,
                    'message_fullname': message._fullname,
                    'message_kind': "message",
                    'message_body': message.body,
                    'message_subject': message.subject,
                    'first_message_fullname': first_message._fullname,
                    'first_message_id': first_message._id,
                    'sender_type': "user",
                    'is_third_party': True,
                    'third_party_metadata': "mailgun",
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    },
                },
            }
        )

    def test_subreddit_subscribe_event(self):
        context = MagicMock(name="context")
        context.user._age.total_seconds.return_value = 1000
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"

        subreddit = MagicMock(name="subreddit")
        subreddit._age.total_seconds.return_value = 1000
        subreddit._id = 1
        subreddit.name = 'cats'
        subreddit.path = '/r/cats/'

        g.events.subreddit_subscribe_event(
            True,
            False,
            subreddit,
            context.user,
            1,
            is_onboarding=False,
            request=request,
            context=context,
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': "ss.subscribe",
                'event_topic': "subscribe_events",
                "payload": {
                    'base_url': subreddit.path,
                    'is_first_subscription': False,
                    'sr_age': 1000000,
                    'sr_id': subreddit._id,
                    'sr_name': subreddit.name,
                    'user_age': 1000000,
                    'user_subscription_size': 1,
                    'domain': request.host,
                    'referrer_domain': self.domain_mock(),
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    },
                },
            }
        )

    def test_subreddit_subscribe_event_from_onboarding(self):
        context = MagicMock(name="context")
        context.user._age.total_seconds.return_value = 1000
        request = MagicMock(name="request")
        request.ip = "1.2.3.4"

        subreddit = MagicMock(name="subreddit")
        subreddit._age.total_seconds.return_value = 1000
        subreddit._id = 1
        subreddit.name = 'cats'
        subreddit.path = '/r/cats/'

        g.events.subreddit_subscribe_event(
            True,
            False,
            subreddit,
            context.user,
            1,
            is_onboarding=True,
            request=request,
            context=context,
        )

        g.events.queue_production.assert_event_item(
            {
                'event_type': "ss.subscribe",
                'event_topic': "subscribe_events",
                "payload": {
                    'base_url': subreddit.path,
                    'is_first_subscription': False,
                    'sr_age': 1000000,
                    'sr_id': subreddit._id,
                    'sr_name': subreddit.name,
                    'user_age': 1000000,
                    'user_subscription_size': 1,
                    'domain': request.host,
                    'referrer_domain': self.domain_mock(),
                    'user_id': context.user._id,
                    'user_name': context.user.name,
                    'user_features': context.user.user_features,
                    'referrer_url': request.headers.get(),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'oauth2_client_id': context.oauth2_client._id,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'oauth2_client_name': context.oauth2_client.name,
                    'process_notes': 'onboarding_experiment',
                    'geoip_country': context.location,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                        'client_ipv4_24': "1.2.3",
                        'client_ipv4_16': "1.2",
                    },
                },
            }
        )

    def test_link_hide_event(self):
        actor = FakeAccount(_id=123456, name="Hider")
        link = MagicMock(name="link")
        context = MagicMock(name="context")
        request = MagicMock(name="request")
        request.parsed_agent.app_name = None

        base_url = '/base/url'
        request.referrer = "https://www.reddit.com/"
        link.url = 'https://www.reddit.com/r/testing/comments/13st/test'

        parent_sr = link.subreddit_slow
        parent_sr._id = link.sr_id
        parent_sr.is_moderator = lambda u: None
        link_author = link.author_slow

        g.events.hide_link_event(actor, link, base_url,
                                 request=request, context=context)
        g.events.queue_production.assert_event_item(
            {
                'event_topic': 'flatlist_events',
                'event_type': 'ss.post_flatlist',
                'payload': {
                    'app_name': request.host,
                    'base_url': base_url,
                    'is_target_author': False,
                    'is_sr_moderator': False,
                    'process_notes': 'hide',
                    'sr_id': parent_sr._id,
                    'sr_name': parent_sr.name,
                    'target_created_ts': 1,
                    'target_author_name': link_author.name,
                    'target_fullname': link._fullname,
                    'target_id': link._id,
                    'target_url': link.url,
                    'target_url_domain': 'www.reddit.com',
                    'user_id': actor._id,
                    'user_name': actor.name,
                    'domain': request.host,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                    },
                    'oauth2_client_id': context.oauth2_client._id,
                    'user_features': context.user.user_features,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'referrer_url': request.headers.get('Referer'),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'geoip_country': context.location,
                },
            }
        )

    def test_link_hide_with_app_name(self):
        actor = FakeAccount(_id=123456, name="Hider")
        link = MagicMock(name="link")
        context = MagicMock(name="context")
        request = MagicMock(name="request")

        base_url = '/'
        link.url = 'https://www.reddit.com/r/testing/comments/13st/test'
        app_name = 'reddit is fun'
        request.parsed_agent.app_name = app_name
        parent_sr = link.subreddit_slow
        parent_sr._id = link.sr_id
        parent_sr.is_moderator = lambda u: None
        link_author = link.author_slow

        g.events.hide_link_event(actor, link, base_url,
                                 request=request, context=context)
        g.events.queue_production.assert_event_item(
            {
                'event_topic': 'flatlist_events',
                'event_type': 'ss.post_flatlist',
                'payload': {
                    'app_name': app_name,
                    'base_url': base_url,
                    'is_target_author': False,
                    'is_sr_moderator': False,
                    'process_notes': 'hide',
                    'sr_id': parent_sr._id,
                    'sr_name': parent_sr.name,
                    'target_created_ts': 1,
                    'target_author_name': link_author.name,
                    'target_fullname': link._fullname,
                    'target_id': link._id,
                    'target_url': link.url,
                    'target_url_domain': 'www.reddit.com',
                    'user_id': actor._id,
                    'user_name': actor.name,
                    'domain': request.host,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                    },
                    'oauth2_client_id': context.oauth2_client._id,
                    'user_features': context.user.user_features,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'referrer_url': request.headers.get('Referer'),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'geoip_country': context.location,
                },
            }
        )

    def test_mod_link_hide_event(self):
        host = "reddit.com"
        actor = FakeAccount(_id=123456, name="Hider")
        link = MagicMock(name="link")
        context = MagicMock(name="context")
        request = MagicMock(name="request", host=host)
        request.parsed_agent.app_name = None

        base_url = '/base/url'
        request.referrer = "https://www.reddit.com/"
        link.url = 'https://www.reddit.com/r/testing/comments/13st/test'

        parent_sr = link.subreddit_slow
        parent_sr._id = link.sr_id
        parent_sr.is_moderator = lambda u: MagicMock(name='sr_mod_rel')
        link_author = link.author_slow

        g.events.hide_link_event(actor, link, base_url,
                                 request=request, context=context)
        g.events.queue_production.assert_event_item(
            {
                'event_topic': 'flatlist_events',
                'event_type': 'ss.post_flatlist',
                'payload': {
                    'app_name': host,
                    'base_url': base_url,
                    'is_target_author': False,
                    'is_sr_moderator': True,
                    'process_notes': 'hide',
                    'sr_id': parent_sr._id,
                    'sr_name': parent_sr.name,
                    'target_created_ts': 1,
                    'target_author_name': link_author.name,
                    'target_fullname': link._fullname,
                    'target_id': link._id,
                    'target_url': link.url,
                    'target_url_domain': 'www.reddit.com',
                    'user_id': actor._id,
                    'user_name': actor.name,
                    'domain': request.host,
                    'oauth2_client_app_type': context.oauth2_client.app_type,
                    'obfuscated_data': {
                        'client_ip': request.ip,
                    },
                    'oauth2_client_id': context.oauth2_client._id,
                    'user_features': context.user.user_features,
                    'oauth2_client_name': context.oauth2_client.name,
                    'referrer_domain': self.domain_mock(),
                    'referrer_url': request.headers.get('Referer'),
                    'session_referrer_domain': self.domain_mock(),
                    'user_agent': request.user_agent,
                    'user_agent_parsed': request.parsed_agent.to_dict(),
                    'geoip_country': context.location,
                },
            }
        )


class TestSearchEngineCrawlEvent(unittest.TestCase):

    def run(self, result=None):
        with mock.patch.object(EventQueue, 'save_event') as mock_save_event:
            self.mock_save_event = mock_save_event
            super(TestSearchEngineCrawlEvent, self).run(result)

    @staticmethod
    def _create_mock_context():
        tmpl_context = Mock()
        tmpl_context.request_timer.elapsed_seconds.return_value = 0.123
        return tmpl_context

    @staticmethod
    def _create_mock_request(**overrides):
        defaults = dict(
            fullurl='https://www.reddit.com/',
            user_agent='msnbot/2.0b (+http://search.msn.com/msnbot.htm)',
            method='GET',
            domain='reddit.local',
            referrer=None,
        )
        mock_request = Mock(spec=Request)
        mock_request.configure_mock(**dict(defaults, **overrides))
        return mock_request

    @staticmethod
    def _create_mock_response(**overrides):
        defaults = dict(status_int=200)
        mock_response = Mock(spec=Response)
        mock_response.configure_mock(**dict(defaults, **overrides))
        return mock_response

    def test_good_case_with_user_url(self):
        mock_req = self._create_mock_request(
            fullurl='https://reddit.local/user/kntsMyDuanereOfOn',
            user_agent='Mozilla/5.0 (compatible) Feedfetcher-Google; \
                (+http://www.google.com/feedfetcher.html)',
        )
        # NOTE(wting|2016-08-15): Using Mock instead FakeAccount because we
        # can't set / access _fullname.
        mock_account = Mock(
            spec=Account,
            _id=123,
            _type_name='account',
            _fullname='t2_1371',
        )

        with mock.patch.object(Account, '_by_name', return_value=mock_account):
            g.events.search_engine_crawl_event(
                mock_req,
                self._create_mock_response(),
                self._create_mock_context())

        self.assertEquals(self.mock_save_event.call_count, 1)

    def test_good_case_with_subreddit_url(self):
        # For a sub-reddit request (e.g. http://reddit.com/r/nba), request.url
        # is '/' instead of '/r/nba'). Since simulating a functional test is
        # difficult, we're checking that request.fullurl is accessed instead
        # as a proxy.
        mock_req = self._create_mock_request()
        mock_url = PropertyMock(return_value='https://reddit.local/r/nba')
        type(mock_req).fullurl = mock_url

        with mock.patch.object(Subreddit, '_by_name'):
            g.events.search_engine_crawl_event(
                mock_req,
                self._create_mock_response(),
                self._create_mock_context())

        self.assertEquals(mock_url.call_count, 2)
        self.assertEquals(self.mock_save_event.call_count, 1)

    def test_comment_post_retrieves_link(self):
        mock_req = self._create_mock_request(
            fullurl='https://reddit.local/r/askhistorians/comments/23/old_photos_etiquette/1j5',  # noqa
            user_agent='Mozilla/5.0 (compatible) Feedfetcher-Google; \
                (+http://www.google.com/feedfetcher.html)',
        )
        mock_link = Mock(spec=Link)
        mock_link_fullname = PropertyMock(return_value='t3_abc1')
        type(mock_link)._fullname = mock_link_fullname
        mock_comment = Mock(
            spec=Comment,
            _id=123,
            _type_name='comment',
            _fullname='t1_1371',
            link=mock_link,
        )

        with mock.patch.object(Comment, '_byID36', return_value=mock_comment):
            g.events.search_engine_crawl_event(
                mock_req,
                self._create_mock_response(),
                self._create_mock_context())

        self.assertEquals(mock_link_fullname.call_count, 1)
        self.assertEquals(self.mock_save_event.call_count, 1)

    def test_missing_thing_fullname(self):
        # Sometimes URLs aren't mapped to real things, but rather fake ones
        # that lack a full name (e.g. '/r/all').
        mock_req = self._create_mock_request(
            fullurl='http://reddit.local/r/all'
        )

        g.events.search_engine_crawl_event(
            mock_req,
            self._create_mock_response(),
            self._create_mock_context())

        self.assertEquals(self.mock_save_event.call_count, 1)

    def test_exceptions_are_supressed(self):
        mock_req = self._create_mock_request()
        mock_context = self._create_mock_context()
        # This mimics when .elapsed_seconds() is called before the request
        # is finished.
        mock_context.request_timer.elapsed_seconds.side_effect = AssertionError

        g.events.search_engine_crawl_event(
            mock_req,
            self._create_mock_response(),
            mock_context)

        self.assertEquals(self.mock_save_event.call_count, 0)
