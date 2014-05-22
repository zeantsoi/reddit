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

import urllib

from oauth2 import require_oauth2_scope
from reddit_base import RedditController, base_listing, paginated_listing

from r2.models import *
from r2.models.query_cache import CachedQuery, MergedCachedQuery
from r2.config.extensions import is_api
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.menus import TimeMenu, SortMenu, RecSortMenu, ProfileSortMenu
from r2.lib.menus import ControversyTimeMenu, menu
from r2.lib.rising import get_rising, normalized_rising
from r2.lib.wrapped import Wrapped
from r2.lib.normalized_hot import normalized_hot
from r2.lib.db.thing import Query, Merge, Relations
from r2.lib.db import queries
from r2.lib.strings import Score
import r2.lib.search as search
from r2.lib.template_helpers import add_sr
from r2.lib.admin_utils import check_cheating
from r2.lib.utils import iters, timeago
from r2.lib import organic, sup, trending
from r2.lib.memoize import memoize
from r2.lib.validator import *
from r2.lib.butler import extract_user_mentions
import socket

from api_docs import api_doc, api_section

from pylons.i18n import _

import random
from functools import partial

class ListingController(RedditController):
    """Generalized controller for pages with lists of links."""

    # toggle skipping of links based on the users' save/hide/vote preferences
    skip = True

    # allow stylesheets on listings
    allow_stylesheets = True

    # toggles showing numbers
    show_nums = True

    # any text that should be shown on the top of the page
    infotext = None

    # builder class to use to generate the listing. if none, we'll try
    # to figure it out based on the query type
    builder_cls = None

    # page title
    title_text = ''

    # login box, subreddit box, submit box, etc, visible
    show_sidebar = True
    show_chooser = False

    # class (probably a subclass of Reddit) to use to render the page.
    render_cls = Reddit

    # class for suggestions next to "next/prev" buttons
    next_suggestions_cls = None

    #extra parameters to send to the render_cls constructor
    render_params = {}
    extra_page_classes = ['listing-page']

    @property
    def menus(self):
        """list of menus underneat the header (e.g., sort, time, kind,
        etc) to be displayed on this listing page"""
        return []

    def build_listing(self, num, after, reverse, count, **kwargs):
        """uses the query() method to define the contents of the
        listing and renders the page self.render_cls(..).render() with
        the listing as contents"""
        self.num = num
        self.count = count
        self.after = after
        self.reverse = reverse

        self.query_obj = self.query()
        self.builder_obj = self.builder()
        self.listing_obj = self.listing()

        content = self.content()
        return self.render_cls(content=content,
                               page_classes=self.extra_page_classes,
                               show_sidebar=self.show_sidebar,
                               show_chooser=self.show_chooser,
                               nav_menus=self.menus,
                               title=self.title(),
                               infotext=self.infotext,
                               robots=getattr(self, "robots", None),
                               **self.render_params).render()

    def content(self):
        """Renderable object which will end up as content of the render_cls"""
        return self.listing_obj

    def query(self):
        """Query to execute to generate the listing"""
        raise NotImplementedError

    def builder(self):
        #store the query itself so it can be used elsewhere
        if self.builder_cls:
            builder_cls = self.builder_cls
        elif isinstance(self.query_obj, Query):
            builder_cls = QueryBuilder
        elif isinstance(self.query_obj, search.SearchQuery):
            builder_cls = SearchBuilder
        elif isinstance(self.query_obj, iters):
            builder_cls = IDBuilder
        elif isinstance(self.query_obj, (queries.CachedResults, queries.MergedCachedResults)):
            builder_cls = IDBuilder
        elif isinstance(self.query_obj, (CachedQuery, MergedCachedQuery)):
            builder_cls = IDBuilder

        b = builder_cls(self.query_obj,
                        num = self.num,
                        skip = self.skip,
                        after = self.after,
                        count = self.count,
                        reverse = self.reverse,
                        keep_fn = self.keep_fn(),
                        wrap = self.builder_wrapper)

        return b

    def keep_fn(self):
        def keep(item):
            wouldkeep = item.keep_item(item)
            if getattr(item, "promoted", None) is not None:
                return False
            if item._deleted and not c.user_is_admin:
                return False
            return wouldkeep
        return keep

    def listing(self):
        """Listing to generate from the builder"""
        if (getattr(c.site, "_id", -1) == get_promote_srid() and
            not c.user_is_sponsor):
            abort(403, 'forbidden')
        model = LinkListing(self.builder_obj, show_nums=self.show_nums)
        suggestions = None
        if self.next_suggestions_cls:
            suggestions = self.next_suggestions_cls()
        pane = model.listing(next_suggestions=suggestions)
        # Indicate that the comment tree wasn't built for comments
        for i in pane:
            if hasattr(i, 'full_comment_path'):
                i.child = None
        return pane

    def title(self):
        """Page <title>"""
        return _(self.title_text) + " : " + c.site.name

    def rightbox(self):
        """Contents of the right box when rendering"""
        pass

    builder_wrapper = staticmethod(default_thing_wrapper())

    @require_oauth2_scope("read")
    @base_listing
    def GET_listing(self, **env):
        check_cheating('site')
        return self.build_listing(**env)

listing_api_doc = partial(
    api_doc,
    section=api_section.listings,
    extends=ListingController.GET_listing,
    notes=[paginated_listing.doc_note],
    extensions=["json", "xml"],
)


