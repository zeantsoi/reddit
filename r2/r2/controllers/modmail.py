from datetime import datetime
import simplejson
from pylons import app_globals as g
from pylons import request, response
from pylons import tmpl_context as c

from r2.config import feature
from r2.controllers.reddit_base import OAuth2OnlyController
from r2.controllers.oauth2 import require_oauth2_scope
from r2.lib.base import abort
from r2.lib.db import queries
from r2.lib.db.thing import NotFound
from r2.lib.errors import errors
from r2.lib.utils import tup
from r2.lib.validator import (
    VAccountByName,
    validate,
    VBoolean,
    VInt,
    VLength,
    VList,
    VMarkdownLength,
    VModConversation,
    VModConvoRecipient,
    VNotInTimeout,
    VOneOf,
    VSRByName,
    VSRByNames,
)
from r2.models import (
    Account,
    Comment,
    Link,
    Message,
    Subreddit,
    Thing,
)
from r2.models.modmail import (
    ModmailConversation,
    ModmailConversationAction,
    ModmailConversationParticipant,
    ModmailConversationUnreadState,
    MustBeAModError,
    Session,
)


class ModmailController(OAuth2OnlyController):

    def pre(self):
        # Set user_is_admin property on context,
        # normally set but this controller does not inherit
        # from RedditController
        c.user_is_admin = False
        if c.user_is_loggedin:
            c.user_is_admin = c.user.name in g.admins

        super(ModmailController, self).pre()
        VNotInTimeout().run()

    def post(self):
        Session.remove()
        super(ModmailController, self).post()

    # TODO: Figure out what scope is required for these
    # for now just defaulting to a logged in user
    @require_oauth2_scope('identity')
    @validate(
        srs=VSRByNames('entity', required=False),
        after=VModConversation('after', required=False),
        limit=VInt('limit', num_default=25),
        sort=VOneOf('sort', options=('recent', 'mod', 'user'),
                    default='recent'),
        state=VOneOf('state',
                     options=('new', 'inprogress', 'mod',
                              'notifications', 'archived',
                              'highlighted', 'all'),
                     default='all'),
    )
    def GET_conversations(self, srs, after, limit, sort, state):
        """Get conversations for logged in user or subreddits

        Querystring Params:
        entity   -- name of the subreddit or a comma separated list of
                    subreddit names (i.e. iama, pics etc)
        limit    -- number of elements to retrieve (default: 25)
        after    -- the id of the last item seen
        sort     -- parameter on how to sort the results, choices:
                    recent: max(last_user_update, last_mod_update)
                    mod: last_mod_update
                    user: last_user_update
        state    -- this parameter lets users filter messages by state
                    choices: new, inprogress, mod, notifications,
                    archived, highlighted, all
        """

        # Retrieve subreddits in question, if entities are passed
        # check if a user is a moderator for the passed entities.
        # If no entities are passed grab all subreddits the logged in
        # user moderates and has modmail permissions for
        modded_entities = {}
        modded_srs = c.user.moderated_subreddits('mail')
        modded_srs = {sr._fullname: sr for sr in modded_srs}

        if srs:
            for sr in srs.values():
                if sr._fullname in modded_srs:
                    modded_entities[sr._fullname] = sr
                else:
                    abort(403, 'Invalid entity passed.')
        else:
            modded_entities = modded_srs

        if not modded_entities:
            abort(404, 'Entities not found')

        # Retrieve conversations for given entities
        conversations = ModmailConversation.get_mod_conversations(
            modded_entities.values(), viewer=c.user,
            limit=limit, after=after, sort=sort, state=state)

        conversation_ids = []
        conversations_dict = {}
        messages_dict = {}
        author_ids = []

        # Extract author ids to query for all accounts at once
        for conversation in conversations:
            author_ids.extend(conversation.author_ids)
            author_ids.extend(conversation.mod_action_account_ids)

        # Query for associated account object of authors and serialize the
        # conversation in the correct context
        authors = self._try_get_byID(author_ids, Account, ignore_missing=True)
        for conversation in conversations:
            conversation_ids.append(conversation.id36)

            conversations_dict[conversation.id36] = conversation.to_serializable(
                authors,
                modded_entities[conversation.owner_fullname],
            )

            latest_message = conversation.messages[0]
            messages_dict[latest_message.id36] = latest_message.to_serializable(
               modded_entities[conversation.owner_fullname],
               authors[latest_message.author_id],
               c.user,
            )

        return simplejson.dumps({
            'viewerId': c.user._fullname,
            'conversationIds': conversation_ids,
            'conversations': conversations_dict,
            'messages': messages_dict,
        })

    @require_oauth2_scope('identity')
    @validate(
        entity=VSRByName('srName'),
        subject=VLength('subject', max_length=100),
        body=VMarkdownLength('body'),
        is_author_hidden=VBoolean('isAuthorHidden', default=False),
        to=VModConvoRecipient('to', required=False),
    )
    def POST_conversations(self, entity, subject, body,
                           is_author_hidden, to):
        """Creates a new conversation for a particular SR

        This endpoint will create a ModmailConversation object as
        well as the first ModmailMessage within the ModmailConversation
        object.

        POST Params:
        srName          -- the human readable name of the subreddit
        subject         -- the subject of the first message in the conversation
        body            -- the body of the first message in the conversation
        isAuthorHidden  -- boolean on whether the mod name should be hidden
                           (only mods can use this flag)
        to              -- name of the user that a mod wants to create a convo
                           with (only mods can use this flag)
        """
        self._feature_enabled_check(entity)

        # make sure the user is not muted when creating a new conversation
        if entity.is_muted(c.user) and not c.user_is_admin:
            abort(403, 'User muted for subreddit')

        # validate post params
        if (errors.USER_BLOCKED, to) in c.errors:
            # empty return to not give away that a user was banned
            return
        elif (errors.USER_DOESNT_EXIST, to) in c.errors:
            return abort(404, 'Recipient user not found')

        # only mods can set a 'to' parameter
        if (not entity.is_moderator_with_perms(c.user, 'mail') and to):
            abort(403, 'Cannot set a convo recipient if you are a non mod')

        try:
            conversation = ModmailConversation(
                entity,
                c.user,
                subject,
                body,
                is_author_hidden=is_author_hidden,
                to=to,
            )
        except MustBeAModError:
            abort(403, 'Must be a mod to hide the message author.')
        except:
            abort(500, 'Failed to save conversation')

        # Create copy of the message in the legacy messaging system as well
        if to:
            message, inbox_rel = Message._new(
                c.user,
                to,
                subject,
                body,
                request.ip,
                sr=entity,
                from_sr=is_author_hidden,
            )
        else:
            message, inbox_rel = Message._new(
                c.user,
                entity,
                subject,
                body,
                request.ip,
            )
        queries.new_message(message, inbox_rel)
        conversation.set_legacy_first_message_id(message._id)

        # Get author associated account object for serialization
        # of the newly created conversation object
        authors = self._try_get_byID(conversation.author_ids, Account,
                                     ignore_missing=True)

        response.status_code = 201
        serializable_convo = conversation.to_serializable(
                authors, entity, all_messages=True, current_user=c.user)
        messages = serializable_convo.pop('messages')
        mod_actions = serializable_convo.pop('modActions')

        return simplejson.dumps({
            'conversation': serializable_convo,
            'messages': messages,
            'modActions': mod_actions,
        })

    @require_oauth2_scope('identity')
    @validate(
        conversation=VModConversation('conversation_id'),
        mark_read=VBoolean('markRead', default=False),
    )
    def GET_mod_messages(self, conversation, mark_read):
        """Returns all messages for a given conversation id

        Url Params:
        conversation_id -- this is the id of the conversation you would
                           like to grab messages for

        Querystring Param:
        markRead -- if passed the conversation will be marked read when the
                    conversation is returned
        """
        self._validate_vmodconversation()

        sr = self._try_get_subreddit_access(conversation, admin_override=True)
        authors = self._try_get_byID(
            list(
                set(conversation.author_ids) |
                set(conversation.mod_action_account_ids)
            ),
            Account,
            ignore_missing=True
        )
        serializable_convo = conversation.to_serializable(
                authors, sr, all_messages=True, current_user=c.user)

        messages = serializable_convo.pop('messages')
        mod_actions = serializable_convo.pop('modActions')

        # Get participant user info for conversation
        try:
            userinfo = self._get_modmail_userinfo(conversation, sr=sr)
        except ValueError:
            userinfo = {}
        except NotFound as e:
            abort(400, str(e))

        if mark_read:
            conversation.mark_read(c.user)

        return simplejson.dumps({
            'conversation': serializable_convo,
            'messages': messages,
            'modActions': mod_actions,
            'user': userinfo,
        })

    @require_oauth2_scope('identity')
    def GET_modmail_enabled_srs(self):
        # sr_name, sr_icon, subsriber_count, most_recent_action
        modded_srs = c.user.moderated_subreddits('mail')
        enabled_srs = [modded_sr for modded_sr in modded_srs
                       if feature.is_enabled('new_modmail',
                                             subreddit=modded_sr.name)]
        recent_convos = ModmailConversation.get_recent_convo_by_sr(enabled_srs)

        results = {}
        for sr in enabled_srs:
            results.update({
                sr._fullname: {
                    'id': sr._fullname,
                    'name': sr.name,
                    'icon': sr.icon_img,
                    'subscribers': sr._ups,
                    'lastUpdated': recent_convos.get(sr._fullname),
                }
            })

        return simplejson.dumps({'subreddits': results})

    @require_oauth2_scope('identity')
    @validate(
        conversation=VModConversation('conversation_id'),
        msg_body=VMarkdownLength('body'),
        is_author_hidden=VBoolean('isAuthorHidden', default=False),
        is_internal=VBoolean('isInternal', default=False),
    )
    def POST_mod_messages(self, conversation, msg_body,
                          is_author_hidden, is_internal):
        """Creates a new message for a particular ModmailConversation

        URL Params:
        conversation_id -- id of the conversation to post a new message to

        POST Params:
        body            -- this is the message body
        isAuthorHidden  -- boolean on whether to hide author, i.e. respond as
                           the subreddit
        isInternal      -- boolean to signify a moderator only message
        """
        self._validate_vmodconversation()

        sr = Subreddit._by_fullname(conversation.owner_fullname)
        self._feature_enabled_check(sr)

        # make sure the user is not muted before posting a message
        if sr.is_muted(c.user):
            abort(403, 'User muted for subreddit')

        if conversation.is_internal and not is_internal:
            is_internal = True

        is_mod = sr.is_moderator(c.user)
        if not is_mod and is_author_hidden:
            abort(422, 'Must be a mod to hide the author.')
        elif not is_mod and is_internal:
            abort(422, 'Must be a mod to make the message internal.')

        try:
            conversation.add_message(
                c.user,
                msg_body,
                is_author_hidden=is_author_hidden,
                is_internal=is_internal,
            )
        except Exception:
            abort(500, 'Failed to save message')

        # Add the message to the legacy messaging system as well (unless it's
        # an internal message on a non-internal conversation, since we have no
        # way to hide specific messages from the external participant)
        legacy_incompatible = is_internal and not conversation.is_internal
        if (conversation.legacy_first_message_id and
                not legacy_incompatible):
            first_message = Message._byID(conversation.legacy_first_message_id)
            subject = conversation.subject
            if not subject.startswith('re: '):
                subject = 're: ' + subject

            # Retrieve the participant to decide whether to send the message
            # to the sr or to the participant. If the currently logged in user
            # is the same as the participant then address the message to the
            # sr.
            recipient = sr
            if not is_internal:
                participant = ModmailConversationParticipant.get_participant(
                    conversation.id
                )

                is_participant = (
                    (c.user._id == participant.account_id) and
                    not sr.is_moderator_with_perms(c.user, 'mail')
                )

                if not is_participant:
                    recipient = Account._byID(participant.account_id)

            message, inbox_rel = Message._new(
                c.user,
                recipient,
                subject,
                msg_body,
                request.ip,
                parent=first_message,
                from_sr=is_author_hidden,
            )
            queries.new_message(message, inbox_rel)

        serializable_convo = conversation.to_serializable(
            entity=sr,
            all_messages=True,
            current_user=c.user,
        )
        messages = serializable_convo.pop('messages')

        response.status_code = 201
        return simplejson.dumps({
            'conversation': serializable_convo,
            'messages': messages,
        })

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def POST_highlight(self, conversation):
        """Marks a conversation as highlighted."""
        self._validate_vmodconversation()
        self._try_get_subreddit_access(conversation)
        conversation.add_action(c.user, 'highlighted')
        conversation.add_highlight()

        # Retrieve updated conversation to be returned
        updated_convo = self._get_updated_convo(conversation.id, c.user)

        return simplejson.dumps(updated_convo)

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def DELETE_highlight(self, conversation):
        """Removes a highlight from a conversation."""
        self._validate_vmodconversation()
        self._try_get_subreddit_access(conversation)
        conversation.add_action(c.user, 'unhighlighted')
        conversation.remove_highlight()

        # Retrieve updated conversation to be returned
        updated_convo = self._get_updated_convo(conversation.id, c.user)

        return simplejson.dumps(updated_convo)

    @require_oauth2_scope('identity')
    @validate(ids=VList('conversation_ids'))
    def POST_unread(self, ids):
        """Marks conversations as unread for the user.

        Expects a list of conversation IDs.
        """
        if not ids:
            abort(400, 'Must pass an id or list of ids.')

        try:
            ids = [int(id, base=36) for id in ids]
        except:
            abort(422, 'Must pass base 36 ids.')

        try:
            convos = self._get_conversation_access(ids)
        except ValueError:
            abort(403, 'Invalid conversation id(s).')

        ModmailConversationUnreadState.mark_unread(
                c.user, [convo.id for convo in convos])

    @require_oauth2_scope('identity')
    @validate(ids=VList('conversation_ids'))
    def POST_read(self, ids):
        """Marks a conversations as read for the user.

        Expects a list of conversation IDs.
        """
        if not ids:
            abort(400, 'Must pass an id or list of ids.')

        try:
            ids = [int(id, base=36) for id in ids]
        except:
            abort(422, 'Must pass base 36 ids.')

        try:
            convos = self._get_conversation_access(ids)
        except ValueError:
            abort(403, 'Invalid conversation id(s).')

        response.status_code = 204
        ModmailConversationUnreadState.mark_read(
                c.user, [convo.id for convo in convos])

    @require_oauth2_scope('identity')
    @validate(
        ids=VList('conversation_ids'),
        archive=VBoolean('archive', default=True),
    )
    def POST_archive_status(self, ids, archive):
        try:
            convos = self._get_conversation_access(
                [int(id, base=36) for id in ids]
            )
        except ValueError:
            abort(403, 'Invalid conversation id passed.')

        convo_ids = []
        for convo in convos:
            if convo.is_internal:
                abort(422, 'Cannot archive/unarchive mod discussions.')
            convo_ids.append(convo.id)

        if not archive:
            ModmailConversation.set_states(
                convo_ids,
                ModmailConversation.STATE['inprogress'])
        else:
            ModmailConversation.set_states(
                convo_ids,
                ModmailConversation.STATE['archived'])

        response.status_code = 204

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def POST_archive(self, conversation):
        self._validate_vmodconversation()
        sr = Subreddit._by_fullname(conversation.owner_fullname)
        self._feature_enabled_check(sr)

        if sr.is_moderator_with_perms(c.user, 'mail'):
            if conversation.state == ModmailConversation.STATE['archived']:
                response.status_code = 204
                return

            if conversation.is_internal:
                abort(422, 'Cannot archive/unarchive mod discussions.')

            conversation.add_action(c.user, 'archived')
            conversation.set_state('archived')
            updated_convo = self._get_updated_convo(conversation.id, c.user)
            return simplejson.dumps(updated_convo)
        else:
            abort(403, 'Must be a moderator with mail access.')

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def POST_unarchive(self, conversation):
        self._validate_vmodconversation()
        sr = Subreddit._by_fullname(conversation.owner_fullname)
        self._feature_enabled_check(sr)

        if sr.is_moderator_with_perms(c.user, 'mail'):
            if conversation.state != ModmailConversation.STATE['archived']:
                response.status_code = 204
                return

            if conversation.is_internal:
                abort(422, 'Cannot archive/unarchive mod discussions.')

            conversation.add_action(c.user, 'unarchived')
            conversation.set_state('inprogress')
            updated_convo = self._get_updated_convo(conversation.id, c.user)
            return simplejson.dumps(updated_convo)
        else:
            abort(403, 'Must be a moderator with mail access.')

    @require_oauth2_scope('identity')
    def GET_unread_convo_count(self):
        """Endpoint to retrieve the unread conversation count by
        category"""

        convo_counts = ModmailConversation.unread_convo_count(c.user)
        return simplejson.dumps(convo_counts)

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def GET_modmail_userinfo(self, conversation):
        # validate that the currently logged in user is a mod
        # of the subreddit associated with the conversation
        self._try_get_subreddit_access(conversation, admin_override=True)
        try:
            userinfo = self._get_modmail_userinfo(conversation)
        except (ValueError, NotFound) as e:
            abort(400, str(e))

        return simplejson.dumps(userinfo)

    def _get_modmail_userinfo(self, conversation, sr=None):
        if conversation.is_internal:
            raise ValueError('Cannot get userinfo for internal conversations')

        if not sr:
            sr = Subreddit._by_fullname(conversation.owner_fullname)

        # Retrieve the participant associated with the conversation
        try:
            participant = ModmailConversationParticipant.get_participant(
                    conversation.id)
            account = Account._byID(participant.account_id)

            permatimeout = (account.in_timeout and
                            account.days_remaining_in_timeout == 0)

            if account._deleted or permatimeout:
                raise ValueError('User info is inaccessible')
        except NotFound:
            raise NotFound('Unable to retrieve conversation participant')

        # Fetch the mute and ban status of the participant as it relates
        # to the subreddit associated with the conversation. Also retrieve
        # the users link and comment karma associated with the subreddit.
        mute_status = sr.is_muted(account)
        ban_status = sr.is_banned(account)

        # Display karma for only users that have not been shadow banned
        post_karma = None
        comment_karma = None
        if not account._spam:
            post_karma = account.karma('link', sr)
            comment_karma = account.karma('comment', sr)

        # Parse the ban status and retrieve the length of the ban,
        # then output the data into a serialiazable dict
        ban_result = {
            'isBanned': bool(ban_status),
            'reason': '',
            'endDate': None,
            'isPermanent': False
        }

        if ban_status:
            ban_result['reason'] = ban_status.note

            ban_duration = sr.get_tempbans('banned', account.name)
            ban_duration = ban_duration.get(account.name)

            if ban_duration:
                ban_result['endDate'] = ban_duration.isoformat()
            else:
                ban_result['isPermanent'] = True
                ban_result['endDate'] = None

        # Parse the mute status and retrieve the length of the ban,
        # then output the data into the serialiazable dict
        mute_result = {
            'isMuted': bool(mute_status),
            'endDate': None,
            'reason': ''
        }

        if mute_status:
            mute_result['reason'] = mute_status.note

            muted_items = sr.get_muted_items(account.name)
            mute_duration = muted_items.get(account.name)
            if mute_duration:
                mute_result['endDate'] = mute_duration.isoformat()

        # Retrieve the participants post and comment fullnames from cache
        post_fullnames = []
        comment_fullnames = []
        if not account._spam:
            post_fullnames = list(
                queries.get_submitted(account, 'new', 'all')
            )[:100]

            comment_fullnames = list(
                queries.get_comments(account, 'new', 'all')
            )[:100]

        # Retrieve the associated link objects for posts and comments
        # using the retrieve fullnames, afer the link objects are retrieved
        # create a serializable dict with the the necessary information from
        # the endpoint.
        lookup_fullnames = list(
            set(post_fullnames) | set(comment_fullnames)
        )
        posts = Thing._by_fullname(lookup_fullnames)

        serializable_posts = {}
        for fullname in post_fullnames:
            if len(serializable_posts) == 3:
                break

            post = posts[fullname]
            if post.sr_id == sr._id and not post._deleted:
                serializable_posts[fullname] = {
                    'title': post.title,
                    'permalink': post.make_permalink(
                        sr,
                        force_domain=True
                    ),
                    'date': post._date.isoformat(),
                }

        # Extract the users most recent comments associated with the
        # subreddit
        sr_comments = []
        for fullname in comment_fullnames:
            if len(sr_comments) == 3:
                break

            comment = posts[fullname]
            if comment.sr_id == sr._id and not comment._deleted:
                sr_comments.append(comment)

        # Retrieve all associated link objects (combines lookup)
        comment_links = Link._byID([
            sr_comment.link_id
            for sr_comment in sr_comments
        ])

        # Serialize all of the user's sr comments
        serializable_comments = {}
        for sr_comment in sr_comments:
            comment_link = comment_links[sr_comment.link_id]
            serializable_comments[sr_comment._fullname] = {
                'title': comment_link.title,
                'permalink': sr_comment.make_permalink(
                    comment_link,
                    sr,
                    force_domain=True
                ),
                'date': sr_comment._date.isoformat(),
            }

        return {
            'id': account._fullname,
            'created': account._date.isoformat(),
            'banStatus': ban_result,
            'isShadowBanned': account._spam,
            'subredditKarma': {
                'post': post_karma,
                'comment': comment_karma,
            },
            'muteStatus': mute_result,
            'recentComments': serializable_comments,
            'recentPosts': serializable_posts,
        }

    def _get_updated_convo(self, convo_id, user):
        # Retrieve updated conversation to be returned
        updated_convo = ModmailConversation._byID(
            convo_id,
            current_user=user
        ).to_serializable(all_messages=True, current_user=c.user)
        messages = updated_convo.pop('messages')
        mod_actions = updated_convo.pop('modActions')

        return {
            'conversations': updated_convo,
            'messages': messages,
            'modActions': mod_actions,
        }

    def _validate_vmodconversation(self):
        if (errors.CONVERSATION_NOT_FOUND, 'conversation_id') in c.errors:
            abort(404, errors.CONVERSATION_NOT_FOUND)

    def _get_conversation_access(self, ids):
        validated_convos = []
        conversations = ModmailConversation._byID(ids)

        # fetch all srs that a user has modmail permissions to
        # transform sr to be a dict with a key being the sr fullname
        # and the value being the sr object itself
        modded_srs = c.user.moderated_subreddits('mail')
        sr_by_fullname = {
            sr._fullname: sr for sr in modded_srs
            if feature.is_enabled('new_modmail', subreddit=sr.name)
        }

        for conversation in tup(conversations):
            if sr_by_fullname.get(conversation.owner_fullname):
                validated_convos.append(conversation)
            else:
                raise ValueError('Invalid conversation id(s).')

        return validated_convos

    def _try_get_byID(self, ids, thing_class, return_dict=True,
                      ignore_missing=False):
        """Helper method to lookup objects by id for a
        given model or return a 404 if not found"""

        try:
            return thing_class._byID(ids, return_dict=return_dict,
                                     ignore_missing=ignore_missing)
        except NotFound:
            abort(404, '{} not found'.format(thing_class.__name__))
        except:
            abort(422, 'Invalid request')

    def _try_get_subreddit_access(self, conversation, admin_override=False):
        sr = Subreddit._by_fullname(conversation.owner_fullname)
        self._feature_enabled_check(sr)

        if (not sr.is_moderator_with_perms(c.user, 'mail') and
                not (admin_override and not c.user_is_admin)):
            abort(403)

        return sr

    def _feature_enabled_check(self, sr):
        if not feature.is_enabled('new_modmail', subreddit=sr.name):
            abort(403, 'Feature not enabled for the passed Subreddit.')
