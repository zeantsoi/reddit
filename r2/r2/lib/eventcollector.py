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
import baseplate.events
import time
import re
from urlparse import urlparse

from pylons import app_globals as g
from collections import defaultdict

from r2.lib import hooks
from r2.lib.language import charset_summary
from r2.lib.geoip import (
    get_request_location,
    location_by_ips,
)
from r2.lib.cache_poisoning import cache_headers_valid
from r2.lib.utils import (
    domain,
    to_epoch_milliseconds,
    sampled,
    squelch_exceptions,
    to36,
    url_to_thing,
)

# XXX External dependencies!
_datetime_to_millis = to_epoch_milliseconds


class EventQueue(object):
    def __init__(self):
        self.queue_production = baseplate.events.EventQueue("production")
        self.queue_test = baseplate.events.EventQueue("test")

    def save_event(self, event, test=False):
        try:
            if not test:
                self.queue_production.put(event)
            else:
                self.queue_test.put(event)
        except baseplate.events.EventTooLargeError as exc:
            g.log.warning("%s", exc)
            g.stats.simple_event("eventcollector.oversize_dropped")
        except baseplate.events.EventQueueFullError as exc:
            g.log.warning("%s", exc)
            g.stats.simple_event("eventcollector.queue_full")
        except UnicodeDecodeError as exc:
            # When including request data in the event payload, we sometimes
            # encounter invalid utf-8 strings in the Referer header or path.
            g.log.error("Got weird unicode in the event data: %s", exc)

    @squelch_exceptions
    @sampled("events_collector_vote_sample_rate")
    def vote_event(self, vote):
        """Create a 'vote' event for event-collector

        vote: An r2.models.vote Vote object
        """

        # For mapping vote directions to readable names used by data team
        def get_vote_direction_name(vote):
            if vote.is_upvote:
                return "up"
            elif vote.is_downvote:
                return "down"
            else:
                return "clear"

        event = Event(
            topic="vote_server",
            event_type="server_vote",
            time=vote.date,
            data=vote.event_data["context"],
            obfuscated_data=vote.event_data["sensitive"],
        )

        event.add("vote_direction", get_vote_direction_name(vote))

        if vote.previous_vote:
            event.add("prev_vote_direction",
                get_vote_direction_name(vote.previous_vote))
            event.add(
                "prev_vote_ts",
                to_epoch_milliseconds(vote.previous_vote.date)
            )

        if vote.is_automatic_initial_vote:
            event.add("auto_self_vote", True)

        for name, value in vote.effects.serializable_data.iteritems():
            # rename the "notes" field to "details_text" for the event
            if name == "notes":
                name = "details_text"

            event.add(name, value)

        # add the note codes separately as "process_notes"
        event.add("process_notes", ", ".join(vote.effects.note_codes))

        event.add_subreddit_fields(vote.thing.subreddit_slow)
        event.add_target_fields(vote.thing)

        # add the rank of the vote if we have it (passed in through the API)
        rank = vote.data.get('rank')
        if rank:
            event.add("target_rank", rank)

        self.save_event(event)

    def canonical_redirect_event(self, canonical_url, request, context):
        event = Event(
            topic='canonical_redirect_events',
            event_type='canonical_redirection',
            request=request,
            context=context,
        )

        event.add('redirect_url', canonical_url)
        event.add('redirect_from_path', request.fullpath)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_submit_sample_rate")
    def submit_event(self, new_post, request=None, context=None,
            context_data=None):
        """Create a 'submit' event for event-collector

        new_post: An r2.models.Link object
        request, context: Should be pylons.request & pylons.c respectively
        context_data: The context_data processed from request and c. Used
            when request and c aren't accessible (from the image_upload_q)

        """
        event = Event(
            topic="submit_events",
            event_type="ss.submit",
            time=new_post._date,
            request=request,
            context=context,
            data=context_data,
        )

        event.add("post_id", new_post._id)
        event.add("post_fullname", new_post._fullname)
        event.add_text("post_title", new_post.title)

        event.add("user_neutered", new_post.author_slow._spam)

        if new_post.is_self:
            event.add("post_type", "self")
            event.add_text("post_body", new_post.selftext)
        else:
            if new_post.image_upload:
                event.add("post_type", "image")
            else:
                event.add("post_type", "link")
            event.add("post_target_url", new_post.url)
            event.add("post_target_domain", new_post.link_domain())

        event.add_subreddit_fields(new_post.subreddit_slow)

        self.save_event(event)

    @squelch_exceptions
    def image_upload_event(self, key_name=None, mimetype=None,
            size=None, px_size=None, url=None,
            successful=True, context_data=None):
        """Create an event for submitting an image upload.

        key_name: Random ID that the image will take on as the filename
            when uploaded to S3
        mimetype: Type of image taken from the file extension
        size: Size in bytes of the file
        px_size: Tuple of (width, height) of image in pixels
        url: Image url
        successful: True if the image is moved to the permanent bucket
        context_data: The context_data processed from request and c. Used
            when request and c aren't accessible (from the image_upload_q)
        """
        event = Event(
            topic="image_upload_events",
            event_type="ss.upload_image",
            data=context_data,
        )

        event.add("image_key", key_name)
        event.add("image_mimetype", mimetype)
        event.add("image_size", size)
        event.add("image_url", url)

        if successful:
            event.add("successful", successful)
        else:
            event.add("process_notes", "BAD_FILETYPE")

        if px_size:
            event.add("image_width", px_size[0])
            event.add("image_height", px_size[1])

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_comment_sample_rate")
    def comment_event(self, new_comment, request=None, context=None):
        """Create a 'comment' event for event-collector.

        new_comment: An r2.models.Comment object
        request, context: Should be pylons.request & pylons.c respectively
        """
        from r2.models import Comment, Link

        event = Event(
            topic="comment_events",
            event_type="ss.comment",
            time=new_comment._date,
            request=request,
            context=context,
        )

        event.add("comment_id", new_comment._id)
        event.add("comment_fullname", new_comment._fullname)

        event.add_text("comment_body", new_comment.body)

        post = Link._byID(new_comment.link_id)
        event.add("post_id", post._id)
        event.add("post_fullname", post._fullname)
        event.add("post_created_ts", to_epoch_milliseconds(post._date))
        if post.promoted:
            event.add("post_is_promoted", bool(post.promoted))

        if new_comment.parent_id:
            parent = Comment._byID(new_comment.parent_id)
        else:
            # If this is a top-level comment, parent is the same as the post
            parent = post
        event.add("parent_id", parent._id)
        event.add("parent_fullname", parent._fullname)
        event.add("parent_created_ts", to_epoch_milliseconds(parent._date))

        event.add("user_neutered", new_comment.author_slow._spam)

        event.add_subreddit_fields(new_comment.subreddit_slow)

        self.save_event(event)

    @squelch_exceptions
    def sr_created_event(self, new_sr, base_url=None, request=None,
                         context=None):
        """Create a 'comment' event for event-collector.

        new_sr: The newly created subreddit.
        request, context: Should be pylons.request & pylons.c respectively
        """
        from r2.models import Subreddit

        event = Event(
            topic="subreddit_create_events",
            event_type="ss.subreddit_created",
            time=new_sr._date,
            request=request,
            context=context,
        )

        event.add("sr_id", new_sr._id)
        event.add('sr_name', new_sr.name)
        event.add('sr_type', new_sr.type)
        event.add('base_url', base_url)
        event.add('user_neutered', new_sr.author_slow._spam)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_poison_sample_rate")
    def cache_poisoning_event(self, poison_info, request=None, context=None):
        """Create a 'cache_poisoning_server' event for event-collector

        poison_info: Details from the client about the poisoning event
        request, context: Should be pylons.request & pylons.c respectively

        """
        poisoner_name = poison_info.pop("poisoner_name")

        event = Event(
            topic="cache_poisoning_events",
            event_type="ss.cache_poisoning",
            request=request,
            context=context,
            data=poison_info,
        )

        event.add("poison_blame_guess", "proxy")

        resp_headers = poison_info["resp_headers"]
        if resp_headers:
            # Check if the caching headers we got back match the current policy
            cache_policy = poison_info["cache_policy"]
            headers_valid = cache_headers_valid(cache_policy, resp_headers)

            event.add("cache_headers_valid", headers_valid)

        # try to determine what kind of poisoning we're dealing with

        if poison_info["source"] == "web":
            # Do we think they logged in the usual way, or do we think they
            # got poisoned with someone else's session cookie?
            valid_login_hook = hooks.get_hook("poisoning.guess_valid_login")
            if valid_login_hook.call_until_return(poisoner_name=poisoner_name):
                # Maybe a misconfigured local Squid proxy + multiple
                # clients?
                event.add("poison_blame_guess", "local_proxy")
                event.add("poison_credentialed_guess", False)
            elif (context.user_is_loggedin and
                  context.user.name == poisoner_name):
                # Guess we got poisoned with a cookie-bearing response.
                event.add("poison_credentialed_guess", True)
            else:
                event.add("poison_credentialed_guess", False)
        elif poison_info["source"] == "mweb":
            # All mweb responses contain an OAuth token, so we have to assume
            # whoever got this response can perform actions as the poisoner
            event.add("poison_credentialed_guess", True)
        else:
            raise Exception("Unsupported source in cache_poisoning_event")

        # Check if the CF-Cache-Status header is present (this header is not
        # present if caching is disallowed.) If it is, the CDN caching rules
        # are all jacked up.
        if resp_headers and "cf-cache-status" in resp_headers:
            event.add("poison_blame_guess", "cdn")

        self.save_event(event)

    @squelch_exceptions
    def muted_forbidden_event(self, details_text, subreddit=None,
            parent_message=None, target=None, request=None, context=None):
        """Create a mute-related 'forbidden_event' for event-collector.

        details_text: "muted" if a muted user is trying to message the
            subreddit or "muted mod" if the subreddit mod is attempting
            to message the muted user
        subreddit: The Subreddit of the mod messaging the muted user
        parent_message: Message that is being responded to
        target: The intended recipient (Subreddit or Account)
        request, context: Should be pylons.request & pylons.c respectively;

        """
        event = Event(
            topic="forbidden_actions",
            event_type="ss.forbidden_message_attempt",
            request=request,
            context=context,
        )
        event.add("details_text", details_text)

        if parent_message:
            event.add("parent_message_id", parent_message._id)
            event.add("parent_message_fullname", parent_message._fullname)

        event.add_subreddit_fields(subreddit)
        event.add_target_fields(target)

        self.save_event(event)

    @squelch_exceptions
    def timeout_forbidden_event(self, action_name, details_text,
                                process_notes="IN_TIMEOUT", target=None,
                                target_fullname=None, subreddit=None,
                                request=None, context=None):
        """Create a timeout-related 'forbidden_actions' for event-collector.

        action_name: the action taken by a user in timeout
        details_text: this provides more details about the action
        process_notes: this provides additional text for the action
        target: The intended item the action was to be taken on
        target_fullname: The fullname used to convert to a target
        subreddit: The Subreddit the action was taken in. If target is of the
            type Subreddit, then this won't be passed in
        request, context: Should be pylons.request & pylons.c respectively;

        """
        from r2.models import Account, Comment, Link, Subreddit

        if not action_name:
            request_vars = request.environ["pylons.routes_dict"]
            action_name = request_vars.get('action_name')

            # type of vote
            if action_name == "vote":
                direction = int(request.POST.get("dir", 0))
                if direction == 1:
                    action_name = "upvote"
                elif direction == -1:
                    action_name = "downvote"
                else:
                    action_name = "clearvote"
            # set or unset for contest mode and subreddit sticky
            elif action_name in ("set_contest_mode", "set_subreddit_sticky"):
                action_name = action_name.replace("_", "")
                if request.POST.get('state') == "False":
                    action_name = "un" + action_name
            # set or unset for suggested sort
            elif action_name == "set_suggested_sort":
                action_name = action_name.replace("_", "")
                if request.POST.get("sort") in ("", "clear"):
                    action_name = "un" + action_name
            # action for viewing /about/reports, /about/spam, /about/modqueue
            elif action_name == "spamlisting":
                action_name = "pageview"
                details_text = request_vars.get("location")
            elif action_name == "clearflairtemplates":
                action_name = "editflair"
                details_text = "flair_clear_template"
            elif action_name in ("flairconfig", "flaircsv", "flairlisting"):
                details_text = action_name.replace("flair", "flair_")
                action_name = "editflair"

        if not target:
            if not target_fullname:
                if action_name in ("wiki_settings", "wiki_edit"):
                    target = context.site
                elif action_name in ("wiki_allow_editor"):
                    target = Account._by_name(request.POST.get("username"))
                elif action_name in ("delete_sr_header", "delete_sr_icon",
                        "delete_sr_banner"):
                    details_text = "%s" % action_name.replace("ete_sr", "")
                    action_name = "editsettings"
                    target = context.site
                elif action_name in ("bannedlisting", "mutedlisting",
                        "wikibannedlisting", "wikicontributorslisting"):
                    target = context.site

            if target_fullname:
                from r2.models import Thing
                target = Thing._by_fullname(
                    target_fullname,
                    return_dict=False,
                    data=True,
            )

        event = Event(
            topic="forbidden_actions",
            event_type="ss.forbidden_%s" % action_name,
            request=request,
            context=context,
        )
        event.add("details_text", details_text)
        event.add("process_notes", process_notes)

        if not subreddit:
            if isinstance(context.site, Subreddit):
                subreddit = context.site
            elif isinstance(target, (Comment, Link)):
                subreddit = target.subreddit_slow
            elif isinstance(target, Subreddit):
                subreddit = target

        event.add_subreddit_fields(subreddit)
        event.add_target_fields(target)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_mod_sample_rate")
    def mod_event(self, modaction, subreddit, mod, target=None,
            request=None, context=None):
        """Create a 'mod' event for event-collector.

        modaction: An r2.models.ModAction object
        subreddit: The Subreddit the mod action is being performed in
        mod: The Account that is performing the mod action
        target: The Thing the mod action was applied to
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = Event(
            topic="mod_events",
            event_type=modaction.action,
            time=modaction.date,
            uuid=modaction._id,
            request=request,
            context=context,
        )

        event.add("details_text", modaction.details_text)

        # Some jobs that perform mod actions (for example, AutoModerator) are
        # run without actually logging into the account that performs the
        # the actions. In that case, set the user data based on the mod that's
        # performing the action.
        if not event.get_field("user_id"):
            event.add("user_id", mod._id)
            event.add("user_name", mod.name)

        event.add_subreddit_fields(subreddit)
        event.add_target_fields(target)

        hooks.get_hook("eventcollector.mod_event").call(
            event=event,
            user=mod,
            request=request,
            context=context,
        )

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_report_sample_rate")
    def report_event(self, reason=None, details_text=None,
            subreddit=None, target=None, request=None, context=None,
                     event_type="ss.report"):
        """Create a 'report' event for event-collector.

        process_notes: Type of rule (pre-defined report reasons or custom)
        details_text: The report reason
        subreddit: The Subreddit the action is being performed in
        target: The Thing the action was applied to
        request, context: Should be pylons.request & pylons.c respectively

        """
        from r2.models.rules import OLD_SITEWIDE_RULES, SITEWIDE_RULES, SubredditRules

        event = Event(
            topic="report_events",
            event_type=event_type,
            request=request,
            context=context,
        )
        if reason in OLD_SITEWIDE_RULES or reason in SITEWIDE_RULES:
            process_notes = "SITE_RULES"
        else:
            if subreddit and SubredditRules.get_rule(subreddit, reason):
                process_notes = "SUBREDDIT_RULES"
            else:
                process_notes = "CUSTOM"

        event.add("process_notes", process_notes)
        event.add("details_text", details_text)

        event.add_subreddit_fields(subreddit)
        event.add_target_fields(target)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_quarantine_sample_rate")
    def quarantine_event(self, event_type, subreddit,
            request=None, context=None):
        """Create a 'quarantine' event for event-collector.

        event_type: quarantine_interstitial_view, quarantine_opt_in,
            quarantine_opt_out, quarantine_interstitial_dismiss
        subreddit: The quarantined subreddit
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = Event(
            topic="quarantine",
            event_type=event_type,
            request=request,
            context=context,
        )

        if context:
            if context.user_is_loggedin:
                event.add("verified_email", context.user.email_verified)
            else:
                event.add("verified_email", False)

        # Due to the redirect, the request object being sent isn't the
        # original, so referrer and action data is missing for certain events
        if request and (event_type == "quarantine_interstitial_view" or
                 event_type == "quarantine_opt_out"):
            request_vars = request.environ["pylons.routes_dict"]
            event.add("sr_action", request_vars.get("action", None))

            # The thing_id the user is trying to view is a comment
            if request.environ["pylons.routes_dict"].get("comment", None):
                thing_id36 = request_vars.get("comment", None)
            # The thing_id is a link
            else:
                thing_id36 = request_vars.get("article", None)

            if thing_id36:
                event.add("thing_id", int(thing_id36, 36))

        event.add_subreddit_fields(subreddit)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_modmail_sample_rate")
    def modmail_event(self, message, request=None, context=None):
        """Create a 'modmail' event for event-collector.

        message: An r2.models.Message object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """

        from r2.models import Account, Message

        sender = message.author_slow
        sr = message.subreddit_slow
        sender_is_moderator = sr.is_moderator_with_perms(sender, "mail")

        if message.first_message:
            first_message = Message._byID(message.first_message, data=True)
        else:
            first_message = message

        event = Event(
            topic="message_events",
            event_type="ss.send_message",
            time=message._date,
            request=request,
            context=context,
            data={
                # set these manually rather than allowing them to be set from
                # the request context because the loggedin user might not
                # be the message sender
                "user_id": sender._id,
                "user_name": sender.name,
            },
        )

        if sender == Account.system_user():
            sender_type = "automated"
        elif sender_is_moderator:
            sender_type = "moderator"
        else:
            sender_type = "user"

        event.add("sender_type", sender_type)
        event.add("message_id", message._id)
        event.add("message_kind", "modmail")
        event.add("message_fullname", message._fullname)
        event.add("first_message_id", first_message._id)
        event.add("first_message_fullname", first_message._fullname)

        if request and request.POST.get("source", None):
            source = request.POST["source"]
            if source in {"compose", "permalink", "modmail", "usermail"}:
                event.add("page", source)

        if message.sent_via_email:
            event.add("is_third_party", True)
            event.add("third_party_metadata", "mailgun")

        if not message.to_id:
            target = sr
        else:
            target = Account._byID(message.to_id, data=True)

        event.add_subreddit_fields(sr)
        event.add_target_fields(target)

        self.save_event(event)

    @squelch_exceptions
    def new_modmail_event(self, event_type, conversation, message=None,
                          msg_author=None, mark_type=None, sr=None,
                          request=None, context=None):
        """Create a 'new_modmail' event for the event-collector

        Events:
            - ss.modmail_mark_thread
            - ss.send_modmail_message

        This is a function that will issue all modmail events
        """
        from r2.models import (
            Account,
            Subreddit,
        )

        if not sr:
            sr = Subreddit._by_fullname(conversation.owner_fullname)

        if event_type == 'ss.send_modmail_message' and not msg_author:
            msg_author = Account._byID(message.author_id)

        event = Event(
            topic='modmail_events',
            event_type=event_type,
            request=request,
            context=context,
        )

        # Get the first message of the conversation and extract
        # all of the associated message ids
        first_message = conversation.messages[-1]
        message_listing = [msg.id for msg in conversation.messages]
        convo_author = Account._byID(first_message.author_id)

        def get_author_type(account):
            if (conversation.is_internal or
                    sr.is_moderator_with_perms(account, 'mail')):
                return 'moderator'
            elif account.name in g.live_config['modmail_admins']:
                return 'admin'
            elif conversation.is_auto:
                return 'automoderator'

            return 'user'

        event.add('conversation_id', conversation.id)
        event.add('conversation_id36', conversation.id36)
        event.add('conversation_subject', conversation.subject)
        event.add('conversation_mod_only', conversation.is_internal)
        event.add('conversation_author_id', convo_author._id)
        event.add('conversation_author_name', convo_author.name)
        event.add('conversation_author_type', get_author_type(convo_author))
        event.add('conversation_message_count', conversation.num_messages)
        event.add('conversation_is_notification', conversation.is_auto)
        event.add('conversation_created_ts',
                  to_epoch_milliseconds(first_message.date))

        event.add('message_listing', message_listing)
        event.add_subreddit_fields(sr)

        # Add event specific event data
        if event_type == 'ss.send_modmail_message':
            if not message:
                raise ValueError('Must pass the ModmailMessage object '
                                 'for the ss.send_modmail_message event')

            recipient = sr
            recipient_type = 'subreddit'
            if not conversation.is_internal:
                try:
                    participant = conversation.get_participant_account()
                    if participant:
                        recipient = participant
                        recipient_type = 'user'
                except:
                    pass

            event.add('conversation_recipient_id', recipient._id)
            event.add('conversation_recipient_type', recipient_type)
            event.add('hide_username', message.is_author_hidden)

            event.add('message_id36', message.id36)
            event.add('message_body', message.body)
            event.add('message_author_id', message.author_id)
            event.add('message_author_type', get_author_type(msg_author))
            event.add('message_mod_only', message.is_internal)
        elif event_type == 'ss.modmail_mark_thread':
            if not mark_type:
                raise ValueError('Must pass mark_type for '
                                 'ss.modmail_mark_thread event')

            event.add('target_mark_type', mark_type)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_message_sample_rate")
    def message_event(self, message, event_type="ss.send_message",
                      request=None, context=None):
        """Create a 'message' event for event-collector.

        message: An r2.models.Message object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """

        from r2.models import Account, Message

        sender = message.author_slow

        if message.first_message:
            first_message = Message._byID(message.first_message, data=True)
        else:
            first_message = message

        event = Event(
            topic="message_events",
            event_type=event_type,
            time=message._date,
            request=request,
            context=context,
            data={
                # set these manually rather than allowing them to be set from
                # the request context because the loggedin user might not
                # be the message sender
                "user_id": sender._id,
                "user_name": sender.name,
            },
        )

        if sender == Account.system_user():
            sender_type = "automated"
        else:
            sender_type = "user"

        event.add("sender_type", sender_type)
        event.add("message_kind", "message")
        event.add("message_id", message._id)
        event.add("message_fullname", message._fullname)

        event.add_text("message_body", message.body)
        event.add_text("message_subject", message.subject)

        event.add("first_message_id", first_message._id)
        event.add("first_message_fullname", first_message._fullname)

        if request and request.POST.get("source", None):
            source = request.POST["source"]
            if source in {"compose", "permalink", "usermail"}:
                event.add("page", source)

        if message.sent_via_email:
            event.add("is_third_party", True)
            event.add("third_party_metadata", "mailgun")

        target = Account._byID(message.to_id, data=True)

        event.add_target_fields(target)

        self.save_event(event)

    @sampled("events_collector_loid_sample_rate")
    def loid_event(self, loid, action_name, request=None, context=None):
        """Create a 'loid' event for event-collector.

        loid: the created/modified loid
        action_name: create_loid (only allowed value currently)
        """
        event = Event(
            topic="loid_events",
            event_type='ss.%s' % action_name,
            request=request,
            context=context,
        )
        event.add("request_url", request.fullpath)
        for k, v in loid.to_dict().iteritems():
            event.add(k, v)
        self.save_event(event)

    def login_event(self, action_name, error_msg,
                    user_name=None, email=None, captcha_shown=None,
                    remember_me=None, newsletter=None, email_verified=None,
                    signature=None, request=None, context=None):
        """Create a 'login' event for event-collector.

        action_name: login_attempt, register_attempt, password_reset
        error_msg: error message string if there was an error
        user_name: user entered username string
        email: user entered email string (register, password reset)
        remember_me:  boolean state of remember me checkbox (login, register)
        newsletter: boolean state of newsletter checkbox (register only)
        email_verified: boolean value for email verification state, requires
            email (password reset only)
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = Event(
            topic="login_events",
            event_type='ss.%s' % action_name,
            request=request,
            context=context,
        )

        if error_msg:
            event.add('successful', False)
            event.add('process_notes', error_msg)
        else:
            event.add('successful', True)

        event.add('user_name', user_name)
        event.add('email', email)
        event.add('remember_me', remember_me)
        event.add('newsletter', newsletter)
        event.add('email_verified', email_verified)
        if signature:
            event.add("signed", True)
            event.add("signature_platform", signature.platform)
            event.add("signature_version", signature.version)
            event.add("signature_valid", signature.is_valid())
            sigerror = ", ".join(
                "%s_%s" % (field, code) for code, field in signature.errors
            )
            event.add("signature_errors", sigerror)
            if signature.epoch:
                event.add("signature_age", int(time.time()) - signature.epoch)


        if context.loid:
            for k, v in context.loid.to_dict().iteritems():
                event.add(k, v)

        if captcha_shown:
            event.add('captcha_shown', captcha_shown)

        if not error_msg and context and context.user_is_loggedin:
            hooks.get_hook("eventcollector.login_event").call(
                event=event,
                user=context.user,
                request=request,
                context=context,
            )

        self.save_event(event)

    def account_recovery_event(self, user_name, base_url, new_email,
                               error_msg=None, request=None, context=None):
        """Create an 'account_recovery' event for event-collector.

        user_name: name of user who tried to recover the account
        base_url: base url where the account recovery triggered
        new_email: original email address to recover account
        error_msg: error message string if there was an error
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = Event(
            topic="account_recovery_events",
            event_type='ss.account_recovery',
            request=request,
            context=context,
        )

        if error_msg:
            event.add('successful', False)
            event.add('process_notes', error_msg)
        else:
            event.add('successful', True)

        event.add('user_name', user_name)
        event.add('new_email', new_email)
        event.add('base_url', base_url)

        self.save_event(event)

    def bucketing_event(
        self, experiment_id, experiment_name, variant, user, loid,
        request=None, context=None
    ):
        """Send an event recording an experiment bucketing.

        experiment_id: an integer representing the experiment
        experiment_name: a human-readable name representing the experiment
        variant: a string representing the variant name
        user: the Account that has been put into the variant
        """
        event = Event(
            topic='bucketing_events',
            event_type='bucket',
            request=request,
            context=context,
        )
        event.add('experiment_id', experiment_id)
        event.add('experiment_name', experiment_name)
        event.add('variant', variant)
        # if the user is logged out, we won't have a user_id or name
        if user is not None:
            event.add('user_id', user._id)
            event.add('user_name', user.name)
        if loid:
            for k, v in loid.to_dict().iteritems():
                event.add(k, v)
        if request:
            event.add('url', request.url)
        self.save_event(event)

    def subreddit_hide_ads_event(
        self, subreddit, hide_ads,
        request=None, context=None
    ):
        """Send an event recording `hide_ads` attr set on a `Subreddit`.

        subreddit: an r2.models.Subreddit object
        hide_ads: a boolean representing the hide_ads attr
        request: pylons.request of the request emitting the event
        context: pylons.tmpl_context of the request emitting the event

        """
        event = Event(
            event_topic='promote_events',
            event_type='subreddit_hide_ads',
            request=request,
            context=context,
        )

        event.add('target_fullname', subreddit._fullname)

        self.save_event(event)

    @squelch_exceptions
    def new_promoted_link_event(self, link, request=None, context=None):
        """Send an event recording a new promoted link's creation.

        link: A promoted r2.models.Link object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        if not link.promoted:
            return

        event = SelfServeEvent(
            event_type="ss.new_promoted_link",
            time=link._date,
            request=request,
            context=context,
        )

        event.add_promoted_link_fields(link)

        self.save_event(event)

    @squelch_exceptions
    def edit_promoted_link_event(self, link, changed_attributes,
            request=None, context=None):
        """Send an event recording edits to a promoted link.

        link: A promoted r2.models.Link object
        changed_attributes: A dictionary of tuples for the attributes that changed,
            the first value in the tuple being the prevous value and the second
            being the new value.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        if not link.promoted:
            return

        event = SelfServeEvent(
            event_type="ss.edit_promoted_link",
            request=request,
            context=context,
        )

        event.add_promoted_link_fields(link, changed=changed_attributes)

        self.save_event(event)

    @squelch_exceptions
    def approve_promoted_link_event(self, link, is_approved,
            reason=None, quality=None, request=None, context=None):
        """Send an event recording a promo link's approval status.

        link: A promoted r2.models.Link object
        is_approved: Boolean for if the post is accepted or rejected
        reason: Optional string specifying reason for the rejection
        quality: Quality of the link. One of (None, 'low', 'high')
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        if not link.promoted:
            return

        event = SelfServeEvent(
            event_type="ss.approve_promoted_link",
            request=request,
            context=context,
            data=dict(
                is_approved=is_approved,
                quality=quality,
            ),
        )

        event.add_promoted_link_fields(link)

        if not is_approved and reason:
            event.add("rejection_reason", reason)

        self.save_event(event)

    @squelch_exceptions
    def approve_campaign_event(self, link, campaign, is_approved, reason=None,
                               request=None, context=None):
        """Send an event recording when promo campaign's is approved.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        is_approved: Boolean for if the campaign is approved or unapproved
        rejection_reason: Optional string specifying reason for the rejection
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.approve_campaign",
            request=request,
            context=context,
            data=dict(
                is_approved=is_approved,
            ),
        )

        if not is_approved and reason:
            event.add('rejection_reason', reason)

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def new_campaign_event(self, link, campaign,
            request=None, context=None):
        """Send an event recording a new promo campaign's creation.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        if not link.promoted:
            return

        event = SelfServeEvent(
            event_type="ss.new_campaign",
            time=campaign._date,
            request=request,
            context=context,
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def edit_campaign_event(self, link, campaign, changed_attributes,
            request=None, context=None):
        """Send an event recording edits to a promo campaign.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        changed_attributes: A dictionary of tuples for the attributes that changed,
            the first value in the tuple being the prevous value and the second
            being the new value.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        if not link.promoted:
            return

        event = SelfServeEvent(
            event_type="ss.edit_campaign",
            request=request,
            context=context,
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign, changed=changed_attributes)

        self.save_event(event)

    @squelch_exceptions
    def pause_campaign_event(self, link, campaign,
            request=None, context=None):
        """Send an event recording when a campaign is paused/unpaused.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.pause_campaign",
            request=request,
            context=context,
            data=dict(
                is_paused=campaign.paused,
            ),
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def extend_campaign_event(self, link, campaign,
            request=None, context=None):
        """Send an event recording when a campaign is automatically extended.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.auto_extend_campaign",
            request=request,
            context=context,
            data=dict(
                extensions_remaining=campaign.extensions_remaining,
            ),
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def terminate_campaign_event(self, link, campaign, original_end,
            request=None, context=None):
        """Send an event recording when a campaign is terminated.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        original_end: Datetime which the campaign was originally suppose to end.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.terminate_campaign",
            request=request,
            context=context,
            data=dict(
                original_end_date=to_epoch_milliseconds(original_end),
            )
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    def delete_event(self, thing, request=None, context=None):
        """Send delete events for when a user removes their own comment
        or their own post
        """
        from r2.models import Comment, Link

        event_type = None
        event_topic = None
        if isinstance(thing, Link):
            event_topic = "submit_events"
            event_type = "ss.delete_post"
        elif isinstance(thing, Comment):
            event_topic = "comment_events"
            event_type = "ss.delete_comment"

        event = Event(
            topic=event_topic,
            event_type=event_type,
            request=request,
            context=context
        )
        event.add_target_fields(thing)

        self.save_event(event)

    @squelch_exceptions
    def delete_campaign_event(self, link, campaign,
            request=None, context=None):
        """Send an event recording when a campaign is deleted.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.delete_campaign",
            request=request,
            context=context,
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_charge_event(self, link, campaign, amount_pennies,
            is_system=True, request=None, context=None):
        """Send an event recording when a campaign payment is charged.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        amount_pennies: Transaction amount in pennies.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        is_system: Bool whether event was system triggered

        """
        event = SelfServeEvent(
            event_type='ss.campaign_payment_charged',
            request=request,
            context=context,
            data=dict(
                amount_pennies=amount_pennies,
                is_system=is_system,
            ),
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_void_event(
            self, link, campaign,
            reason, amount_pennies,
            request=None, context=None):
        """Send an event recording when a campaign payment is voided.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        reason: Why the campaign was voided
        amount_pennies: Transaction amount in pennies.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.campaign_payment_voided",
            request=request,
            context=context,
            data=dict(
                reason=reason,
                amount_pennies=amount_pennies,
            ),
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_refund_event(
            self, link, campaign,
            amount_pennies, issued_by=None, reason=None,
            request=None, context=None):
        """Send an event recording when a campaign payment is voided.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        amount_pennies: Transaction amount in pennies.
        issued_by: The user that issued the refund (None == system)
        reason: The reason the refund was issued.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.campaign_payment_refunded",
            request=request,
            context=context,
            data=dict(
                reason=reason,
                amount_pennies=amount_pennies,
            ),
        )

        is_system = issued_by is None
        event.add("is_system", is_system)

        if not is_system:
            event.add("issued_by_id", issued_by._id)
            event.add("issued_by_name", issued_by.name)

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_freebie_event(
            self, link, campaign, amount_pennies,
            transaction_id=None,
            request=None, context=None):
        """Send an event recording when a campaign is comped.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        amount_pennies: Transaction amount in pennies.
        transaction_id: Unique id of the transaction if successful.
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.campaign_freebie",
            request=request,
            context=context,
            data=dict(
                amount_pennies=amount_pennies,
                transaction_id=transaction_id,
            ),
        )

        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_attempt_event(
            self, link, campaign,
            is_new_payment_method, amount_pennies,
            payment_id=None, address=None, payment=None,
            request=None, context=None):
        """Send an event recording when a campaign payment is attempted.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        is_new_payment_method: Whether or not this is a new or
            existing payment method.
        amount_pennies: Transaction amount in pennies.
        payment_id: Unique id of payment method used (optional)
        address: An r2.lib.authorize.api.Address object
        payment: An r2.lib.authorize.api.CreditCard object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.campaign_payment_attempt",
            request=request,
            context=context,
            data=dict(
                payment_id=payment_id,
                is_new_payment_method=is_new_payment_method,
            )
        )

        event.add_payment_fields(
            payment=payment,
            address=address,
            request=request,
        )
        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_failed_event(
            self, link, campaign,
            is_new_payment_method, amount_pennies, reason,
            payment_id=None, address=None, payment=None,
            request=None, context=None):
        """Send an event recording when a campaign payment fails.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        is_new_payment_method: Whether or not this is a new or
            existing payment method.
        amount_pennies: Transaction amount in pennies.
        reason: Reason for the payment failure.
        payment_id: Unique id of payment method used (optional)
        address: An r2.lib.authorize.api.Address object
        payment: An r2.lib.authorize.api.CreditCard object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message

        """
        event = SelfServeEvent(
            event_type="ss.campaign_payment_failed",
            request=request,
            context=context,
            data=dict(
                payment_id=payment_id,
                is_new_payment_method=is_new_payment_method,
                reason=reason,
            ),
        )

        event.add_payment_fields(
            payment=payment,
            address=address,
            request=request,
        )
        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def campaign_payment_success_event(
            self, link, campaign,
            is_new_payment_method, amount_pennies, transaction_id,
            payment_id=None, address=None, payment=None, request=None,
            context=None, advertiser_industry_changed_to=None):
        """Send an event recording when a campaign payment succeeds.

        link: A promoted r2.models.Link object
        campaign: A r2.models.PromoCampaign object
        is_new_payment_method: Whether or not this is a new or
            existing payment method.
        amount_pennies: Transaction amount in pennies.
        payment_id: Unique id of payment method used (optional)
        transaction_id: Unique id of transaction (optional)
        address: An r2.lib.authorize.api.Address object
        payment: An r2.lib.authorize.api.CreditCard object
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        advertiser_industry_changed_to: Change value for Account.advertiser_industry  # noqa

        """
        event = SelfServeEvent(
            event_type="ss.campaign_payment_success",
            request=request,
            context=context,
            data=dict(
                payment_id=payment_id,
                transaction_id=transaction_id,
                is_new_payment_method=is_new_payment_method,
                advertiser_industry_changed_to=advertiser_industry_changed_to,
            ),
        )

        event.add_payment_fields(
            payment=payment,
            address=address,
            request=request,
        )
        event.add_promoted_link_fields(link)
        event.add_campaign_fields(campaign)

        self.save_event(event)

    @squelch_exceptions
    def password_update_event(self, user, base_url=None,
                              request=None, context=None):

        """Create a 'Password Update Event' for the event-collector.

        user: user that triggered above actions
        base_url: URL of the page from where the event is sent, relative
            to "reddit.com"
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        """
        event = Event(
            topic="password_update_events",
            event_type='ss.change_password',
            request=request,
            context=context,
        )

        event.add('base_url', base_url)
        event.add('user_age_seconds', user._age.total_seconds())
        event.add_target_fields(user)

        hooks.get_hook("eventcollector.password_update_event").call(
            user=user, request=request, context=context,
        )
        self.save_event(event)

    @squelch_exceptions
    def email_update_event(self, action_name, user, base_url=None,
                           dnt=None, new_email=None, request=None,
                           context=None):

        """Create an 'Email Update Event' for event-collector.

        action_name: add_email, remove_email, update_email, verify_email
        user: user that triggered above actions
        base_url: URL of the page from where the event is sent, relative
            to "reddit.com"
        dnt: do not track feature enabled or not
        new_email: the email added
        prev_email: previous email address if any
        prev_email_verified: whether previous email verified or not
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        """
        event = Event(
            topic="email_update_events",
            event_type='ss.%s' % action_name,
            request=request,
            context=context,
        )

        event.add('base_url', base_url)
        event.add('dnt', dnt)

        # if the user is adding or verifying emails
        if new_email:
            event.add('new_email', new_email)
            event.add('new_email_domain', new_email.split("@")[-1])
            event.add('new_email_tld', "." + new_email.split(".")[-1])

        # if the user is updating or removing emails
        if user.email and action_name != "verify_email":
            event.add('prev_email', user.email)
            event.add('prev_email_verified', user.email_verified)

        event.add('user_age_seconds', user._age.total_seconds())
        event.add_target_fields(user)

        hooks.get_hook("eventcollector.email_update_event").call(
            user=user,
            action_name=action_name,
            new_email=new_email,
            request=request,
            context=context,
        )
        self.save_event(event)

    @squelch_exceptions
    def subreddit_subscribe_event(self, is_subscribing, is_first_sub,
                                  subreddit, user, sub_size, request=None,
                                  context=None):
        """Create a subreddit subscribe event

        is_subscribing: whether user is suscribing or unsubscribing
        is_first_sub: whether this is the user's first time subscribing
        subreddit: subreddit object to track
        user: user that triggered above actions
        sub_size: the number of subreddits being subscribed or unsubscribed to
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        """

        event_type = 'subscribe' if is_subscribing else 'unsubscribe'

        event = Event(
            topic="subscribe_events",
            event_type="ss.%s" % event_type,
            request=request,
            context=context,
            data={
                'base_url': subreddit.path,
                'is_first_subscription': is_first_sub,
                'sr_age': subreddit._age.total_seconds() * 1000,
                'sr_id': subreddit._id,
                'sr_name': subreddit.name,
                'user_age': user._age.total_seconds() * 1000,
                'user_subscription_size': sub_size,
            },
        )

        self.save_event(event)

    @squelch_exceptions
    def orangered_email_event(self, user, messages, email_hash,
                              reply_count, newest_reply_age, oldest_reply_age,
                              request=None, context=None):
        """Create an orangered to email event

        email_hash: unique id hash of the email message being sent. built with
            a hash of the set of message_ids displayed in the email
        reply_count: count of replies included in an orangered to email
        newest_reply_age: age of the newest reply (sent as datetime,
            we coerce to milli)
        oldest_reply_age: age of the oldest reply (sent as datetime,
            we coerce to milli)
        user: user that triggered above actions
        messages: displayed messages in the email
        request: pylons.request of the request that created the message
        context: pylons.tmpl_context of the request that created the message
        """

        fullnames = []
        reply_types = defaultdict(int)

        # get fullnames for displayed messages
        for message in messages:
            fullnames.append(message['fullname'])
            key = message['message_type'].split(' ')
            key = '_'.join(key)
            reply_types[key] += 1

        reply_types = dict(reply_types)

        event = Event(
            topic="email_sending_events",
            event_type="ss.orangered_email",
            request=request,
            context=context,
            data={
                'email_address': user.email,
                'user_id': user._id,
                'user_name': user.name,
                'user_age': to_epoch_milliseconds(user._date),
                'reply_count': reply_count,
                'email_hash': email_hash,
                'newest_reply_age': to_epoch_milliseconds(newest_reply_age),
                'oldest_reply_age': to_epoch_milliseconds(oldest_reply_age),
                'reply_fullname_listing': fullnames,
                'reply_type_count': reply_types,
            }
        )

        if user.email_verified:
            event.add('email_verified', user.email_verified)

        self.save_event(event)

    def hide_link_event(self, user, link, base_url,
                        request=None, context=None):
        link_sr = link.subreddit_slow
        actor_is_moderator = bool(link_sr.is_moderator(user))

        link_author = link.author_slow
        actor_is_author = link_author._id == user._id
        target_domain = urlparse(link.url).hostname
        app_name = request.parsed_agent.app_name or request.host

        e = Event(
            topic='flatlist_events',
            event_type='ss.post_flatlist',
            request=request,
            context=context,
            data={
                'app_name': app_name,
                'base_url': base_url,
                'is_target_author': actor_is_author,
                'is_sr_moderator': actor_is_moderator,
                'process_notes': 'hide',
                'sr_id': link_sr._id,
                'sr_name': link_sr.name,
                'target_created_ts': _datetime_to_millis(link._date),
                'target_author_name': link_author.name,
                'target_fullname': link._fullname,
                'target_id': link._id,
                'target_url': link.url,
                'target_url_domain': target_domain,
                'user_id': user._id,
                'user_name': user.name,
            }
        )
        self.save_event(e)

    @squelch_exceptions
    def search_engine_crawl_event(self, req, resp, context):
        parsed_url = urlparse(req.fullurl)
        event = Event(
            topic='crawl_events',
            event_type='url_crawl',
        )

        event.add('base_url', parsed_url.path)
        event.add('http_response_code', resp.status_int)
        event.add(
            'response_time',
            int(1000 * context.request_timer.elapsed_seconds())
        )
        event.add('crawler_name', g.pool_name)
        event.add('user_agent', req.user_agent)
        event.add('server', g.reddit_host)
        event.add('method', req.method)
        event.add('domain', req.domain)
        event.add('protocol', parsed_url.scheme)
        event.add('sr_name', context.site.name)

        thing = url_to_thing(req.fullurl)
        if thing:
            # NOTE(wting|2016-09-01): If we keep adding things here, look into
            # using self.add_target_fields and fixing that to handle
            # FakeSubreddit.
            event.add('target_fullname', getattr(thing, '_fullname', None))

            type_name = getattr(thing, '_type_name', None)
            if type_name:
                event.add('target_type', type_name)
                if type_name == 'comment':
                    link = getattr(thing, 'link', thing.link_slow)
                    event.add('post_fullname', link._fullname)

            try:
                event.add(
                    'target_created_ts',
                    to_epoch_milliseconds(thing._date)
                )
            except AttributeError:
                pass

        if req.referrer:
            event.add('referrer_url', req.referrer)
            ref_url = urlparse(req.referrer)
            if ref_url.query:
                event.add('referrer_url_params', ref_url.query)

        self.save_event(event)


