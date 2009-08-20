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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from validator import *
from pylons.i18n import _
from r2.models import *
from r2.models import bidding
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.menus import *
from r2.controllers import ListingController

from r2.controllers.reddit_base import RedditController

from r2.lib.promote import get_promoted, STATUS, PromoteSR
from r2.lib.utils import timetext
from r2.lib.media import force_thumbnail, thumbnail_url
from r2.lib import cssfilter
from datetime import datetime

class PromoteController(ListingController):
    skip = False
    where = 'promoted'
    render_cls = PromotePage
    
    @property
    def title_text(self):
        return _('promoted by you')
    
    def query(self):
        if c.user_is_sponsor:
            # get all promotions for sponsors
            q = Link._query(Link.c.sr_id == PromoteSR._id)
        else:
            # get user's own promotions
            q = Link._query(Link.c.author_id == c.user._id)
        q._filter(Link.c._spam == (True, False),
                  Link.c.promoted == (True, False))
        q._sort = desc('_date')

        if c.user_is_admin and self.sort == "future_promos":
            q._filter(Link.c.promote_status == STATUS.unseen)
        elif self.sort == "pending_promos":
            if c.user_is_admin:
                q._filter(Link.c.promote_status == STATUS.pending)
            else:
                q._filter(Link.c.promote_status == (STATUS.unpaid,
                                                    STATUS.unseen,
                                                    STATUS.accepted,
                                                    STATUS.rejected))
        elif self.sort == "live_promos":
            q._filter(Link.c.promote_status == STATUS.promoted)

        return q

    @validate(VSponsor())
    def GET_listing(self, sort = "", **env):
        self.sort = sort
        return ListingController.GET_listing(self, **env)

    GET_index = GET_listing
    
    # To open up: VSponsor -> VVerifiedUser
    @validate(VSponsor(),
              VVerifiedUser())
    def GET_new_promo(self):
        return PromotePage('content', content = PromoteLinkForm()).render()

    @validate(VSponsor('link'),
              link = VLink('link'))
    def GET_edit_promo(self, link):
        if link.promoted is None:
            return self.abort404()
        rendered = wrap_links(link)
        timedeltatext = ''
        if link.promote_until:
            timedeltatext = timetext(link.promote_until - datetime.now(g.tz),
                                     resultion=2)

        form = PromoteLinkForm(link = link,
                               listing = rendered,
                               timedeltatext = timedeltatext)
        page = PromotePage('new_promo', content = form)

        return page.render()

    @validate(VSponsor())
    def GET_graph(self):
        return PromotePage("graph", content = Promote_Graph()).render()


    ### POST controllers below
    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   bid   = VBid('bid'))
    def POST_freebie(self, form, jquery, link, bid):
        if link and link.promoted is not None:
            promote.auth_paid_promo(link, c.user, -1, bid)
        jquery.refresh()

    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   note = nop("note"))
    def POST_promote_note(self, form, jquery, link, note):
        if link and link.promoted is not None:
            form.find(".notes").children(":last").after(
                "<p>" + promote.promotion_log(link, note, True) + "</p>")


    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   refund   = VBid('bid'))
    def POST_refund(self, form, jquery, link, refund):
        if link:
            # make sure we don't refund more than we should
            refund = min(refund, link.promote_bid)
            promote.refund_promo(link, c.user, -1, bid)
        jquery.refresh()

    @noresponse(VSponsor(),
                thing = VByName('id'))
    def POST_promote(self, thing):
        if thing:
            now = datetime.now(g.tz)
            # make accepted if unseen or already rejected
            if thing.promote_status in (promote.STATUS.unseen,
                                        promote.STATUS.rejected):
                promote.accept_promo(thing)
            # if not finished and the dates are current
            elif (thing.promote_status < promote.STATUS.finished and
                  thing._date <= now and thing.promote_until > now):
                # if already pending, cron job must have failed.  Promote.  
                if thing.promote_status == promote.STATUS.accepted:
                    promote.pending_promo(thing)
                promote.promote(thing)

    @noresponse(VSponsor(),
                thing = VByName('id'),
                reason = nop("reason"))
    def POST_unpromote(self, thing, reason):
        if thing:
            if (c.user_is_admin and
                (thing.promote_status in (promote.STATUS.unseen,
                                          promote.STATUS.accepted,
                                          promote.STATUS.promoted)) ):
                promote.reject_promo(thing, reason = reason)
            else:
                promote.unpromote(thing)

    # TODO: when opening up, may have to refactor 
    @validatedForm(VSponsor('link_id'),
                   VModhash(),
                   VRatelimit(rate_user = True,
                              rate_ip = True,
                              prefix = 'create_promo_'),
                   ip    = ValidIP(),
                   l     = VLink('link_id'),
                   title = VTitle('title'),
                   url   = VUrl('url', allow_self = False),
                   dates = VDateRange(['startdate', 'enddate'],
                                      future = g.min_promote_future,
                                      admin_override = True),
                   disable_comments = VBoolean("disable_comments"),
                   set_clicks = VBoolean("set_maximum_clicks"),
                   max_clicks = VInt("maximum_clicks", min = 0),
                   set_views = VBoolean("set_maximum_views"),
                   max_views = VInt("maximum_views", min = 0),
                   bid   = VBid('bid'))
    def POST_new_promo(self, form, jquery, l, ip, title, url, dates,
                       disable_comments, 
                       set_clicks, max_clicks, set_views, max_views, bid):
        should_ratelimit = False
        if not c.user_is_sponsor:
            set_clicks = False
            set_views = False
            should_ratelimit = True
        if not set_clicks:
            max_clicks = None
        if not set_views:
            max_views = None

        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))
            
        # demangle URL in canonical way
        if url:
            if isinstance(url, (unicode, str)):
                form.set_inputs(url = url)
            elif isinstance(url, tuple) or isinstance(url[0], Link):
                # there's already one or more links with this URL, but
                # we're allowing mutliple submissions, so we really just
                # want the URL
                url = url[0].url

        # check dates and date range
        start, end = [x.date() for x in dates] if dates else (None, None)
        if not l or (l._date.date(), l.promote_until.date()) == (start,end):
            if (form.has_errors('startdate', errors.BAD_DATE,
                                errors.BAD_FUTURE_DATE) or
                form.has_errors('enddate', errors.BAD_DATE,
                                errors.BAD_FUTURE_DATE, errors.BAD_DATE_RANGE)):
                return

        # dates have been validated at this point.  Next validate title, etc.
        if (form.has_errors('title', errors.NO_TEXT,
                            errors.TOO_LONG) or
            form.has_errors('url', errors.NO_URL, errors.BAD_URL) or
            form.has_errors('bid', errors.BAD_NUMBER) or
            (not l and form.has_errors('ratelimit', errors.RATELIMIT))):
            return
        elif l:
            if l.promote_status == promote.STATUS.finished:
                form.parent().set_html(".status",
                             _("that promoted link is already finished."))
            else:
                # we won't penalize for changes of dates provided
                # the submission isn't pending (or promoted, or
                # finished)
                changed = False
                if dates and not promote.update_promo_dates(l, *dates):
                    form.parent().set_html(".status",
                                           _("too late to change the date."))
                else:
                    changed = True

                # check for changes in the url and title
                if promote.update_promo_data(l, title, url):
                    changed = True
                # sponsors can change the bid value (at the expense of making
                # the promotion a freebie)
                if c.user_is_sponsor and bid != l.promote_bid:
                    promote.auth_paid_promo(l, c.user, -1, bid)
                    promote.accept_promo(l)
                    changed = True

                if c.user_is_sponsor:
                    l.maximum_clicks = max_clicks
                    l.maximum_views = max_views
                    changed = True

                l.disable_comments = disable_comments
                l._commit()

                if changed:
                    jquery.refresh()

        # no link so we are creating a new promotion
        elif dates:
            promote_start, promote_end = dates
            l = promote.new_promotion(title, url, c.user, ip,
                                      promote_start, promote_end, bid,
                                      disable_comments = disable_comments,
                                      max_clicks = max_clicks,
                                      max_views = max_views)
            # if the submitter is a sponsor (or implicitly an admin) we can
            # fast-track the approval and auto-accept the bid
            if c.user_is_sponsor:
                promote.auth_paid_promo(l, c.user, -1, bid)
                promote.accept_promo(l)

            # register a vote
            v = Vote.vote(c.user, l, True, ip)

            # set the rate limiter
            if should_ratelimit:
                VRatelimit.ratelimit(rate_user=True, rate_ip = True, 
                                     prefix = "create_promo_")

            form.redirect(promote.promo_edit_url(l))


    def GET_link_thumb(self, *a, **kw):
        """
        See GET_upload_sr_image for rationale
        """
        return "nothing to see here."

    @validate(VSponsor("link_id"),
              link = VByName('link_id'),
              file = VLength('file', 500*1024))
    def POST_link_thumb(self, link=None, file=None):
        errors = dict(BAD_CSS_NAME = "", IMAGE_ERROR = "")
        try:
            force_thumbnail(link, file)
        except cssfilter.BadImage:
            # if the image doesn't clean up nicely, abort
            errors["IMAGE_ERROR"] = _("bad image")

        if any(errors.values()):
            return UploadedImage("", "", "upload", errors = errors).render()
        else:
            if not c.user_is_sponsor:
                promote.unapproved_promo(l)
            return UploadedImage(_('saved'), thumbnail_url(link), "",
                                 errors = errors).render()


