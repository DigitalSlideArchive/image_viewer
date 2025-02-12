import Vue from 'vue';

import largeImageConfig from './configView';
import * as viewers from './imageViewerWidget';

import imageViewerSelectWidget from '../templates/imageViewerSelectWidget.pug';
import '../stylesheets/imageViewerSelectWidget.styl';

import FrameSelector from '../widgets/FrameSelector.vue';
import DualInput from '../widgets/DualInput.vue';
import CompositeLayers from '../widgets/CompositeLayers.vue';
import HistogramEditor from '../widgets/HistogramEditor.vue';
import colors from '../widgets/colors.json';
import PresetsMenu from '../vue/components/PresetsMenu.vue';

const $ = girder.$;
const _ = girder._;
const {wrap} = girder.utilities.PluginUtils;
const eventStream = girder.utilities.EventStream;
const ItemView = girder.views.body.ItemView;
const View = girder.views.View;
const {restRequest} = girder.rest;

wrap(ItemView, 'render', function (render) {
    // ItemView is a special case in which rendering is done asynchronously,
    // so we must listen for a render event.
    this.once('g:rendered', function () {
        if (this.model.get('largeImage') &&
            this.model.get('largeImage').fileId) {
            this.imageViewerSelect = new ImageViewerSelectWidget({
                el: $('<div>', {class: 'g-item-image-viewer-select'})
                    .insertAfter(this.$('.g-item-info')),
                parentView: this,
                imageModel: this.model
            });
        }
    }, this);
    render.call(this);
});

var ImageViewerSelectWidget = View.extend({
    events: {
        'change select.image-viewer-control': function (event) {
            this._selectViewer(event.target.value);
        },
        'keyup select.image-viewer-control': function (event) {
            this._selectViewer(event.target.value);
        },
        'input #image-frame,#image-frame-number': function (event) {
            this.frameUpdate(event.target);
        }
    },

    initialize: function (settings) {
        this.itemId = settings.imageModel.id;
        this.model = settings.imageModel;
        this.currentViewer = null;
        largeImageConfig.getSettings(() => {
            largeImageConfig.getConfigFile(this.model.get('folderId')).done((config) => {
                this._liConfig = config || {};
                this.render();
            });
        });
    },

    render: function () {
        if (largeImageConfig.settings['large_image.show_viewer'] === false) {
            return this;
        }
        this.$el.html(imageViewerSelectWidget({
            viewers: largeImageConfig.viewers
        }));
        var name = largeImageConfig.settings['large_image.default_viewer'];
        if (_.findWhere(largeImageConfig.viewers, {name: name}) === undefined) {
            name = largeImageConfig.viewers[0].name;
        }
        this.$('select.form-control.image-viewer-control').val(name);
        this._selectViewer(name);
        return this;
    },

    _createVue(imageMetadata, frameUpdate) {
        const el = this.$('#vue-container').get(0);
        const getFrameHistogram = (params) => {
            params = Object.assign({}, params);
            restRequest({
                type: 'GET',
                url: 'item/' + this.itemId + '/tiles/histogram',
                data: params
            }).then((response) => {
                const frameHistograms = this.vueApp._props.frameHistograms || {};
                frameHistograms[params.frame] = response;
                this.vueApp._props.frameHistograms = Object.assign({}, frameHistograms);
                return undefined;
            });
        };
        CompositeLayers.components = {HistogramEditor};
        FrameSelector.components = {DualInput, CompositeLayers, HistogramEditor, PresetsMenu};
        const Component = Vue.extend(FrameSelector);
        const vm = new Component({
            el,
            propsData: {
                currentFrame: 0,
                itemId: this.itemId,
                imageMetadata: imageMetadata,
                frameUpdate,
                liConfig: this._liConfig,
                frameHistograms: undefined,
                getFrameHistogram,
                colors
            }
        });
        this.vueApp = vm;
    },

    _selectViewer: function (viewerName) {
        if (this.currentViewer && this.currentViewer.name === viewerName) {
            return;
        }
        if (this.currentViewer) {
            this.currentViewer.destroy();
            this.currentViewer = null;
        }
        // hide general image controls; individual viewers must enable them
        this.$('.image-controls>div').toggleClass('hidden', true);
        this._frameUpdate = null;
        this.$('.image-viewer').toggleClass('hidden', true);

        var viewer = _.findWhere(largeImageConfig.viewers,
            {name: viewerName});
        var ViewerType = viewers[viewer.type];
        // use dedicated elements for each viewer for now in case they aren't
        // fully cleaned up
        var viewerEl = this.$('#' + viewerName);
        viewerEl.toggleClass('hidden', false);
        this.currentViewer = new ViewerType({
            el: viewerEl,
            parentView: this,
            itemId: this.itemId,
            model: this.model,
            setFrames: _.bind(this.setFrames, this)
        });
        this.currentViewer.name = viewerName;
    },

    /**
     * If a viewer supports handling multi-frame images, call this as part of
     * this initial render to expose frame controls.
     *
     * @param {object} metadata A dictionary of metadata that might contain a
     *      list of frames.
     * @param {function} frameUpdate a function to call with the current frame
     *      number when it changes.  This is called with an initial frame
     *      number if the frame controls are available.  It is never called if
     *      there is only one frame.
     */
    setFrames: function (metadata, frameUpdate) {
        this.$('.image-controls>div').toggleClass('hidden', false);
        // Vue frame control
        this._createVue(metadata, frameUpdate);
    },

    /**
     * Handle a change in a frame control.
     */
    frameUpdate: function (ctrl) {
        ctrl = $(ctrl);
        var frame = ctrl.val();
        this.$('#image-frame,#image-frame-number').val(frame);
        if (this._frameUpdate) {
            this._frameUpdate(frame);
        }
    }
});

wrap(ItemView, 'initialize', function (initialize) {
    this.listenTo(eventStream, 'g:event.large_image.finished_image_item', () => {
        this.model.unset('largeImage');
        this.model.fetch();
    });
    initialize.apply(this, _.rest(arguments));
});

export default ImageViewerSelectWidget;
