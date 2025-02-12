import ElementCollection from '../collections/ElementCollection';
import convert from '../annotations/convert';
import {convertFeatures} from '../annotations/convertFeatures';

import style from '../annotations/style.js';

const _ = girder._;
const AccessControlledModel = girder.models.AccessControlledModel;
const {getCurrentUser} = girder.auth;
const {restRequest} = girder.rest;
const MetadataMixin = girder.models.MetadataMixin;

/**
 * Define a backbone model representing an annotation.
 * An annotation contains zero or more "elements" or
 * geometric primitives that are represented in the
 * embedded "elements" attribute.  This attribute is
 * an "ElementCollection" that triggers events when
 * any of the "ElementModel"'s contained within change.
 *
 * This model listens to changes in the element collection
 * and updates its own attribute in response.  Users
 * should not modify the "elements" attribute directly.
 */
const AnnotationModel = AccessControlledModel.extend({
    resourceName: 'annotation',

    defaults: {
        annotation: {},
        minElements: 5000,
        maxDetails: 250000,
        maxCentroids: 2000000
    },

    initialize() {
        if (!this.get('updated') && getCurrentUser()) {
            this.attributes.updated = '' + Date.now(); // eslint-disable-line backbone/no-model-attributes
            this.attributes.updatedId = getCurrentUser().id; // eslint-disable-line backbone/no-model-attributes
        }
        this._region = {
            maxDetails: this.get('maxDetails'),
            minElements: this.get('minElements'),
            sort: 'size',
            sortdir: -1
        };
        /* amount of annotations to request compared to visible area.  1 will
         * request exactly the visible area of the map, 2 will get a region
         * twice as big in each direction. */
        this._viewArea = 3;
        this._elements = new ElementCollection(
            this.get('annotation').elements || []
        );
        this._elements.annotation = this;

        this.listenTo(this._elements, 'change add remove reset', () => {
            // copy the object to ensure a change event is triggered
            var annotation = _.extend({}, this.get('annotation'));

            annotation.elements = this._elements.toJSON();
            this.set('annotation', annotation);
        });
    },

    /**
     * Fetch the centroids and unpack the binary data.
     */
    fetchCentroids: function () {
        var url = (this.altUrl || this.resourceName) + '/' + this.get('_id');
        var restOpts = {
            url: url,
            data: {
                sort: 'size',
                sortdir: -1,
                centroids: true,
                limit: this.get('maxCentroids'),
                _: (this.get('updated') || this.get('created')) + '_' + this.get('_version')
            },
            xhrFields: {
                responseType: 'arraybuffer'
            },
            error: null
        };

        return restRequest(restOpts).done((resp) => {
            let dv = new DataView(resp);
            let z0 = 0, z1 = dv.byteLength - 1;
            for (; dv.getUint8(z0) && z0 < dv.byteLength; z0 += 1);
            for (; dv.getUint8(z1) && z1 >= 0; z1 -= 1);
            if (z0 >= z1) {
                throw new Error('invalid centroid data');
            }
            const json = new Uint8Array(z0 + dv.byteLength - z1 - 1);
            json.set(new Uint8Array(resp.slice(0, z0)), 0);
            json.set(new Uint8Array(resp.slice(z1 + 1)), z0);
            const result = JSON.parse(decodeURIComponent(escape(String.fromCharCode.apply(null, json))));
            const defaults = {
                default: {
                    fillColor: {r: 1, g: 120 / 255, b: 0},
                    fillOpacity: 0.8,
                    strokeColor: {r: 0, g: 0, b: 0},
                    strokeOpacity: 1,
                    strokeWidth: 1
                },
                rectangle: {
                    fillColor: {r: 176 / 255, g: 222 / 255, b: 92 / 255},
                    strokeColor: {r: 153 / 255, g: 153 / 255, b: 153 / 255},
                    strokeWidth: 2
                },
                ellipse: {
                    fillColor: {r: 176 / 255, g: 222 / 255, b: 92 / 255},
                    strokeColor: {r: 153 / 255, g: 153 / 255, b: 153 / 255},
                    strokeWidth: 2
                },
                circle: {
                    fillColor: {r: 176 / 255, g: 222 / 255, b: 92 / 255},
                    strokeColor: {r: 153 / 255, g: 153 / 255, b: 153 / 255},
                    strokeWidth: 2
                },
                polyline: {
                    strokeColor: {r: 1, g: 120 / 255, b: 0},
                    strokeOpacity: 0.5,
                    strokeWidth: 4
                },
                polyline_closed: {
                    fillColor: {r: 176 / 255, g: 222 / 255, b: 92 / 255},
                    strokeColor: {r: 153 / 255, g: 153 / 255, b: 153 / 255},
                    strokeWidth: 2
                }
            };
            result.props = result._elementQuery.props.map((props) => {
                const propsdict = {};
                result._elementQuery.propskeys.forEach((key, i) => {
                    propsdict[key] = props[i];
                });
                Object.assign(propsdict, style(propsdict));
                const type = propsdict.type + (propsdict.closed ? '_closed' : '');
                ['fillColor', 'strokeColor', 'strokeWidth', 'fillOpacity', 'strokeOpacity'].forEach((key) => {
                    if (propsdict[key] === undefined) {
                        propsdict[key] = (defaults[type] || defaults.default)[key];
                    }
                    if (propsdict[key] === undefined) {
                        propsdict[key] = defaults.default[key];
                    }
                });
                return propsdict;
            });
            dv = new DataView(resp, z0 + 1, z1 - z0 - 1);
            if (dv.byteLength !== result._elementQuery.returned * 28) {
                throw new Error('invalid centroid data size');
            }
            const centroids = {
                id: new Array(result._elementQuery.returned),
                x: new Float32Array(result._elementQuery.returned),
                y: new Float32Array(result._elementQuery.returned),
                r: new Float32Array(result._elementQuery.returned),
                s: new Uint32Array(result._elementQuery.returned)
            };
            let i, s;
            for (i = s = 0; s < dv.byteLength; i += 1, s += 28) {
                centroids.id[i] =
                    ('0000000' + dv.getUint32(s, false).toString(16)).substr(-8) +
                    ('0000000' + dv.getUint32(s + 4, false).toString(16)).substr(-8) +
                    ('0000000' + dv.getUint32(s + 8, false).toString(16)).substr(-8);
                centroids.x[i] = dv.getFloat32(s + 12, true);
                centroids.y[i] = dv.getFloat32(s + 16, true);
                centroids.r[i] = dv.getFloat32(s + 20, true);
                centroids.s[i] = dv.getUint32(s + 24, true);
            }
            result.centroids = centroids;
            result.data = {length: result._elementQuery.returned};
            if (result._elementQuery.count > result._elementQuery.returned) {
                result.partial = true;
            }
            this._centroids = result;
            return result;
        });
    },

    /**
     * Fetch a single resource from the server. Triggers g:fetched on success,
     * or g:error on error.
     * To ignore the default error handler, pass
     *     ignoreError: true
     * in your opts object.
     */
    fetch: function (opts) {
        if (this.altUrl === null && this.resourceName === null) {
            alert('Error: You must set an altUrl or a resourceName on your model.'); // eslint-disable-line no-alert
            return;
        }

        opts = opts || {};
        var restOpts = {
            url: (this.altUrl || this.resourceName) + '/' + this.get('_id'),
            /* Add our region request into the query */
            data: Object.assign({}, this._region, {_: (this.get('updated') || this.get('created')) + '_' + this.get('_version')})
        };
        if (opts.extraPath) {
            restOpts.url += '/' + opts.extraPath;
        }
        if (opts.ignoreError) {
            restOpts.error = null;
        }
        this._inFetch = true;
        if (this._refresh) {
            delete this._pageElements;
            delete this._centroids;
            this._refresh = false;
        }
        return restRequest(restOpts).done((resp) => {
            const annotation = resp.annotation || {};
            const elements = annotation.elements || [];

            this.set(resp);
            if (this._pageElements === undefined && resp._elementQuery) {
                this._pageElements = resp._elementQuery.count > resp._elementQuery.returned;
                if (this._pageElements) {
                    this._inFetch = 'centroids';
                    this.fetchCentroids().then(() => {
                        this._inFetch = true;
                        if (opts.extraPath) {
                            this.trigger('g:fetched.' + opts.extraPath);
                        } else {
                            this.trigger('g:fetched');
                        }
                        return null;
                    }).always(() => {
                        this._inFetch = false;
                        if (this._nextFetch) {
                            var nextFetch = this._nextFetch;
                            this._nextFetch = null;
                            nextFetch();
                        }
                        return null;
                    });
                } else {
                    this._nextFetch = null;
                }
            }
            if (this._inFetch !== 'centroids') {
                if (opts.extraPath) {
                    this.trigger('g:fetched.' + opts.extraPath);
                } else {
                    this.trigger('g:fetched');
                }
            }
            this._elements.reset(elements, _.extend({sync: true}, opts));
        }).fail((err) => {
            this.trigger('g:error', err);
        }).always(() => {
            if (this._inFetch !== 'centroids') {
                this._inFetch = false;
                if (this._nextFetch) {
                    var nextFetch = this._nextFetch;
                    this._nextFetch = null;
                    if (this._pageElements !== false) {
                        nextFetch();
                    }
                }
            }
        });
    },

    /**
     * Get/set for a refresh flag.
     *
     * @param {boolean} [val] If specified, set the refresh flag.  If not
     *    specified, return the refresh flag.
     * @returns {boolean|this}
     */
    refresh(val) {
        if (val === undefined) {
            return self._refresh;
        }
        self._refresh = val;
        return this;
    },

    /**
     * Perform a PUT or POST request on the annotation data depending
     * on whether the annotation is new or not.  This mirrors somewhat
     * the api of `Backbone.Model.save`.  For new models, the `itemId`
     * attribute is required.
     */
    save(options) {
        const data = _.extend({}, this.get('annotation'));
        let url;
        let method;
        const isNew = this.isNew();

        if (isNew) {
            if (!this.get('itemId')) {
                throw new Error('itemId is required to save new annotations');
            }
            url = `annotation?itemId=${this.get('itemId')}`;
            method = 'POST';
        } else {
            url = `annotation/${this.id}`;
            method = 'PUT';
            if (getCurrentUser()) {
                this.attributes.updated = '' + Date.now(); // eslint-disable-line backbone/no-model-attributes
                this.attributes.updatedId = getCurrentUser().id; // eslint-disable-line backbone/no-model-attributes
            }
        }

        if (this._pageElements === false || isNew) {
            this._pageElements = false;
            data.elements = _.map(data.elements, (element) => {
                element = _.extend({}, element);
                if (element.label && !element.label.value) {
                    delete element.label;
                }
                return element;
            });
        } else {
            delete data.elements;
            // we don't want to override an annotation with a partial response
            if (this._pageElements === true) {
                console.warn('Cannot save elements of a paged annotation');
            }
        }

        return restRequest({
            url,
            method,
            contentType: 'application/json',
            processData: false,
            data: JSON.stringify(data)
        }).done((annotation) => {
            if (isNew) {
                // the elements array does not come back with this request
                annotation.elements = (this.get('annotation') || {}).elements || [];
                this.set(annotation);
            }
            this.trigger('sync', this, annotation, options);
        });
    },

    /**
     * Perform a DELETE request on the annotation model and remove all
     * event listeners.  This mirrors the api of `Backbone.Model.destroy`
     * without the backbone specific options, which are not supported by
     * girder's base model either.
     */
    destroy(options) {
        this.stopListening();
        this.trigger('destroy', this, this.collection, options);
        return this.delete(options);
    },

    name() {
        return (this.get('annotation') || {}).name;
    },

    /**
     * Perform a DELETE request on the annotation model and reset the id
     * attribute, but don't remove event listeners.
     */
    delete(options) {
        this.trigger('g:delete', this, this.collection, options);
        let xhr = false;
        if (!this.isNew()) {
            if (getCurrentUser()) {
                this.attributes.updated = '' + Date.now(); // eslint-disable-line backbone/no-model-attributes
                this.attributes.updatedId = getCurrentUser().id; // eslint-disable-line backbone/no-model-attributes
            }
            xhr = restRequest({
                url: `annotation/${this.id}`,
                method: 'DELETE'
            });
        }
        this.unset('_id');
        return xhr;
    },

    /**
     * Return the annotation as a geojson FeatureCollection.
     *
     * WARNING: Not all annotations are representable in geojson.
     * Annotation types that cannot be converted will be ignored.
     */
    geojson() {
        const json = this.get('annotation') || {};
        const elements = json.elements || [];
        return convert(elements, {annotation: this.id});
    },

    /**
     * Return annotations that cannot be represented as geojson as geojs
     * features specifications.
     *
     * @param webglLayer: the parent feature layer.
     */
    non_geojson(layer) {
        const json = this.get('annotation') || {};
        const elements = json.elements || [];
        return convertFeatures(elements, {annotation: this.id}, layer);
    },

    /**
     * Return annotation elements that cannot be represented as geojs
     * features, such as image overlays.
     */
    overlays() {
        const overlayElementTypes = ['image', 'pixelmap'];
        const json = this.get('annotation') || {};
        const elements = json.elements || [];
        return elements.filter((element) => overlayElementTypes.includes(element.type));
    },

    /**
     * Set the view.  If we are paging elements, possibly refetch the elements.
     * Callers should listen for the g:fetched event to know when new elements
     * have been fetched.
     *
     * @param {object} bounds the corners of the visible region.  This is an
     *      object with left, top, right, bottom in pixels.
     * @param {number} zoom the zoom factor.
     * @param {number} maxZoom the maximum zoom factor.
     * @param {boolean} noFetch Truthy to not perform a fetch if the view
     *  changes.
     * @param {number} sizeX the maximum width to query.
     * @param {number} sizeY the maximum height to query.
     */
    setView(bounds, zoom, maxZoom, noFetch, sizeX, sizeY) {
        if (this._pageElements === false || this.isNew()) {
            return;
        }
        var width = bounds.right - bounds.left,
            height = bounds.bottom - bounds.top,
            xoverlap = (width * (this._viewArea - 1)) / 2,
            yoverlap = (height * (this._viewArea - 1)) / 2,
            minxoverlap = xoverlap / 2,
            minyoverlap = yoverlap / 2;
        var canskip = (this._region.left !== undefined &&
            bounds.left >= this._region.left + minxoverlap &&
            bounds.top >= this._region.top + minyoverlap &&
            bounds.right <= this._region.right - minxoverlap &&
            bounds.bottom <= this._region.bottom - minyoverlap &&
            Math.abs(this._lastZoom - zoom) < 1);
        if (canskip && !this._inFetch) {
            return;
        }
        if (this._pageElements || this._region.left !== undefined) {
            var lastRegion = Object.assign({}, this._region);
            this._region.left = Math.max(0, bounds.left - xoverlap);
            this._region.top = Math.max(0, bounds.top - yoverlap);
            this._region.right = Math.min(sizeX || 1e6, bounds.right + xoverlap);
            this._region.bottom = Math.min(sizeY || 1e6, bounds.bottom + yoverlap);
            this._lastZoom = zoom;
            /* Don't ask for a minimum size; we show centroids if the data is
             * incomplete. */
            if (['left', 'top', 'right', 'bottom', 'minimumSize'].every((key) => this._region[key] === lastRegion[key])) {
                return;
            }
        }
        if (noFetch) {
            return;
        }
        if (!this._nextFetch) {
            var nextFetch = () => {
                this.fetch();
            };
            if (this._inFetch) {
                this._nextFetch = nextFetch;
            } else {
                nextFetch();
            }
        }
    },

    /**
     * Return a backbone collection containing the annotation elements.
     */
    elements() {
        return this._elements;
    }
});

_.extend(AnnotationModel.prototype, MetadataMixin);

export default AnnotationModel;
