""" Importer for Monzo current accounts, using JSON as the data source format.

Also works with legacy Prepaid accounts.


Possibly useful content to have in your importer configuration:

from institutions.monzo import current_account_json as monzo_current
from categorisers.monzo import TransactionCategoriser as MonzoCategoriser # optional
 CONFIG = [
      monzo_current.Importer('Assets:Monzo:Current', account_id='acc_00009xxxxxxxxxxxxxxxxx',
            categorizer=MonzoCategoriser()),

      # if you don't want to use a categorizer
      monzo_current.Importer('Assets:Monzo:Prepaid', account_id='acc_00009yyyyyyyyyyyyyyyyy'),
]

"""

import collections
import json
from beancount.ingest.importers.mixins import filing
from beancount.core import data, flags
from beancount.core.amount import Amount, div
from beancount.core.number import D

from beancount.utils.date_utils import parse_date_liberally

dateutil_kwds = {"yearfirst": False, "dayfirst": False}

class Importer(filing.FilingMixin):
    """ The main importer class."""

    @staticmethod
    def _suggested_tags(txn):
        if 'suggested_tags' not in txn:
            return set([])
        return set(txn['suggested_tags'].split())

    def _additional_tags(self, txn):
        if 'metadata' not in txn:
            return set([])
        if 'bacs_direct_debit_instruction_id' in txn['metadata']:
            return set(['DD'])
        if 'faster_payment' in txn['metadata']:
            amount = self.parse_amount(txn['amount'])
            if amount < 0:
                return set(['FPO'])
            return set(['FPI'])
        return set([])


    def parse_amount(self, string):
        """The method used to create Decimal instances. You can override this."""
        return D(string)

    def file_date(self, file):
        "Return the period end, taken as the date of the latest transaction"
        try:
            with open(file.name, encoding='utf8') as fileh:
                txns = json.loads(fileh.read())
        except json.decoder.JSONDecodeError:
            return False

        if 'transactions' not in txns:
            return False

        dates = list(map(lambda tx: parse_date_liberally(tx['created']), txns['transactions']))
        dates.sort()
        latest = dates[-1]
        return latest

    def identify(self, file):
        """ the heuristic we use is to check for valid UTF8, valid JSON, and
        then for a dict key called 'transactions', and then that the first 5
        records in that list each being a dict with an id starting with tx_
        and that the account_id matches what we expect
        """
        try:
            if self.file_date(file) is None:
                return False
            with open(file.name, encoding='utf8') as fileh:
                txns = json.loads(fileh.read())
        except (UnicodeDecodeError, json.decoder.JSONDecodeError):
            return False

        if 'transactions' not in txns:
            return False
        # check the first 5 transactions:
        for txn in txns['transactions'][0:5]:
            try:
                if not txn['id'].startswith('tx_') or self.account_id != txn['account_id']:
                    return False
            except KeyError:
                return False
        return True

    def call_categorizer(self, txn):
        """ Calls the categorizer if one has been set.
        Input: A beancount transaction.
        Returns: A possibly amended beancount transaction
        """
        if not isinstance(self.categorizer, collections.abc.Callable):
            return txn
        return self.categorizer(txn)

    def extract(self, file, _=None):
        """
        Transactions are initially returned with the flag '!', and the
        assumption is that your categoriser will change this to the OK flag
        ('*') for transactions which can be identified
        """
        try:
            with open(file.name, encoding='utf8') as fileh:
                txns = json.loads(fileh.read())['transactions']
        except UnicodeDecodeError:
            return []

        index = 0
        entries = []
        for txn in txns:

            date = parse_date_liberally(txn['created'], dateutil_kwds)
            amount = self.parse_amount(txn['amount'])

            meta = data.new_metadata(file.name, index)

            tags = self._suggested_tags(txn)

            if 'merchant' in txn and txn['merchant'] is not None and 'name' in txn['merchant']:
                payee = txn['merchant']['name']
                narration = txn['description']
                if len(txn['merchant']['category']) > 0:
                    meta['category'] = txn['merchant']['category']
            elif txn['description'].startswith('pot_'):
                payee = "Monzo Pot"
                narration = txn['description']
                tags.add('POT')
            else:
                payee = txn['description']
                narration = ''
            if 'notes' in txn and len(txn['notes']) > 0 and txn['notes'] not in [payee, narration]:
                meta['notes'] = txn['notes']
            if 'counterparty' in txn and len(txn['counterparty']) > 0:
                # extract account_number, sort_code, number, name from the
                # counterparty (ignoring any which aren't present) and join
                # those fields with ", "
                meta['counterparty'] = ', '.join(
                        filter(lambda x: x is not None,
                               map(txn['counterparty'].get,
                                   ['account_number', 'sort_code', 'number', 'name'])))

            meta['id'] = txn['id']

            # payee = ''
            if payee == 'ATM' and meta['category'] == 'cash':
                tags.add('CPT')
            tags |= self._additional_tags(txn)
            units = div(Amount(amount, self.currency), D('100'))
            txn = data.Transaction(meta, date, self.flag, payee, narration,
                                   tags, data.EMPTY_SET, [])
            txn.postings.append(
                data.Posting(self.filing_account, units, None, None, None, None))

            txn = self.call_categorizer(txn)
            entries.append(txn)
            index += 1

        return entries

    def __init__(self, account, account_id, categorizer=None):
        super().__init__(filing=account)
        self.flag = flags.FLAG_WARNING
        self.categorizer = categorizer
        self.account_id = account_id
        self.prefix = 'monzo'
        self.currency = "GBP"
