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
from datetime import datetime, timedelta

from babel.dates import format_date
from babel.numbers import format_number
import hashlib
import hmac
import json
import urllib
import mimetypes
import os

from pylons import request
from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons.i18n import _, N_

from r2.config import feature
from r2.controllers.api import ApiController
from r2.controllers.listingcontroller import ListingController
from r2.controllers.reddit_base import RedditController
from r2.lib import (
    hooks,
    inventory,
    media,
    promote,
    s3_helpers,
)
from r2.lib.authorize.interaction import (
    get_or_create_customer_profile,
    add_or_update_payment_method,
)
from r2.lib.authorize.api import AuthorizeNetException, PROFILE_LIMIT
from r2.lib.base import abort
from r2.lib.db import queries
from r2.lib.errors import errors
from r2.lib.filters import (
    jssafe,
    scriptsafe_dumps,
    websafe,
)
from r2.lib.template_helpers import (
    add_sr,
    format_html,
)
from r2.lib.memoize import memoize
from r2.lib.menus import NamedButton, NavButton, NavMenu, QueryButton
from r2.lib.pages import (
    LinkInfoPage,
    PaymentForm,
    PromoteInventory,
    PromotePage,
    PromoteLinkEdit,
    PromoteLinkNew,
    PromotePost,
    PromoteReport,
    Reddit,
    RefundPage,
    RenderableCampaign,
    Roadblocks,
    SponsorLookupUser,
)
from r2.lib.pages.things import default_thing_wrapper, wrap_links
from r2.lib.system_messages import user_added_messages
from r2.lib.utils import (
    constant_time_compare,
    get_thing_based_hmac,
    is_subdomain,
    exclude_from_logging,
    to_date,
    to36,
    UrlParser,
)
from r2.lib.validator import (
    json_validate,
    nop,
    noresponse,
    VAccountByName,
    ValidAddress,
    validate,
    validatedMultipartForm,
    validatedForm,
    ValidCard,
    ValidEmail,
    VBoolean,
    VByName,
    VCollection,
    VDate,
    VExistingUname,
    VFloat,
    VFrequencyCap,
    VImageType,
    VInt,
    VLength,
    VLink,
    VList,
    VLocation,
    VModhash,
    VOneOf,
    VOSVersion,
    VPrintable,
    VPriority,
    VPromoCampaign,
    VPromoTarget,
    VRatelimit,
    VMarkdownLength,
    VShamedDomain,
    VSponsor,
    VSponsorAdmin,
    VSponsorAdminOrAdminSecret,
    VVerifiedSponsor,
    VSubmitSR,
    VSRByNames,
    VTitle,
    VUploadLength,
    VUrl,
)
from r2.models import (
    Account,
    AccountsByCanonicalEmail,
    calc_impressions,
    Collection,
    Frontpage,
    Link,
    Message,
    NotFound,
    PromoCampaign,
    PromotionLog,
    PromotionPrices,
    PromotionWeights,
    PromotedLinkRoadblock,
    PROMOTE_STATUS,
    Subreddit,
    Target,
)
from r2.models.promo import PROMOTE_COST_BASIS, PROMOTE_PRIORITIES

IOS_DEVICES = ('iPhone', 'iPad', 'iPod',)
ANDROID_DEVICES = ('phone', 'tablet',)

ADZERK_URL_MAX_LENGTH = 499

ALLOWED_IMAGE_TYPES = set(["image/jpg", "image/jpeg", "image/png"])


def campaign_has_oversold_error(form, campaign):
    if campaign.priority.inventory_override:
        return

    return has_oversold_error(
        form,
        campaign,
        start=campaign.start_date,
        end=campaign.end_date,
        total_budget_pennies=campaign.total_budget_pennies,
        cpm=campaign.bid_pennies,
        target=campaign.target,
        location=campaign.location,
    )


def has_oversold_error(form, campaign, start, end, total_budget_pennies, cpm,
        target, location):
    ndays = (to_date(end) - to_date(start)).days
    total_request = calc_impressions(total_budget_pennies, cpm)
    daily_request = int(total_request / ndays)
    oversold = inventory.get_oversold(
        target, start, end, daily_request, ignore=campaign, location=location)

    if oversold:
        min_daily = min(oversold.values())
        available = min_daily * ndays
        msg_params = {
            'available': format_number(available, locale=c.locale),
            'target': target.pretty_name,
            'start': start.strftime('%m/%d/%Y'),
            'end': end.strftime('%m/%d/%Y'),
        }
        c.errors.add(errors.OVERSOLD_DETAIL, field='total_budget_dollars',
                     msg_params=msg_params)
        form.has_errors('total_budget_dollars', errors.OVERSOLD_DETAIL)
        return True


def _key_to_dict(key, data=False):
    timer = g.stats.get_timer("providers.s3.get_ads_key_meta.with_%s" %
        ("data" if data else "no_data"))
    timer.start()

    url = key.generate_url(expires_in=0, query_auth=False)
    # Generating an S3 url without authentication fails for IAM roles.
    # This removes the bad query params.
    # see: https://github.com/boto/boto/issues/2043
    url = promote.update_query(url, {"x-amz-security-token": None}, unset=True)

    result = {
        "url": url,
        "data": key.get_contents_as_string() if data else None,
        "ext": key.get_metadata("ext"),
    }

    timer.stop()

    return result


def _get_ads_keyspace(thing):
    return "ads/%s/" % thing._fullname


def _get_ads_images(thing, data=False, **kwargs):
    images = {}

    timer = g.stats.get_timer("providers.s3.get_ads_image_keys")
    timer.start()

    keys = s3_helpers.get_keys(g.s3_client_uploads_bucket, prefix=_get_ads_keyspace(thing), **kwargs)

    timer.stop()

    for key in keys:
        filename = os.path.basename(key.key)
        name, ext = os.path.splitext(filename)

        if name not in ("mobile", "thumbnail"):
            continue

        images[name] = _key_to_dict(key, data=data)

    return images


def _clear_ads_images(thing):
    timer = g.stats.get_timer("providers.s3.delete_ads_image_keys")
    timer.start()

    s3_helpers.delete_keys(g.s3_client_uploads_bucket, prefix=_get_ads_keyspace(thing))

    timer.stop()


