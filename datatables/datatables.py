# -*- coding: utf-8 -*-
from sqlalchemy.sql.expression import asc, desc
from sqlalchemy.sql import or_, and_
from sqlalchemy.orm.properties import RelationshipProperty
from sqlalchemy.sql.expression import cast
from sqlalchemy import String
import logging

from collections import namedtuple

ColumnTuple = namedtuple('ColumnDT', ['column_name', 'mData', 'search_like', 'filter'])
log = logging.getLogger(__name__)


def get_attr(sqla_object, attribute):
    """Returns the value of an attribute of an SQLAlchemy entity
    """
    output = sqla_object
    log.debug('SQL object dir - %s', dir(sqla_object.properties))
    log.debug('Value of arch in properties - %s' % sqla_object.properties.arch)
    log.debug('Attribute value - %s', attribute)
    previous = ''
    for x in attribute.split('.'):
        if hasattr(output, x):
            output = getattr(output, x)
        elif previous:
            if hasattr(output, previous + '.' + x):
                output = getattr(output, previous + '.' + x)
        else:
            previous = x

    return output


class ColumnDT(ColumnTuple):
    """Class defining a DataTables Column with a ColumnTuple:

    :param column_name: name of the column as defined by the SQLAlchemy model
    :type column_name: str
    :param mData: name of the mData property as defined in the DataTables javascript options (default None)
    :type mData: str
    :param search_like: search criteria to like on without forgetting to escape the '%' character
    :type search_like: str
    :param filter: the method needed to be executed on the cell values of the column
    as an equivalent of a jinja2 filter (default None)
    :type filter: a callable object

    :returns: a ColumnDT object
    """
    def __new__(cls, column_name, mData=None, search_like=None, filter=str):
        """
        On creation, sets default None values for mData and string value for
        filter (cause: Object representation is not JSON serializable)
        """
        return super(ColumnDT, cls).__new__(cls, column_name, mData, search_like, filter)


