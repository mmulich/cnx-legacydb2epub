# -*- coding: utf-8 -*-
# ###
# Copyright (c) 2013, Rice University
# This software is subject to the provisions of the GNU Affero General
# Public License version 3 (AGPLv3).
# See LICENCE.txt for details.
# ###
"""\
Exports Connexions documents from the legacy database to EPUB.

Usage:
  legacydb2epub <id> <version> [--db-uri=<uri>] [--file=<file>]

Options:
  <id>            A module's content id (e.g. m44425)
  <version>       A module's version number (e.g. 1.1)
  --db-uri=<uri>  The database connection URI
        (e.g. postgresql://[<user>[:<pass>]]@<host>[:<port>]/<db-name>)
        [default: postgresql://localhost]
  --file=<file>   File output file-path
  -h, --help      Display this usage help.
  --version       Display version number.

"""
import sys
import re

from docopt import docopt


__version__ = '0.1'
__all__ = ('main',)  # Do not import from here. It is not a library.

VERSION = "legacydb2epub v{}".format(__version__)
URI_REGEX = re.compile(r'''
(?P<name>[\w\+]+)://
(?:
    (?P<username>[^:/]*)
    (?::(?P<password>[^/]*))?
@)?
(?:
    (?:
        \[(?P<ipv6host>[^/]+)\] |
        (?P<ipv4host>[^/:]+)
    )?
    (?::(?P<port>[^/]*))?
)?
(?:/(?P<database>.*))?
''', re.X)


class CoreException(Exception):
    """Exception base class"""
    # Note, not using BaseException because it exists base Python.
    code = -1


class URIParsingError(Exception):
    """Raised when the database URI cannot be parsed."""
    code = 10


def db_uri_to_connection_str(uri):
    """Conversion utility for making a ``psycopg2`` compatible
    connection string from a URI.
    """
    conn_str_items = []
    match = URI_REGEX.match(uri)
    if match is None:
        raise UriParsingError("Unparsable URI value: {}".format(uri))
    components = match.groupdict()
    if components['database'] is not None:
        conn_str_items.append("dbname={}".format(components['database']))
    if components['username'] is not None:
        conn_str_items.append("username={}".format(components['username']))
    if components['password'] is not None:
        password = urllib.parse.unquote_plus(components['password'])
        conn_str_items.append("password={}".format(password))
    if components['port'] is not None:
        conn_str_items.append("port={}".format(components['port']))
    ipv4host = components.pop('ipv4host')
    ipv6host = components.pop('ipv6host')
    host = ipv4host or ipv6host
    conn_str_items.append("host={}".format(host))
    return ' '.join(conn_str_items)


def extract_content(id, version):
    pass



def main(argv=None):
    """Main command-line interface"""
    args = docopt(__doc__, argv, version=VERSION)
    psycopg2_db_conn_str = db_uri_to_connection_str(args['--db-uri'])

    # Build the legacy content as a mapping object.


    # - Determine the output stream (stdout or file).


    # Render the legacy content to EPUB format.


    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
