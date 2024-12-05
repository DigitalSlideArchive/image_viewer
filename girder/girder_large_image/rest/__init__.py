import collections
import json

from girder import logger
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import boundHandler
from girder.constants import AccessType, TokenScope
from girder.models.folder import Folder
from girder.models.item import Item


def addSystemEndpoints(apiRoot):  # noqa
    """
    This adds endpoints to routes that already exist in Girder.

    :param apiRoot: Girder api root class.
    """
    apiRoot.folder.route('GET', (':id', 'yaml_config', ':name'), getYAMLConfigFile)
    apiRoot.folder.route('PUT', (':id', 'yaml_config', ':name'), putYAMLConfigFile)

    origItemFind = apiRoot.item._find
    origFolderFind = apiRoot.folder._find

    @boundHandler(apiRoot.item)
    def altItemFind(self, folderId, text, name, limit, offset, sort, filters=None):
        if sort and sort[0][0][0] == '[':
            sort = json.loads(sort[0][0])
        recurse = False
        if text and text.startswith('_recurse_:'):
            recurse = True
            text = text.split('_recurse_:', 1)[1]
        group = None
        if text and text.startswith('_group_:') and len(text.split(':', 2)) >= 3:
            _, group, text = text.split(':', 2)
        if filters is None and text and text.startswith('_filter_:'):
            try:
                filters = json.loads(text.split('_filter_:', 1)[1].strip())
                text = None
            except Exception as exc:
                logger.warning('Failed to parse _filter_ from text field: %r', exc)
        if filters:
            try:
                logger.debug('Item find filters: %s', json.dumps(filters))
            except Exception:
                pass
        if recurse or group:
            return _itemFindRecursive(
                self, origItemFind, folderId, text, name, limit, offset, sort,
                filters, recurse, group)
        return origItemFind(folderId, text, name, limit, offset, sort, filters)

    @boundHandler(apiRoot.item)
    def altFolderFind(self, parentType, parentId, text, name, limit, offset, sort, filters=None):
        if sort and sort[0][0][0] == '[':
            sort = json.loads(sort[0][0])
        return origFolderFind(parentType, parentId, text, name, limit, offset, sort, filters)

    if not hasattr(origItemFind, '_origFunc'):
        apiRoot.item._find = altItemFind
        altItemFind._origFunc = origItemFind
        apiRoot.folder._find = altFolderFind
        altFolderFind._origFunc = origFolderFind


def _groupingPipeline(initialPipeline, cbase, grouping, sort=None):
    """
    Modify the recursive pipeline to add grouping and counts.

    :param initialPipeline: a pipeline to extend.
    :param cbase: a unique value for each grouping set.
    :param grouping: a dictionary where 'keys' is a list of data to group by
        and, optionally, 'counts' is a dictionary of data to count as keys and
        names where to add the results.  For instance, this could be
        {'keys': ['meta.dicom.PatientID'], 'counts': {
        'meta.dicom.StudyInstanceUID': 'meta._count.studycount',
        'meta.dicom.SeriesInstanceUID': 'meta._count.seriescount'}}
    :param sort: an optional list of (key, direction) tuples
    """
    for gidx, gr in enumerate(grouping['keys']):
        grsort = [(gr, 1)] + (sort or []) + [('_id', 1)]
        initialPipeline.extend([{
            '$match': {gr: {'$exists': True}},
        }, {
            '$sort': collections.OrderedDict(grsort),
        }, {
            '$group': {
                '_id': f'${gr}',
                'firstOrder': {'$first': '$$ROOT'},
            },
        }])
        groupStep = initialPipeline[-1]['$group']
        if not gidx and grouping['counts']:
            for cidx, (ckey, cval) in enumerate(grouping['counts'].items()):
                groupStep[f'count_{cbase}_{cidx}'] = {'$addToSet': f'${ckey}'}
                cparts = cval.split('.')
                centry = {cparts[-1]: {'$size': f'$count_{cbase}_{cidx}'}}
                for cidx in range(len(cparts) - 2, -1, -1):
                    centry = {
                        cparts[cidx]: {
                            '$mergeObjects': [
                                '$firstOrder.' + '.'.join(cparts[:cidx + 1]),
                                centry,
                            ],
                        },
                    }
                initialPipeline.append({'$set': {'firstOrder': {
                    '$mergeObjects': ['$firstOrder', centry]}}})
        initialPipeline.append({'$replaceRoot': {'newRoot': '$firstOrder'}})
    initialPipeline.append({'$set': {'meta._grouping': {
        'keys': grouping['keys'],
        'values': [f'${key}' for key in grouping['keys']],
    }}})