class DataTables:
    """Class defining a DataTables object with:

    :param request: request containing the GET values, specified by the
    datatable for filtering, sorting and paging
    :type request: pyramid.request
    :param sqla_object: your SQLAlchemy table object
    :type sqla_object: sqlalchemy.ext.declarative.DeclarativeMeta
    :param query: the query wanted to be seen in the the table
    :type query: sqlalchemy.orm.query.Query
    :param columns: columns specification for the datatables
    :type columns: list

    :returns: a DataTables object
    """
    def __init__(self, request, sqla_object, query, columns):
        """Initializes the object with the attributes needed, and runs the query
        """
        self.request_values = request.GET
        self.sqla_object = sqla_object
        self.query = query
        self.columns = columns
        self.results = None

        # total in the table after filtering
        self.cardinality_filtered = 0

        # total in the table unfiltered
        self.cardinality = 0

        self.run()

    def output_result(self):
        """Outputs the results in the format needed by DataTables
        """
        output = {}
        output['sEcho'] = str(int(self.request_values['sEcho']))
        output['iTotalRecords'] = str(self.cardinality)
        output['iTotalDisplayRecords'] = str(self.cardinality_filtered)

        output['aaData'] = self.results

        return output

    def run(self):
        """Launch filtering, sorting and paging processes to output results
        """
        # count before filtering
        self.cardinality = self.query.count()

        # the term entered in the datatable's search box
        self.filtering()

        # field chosen to sort on
        self.sorting()

        # pages have a 'start' and 'length' attributes
        self.paging()

        # fetch the result of the queries
        self.results = self.query.all()

        #return formatted results with correct filters applied
        formatted_results = []
        for i in range(len(self.results)):
            row = dict()
            for j in range(len(self.columns)):
                col = self.columns[j]
                tmp_row = get_attr(self.results[i], col.column_name)
                if col.filter:
                    tmp_row = col.filter(tmp_row)
                row[col.mData if col.mData else str(j)] = tmp_row
            formatted_results.append(row)

        self.results = formatted_results

    def filtering(self):
        """Construct the query, by adding filtering(LIKE) on all columns when the datatable's search box is used
        """
        search_value = self.request_values.get('sSearch')
        condition = None
        def search(idx, col):
            tmp_column_name = col.column_name.split('.')
            #log.debug('Value of tmp_column_name in filtering - %s', tmp_column_name)
            obj = getattr(self.sqla_object, tmp_column_name[0])
            if not hasattr(obj, "property"): # Ex: hybrid_property or property
                #log.debug('Filtering on property or hybrid_property')
                sqla_obj = self.sqla_object
                column_name = col.column_name
            elif isinstance(obj.property, RelationshipProperty): #Ex: ForeignKey
                # Ex: address.description
                log.debug('Filtering on ForeignKey')
                sqla_obj = obj.mapper.class_
                if tmp_column_name[1] in ['com', 'org']:  # Namespace column has periods
                    column_name = ".".join(tmp_column_name[1:])
                else:
                    column_name = "".join(tmp_column_name[1:])
                if not column_name:
                    # find first primary key
                    column_name = obj.property.table.primary_key.columns \
                        .values()[0].name
            else:
                sqla_obj = self.sqla_object
                column_name = col.column_name
            #log.debug('Returning column_name from filtering - %s' % column_name)
            return sqla_obj, column_name

        if search_value:
            conditions = []
            for idx, col in enumerate(self.columns):
                #log.debug('Value of request value bSearchable_%s is %s', idx, self.request_values.get('bSearchable_%s' % idx))
                if self.request_values.get('bSearchable_%s' % idx) in (
                        True, 'true'):
                    sqla_obj, column_name = search(idx, col)
                    log.debug('Value of getattr sqlobj column_name - %s', str(getattr(sqla_obj, column_name)))
                    conditions.append(cast(get_attr(sqla_obj, column_name), String).ilike('%%%s%%' % search_value))
            condition = or_(*conditions)
        conditions = []
        for idx, col in enumerate(self.columns):
            #log.debug('Debug filtering idx - %r, col - %r', idx, col)
            #log.debug('Value for sSearch_%s is %s', idx, self.request_values.get('sSearch_%s' % idx))
            if self.request_values.get('sSearch_%s' % idx):
                #log.debug('Found filter request for idx - %r, col - %r', idx, col)
                search_value2 = self.request_values.get('sSearch_%s' % idx)
                #log.debug('Set search_value2 - %r', search_value2)
                sqla_obj, column_name = search(idx, col)
                #log.debug('Values for sqla_obj - %r, column_name - %r', sqla_obj, column_name)

                if col.search_like:
                    #log.debug('Value of col.search_like was True')
                    #log.debug('Getting dir on sqla_obj - %s', dir(sqla_obj))
                    #log.debug('Value of get_attr sqla_obj column_name - %s, Value of search_value2 - %s', get_attr(sqla_obj, column_name), search_value2)
                    conditions.append(cast(get_attr(sqla_obj, column_name), String).like(col.search_like % search_value2))
                else:
                    #log.debug('Value of col.search_like was not True')
                    conditions.append(cast(get_attr(sqla_obj, column_name), String).__eq__(search_value2))
                    #log.debug('Value of conditions is %r', conditions)

                if condition is not None:
                    #log.debug('Value of condition is not None and value is %r', condition)
                    condition = and_(condition, and_(*conditions))
                    #log.debug('Value of condition after is %r', condition)
                else:
                    #log.debug('Value of condition is None')
                    condition= and_(*conditions)
                    #log.debug('Value of condition after is %r', condition)

        if condition is not None:
            #log.debug('Value of condition is not None and is %s', condition)
            self.query = self.query.filter(condition)
            # count after filtering
            self.cardinality_filtered = self.query.count()
            #log.debug('Values of self.query - %s, self.cardinality_filtered - %r', self.query.as_scalar(), self.cardinality_filtered)
        else:
            self.cardinality_filtered = self.cardinality
            #log.debug('Value of condition was None and self.cardinality_filtered is %r', self.cardinality_filtered)

    def sorting(self):
        """Construct the query, by adding sorting(ORDER BY) on the columns needed to be applied on
        """
        sorting = []

        Order = namedtuple('order', ['name', 'dir'])

        if self.request_values.get('iSortCol_0') \
            and self.request_values.get('iSortingCols') > 0:

            for i in range(int(self.request_values['iSortingCols'])):
                sorting.append(Order( self.columns[int(self.request_values['iSortCol_'+str(i)])].column_name,
                        self.request_values['sSortDir_'+str(i)]))

        for sort in sorting:
            tmp_sort_name = sort.name.split('.')
            obj = getattr(self.sqla_object, tmp_sort_name[0])
            if not hasattr(obj, "property"): #hybrid_property or property
                #log.debug('Sort value is hybrid_property or property - %s', dir(obj))
                sort_name = sort.name

                if hasattr(self.sqla_object, "__tablename__"):
                    tablename = self.sqla_object.__tablename__
                else:
                    tablename = self.sqla_object.__table__.name
            elif isinstance(obj.property, RelationshipProperty): # Ex: ForeignKey
                 # Ex: address.description => description => addresses.description
                #log.debug('Sort value is a foreign key - %s', str(obj.property))
                sort_name = "".join(tmp_sort_name[1:])
                if tmp_sort_name[1] in ['com', 'org']:  # Namespace column has periods
                    sort_name = '`' + ".".join(tmp_sort_name[1:]) + '`'
                #log.debug('Value of tmp_sort_name - %s sort_name - %s', tmp_sort_name, sort_name)
                if not sort_name:
                    # Find first primary key
                    sort_name = obj.property.table.primary_key.columns \
                            .values()[0].name
                tablename = obj.property.table.name
            else: #-> ColumnProperty
                #log.debug('Sort value is column property - %s', sort.name)
                sort_name = sort.name

                if hasattr(self.sqla_object, "__tablename__"):
                    tablename = self.sqla_object.__tablename__
                else:
                    tablename = self.sqla_object.__table__.name

            sort_name = "%s.%s" % (tablename, sort_name)
            self.query = self.query.order_by(
                asc(sort_name) if sort.dir == 'asc' else desc(sort_name))

    def paging(self):
        """Construct the query, by slicing the results in order to limit rows showed on the page, and paginate the rest
        """
        pages = namedtuple('pages', ['start', 'length'])

        if (self.request_values['iDisplayStart'] ) \
            and (self.request_values['iDisplayLength'] != -1 ):
            pages.start = int(self.request_values['iDisplayStart'])
            pages.length = int(self.request_values['iDisplayLength'])

        offset = pages.start + pages.length
        self.query = self.query.slice(pages.start, offset)