class ListingWithPromos(ListingController):
    show_organic = False

    def make_requested_ad(self, requested_ad):
        try:
            link = Link._by_fullname(requested_ad, data=True)
        except NotFound:
            self.abort404()

        if not (link.promoted and
                (c.user_is_sponsor or
                 c.user_is_loggedin and link.author_id == c.user._id)):
            self.abort403()

        if not promote.is_live_on_sr(link, c.site):
            self.abort403()

        res = wrap_links([link._fullname], wrapper=self.builder_wrapper,
                         skip=False)
        res.parent_name = "promoted"
        if res.things:
            return res

    def make_single_ad(self):
        srnames = promote.srnames_with_live_promos(c.user, c.site)
        if srnames:
            return SpotlightListing(show_promo=True, srnames=srnames,
                                    navigable=False).listing()

    def make_spotlight(self):
        """Build the Spotlight.

        The frontpage gets a Spotlight box that contains promoted and organic
        links from the user's subscribed subreddits and promoted links targeted
        to the frontpage. If the user has disabled ads promoted links will not
        be shown. Promoted links are requested from the adserver client-side.

        """

        organic_fullnames = organic.organic_links(c.user)
        promoted_links = []

        show_promo = False
        srnames = []
        can_show_promo = c.user.pref_show_sponsors or not c.user.gold
        try_show_promo = ((c.user_is_loggedin and random.random() > 0.5) or
                          not c.user_is_loggedin)

        if can_show_promo and try_show_promo:
            srnames = promote.srnames_with_live_promos(c.user, c.site)
            if srnames:
                show_promo = True

        random.shuffle(organic_fullnames)
        organic_fullnames = organic_fullnames[:10]
        b = IDBuilder(organic_fullnames,
                      wrap=self.builder_wrapper,
                      keep_fn=organic.keep_fresh_links,
                      skip=True)
        organic_links = b.get_items()[0]

        has_subscribed = c.user.has_subscribed
        interestbar_prob = g.live_config['spotlight_interest_sub_p'
                                         if has_subscribed else
                                         'spotlight_interest_nosub_p']
        interestbar = InterestBar(has_subscribed)

        s = SpotlightListing(organic_links=organic_links,
                             interestbar=interestbar,
                             interestbar_prob=interestbar_prob,
                             show_promo=show_promo,
                             srnames=srnames,
                             max_num = self.listing_obj.max_num,
                             max_score = self.listing_obj.max_score).listing()
        return s

    def content(self):
        # only send a spotlight listing for HTML rendering
        if c.render_style == "html":
            spotlight = None
            show_sponsors = not (not c.user.pref_show_sponsors and c.user.gold)
            show_organic = self.show_organic and c.user.pref_organic
            on_frontpage = isinstance(c.site, DefaultSR)
            requested_ad = request.GET.get('ad')

            if on_frontpage:
                self.extra_page_classes = \
                    self.extra_page_classes + ['front-page']

            if requested_ad:
                spotlight = self.make_requested_ad(requested_ad)
            elif on_frontpage and show_organic:
                spotlight = self.make_spotlight()
            elif show_sponsors:
                spotlight = self.make_single_ad()

            self.spotlight = spotlight

            if spotlight:
                return PaneStack([spotlight, self.listing_obj],
                                 css_class='spacer')
        return self.listing_obj


class HotController(ListingWithPromos):
    where = 'hot'
    extra_page_classes = ListingController.extra_page_classes + ['hot-page']
    show_chooser = True
    next_suggestions_cls = ListingSuggestions
    show_organic = True

    def query(self):

        if isinstance(c.site, DefaultSR):
            sr_ids = Subreddit.user_subreddits(c.user)
            return normalized_hot(sr_ids)
        elif isinstance(c.site, MultiReddit):
            return normalized_hot(c.site.kept_sr_ids, obey_age_limit=False)
        else:
            if c.site.sticky_fullname:
                link_list = [c.site.sticky_fullname]
                wrapped = wrap_links(link_list,
                                     wrapper=self.builder_wrapper,
                                     keep_fn=self.keep_fn(),
                                     skip=True)
                # add all other items and decrement count if sticky is visible
                if wrapped.things:
                    link_list += [l for l in c.site.get_links('hot', 'all')
                                    if l != c.site.sticky_fullname]
                    if not self.after:
                        self.count -= 1
                        self.num += 1
                    return link_list
            
            # no sticky or sticky hidden
            return c.site.get_links('hot', 'all')

    @classmethod
    def trending_info(cls):
        if not c.user.pref_show_trending:
            return None

        trending_data = trending.get_trending_subreddits()

        if not trending_data:
            return None

        link = Link._byID(trending_data['link_id'], data=True, stale=True)
        return {
            'subreddit_names': trending_data['subreddit_names'],
            'comment_url': trending_data['permalink'],
            'comment_count': link.num_comments,
        }

    def content(self):
        content = super(HotController, self).content()
        if (c.render_style == "html" and isinstance(c.site, DefaultSR) and
                not self.listing_obj.prev):
            trending_info = self.trending_info()
            if trending_info:
                return PaneStack(filter(None, [
                    self.spotlight,
                    TrendingSubredditsBar(**trending_info),
                    self.listing_obj,
                ]), css_class='spacer')
        return content


    def title(self):
        return c.site.title

    @require_oauth2_scope("read")
    @listing_api_doc(uri='/hot', uses_site=True)
    def GET_listing(self, **env):
        self.infotext = request.GET.get('deleted') and strings.user_deleted
        return ListingController.GET_listing(self, **env)

