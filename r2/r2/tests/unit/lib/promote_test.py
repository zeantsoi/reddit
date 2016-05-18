import datetime
import pytz
import unittest

from mock import MagicMock, Mock, patch
from pylons import app_globals as g

from r2.tests import RedditTestCase
from r2.lib.authorize.api import Transaction
from r2.lib import promote
from r2.lib.promote import (
    can_extend,
    can_refund,
    free_campaign,
    extend_campaign,
    get_nsfw_collections_srnames,
    get_refund_amount,
    get_spent_amount,
    get_unspent_budget,
    is_pre_cpm,
    is_underdelivered,
    RefundProviderException,
    refund_campaign,
    srnames_from_site,
    InapplicableRefundException,
    get_utc_offset,
    make_daily_promotions,
)
from r2.models import (
    Account,
    Collection,
    FakeAccount,
    Frontpage,
    Link,
    PromoCampaign,
    Subreddit,
    MultiReddit,
)
from r2.tests import RedditTestCase

# use the original function to avoid going out to memcached.
get_nsfw_collections_srnames = get_nsfw_collections_srnames.memoized_fn

subscriptions_srnames = ["foo", "bar"]
subscriptions = map(lambda srname: Subreddit(name=srname), subscriptions_srnames)
multi_srnames = ["bing", "bat"]
multi_subreddits = map(lambda srname: Subreddit(name=srname), multi_srnames)
nice_srname = "mylittlepony"
nsfw_srname = "pr0n"
questionably_nsfw = "sexstories"
quarantined_srname = "croontown"
naughty_subscriptions = [
    Subreddit(name=nice_srname),
    Subreddit(name=nsfw_srname, over_18=True),
    Subreddit(name=quarantined_srname, quarantine=True),
]
nsfw_collection_srnames = [questionably_nsfw, nsfw_srname]
nsfw_collection = Collection(
    name="after dark",
    sr_names=nsfw_collection_srnames,
    over_18=True
)
recent_subreddits = [
    Subreddit(name=nice_srname, id=1),
    Subreddit(name=nsfw_srname, over_18=True, id=2),
]


class TestSRNamesFromSite(RedditTestCase):
    def setUp(self):
        super(TestSRNamesFromSite, self).setUp()
        self.logged_in = Account(name="test")
        self.logged_out = FakeAccount()

    def test_frontpage_logged_out(self):
        srnames = srnames_from_site(self.logged_out, Frontpage)

        self.assertEqual(srnames, set())

    @patch("r2.models.Subreddit.user_subreddits")
    def test_frontpage_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, set(subscriptions_srnames))

    def test_multi_logged_out(self):
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_out, multi)

        self.assertEqual(srnames, set(multi_srnames))

    @patch("r2.models.Subreddit.user_subreddits")
    def test_multi_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_in, multi)

        self.assertEqual(srnames, set(multi_srnames))

    def test_subreddit_logged_out(self):
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_out, subreddit)

        self.assertEqual(srnames, {srname})

    @patch("r2.models.Subreddit.user_subreddits")
    def test_subreddit_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname})

    @patch("r2.models.Subreddit.user_subreddits")
    def test_quarantined_subscriptions_are_never_included(self, user_subreddits):
        user_subreddits.return_value = naughty_subscriptions
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, {nice_srname})
        self.assertTrue(len(srnames & {quarantined_srname}) == 0)

    @patch("r2.models.Subreddit.user_subreddits")
    def test_nsfw_subscriptions_arent_included_when_viewing_frontpage(self, user_subreddits):
        user_subreddits.return_value = naughty_subscriptions
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, {nice_srname})
        self.assertTrue(len(srnames & {nsfw_srname}) == 0)

    @patch("r2.models.Collection.get_all")
    def test_get_nsfw_collections_srnames(self, get_all):
        get_all.return_value = [nsfw_collection]
        srnames = get_nsfw_collections_srnames()

        self.assertEqual(srnames, set(nsfw_collection_srnames))

    @patch("r2.lib.promote.get_nsfw_collections_srnames")
    def test_remove_nsfw_collection_srnames_on_frontpage(self, get_nsfw_collections_srnames):
        get_nsfw_collections_srnames.return_value = set(nsfw_collection.sr_names)
        with patch.object(Subreddit, "user_subreddits", return_value=[
            Subreddit(name=nice_srname),
            Subreddit(name=questionably_nsfw),
        ]):
            frontpage_srnames = srnames_from_site(self.logged_in, Frontpage)

            self.assertEqual(frontpage_srnames, {nice_srname})
            self.assertTrue(len(frontpage_srnames & {questionably_nsfw}) == 0)

    @patch("r2.lib.promote.c")
    def test_remove_nsfw_recent_subreddits_on_frontpage(self, c):
        c.recent_subreddits = recent_subreddits
        with patch.object(Subreddit, "user_subreddits", return_value=[]):
            frontpage_srnames = srnames_from_site(self.logged_in, Frontpage)

            self.assertEqual(
                frontpage_srnames,
                {nice_srname},
            )
            self.assertTrue(len(frontpage_srnames & {nsfw_srname}) == 0)


