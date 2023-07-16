from beancount.ingest.importers.mixins import filing, identifier
import collections
import datetime
import json
from beancount.core import data, flags
from beancount.core.amount import Amount, div
from beancount.core.number import ZERO, D

from beancount.utils.date_utils import parse_date_liberally

dateutil_kwds =  { "yearfirst": False, "dayfirst": False }

class Importer(filing.FilingMixin):
    def parse_amount(self, string):
        """The method used to create Decimal instances. You can override this."""
        return D(string)


    def file_date(self, file):
        "Return the period end, taken as the date of the latest transaction"
        try:
            txns = json.loads(open(file.name, encoding='utf8').read())
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
            txns = json.loads(open(file.name, encoding='utf8').read())
        except UnicodeDecodeError:
            return False
        except json.decoder.JSONDecodeError:
            return False

        if 'transactions' not in txns:
            return False
        # check the first 5 transactions:
        for txn in txns['transactions'][0:5]:
            try:
                if not txn['id'].startswith('tx_'):
                    return False
                if self.account_id != txn['account_id']:
                    return False
            except KeyError:
                return False
        return True


    def call_categorizer(self, txn, row):
        if not isinstance(self.categorizer, collections.abc.Callable):
            return txn
        return self.categorizer(txn)


    def extract(self, file, existing_entries=None):
        """
        Transactions are initially returned with the flag '!', and the
        assumption is that your categoriser will change this to the OK flag
        ('*') for transactions which can be identified
        """
        try:
            txns = json.loads(open(file.name, encoding='utf8').read())['transactions']
        except UnicodeDecodeError:
            return []

        index = 0
        entries = []
        for txn in txns:

            date = parse_date_liberally(txn['created'], dateutil_kwds)
            desc = txn['description']
            amount = self.parse_amount(txn['amount']) # TODO currency

            row = [ date, desc,amount, index]

            meta = data.new_metadata(file.name, index)

            if 'suggested_tags' in txn:
                tags = set( txn['suggested_tags'].split() )
            else:
                tags = set([])

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
            if 'notes' in txn and len(txn['notes']) > 0 and txn['notes'] != payee and txn['notes'] != narration:
                meta['notes'] = txn['notes']
            if 'counterparty' in txn and len(txn['counterparty']) > 0:
                counterparty = ', '.join(filter(lambda x: x is not None, map(lambda x: txn['counterparty'][x] if x in txn['counterparty'] else None, ['account_number', 'sort_code', 'number', 'name'])))
                meta['counterparty'] = counterparty
                    
            meta['id'] = txn['id']

            # payee = ''
            # narration = desc
            if payee == 'ATM' and meta['category'] == 'cash':
                tags.add('CPT')
            if 'metadata' in txn:
                if 'bacs_direct_debit_instruction_id' in txn['metadata']:
                        tags.add('DD')
                elif 'faster_payment' in txn['metadata']:
                    if amount < 0:
                        tags.add('FPO')
                    else:
                        tags.add('FPI')

            links = data.EMPTY_SET
            units = div(Amount(amount, self.currency),D('100'))
            txn = data.Transaction(meta, date, self.FLAG, payee, narration, tags, links, [])
            txn.postings.append(
                data.Posting(self.filing_account, units, None, None, None, None))

            txn = self.call_categorizer(txn, row)
            entries.append(txn)
            index += 1

        return entries

    def __init__(self, account, account_id, categorizer=None):
        self.filing_account = account
        self.FLAG = flags.FLAG_WARNING
        self.categorizer = categorizer
        self.account_id = account_id
        self.prefix = 'monzo'
        self.currency = "GBP"