class NewController(ListingWithPromos):
    where = 'new'
    title_text = _('newest submissions')
    extra_page_classes = ListingController.extra_page_classes + ['new-page']
    show_chooser = True
    next_suggestions_cls = ListingSuggestions

    def keep_fn(self):
        def keep(item):
            if item.promoted is not None:
                return False
            else:
                return item.keep_item(item)
        return keep

    def query(self):
        return c.site.get_links('new', 'all')

    def POST_listing(self, **env):
        # Redirect to GET mode in case of any legacy requests
        return self.redirect(request.fullpath)

    @require_oauth2_scope("read")
    @listing_api_doc(uri='/new', uses_site=True)
    def GET_listing(self, **env):
        if request.params.get('sort') == 'rising':
            return self.redirect(add_sr('/rising'))

        return ListingController.GET_listing(self, **env)

class RisingController(NewController):
    where = 'rising'
    title_text = _('rising submissions')
    extra_page_classes = ListingController.extra_page_classes + ['rising-page']

    def query(self):
        if isinstance(c.site, DefaultSR):
            sr_ids = Subreddit.user_subreddits(c.user)
            return normalized_rising(sr_ids)
        elif isinstance(c.site, MultiReddit):
            return normalized_rising(c.site.kept_sr_ids)

        return get_rising(c.site)

class BrowseController(ListingWithPromos):
    where = 'browse'
    show_chooser = True
    next_suggestions_cls = ListingSuggestions

    def keep_fn(self):
        """For merged time-listings, don't show items that are too old
           (this can happen when mr_top hasn't run in a while)"""
        if self.time != 'all' and c.default_sr:
            oldest = timeago('1 %s' % (str(self.time),))
            def keep(item):
                return item._date > oldest and item.keep_item(item)
            return keep
        else:
            return ListingController.keep_fn(self)

    @property
    def menus(self):
        return [ControversyTimeMenu(default = self.time)]

    def query(self):
        return c.site.get_links(self.sort, self.time)

    @validate(t = VMenu('sort', ControversyTimeMenu))
    def POST_listing(self, sort, t, **env):
        # VMenu validator will save the value of time before we reach this
        # point. Now just redirect to GET mode.
        return self.redirect(
            request.fullpath + query_string(dict(sort=sort, t=t)))

    @require_oauth2_scope("read")
    @validate(t = VMenu('sort', ControversyTimeMenu))
    @listing_api_doc(uri='/{sort}', uri_variants=['/top', '/controversial'],
                     uses_site=True)
    def GET_listing(self, sort, t, **env):
        self.sort = sort
        if sort == 'top':
            self.title_text = _('top scoring links')
            self.extra_page_classes = \
                self.extra_page_classes + ['top-page']
        elif sort == 'controversial':
            self.title_text = _('most controversial links')
            self.extra_page_classes = \
                self.extra_page_classes + ['controversial-page']
        else:
            # 'sort' is forced to top/controversial by routing.py,
            # but in case something has gone wrong...
            abort(404)
        self.time = t
        return ListingController.GET_listing(self, **env)


class AdsController(ListingController):
    builder_cls = CampaignBuilder
    title_text = _('promoted links')

    @property
    def infotext(self):
        infotext = _("want to advertise? [click here!](%(link)s)")
        if c.user.pref_show_promote or c.user_is_sponsor:
            return infotext % {'link': '/promoted'}
        else:
            return infotext % {'link': '/ad_inq'}

    def keep_fn(self):
        def keep(item):
            return item.promoted and not item._deleted
        return keep

    def query(self):
        try:
            return c.site.get_live_promos()
        except NotImplementedError:
            self.abort404()


class RandomrisingController(ListingWithPromos):
    where = 'randomrising'
    title_text = _('you\'re really bored now, eh?')
    next_suggestions_cls = ListingSuggestions

    def query(self):
        links = get_rising(c.site)

        if not links:
            # just pull from the new page if the rising page isn't
            # populated for some reason
            links = c.site.get_links('new', 'all')
            if isinstance(links, Query):
                links._limit = 200
                links = [x._fullname for x in links]

        links = list(links)
        random.shuffle(links)

        return links

class ByIDController(ListingController):
    title_text = _('API')
    skip = False

    def query(self):
        return self.names

    @require_oauth2_scope("read")
    @validate(links=VByName("names", thing_cls=Link,
                            ignore_missing=True, multiple=True))
    @api_doc(api_section.listings, uri='/by_id/{names}')
    def GET_listing(self, links, **env):
        """Get a listing of links by fullname.

        `names` is a list of fullnames for links separated by commas or spaces.

        """
        if not links:
            return self.abort404()
        self.names = [l._fullname for l in links]
        return ListingController.GET_listing(self, **env)