class TestPromoteRefunds(RedditTestCase):
    def setUp(self):
        super(TestPromoteRefunds, self).setUp()
        self.link = Mock()
        self.campaign = MagicMock(spec=PromoCampaign)
        self.campaign._id = 1
        self.campaign.owner_id = 1
        self.campaign.trans_id = 1
        self.campaign.start_date = datetime.datetime.now()
        self.campaign.end_date = (datetime.datetime.now() +
            datetime.timedelta(days=1))
        self.campaign.total_budget_dollars = 200.

    @patch("r2.lib.promote.get_refund_amount")
    @patch("r2.lib.promote.get_transactions")
    def test_can_refund_returns_false_if_transaction_not_charged(
            self, get_transactions, get_refund_amount):
        transaction = MagicMock()
        get_transactions.return_value = {self.campaign._id: transaction}
        transaction.is_charged = MagicMock()
        transaction.is_charged.return_value = False

        self.campaign.is_freebie = MagicMock()
        self.campaign.is_freebie.return_value = False

        self.assertFalse(can_refund(self.link, self.campaign))

    @patch("r2.lib.promote.get_refund_amount")
    @patch("r2.lib.promote.get_transactions")
    def test_can_refund_returns_false_if_transaction_is_already_refunded(
            self, get_transactions, get_refund_amount):
        transaction = MagicMock()
        get_transactions.return_value = {self.campaign._id:transaction}
        transaction.is_charged = MagicMock()
        transaction.is_charged.return_value = True
        transaction.is_refund = MagicMock()
        transaction.is_refund.return_value = True

        self.campaign.is_freebie = MagicMock()
        self.campaign.is_freebie.return_value = False

        self.assertFalse(can_refund(self.link, self.campaign))

    @patch("r2.lib.promote.get_refund_amount")
    @patch("r2.lib.promote.get_transactions")
    def test_can_refund_returns_false_if_refund_amount_is_zero(
            self, get_transactions, get_refund_amount):
        transaction = MagicMock()
        get_transactions.return_value = {self.campaign._id: transaction}
        get_refund_amount.return_value = 0
        transaction.is_charged = MagicMock()
        transaction.is_charged.return_value = True

        self.campaign.is_freebie = MagicMock()
        self.campaign.is_freebie.return_value = False

        self.assertFalse(can_refund(self.link, self.campaign))

    def test_can_refund_returns_false_if_campaign_is_free(self):
        self.campaign.is_freebie = MagicMock()
        self.campaign.is_freebie.return_value = True

        self.assertFalse(can_refund(self.link, self.campaign))

    @patch("r2.lib.promote.can_refund")
    def test_refund_campaign_throws_if_transaction_cant_be_refunded(
            self, can_refund):
        can_refund.return_value = False

        with self.assertRaises(InapplicableRefundException):
            refund_campaign(self.link, self.campaign)

    @patch("r2.models.Account._byID")
    @patch('r2.models.PromotionLog.add')
    @patch("r2.lib.promote.can_refund")
    @patch("r2.lib.promote.get_refund_amount")
    @patch("r2.lib.promote.g.events.campaign_payment_refund_event")
    @patch("r2.lib.authorize.refund_transaction")
    def test_refund_campaign_throws_if_refund_fails(
            self, refund_transaction, campaign_payment_refund_event,
            get_refund_amount, can_refund, account_by_id, promo_log_add):
        error_message = "because we're testing errors!"
        refund_transaction.return_value = (False, error_message)
        can_refund.return_value = True
        account_by_id.return_value = MagicMock()

        with self.assertRaisesRegexp(RefundProviderException, error_message):
            refund_campaign(self.link, self.campaign)

    @patch("r2.lib.promote.g.events.campaign_payment_refund_event")
    @patch("r2.lib.authorize.refund_transaction")
    @patch('r2.models.PromotionLog.add')
    @patch('r2.lib.db.queries.unset_underdelivered_campaigns')
    @patch('r2.lib.emailer.refunded_promo')
    @patch("r2.lib.promote.can_refund")
    @patch("r2.lib.promote.get_refund_amount")
    def test_refund_campaign_success(
            self, get_refund_amount, can_refund, emailer_refunded_promo,
            queries_unset, promotion_log_add, refund_transaction,
            campaign_payment_refund_event):
        """Assert return value and that correct calls are made on success."""
        refund_amount = 100.
        get_refund_amount.return_value = refund_amount
        can_refund.return_value = True
        refund_transaction.return_value = (True, "")

        # the refund process attemtps a db lookup. We don't need it for the
        # purpose of the test.
        with patch.object(Account, "_byID"):
            refund_campaign(
                link=self.link,
                campaign=self.campaign,
            )

        self.assertTrue(refund_transaction.called)
        self.assertTrue(promotion_log_add.called)
        queries_unset.assert_called_once_with(self.campaign)
        emailer_refunded_promo.assert_called_once_with(self.link)
        self.assertEqual(self.campaign.refund_amount, refund_amount)
        self.assertTrue(campaign_payment_refund_event.called)

    @patch("r2.lib.promote.get_billable_amount")
    def test_get_refund_amount_with_no_existing_refund(self, get_billable_amount):
        billable_amount = 100
        get_billable_amount.return_value = billable_amount
        self.campaign.refund_amount = 0.
        self.assertEquals(get_refund_amount(self.campaign), billable_amount)

    @patch("r2.lib.promote.get_billable_amount")
    def test_get_refund_amount_with_existing_refund_amount(self, get_billable_amount):
        billable_amount = 100.
        existing_refund = 10.
        get_billable_amount.return_value = billable_amount
        self.campaign.refund_amount = existing_refund
        refund_amount = get_refund_amount(self.campaign)
        self.assertEquals(refund_amount, billable_amount - existing_refund)

    @patch("r2.lib.promote.get_billable_amount")
    def test_get_refund_amount_rounding(self, get_billable_amount):
        """Assert that inputs are correctly rounded up to the nearest penny."""
        billable_amount = 100.
        get_billable_amount.return_value = billable_amount
        self.campaign.refund_amount = 0.0001
        refund_amount = get_refund_amount(self.campaign)
        self.assertEquals(refund_amount, billable_amount)

        # If campaign.refund_amount is just slightly more than a penny,
        # the refund amount should be campaign.total_budget_dollars - 0.01.
        self.campaign.refund_amount = 0.01000001
        refund_amount = get_refund_amount(self.campaign)
        self.assertEquals(refund_amount, billable_amount - 0.01)

        # Even if campaign.refund_amount is just barely short of two pennies,
        # the refund amount should be campaign.total_budget_dollars - 0.01.
        self.campaign.refund_amount = 0.01999999
        refund_amount = get_refund_amount(self.campaign)
        self.assertEquals(refund_amount, billable_amount - 0.01)

    def test_get_spent_amount_returns_zero_for_house(self):
        house_campaign = MagicMock(spec=("is_house",))
        house_campaign.is_house = True

        spent = get_spent_amount(house_campaign)

        self.assertEqual(spent, 0)

    def test_get_spent_amount_uses_adserver_spent_for_auction(self):
        spent_pennies = 1000
        auction_campaign = MagicMock(spec=(
            "adserver_spent_pennies",
            "is_house",
            "is_auction",
        ))
        auction_campaign.adserver_spent_pennies = spent_pennies
        auction_campaign.is_house = False
        auction_campaign.is_auction = True

        spent = get_spent_amount(auction_campaign)

        self.assertEqual(spent, spent_pennies / 100.)

    @patch("r2.lib.promote.get_billable_impressions")
    def test_get_spent_amount_fixed_cpm(self, get_billable_impressions):
        """`get_spent_amount`: fixed cpm campaigns should bill the bid amount
                for every 1k impressions
        """

        get_billable_impressions.return_value = 2000
        fixed_cpm_campaign = MagicMock(spec=(
            "is_house",
            "is_auction",
            "bid_dollars",
        ))
        fixed_cpm_campaign.is_house = False
        fixed_cpm_campaign.is_auction = False
        fixed_cpm_campaign.bid_dollars = 10.

        spent = get_spent_amount(fixed_cpm_campaign)
        self.assertTrue(spent, 20.)

    @patch("r2.lib.promote.is_pre_cpm")
    def test_get_spent_amount_pre_cpm(self, is_pre_cpm):
        """`get_spent_amount`: Fixed price campaigns should use their budget"""

        budget = 100.
        is_pre_cpm.return_value = True
        pre_cpm_campaign = MagicMock(spec=(
            "is_house",
            "is_auction",
            "total_budget_dollars",
        ))
        pre_cpm_campaign.is_house = False
        pre_cpm_campaign.is_auction = False
        pre_cpm_campaign.total_budget_dollars = budget

        spent = get_spent_amount(pre_cpm_campaign)
        self.assertTrue(spent, budget)

    @patch("r2.lib.promote.get_spent_amount")
    def test_get_billable_amount(
            self, get_spent_amount):
        spent = 90.
        get_spent_amount.return_value = spent
        campaign = MagicMock(spec=("total_budget_dollars"))
        campaign.total_budget_dollars = 100.

        self.assertTrue(get_spent_amount(campaign), spent)

    @patch("r2.lib.promote.get_spent_amount")
    def test_get_billable_amount_should_not_exceed_budget(
            self, get_spent_amount):
        get_spent_amount.return_value = 1000.
        campaign = MagicMock(spec=("total_budget_dollars"))
        campaign.total_budget_dollars = 100.

        spent = get_spent_amount(campaign)
        self.assertTrue(spent, campaign.total_budget_dollars)

    def test_is_pre_cpm(self):
        """Tests all cases of `is_pre_cpm`"""

        # True
        campaign_is_pre = MagicMock(spec=("is_pre_cpm"))
        campaign_is_pre.is_pre_cpm = True
        self.assertTrue(is_pre_cpm(campaign_is_pre))

        # False
        campaign_is_not_pre = MagicMock(spec=("is_pre_cpm"))
        campaign_is_not_pre.is_pre_cpm = False
        self.assertFalse(is_pre_cpm(campaign_is_not_pre))

        # Undefined
        campaign = object()
        self.assertFalse(is_pre_cpm(campaign))


