const Backbone = girder.Backbone;

/**
 * Define a "view model" representing an annotation element
 * (an individual shape.  This model does not support REST
 * calls such as save/fetch/sync/delete because annotation
 * elements don't have endpoints.  Instead this model exists
 * to support editing of the AnnotationModel on the client.
 */
export default Backbone.Model.extend({
    idAttribute: 'id'
});