class UserController(ListingController):
    render_cls = ProfilePage
    show_nums = False
    skip = True

    @property
    def menus(self):
        res = []
        if (self.where in ('overview', 'submitted', 'comments')):
            res.append(ProfileSortMenu(default = self.sort))
            if self.sort not in ("hot", "new"):
                res.append(TimeMenu(default = self.time))
        if self.where == 'saved' and c.user.gold:
            srnames = LinkSavesBySubreddit.get_saved_subreddits(self.vuser)
            srnames += CommentSavesBySubreddit.get_saved_subreddits(self.vuser)
            srs = Subreddit._by_name(srnames)
            srnames = [name for name, sr in srs.iteritems()
                            if sr.can_view(c.user)]
            srnames = sorted(set(srnames), key=lambda name: name.lower())
            if len(srnames) > 1:
                sr_buttons = [NavButton(_('all'), None, opt='sr',
                                        css_class='primary')]
                for srname in srnames:
                    sr_buttons.append(NavButton(srname, srname, opt='sr'))
                base_path = '/user/%s/saved' % self.vuser.name
                if self.savedcategory:
                    base_path += '/%s' % urllib.quote(self.savedcategory)
                sr_menu = NavMenu(sr_buttons, base_path=base_path,
                                  title=_('filter by subreddit'),
                                  type='lightdrop')
                res.append(sr_menu)
            categories = LinkSavesByCategory.get_saved_categories(self.vuser)
            categories += CommentSavesByCategory.get_saved_categories(self.vuser)
            categories = sorted(set(categories))
            if len(categories) >= 1:
                cat_buttons = [NavButton(_('all'), '/', css_class='primary')]
                for cat in categories:
                    cat_buttons.append(NavButton(cat,
                                                 urllib.quote(cat),
                                                 use_params=True))
                base_path = '/user/%s/saved/' % self.vuser.name
                cat_menu = NavMenu(cat_buttons, base_path=base_path,
                                   title=_('filter by category'),
                                   type='lightdrop')
                res.append(cat_menu)
        elif (self.where == 'gilded' and
                (c.user == self.vuser or c.user_is_admin)):
            path = '/user/%s/gilded/' % self.vuser.name
            buttons = [NavButton(_("gildings received"), dest='/'),
                       NavButton(_("gildings given"), dest='/given')]
            res.append(NavMenu(buttons, base_path=path, type='flatlist'))

        return res

    def title(self):
        titles = {'overview': _("overview for %(user)s"),
                  'comments': _("comments by %(user)s"),
                  'submitted': _("submitted by %(user)s"),
                  'gilded': _("gilded by %(user)s"),
                  'liked': _("liked by %(user)s"),
                  'disliked': _("disliked by %(user)s"),
                  'saved': _("saved by %(user)s"),
                  'hidden': _("hidden by %(user)s"),
                  'promoted': _("promoted by %(user)s")}
        if self.where == 'gilded' and self.show == 'given':
            return _("gildings given by %(user)s") % {'user': self.vuser.name}

        title = titles.get(self.where, _('profile for %(user)s')) \
            % dict(user = self.vuser.name, site = c.site.name)
        return title

    def keep_fn(self):
        def keep(item):
            if self.where == 'promoted':
                return bool(getattr(item, "promoted", None))

            if item._deleted and not c.user_is_admin:
                return False

            if c.user == self.vuser:
                if not item.likes and self.where == 'liked':
                    return False
                if item.likes is not False and self.where == 'disliked':
                    return False
                if self.where == 'saved' and not item.saved:
                    return False

            if (self.time != 'all' and
                item._date <= utils.timeago('1 %s' % str(self.time))):
                return False

            if self.where == 'gilded' and item.gildings <= 0:
                return False

            if self.where == 'deleted' and not item._deleted:
                return False

            is_promoted = getattr(item, "promoted", None) is not None
            if self.where != 'saved' and is_promoted:
                return False

            return True
        return keep

    def query(self):
        q = None
        if self.where == 'overview':
            self.check_modified(self.vuser, 'overview')
            q = queries.get_overview(self.vuser, self.sort, self.time)

        elif self.where == 'comments':
            sup.set_sup_header(self.vuser, 'commented')
            self.check_modified(self.vuser, 'commented')
            q = queries.get_comments(self.vuser, self.sort, self.time)

        elif self.where == 'submitted':
            sup.set_sup_header(self.vuser, 'submitted')
            self.check_modified(self.vuser, 'submitted')
            q = queries.get_submitted(self.vuser, self.sort, self.time)

        elif self.where == 'gilded':
            sup.set_sup_header(self.vuser, 'gilded')
            self.check_modified(self.vuser, 'gilded')
            if self.show == 'given':
                q = queries.get_user_gildings(self.vuser)
            else:
                q = queries.get_gilded_user(self.vuser)

        elif self.where in ('liked', 'disliked'):
            sup.set_sup_header(self.vuser, self.where)
            self.check_modified(self.vuser, self.where)
            if self.where == 'liked':
                q = queries.get_liked(self.vuser)
            else:
                q = queries.get_disliked(self.vuser)

        elif self.where == 'hidden':
            q = queries.get_hidden(self.vuser)

        elif self.where == 'saved':
            if not self.savedcategory and c.user.gold:
                self.builder_cls = SavedBuilder
            sr_id = self.savedsr._id if self.savedsr else None
            q = queries.get_saved(self.vuser, sr_id,
                                  category=self.savedcategory)
        elif c.user_is_sponsor and self.where == 'promoted':
            q = queries.get_promoted_links(self.vuser._id)

        if q is None:
            return self.abort404()

        return q

    @require_oauth2_scope("history")
    @validate(vuser = VExistingUname('username'),
              sort = VMenu('sort', ProfileSortMenu, remember = False),
              time = VMenu('t', TimeMenu, remember = False),
              show=VOneOf('show', ('given',)))
    @listing_api_doc(section=api_section.users, uri='/user/{username}/{where}',
                     uri_variants=['/user/{username}/' + where for where in [
                                       'overview', 'submitted', 'comments',
                                       'liked', 'disliked', 'hidden', 'saved',
                                       'gilded']])
    def GET_listing(self, where, vuser, sort, time, show, **env):
        self.where = where
        self.sort = sort
        self.time = time
        self.show = show

        # the validator will ensure that vuser is a valid account
        if not vuser:
            return self.abort404()

        if self.sort in  ('hot', 'new'):
            self.time = 'all'


        # hide spammers profile pages
        if (not c.user_is_loggedin or
            (c.user._id != vuser._id and not c.user_is_admin)) \
               and vuser._spam:
            return self.abort404()

        if where in ('liked', 'disliked') and not votes_visible(vuser):
            return self.abort403()

        if ((where in ('saved', 'hidden') or 
                (where == 'gilded' and show == 'given')) and
                not (c.user_is_loggedin and c.user._id == vuser._id) and
                not c.user_is_admin):
            return self.abort403()

        if where == 'saved':
            self.show_chooser = True
            category = VSavedCategory('category').run(env.get('category'))
            srname = request.GET.get('sr')
            if srname and c.user.gold:
                try:
                    sr = Subreddit._by_name(srname)
                except NotFound:
                    sr = None
            else:
                sr = None
            if category and not c.user.gold:
                category = None
            self.savedsr = sr
            self.savedcategory = category

        check_cheating('user')

        self.vuser = vuser
        self.render_params = {'user' : vuser}
        c.profilepage = True

        if vuser.pref_hide_from_robots:
            self.robots = 'noindex,nofollow'

        return ListingController.GET_listing(self, **env)

    @require_oauth2_scope("read")
    @validate(vuser = VExistingUname('username'))
    @api_doc(section=api_section.users, uri='/user/{username}/about',
             extensions=['json'])
    def GET_about(self, vuser):
        """Return information about the user, including karma and gold status."""
        if (not is_api() or
                not vuser or
                (vuser._spam and vuser != c.user)):
            return self.abort404()
        return Reddit(content = Wrapped(vuser)).render()

    def GET_saved_redirect(self):
        if not c.user_is_loggedin:
            abort(404)

        dest = "/".join(("/user", c.user.name, "saved"))
        extension = request.environ.get('extension')
        if extension:
            dest = ".".join((dest, extension))
        query_string = request.environ.get('QUERY_STRING')
        if query_string:
            dest += "?" + query_string
        return self.redirect(dest)

