import ElementModel from '../models/ElementModel';

const Backbone = girder.Backbone;

export default Backbone.Collection.extend({
    model: ElementModel,
    comparator: undefined
});
