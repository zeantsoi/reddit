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
import mock
from xml.etree import ElementTree
from pylons import app_globals as g
from paste.fixture import AppError

from r2.lib import all_sr
from r2.tests import RedditControllerTestCase


class PartnerApiTest(RedditControllerTestCase):

    CONTROLLER = 'partner_api'

    def _get(self, **overrides):
        defaults = dict(
            url='/partner_api/trending.rss',
            extra_environ=dict(REMOTE_ADDR='1.2.3.4'),
        )
        return self.app.get(**dict(defaults, **overrides))

    def test_requires_enabled_rss_toggle(self):
        try:
            with mock.patch.object(g, 'partner_api_enable_rss', False):
                self.assertRaises(AppError, self._get())
        except Exception as e:
            self.assertIn('403 Forbidden', e.message)

    def test_rss_extension(self):
        with mock.patch.object(g, 'partner_api_enable_rss', True), \
                mock.patch.object(
                    all_sr, 'get_all_hot_ids', return_value=['t5_ab']):
            resp = self._get(url='/partner_api/trending.rss')

        self.assertEqual(resp.status, 200)

        # We're not doing an exhaustive check of the RSS spec, just sanity
        # checking to make sure it's valid XML.
        root = ElementTree.fromstring(resp.body)
        self.assertEqual(root.tag, '{http://www.w3.org/2005/Atom}feed')

    def test_xml_extension(self):
        with mock.patch.object(g, 'partner_api_enable_rss', True), \
                mock.patch.object(
                    all_sr, 'get_all_hot_ids', return_value=['t5_ab']):
            resp = self._get(url='/partner_api/trending.xml')

        self.assertEqual(resp.status, 200)

    def test_supports_rss_extensions_only(self):
        with mock.patch.object(g, 'partner_api_enable_rss', True):
            try:
                self.assertRaises(
                    AppError,
                    self._get(url='/partner_api/trending.html')
                )
            except Exception as e:
                self.assertIn('404 Not Found', e.message)