class MessageController(ListingController):
    show_nums = False
    render_cls = MessagePage
    allow_stylesheets = False
    # note: this intentionally replaces the listing-page class which doesn't
    # conceptually fit for styling these pages.
    extra_page_classes = ['messages-page']

    @property
    def show_sidebar(self):
        if c.default_sr and not isinstance(c.site, (ModSR, MultiReddit)):
            return False

        return self.where in ("moderator", "multi")

    @property
    def menus(self):
        if c.default_sr and self.where in ('inbox', 'messages', 'comments',
                          'selfreply', 'unread', 'mentions'):
            buttons = [NavButton(_("all"), "inbox"),
                       NavButton(_("unread"), "unread"),
                       NavButton(plurals.messages, "messages"),
                       NavButton(_("comment replies"), 'comments'),
                       NavButton(_("post replies"), 'selfreply')]

            if c.user.gold:
                buttons += [NavButton(_("username mentions"),
                                      "mentions",
                                      css_class="gold")]

            return [NavMenu(buttons, base_path = '/message/',
                            default = 'inbox', type = "flatlist")]
        elif not c.default_sr or self.where in ('moderator', 'multi'):
            buttons = (NavButton(_("all"), "inbox"),
                       NavButton(_("unread"), "unread"))
            return [NavMenu(buttons, base_path = '/message/moderator/',
                            default = 'inbox', type = "flatlist")]
        return []


    def title(self):
        return _('messages') + ': ' + _(self.where)

    def keep_fn(self):
        def keep(item):
            wouldkeep = item.keep_item(item)

            # TODO: Consider a flag to disable this (and see above plus builder.py)
            if item._deleted and not c.user_is_admin:
                return False
            if (item._spam and
                    item.author_id != c.user._id and
                    not c.user_is_admin):
                return False
            if item.author_id in c.user.enemies:
                return False
            # don't show user their own unread stuff
            if ((self.where == 'unread' or self.subwhere == 'unread')
                and (item.author_id == c.user._id or not item.new)):
                return False

            if (item.message_style == "mention" and
                c.user.name.lower() not in extract_user_mentions(item.body)):
                return False

            return wouldkeep
        return keep

    @staticmethod
    def builder_wrapper(thing):
        if isinstance(thing, Comment):
            f = thing._fullname
            w = Wrapped(thing)
            w.render_class = Message
            w.to_id = c.user._id
            w.was_comment = True
            w._fullname = f
        else:
            w = ListingController.builder_wrapper(thing)

        return w

    def builder(self):
        if (self.where == 'messages' or
            (self.where in ("moderator", "multi") and self.subwhere != "unread")):
            root = c.user
            message_cls = UserMessageBuilder

            if self.where == "multi":
                root = c.site
                message_cls = MultiredditMessageBuilder
            elif not c.default_sr:
                root = c.site
                message_cls = SrMessageBuilder
            elif self.where == 'moderator' and self.subwhere != 'unread':
                message_cls = ModeratorMessageBuilder

            parent = None
            skip = False
            if self.message:
                if self.message.first_message:
                    parent = Message._byID(self.message.first_message,
                                           data=True)
                else:
                    parent = self.message
            elif c.user.pref_threaded_messages:
                skip = (c.render_style == "html")

            if (message_cls is UserMessageBuilder and parent and parent.sr_id
                and not parent.from_sr):
                # Make sure we use the subreddit message builder for modmail,
                # because the per-user cache will be wrong if more than two
                # parties are involved in the thread.
                root = Subreddit._byID(parent.sr_id)
                message_cls = SrMessageBuilder

            return message_cls(root,
                               wrap = self.builder_wrapper,
                               parent = parent,
                               skip = skip,
                               num = self.num,
                               after = self.after,
                               keep_fn = self.keep_fn(),
                               reverse = self.reverse)
        return ListingController.builder(self)

    def listing(self):
        if (self.where == 'messages' and
            (c.user.pref_threaded_messages or self.message)):
            return Listing(self.builder_obj).listing()
        pane = ListingController.listing(self)

        # Indicate that the comment tree wasn't built for comments
        for i in pane.things:
            if i.was_comment:
                i.child = None

        return pane

    def query(self):
        if self.where == 'messages':
            q = queries.get_inbox_messages(c.user)
        elif self.where == 'comments':
            q = queries.get_inbox_comments(c.user)
        elif self.where == 'selfreply':
            q = queries.get_inbox_selfreply(c.user)
        elif self.where == 'mentions':
            q = queries.get_inbox_comment_mentions(c.user)
        elif self.where == 'inbox':
            q = queries.get_inbox(c.user)
        elif self.where == 'unread':
            q = queries.get_unread_inbox(c.user)
        elif self.where == 'sent':
            q = queries.get_sent(c.user)
        elif self.where == 'multi' and self.subwhere == 'unread':
            q = queries.get_unread_subreddit_messages_multi(c.site.kept_sr_ids)
        elif self.where == 'moderator' and self.subwhere == 'unread':
            if c.default_sr:
                srids = Subreddit.reverse_moderator_ids(c.user)
                srs = [sr for sr in Subreddit._byID(srids, data=False,
                                                    return_dict=False)
                       if sr.is_moderator_with_perms(c.user, 'mail')]
                q = queries.get_unread_subreddit_messages_multi(srs)
            else:
                q = queries.get_unread_subreddit_messages(c.site)
        elif self.where in ('moderator', 'multi'):
            if c.have_mod_messages and self.mark != 'false':
                c.have_mod_messages = False
                c.user.modmsgtime = False
                c.user._commit()
            # the query is handled by the builder on the moderator page
            return
        else:
            return self.abort404()
        if self.where != 'sent':
            #reset the inbox
            if c.have_messages and self.mark != 'false':
                c.have_messages = False
                c.user.msgtime = False
                c.user._commit()

        return q

    @require_oauth2_scope("privatemessages")
    @validate(VUser(),
              message = VMessageID('mid'),
              mark = VOneOf('mark',('true','false')))
    @listing_api_doc(section=api_section.messages,
                     uri='/message/{where}',
                     uri_variants=['/message/inbox', '/message/unread', '/message/sent'])
    def GET_listing(self, where, mark, message, subwhere = None, **env):
        if not (c.default_sr
                or c.site.is_moderator_with_perms(c.user, 'mail')
                or c.user_is_admin):
            abort(403, "forbidden")
        if isinstance(c.site, MultiReddit):
            if not (c.user_is_admin or c.site.is_moderator(c.user)):
                self.abort403()
            self.where = "multi"
        elif isinstance(c.site, ModSR) or not c.default_sr:
            self.where = "moderator"
        else:
            self.where = where
        self.subwhere = subwhere
        if mark is not None:
            self.mark = mark
        elif is_api():
            self.mark = 'false'
        elif c.render_style and c.render_style == "xml":
            self.mark = 'false'
        else:
            self.mark = 'true'
        self.message = message
        return ListingController.GET_listing(self, **env)

    @validate(VUser(),
              to = nop('to'),
              subject = nop('subject'),
              message = nop('message'),
              success = nop('success'))
    def GET_compose(self, to, subject, message, success):
        captcha = Captcha() if c.user.needs_captcha() else None
        content = MessageCompose(to = to, subject = subject,
                                 captcha = captcha,
                                 message = message,
                                 success = success)
        return MessagePage(content = content).render()

