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

from pylons import app_globals as g
from sqlalchemy.exc import DataError

from r2.lib.authorize.api import (
    GetSettledBatchListRequest,
    GetTransactionListRequest,
)
from r2.models.authorizenet import (
    AuthorizeBatchSettlement,
    AuthorizeBatchStatistic,
    AuthorizeBatchTransaction,
    Session,
)

DEFAULT_CHUNK_SIZE = 31


def chunked_dates(start_date, end_date=None, chunk=DEFAULT_CHUNK_SIZE):
    """Returns a list of tuples of start and end dates
    that are `chunk` days apart or less.

    """

    todays_date = datetime.datetime.now().date()

    if not end_date:
        end_date = todays_date

    dates = []
    chunk_start_date = start_date
    chunk_end_date = start_date
    while chunk_end_date < end_date:
        chunk_end_date = chunk_start_date + datetime.timedelta(days=chunk)
        if chunk_start_date == end_date:
            dates.append((chunk_start_date,))
        elif todays_date < chunk_end_date:
            dates.append((chunk_start_date, todays_date))
        elif end_date < chunk_end_date:
            dates.append((chunk_start_date, end_date))
        else:
            dates.append((chunk_start_date, chunk_end_date))
            chunk_start_date += datetime.timedelta(days=chunk + 1)

    return dates


def str_to_date(date_str):
    return datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')


def _write_data(data):
    try:
        Session.merge(data)
        Session.commit()
    except DataError:
        Session.rollback()
        g.log.warning('Error writing to authorize DB: %s' % data)


def _write_batch_statistic(statistic, batch_id, settlement_time):
    session_statistic = AuthorizeBatchStatistic(
        batch_id=batch_id,
        settlement_time=settlement_time,
        account_type=statistic.find('accounttype').text,
        charge_amount=float(statistic.find('chargeamount').text),
        charge_count=int(statistic.find('chargecount').text),
        refund_amount=float(statistic.find('refundamount').text),
        refund_count=int(statistic.find('refundcount').text),
        void_count=int(statistic.find('voidcount').text),
        decline_count=int(statistic.find('declinecount').text),
        error_count=int(statistic.find('errorcount').text),
    )
    _write_data(session_statistic)


def _write_batch_settlement(batch):
    batch_id = int(batch.find('batchid').text)
    settlement_time_str = batch.find('settlementtimeutc').text
    settlement_time = str_to_date(settlement_time_str)

    session_batch = AuthorizeBatchSettlement(
        batch_id=batch_id,
        settlement_state=batch.find('settlementstate').text,
        settlement_time=settlement_time,
    )
    _write_data(session_batch)

    for statistic in batch.findAll('statistic'):
        _write_batch_statistic(statistic, batch_id, settlement_time)

    update_batch_transactions(batch_id)


# TODO
def write_missing_batch_statistics():
    raise NotImplementedError


# Use this to manually update transactions by batch
def update_batch_transactions(batch_id):
    res = GetTransactionListRequest(batch_id).make_request()

    for transaction in res.findAll('transaction'):
        _write_batch_transaction(transaction, batch_id)


def _write_batch_transaction(transaction, batch_id):
    submit_time_str = transaction.find('submittimeutc').text
    # `invoicenumber` is not a required field in the response
    invoice_number = getattr(transaction.find('invoicenumber'),
                             'text', None)
    # `firstname` and `lastname` are sometimes missing in the response
    first_name = getattr(transaction.find('firstname'), 'text', None)
    last_name = getattr(transaction.find('lastname'), 'text', None)

    session_transaction = AuthorizeBatchTransaction(
        batch_id=batch_id,
        trans_id=int(transaction.find('transid').text),
        submit_time=str_to_date(submit_time_str),
        transaction_status=transaction.find('transactionstatus').text,
        invoice_number=invoice_number,
        first_name=first_name,
        last_name=last_name,
        account_type=transaction.find('accounttype').text,
        account_number=transaction.find('accountnumber').text,
        settle_amount=float(transaction.find('settleamount').text),
    )
    _write_data(session_transaction)


# Use this to manually update settlements, statistics, and transactions by date
def update_batch_settlements(start_date=None, end_date=None):
    if not start_date or not end_date:
        # Write most recent batch settlement
        res = GetSettledBatchListRequest().make_request()
    else:
        # Backfill all batch settlements from start_date to end_date
        res = GetSettledBatchListRequest(start_date, end_date).make_request()

    for batch in res.findAll('batch'):
        _write_batch_settlement(batch)


def update_authorize_data():
    latest_entry_time = AuthorizeBatchSettlement.last_settlement_time()
    todays_date = datetime.datetime.now().date()

    if not latest_entry_time:
        # There are no entries; just create a row for the latest batch
        update_batch_settlements()
    else:
        date_chunks = chunked_dates(latest_entry_time.date(), todays_date)
        # Add a row for each batch since the last row
        for date_chunk in date_chunks:
            update_batch_settlements(
                start_date=date_chunk[0],
                end_date=date_chunk[1],
            )