class Event(baseplate.events.Event):
    def __init__(self, topic, event_type,
                 time=None, uuid=None, request=None, context=None,
                 data=None, obfuscated_data=None):
        """Create a new event for event-collector.

        topic: Used to filter events into appropriate streams for processing
        event_type: Used for grouping and sub-categorizing events
        time: Should be a datetime.datetime object in UTC timezone
        uuid: Should be a UUID object
        request, context: Should be pylons.request & pylons.c respectively
        data: A dict of field names/values to initialize the payload with
        obfuscated_data: Same as `data`, but fields that need obfuscation
        """

        super(Event, self).__init__(
            topic=topic,
            event_type=event_type,
            timestamp=time,
            id=uuid,
        )

        # this happens before we ingest data/obfuscated_data so explicitly
        # passed data can override the general context data
        if request and context:
            context_data = self.get_context_data(request, context)
            for key, value in context_data.iteritems():
                self.set_field(key, value)

            sensitive_data = self.get_sensitive_context_data(request, context)
            for key, value in sensitive_data.iteritems():
                self.set_field(key, value,
                               kind=baseplate.events.FieldKind.OBFUSCATED)

        if data:
            for key, value in data.iteritems():
                self.set_field(key, value)

        if obfuscated_data:
            for key, value in obfuscated_data.iteritems():
                self.set_field(key, value,
                               kind=baseplate.events.FieldKind.OBFUSCATED)

    def add(self, key, value, kind=baseplate.events.FieldKind.NORMAL):
        self.set_field(key, value, kind=kind)

    def add_text(self, key, value, kind=baseplate.events.FieldKind.NORMAL):
        self.add(key, value, kind=kind)

        if value is None:
            return

        for k, v in charset_summary(value).iteritems():
            self.add("{}_{}".format(key, k), v)

    def add_target_fields(self, target):
        if not target:
            return
        from r2.models import Comment, Link, Message

        self.add("target_id", target._id)
        self.add("target_fullname", target._fullname)
        self.add("target_age_seconds", target._age.total_seconds())

        target_type = target.__class__.__name__.lower()
        if target_type == "link" and target.is_self:
            target_type = "self"
        self.add("target_type", target_type)

        # If the target is an Account or Subreddit (or has a "name" attr),
        # add the target_name
        if hasattr(target, "name"):
            self.add("target_name", target.name)

        # Add info about the target's author for comments, links, & messages
        if isinstance(target, (Comment, Link, Message)):
            author = target.author_slow
            if target._deleted or author._deleted:
                self.add("target_author_id", 0)
                self.add("target_author_name", "[deleted]")
            else:
                self.add("target_author_id", author._id)
                self.add("target_author_name", author.name)

        # Add info about the url being linked to for link posts
        if isinstance(target, Link):
            self.add_text("target_title", target.title)
            if not target.is_self:
                self.add("target_url", target.url)
                self.add("target_url_domain", target.link_domain())

        # Add info about the link being commented on for comments
        if isinstance(target, Comment):
            link_fullname = Link._fullname_from_id36(to36(target.link_id))
            self.add("link_id", target.link_id)
            self.add("link_fullname", link_fullname)

        # Add info about when target was originally posted for links/comments
        if isinstance(target, (Comment, Link)):
            self.add("target_created_ts", to_epoch_milliseconds(target._date))

        hooks.get_hook("eventcollector.add_target_fields").call(
            event=self,
            target=target,
        )

    def add_subreddit_fields(self, subreddit):
        if not subreddit:
            return

        self.add("sr_id", subreddit._id)
        self.add("sr_name", subreddit.name)

    @classmethod
    def get_context_data(self, request, context):
        """Extract common data from the current request and context

        This is generally done explicitly in `__init__`, but is done by hand for
        votes before the request context is lost by the queuing.

        request, context: Should be pylons.request & pylons.c respectively
        """
        data = {}

        if context.user_is_loggedin:
            data["user_id"] = context.user._id
            data["user_name"] = context.user.name
            if getattr(context.user, "user_features", None):
                data["user_features"] = context.user.user_features
        else:
            if context.loid:
                data.update(context.loid.to_dict())

        oauth2_client = getattr(context, "oauth2_client", None)
        if oauth2_client:
            data["oauth2_client_id"] = oauth2_client._id
            data["oauth2_client_name"] = oauth2_client.name
            data["oauth2_client_app_type"] = oauth2_client.app_type

        data["geoip_country"] = get_request_location(request, context)
        data["domain"] = request.host
        data["user_agent"] = request.user_agent
        if hasattr(request, "parsed_agent"):
            data["user_agent_parsed"] = request.parsed_agent.to_dict()

        http_referrer = request.headers.get("Referer", None)
        if http_referrer:
            data["referrer_url"] = http_referrer
            data["referrer_domain"] = domain(http_referrer)

        if context.init_referrer:
            data["session_referrer_domain"] = domain(context.init_referrer)

        hooks.get_hook("eventcollector.context_data").call(
            data=data,
            user=context.user,
            request=request,
            context=context,
        )

        return data

    @classmethod
    def get_sensitive_context_data(self, request, context):
        data = {}
        ip = getattr(request, "ip", None)
        if ip:
            data["client_ip"] = ip
            # since we obfuscate IP addresses in the DS pipeline, we can't
            # extract the subnet for analysis after this step. So, pre-generate
            # (and separately obfuscate) the subnets.
            if "." in ip:
                octets = ip.split(".")
                data["client_ipv4_24"] = ".".join(octets[:3])
                data["client_ipv4_16"] = ".".join(octets[:2])

        return data