class RedditsController(ListingController):
    render_cls = SubredditsPage

    def title(self):
        return _('subreddits')

    def keep_fn(self):
        base_keep_fn = ListingController.keep_fn(self)
        def keep(item):
            return base_keep_fn(item) and (c.over18 or not item.over_18)
        return keep

    def query(self):
        if self.where == 'banned' and c.user_is_admin:
            reddits = Subreddit._query(Subreddit.c._spam == True,
                                       sort = desc('_date'),
                                       write_cache = True,
                                       read_cache = True,
                                       cache_time = 5 * 60)
        else:
            reddits = None
            if self.where == 'new':
                reddits = Subreddit._query( write_cache = True,
                                            read_cache = True,
                                            cache_time = 5 * 60)
                reddits._sort = desc('_date')
            else:
                reddits = Subreddit._query( write_cache = True,
                                            read_cache = True,
                                            cache_time = 60 * 60)
                reddits._sort = desc('_downs')
            # Consider resurrecting when it is not the World Cup
            #if c.content_langs != 'all':
            #    reddits._filter(Subreddit.c.lang == c.content_langs)

            if g.domain != 'reddit.com':
                # don't try to render special subreddits (like promos)
                reddits._filter(Subreddit.c.author_id != -1)

        if self.where == 'popular':
            self.render_params = {"show_interestbar": True}

        return reddits

    @require_oauth2_scope("read")
    @listing_api_doc(section=api_section.subreddits,
                     uri='/subreddits/{where}',
                     uri_variants=['/subreddits/popular', '/subreddits/new'])
    def GET_listing(self, where, **env):
        """Get all subreddits.

        The `where` parameter chooses the order in which the subreddits are
        displayed.  `popular` sorts on the activity of the subreddit and the
        position of the subreddits can shift around. `new` sorts the subreddits
        based on their creation date, newest first.

        """
        self.where = where
        return ListingController.GET_listing(self, **env)

