# -*- coding: utf-8 -*-
from setuptools import setup


install_requires = (
    'docopt',
    'lxml',
    'jinja2',
    'psycopg2>=2.5',
    )
with open('README.rst', 'r') as fb:
    description = fb.read()


setup(
    name='cnx-legacydb2epub',
    version='0.1',
    author='',
    author_email='',
    url="https://github.com/pumazi/cnx-legacydb2epub",
    license='AGPL, See also LICENSE.txt',
    description=description,
    py_modules=['cnxlegacydb2epub'],
    install_requires=install_requires,
    include_package_data=False,
    entry_points="""\
[console_scripts]
legacydb2epub = cnxlegacydb2epub:main
""",
    test_suite='tests'
    )
