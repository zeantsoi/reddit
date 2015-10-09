#!/usr/bin/env python
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

import unittest
from r2.tests import RedditTestCase

from mock import MagicMock, patch
from pylons import tmpl_context as c
from webob.exc import HTTPForbidden

from r2.lib.errors import errors, ErrorSet
from r2.lib.validator import (
    VByName,
    VSubmitParent,
    VSubredditName,
    ValidEmail,
)
from r2.models import Account, Comment, Link, Message, Subreddit


class ValidatorTests(unittest.TestCase):
    def _test_failure(self, input, error):
        """Helper for testing bad inputs."""
        self.validator.run(input)
        self.assertTrue(self.validator.has_errors)
        self.assertTrue(c.errors.get((error, None)))

    def _test_success(self, input, assertEqual=True):
        result = self.validator.run(input)
        self.assertFalse(self.validator.has_errors)
        self.assertEqual(len(c.errors), 0)
        if assertEqual:
            self.assertEqual(result, input)

        return result


class TestVSubmitParent(ValidatorTests):
    def setUp(self):
        # Reset the validator state and errors before every test.
        self.validator = VSubmitParent(None)
        c.errors = ErrorSet()

        c.user_is_loggedin = True
        c.user_is_admin = False
        c.user = Account(id=100)

        Account.enemy_ids = MagicMock(return_value=[])

    def _mock_message(id=1, author_id=1, **kwargs):
        kwargs['id'] = id
        kwargs['author_id'] = author_id

        message = Message(**kwargs)
        VByName.run = MagicMock(return_value=message)

        return message

    def _mock_link(id=1, author_id=1, **kwargs):
        kwargs['id'] = id
        kwargs['author_id'] = author_id

        link = Link(**kwargs)
        VByName.run = MagicMock(return_value=link)

        return link

    def _mock_comment(id=1, author_id=1, link_id=1, sr_id=1, **kwargs):
        kwargs['id'] = id
        kwargs['author_id'] = author_id
        kwargs['link_id'] = link_id

        comment = Comment(**kwargs)
        VByName.run = MagicMock(return_value=comment)

        link = Link(id=link_id)
        Link._byID = MagicMock(return_value=link)

        sr = Subreddit(id=sr_id)
        comment.subreddit_slow = MagicMock(return_value=sr)
        comment.subreddit_slow.is_moderator = MagicMock(return_value=False)

        return comment

    def test_no_fullname(self):
        with self.assertRaises(HTTPForbidden):
            self.validator.run('', None)

        self.assertFalse(self.validator.has_errors)

    def test_not_found(self):
        with self.assertRaises(HTTPForbidden):
            VByName.run = MagicMock(return_value=None)
            self.validator.run('fullname', None)

        self.assertFalse(self.validator.has_errors)

    def test_invalid_thing(self):
        with self.assertRaises(HTTPForbidden):
            sr = Subreddit(id=1)
            VByName.run = MagicMock(return_value=sr)
            self.validator.run('fullname', None)

        self.assertFalse(self.validator.has_errors)

    def test_blocked_user(self):
        message = self._mock_message()
        Account.enemy_ids = MagicMock(return_value=[message.author_id])

        result = self.validator.run('fullname', None)

        self.assertEqual(result, message)
        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.USER_BLOCKED, None), c.errors)

    def test_valid_message(self):
        message = self._mock_message()
        result = self.validator.run('fullname', None)

        self.assertEqual(result, message)
        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_valid_link(self, can_comment_link):
        can_comment_link.return_value = True

        link = self._mock_link()
        result = self.validator.run('fullname', None)

        self.assertEqual(result, link)
        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_deleted_link(self, can_comment_link):
        can_comment_link.return_value = True

        link = self._mock_link(_deleted=True)
        result = self.validator.run('fullname', None)

        self.assertEqual(result, link)
        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.DELETED_LINK, None), c.errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_deleted_link_logged_out(self, can_comment_link):
        with self.assertRaises(HTTPForbidden):
            c.user_is_loggedin = False

            link = self._mock_link(_deleted=True)
            self.validator.run('fullname', None)

        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.DELETED_LINK, None), c.errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_removed_link(self, can_comment_link):
        can_comment_link.return_value = True

        link = self._mock_link(_spam=True)
        result = self.validator.run('fullname', None)

        self.assertEqual(result, link)
        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_invalid_link(self, can_comment_link):
        with self.assertRaises(HTTPForbidden):
            can_comment_link.return_value = False

            self._mock_link()
            self.validator.run('fullname', None)

        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_valid_comment(self, can_comment_link):
        can_comment_link.return_value = True

        comment = self._mock_comment()
        result = self.validator.run('fullname', None)

        self.assertEqual(result, comment)
        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_deleted_comment(self, can_comment_link):
        can_comment_link.return_value = True

        comment = self._mock_comment(_deleted=True)
        result = self.validator.run('fullname', None)

        self.assertEqual(result, comment)
        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.DELETED_COMMENT, None), c.errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_deleted_comment_logged_out(self, can_comment_link):
        with self.assertRaises(HTTPForbidden):
            c.user_is_loggedin = False

            comment = self._mock_comment(_deleted=True)
            self.validator.run('fullname', None)

        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.DELETED_COMMENT, None), c.errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_removed_comment(self, can_comment_link):
        can_comment_link.return_value = True

        comment = self._mock_comment(_spam=True)
        result = self.validator.run('fullname', None)

        self.assertEqual(result, comment)
        self.assertTrue(self.validator.has_errors)
        self.assertIn((errors.DELETED_COMMENT, None), c.errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_removed_comment_self_reply(self, can_comment_link):
        can_comment_link.return_value = True

        comment = self._mock_comment(author_id=c.user._id, _spam=True)
        result = self.validator.run('fullname', None)

        self.assertEqual(result, comment)
        self.assertFalse(self.validator.has_errors)

    @patch('r2.lib.validator.validator.can_comment_link')
    def test_invalid_comment(self, can_comment_link):
        with self.assertRaises(HTTPForbidden):
            can_comment_link.return_value = False

            comment = self._mock_comment()
            self.validator.run('fullname', None)

        self.assertFalse(self.validator.has_errors)


class TestVSubredditName(ValidatorTests):
    def setUp(self):
        # Reset the validator state and errors before every test.
        self.validator = VSubredditName(None)
        c.errors = ErrorSet()

    def _test_failure(self, input, error=errors.BAD_SR_NAME):
        super(TestVSubredditName, self)._test_failure(input, error)

    # Most of this validator's logic is already covered in `IsValidNameTest`.

    def test_slash_r_slash(self):
        result = self._test_success('/r/foo', assertEqual=False)
        self.assertEqual(result, 'foo')

    def test_r_slash(self):
        result = self._test_success('r/foo', assertEqual=False)
        self.assertEqual(result, 'foo')

    def test_two_prefixes(self):
        self._test_failure('/r/r/foo')

    def test_slash_not_prefix(self):
        self._test_failure('foo/r/')


class TestValidEmail(ValidatorTests):
    """Lightly test email address ("addr-spec") validation against RFC 2822.

    http://www.faqs.org/rfcs/rfc2822.html
    """
    def setUp(self):
        # Reset the validator state and errors before every test.
        self.validator = ValidEmail()
        c.errors = ErrorSet()

    def test_valid_emails(self):
        self._test_success('test@example.com')
        self._test_success('test@example.co.uk')
        self._test_success('test+foo@example.com')

    def _test_failure(self, email, error=errors.BAD_EMAIL):
        super(TestValidEmail, self)._test_failure(email, error)

    def test_blank_email(self):
        self._test_failure('', errors.NO_EMAIL)
        self.setUp()
        self._test_failure(' ', errors.NO_EMAIL)

    def test_no_whitespace(self):
        self._test_failure('test @example.com')
        self.setUp()
        self._test_failure('test@ example.com')
        self.setUp()
        self._test_failure('test@example. com')
        self.setUp()
        self._test_failure("test@\texample.com")

    def test_no_hostname(self):
        self._test_failure('example')
        self.setUp()
        self._test_failure('example@')

    def test_no_username(self):
        self._test_failure('example.com')
        self.setUp()
        self._test_failure('@example.com')

    def test_two_hostnames(self):
        self._test_failure('test@example.com@example.com')
