# Description
This is a collection of importers for the UK neo-bank Monzo for use by <a href="https://beancount.github.io/docs/index.html">Beancount</a>. 

There is currently only one importer:

* current_account_json.py - which parses a JSON dump of your account transactions

# Setup
I recommend the following directory layout:

* `./main.bean` : Your top-level beancount file
* `./foo.bean` : (any included file)
* `importers/institutions/monzo` : *This repo*
* `categorisers/` : Your categorisers
* `config.py` : Your importer configuration (see below)

# Sample importer configuration
```python
from institutions.monzo import current_account_json as monzo_current

CONFIG = [
    monzo_current.Importer('Assets:Monzo:Current', account_id='acc_0000999999999999999999'),
]

```

# Usage

```bash
bean-extract config.py documents/monzo.json >> monzo.bean
```
You'll need to find your `account_id` in your JSON file and edit the config
snippet given above. My reason for adding this is that some people might have
multiple Monzo accounts (e.g. the now superceded Prepaid accounts) which are
filed in different Beancount accounts.

I like to test the import by writing to a temporary file first (which I include
from my top-level file, but I subsequently truncate this file prior to
importing for real). This allows me to modify my categoriser and re-run
`bean-extract` without having to manually edit my already-imported credit card
beanfile.

