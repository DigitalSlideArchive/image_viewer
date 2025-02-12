import AnnotationModel from '../models/AnnotationModel';

const Collection = girder.collections.Collection;
const {SORT_DESC} = girder.constants;

export default Collection.extend({
    resourceName: 'annotation',
    model: AnnotationModel,
    // this is a large number so that we probably never need to page
    // annotations.
    pageLimit: 10000,
    sortField: 'created',
    sortDir: SORT_DESC
});
