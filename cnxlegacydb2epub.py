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
  legacydb2epub [--file <file>] <id> <version>

Options:
  -f --file     File output file-path
  -h --help     Display this usage help.
  --version     Display version number.

"""
import sys

from docopt import docopt


__version__ = '0.1'
VERSION = "legacydb2epub v{}".format(__version__)


def main(argv=None):
    """Main command-line interface"""
    args = docopt(__doc__, argv, version=VERSION)

    # Build the legacy content as a mapping object.


    # - Determine the output stream (stdout or file).


    # Render the legacy content to EPUB format.


    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
