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


from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta
import re

from sqlalchemy import func

from r2.lib.memoize import memoize
from r2.lib.utils import to_date, tup
from r2.models import (
    Bid,
    FakeSubreddit,
    LocalizedDefaultSubreddits,
    Location,
    NO_TRANSACTION,
    PromoCampaign,
    PromotionWeights,
    traffic,
)
from r2.models.promo_metrics import LocationPromoMetrics, PromoMetrics
from r2.models.subreddit import DefaultSR

NDAYS_TO_QUERY = 14  # how much history to use in the estimate
MIN_DAILY_CASS_KEY = 'min_daily_pageviews.GET_listing'
PAGEVIEWS_REGEXP = re.compile('(.*)-GET_listing')
INVENTORY_FACTOR = 1.00
DEFAULT_INVENTORY_FACTOR = 5.00


def update_prediction_data():
    """Fetch prediction data and write it to cassandra."""
    min_daily_by_sr = _min_daily_pageviews_by_sr(NDAYS_TO_QUERY)

    # combine front page values (sometimes frontpage gets '' for its name)
    if '' in min_daily_by_sr:
        fp = DefaultSR.name.lower()
        min_daily_by_sr[fp] = min_daily_by_sr.get(fp, 0) + min_daily_by_sr['']
        del min_daily_by_sr['']

    filtered = {sr_name: num for sr_name, num in min_daily_by_sr.iteritems()
                if num > 100}
    PromoMetrics.set(MIN_DAILY_CASS_KEY, filtered)


def _min_daily_pageviews_by_sr(ndays=NDAYS_TO_QUERY, end_date=None):
    """Return dict mapping sr_name to min_pageviews over the last ndays."""
    if not end_date:
        last_modified = traffic.get_traffic_last_modified()
        end_date = last_modified - timedelta(days=1)
    stop = end_date
    start = stop - timedelta(ndays)
    time_points = traffic.get_time_points('day', start, stop)
    cls = traffic.PageviewsBySubredditAndPath
    q = (traffic.Session.query(cls.srpath, func.min(cls.pageview_count))
                               .filter(cls.interval == 'day')
                               .filter(cls.date.in_(time_points))
                               .filter(cls.srpath.like('%-GET_listing'))
                               .group_by(cls.srpath))

    # row looks like: ('lightpainting-GET_listing', 16)
    retval = {}
    for row in q:
        m = PAGEVIEWS_REGEXP.match(row[0])
        if m:
            retval[m.group(1)] = row[1]
    return retval


def get_date_range(start, end):
    start, end = map(to_date, [start, end])
    dates = [start + timedelta(i) for i in xrange((end - start).days)]
    return dates


def get_campaigns_by_date(srs, start, end, ignore=None):
    srs = tup(srs)
    sr_names = [sr.name for sr in srs]
    q = PromotionWeights.get_campaigns(start, end=end, sr_names=sr_names)
    campaign_ids = {pw.promo_idx for pw in q}
    if ignore:
        campaign_ids.discard(ignore._id)
    campaigns = PromoCampaign._byID(campaign_ids, data=True, return_dict=False)

    # filter out deleted campaigns that didn't have their PromotionWeights
    # deleted
    campaigns = filter(lambda camp: not camp._deleted, campaigns)

    transaction_ids = {camp.trans_id for camp in campaigns
                                     if camp.trans_id != NO_TRANSACTION}

    if transaction_ids:
        transactions = Bid.query().filter(Bid.transaction.in_(transaction_ids))
        transaction_by_id = {bid.transaction: bid for bid in transactions}
    else:
        transaction_by_id = {}

    dates = set(get_date_range(start, end))
    ret = {date: set() for date in dates}
    for camp in campaigns:
        if camp.trans_id == NO_TRANSACTION:
            continue

        if camp.impressions <= 0:
            # pre-CPM campaign
            continue

        transaction = transaction_by_id[camp.trans_id]
        if not (transaction.is_auth() or transaction.is_charged()):
            continue

        camp_dates = set(get_date_range(camp.start_date, camp.end_date))
        for date in camp_dates.intersection(dates):
            ret[date].add(camp)
    return ret


def get_sold_pageviews(srs, start, end, ignore=None):
    srs, is_single = tup(srs, ret_is_single=True)
    campaigns_by_date = get_campaigns_by_date(srs, start, end, ignore)

    ret = {sr.name: defaultdict(int) for sr in srs}
    for date, campaigns in campaigns_by_date.iteritems():
        for camp in campaigns:
            daily_impressions = camp.impressions / camp.ndays
            for sr_name in camp.target.subreddit_names:
                # NOTE: campaign should only have one sr in target, but we're
                # not enforcing that here
                ret[sr_name][date] += daily_impressions

    if is_single:
        return ret[srs[0].name]
    else:
        return ret