class TestGetUtcOffset(RedditTestCase):
    def test_est(self):
        self.assertEquals(-5, get_utc_offset(datetime.date(2016,3,1), "US/Eastern"))

    def test_est_dst(self):
        self.assertEquals(-4, get_utc_offset(datetime.date(2016,4,1), "US/Eastern"))


class TestFreebies(RedditTestCase):
    def setUp(self):
        self.link = Mock()
        self.user = Mock()

        self.transaction_id = MagicMock()

        # Functions that should run unconditionally
        self.auth_campaign = self.autopatch(promote, 'auth_campaign',
            return_value=(self.transaction_id, Mock()))
        self.campaign_freebie_event = self.autopatch(g.events,
            'campaign_freebie_event')

        # Functions that should run conditionally
        self.promote_link = self.autopatch(promote, 'promote_link')
        self.charge_campaign = self.autopatch(promote, 'charge_campaign')
        self.all_live_promo_srnames = self.autopatch(promote,
            'all_live_promo_srnames')

    def test_current_campaign_start_date(self):
        """
        When the campaign being freebied has a start_date that is right now,
        assert that `auth_campaign` and `campaign_freebie_event are called;
        also assert that the charge and link update functions are not run.
        """
        campaign = MagicMock(start_date=datetime.datetime.now(pytz.utc))

        free_campaign(self.link, campaign, self.user)

        self.auth_campaign.assert_called_once_with(
            self.link,
            campaign,
            self.user,
            freebie=True
        )

        self.campaign_freebie_event.assert_called_once_with(
            link=self.link,
            campaign=campaign,
            amount_pennies=campaign.total_budget_pennies,
            transaction_id=self.transaction_id,
        )

        # Assert that none of these are called because this will take place
        # when make_daily_promotions run
        self.assertEqual(self.all_live_promo_srnames.call_count, 0)
        self.assertEqual(self.promote_link.call_count, 0)
        self.assertEqual(self.charge_campaign.call_count, 0)

    def test_past_campaign_start_date(self):
        """
        When the campaign being freebied has a start_date that is in the past,
        assert that the campaign charged and link update functions are run.
        """
        current_date = datetime.datetime.now(pytz.utc)
        past_date = current_date - datetime.timedelta(days=1)
        campaign = MagicMock(start_date=past_date)

        free_campaign(self.link, campaign, self.user)

        # Assert these are called becase the link needs to be updated
        self.charge_campaign.assert_called_once_with(self.link, campaign,
            freebie=True)
        self.promote_link.assert_called_once_with(self.link, campaign)
        self.all_live_promo_srnames.called_once_with(_update=True)