class PromoteController(RedditController):
    @validate(VSponsor())
    def GET_new_promo(self):
        ads_images = _get_ads_images(c.user)
        images = {k: v.get("url") for k, v in ads_images.iteritems()}

        return PromotePage(title=_("create sponsored link"),
                           content=PromoteLinkNew(images),
                           extra_js_config={
                            "ads_virtual_page": "new-promo",
                           }).render()

    @validate(VSponsor('link'),
              link=VLink('link'))
    def GET_edit_promo(self, link):
        if not link or link.promoted is None:
            return self.abort404()
        # Only sponsored accounts can manage promoted posts            
        if link.is_promoted_post and not c.user_is_sponsor:
            return self.abort404()            
        rendered = wrap_links(link, skip=False)
        form = PromoteLinkEdit(link, rendered)
        page = PromotePage(title=_("edit sponsored link"), content=form,
                      show_sidebar=False, extension_handling=False)
        return page.render()

    @validate(VSponsorAdmin(),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_refund(self, link, campaign):
        if link._id != campaign.link_id:
            return self.abort404()

        content = RefundPage(link, campaign)
        return Reddit("refund", content=content, show_sidebar=False).render()

    @validate(VVerifiedSponsor("link"),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_pay(self, link, campaign):
        if link._id != campaign.link_id:
            return self.abort404()

        # no need for admins to play in the credit card area
        if c.user_is_loggedin and c.user._id != link.author_id:
            return self.abort404()

        if g.authorizenetapi:
            data = get_or_create_customer_profile(c.user)
            content = PaymentForm(link, campaign,
                                  customer_id=data.customerProfileId,
                                  profiles=data.paymentProfiles,
                                  max_profiles=PROFILE_LIMIT)
        else:
            content = None
        res = LinkInfoPage(link=link,
                            content=content,
                            show_sidebar=False,
                            extra_js_config={
                              "ads_virtual_page": "checkout",
                            })
        return res.render()


class SponsorController(PromoteController):
    @validate(VSponsorAdmin())
    def GET_roadblock(self):
        return PromotePage(title=_("manage roadblocks"),
                           content=Roadblocks()).render()

    @validate(VSponsorAdminOrAdminSecret('secret'),
              start=VDate('startdate'),
              end=VDate('enddate'),
              link_text=nop('link_text'),
              owner=VAccountByName('owner'),
              grouping=VOneOf("grouping", ("total", "day"), default="total"))
    def GET_report(self, start, end, grouping, link_text=None, owner=None):
        now = datetime.now(g.tz).replace(hour=0, minute=0, second=0,
                                         microsecond=0)
        if not start or not end:
            start = promote.promo_datetime_now(offset=1).date()
            end = promote.promo_datetime_now(offset=8).date()
            c.errors.remove((errors.BAD_DATE, 'startdate'))
            c.errors.remove((errors.BAD_DATE, 'enddate'))
        end = end or now - timedelta(days=1)
        start = start or end - timedelta(days=7)

        links = []
        bad_links = []
        owner_name = owner.name if owner else ''

        if owner:
            campaign_ids = PromotionWeights.get_campaign_ids(
                start, end, author_id=owner._id)
            campaigns = PromoCampaign._byID(campaign_ids, data=True)
            link_ids = {camp.link_id for camp in campaigns.itervalues()}
            links.extend(Link._byID(link_ids, data=True, return_dict=False))

        if link_text is not None:
            id36s = link_text.replace(',', ' ').split()
            try:
                links_from_text = Link._byID36(id36s, data=True)
            except NotFound:
                links_from_text = {}

            bad_links = [id36 for id36 in id36s if id36 not in links_from_text]
            links.extend(links_from_text.values())

        content = PromoteReport(links, link_text, owner_name, bad_links, start,
                                end, group_by_date=grouping == "day")
        if c.render_style == 'csv':
            return content.as_csv()
        else:
            return PromotePage(title=_("sponsored link report"),
                               content=content).render()

    @validate(
        VSponsorAdmin(),
        start=VDate('startdate'),
        end=VDate('enddate'),
        srs=VSRByNames('sr_names', required=True),
        collection=VCollection('collection_name'),
    )
    def GET_promote_inventory(self, start, end, srs, collection):
        if not start or not end:
            start = promote.promo_datetime_now(offset=1).date()
            end = promote.promo_datetime_now(offset=8).date()
            c.errors.remove((errors.BAD_DATE, 'startdate'))
            c.errors.remove((errors.BAD_DATE, 'enddate'))

        target = Target(Frontpage.name)
        if srs:
            srs = srs.values() if type(srs) is dict else [srs]
            pretty_name = "\n ".join(["/r/%s" % sr.name for sr in srs])
            sr_names = [sr.name for sr in srs]
            target = Target(Collection(pretty_name, sr_names))
        elif collection:
            target = Target(collection)

        content = PromoteInventory(start, end, target)

        if c.render_style == 'csv':
            return content.as_csv()
        else:
            return PromotePage(title=_("sponsored link inventory"),
                               content=content).render()

    @validate(
        VSponsorAdmin(),
        id_user=VByName('name', thing_cls=Account),
        email=ValidEmail("email"),
    )
    def GET_lookup_user(self, id_user, email):
        email_users = AccountsByCanonicalEmail.get_accounts(email)
        content = SponsorLookupUser(
            id_user=id_user, email=email, email_users=email_users)
        return PromotePage(title="look up user", content=content).render()
    
    @validate(
        VSponsorAdmin(),
    )
    def GET_promote_post(self):
        content = PromotePost()
        return PromotePage(title="promote a post", content=content).render()

class PromoteListingController(ListingController):
    where = 'promoted'
    render_cls = PromotePage
    titles = {
        'unapproved_campaigns': N_('unapproved campaigns'),
        'external_promos': N_('externally promoted links'),
        'future_promos': N_('unapproved promoted links'),
        'pending_promos': N_('accepted promoted links'),
        'unpaid_promos': N_('unpaid promoted links'),
        'rejected_promos': N_('rejected promoted links'),
        'live_promos': N_('live promoted links'),
        'edited_live_promos': N_('edited live promoted links'),
        'all': N_('all promoted links'),
    }
    base_path = '/promoted'

    default_filters = [
        NamedButton('all_promos', dest='',
                    use_params=False,
                    aliases=['/sponsor']),
        NamedButton('future_promos',
                    use_params=False),
        NamedButton('unpaid_promos',
                    use_params=False),
        NamedButton('rejected_promos',
                    use_params=False),
        NamedButton('pending_promos',
                    use_params=False),
        NamedButton('live_promos',
                    use_params=False),
        NamedButton('edited_live_promos',
                    use_params=False),
    ]

    def title(self):
        return _(self.titles[self.sort])

    @property
    def title_text(self):
        return _('promoted by you')

    @property
    def menus(self):
        # copy to prevent modifing the class attribute.
        filters = self.default_filters[:]

        if c.user_is_sponsor:
            filters.append(
                NamedButton('external_promos', use_params=False)
            )

        return [NavMenu(filters, base_path=self.base_path, title='show',
                         type='lightdrop')]

    def builder_wrapper(self, thing):
        builder_wrapper = default_thing_wrapper()
        w = builder_wrapper(thing)
        w.hide_after_seen = self.sort == "future_promos"

        return w

    def keep_fn(self):
        def keep(item):
            if self.sort == "future_promos":
                # this sort is used to review links that need to be approved
                # skip links that don't have any paid campaigns
                campaigns = list(PromoCampaign._by_link(item._id))
                if not any(promote.authed_or_not_needed(camp)
                           for camp in campaigns):
                    return False

            if item.promoted and not item._deleted:
                return True
            else:
                return False
        return keep

    def query(self):
        if self.sort == "future_promos":
            return queries.get_unapproved_links(c.user._id)
        elif self.sort == "external_promos":
            return queries.get_external_links(c.user._id)
        elif self.sort == "pending_promos":
            return queries.get_accepted_links(c.user._id)
        elif self.sort == "unpaid_promos":
            return queries.get_unpaid_links(c.user._id)
        elif self.sort == "rejected_promos":
            return queries.get_rejected_links(c.user._id)
        elif self.sort == "live_promos":
            return queries.get_live_links(c.user._id)
        elif self.sort == "edited_live_promos":
            return queries.get_edited_live_links(c.user._id)
        elif self.sort == "all":
            return queries.get_promoted_links(c.user._id)

    @validate(VSponsor())
    def GET_listing(self, sort="all", **env):
        self.sort = sort
        return ListingController.GET_listing(self, **env)


class SponsorListingController(PromoteListingController):
    titles = dict(PromoteListingController.titles.items() + {
        'by_platform': N_('promoted links by platform'),
        'underdelivered': N_('underdelivered promoted links'),
        'reported': N_('reported promoted links'),
        'house': N_('house promoted links'),
        'fraud': N_('fraud suspected promoted links'),
    }.items())
    base_path = '/sponsor/promoted'

    @property
    def title_text(self):
        return _('promos on reddit')

    @property
    def menus(self):
        managed_menu = NavMenu([
            QueryButton("exclude managed", dest=None,
                        query_param='include_managed'),
            QueryButton("include managed", dest="yes",
                        query_param='include_managed'),
        ], base_path=request.path, type='lightdrop')

        if self.sort in {'underdelivered', 'reported', 'house',
                         'fraud', 'by_platform'}:
            menus = []

            if self.sort == 'by_platform':
                platform_menu = NavMenu([
                    QueryButton("desktop", dest="desktop",
                                query_param='platform'),
                    QueryButton("mobile web", dest="mobile_web",
                                query_param='platform'),
                    QueryButton("native mobile", dest="mobile_native",
                                query_param='platform'),
                    QueryButton("all platforms", dest="all",
                                query_param='platform'),
                    ],
                    base_path=request.path,
                    title='platform',
                    default='desktop',
                    type='lightdrop',
                )
                menus.append(platform_menu)
            elif self.sort == 'fraud':
                fraud_menu = NavMenu([
                    QueryButton("exclude unpaid", dest=None,
                                query_param='exclude_unpaid'),
                    QueryButton("include unpaid", dest="no",
                                query_param='exclude_unpaid'),
                ], base_path=request.path, type='lightdrop')
                menus.append(fraud_menu)
            if self.sort in ('house', 'fraud', 'by_platform'):
                menus.append(managed_menu)
        else:
            # copy to prevent modifing the class attribute.
            filters = self.default_filters[:]
            filters.append(
                NamedButton('external_promos', use_params=False)
            )
            filters.append(
                NamedButton('unapproved_campaigns',
                            use_params=False)
            )

            menus = [
                NavMenu(filters,
                    base_path=self.base_path,
                    title='show',
                    type='lightdrop',
                ),
            ]
            menus.append(managed_menu)

        if self.sort == 'live_promos':
            srnames = promote.all_live_promo_srnames()
            buttons = [NavButton('all', '', use_params=True)]
            try:
                srnames.remove(Frontpage.name)
                frontbutton = NavButton('FRONTPAGE', Frontpage.name,
                                        use_params=True,
                                        aliases=['/promoted/live_promos/%s' %
                                                 urllib.quote(Frontpage.name)])
                buttons.append(frontbutton)
            except KeyError:
                pass

            srnames = sorted(srnames, key=lambda name: name.lower())
            buttons.extend(
                NavButton(name, name, use_params=True) for name in srnames)
            base_path = self.base_path + '/live_promos'
            menus.append(NavMenu(buttons, base_path=base_path,
                                 title='subreddit', type='lightdrop'))
        return menus

    @classmethod
    @memoize('live_by_subreddit', time=300)
    def _live_by_subreddit(cls, sr_names):
        promotuples = promote.get_live_promotions(sr_names)
        return [pt.link for pt in promotuples]

    def live_by_subreddit(cls, sr):
        return cls._live_by_subreddit([sr.name])

    @classmethod
    @memoize('house_link_names', time=60)
    def get_house_link_names(cls):
        now = promote.promo_datetime_now()
        campaign_ids = PromotionWeights.get_campaign_ids(now)
        q = PromoCampaign._query(PromoCampaign.c._id.in_(campaign_ids),
                                 PromoCampaign.c.priority_name == 'house',
                                 data=True)
        link_names = {Link._fullname_from_id36(to36(camp.link_id))
                      for camp in q}
        return sorted(link_names, reverse=True)

    def keep_fn(self):
        base_keep_fn = PromoteListingController.keep_fn(self)

        if self.exclude_unpaid:
            exclude = set(queries.get_all_unpaid_links())
        else:
            exclude = set()

        def keep(item):
            if not self.include_managed and item.managed_promo:
                return False

            if self.exclude_unpaid and item._fullname in exclude:
                return False

            return base_keep_fn(item)
        return keep

    def query(self):
        if self.sort == "unapproved_campaigns":
            return queries.get_all_links_with_unapproved_campaigns()
        elif self.sort == "external_promos":
            return queries.get_all_external_links()
        elif self.sort == "future_promos":
            return queries.get_all_unapproved_links()
        elif self.sort == "pending_promos":
            return queries.get_all_accepted_links()
        elif self.sort == "unpaid_promos":
            return queries.get_all_unpaid_links()
        elif self.sort == "rejected_promos":
            return queries.get_all_rejected_links()
        elif self.sort == "live_promos" and self.sr:
            return self.live_by_subreddit(self.sr)
        elif self.sort == 'live_promos':
            return queries.get_all_live_links()
        elif self.sort == 'edited_live_promos':
            return queries.get_all_edited_live_links()
        elif self.sort == 'underdelivered':
            q = queries.get_underdelivered_campaigns()
            campaigns = PromoCampaign._by_fullname(list(q), data=True,
                                                   return_dict=False)
            link_ids = {camp.link_id for camp in campaigns}
            return [Link._fullname_from_id36(to36(id)) for id in link_ids]
        elif self.sort == 'reported':
            return queries.get_reported_links(Subreddit.get_promote_srid())
        elif self.sort == 'fraud':
            return queries.get_payment_flagged_links()
        elif self.sort == 'house':
            return self.get_house_link_names()
        elif self.sort == 'all':
            return queries.get_all_promoted_links()
        elif self.sort == 'by_platform':
            return queries.get_platform_links(self.platform)

    def listing(self):
        """For sponsors, update wrapped links to include their campaigns."""
        pane = super(self.__class__, self).listing()

        if c.user_is_sponsor:
            link_ids = {item._id for item in pane.things}
            campaigns = PromoCampaign._by_link(link_ids)
            campaigns_by_link = defaultdict(list)
            for camp in campaigns:
                campaigns_by_link[camp.link_id].append(camp)

            for item in pane.things:
                campaigns = campaigns_by_link[item._id]
                item.campaigns = RenderableCampaign.from_campaigns(
                    item, campaigns, full_details=False, hide_after_seen=True)
                item.cachable = False
                item.show_campaign_summary = True
        return pane

    @validate(
        VSponsorAdmin(),
        srname=nop('sr'),
        platform=VOneOf("platform", (
            "desktop",
            "mobile_web",
            "mobile_native",
            "all",
        ), default="desktop"),
        include_managed=VBoolean("include_managed"),
        exclude_unpaid=VBoolean("exclude_unpaid"),
    )
    def GET_listing(self, srname=None, platform="desktop", include_managed=False,
                    exclude_unpaid=None, sort="all", **kw):
        self.sort = sort
        self.sr = None
        self.platform = platform
        self.include_managed = include_managed

        if "exclude_unpaid" not in request.GET:
            self.exclude_unpaid = self.sort == "fraud"
        else:
            self.exclude_unpaid = exclude_unpaid

        if srname:
            try:
                self.sr = Subreddit._by_name(srname)
            except NotFound:
                pass
        return ListingController.GET_listing(self, **kw)


def allowed_location_and_targets(location, targets):
    if c.user_is_sponsor or feature.is_enabled('ads_auction'):
        return True

    # regular users can only use locations when targeting frontpage
    is_location = location and location.country

    if isinstance(targets, list):
        is_frontpage = reduce(lambda x, y: x or y, [t.is_frontpage for t in targets])
    elif isinstance(targets, Target):
        is_frontpage = target.is_frontpage
    else:
        is_frontpage = False

    return not is_location or is_frontpage


class PromoteApiController(ApiController):
    @json_validate(
        srs=VSRByNames('sr', required=True),
        collection=VCollection('collection'),
        location=VLocation(),
        start=VDate('startdate'),
        end=VDate('enddate'),
        platform=VOneOf('platform', [
            'mobile_web',
            'mobile_native',
            'desktop',
            'all',
        ], default='all'))
    def GET_check_inventory(self, responder, srs, collection, location, start,
                            end, platform):
        if responder.has_errors("srs", errors.SUBREDDIT_NOEXIST):
            return {'error': errors.SUBREDDIT_NOEXIST}

        if responder.has_errors("srs", errors.SUBREDDIT_NOTALLOWED):
            return {'error': errors.SUBREDDIT_NOTALLOWED}

        if responder.has_errors("srs", errors.SUBREDDIT_DISABLED_ADS):
            return {'error': errors.SUBREDDIT_DISABLED_ADS}

        if collection:
            targets = [Target(collection)]
            srs = None
        else:
            srs = srs or Frontpage
            srs = srs.values() if type(srs) is dict else [srs]
            targets = [Target(s.name) for s in srs]

        if not allowed_location_and_targets(location, targets):
            return abort(403, 'forbidden')

        available = inventory.get_available_pageviews(
                        targets, start, end, location=location, platform=platform,
                        datestr=True)
        return {'inventory': available}

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink("link_id36"),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_freebie(self, form, jquery, link, campaign):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        if campaign_has_oversold_error(form, campaign):
            form.set_text(".freebie", _("target oversold, can't freebie"))
            return

        if promote.is_promo(link) and campaign:
            promote.free_campaign(link, campaign, c.user)
            form.redirect(promote.promo_edit_url(link))

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VByName("link"),
                   note=nop("note"))
    def POST_promote_note(self, form, jquery, link, note):
        if promote.is_promo(link):
            text = PromotionLog.add(link, note)
            form.find(".notes").children(":last").after(
                format_html("<p>%s</p>", text))

    @validatedForm(
        VSponsorAdmin(),
        VModhash(),
        thing = VByName("thing_id"),
        is_fraud=VBoolean("fraud"),
    )
    def POST_review_fraud(self, form, jquery, thing, is_fraud):
        if not thing or not getattr(thing, "promoted", False):
            return

        promote.review_fraud(thing, is_fraud)

        button = jquery(".id-%s .fraud-button" % thing._fullname)
        button.text(_("fraud" if is_fraud else "not fraud"))
        form.parents('.link').fadeOut()

    @noresponse(VSponsorAdmin(),
                VModhash(),
                thing=VByName('id'),
                quality=VOneOf('quality', options=(None, 'low', 'high')))
    def POST_promote(self, thing, quality):
        if promote.is_promo(thing):
            promote.accept_promotion(thing, quality)
            if isinstance(thing, Link):
                promote.approve_all_campaigns(thing)


    @noresponse(VSponsorAdmin(),
                VModhash(),
                thing=VByName('id'),
                reason=nop("reason"))
    def POST_unpromote(self, thing, reason):
        if promote.is_promo(thing):
            promote.reject_promotion(thing, reason=reason)
            if isinstance(thing, Link):
                promote.unapprove_all_campaigns(thing)

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link'),
                   campaign=VPromoCampaign('campaign'))
    def POST_refund_campaign(self, form, jquery, link, campaign):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        try:
            promote.refund_campaign(link, campaign, issued_by=c.user)
            form.set_text('.status', _("refund succeeded"))
        except promote.InapplicableRefundException:
            form.set_text('.status', _("refund not needed"))
        except promote.RefundProviderException as e:
            form.set_text(".status", e.message)

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        VRatelimit(rate_user=True,
                   rate_ip=True,
                   prefix='create_promo_'),
        VShamedDomain('url'),
        username=VLength('username', 100, empty_error=None),
        title=VTitle('title'),
        url=VUrl('url', allow_self=False),
        selftext=VMarkdownLength('text', max_length=40000),
        kind=VOneOf('kind', ['link', 'self']),
        disable_comments=VBoolean("disable_comments"),
        sendreplies=VBoolean("sendreplies"),
        media_url=VUrl("media_url", allow_self=False,
                       valid_schemes=('http', 'https')),
        iframe_embed_url=VUrl("iframe_embed_url", allow_self=False,
                             valid_schemes=('http', 'https')),
        media_url_type=VOneOf("media_url_type", ("redditgifts", "scrape")),
        media_autoplay=VBoolean("media_autoplay"),
        media_override=VBoolean("media-override"),
        domain_override=VLength("domain", 100),
        third_party_tracking=VUrl("third_party_tracking"),
        third_party_tracking_2=VUrl("third_party_tracking_2"),
        is_managed=VBoolean("is_managed"),
        moat_tracking=VBoolean("moat_tracking"),
        promoted_externally=VBoolean("promoted_externally", default=False),
    )
    def POST_create_promo(self, form, jquery, username, title, url,
                          selftext, kind, disable_comments, sendreplies,
                          media_url, media_autoplay, media_override,
                          iframe_embed_url, media_url_type, domain_override,
                          third_party_tracking, third_party_tracking_2,
                          is_managed, moat_tracking, promoted_externally):

        images = _get_ads_images(c.user, data=True, meta=True)

        return self._edit_promo(
            form, jquery, username, title, url,
            selftext, kind, disable_comments, sendreplies,
            media_url, media_autoplay, media_override,
            iframe_embed_url, media_url_type, domain_override,
            third_party_tracking, third_party_tracking_2,
            is_managed, moat_tracking,
            promoted_externally=promoted_externally,
            thumbnail=images.get("thumbnail", None),
            mobile=images.get("mobile", None),
        )

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        VRatelimit(rate_user=True,
                   rate_ip=True,
                   prefix='create_promo_'),
        VShamedDomain('url'),
        username=VLength('username', 100, empty_error=None),
        title=VTitle('title'),
        url=VUrl('url', allow_self=False),
        selftext=VMarkdownLength('text', max_length=40000),
        kind=VOneOf('kind', ['link', 'self']),
        disable_comments=VBoolean("disable_comments"),
        sendreplies=VBoolean("sendreplies"),
        media_url=VUrl("media_url", allow_self=False,
                       valid_schemes=('http', 'https')),
        iframe_embed_url=VUrl("iframe_embed_url", allow_self=False,
                             valid_schemes=('http', 'https')),
        media_url_type=VOneOf("media_url_type", ("redditgifts", "scrape")),
        media_autoplay=VBoolean("media_autoplay"),
        media_override=VBoolean("media-override"),
        domain_override=VLength("domain", 100),
        third_party_tracking=VUrl("third_party_tracking"),
        third_party_tracking_2=VUrl("third_party_tracking_2"),
        is_managed=VBoolean("is_managed"),
        moat_tracking=VBoolean("moat_tracking"),
        l=VLink('link_id36'),
    )
    def POST_edit_promo(self, form, jquery, username, title, url,
                        selftext, kind, disable_comments, sendreplies,
                        media_url, media_autoplay, media_override,
                        iframe_embed_url, media_url_type, domain_override,
                        third_party_tracking, third_party_tracking_2,
                        is_managed, moat_tracking, l):

        images = _get_ads_images(l, data=True, meta=True)

        return self._edit_promo(
            form, jquery, username, title, url,
            selftext, kind, disable_comments, sendreplies,
            media_url, media_autoplay, media_override,
            iframe_embed_url, media_url_type, domain_override,
            third_party_tracking, third_party_tracking_2,
            is_managed, moat_tracking,
            l=l,
            thumbnail=images.get("thumbnail", None),
            mobile=images.get("mobile", None),
        )

    def _edit_promo(self, form, jquery, username, title, url,
                    selftext, kind, disable_comments, sendreplies,
                    media_url, media_autoplay, media_override,
                    iframe_embed_url, media_url_type, domain_override,
                    third_party_tracking, third_party_tracking_2,
                    managed_promo, moat_tracking, promoted_externally=False,
                    l=None, thumbnail=None, mobile=None):
        should_ratelimit = False
        is_self = (kind == "self")
        is_link = not is_self
        is_new_promoted = not l
        third_party_tracking_enabled = feature.is_enabled("third_party_tracking")
        configure_moat_enabled = feature.is_enabled("configure_moat")
        if not c.user_is_sponsor:
            should_ratelimit = True

        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        changed = {}

        # check for user override
        if c.user_is_sponsor:
            if not username:
                c.errors.add(errors.NO_USER, field="username")
                form.set_error(errors.NO_USER, "username")
                return

            try:
                user = Account._by_name(username)
            except NotFound:
                c.errors.add(errors.USER_DOESNT_EXIST, field="username")
                form.set_error(errors.USER_DOESNT_EXIST, "username")
                return

            if not user.email:
                c.errors.add(errors.NO_EMAIL_FOR_USER, field="username")
                form.set_error(errors.NO_EMAIL_FOR_USER, "username")
                return

            if not user.email_verified:
                c.errors.add(errors.NO_VERIFIED_EMAIL, field="username")
                form.set_error(errors.NO_VERIFIED_EMAIL, "username")
                return

        else:
            user = c.user

        # check for shame banned domains
        if form.has_errors("url", errors.DOMAIN_BANNED):
            g.stats.simple_event('spam.shame.link')
            return

        # demangle URL in canonical way
        if url:
            if isinstance(url, (unicode, str)):
                form.set_inputs(url=url)
            elif isinstance(url, tuple) or isinstance(url[0], Link):
                # there's already one or more links with this URL, but
                # we're allowing mutliple submissions, so we really just
                # want the URL
                url = url[0].url

            # Adzerk limits URLs length for creatives
            if len(url) > ADZERK_URL_MAX_LENGTH:
                c.errors.add(errors.TOO_LONG, field='url',
                    msg_params={'max_length': PROMO_URL_MAX_LENGTH})

        if is_link:
            if form.has_errors('url', errors.NO_URL, errors.BAD_URL,
                    errors.TOO_LONG):
                return

        # users can change the disable_comments on promoted links
        if ((is_new_promoted or not promote.is_promoted(l)) and
            (form.has_errors('title', errors.NO_TEXT, errors.TOO_LONG) or
             jquery.has_errors('ratelimit', errors.RATELIMIT))):
            return

        if is_self and form.has_errors('text', errors.TOO_LONG):
            return

        # create only
        if is_new_promoted:
            l = promote.new_promotion(
                is_self=is_self,
                title=title,
                content=(selftext if is_self else url),
                author=user,
                ip=request.ip,
            )

            # manage flights in adzerk
            if promoted_externally:
                promote.update_promote_status(l, PROMOTE_STATUS.external)
        elif not promote.is_promo(l):
            return
        # edit only
        else:
            if title and title != l.title:
                changed["title"] = (l.title, title)
                l.title = title

            # type changing
            if is_self != l.is_self:
                changed["is_self"] = (l.is_self, is_self)
                prev_selftext = l.selftext
                prev_url = l.url

                l.set_content(is_self, selftext if is_self else url)

                if l.is_self:
                    changed["selftext"] = (prev_selftext, l.selftext)
                else:
                    changed["url"] = (prev_url, l.url)

            else:
                if is_link and url and url != l.url:
                    changed["url"] = (l.url, url)
                    l.url = url

                if is_self and selftext != l.selftext:
                    changed["selftext"] = (l.selftext, selftext)
                    l.selftext = selftext

            if c.user_is_sponsor:
                if (form.has_errors("media_url", errors.BAD_URL) or
                        form.has_errors("iframe_embed_url", errors.BAD_URL)):
                    return

            scraper_embed = media_url_type == "scrape"
            media_url = media_url or None
            iframe_embed_url = iframe_embed_url or None

            if c.user_is_sponsor and scraper_embed and media_url != l.media_url:
                if media_url:
                    scraped = media._scrape_media(
                        media_url, autoplay=media_autoplay,
                        save_thumbnail=False, use_cache=True)

                    if scraped:
                        l.set_media_object(scraped.media_object)
                        l.set_secure_media_object(scraped.secure_media_object)
                        l.media_url = media_url
                        l.iframe_embed_url = None
                        l.media_autoplay = media_autoplay
                    else:
                        c.errors.add(errors.SCRAPER_ERROR, field="media_url")
                        form.set_error(errors.SCRAPER_ERROR, "media_url")
                        return
                else:
                    l.set_media_object(None)
                    l.set_secure_media_object(None)
                    l.media_url = None
                    l.iframe_embed_url = None
                    l.media_autoplay = False

            if (c.user_is_sponsor and not scraper_embed and
                    iframe_embed_url != l.iframe_embed_url):
                if iframe_embed_url:

                    sandbox = (
                        'allow-popups',
                        'allow-forms',
                        'allow-same-origin',
                        'allow-scripts',
                    )
                    iframe_attributes = {
                        'embed_url': websafe(iframe_embed_url),
                        'sandbox': ' '.join(sandbox),
                    }
                    iframe = """
                        <iframe class="redditgifts-embed"
                                src="%(embed_url)s"
                                width="710" height="500" scrolling="no"
                                frameborder="0" allowfullscreen
                                sandbox="%(sandbox)s">
                        </iframe>
                    """ % iframe_attributes
                    media_object = {
                        'oembed': {
                            'description': 'redditgifts embed',
                            'height': 500,
                            'html': iframe,
                            'provider_name': 'iframe embed',
                            'provider_url': iframe_embed_url,
                            'type': 'rich',
                            'width': 710},
                            'type': 'iframe'
                    }
                    l.set_media_object(media_object)
                    l.set_secure_media_object(media_object)
                    l.media_url = None
                    l.iframe_embed_url = iframe_embed_url
                    l.media_autoplay = False
                else:
                    l.set_media_object(None)
                    l.set_secure_media_object(None)
                    l.media_url = None
                    l.iframe_embed_url = None
                    l.media_autoplay = False

        if thumbnail:
            old_thumbnail_url = getattr(l, "thumbnail_url", None)
            media.force_thumbnail(l, thumbnail["data"], thumbnail["ext"])
            new_thumbnail_url = getattr(l, "thumbnail_url", None)

            if old_thumbnail_url != new_thumbnail_url:
                changed["thumbnail_url"] = (
                    old_thumbnail_url,
                    new_thumbnail_url,
                )

        can_target_mobile = (feature.is_enabled("mobile_web_targeting") or
            feature.is_enabled("mobile_native_targeting"))

        if can_target_mobile and mobile:
            old_mobile_ad_url = getattr(l, "mobile_ad_url", None)
            media.force_mobile_ad_image(l, mobile["data"], mobile["ext"])
            new_mobile_ad_url = getattr(l, "mobile_ad_url", None)

            if old_mobile_ad_url != new_mobile_ad_url:
                changed["mobile_ad_url"] = (
                    old_mobile_ad_url,
                    new_mobile_ad_url,
                )

        # comment disabling and sendreplies is free to be changed any time.
        if disable_comments != l.disable_comments:
            changed["disable_comments"] = (l.disable_comments, disable_comments)
            l.disable_comments = disable_comments

        if sendreplies != l.sendreplies:
            changed["sendreplies"] = (l.sendreplies, sendreplies)
            l.sendreplies = sendreplies

        if c.user_is_sponsor and l.author_id != user._id:
            promote.queue_change_promo_author(l, user)

        if c.user_is_sponsor:
            if media_override != l.media_override:
                changed["media_override"] = (l.media_override, media_override)
                l.media_override = media_override

            domain_override = domain_override or None
            if domain_override != l.domain_override:
                changed["domain_override"] = (l.domain_override, domain_override)
                l.domain_override = domain_override

            if managed_promo != l.managed_promo:
                changed["managed_promo"] = (l.managed_promo, managed_promo)
                l.managed_promo = managed_promo

        if configure_moat_enabled:
            if moat_tracking != l.moat_tracking:
                changed["moat_tracking"] = (l.moat_tracking, moat_tracking)
                l.moat_tracking = moat_tracking

        if third_party_tracking_enabled:
            third_party_tracking = third_party_tracking or None
            if third_party_tracking != l.third_party_tracking:
                changed["third_party_tracking"] = (
                    l.third_party_tracking,
                    third_party_tracking,
                )
                l.third_party_tracking = third_party_tracking

            third_party_tracking_2 = third_party_tracking_2 or None
            if third_party_tracking_2 != l.third_party_tracking_2:
                changed["third_party_tracking_2"] = (
                    l.third_party_tracking_2,
                    third_party_tracking_2,
                )
                l.third_party_tracking_2 = third_party_tracking_2

        l._commit()

        if not is_new_promoted:
            requires_review = any(key in changed for key in (
                "title",
                "is_self",
                "selftext",
                "url",
                "thumbnail_url",
                "mobile_ad_url",
            ))

            # only trips if changed by a non-sponsor
            if (requires_review and
                    not c.user_is_sponsor and promote.is_promoted(l)):
                promote.edited_live_promotion(l)

            # ensure plugins are notified of the final edits to the link
            # if there are any.
            if changed:
                hooks.get_hook('promote.edit_promotion').call(link=l)

            g.events.edit_promoted_link_event(
                link=l,
                changed_attributes=changed,
                request=request,
                context=c,
            )
        else:
            g.events.new_promoted_link_event(
                link=l,
                request=request,
                context=c,
            )

        # clean up so the same images don't reappear if they create
        # another link
        _clear_ads_images(thing=c.user if is_new_promoted else l)

        form.redirect(promote.promo_edit_url(l))

    @validatedForm(
        VSponsorAdmin(),
        VModhash(),
        start=VDate('startdate'),
        end=VDate('enddate'),
        srs=VSRByNames('srs', required=True),
    )
    def POST_add_roadblock(self, form, jquery, start, end, srs):
        if (form.has_errors('startdate', errors.BAD_DATE) or
                form.has_errors('enddate', errors.BAD_DATE)):
            return

        if end < start:
            c.errors.add(errors.BAD_DATE_RANGE, field='enddate')
            form.has_errors('enddate', errors.BAD_DATE_RANGE)
            return

        if form.has_errors('srs', errors.SUBREDDIT_NOEXIST,
                           errors.SUBREDDIT_NOTALLOWED,
                           errors.SUBREDDIT_REQUIRED):
            return

        if srs:
            srs = srs.values() if type(srs) is dict else [srs]
            for sr in srs:
                PromotedLinkRoadblock.add(sr, start, end)
        jquery.refresh()

    @validatedForm(
        VSponsorAdmin(),
        VModhash(),
        start=VDate('startdate'),
        end=VDate('enddate'),
        sr=VSubmitSR('sr', promotion=True),
    )
    def POST_rm_roadblock(self, form, jquery, start, end, sr):
        if end < start:
            c.errors.add(errors.BAD_DATE_RANGE, field='enddate')
            form.has_errors('enddate', errors.BAD_DATE_RANGE)
            return

        if start and end and sr:
            PromotedLinkRoadblock.remove(sr, start, end)
            jquery.refresh()

    def _lowest_max_bid_dollars(self, total_budget_dollars, bid_dollars, start,
            end):
        """
        Calculate the lower between g.max_bid_pennies
        and maximum bid per day by budget
        """
        ndays = (to_date(end) - to_date(start)).days
        max_daily_bid = total_budget_dollars / ndays
        max_bid_dollars = g.max_bid_pennies / 100.

        return min(max_daily_bid, max_bid_dollars)

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        is_auction=VBoolean('is_auction'),
        start=VDate('startdate', required=False),
        end=VDate('enddate'),
        link=VLink('link_id36'),
        target=VPromoTarget(),
        campaign_id36=nop("campaign_id36"),
        frequency_cap=VFrequencyCap(("frequency_capped",
                                     "frequency_cap"),),
        priority=VPriority("priority"),
        location=VLocation(),
        platform=VOneOf("platform", ("mobile_web", "mobile_native", "desktop", "all"), default="desktop"),
        mobile_os=VList("mobile_os", choices=["iOS", "Android"]),
        os_versions=VOneOf('os_versions', ('all', 'filter'), default='all'),
        ios_devices=VList('ios_device', choices=IOS_DEVICES),
        android_devices=VList('android_device', choices=ANDROID_DEVICES),
        ios_versions=VOSVersion('ios_version_range', 'ios'),
        android_versions=VOSVersion('android_version_range', 'android'),
        no_daily_budget=VBoolean('no_daily_budget', default=False),
        total_budget_dollars=VFloat('total_budget_dollars', coerce=False),
        cost_basis=VOneOf('cost_basis', ('cpc', 'cpm',), default=None),
        bid_dollars=VFloat('bid_dollars', coerce=True),
        auto_extend=VBoolean('auto_extend', default=False)
    )
    def POST_edit_campaign(self, form, jquery, is_auction, link, campaign_id36,
                           start, end, target, frequency_cap,
                           priority, location, platform, mobile_os,
                           os_versions, ios_devices, ios_versions,
                           android_devices, android_versions, no_daily_budget,
                           total_budget_dollars, cost_basis, bid_dollars,
                           auto_extend):
        if not link:
            return

        if (form.has_errors('frequency_cap', errors.INVALID_FREQUENCY_CAP) or
                form.has_errors('frequency_cap', errors.FREQUENCY_CAP_TOO_LOW)):
            return

        if not target:
            # run form.has_errors to populate the errors in the response
            form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                            errors.SUBREDDIT_NOTALLOWED,
                            errors.SUBREDDIT_REQUIRED)
            form.has_errors('collection', errors.COLLECTION_NOEXIST)
            form.has_errors('targeting', errors.INVALID_TARGET)
            form.has_errors('targeting', errors.TARGET_TOO_MANY_SUBREDDITS)
            return

        if form.has_errors('location', errors.INVALID_LOCATION):
            return

        if not allowed_location_and_targets(location, target):
            return abort(403, 'forbidden')

        if (form.has_errors('startdate', errors.BAD_DATE) or
                form.has_errors('enddate', errors.BAD_DATE)):
            return

        if not campaign_id36 and not start:
            c.errors.add(errors.BAD_DATE, field='startdate')
            form.set_error('startdate', errors.BAD_DATE)

        can_target_mobile_web = feature.is_enabled('mobile_web_targeting')
        can_target_mobile_native = feature.is_enabled('mobile_native_targeting')
        can_target_mobile = can_target_mobile_web or can_target_mobile_native
        can_target_mobile_device_version = feature.is_enabled('mobile_device_version_targeting')

        if ((not can_target_mobile_web and platform == "mobile_web") or
                (not can_target_mobile_native and platform == "mobile_native") or
                (not can_target_mobile and platform == "all")):
            return abort(403, 'forbidden')

        if not feature.is_enabled('cpc_pricing'):
            cost_basis = 'cpm'

        # Setup campaign details for existing campaigns
        campaign = None
        if campaign_id36:
            try:
                campaign = PromoCampaign._byID36(campaign_id36, data=True)
            except NotFound:
                pass

            if (not campaign
                    or (campaign._deleted or link._id != campaign.link_id)):
                return abort(404, 'not found')

            requires_reapproval = False
            is_live = promote.is_live_promo(link, campaign)
            is_complete = promote.is_complete_promo(link, campaign)

            if not c.user_is_sponsor:
                # If campaign is live, start_date and total_budget_dollars
                # must not be changed
                if is_live:
                    start = campaign.start_date
                    total_budget_dollars = campaign.total_budget_dollars

        # Configure priority, cost_basis, and bid_pennies
        if feature.is_enabled('ads_auction'):
            if c.user_is_sponsor:
                if is_auction:
                    priority = PROMOTE_PRIORITIES['auction']
                    cost_basis = PROMOTE_COST_BASIS[cost_basis]
                else:
                    cost_basis = PROMOTE_COST_BASIS.fixed_cpm
            else:
                # if non-sponsor, is_auction is not part of the POST request,
                # so must be set independently
                is_auction = True
                priority = PROMOTE_PRIORITIES['auction']
                cost_basis = PROMOTE_COST_BASIS[cost_basis]

                # Error if bid is outside acceptable range
                min_bid_dollars = promote.get_min_bid_dollars(c.user)
                max_bid_dollars = self._lowest_max_bid_dollars(
                    total_budget_dollars=total_budget_dollars,
                    bid_dollars=bid_dollars,
                    start=start,
                    end=end)

                if bid_dollars < min_bid_dollars or bid_dollars > max_bid_dollars:
                    c.errors.add(errors.BAD_BID, field='bid',
                        msg_params={'min': '%.2f' % round(min_bid_dollars, 2),
                                    'max': '%.2f' % round(max_bid_dollars, 2)}
                    )
                    form.has_errors('bid', errors.BAD_BID)
                    return

        else:
            cost_basis = PROMOTE_COST_BASIS.fixed_cpm

        if priority == PROMOTE_PRIORITIES['auction']:
            bid_pennies = bid_dollars * 100
        else:
            link_owner = Account._byID(link.author_id)
            bid_pennies = PromotionPrices.get_price(link_owner, target,
                location)

        if platform == 'desktop':
            mobile_os = None
        else:
            # check if platform includes mobile, but no mobile OS is selected
            if not mobile_os:
                c.errors.add(errors.BAD_PROMO_MOBILE_OS, field='mobile_os')
                form.set_error(errors.BAD_PROMO_MOBILE_OS, 'mobile_os')
                return
            elif can_target_mobile_device_version and os_versions == 'filter':
                # check if OS is selected, but OS devices are not
                if (('iOS' in mobile_os and not ios_devices) or
                        ('Android' in mobile_os and not android_devices)):
                    c.errors.add(errors.BAD_PROMO_MOBILE_DEVICE, field='os_versions')
                    form.set_error(errors.BAD_PROMO_MOBILE_DEVICE, 'os_versions')
                    return
                # check if OS versions are invalid
                if form.has_errors('os_version', errors.INVALID_OS_VERSION):
                    c.errors.add(errors.INVALID_OS_VERSION, field='os_version')
                    form.set_error(errors.INVALID_OS_VERSION, 'os_version')
                    return

        min_start, max_start, max_end = promote.get_date_limits(
            link, c.user_is_sponsor)

        if campaign:
            if feature.is_enabled('ads_auction'):
                # non-sponsors cannot update fixed CPM campaigns,
                # even if they haven't launched (due to auction)
                if not c.user_is_sponsor and not campaign.is_auction:
                    c.errors.add(errors.COST_BASIS_CANNOT_CHANGE,
                        field='cost_basis')
                    form.set_error(errors.COST_BASIS_CANNOT_CHANGE, 'cost_basis')
                    return

            if not c.user_is_sponsor:
                # If target is changed, require reapproval
                if campaign.target != target:
                    requires_reapproval = True

            if campaign.start_date.date() != start.date():
                # Can't edit the start date of campaigns that have served
                if campaign.has_served:
                    c.errors.add(errors.START_DATE_CANNOT_CHANGE, field='startdate')
                    form.has_errors('startdate', errors.START_DATE_CANNOT_CHANGE)
                    return

                if is_live or is_complete:
                    c.errors.add(errors.START_DATE_CANNOT_CHANGE, field='startdate')
                    form.has_errors('startdate', errors.START_DATE_CANNOT_CHANGE)
                    return

        elif start.date() < min_start:
            c.errors.add(errors.DATE_TOO_EARLY,
                         msg_params={'day': min_start.strftime("%m/%d/%Y")},
                         field='startdate')
            form.has_errors('startdate', errors.DATE_TOO_EARLY)
            return

        if start.date() > max_start:
            c.errors.add(errors.DATE_TOO_LATE,
                         msg_params={'day': max_start.strftime("%m/%d/%Y")},
                         field='startdate')
            form.has_errors('startdate', errors.DATE_TOO_LATE)
            return

        if end.date() > max_end:
            c.errors.add(errors.DATE_TOO_LATE,
                         msg_params={'day': max_end.strftime("%m/%d/%Y")},
                         field='enddate')
            form.has_errors('enddate', errors.DATE_TOO_LATE)
            return

        # Ensure end date isn't in the past.
        today = promote.promo_datetime_now()
        if end < today:
            c.errors.add(errors.DATE_TOO_EARLY,
                         msg_params={'day': today.strftime("%m/%d/%Y")},
                         field='enddate')
            form.has_errors('enddate', errors.DATE_TOO_EARLY)
            return

        if end < start:
            c.errors.add(errors.BAD_DATE_RANGE, field='enddate')
            form.has_errors('enddate', errors.BAD_DATE_RANGE)
            return

        # Limit the number of PromoCampaigns a Link can have
        # Note that the front end should prevent the user from getting
        # this far
        existing_campaigns = list(PromoCampaign._by_link(link._id))
        if len(existing_campaigns) > g.MAX_CAMPAIGNS_PER_LINK:
            c.errors.add(errors.TOO_MANY_CAMPAIGNS,
                         msg_params={'count': g.MAX_CAMPAIGNS_PER_LINK},
                         field='title')
            form.has_errors('title', errors.TOO_MANY_CAMPAIGNS)
            return

        if not priority == PROMOTE_PRIORITIES['house']:
            # total_budget_dollars is submitted as a float;
            # convert it to pennies
            total_budget_pennies = int(total_budget_dollars * 100)
            if c.user_is_sponsor:
                min_total_budget_pennies = 0
                max_total_budget_pennies = 0
            else:
                min_total_budget_pennies = g.min_total_budget_pennies
                max_total_budget_pennies = g.max_total_budget_pennies

            if (total_budget_pennies is None or
                    total_budget_pennies < min_total_budget_pennies or
                    (max_total_budget_pennies and
                    total_budget_pennies > max_total_budget_pennies)):
                c.errors.add(errors.BAD_BUDGET, field='total_budget_dollars',
                             msg_params={'min': min_total_budget_pennies,
                                         'max': max_total_budget_pennies or
                                         g.max_total_budget_pennies})
                form.has_errors('total_budget_dollars', errors.BAD_BUDGET)
                return

            # you cannot edit the bid of a live ad unless it's a freebie
            if (campaign and
                    total_budget_pennies != campaign.total_budget_pennies and
                    promote.is_live_promo(link, campaign) and
                    not campaign.is_freebie()):
                c.errors.add(errors.BUDGET_LIVE, field='total_budget_dollars')
                form.has_errors('total_budget_dollars', errors.BUDGET_LIVE)
                return
        else:
            total_budget_pennies = 0

        is_frontpage = (not target.is_collection and
                        target.subreddit_name == Frontpage.name)

        if not target.is_collection and not is_frontpage:
            # targeted to a single subreddit, check roadblock
            sr = target.subreddits_slow[0]
            roadblock = PromotedLinkRoadblock.is_roadblocked(sr, start, end)
            if roadblock and not c.user_is_sponsor:
                msg_params = {"start": roadblock[0].strftime('%m/%d/%Y'),
                              "end": roadblock[1].strftime('%m/%d/%Y')}
                c.errors.add(errors.OVERSOLD, field='sr',
                             msg_params=msg_params)
                form.has_errors('sr', errors.OVERSOLD)
                return

        # Check inventory
        campaign = campaign if campaign_id36 else None
        if not priority.inventory_override:
            oversold = has_oversold_error(form, campaign, start, end,
                                          total_budget_pennies, bid_pennies,
                                          target, location)
            if oversold:
                return

        # Always set frequency_cap_default for auction campaign if
        # frequency_cap is not set and the user isn't a sponsor.
        if not c.user_is_sponsor and not frequency_cap and is_auction:
            frequency_cap = g.frequency_cap_default

        campaign_dict = {
            'start_date': start,
            'end_date': end,
            'target': target,
            'frequency_cap': frequency_cap,
            'priority': priority,
            'location': location,
            'total_budget_pennies': total_budget_pennies,
            'cost_basis': cost_basis,
            'bid_pennies': bid_pennies,
            'platform': platform,
            'mobile_os': mobile_os,
            'no_daily_budget': is_auction and no_daily_budget,
            'auto_extend': (feature.is_enabled("ads_auto_extend") and
                is_auction and auto_extend),
        }

        if can_target_mobile_device_version:
            campaign_dict.update({
                'ios_devices': ios_devices,
                'ios_version_range': ios_versions,
                'android_devices': android_devices,
                'android_version_range': android_versions,
            })

        if campaign:
            if requires_reapproval and promote.is_accepted(link):
                campaign_dict['is_approved'] = False
                campaign_dict['manually_reviewed'] = False
            promote.edit_campaign(
                link,
                campaign,
                **campaign_dict
            )
        else:
            campaign = promote.new_campaign(
                link,
                requires_review=(not c.user_is_sponsor),
                **campaign_dict
            )
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsor('link_id36'),
                   VModhash(),
                   l=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_delete_campaign(self, form, jquery, l, campaign):
        if not campaign or not l or l._id != campaign.link_id:
            return abort(404, 'not found')

        promote.delete_campaign(l, campaign)

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        link=VLink('link_id36'),
        campaign=VPromoCampaign('campaign_id36'),
        should_pause=VBoolean('should_pause'),)
    def POST_toggle_pause_campaign(self, form, jquery, link, campaign,
            should_pause=False):
        if (not link or not campaign or link._id != campaign.link_id
                or not feature.is_enabled('pause_ads')):
            return abort(404, 'not found')

        if campaign.paused == should_pause:
            return

        promote.toggle_pause_campaign(link, campaign, should_pause)
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_terminate_campaign(self, form, jquery, link, campaign):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        promote.terminate_campaign(link, campaign)
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"),
                   hide_after_seen=VBoolean("hide_after"),
                   approved=VBoolean('approved'),
                   reason=nop('reason'),)
    def POST_approve_campaign(self, form, jquery,
                              link, campaign, hide_after_seen,
                              approved, reason):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        promote.set_campaign_approval(link, campaign, is_approved=approved,
                                      manually_reviewed=True, reason=reason)
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

        if hide_after_seen and promote.all_campaigns_reviewed(link):
            jquery("#thing_%s" % link._fullname).hide()

    @exclude_from_logging(
        "firstName",
        "lastName"
        "phoneNumber",
        "cardNumber",
        "cardCode",
        "expirationDate",
    )
    @validatedForm(
        VVerifiedSponsor('link'),
        VModhash(),
        link=VByName("link"),
        campaign=VPromoCampaign("campaign"),
        customer_id=VInt("customer_id", min=0),
        pay_id=VInt("account", min=0),
        edit=VBoolean("edit"),
        address=ValidAddress(
            ["firstName", "lastName", "company", "address", "city", "state",
             "zip", "country", "phoneNumber"]
        ),
        creditcard=ValidCard(["cardNumber", "expirationDate", "cardCode"]),
    )
    def POST_update_pay(self, form, jquery, link, campaign, customer_id, pay_id,
                        edit, address, creditcard):

        def _handle_failed_payment(pay_id=None, reason=None):
            promote.failed_payment_method(c.user, link)
            msg = reason or _("failed to authenticate card. sorry.")
            form.set_text(".status", msg)
            g.events.campaign_payment_failed_event(
                link=link,
                campaign=campaign,
                amount_pennies=campaign.total_budget_pennies,
                reason=reason,
                address=address,
                payment=creditcard,
                is_new_payment_method=new_payment,
                payment_id=pay_id,
                request=request,
                context=c,
            )

        if not g.authorizenetapi:
            return

        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        # Check inventory
        if not campaign.is_auction:
            if campaign_has_oversold_error(form, campaign):
                return

        # check the campaign dates are still valid (user may have created
        # the campaign a few days ago)
        min_start, max_start, max_end = promote.get_date_limits(
            link, c.user_is_sponsor)

        if campaign.start_date.date() > max_start:
            msg = _("please change campaign start date to %(date)s or earlier")
            date = format_date(max_start, format="short", locale=c.locale)
            msg %= {'date': date}
            form.set_text(".status", msg)
            return

        if campaign.start_date.date() < min_start:
            msg = _("please change campaign start date to %(date)s or later")
            date = format_date(min_start, format="short", locale=c.locale)
            msg %= {'date': date}
            form.set_text(".status", msg)
            return

        new_payment = not pay_id
        payment_failed_reason = None

        address_modified = new_payment or edit
        if address_modified:
            address_fields = ["firstName", "lastName", "company", "address",
                              "city", "state", "zip", "country", "phoneNumber"]
            card_fields = ["cardNumber", "expirationDate", "cardCode"]

            if (form.has_errors(address_fields, errors.BAD_ADDRESS) or
                    form.has_errors(card_fields, errors.BAD_CARD)):
                return

            try:
                pay_id = add_or_update_payment_method(
                    c.user, address, creditcard, pay_id)

                if pay_id:
                    promote.new_payment_method(user=c.user,
                                               ip=request.ip,
                                               address=address,
                                               link=link)

            except AuthorizeNetException as e:
                payment_failed_reason = e.message

        g.events.campaign_payment_attempt_event(
            link=link,
            campaign=campaign,
            address=address,
            payment=creditcard,
            amount_pennies=campaign.total_budget_pennies,
            is_new_payment_method=new_payment,
            payment_id=pay_id,
            request=request,
            context=c,
        )

        if pay_id and payment_failed_reason is None:
            success, payment_failed_reason = promote.auth_campaign(link, campaign, c.user,
                                                    pay_id)

            if success:
                hooks.get_hook("promote.campaign_paid").call(link=link, campaign=campaign)
                if not address and g.authorizenetapi:
                    profiles = get_or_create_customer_profile(c.user).paymentProfiles
                    profile = {p.customerPaymentProfileId: p for p in profiles}[pay_id]

                    address = profile.billTo

                promote.successful_payment(link, campaign, request.ip, address)
                g.events.campaign_payment_success_event(
                    link=link,
                    campaign=campaign,
                    amount_pennies=campaign.total_budget_pennies,
                    address=address,
                    payment=creditcard,
                    is_new_payment_method=new_payment,
                    payment_id=pay_id,
                    transaction_id=campaign.trans_id,
                    request=request,
                    context=c,
                )

                jquery.payment_redirect(promote.promo_edit_url(link),
                        new_payment, campaign.total_budget_pennies)
                return
            else:
                _handle_failed_payment(pay_id=pay_id, reason=payment_failed_reason)

        else:
            _handle_failed_payment(pay_id=pay_id, reason=payment_failed_reason)

    @json_validate(
        VSponsor("link"),
        VModhash(),
        link=VLink("link"),
        kind=VOneOf("kind", ["thumbnail", "mobile"]),
        filepath=nop("filepath"),
        ajax=VBoolean("ajax", default=True)
    )
    def POST_ad_s3_params(self, responder, link, kind, filepath, ajax):
        filename, ext = os.path.splitext(filepath)
        ext = ext[1:]
        mime_type, encoding = mimetypes.guess_type(filepath)

        if not mime_type or mime_type not in ALLOWED_IMAGE_TYPES:
            request.environ["extra_error_data"] = {
                "message": _("image must be a jpg or png"),
            }
            abort(403)

        keyspace = _get_ads_keyspace(link if link else c.user)
        key = os.path.join(keyspace, kind)
        redirect = None

        if not ajax:
            now = datetime.now().replace(tzinfo=g.tz)
            signature = get_thing_based_hmac(
                secret=g.secrets["s3_direct_post_callback"],
                thing_name=c.user.name,
                key=key,
                expires=now,
            )
            path = ("/api/ad_s3_callback?hmac=%s&ts=%s" %
                (signature, s3_helpers.format_expires(now)))
            redirect = add_sr(path, sr_path=False)

        return s3_helpers.get_post_args(
            bucket=g.s3_client_uploads_bucket,
            key=key,
            success_action_redirect=redirect,
            success_action_status="201",
            content_type=mime_type,
            meta={
                "x-amz-meta-ext": ext,
            },
        )

    @validate(
        VSponsor(),
        expires=VDate("ts", format=s3_helpers.EXPIRES_DATE_FORMAT),
        signature=VPrintable("hmac", 255),
        callback=nop("callback"),
        key=nop("key"),
    )
    def GET_ad_s3_callback(self, expires, signature, callback, key):
        now = datetime.now(tz=g.tz)
        if (expires + timedelta(minutes=10) < now):
            self.abort404()

        expected_mac = get_thing_based_hmac(
            secret=g.secrets["s3_direct_post_callback"],
            thing_name=c.user.name,
            key=key,
            expires=expires,
        )

        if not constant_time_compare(signature, expected_mac):
            self.abort404()

        template = "<script>parent.__s3_callbacks__[%(callback)s](%(data)s);</script>"
        image = _key_to_dict(
            s3_helpers.get_key(g.s3_client_uploads_bucket, key))
        response = {
            "callback": scriptsafe_dumps(callback),
            "data": scriptsafe_dumps(image),
        }

        return format_html(template, response)

    @validatedForm(
        VSponsorAdmin(),
        VModhash(),
        original_link=VLink("linkid"),
        promoter_text=VTitle('ptext'),
        promoter_url=VUrl('purl', allow_self=False),
        discussion_link=VBoolean('discussion_link'),
        promoted_externally=VBoolean('promoted_externally'),
    )
    def POST_promote_post_submit(self, form, jquery, original_link, 
                                 promoter_text, promoter_url, 
                                 discussion_link, promoted_externally):
        # Create the promoted link
        if discussion_link:
            original_subreddit = Subreddit._byID(original_link.sr_id, stale=True)
            link_url = original_link.make_permalink(original_subreddit)
        else:
            link_url = original_link.url

        sr = Subreddit._byID(Subreddit.get_promote_srid(), stale=True)
        l = Link._submit(
            is_self=False,
            title=original_link.title,
            content=link_url,
            author=Account._byID(original_link.author_id),
            sr=sr,
            ip=request.ip,
        )
        l.promoted = True
        l.disable_comments = True
        if discussion_link:
            l.domain_override = "self." + original_subreddit.name

        # Add additional properties
        l._ups = original_link._ups
        l._downs = original_link._downs
        l.original_link = original_link._fullname
        l.promoted_display_name = promoter_text
        l.promoted_url = promoter_url

        if hasattr(original_link, 'thumbnail_url') and hasattr(original_link, 'thumbnail_size'):
            l.thumbnail_url = original_link.thumbnail_url
            l.thumbnail_size = original_link.thumbnail_size

        if original_link.mobile_ad_url and hasattr(original_link, 'mobile_ad_size'):
            l.mobile_ad_url = original_link.mobile_ad_url
            l.mobile_ad_size = original_link.mobile_ad_size

        # manage flights in adzerk
        if promoted_externally:
            promote.update_promote_status(l, PROMOTE_STATUS.external)
        else:
            promote.update_promote_status(l, PROMOTE_STATUS.promoted)

        l._commit()
        form.redirect(promote.promo_edit_url(l))            