class SelfServeEvent(Event):
    def __init__(self, event_type, **kwargs):
        super(SelfServeEvent, self).__init__(
            topic="selfserve_events",
            event_type=event_type,
            **kwargs
        )

    def add_payment_fields(self, payment, address, request=None):
        if request:
            location = location_by_ips(request.ip)
            if location:
                self.add("geoip_region", location.get("region_name"))

        if not (payment and address):
            return

        card_number = getattr(payment, "cardNumber", None)

        if card_number is None:
            return

        self.add("payment_card_last4", card_number[-4:],
                 kind=baseplate.events.FieldKind.OBFUSCATED)
        self.add("payment_card_expiry", payment.expirationDate,
                 kind=baseplate.events.FieldKind.OBFUSCATED)
        self.add("payment_postal_code", address.zip)

    def add_promoted_link_fields(self, link, changed=None):
        if not link.promoted:
            return

        from r2.lib import media
        from r2.models.promo import PROMOTE_STATUS

        author = link.author_slow

        self.add("link_id", link._id)
        self.add("link_fullname", link._fullname)
        self.add("title", link.title)
        self.add("author_id", author._id)
        self.add("author_neutered", author._spam)
        self.add("author_email_verified", author.email_verified)
        self.add("is_managed", link.managed_promo)
        self.add("moat_tracking", link.moat_tracking)
        self.add("promote_status", PROMOTE_STATUS.name[link.promote_status])

        if link.is_self:
            self.truncatable_field = "post_body"
            self.add("post_type", "self")
            self.add_text("post_body", link.selftext)
        else:
            self.add("post_type", "link")
            self.add("target_url", link.url)
            self.add("target_domain", domain(link.url))

        self.add("thumbnail_url", media.thumbnail_url(link))
        self.add("mobile_card_url", media.mobile_ad_url(link))
        self.add("domain_override", link.domain_override)
        self.add("third_party_tracking", link.third_party_tracking)
        self.add("third_party_tracking_2", link.third_party_tracking_2)

        if changed is not None:
            prev_attrs = {key: prev
                for key, (prev, current) in changed.iteritems()}
            self.add_text("prev_title", prev_attrs.get("title"))
            self.add("prev_is_managed", prev_attrs.get("managed_promo"))
            self.add("prev_moat_tracking", prev_attrs.get("moat_tracking"))

            is_self = prev_attrs.get("is_self", link.is_self)

            if "is_self" in prev_attrs:
                self.add("prev_post_type", "self" if is_self else "link")

            if is_self:
                self.add_text("prev_post_body", prev_attrs.get("selftext"))
            elif "url" in prev_attrs:
                url = prev_attrs["url"]
                self.add("prev_target_url", url)
                self.add("prev_target_domain", domain(url))

            self.add("prev_thumbnail_url", prev_attrs.get("thumbnail_url"))
            self.add("prev_mobile_card_url", prev_attrs.get("mobile_ad_url"))
            self.add("prev_domain_override",
                prev_attrs.get("domain_override"))
            self.add("prev_third_party_tracking",
                prev_attrs.get("third_party_tracking"))
            self.add("prev_third_party_tracking_2",
                prev_attrs.get("third_party_tracking_2"))

            prev_promote_status = prev_attrs.get("promote_status")
            if prev_promote_status is not None:
                self.add("prev_promote_status",
                    PROMOTE_STATUS.name[prev_promote_status])

    def add_campaign_fields(self, campaign, changed=None):
        from r2.lib import promote
        from r2.models.promo import PROMOTE_COST_BASIS

        self.add("campaign_id", campaign._id)
        self.add("start_date_ts", to_epoch_milliseconds(campaign.start_date))
        self.add("end_date_ts", to_epoch_milliseconds(campaign.end_date))
        self.add("target_name", campaign.target.pretty_name)
        self.add("subreddit_targets", campaign.target.subreddit_names)
        self.add("no_daily_budget", campaign.no_daily_budget)
        self.add("total_budget_pennies", campaign.total_budget_pennies)
        self.add("spent_budget_pennies", int(promote.get_spent_amount(campaign) * 100))
        self.add("priority", campaign.priority_name)
        self.add("cost_basis", PROMOTE_COST_BASIS.name[campaign.cost_basis])
        self.add("platform", campaign.platform)
        self.add("auto_extend", campaign.auto_extend)

        self.add_location_fields(campaign.location)

        if campaign.cost_basis != PROMOTE_COST_BASIS.fixed_cpm:
            self.add("bid_pennies", campaign.bid_pennies)

        self.add("frequency_cap", campaign.frequency_cap)
        self.add("mobile_os_names", campaign.mobile_os)
        self.add("ios_device_types", campaign.ios_devices)
        self.add("android_device_types", campaign.android_devices)

        if campaign.ios_version_range is not None:
            self.add("ios_version_range",
                "-".join(campaign.ios_version_range))
        if campaign.android_version_range is not None:
            self.add("android_version_range",
                "-".join(campaign.android_version_range))

        if changed is not None:
            prev_attrs = {key: prev
                for key, (prev, current) in changed.iteritems()}

            prev_start_date = prev_attrs.get("start_date")
            if prev_start_date is not None:
                self.add(
                    "prev_start_date_ts",
                    to_epoch_milliseconds(prev_start_date)
                )
            prev_end_date = prev_attrs.get("end_date")
            if prev_end_date is not None:
                self.add(
                    "prev_end_date_ts",
                    to_epoch_milliseconds(prev_end_date)
                )

            prev_target = prev_attrs.get("target")
            if prev_target:
                self.add("prev_target_name", prev_target.pretty_name)
                self.add("prev_subreddit_targets", prev_target.subreddit_names)

            self.add_location_fields(
                prev_attrs.get("location"),
                prefix="prev_",
            )

            self.add("prev_no_daily_budget",
                prev_attrs.get("no_daily_budget"))
            self.add("prev_total_budget_pennies",
                prev_attrs.get("total_budget_pennies"))
            self.add("prev_priority",
                prev_attrs.get("priority_name"))
            self.add("prev_platform", prev_attrs.get("platform"))
            self.add("prev_auto_extend", prev_attrs.get("auto_extend"))

            prev_cost_basis = prev_attrs.get("cost_basis")
            if prev_cost_basis is not None:
                self.add("prev_cost_basis",
                    PROMOTE_COST_BASIS.name[prev_cost_basis])
                if prev_cost_basis != PROMOTE_COST_BASIS.fixed_cpm:
                    self.add("prev_bid_pennies", prev_attrs.get("bid_pennies"))

            self.add("prev_frequency_cap", prev_attrs.get("frequency_cap"))
            self.add("prev_mobile_os_names", prev_attrs.get("mobile_os"))
            self.add("prev_ios_device_types", prev_attrs.get("ios_devices"))
            self.add("prev_android_device_types",
                prev_attrs.get("android_devices"))

            prev_ios_version_range = prev_attrs.get("ios_version_range")
            if prev_ios_version_range is not None:
                self.add("ios_version_range",
                    "-".join(prev_ios_version_range))

            prev_android_version_range = prev_attrs.get("android_version_range")
            if prev_android_version_range is not None:
                self.add("android_version_range",
                    "-".join(prev_android_version_range))

    def add_location_fields(self, location, prefix=""):
        if location is None:
            return

        fields = ["country", "region", "metro"]

        if not location.country:
            return

        from r2.models.promo import Location

        self.add(
            prefix + "country_targets",
            [Location.DELIMITER.join(
                getattr(location, f, "") for f in fields[:1])],
        )

        if not location.region:
            return

        self.add(
            prefix + "region_targets",
            [Location.DELIMITER.join(
                getattr(location, f, "") for f in fields[:2])],
        )

        if not location.metro:
            return

        self.add(
            prefix + "metro_targets",
            [Location.DELIMITER.join(
                getattr(location, f, "") for f in fields[:3])],
        )
