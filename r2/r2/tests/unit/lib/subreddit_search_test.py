from mock import (
    call,
    Mock,
    patch,
    PropertyMock,
)

from pylons import app_globals as g

from r2.lib.db import tdb_cassandra
from r2.lib.subreddit_search import (
    load_all_reddits,
    search_reddits,
    SubredditsByPartialName,
)
from r2.tests import RedditTestCase


class TestSearchReddits(RedditTestCase):

    def setUp(self):
        """Setup instance variables for use across all tests.

        Patches the return value of `tups` on `SubredditsByPartialName._byID`
        by returning a list of tuples mimicking the following four subreddit
        conditions:

        1. subreddit.over_18 == False and subreddit.hide_ads == False
        2. subreddit.over_18 == True and subreddit.hide_ads == False
        3. subreddit.over_18 == False and subreddit.hide_ads == True
        4. subreddit.over_18 == True and subreddit.hide_ads == True

        Tuples in the `tups` list adhere to the following pattern:

        (subreddit.name, subreddit.over_18, subreddit.hide_ads)

        """
        self.not_over_18_not_unadvertisable = 'not_over_18_not_unadvertisable'
        self.over_18_not_unadvertisable = 'over_18_not_unadvertisable'
        self.not_over_18_unadvertisable = 'not_over_18_unadvertisable'
        self.over_18_unadvertisable = 'over_18_unadvertisable'
        tups = [
            (self.not_over_18_not_unadvertisable, False, False),
            (self.over_18_not_unadvertisable, True, False),
            (self.not_over_18_unadvertisable, False, True),
            (self.over_18_unadvertisable, True, True),
        ]
        tups_mock = Mock(tups=tups)
        self.autopatch(SubredditsByPartialName, '_byID',
                       return_value=tups_mock)

        self.query = Mock()

    def _assert_equal_membership(self, expected, actual):
        if not (len(expected) == len(actual) and
                sorted(expected) == sorted(actual)):
            msg = ('Expected to contain exactly %s; actually contains %s' %
                   (expected, actual))
            raise AssertionError(msg)

    def test_include_over_18_include_unadvertisable(self):
        expected = [
            self.not_over_18_not_unadvertisable,
            self.over_18_not_unadvertisable,
            self.not_over_18_unadvertisable,
            self.over_18_unadvertisable,
        ]
        actual = search_reddits(self.query)
        self._assert_equal_membership(expected, actual)

    def test_dont_include_over_18_include_unadvertisable(self):
        expected = [
            self.not_over_18_not_unadvertisable,
            self.not_over_18_unadvertisable,
        ]
        actual = search_reddits(self.query, include_over_18=False)
        self._assert_equal_membership(expected, actual)

    def test_include_over_18_dont_include_unadvertisable(self):
        expected = [
            self.not_over_18_not_unadvertisable,
            self.over_18_not_unadvertisable,
        ]
        actual = search_reddits(self.query, include_unadvertisable=False)
        self._assert_equal_membership(expected, actual)

    def test_dont_include_over_18_dont_include_unadvertisable(self):
        expected = [
            self.not_over_18_not_unadvertisable,
        ]
        actual = search_reddits(self.query, include_over_18=False,
                                include_unadvertisable=False)
        self._assert_equal_membership(expected, actual)

    @patch('r2.lib.subreddit_search.SubredditsByPartialName')
    def test_subreddit_search_not_found(self, SubredditsByPartialName):
        SubredditsByPartialName._byID.side_effect = tdb_cassandra.NotFound()
        expected = []
        actual = search_reddits(self.query)
        self._assert_equal_membership(expected, actual)


@patch('r2.lib.subreddit_search.utils')
@patch('r2.lib.subreddit_search.SubredditsByPartialName._set_values')
class TestLoadAllReddits(RedditTestCase):

    def setUp(self):
        self._reset_anti_ads_subreddits()
        self.default_subreddit = Mock(quarantine=False, over_18=False,
                                      hide_ads=False)
        type(self.default_subreddit).name = PropertyMock(return_value='foo')

    def tearDown(self):
        self._reset_anti_ads_subreddits()

    def _reset_anti_ads_subreddits(self):
        g.live_config['anti_ads_subreddits'] = []

    def _expected_calls(self, over_18, unadvertisable):
        expected_tups = {'tups': [('foo', over_18, unadvertisable)]}
        return [
            call('f', expected_tups),
            call('fo', expected_tups),
            call('foo', expected_tups),
        ]

    def test_load_default(self, _set_values, utils):
        """
        Assert (`name`, False, False) passed by default.
        """
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        expected_calls = self._expected_calls(False, False)
        _set_values.assert_has_calls(expected_calls, any_order=True)

    def test_load_not_over_18(self, _set_values, utils):
        """
        Assert (`name`, True, False) passed when over_18 is True.
        """
        self.default_subreddit.over_18 = True
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        expected_calls = self._expected_calls(True, False)
        _set_values.assert_has_calls(expected_calls, any_order=True)

    def test_load_not_hide_ads(self, _set_values, utils):
        """
        Assert (`name`, False, True) passed when hide_ads is True.
        """
        self.default_subreddit.hide_ads = True
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        expected_calls = self._expected_calls(False, True)
        _set_values.assert_has_calls(expected_calls, any_order=True)

    def test_load_not_over_18_not_hide_ads(self, _set_values, utils):
        """
        Assert (`name`, True, True) passed when over_18 and hide_ads are True.
        """
        self.default_subreddit.over_18 = True
        self.default_subreddit.hide_ads = True
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        expected_calls = self._expected_calls(True, True)
        _set_values.assert_has_calls(expected_calls, any_order=True)

    def test_load_hide_ads_on_blacklist(self, _set_values, utils):
        """
        Assert (`name`, False, True) passed when name on anti_ads_subreddits.
        """
        g.live_config['anti_ads_subreddits'] = ['foo']
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        expected_calls = self._expected_calls(False, True)
        _set_values.assert_has_calls(expected_calls, any_order=True)

    def test_load_quarantined(self, _set_values, utils):
        """
        Assert `_set_values` never called when subreddit is quarantined.
        """
        self.default_subreddit.quarantined = True
        utils.fetch_things2.return_value = [self.default_subreddit]
        load_all_reddits()
        _set_values.assert_not_called()