def get_predicted_pageviews(srs):
    srs, is_single = tup(srs, ret_is_single=True)
    sr_names = [sr.name for sr in srs]

    # default subreddits require a different inventory factor
    default_srids = LocalizedDefaultSubreddits.get_global_defaults()

    # prediction does not vary by date
    daily_inventory = PromoMetrics.get(MIN_DAILY_CASS_KEY, sr_names=sr_names)
    ret = {}
    for sr in srs:
        if not isinstance(sr, FakeSubreddit) and sr._id in default_srids:
            factor = DEFAULT_INVENTORY_FACTOR
        else:
            factor = INVENTORY_FACTOR
        ret[sr.name] = int(daily_inventory.get(sr.name, 0) * factor)

    if is_single:
        return ret[srs[0].name]
    else:
        return ret


def get_predicted_geotargeted(sr, location):
    """
    Predicted geotargeted impressions are estimated as:

    geotargeted impressions = (predicted untargeted impressions) *
                                 (fp impressions for location / fp impressions)

    """

    predicted_pageviews = get_predicted_pageviews(sr)
    no_location = Location(None)
    r = LocationPromoMetrics.get(DefaultSR, [no_location, location])
    ratio = r[(DefaultSR, location)] / float(r[(DefaultSR, no_location)])
    return int(predicted_pageviews * ratio)


def get_available_pageviews_geotargeted(sr, location, start, end, datestr=False, 
                                        ignore=None):
    """
    Return the available pageviews by date for the subreddit and location.

    Available pageviews depends on all equal and higher level targets:
    A target is: subreddit > country > metro

    e.g. if a campaign is targeting /r/funny in USA/Boston we need to check that
    there's enough inventory in:
    * /r/funny (all campaigns targeting /r/funny regardless of geotargeting)
    * /r/funny + USA (all campaigns targeting /r/funny and USA with or without
      metro level targeting)
    * /r/funny + USA + Boston (all campaigns targeting /r/funny and USA and
      Boston)
    The available inventory is the smallest of these values.

    """

    predicted_by_location = {
        None: get_predicted_pageviews(sr),
        location: get_predicted_geotargeted(sr, location),
    }

    if location.metro:
        country_location = Location(country=location.country)
        country_prediction = get_predicted_geotargeted(sr, country_location)
        predicted_by_location[country_location] = country_prediction
    locations = predicted_by_location.keys()

    datekey = lambda dt: dt.strftime('%m/%d/%Y') if datestr else dt

    ret = {}
    campaigns_by_date = get_campaigns_by_date(sr, start, end, ignore)
    for date, campaigns in campaigns_by_date.iteritems():

        # calculate sold impressions for each location
        sold_by_location = dict.fromkeys(locations, 0)
        for camp in campaigns:
            daily_impressions = camp.impressions / camp.ndays
            for location in locations:
                if not location or location.contains(camp.location):
                    sold_by_location[location] += daily_impressions

        # calculate available impressions for each location
        available_by_location = dict.fromkeys(locations, 0)
        for location, predicted in predicted_by_location.iteritems():
            sold = sold_by_location[location]
            available_by_location[location] = predicted - sold

        ret[datekey(date)] = max(0, min(available_by_location.values()))
    return ret


def get_available_pageviews(srs, start, end, datestr=False, ignore=None):
    srs, is_single = tup(srs, ret_is_single=True)
    pageviews_by_sr_by_date = get_predicted_pageviews(srs, start, end)
    sold_by_sr_by_date = get_sold_pageviews(srs, start, end, ignore)

    datekey = lambda dt: dt.strftime('%m/%d/%Y') if datestr else dt

    ret = {}
    dates = get_date_range(start, end)
    for sr in srs:
        sold_by_date = sold_by_sr_by_date[sr.name]
        pageviews_by_date = pageviews_by_sr_by_date[sr.name]
        ret[sr.name] = {}
        for date in dates:
            sold = sold_by_date[date]
            pageviews = pageviews_by_date[date]
            ret[sr.name][datekey(date)] = max(0, pageviews - sold)

    if is_single:
        return ret[srs[0].name]
    else:
        return ret


def get_oversold(srs, start, end, daily_request, ignore=None, location=None):
    assert len(srs) == 1, "can't check inventory for multiple subreddits"
    sr = srs[0]

    if location:
        available_by_date = get_available_pageviews_geotargeted(sr, location,
                                start, end, datestr=True, ignore=ignore)
    else:
        available_by_date = get_available_pageviews(sr, start, end,
                                                    datestr=True, ignore=ignore)
    oversold = {}
    for datestr, available in available_by_date.iteritems():
        if available < daily_request:
            oversold[datestr] = available
    return oversold