class MyredditsController(ListingController):
    render_cls = MySubredditsPage

    @property
    def menus(self):
        buttons = (NavButton(plurals.subscriber,  'subscriber'),
                    NavButton(getattr(plurals, "approved submitter"), 'contributor'),
                    NavButton(plurals.moderator,   'moderator'))

        return [NavMenu(buttons, base_path = '/subreddits/mine/',
                        default = 'subscriber', type = "flatlist")]

    def title(self):
        return _('subreddits: ') + self.where

    def builder_wrapper(self, thing):
        w = ListingController.builder_wrapper(thing)
        if self.where == 'moderator':
            is_moderator = thing.is_moderator(c.user)
            if is_moderator:
                w.mod_permissions = is_moderator.get_permissions()
        return w

    def query(self):
        reddits = SRMember._query(SRMember.c._name == self.where,
                                  SRMember.c._thing2_id == c.user._id,
                                  #hack to prevent the query from
                                  #adding it's own date
                                  sort = (desc('_t1_ups'), desc('_t1_date')),
                                  eager_load = True,
                                  thing_data = True)
        reddits.prewrap_fn = lambda x: x._thing1
        return reddits

    def content(self):
        user = c.user if c.user_is_loggedin else None
        num_subscriptions = len(Subreddit.reverse_subscriber_ids(user))
        if self.where == 'subscriber' and num_subscriptions == 0:
            message = strings.sr_messages['empty']
        else:
            message = strings.sr_messages.get(self.where)

        stack = PaneStack()

        if message:
            stack.append(InfoBar(message=message))

        stack.append(self.listing_obj)

        return stack

    def build_listing(self, after=None, **kwargs):
        if after and isinstance(after, Subreddit):
            after = SRMember._fast_query(after, c.user, self.where,
                                         data=False).values()[0]
        if after and not isinstance(after, SRMember):
            abort(400, 'gimme a srmember')

        return ListingController.build_listing(self, after=after, **kwargs)

    @require_oauth2_scope("mysubreddits")
    @validate(VUser())
    @listing_api_doc(section=api_section.subreddits,
                     uri='/subreddits/mine/{where}',
                     uri_variants=['/subreddits/mine/subscriber', '/subreddits/mine/contributor', '/subreddits/mine/moderator'])
    def GET_listing(self, where='subscriber', **env):
        """Get subreddits the user has a relationship with.

        The `where` parameter chooses which subreddits are returned as follows:

        * `subscriber` - subreddits the user is subscribed to
        * `contributor` - subreddits the user is an approved submitter in
        * `moderator` - subreddits the user is a moderator of

        See also: [/api/subscribe](#POST_api_subscribe),
        [/api/friend](#POST_api_friend), and
        [/api/accept_moderator_invite](#POST_api_accept_moderator_invite).

        """
        self.where = where
        return ListingController.GET_listing(self, **env)

class CommentsController(ListingController):
    title_text = _('comments')

    def keep_fn(self):
        def keep(item):
            can_see_spam = (c.user_is_loggedin and
                            (item.author_id == c.user._id or
                             c.user_is_admin or
                             item.subreddit.is_moderator(c.user)))
            can_see_deleted = c.user_is_loggedin and c.user_is_admin

            return ((not item._spam or can_see_spam) and
                    (not item._deleted or can_see_deleted))

        return keep

    def query(self):
        return c.site.get_all_comments()

    @require_oauth2_scope("read")
    def GET_listing(self, **env):
        c.profilepage = True
        return ListingController.GET_listing(self, **env)

