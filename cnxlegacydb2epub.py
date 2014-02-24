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
  legacydb2epub [--db-uri=<uri>] [--] <ident-hash> [<file>]

Options:
  <ident-hash>    A module's content id and version (e.g. <uuid>[@<version>])
  <file>          File-path to output [default: <ident-hash>.epub]
  --db-uri=<uri>  The database connection URI
        (e.g. postgresql://[<user>[:<pass>]]@<host>[:<port>]/<db-name>)
        [default: postgresql://localhost]
  -h, --help      Display this usage help.
  --version       Display version number.

"""
import os
import sys
import re
import json
import zipfile

import jinja2
import psycopg2
from lxml import etree
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
COLLECTION_TYPE = 'Collection'
MODULE_TYPE = 'Module'


class CoreException(Exception):
    """Exception base class"""
    # Note, not using BaseException because it exists base Python.
    code = -1


class OptionError(CoreException):
    code = 5

    def __init__(self, option, cli_args, message=None):
        self.option = option
        self.cli_args = cli_args
        self.message = message

    def __str__(self):
        return "{}={} -- {}".format(self.option, self.cli_args[self.option],
                                     self.message or '')

    def __repr__(self):
        cls_name = self.__class__.__name__
        return "<{} ({})>".format(cls_name, str(self))


class URIParsingError(CoreException):
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
        conn_str_items.append("user={}".format(components['username']))
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


def flatten_tree_to_ident_hashs(item_or_tree):
    """Flatten a collection tree to id and version values."""
    if 'contents' in item_or_tree:
        tree = item_or_tree
        if tree['id'] != 'subcol':
            yield tree['id']
        for i in tree['contents']:
            yield from flatten_tree_to_ident_hashs(i)
    else:
        item = item_or_tree
        yield item['id']
    raise StopIteration()


def extract_content(id, version, db_cursor):
    """Returns the contents in a flat list."""
    # Grab the module in question.
    db_cursor.execute(SQL_GET_MODULE, dict(id=id, version=version))
    try:
        module = db_cursor.fetchone()[0]
    except TypeError:  # because <NoneType>[0]
        raise ValueError("Content not found for id={} and version={}" \
                         .format(id, version))
    # Is it a module or collection? (LEAF or TREE)
    if module['_type'] == COLLECTION_TYPE:
        # Grab the tree...
        db_cursor.execute(SQL_GET_TREE, module)
        module['tree'] = json.loads(db_cursor.fetchone()[0])
        # ...rerun extract_content over of the items.
        yield module
        for ident_hash in flatten_tree_to_ident_hashs(module['tree']):
            id, version = ident_hash.split('@')
            if id == module['id'] and version == module['version']:
                continue
            yield from extract_content(id, version, db_cursor)
    else:
        args = {'module_ident': module['_ident']}
        # Grab the content document.
        db_cursor.execute(SQL_GET_CONTENT, args)
        try:
            content = db_cursor.fetchone()[0]
        except TypeError:  # because <NoneType>[0]
            raise ValueError("Content (index.cnxml.html) not found " \
                             "for id={} and version={}" \
                             .format(id, version))
        module['content'] = content[:]
        yield module
    raise StopIteration()


def extract_resources(idents, db_cursor):
    """Returns a list of resource files given a list of
    module_idents (the internal primary key for modules).
    """
    # Extract resource files.
    args = {'idents': idents}
    db_cursor.execute(SQL_GET_FILES, args)
    # List of (md5, mediatype, filename, buff,)
    resources = db_cursor.fetchall()


# HTML namespace mapping
HTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
HTML_NSMAP = {
    None: HTML_NAMESPACE,
    'html': HTML_NAMESPACE,
}
# NoneType keyed namespaces are not allowed in etree.XPath.
XPATH_HTML_NSMAP = HTML_NSMAP.copy()
XPATH_HTML_NSMAP.pop(None)


def html_listify(tree, root_ul_element):
    for node in tree:
        li_elm = etree.SubElement(root_ul_element, 'li')
        a_elm = etree.SubElement(li_elm, 'a')
        a_elm.text = node['title']
        if node['id'] != 'subcol':
            # FIXME Hard coded route...
            a_elm.set('href', '{}.html'.format(node['id']))
        if 'contents' in node:
            elm = etree.SubElement(li_elm, 'ul')
            html_listify(node['contents'], elm)


def tree_to_html(tree):
    """Renders the tree to HTML"""
    nav = etree.Element('nav', nsmap=HTML_NSMAP)
    ul = etree.SubElement(nav, 'ul')
    html_listify([tree], ul)
    return str(etree.tostring(nav), 'utf-8')


def fix_content(content):
    """Fixes the content by stripping the HTML wrapper."""
    # FIXME Strip existing HTML down to body. Note,
    #       it should be this way in the database.
    module_html = etree.fromstring(content['content'])
    module_body = module_html.xpath('//html:body/*',
                                    namespaces=XPATH_HTML_NSMAP)
    content['content'] = '\n'.join([str(etree.tostring(elm), 'utf-8')
                                    for elm in module_body])


def render_to_html(content):
    """Render the given content to HTML."""
    info = content.copy()
    if content['_type'] == COLLECTION_TYPE:
        info['content'] = tree_to_html(info['tree'])
    else:
        fix_content(info)
    html_template = jinja2.Template(HTML_TEMPLATE)
    head_template = jinja2.Template(HTML_HEAD_TEMPLATE)
    body_template = jinja2.Template(HTML_BODY_TEMPLATE)
    html_blocks = {
        'head': head_template.render(**info),
        'body': body_template.render(**info),
        }
    return html_template.render(**html_blocks)


def main(argv=None):
    """Main command-line interface"""
    args = docopt(__doc__, argv, version=VERSION)
    psycopg2_db_conn_str = db_uri_to_connection_str(args['--db-uri'])

    # - Set up the output stream.
    if args['<file>'] is None:
        filepath = "{}.epub".format(args['<ident-hash>'])
    else:
        filepath = args['<file>']
    epub = zipfile.ZipFile(filepath, 'w')

    try:
        id, version = args['<ident-hash>'].split('@')
    except ValueError as exc:
        if exc.args[0].find('unpack') >= 0:
            raise OptionError('<ident-hash>', args, "missing version")
    # Build the legacy content as a mapping object.
    with psycopg2.connect(psycopg2_db_conn_str) as db_conn:
        with db_conn.cursor() as cursor:
            for content in extract_content(id, version, cursor):
                filename = "{}@{}.html".format(content['id'],
                                               content['version'])
                arc_filepath = os.path.join('contents', filename)
                epub.writestr(arc_filepath, render_to_html(content))

                MSG = "{} - {}"
                print(MSG.format(arc_filepath, content['title']))


    # Render the legacy content to EPUB format.


    epub.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))



# From here down be Dragons!


HTML_TEMPLATE = """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:lrmi="http://lrmi.net/the-specification"
      version="HTML+RDFa 1.1"
      >
{{ head }}
{{ body }}
</html>
"""
HTML_HEAD_TEMPLATE = """\
<head itemscope="itemscope"
      itemtype="http://schema.org/Book"
      >
 <title>{{ title }}</title>
 <meta name="dc:license" content="{{ license.name }}" />
 <link rel="lrmi:useRightsURL" href="{{ license.url }}"/>
 <meta itemprop="inLanguage" content="{{ language }}">
 <meta itemprop="accessibilityFeature" content="MathML" />
 <meta itemprop="accessibilityFeature" content="alternativeText" />
 {% for keyword in keywords -%}
   <meta itemprop="keywords" content="{{ keyword }}" />
 {%- endfor %}
 {% for subject in subjects -%}
   <meta itemprop="about" content="{{ subject }}" />
 {%- endfor %}
 <meta itemprop="dateCreated" content="{{ created }}" />
 <meta itemprop="dateModified" content="{{ revised }}" />
</head>
"""
HTML_BODY_TEMPLATE = """\
<body>
  <div itemscope="itemscope"
       itemtype="http://schema.org/CreativeWork"
       data-type="metadata"
       >
    <h1 data-type="title" itemprop="name">{{ title }}</h1>
    <div class="contributors">
      <div class="authors">By: 
      {% for person in authors -%}
        <span itemscope="itemscope"
              itemtype="http://schema.org/Person"
              itemprop="author"
              data-type="author"
              >
          <a href="https://accounts.cnx.org/{{ person.id }}"
             itemprop="url"
             data-type="cnx-id"
             >{{ person.fullname }}</a>
        </span>{% if not loop.last %} and {% endif %}
      {%- endfor %}
      </div>
      <div class="editors">Edited by: 
      {% for person in editors -%}
        <span itemscope="itemscope"
              itemtype="http://schema.org/Person"
              itemprop="editor"
              data-type="editor"
              >
          <a href="https://accounts.cnx.org/{{ person.id }}"
             itemprop="url"
             data-type="cnx-id"
             >{{ person.fullname }}</a>
        </span>{% if not loop.last %} and {% endif %}
      {%- endfor %}
      </div>
      <!-- Schema.org doesn't have translator. Rather than really contorting
           to try and use something like marc:relators, for now,
           just use our own data-type, and use the more generic
           "contributor" from schema.org. -->
      <div class="editors">Edited by: 
      {% for person in translator -%}
        <span itemscope="itemscope"
              itemtype="http://schema.org/Person"
              itemprop="contributor"
              data-type="translator"
              >
          <a href="https://accounts.cnx.org/{{ person.id }}"
             itemprop="url"
             data-type="cnx-id"
             >{{ person.fullname }}</a>
        </span>{% if not loop.last %} and {% endif %}
      {%- endfor %}
      </div>
    </div>
    <div class="publishers">Published by: 
      <span itemprop="publisher"
            data-type="publisher"
            >
          <a href="https://accounts.cnx.org/{{ submitter.id }}"
             itemprop="url"
             data-type="cnx-id"
             >{{ submitter.fullname }}</a>
    </div>

    {% if basedOn is defined %}
    <div class="derived-from">Based on: 
      <a href="http://cnx.org/contents/{{ basedOn.id }}@{{ basedOn.version }}"
         itemprop="isBasedOnURL"
         data-type="based-on"
         >{{ basedOn.title }}</a>
    </div>
    {% endif %}

    <div class="permissions">
      <div class="copyright">Copyright: 
        {% for person in copyrightHolders -%}
        <span itemscope="itemscope"
              itemtype="http://schema.org/Person"
              itemprop="contributor"
              data-type="copyright-holder"
              >
          <a href="https://accounts.cnx.org/{{ person.id }}"
             itemprop="url"
             data-type="cnx-id"
             >{{ person.fullname }}</a>
        </span>{% if not loop.last %} and {% endif %}
        {%- endfor %}
      </div>

      <div class="license">Licensed: 
        <a rel="license"
           href="{{ license.url }}"
           data-type="license"
           >{{ license.name }}</a>
      </div>

    </div>

    {% if keywords is defined %}
    <div class="keywords">Keywords:
      {% for keyword in keywords -%}
        <span itemprop="keywords"
              data-type="keyword"
              >{{ keyword }}</span>
        {% if not loop.last %}, {% endif %}
      {%- endfor %}
    </div>
    {% endif %}

    {% if subjects is defined %}
    <div class="subjects">Subjects:
      {% for subject in subjects -%}
        <span itemprop="about"
              data-type="subject"
              >{{ subject }}</span>
        {% if not loop.last %}, {% endif %}
      {%- endfor %}
    </div>
    {% endif %}

   <div class="description"
        itemprop="description"
        data-type="description"
        >
     <p class="summary">Summary: {{ abstract }}</p>
    </div>
  </div>

  {{ content }}
</body>
"""


SQL_GET_MODULE = """\
SELECT row_to_json(combined_rows) as module
FROM (SELECT
  m.uuid AS id,
  concat_ws('.', m.major_version, m.minor_version) AS "version",
  -- can't use "version" as we need it in GROUP BY clause and it causes a
  -- "column name is ambiguous" error

  m.module_ident as "_ident",
  m.name as title,
  m.google_analytics as "googleAnalytics",
  m.buylink as "buyLink",
  m.moduleid as "legacy_id",
  m.version as "legacy_version",
  m.portal_type as "_type",
  iso8601(m.created) as created, iso8601(m.revised) as revised,
  a.html AS "abstract",

  (SELECT row_to_json(license) AS "license" FROM (
        SELECT l.code, l.version, l.name, l.url
    ) AS "license"),
  (SELECT row_to_json(submitter_row) AS "submitter" FROM (
        SELECT id, email, firstname, othername, surname, fullname,
            title, suffix, website
        FROM users
        WHERE users.id::text = m.submitter
    ) AS "submitter_row"),
  m.submitlog AS "submitlog",
  ARRAY(SELECT row_to_json(user_rows) FROM
        (SELECT id, email, firstname, othername, surname, fullname,
                title, suffix, website
         FROM users
         WHERE users.id::text = ANY (m.authors)
         ) as user_rows) as "authors",
  ARRAY(SELECT row_to_json(user_rows) FROM
        (SELECT id, email, firstname, othername, surname, fullname,
                title, suffix, website
         FROM users
         WHERE users.id::text = ANY (m.maintainers)
         ) as user_rows) as maintainers,
  ARRAY(SELECT row_to_json(user_rows) FROM
        (SELECT id, email, firstname, othername, surname, fullname,
                title, suffix, website
         FROM users
         WHERE users.id::text = ANY (m.licensors)
         ) user_rows) as licensors,
  p.uuid AS "parentId",
  concat_ws('.', p.major_version, p.minor_version) AS "parentVersion",
  p.name as "parentTitle",
  ARRAY(SELECT row_to_json(user_rows) FROM
        (SELECT id, email, firstname, othername, surname, fullname,
                title, suffix, website
         FROM users
         WHERE users.id::text = ANY (m.parentauthors)
         ) user_rows) as "parentAuthors",
  m.language AS "language",
  (select '{'||list(''''||roleparam||''':['''||array_to_string(personids,''',''')||''']')||'}' from roles natural join moduleoptionalroles where module_ident=m.module_ident group by module_ident) as roles,
  ARRAY(SELECT tag FROM moduletags AS mt NATURAL JOIN tags WHERE mt.module_ident = m.module_ident) AS subjects,
  ARRAY(
    SELECT row_to_json(history_info) FROM (
        SELECT concat_ws('.', m1.major_version, m1.minor_version) AS version,
            iso8601(m1.revised) AS revised, m1.submitlog AS changes,
            (SELECT row_to_json(publisher) AS publisher FROM (
                    SELECT id, email, firstname, othername, surname, fullname, title, suffix, website
                    FROM users WHERE users.id::text = m1.submitter
            ) publisher)
            FROM modules m1 WHERE m1.uuid = %(id)s::uuid AND m1.revised <= m.revised
            ORDER BY m1.revised DESC
    ) history_info) AS "history",
  ARRAY(SELECT word FROM modulekeywords AS mk NATURAL JOIN keywords WHERE mk.module_ident = m.module_ident) AS "keywords"
FROM modules m
  LEFT JOIN abstracts a on m.abstractid = a.abstractid
  LEFT JOIN modules p on m.parent = p.module_ident,
  licenses l
WHERE
  m.licenseid = l.licenseid AND
  m.uuid = %(id)s::uuid AND
  concat_ws('.', m.major_version, m.minor_version) = %(version)s
GROUP BY
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
  a.html, l.code, l.name, l.version, l.url,
  m.submitter, m.submitlog,
  p.uuid, "parentVersion", p.name, m.authors,
  m.licensors, m.maintainers, m.parentauthors, m.language
) combined_rows ;
"""

SQL_GET_TREE = """\
select string_agg(toc,'
'
) from (
WITH RECURSIVE t(node, title, path, value, depth, corder) AS (
    SELECT nodeid, title, ARRAY[nodeid], documentid, 1, ARRAY[childorder]
    FROM trees tr, modules m
    WHERE m.uuid = %(id)s::uuid
          and concat_ws('.',  m.major_version, m.minor_version) = %(version)s
          AND tr.documentid = m.module_ident
UNION ALL
    SELECT c1.nodeid, c1.title, t.path || ARRAY[c1.nodeid], c1.documentid, t.depth+1, t.corder || ARRAY[c1.childorder] /* Recursion */
    FROM trees c1 JOIN t ON (c1.parent_id = t.node)
    WHERE not nodeid = any (t.path)
)
SELECT
    REPEAT('    ', depth - 1) || '{"id":"' || COALESCE(m.uuid::text,'subcol') ||concat_ws('.', '@'||m.major_version, m.minor_version) ||'",' ||
      '"title":' || to_json(COALESCE(title,name)) ||
      CASE WHEN (depth < lead(depth,1,0) over(w)) THEN ', "contents":['
           WHEN (depth > lead(depth,1,0) over(w) AND lead(depth,1,0) over(w) = 0 AND m.uuid IS NULL) THEN ', "contents":[]}'||REPEAT(']}',depth - lead(depth,1,0) over(w) - 1)
           WHEN (depth > lead(depth,1,0) over(w) AND lead(depth,1,0) over(w) = 0 ) THEN '}'||REPEAT(']}',depth - lead(depth,1,0) over(w) - 1)
           WHEN (depth > lead(depth,1,0) over(w) AND lead(depth,1,0) over(w) != 0 AND m.uuid IS NULL) THEN ', "contents":[]}'||REPEAT(']}',depth - lead(depth,1,0) over(w))||','
           WHEN (depth > lead(depth,1,0) over(w) AND lead(depth,1,0) over(w) != 0 ) THEN '}'||REPEAT(']}',depth - lead(depth,1,0) over(w))||','
           WHEN m.uuid IS NULL THEN ', "contents":[]},'
           ELSE '},' END
      AS "toc"
FROM t left join modules m on t.value = m.module_ident
    WINDOW w as (ORDER BY corder) order by corder ) as tree
"""

SQL_GET_CONTENT = """\
select convert_from(file, 'utf-8')
from module_files natural join files
where module_ident = %(module_ident)s
      and filename = 'index.cnxml.html';
"""

SQL_GET_FILES = """\

"""
