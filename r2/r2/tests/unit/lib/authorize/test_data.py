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
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################

import datetime
from mock import MagicMock, Mock, patch

from BeautifulSoup import BeautifulStoneSoup
from sqlalchemy.exc import DataError

from r2.lib.authorize import data
from r2.lib.authorize.data import (
    DEFAULT_CHUNK_SIZE,
    _write_data,
    _write_batch_settlement,
    chunked_dates,
    str_to_date,
    update_authorize_data,
    update_batch_settlements,
    update_batch_transactions,
    write_missing_batch_statistics,
)
from r2.tests import RedditTestCase


class TestChunkedDates(RedditTestCase):

    def setUp(self):
        self.todays_date = datetime.datetime.now().date()

    def test_chunked_dates_offset_1(self):
        """Assert that dates are correctly chunked when start date
        is DEFAULT_CHUNK_SIZE + 1 days prior.

        """

        chunk_size = DEFAULT_CHUNK_SIZE + 1
        start_date = self.todays_date - datetime.timedelta(days=chunk_size)

        date_chunks = chunked_dates(start_date)
        chunk_1, chunk_2 = date_chunks

        # Assert that there are two chunks
        self.assertEquals(len(date_chunks), 2)

        # Assert that the first chunk has two dates separated by
        # DEFAULT_CHUNK_SIZE number of days
        num_days = (chunk_1[1] - chunk_1[0]).days
        self.assertEquals(num_days, DEFAULT_CHUNK_SIZE)

        # Assert that the second chunk is a tuple of a single date
        self.assertEquals(len(chunk_2), 1)

        # Assert that the second chunk end date is now
        self.assertEquals(chunk_2[0], self.todays_date)

    def test_chunked_dates_not_offset_1(self):
        """Assert that dates are correctly chunked when start date
        is not DEFAULT_CHUNK_SIZE + 1 days prior.

        """

        chunk_size = DEFAULT_CHUNK_SIZE + 2
        start_date = self.todays_date - datetime.timedelta(days=chunk_size)

        date_chunks = chunked_dates(start_date)

        # Assert that the second chunk is a tuple of two dates
        self.assertEquals(len(date_chunks[1]), 2)

    def test_chunked_dates_with_valid_end_date(self):
        """Assert that dates are correctly chunked when end_date is passed."""

        start_date = self.todays_date - datetime.timedelta(days=60)
        end_date = self.todays_date - datetime.timedelta(days=20)

        date_chunks = chunked_dates(start_date, end_date)

        # Assert that the start date of the first chunk is start_date
        self.assertEquals(date_chunks[0][0], start_date)

        # Assert that the end date of the last chunk is end_date
        last_chunk = reversed(date_chunks).next()
        end_date = reversed(last_chunk).next()
        self.assertEquals(end_date, end_date)

    def test_chunked_dates_with_invalid_end_date(self):
        """Assert that dates are correctly chunked when end_date is greater
        today's date.

        """

        start_date = self.todays_date - datetime.timedelta(days=10)
        end_date = self.todays_date + datetime.timedelta(days=10)

        date_chunks = chunked_dates(start_date, end_date)

        # Assert that the start date of the first chunk is start_date
        self.assertEquals(date_chunks[0][0], start_date)

        # Assert that the end date of the last chunk is today's date
        last_chunk = reversed(date_chunks).next()
        end_date = reversed(last_chunk).next()
        self.assertEquals(end_date, self.todays_date)

    def test_chunked_dates_with_chunk_override(self):
        """Assert that dates are correctly chunked when chunk is overridden."""

        chunk_size = 15
        num_chunks = 3
        start_date = (self.todays_date -
                      datetime.timedelta(days=chunk_size * num_chunks))

        date_chunks = chunked_dates(start_date, chunk=chunk_size)

        # Assert that there are num_chunk number of chunked dates
        self.assertEquals(len(date_chunks), num_chunks)

        # Assert that start date is chunk_size days prior to end date
        start_date, end_date = date_chunks[0]
        self.assertEquals((end_date - start_date).days, chunk_size)