class TestGetUnspentBudget(unittest.TestCase):
    @patch("r2.lib.promote.get_spent_amount")
    def test_unspent_budget(
        self,
        get_spent_amount,
    ):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.total_budget_dollars = 500
        get_spent_amount.return_value = 100

        self.assertEqual(get_unspent_budget(campaign), 400)

    @patch("r2.lib.promote.get_spent_amount")
    def test_unspent_budget_cannot_be_negative(
        self,
        get_spent_amount,
    ):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.total_budget_dollars = 500
        get_spent_amount.return_value = 600

        self.assertEqual(get_unspent_budget(campaign), 0)


class TestIsUnderdelivered(unittest.TestCase):
    @patch("r2.lib.promote.get_unspent_budget")
    def test_is_underdelivered_is_true_if_unspent_budget_remains(
        self,
        get_unspent_budget,
    ):
        campaign = MagicMock(spec=PromoCampaign)
        get_unspent_budget.return_value = 1

        self.assertTrue(is_underdelivered(campaign))

    @patch("r2.lib.promote.get_unspent_budget")
    def test_is_underdelivered_is_false_if_no_budget_remains(
        self,
        get_unspent_budget,
    ):
        campaign = MagicMock(spec=PromoCampaign)
        get_unspent_budget.return_value = 0

        self.assertFalse(is_underdelivered(campaign))


