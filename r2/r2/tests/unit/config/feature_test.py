#!/usr/bin/env python
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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import collections
import unittest

import mock

from r2.config.feature.state import FeatureState
from r2.config.feature.world import World

MockAccount = collections.namedtuple('Account', 'name')
gary = MockAccount(name='gary')


class TestFeature(unittest.TestCase):
    _world = None

    @classmethod
    def world(cls):
        if not cls._world:
            cls._world = World()
            cls._world.current_user = mock.Mock(return_value='')

        return cls._world

    def _make_state(self, config, world=None):
        # Mock by hand because _parse_config is called in __init__, so we
        # can't instantiate then update.
        class MockState(FeatureState):
            def _parse_config(*args, **kwargs):
                return config
        if not world:
            world = self.world()
        return MockState('test_state', world)

    def test_enabled(self):
        cfg = {'enabled': 'on'}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(gary))

    def test_disabled(self):
        cfg = {'enabled': 'off'}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(gary))

    def test_admin_enabled(self):
        cfg = {'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(gary))

    def test_admin_disabled(self):
        cfg = {'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(gary))

    def test_employee_enabled(self):
        cfg = {'employee': True}
        mock_world = self.world()
        mock_world.is_employee = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(gary))

    def test_employee_disabled(self):
        cfg = {'employee': True}
        mock_world = self.world()
        mock_world.is_employee = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(gary))

    def test_url_enabled(self):
        mock_world = self.world()

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'test_state'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(gary))

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'x', 'test_state'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(gary))

    def test_url_disabled(self):
        mock_world = self.world()

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(gary))

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'x'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(gary))

    def test_user_in(self):
        cfg = {'users': ['gary']}
        mock_world = self.world()
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(gary))

        cfg = {'users': ['dave', 'gary']}
        mock_world = self.world()
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(gary))

    def test_user_not_in(self):
        cfg = {'users': ['']}
        mock_world = self.world()
        featurestate = self._make_state(cfg, mock_world)
        self.assertFalse(featurestate.is_enabled(gary))

        cfg = {'users': ['dave', 'joe']}
        mock_world = self.world()
        featurestate = self._make_state(cfg, mock_world)
        self.assertFalse(featurestate.is_enabled(gary))

    def test_multiple(self):
        # is_admin, globally off should still be False
        cfg = {'enabled': 'off', 'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=True)
        featurestate = self._make_state(cfg, mock_world)
        self.assertFalse(featurestate.is_enabled(gary))

        # globally on but not admin should still be True
        cfg = {'enabled': 'on', 'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=False)
        featurestate = self._make_state(cfg, mock_world)
        self.assertTrue(featurestate.is_enabled(gary))
        self.assertTrue(featurestate.is_enabled())

        # no URL but admin should still be True
        cfg = {'url': 'test_featurestate', 'admin': True}
        mock_world = self.world()
        mock_world.url_features = mock.Mock(return_value={})
        mock_world.is_admin = mock.Mock(return_value=True)
        featurestate = self._make_state(cfg, mock_world)
        self.assertTrue(featurestate.is_enabled(gary))
