## The contents of this file are subject to the Common Public Attribution
## License Version 1.0. (the "License"); you may not use this file except in
## compliance with the License. You may obtain a copy of the License at
## http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
## License Version 1.1, but Sections 14 and 15 have been added to cover use of
## software over a computer network and provide for limited attribution for the
## Original Developer. In addition, Exhibit A has been modified to be consistent
## with Exhibit B.
## 
## Software distributed under the License is distributed on an "AS IS" basis,
## WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
## the specific language governing rights and limitations under the License.
## 
## The Original Code is Reddit.
## 
## The Original Developer is the Initial Developer.  The Initial Developer of
## the Original Code is CondeNet, Inc.
## 
## All portions of the code written by CondeNet are Copyright (c) 2006-2009
## CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.menus import Styled
from r2.lib.wrapped import Wrapped
from r2.models import LinkListing, make_wrapper, Link, IDBuilder, PromotedLink, Thing
from r2.lib.utils import tup
from r2.lib.strings import Score
from r2.lib.promote import promo_edit_url
from datetime import datetime
from pylons import c, g

class PrintableButtons(Styled):
    def __init__(self, style, thing,
                 show_delete = False, show_report = True,
                 show_distinguish = False, **kw):
        show_report = show_report and c.user_is_loggedin
        Styled.__init__(self, style = style,
                        fullname = thing._fullname,
                        can_ban = thing.can_ban,
                        show_spam = thing.show_spam,
                        show_reports = thing.show_reports,
                        show_delete = show_delete,
                        show_report = show_report,
                        show_distinguish = show_distinguish,
                        **kw)
        
class BanButtons(PrintableButtons):
    def __init__(self, thing,
                 show_delete = False, show_report = True):
        PrintableButtons.__init__(self, "banbuttons", thing)

class LinkButtons(PrintableButtons):
    def __init__(self, thing, comments = True, delete = True, report = True):
        # is the current user the author?
        is_author = (c.user_is_loggedin and thing.author and
                     c.user.name == thing.author.name)
        # do we show the report button?
        show_report = not is_author and report
        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted
        # do we show the distinguish button? among other things,
        # we never want it to appear on link listings -- only
        # comments pages
        show_distinguish = (is_author and thing.can_ban 
                            and getattr(thing, "expand_children", False))

        kw = {}
        if thing.promoted is not None:
            now = datetime.now(g.tz)
            promotable = (thing._date <= now and thing.promote_until > now)
            kw = dict(promo_url = promo_edit_url(thing),
                      promote_status = getattr(thing, "promote_status", 0),
                      user_is_sponsor = c.user_is_sponsor,
                      promotable = promotable,
                      traffic_url = "/traffic/" + thing._id36, 
                      is_author = thing.is_author)
                      
        PrintableButtons.__init__(self, 'linkbuttons', thing, 
                                  # user existence and preferences
                                  is_loggedin = c.user_is_loggedin,
                                  new_window = c.user.pref_newwindow,
                                  # comment link params
                                  comment_label = thing.comment_label,
                                  commentcls = thing.commentcls,
                                  permalink  = thing.permalink,
                                  # button visibility
                                  saved = thing.saved,
                                  editable = thing.editable, 
                                  hidden = thing.hidden, 
                                  show_delete = show_delete,
                                  show_report = show_report,
                                  show_distinguish = show_distinguish,
                                  show_comments = comments,
                                  # promotion
                                  promoted = thing.promoted,
                                  **kw)

class CommentButtons(PrintableButtons):
    def __init__(self, thing, delete = True, report = True):
        # is the current user the author?
        is_author = (c.user_is_loggedin and thing.author and
                     c.user.name == thing.author.name)
        # do we show the report button?
        show_report = not is_author and report
        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted

        show_distinguish = is_author and thing.can_ban

        PrintableButtons.__init__(self, "commentbuttons", thing,
                                  is_author = is_author, 
                                  profilepage = c.profilepage,
                                  permalink = thing.permalink,
                                  deleted = thing.deleted,
                                  parent_permalink = thing.parent_permalink, 
                                  can_reply = thing.can_reply,
                                  show_report = show_report,
                                  show_distinguish = show_distinguish,
                                  show_delete = show_delete)

class MessageButtons(PrintableButtons):
    def __init__(self, thing, delete = False, report = True):
        was_comment = getattr(thing, 'was_comment', False)
        permalink = thing.permalink if was_comment else ""

        PrintableButtons.__init__(self, "messagebuttons", thing,
                                  profilepage = c.profilepage,
                                  permalink = permalink,
                                  was_comment = was_comment,
                                  can_reply = c.user_is_loggedin,
                                  parent_id = getattr(thing, "parent_id", None),
                                  show_report = True,
                                  show_delete = False)

# formerly ListingController.builder_wrapper
def default_thing_wrapper(**params):
    def _default_thing_wrapper(thing):
        w = Wrapped(thing)
        style = params.get('style', c.render_style)
        if isinstance(thing, Link):
            if thing.promoted is not None:
                w.render_class = PromotedLink
                w.rowstyle = 'promoted link'
            elif style == 'htmllite':
                w.score_fmt = Score.points
        return w
    params['parent_wrapper'] = _default_thing_wrapper
    return make_wrapper(**params)

# TODO: move this into lib somewhere?
def wrap_links(links, wrapper = default_thing_wrapper(),
               listing_cls = LinkListing, 
               num = None, show_nums = False, nextprev = False,
               num_margin = None, mid_margin = None):
    links = tup(links)
    if not all(isinstance(x, str) for x in links):
        links = [x._fullname for x in links]
    b = IDBuilder(links, num = num, wrap = wrapper)
    l = listing_cls(b, nextprev = nextprev, show_nums = show_nums)
    if num_margin is not None:
        l.num_margin = num_margin
    if mid_margin is not None:
        l.mid_margin = mid_margin
    return l.listing()
    