@patch("r2.lib.promote.emailer.auto_extend_promo")
@patch("r2.lib.promote.edit_campaign")
@patch("r2.lib.promote.g.events.extend_campaign_event")
@patch("r2.lib.promote.PromotionLog.add")
class TestExtendCampaign(unittest.TestCase):
    def setUp(self):
        self.link = MagicMock(spec=Link)
        self.campaign = PromoCampaign(
            end_date=datetime.datetime.now(),
        )

    def test_user_is_only_emailed_on_first_extension(
        self,
        PromotionLog_add,
        extend_campaign_event,
        edit_campaign,
        auto_extend_promo,
    ):
        default_extensions = PromoCampaign._defaults["extensions_remaining"]
        self.campaign.extensions_remaining = default_extensions
        extend_campaign(self.link, self.campaign)

        self.assertEqual(auto_extend_promo.call_count, 1)

        self.campaign.extensions_remaining = default_extensions - 1
        extend_campaign(self.link, self.campaign)

        self.assertEqual(auto_extend_promo.call_count, 1)

    def test_campaign_can_be_extended_if_there_are_extensions_remaining(
        self,
        PromotionLog_add,
        extend_campaign_event,
        edit_campaign,
        auto_extend_promo,
    ):
        self.campaign.extensions_remaining = 0

        with self.assertRaises(ValueError):
            extend_campaign(self.link, self.campaign)

    def test_campaign_is_extended_1_day_at_a_time(
        self,
        PromotionLog_add,
        extend_campaign_event,
        edit_campaign,
        auto_extend_promo,
    ):
        end_after = self.campaign.end_date + datetime.timedelta(days=1)
        extend_campaign(self.link, self.campaign)

        edit_campaign.assert_called_once_with(
            self.link, self.campaign,
            end_date=end_after,
            extensions_remaining=29,
            send_event=False,
        )

    def test_sends_an_event(
        self,
        PromotionLog_add,
        extend_campaign_event,
        edit_campaign,
        auto_extend_promo,
    ):
        extend_campaign(self.link, self.campaign)

        self.assertTrue(extend_campaign_event.called)

    def test_writes_to_promotion_log(
        self,
        PromotionLog_add,
        extend_campaign_event,
        edit_campaign,
        auto_extend_promo,
    ):
        extend_campaign(self.link, self.campaign)

        self.assertTrue(PromotionLog_add.called)