class TestAuthorizeData(RedditTestCase):

    def setUp(self):
        self.session = self.autopatch(data, 'Session')
        self.valid_date_str = '2011-11-11T11:11:11Z'

    def test_write_missing_batch_statistics_raises_exception(self):
        """Assert that calling write_missing_batch_statistics raises
        a NotImplementedError exception.

        """

        with self.assertRaises(NotImplementedError):
            write_missing_batch_statistics()

    def test_str_to_date(self):
        """Assert that str_to_date takes an exact format and returns a date."""

        invalid_str = '2011-11-11T11:11:11'

        # Assert that an invalid string format will raise a ValueError
        with self.assertRaises(ValueError):
            str_to_date(invalid_str)

        # Assert that a valid string will return a datetime
        valid_date = str_to_date(self.valid_date_str)
        self.assertTrue(type(valid_date), datetime.datetime)

    def test_write_data(self):
        """Assert that _write_data properly calls methods on Session."""

        fake_data = MagicMock()
        _write_data(fake_data)

        # Assert that - if no DataError - that Session method calls are made
        self.session.merge.assert_called_once_with(fake_data)
        self.assertTrue(self.session.commit.called)

        # Assert that a DataError on Session.merge will call Session.rollback
        data_error = DataError(Mock(), Mock(), Mock(), Mock())
        self.session.merge.side_effect = data_error
        _write_data(fake_data)
        self.assertTrue(self.session.rollback.called)

        self.session.reset_mock()

        # Assert that a DataError on Session.commit will call Session.rollback
        self.session.commit.side_effect = data_error
        _write_data(fake_data)
        self.assertTrue(self.session.rollback.called)

    @patch('r2.lib.authorize.data.update_batch_transactions')
    @patch('r2.lib.authorize.data._write_batch_statistic')
    @patch('r2.lib.authorize.data.AuthorizeBatchSettlement')
    def test_write_batch_settlement(self, settlement, write_statistic,
                                    update_transactions):
        """Assert that AuthorizeBatchSettlement is initialized with the correct
        args and that _write_batch_statistic is called accordingly.

        """

        time_str = self.valid_date_str
        xml = '<batchid>123</batchid>' + \
              '<settlementtimeutc>' + time_str + '</settlementtimeutc>' + \
              '<settlementstate>OK</settlementstate>' + \
              '<statistic></statistic><statistic></statistic>'
        data = BeautifulStoneSoup(xml)

        _write_batch_settlement(data)

        # Assert that AuthorizeBatchSettlement is correctly initialized
        settlement.assert_called_once_with(
            batch_id=123,
            settlement_state='OK',
            settlement_time=str_to_date(time_str),
        )

        # Assert that _write_batch_statistic is called once for each incidence
        # of <transaction</transaction> in the XML
        self.assertEquals(write_statistic.call_count, 2)

        # Assert that update_transactions is called with batch ID
        update_transactions.assert_called_once_with(123)

    @patch('r2.lib.authorize.data._write_batch_transaction')
    @patch('r2.lib.authorize.data.GetTransactionListRequest.make_request')
    def test_update_batch_transactions(self, make_request, write_transaction):
        """Assert that _write_batch_transactions is called correct number of
        times.

        """

        def transactions_data(num):
            xml = ''.join(['<transaction></transaction>' for i in range(num)])
            return BeautifulStoneSoup(xml)

        # Assert _write_batch_transaction called for each instance of
        # <transaction></transaction
        make_request.return_value = transactions_data(5)
        update_batch_transactions(123)
        self.assertEquals(write_transaction.call_count, 5)

        make_request.return_value = transactions_data(2)
        write_transaction.reset_mock()
        update_batch_transactions(123)
        self.assertEquals(write_transaction.call_count, 2)

    @patch('r2.lib.authorize.data.GetSettledBatchListRequest')
    def test_update_batch_settlements(self, request):
        """Assert that update_batch_settlements is passed the proper args."""

        time_now = datetime.datetime.now()

        # Assert that no args passed if called with no args
        update_batch_settlements()
        request.assert_called_once_with()

        # Assert that no args passed if called with only start date
        request.reset_mock()
        update_batch_settlements(time_now)
        request.assert_called_once_with()

        # Assert that no args passed if called with only end date
        request.reset_mock()
        update_batch_settlements(end_date=time_now)
        request.assert_called_once_with()

        # Assert that both start and end date passed if called with both
        start_time = time_now - datetime.timedelta(days=7)
        request.reset_mock()
        update_batch_settlements(start_time, time_now)
        request.assert_called_once_with(start_time, time_now)

    @patch('r2.lib.authorize.data.AuthorizeBatchSettlement')
    @patch('r2.lib.authorize.data.update_batch_settlements')
    def test_update_authorize_data(self, update_settlements, settlement):
        """Assert update_batch_settlements is called right number of times."""

        # Assert that update_batch_settlements passed no args if no entries
        settlement.last_settlement_time.return_value = None
        update_authorize_data()
        update_settlements.assert_called_once_with()

        # Assert that update_batch_settlements is called for each date chunk
        update_settlements.reset_mock()
        num_chunks = 5
        start_date = (datetime.datetime.now() -
                      datetime.timedelta(days=num_chunks * DEFAULT_CHUNK_SIZE))
        settlement.last_settlement_time.return_value = start_date
        update_authorize_data()
        self.assertEquals(update_settlements.call_count, num_chunks)
