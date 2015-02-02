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

import time

from r2.lib.db.operators import desc
from r2.lib.utils import fetch_things2, progress
from r2.lib import amqp
from r2.models import Account


def get_queue_length(name):
    # https://stackoverflow.com/questions/1038318/check-rabbitmq-queue-size-from-client
    chan = amqp.connection_manager.get_channel()
    queue_response = chan.queue_declare(name, passive=True)
    return queue_response[1]


def backfill_deleted_accounts(resume_id=None):
    del_accts = Account._query(Account.c._deleted == True, sort=desc('_date'))
    if resume_id:
        del_accts._filter(Account.c._id < resume_id)

    for i, account in enumerate(progress(fetch_things2(del_accts))):
        # Don't kill the rabbit!
        if i % 1000 == 0:
            while get_queue_length('del_account_q') > 10000:
                time.sleep(1)
        amqp.add_item('account_deleted', account._fullname)