@patch("r2.lib.promote.is_underdelivered")
class TestCanExtend(unittest.TestCase):
    def test_can_extend_is_false_if_auto_extend_is_off(self, is_underdelivered):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.auto_extend = False
        campaign.extensions_remaining = 1
        campaign.is_terminated = False
        is_underdelivered.return_value = False
        self.assertFalse(can_extend(campaign))

    def test_can_extend_is_false_if_no_extensions_remain(self, is_underdelivered):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.auto_extend = True
        campaign.extensions_remaining = 0
        campaign.is_terminated = False
        is_underdelivered.return_value = False
        self.assertFalse(can_extend(campaign))

    def test_can_extend_is_false_if_not_underdelivered(self, is_underdelivered):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.auto_extend = True
        campaign.extensions_remaining = 1
        campaign.is_terminated = False
        is_underdelivered.return_value = False
        self.assertFalse(can_extend(campaign))

    def test_can_extend_is_false_if_the_campaign_was_terminated(self, is_underdelivered):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.auto_extend = True
        campaign.extensions_remaining = 1
        campaign.is_terminated = True
        is_underdelivered.return_value = False
        self.assertFalse(can_extend(campaign))

    def test_can_extend_is_true(self, is_underdelivered):
        campaign = MagicMock(spec=PromoCampaign)
        campaign.auto_extend = True
        campaign.extensions_remaining = 1
        campaign.is_terminated = False
        is_underdelivered.return_value = True
        self.assertTrue(can_extend(campaign))