def _itemFindRecursive(  # noqa
        self, origItemFind, folderId, text, name, limit, offset, sort, filters,
        recurse=True, group=None):
    """
    If a recursive search within a folderId is specified, use an aggregation to
    find all folders that are descendants of the specified folder.  If there
    are any, then perform a search that matches any of those folders rather
    than just the parent.

    :param self: A reference to the Item() resource record.
    :param origItemFind: the original _find method, used as a fallback.

    For the remaining parameters, see girder/api/v1/item._find
    """
    from bson.objectid import ObjectId

    if folderId:
        user = self.getCurrentUser()
        if recurse:
            pipeline = [
                {'$match': {'_id': ObjectId(folderId)}},
                {'$graphLookup': {
                    'from': 'folder',
                    'connectFromField': '_id',
                    'connectToField': 'parentId',
                    'depthField': '_depth',
                    'as': '_folder',
                    'startWith': '$_id',
                }},
                {'$match': Folder().permissionClauses(user, AccessType.READ, '_folder.')},
                {'$group': {'_id': '$_folder._id'}},
            ]
            children = [ObjectId(folderId)] + next(Folder().collection.aggregate(pipeline))['_id']
        else:
            children = [ObjectId(folderId)]
        if len(children) > 1 or group:
            filters = (filters.copy() if filters else {})
            if text:
                filters['$text'] = {
                    '$search': text,
                }
            if name:
                filters['name'] = name
            filters['folderId'] = {'$in': children}
            if isinstance(sort, list):
                sort.append(('parentId', 1))

            # This is taken from girder.utility.acl_mixin.findWithPermissions,
            # except it adds a grouping stage
            initialPipeline = [
                {'$match': filters},
            ]
            if group is not None:
                if not isinstance(group, list):
                    group = [gr for gr in group.split(',') if gr]
                groups = []
                idx = 0
                while idx < len(group):
                    if group[idx] != '_count_':
                        if not len(groups) or groups[-1]['counts']:
                            groups.append({'keys': [], 'counts': {}})
                        groups[-1]['keys'].append(group[idx])
                        idx += 1
                    else:
                        if idx + 3 <= len(group):
                            groups[-1]['counts'][group[idx + 1]] = group[idx + 2]
                        idx += 3
                for gidx, grouping in enumerate(groups):
                    _groupingPipeline(initialPipeline, gidx, grouping, sort)
            fullPipeline = initialPipeline
            countPipeline = initialPipeline + [
                {'$count': 'count'},
            ]
            if sort is not None:
                fullPipeline.append({'$sort': collections.OrderedDict(sort)})
            if limit:
                fullPipeline.append({'$limit': limit + (offset or 0)})
            if offset:
                fullPipeline.append({'$skip': offset})

            logger.debug('Find item pipeline %r', fullPipeline)

            options = {
                'allowDiskUse': True,
                'cursor': {'batchSize': 0},
            }
            result = Item().collection.aggregate(fullPipeline, **options)

            def count():
                try:
                    return next(iter(
                        Item().collection.aggregate(countPipeline, **options)))['count']
                except StopIteration:
                    # If there are no values, this won't return the count, in
                    # which case it is zero.
                    return 0

            result.count = count
            result.fromAggregate = True
            return result
    return origItemFind(folderId, text, name, limit, offset, sort, filters)


@access.public(scope=TokenScope.DATA_READ)
@autoDescribeRoute(
    Description('Get a config file.')
    .notes(
        'This walks up the chain of parent folders until the file is found.  '
        'If not found, the .config folder in the parent collection or user is '
        'checked.\n\nAny yaml file can be returned.  If the top-level is a '
        'dictionary and contains keys "access" or "groups" where those are '
        'dictionaries, the returned value will be modified based on the '
        'current user.  The "groups" dictionary contains keys that are group '
        'names and values that update the main dictionary.  All groups that '
        'the user is a member of are merged in alphabetical order.  If a key '
        'and value of "\\__all\\__": True exists, the replacement is total; '
        'otherwise it is a merge.  If the "access" dictionary exists, the '
        '"user" and "admin" subdictionaries are merged if a calling user is '
        'present and if the user is an admin, respectively (both get merged '
        'for admins).')
    .modelParam('id', model=Folder, level=AccessType.READ)
    .param('name', 'The name of the file.', paramType='path')
    .errorResponse(),
)
@boundHandler()
def getYAMLConfigFile(self, folder, name):
    from .. import yamlConfigFile

    user = self.getCurrentUser()
    return yamlConfigFile(folder, name, user)


@access.public(scope=TokenScope.DATA_READ)
@autoDescribeRoute(
    Description('Get a config file.')
    .notes(
        'This replaces or creates an item in the specified folder with the '
        'specified name containing a single file also of the specified '
        'name.  The file is added to the default assetstore, and any existing '
        'file may be permanently deleted.')
    .modelParam('id', model=Folder, level=AccessType.READ)
    .param('name', 'The name of the file.', paramType='path')
    .param('user_context', 'Whether these settings should only apply to the '
           'current user.', paramType='query', dataType='boolean', default=False)
    .param('config', 'The contents of yaml config file to validate.',
           paramType='body'),
)
@boundHandler()
def putYAMLConfigFile(self, folder, name, config, user_context):
    from .. import yamlConfigFileWrite

    user = self.getCurrentUser()
    if not user_context:
        Folder().requireAccess(folder, user, AccessType.WRITE)
    config = config.read().decode('utf8')
    return yamlConfigFileWrite(folder, name, user, config, user_context)
