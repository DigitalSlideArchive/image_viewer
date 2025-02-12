/**
 * Given metadata on a tile source, a GeoJS tileLayer,  and a set of options,
 * add a function to the layer `setFrameQuad(<frame>)` that will, if possible,
 * set the baseQuad to a cropped section of an image that contains excerpts of
 * all frames.
 *
 * @param {object} tileinfo The metadata of the source image.  This expects
 *   ``sizeX`` and ``sizeY`` to be the width and height of the image and
 *   ``frames`` to contain a list of the frames of the image or be undefined if
 *   there is only one frame.
 * @param {geo.tileLayer} layer The GeoJS layer to add the function to.  This
 *   is also used to get a maximal texture size if the layer is a webGL
 *   layer.
 * @param {object} options Additional options for the function.  This must
 *   minimally include ``baseUrl``.
 * @param {string} options.baseUrl The reference to the tile endpoint, e.g.,
 *   <url>/api/v1/item/<item id>/tiles.
 * @param {string} options.restRequest A backbone-like ajax handler function.
 * @param {string} options.restUrl A reference to the tile endpoint as used by
 *   the restRequest function, e.g., item/<item id>/tiles.
 * @param {string} [options.format='encoding=JPEG&jpegQuality=85&jpegSubsampling=1']
 *   The compression and format for the texture.
 * @param {string} [options.query] Additional query options to add to the
 *   tile_frames endpoint, e.g. 'style={"min":"min","max":"max"}'.  Do not
 *   include framesAcross or frameList.  You must specify 'cache=true' if
 *   that is desired.
 * @param {number} [options.frameBase=0] Starting frame number used.
 * @param {number} [options.frameStride=1] Only use every ``frameStride`` frame
 *   of the image.
 * @param {number} [options.frameGroup=1] If above 1 and multiple textures are
 *   used, each texture will have an even multiple of the group size number of
 *   frames.  This helps control where texture loading transitions occur.
 * @param {number} [options.frameGroupFactor=4] If ``frameGroup`` would reduce
 *   the size of the tile images beyond this factor, don't use it.
 * @param {number} [options.frameGroupStride=1] If ``frameGroup`` is above 1
 *  and multiple textures are used, then the frames are reordered based on this
 *  stride value.
 * @param {number} [options.maxTextureSize] Limit the maximum texture size to a
 *   square of this size.  The size is also limited by the WebGL maximum
 *   size for webgl-based layers or 8192 for canvas-based layers.
 * @param {number} [options.maxTextures=1] If more than one, allow multiple
 *   textures to increase the size of the individual frames.  The number of
 *   textures will be capped by ``maxTotalTexturePixels`` as well as this
 *   number.
 * @param {number} [options.maxTotalTexturePixels=1073741824] Limit the
 *   maximum texture size and maximum number of textures so that the combined
 *   set does not exceed this number of pixels.
 * @param {number} [options.alignment=16] Individual frames are buffer to an
 *   alignment of this maxy pixels.  If JPEG compression is used, this should
 *   be 8 for monochrome images or jpegs without subsampling, or 16 for jpegs
 *   with moderate subsampling to avoid compression artifacts from leaking
 *   between frames.
 * @param {number} [options.adjustMinLevel=true] If truthy, adjust the tile
 *   layer's minLevel after the quads are loaded.
 * @param {number} [options.maxFrameSize] If set, limit the maximum width and
 *   height of an individual frame to this value.
 * @param {string} [options.crossOrigin] If specified, use this as the
 *   crossOrigin policy for images.
 * @param {string} [options.progress] If specified, a function to call whenever
 *   a texture image is loaded.  This is also called before the first load.
 * @param {boolean} [options.redrawOnFirstLoad=true] If truthy, redraw the
 *   layer after the base quad is first loaded if a frame value has been set.
 */
function setFrameQuad(tileinfo, layer, options) {
    layer.setFrameQuad = function () { };
    if (!tileinfo || !tileinfo.sizeX || !tileinfo.sizeY || !options || !options.baseUrl) {
        return;
    }
    let maxTextureSize;
    try {
        maxTextureSize = layer.renderer()._maxTextureSize || layer.renderer().constructor._maxTextureSize;
    } catch (err) { }
    options = Object.assign({}, {maxTextureSize: Math.min(8192, maxTextureSize || 8192)}, options);
    const status = {
        tileinfo: tileinfo,
        options: options,
        images: [],
        src: [],
        quads: [],
        frames: ['placeholder'],
        framesToIdx: {},
        loadedCount: 0
    };
    const qiOptions = Object.assign({}, options);
    ['restRequest', 'restUrl', 'baseUrl', 'crossOrigin', 'progress', 'redrawOnFirstLoad'].forEach((k) => delete qiOptions[k]);
    options.restRequest({
        type: 'GET',
        url: `${options.restUrl}/tile_frames/quad_info`,
        data: qiOptions
    }).then((data) => {
        status.quads = data.quads;
        status.frames = data.frames;
        status.framesToIdx = data.framesToIdx;
        for (let idx = 0; idx < data.src.length; idx += 1) {
            const img = new Image();
            for (let qidx = 0; qidx < data.quads.length; qidx += 1) {
                if (data.quadsToIdx[qidx] === idx) {
                    status.quads[qidx].image = img;
                }
            }
            if (options.baseUrl.indexOf(':') >= 0 && options.baseUrl.indexOf('/') === options.baseUrl.indexOf(':') + 1) {
                img.crossOrigin = options.crossOrigin || 'anonymous';
            }
            const params = Object.keys(data.src[idx]).map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(data.src[idx][k])).join('&');
            const src = `${options.baseUrl}/tile_frames?` + params;
            status.src.push(src);
            if (idx === data.src.length - 1) {
                img.onload = function () {
                    status.loadedCount += 1;
                    status.loaded = true;
                    if (layer._options && layer._options.minLevel !== undefined && (options.adjustMinLevel === undefined || options.adjustMinLevel) && status.minLevel && status.minLevel > layer._options.minLevel) {
                        layer._options.minLevel = Math.min(layer._options.maxLevel, status.minLevel);
                    }
                    if (options.progress) {
                        try {
                            options.progress(status);
                        } catch (err) {}
                    }
                    if (status.frame !== undefined) {
                        layer.baseQuad = Object.assign({}, status.quads[status.framesToIdx[status.frame]]);
                        if (options.redrawOnFirstLoad || options.redrawOnFirstLoad === undefined) {
                            layer.draw();
                        }
                    }
                };
            } else {
                ((idx) => {
                    img.onload = function () {
                        status.loadedCount += 1;
                        status.images[idx + 1].src = status.src[idx + 1];
                        if (options.progress) {
                            try {
                                options.progress(status);
                            } catch (err) {}
                        }
                    };
                })(idx);
            }
            status.images.push(img);
        }
        status.images[0].src = status.src[0];
        if (options.progress) {
            try {
                options.progress(status);
            } catch (err) {}
        }
        return status;
    });
    layer.setFrameQuad = function (frame) {
        if (frame === undefined) {
            layer.baseQuad = undefined;
        } else if (status.framesToIdx[frame] !== undefined && status.loaded) {
            layer.baseQuad = Object.assign({}, status.quads[status.framesToIdx[frame]]);
        }
        status.frame = frame;
    };
    layer.setFrameQuad.status = status;
}

export {setFrameQuad};