@patch("r2.lib.promote.charge_pending")
@patch("r2.lib.promote.all_live_promo_srnames")
@patch("r2.lib.promote._mark_promos_updated")
@patch("r2.lib.promote.finalize_completed_campaigns")
@patch("r2.lib.promote.hooks.get_hook")
@patch("r2.lib.promote.get_scheduled_promos")
@patch("r2.lib.promote.promote_link")
@patch("r2.lib.promote.Link._query")
@patch("r2.lib.promote.PromoCampaign._query")
@patch("r2.lib.promote.can_extend")
@patch("r2.lib.promote.extend_campaign")
@patch("r2.lib.promote.update_promote_status")
@patch("r2.lib.promote.emailer.finished_promo")
class TestMakeDailyPromotions(unittest.TestCase):
    def setUp(self):
        self.link_1 = MagicMock(spec=Link)
        self.link_1._id = 1
        self.link_2 = MagicMock(spec=Link)
        self.link_2._id = 2
        self.link_3 = MagicMock(spec=Link)
        self.link_3._id = 3
        self.link_4 = MagicMock(spec=Link)
        self.link_4._id = 4
        self.link_5 = MagicMock(spec=Link)
        self.link_5._id = 5

        self.campaign_1 = MagicMock(spec=PromoCampaign)
        self.campaign_1._id = 1
        self.campaign_1.link_id = 1
        self.campaign_2 = MagicMock(spec=PromoCampaign)
        self.campaign_2._id = 2
        self.campaign_2.link_id = 2
        self.campaign_3 = MagicMock(spec=PromoCampaign)
        self.campaign_3._id = 3
        self.campaign_3.link_id = 3
        self.campaign_4 = MagicMock(spec=PromoCampaign)
        self.campaign_4._id = 4
        self.campaign_4.link_id = 4
        self.campaign_5 = MagicMock(spec=PromoCampaign)
        self.campaign_5._id = 5
        self.campaign_5.link_id = 5

    def test_scheduled_campaigns_are_promoted(
        self,
        finished_promo,
        update_promote_status,
        extend_campaign,
        can_extend,
        PromoCampaign_query,
        Link_query,
        promote_link,
        get_scheduled_promos,
        get_hook,
        finalize_completed_campaigns,
        _mark_promos_updated,
        all_live_promo_srnames,
        charge_pending,
    ):
        get_scheduled_promos.return_value = [
            (self.link_1, self.campaign_1),
            (self.link_2, self.campaign_2),
            (self.link_3, self.campaign_3),
        ]

        make_daily_promotions()

        self.assertEqual(promote_link.call_count, 3)

    def test_unscheduled_campaigns_are_marked_finished(
        self,
        finished_promo,
        update_promote_status,
        extend_campaign,
        can_extend,
        PromoCampaign_query,
        Link_query,
        promote_link,
        get_scheduled_promos,
        get_hook,
        finalize_completed_campaigns,
        _mark_promos_updated,
        all_live_promo_srnames,
        charge_pending,
    ):
        scheduled = [
            (self.link_1, self.campaign_1),
            (self.link_2, self.campaign_2),
            (self.link_3, self.campaign_3),
        ]
        live = [t[0] for t in scheduled] + [
            self.link_4,
            self.link_5,
        ]

        get_scheduled_promos.return_value = scheduled
        Link_query.return_value = live

        make_daily_promotions()

        self.assertEqual(promote_link.call_count, 3)
        self.assertEqual(update_promote_status.call_count, 2)

    def test_underdelivered_campaigns_that_can_be_are_extended(
        self,
        finished_promo,
        update_promote_status,
        extend_campaign,
        can_extend,
        PromoCampaign_query,
        Link_query,
        promote_link,
        get_scheduled_promos,
        get_hook,
        finalize_completed_campaigns,
        _mark_promos_updated,
        all_live_promo_srnames,
        charge_pending,
    ):
        scheduled = [
            (self.link_1, self.campaign_1),
            (self.link_2, self.campaign_2),
            (self.link_3, self.campaign_3),
        ]

        live_links = [t[0] for t in scheduled] + [
            self.link_4,
            self.link_5,
        ]

        live_campaigns = [
            self.campaign_1,
            self.campaign_2,
            self.campaign_3,
            self.campaign_4,
            self.campaign_5,
        ]

        get_scheduled_promos.return_value = scheduled
        Link_query.return_value = live_links
        PromoCampaign_query.return_value = live_campaigns
        can_extend.return_value = True

        make_daily_promotions()

        self.assertEqual(promote_link.call_count, 3)
        self.assertEqual(update_promote_status.call_count, 0)
        self.assertEqual(extend_campaign.call_count, 2)

    def test_underdelivered_campaigns_cannot_be_extended_are_marked_finished(
        self,
        finished_promo,
        update_promote_status,
        extend_campaign,
        can_extend,
        PromoCampaign_query,
        Link_query,
        promote_link,
        get_scheduled_promos,
        get_hook,
        finalize_completed_campaigns,
        _mark_promos_updated,
        all_live_promo_srnames,
        charge_pending,
    ):
        scheduled = [
            (self.link_1, self.campaign_1),
            (self.link_2, self.campaign_2),
            (self.link_3, self.campaign_3),
        ]

        live_links = [t[0] for t in scheduled] + [
            self.link_4,
            self.link_5,
        ]

        live_campaigns = [
            self.campaign_1,
            self.campaign_2,
            self.campaign_3,
            self.campaign_4,
            self.campaign_5,
        ]

        get_scheduled_promos.return_value = scheduled
        Link_query.return_value = live_links
        PromoCampaign_query.return_value = live_campaigns
        can_extend.return_value = False

        make_daily_promotions()

        self.assertEqual(promote_link.call_count, 3)
        self.assertEqual(update_promote_status.call_count, 2)
        self.assertEqual(extend_campaign.call_count, 0)