class UserListListingController(ListingController):
    builder_cls = UserListBuilder
    allow_stylesheets = False
    skip = False
    friends_compat = True

    @property
    def infotext(self):
        if self.where == 'friends':
            return strings.friends % Friends.path
        elif self.where == 'blocked':
            return _("To block a user click 'block user'  below a message"
                     " from a user you wish to block from messaging you.")

    @property
    def render_params(self):
        params = {}
        is_wiki_action = self.where in ["wikibanned", "wikicontributors"]
        params["show_wiki_actions"] = is_wiki_action
        return params

    @property
    def render_cls(self):
        if self.where in ["friends", "blocked"]:
            return PrefsPage
        return Reddit

    def moderator_wrap(self, rel, invited=False):
        rel._permission_class = ModeratorPermissionSet
        cls = ModTableItem if not invited else InvitedModTableItem
        return cls(rel, editable=self.editable)

    @property
    def builder_wrapper(self):
        if self.where == 'banned':
            cls = BannedTableItem
        elif self.where == 'moderators':
            return self.moderator_wrap
        elif self.where == 'wikibanned':
            cls = WikiBannedTableItem
        elif self.where == 'contributors':
            cls = ContributorTableItem
        elif self.where == 'wikicontributors':
            cls = WikiMayContributeTableItem
        elif self.where == 'friends':
            cls = FriendTableItem
        elif self.where == 'blocked':
            cls = EnemyTableItem
        return lambda rel : cls(rel, editable=self.editable)

    def title(self):
        return menu[self.where]

    def rel(self):
        if self.where in ['friends', 'blocked']:
            return Friend
        return SRMember

    def name(self):
        return self._names.get(self.where)

    _names = {
              'friends': 'friend',
              'blocked': 'enemy',
              'moderators': 'moderator',
              'contributors': 'contributor',
              'banned': 'banned',
              'wikibanned': 'wikibanned',
              'wikicontributors': 'wikicontributor',
             }

    def query(self):
        rel = self.rel()
        if self.where in ["friends", "blocked"]:
            thing1_id = c.user._id
        else:
            thing1_id = c.site._id
        reversed_types = ["friends", "moderators", "blocked"]
        sort = desc if self.where not in reversed_types else asc
        q = rel._query(rel.c._thing1_id == thing1_id,
                       rel.c._name == self.name(),
                       sort=sort('_date'),
                       data=True)
        if self.jump_to_val:
            thing2_id = self.user._id if self.user else None
            q._filter(rel.c._thing2_id == thing2_id)
        return q

    def listing(self):
        listing = self.listing_cls(self.builder_obj,
                                   addable=self.editable,
                                   show_jump_to=self.show_jump_to,
                                   jump_to_value=self.jump_to_val,
                                   show_not_found=self.show_not_found,
                                   nextprev=self.paginated,
                                   has_add_form=self.editable)
        return listing.listing()

    def invited_mod_listing(self):
        query = SRMember._query(SRMember.c._name == 'moderator_invite',
                                SRMember.c._thing1_id == c.site._id,
                                sort=asc('_date'), data=True)
        wrapper = lambda rel: self.moderator_wrap(rel, invited=True)
        b = self.builder_cls(query,
                             keep_fn=self.keep_fn(),
                             wrap=wrapper,
                             skip=False,
                             num=0)
        return InvitedModListing(b, nextprev=False).listing()

    def content(self):
        is_api = c.render_style in extensions.API_TYPES
        if self.where == 'moderators' and self.editable and not is_api:
            # Do not stack the invited mod list in api mode
            # to allow for api compatibility with older api users.
            content = PaneStack()
            content.append(self.listing_obj)
            content.append(self.invited_mod_listing())
        elif self.where == 'friends' and is_api and self.friends_compat:
            content = PaneStack()
            content.append(self.listing_obj)
            empty_builder = IDBuilder([])
            # Append an empty UserList on the api for backwards
            # compatibility with the old blocked list.
            content.append(UserListing(empty_builder, nextprev=False).listing())
        else:
            content = self.listing_obj
        return content

    @require_oauth2_scope("read")
    @validate(VUser())
    @base_listing
    @listing_api_doc(section=api_section.account,
                     uri='/prefs/{where}',
                     uri_variants=['/prefs/friends', '/prefs/blocked',
                         '/api/v1/me/friends', '/api/v1/me/blocked'])
    def GET_user_prefs(self, where, **kw):
        self.where = where

        self.listing_cls = None
        self.editable = True
        self.paginated = False
        self.jump_to_val = None
        self.show_not_found = False
        self.show_jump_to = False
        # The /prefs/friends version of this endpoint used to contain
        # two lists of users: friends AND blocked users. For backwards
        # compatibility with the old JSON structure, an empty list
        # of "blocked" users is sent.
        # The /api/v1/me/friends version of the friends list does not
        # have this requirement, so it will send just the "friends"
        # data structure.
        self.friends_compat = not request.path.startswith('/api/v1/me/')

        if where == 'friends':
            self.listing_cls = FriendListing
        elif where == 'blocked':
            self.listing_cls = EnemyListing
            self.show_not_found = True
        else:
            abort(404)

        kw['num'] = 0
        check_cheating('site')
        return self.build_listing(**kw)


    @require_oauth2_scope("read")
    @validate(user=VAccountByName('user'))
    @base_listing
    @listing_api_doc(section=api_section.subreddits,
                     uses_site=True,
                     uri='/about/{where}',
                     uri_variants=['/about/' + where for where in [
                        'banned', 'wikibanned', 'contributors',
                        'wikicontributors', 'moderators']])
    def GET_listing(self, where, user=None, **kw):
        if isinstance(c.site, FakeSubreddit):
            return self.abort404()

        self.where = where

        has_mod_access = ((c.user_is_loggedin and
                           c.site.is_moderator_with_perms(c.user, 'access'))
                          or c.user_is_admin)

        if not c.user_is_loggedin and where not in ['contributors', 'moderators']:
            abort(403)

        self.listing_cls = None
        self.editable = True
        self.paginated = True
        self.jump_to_val = request.GET.get('user')
        self.show_not_found = bool(self.jump_to_val)

        if where == 'contributors':
            # On public reddits, only moderators may see the whitelist.
            if c.site.type == 'public' and not has_mod_access:
                abort(403)
            # Used for subreddits like /r/lounge
            if c.site.hide_subscribers:
                abort(403)
            self.listing_cls = ContributorListing
            self.editable = has_mod_access

        elif where == 'banned':
            if not has_mod_access:
                abort(403)
            self.listing_cls = BannedListing

        elif where == 'wikibanned':
            if not c.site.is_moderator_with_perms(c.user, 'wiki'):
                abort(403)
            self.listing_cls = WikiBannedListing

        elif where == 'wikicontributors':
            if not c.site.is_moderator_with_perms(c.user, 'wiki'):
                abort(403)
            self.listing_cls = WikiMayContributeListing

        elif where == 'moderators':
            self.editable = ((c.user_is_loggedin and
                              c.site.is_unlimited_moderator(c.user)) or
                             c.user_is_admin)
            self.listing_cls = ModListing
            self.paginated = False

        if not self.listing_cls:
            abort(404)

        self.user = user
        self.show_jump_to = self.paginated

        if not self.paginated:
            kw['num'] = 0

        check_cheating('site')
        return self.build_listing(**kw)

class GildedController(ListingController):
    title_text = _("gilded")

    def keep_fn(self):
        def keep(item):
            return item.gildings > 0 and not item._deleted and not item._spam
        return keep

    def query(self):
        try:
            return c.site.get_gilded()
        except NotImplementedError:
            abort(404)

    @require_oauth2_scope("read")
    def GET_listing(self, **env):
        c.profilepage = True
        return ListingController.GET_listing(self, **env)
