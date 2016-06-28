import simplejson
from pylons import response
from pylons import tmpl_context as c

from r2.config import feature
from r2.controllers.reddit_base import OAuth2OnlyController
from r2.controllers.oauth2 import require_oauth2_scope
from r2.lib.base import abort
from r2.lib.db.thing import NotFound
from r2.lib.errors import errors
from r2.lib.validator import (
    validate,
    VBoolean,
    VInt,
    VLength,
    VList,
    VMarkdownLength,
    VModConversation,
    VNotInTimeout,
    VOneOf,
    VSRByName,
    VSRByNames,
)
from r2.models.modmail import (
    ModmailConversation,
    ModmailConversationAction,
    ModmailConversationUnreadState,
    MustBeAModError,
    Session,
)
from r2.models.subreddit import Subreddit
from r2.models.account import Account


class ModmailController(OAuth2OnlyController):

    def pre(self):
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
                              'notification', 'archived', 'all'),
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
                    choices: new, inprogress, mod,
                    notification, archived, all
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
            conversation_ids.append(conversation.id)

            conversations_dict[conversation.id] = conversation.to_serializable(
                authors,
                modded_entities[conversation.owner_fullname],
            )

            latest_message = conversation.messages[0]
            messages_dict[latest_message.id] = latest_message.to_serializable(
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
    )
    def POST_conversations(self, entity, subject, body,
                           is_author_hidden):
        """Creates a new conversation for a particular SR

        This endpoint will create a ModmailConversation object as
        well as the first ModmailMessage within the ModmailConversation
        object.

        POST Params:
        srName      -- the human readable name of the subreddit
        subject     -- the subject of the first message in the conversation
        body        -- the body of the first message in the conversation

        """
        self._feature_enabled_check(entity)

        try:
            conversation = ModmailConversation(
                entity,
                c.user,
                subject,
                body,
                is_author_hidden=is_author_hidden,
            )
        except MustBeAModError:
            abort(403, 'Must be a mod to hide the message author.')
        except:
            abort(500, 'Failed to save conversation')

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

        sr = self._try_get_subreddit_access(conversation)
        authors = self._try_get_byID(conversation.author_ids, Account,
                                     ignore_missing=True)
        serializable_convo = conversation.to_serializable(
                authors, sr, all_messages=True, current_user=c.user)

        messages = serializable_convo.pop('messages')
        mod_actions = serializable_convo.pop('modActions')

        if mark_read:
            conversation.mark_read(c.user)

        return simplejson.dumps({
            'conversation': serializable_convo,
            'messages': messages,
            'modActions': mod_actions,
        })

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

        serializable_convo = conversation.to_serializable(
                entity=sr, all_messages=True,
                current_user=c.user)
        messages = serializable_convo.pop('messages')

        response.status_code = 201
        return simplejson.dumps({
            'conversation': serializable_convo,
            'messages': messages,
        })

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def POST_star(self, conversation):
        """Marks a conversation as having a star."""
        self._validate_vmodconversation()
        self._try_get_subreddit_access(conversation)
        conversation.add_star()
        conversation.add_action(c.user, 'marked_important')
        response.status_code = 204

    @require_oauth2_scope('identity')
    @validate(conversation=VModConversation('conversation_id'))
    def DELETE_star(self, conversation):
        """Removes a star from a conversation."""
        self._validate_vmodconversation()
        self._try_get_subreddit_access(conversation)
        conversation.remove_star()
        conversation.add_action(c.user, 'unmarked_important')
        response.status_code = 204

    @require_oauth2_scope('identity')
    @validate(ids=VList('conversation_ids'))
    def POST_unread(self, ids):
        """Marks conversations as unread for the user.

        Expects a list of conversation IDs.
        """
        if not ids:
            abort(400, 'Must pass an id or list of ids.')

        try:
            ids = [int(id) for id in ids]
        except:
            abort(422, 'Must pass int ids.')

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
            ids = [int(id) for id in ids]
        except:
            abort(422, 'Must pass int ids.')

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
            convos = self._get_conversation_access(ids)
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

            conversation.set_state('archived')
            conversation.add_action(c.user, 'archived')
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

            conversation.set_state('inprogress')
        else:
            abort(403, 'Must be a moderator with mail access.')

        response.status_code = 204

    @require_oauth2_scope('identity')
    def GET_unread_convo_count(self):
        """Endpoint to retrieve the unread conversation count by
        category"""

        convo_counts = ModmailConversation.unread_convo_count(c.user)
        return simplejson.dumps(convo_counts)

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
        sr_by_fullname = {}
        for sr in modded_srs:
            if feature.is_enabled('new_modmail', subreddit=sr.name):
                sr_by_fullname[sr._fullname] = sr

        sr_by_fullname = {
            sr._fullname: sr for sr in modded_srs
            if feature.is_enabled('new_modmail', subreddit=sr.name)
        }

        for conversation in conversations:
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

    def _try_get_subreddit_access(self, conversation):
        sr = Subreddit._by_fullname(conversation.owner_fullname)
        self._feature_enabled_check(sr)

        if not sr.is_moderator_with_perms(c.user, 'mail'):
            abort(403)

        return sr

    def _feature_enabled_check(self, sr):
        if not feature.is_enabled('new_modmail', subreddit=sr.name):
            abort(403, 'Feature not enabled for the passed Subreddit.')
