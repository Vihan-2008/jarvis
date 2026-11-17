# jcc/data

`cacert.pem` is the list of certificate authorities Mozilla trusts in Firefox, as packed by the
[certifi](https://github.com/certifi/python-certifi) project (version 2026.10.23). It is distributed under the
Mozilla Public License 2.0 (https://mozilla.org/MPL/2.0/); it is used unchanged.

JARVIS trusts it beside the PC's own list (see `jcc/net.py`), so secure connections work on a new Windows PC that has
not yet fetched every authority it trusts. To update it, copy `cacert.pem` from a newer certifi.
