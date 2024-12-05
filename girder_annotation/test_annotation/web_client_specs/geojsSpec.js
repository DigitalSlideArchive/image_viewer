/* globals beforeEach, afterEach, describe, it, expect, sinon, girder, Backbone, _, girderTest, $, runs, waitsFor */
/* eslint-disable camelcase, no-new */

girderTest.importPlugin('jobs', 'worker', 'large_image', 'large_image_annotation');
girderTest.addScripts([
    '/static/built/plugins/large_image/extra/sinon.js'
]);

girderTest.startApp();

$(function () {
    var itemId, annotationId, overlayAnnotationId, interactor;

    function closeTo(a, b, tol) {
        var i;
        tol = tol || 6;
        expect(a.length).toBe(b.length);
        for (i = 0; i < a.length; i += 1) {
            expect(a[i]).toBeCloseTo(b[i], tol);
        }
    }

    describe('setup', function () {
        it('create the admin user', function () {
            girderTest.createUser(
                'admin', 'admin@email.com', 'Admin', 'Admin', 'testpassword')();
        });
        it('go to collections page', function () {
            runs(function () {
                $("a.g-nav-link[g-target='collections']").click();
            });

            waitsFor(function () {
                return $('.g-collection-create-button:visible').length > 0;
            }, 'navigate to collections page');

            runs(function () {
                expect($('.g-collection-list-entry').length).toBe(0);
            });
        });
        it('create collection', girderTest.createCollection('test', '', 'image'));
        it('upload test file', function () {
            girderTest.waitForLoad();
            runs(function () {
                $('.g-folder-list-link:first').click();
            });
            girderTest.waitForLoad();
            runs(function () {
                girderTest.binaryUpload('${large_image}/../../test/test_files/small_la.tiff'); // eslint-disable-line no-template-curly-in-string
            });
            girderTest.waitForLoad();
            runs(function () {
                itemId = $('.large_image_thumbnail img').prop('src').match(/\/item\/([^/]*)/)[1];
            });
        });
        it('upload test annotation', function () {
            runs(function () {
                girder.rest.restRequest({
                    url: 'annotation?itemId=' + itemId,
                    contentType: 'application/json',
                    processData: false,
                    type: 'POST',
                    data: JSON.stringify({
                        name: 'test annotation',
                        elements: [{
                            type: 'rectangle',
                            center: [200, 200, 0],
                            width: 400,
                            height: 400,
                            rotation: 0
                        }]
                    })
                }).then(function (resp) {
                    annotationId = resp._id;
                    return null;
                });
            });
            waitsFor(function () {
                return annotationId !== undefined;
            });
            girderTest.waitForLoad();
            runs(function () {
                expect(annotationId).toBeDefined();
            });
        });
        it('upload test overlay annotation', function () {
            runs(function () {
                girder.rest.restRequest({
                    url: 'annotation?itemId=' + itemId,
                    contentType: 'application/json',
                    processData: false,
                    type: 'POST',
                    data: JSON.stringify({
                        name: 'test overlay annotation',
                        elements: [{
                            type: 'image',
                            girderId: itemId,
                            opacity: 0.5,
                            transform: {
                                xoffset: 10,
                                yoffset: 15
                            }
                        }]
                    })
                }).then(function (resp) {
                    overlayAnnotationId = resp._id;
                    return null;
                });
            });
            waitsFor(function () {
                return overlayAnnotationId !== undefined;
            });
            girderTest.waitForLoad();
            runs(function () {
                expect(overlayAnnotationId).toBeDefined();
            });
        });
    });

    describe('Geojs viewer', function () {
        var girder, large_image, $el, GeojsViewer, viewer, annotation, overlayAnnotation, featureSpy, largeImageAnnotation;

        beforeEach(function () {
            girder = window.girder;
            large_image = girder.plugins.large_image;
            largeImageAnnotation = girder.plugins.large_image_annotation;
            GeojsViewer = large_image.views.imageViewerWidget.geojs;
        });

        it('script is loaded', function () {
            $el = $('<div/>').appendTo('body')
                .css({
                    width: '400px',
                    height: '300px'
                });
            viewer = new GeojsViewer({
                el: $el,
                itemId: itemId,
                parentView: null,
                hoverEvents: true
            });
            viewer.once('g:beforeFirstRender', function () {
                try {
                    window.geo.util.mockWebglRenderer();
                } catch (err) {
                    // if this is already mocked, do nothing.
                }
            });
            waitsFor(function () {
                return $('.geojs-layer.active').length >= 1;
            }, 'viewer to load');
            runs(function () {
                expect(viewer.viewer.size()).toEqual({
                    width: 400,
                    height: 300
                });
                interactor = viewer.viewer.interactor();
            });
        });

        it('drawAnnotation', function () {
            var setViewSpy, firstCount;
            runs(function () {
                annotation = new largeImageAnnotation.models.AnnotationModel({
                    _id: annotationId
                });
                annotation.fetch();
            });

            girderTest.waitForLoad();
            runs(function () {
                setViewSpy = sinon.spy(annotation, 'setView');
                viewer.drawAnnotation(annotation);
                viewer.viewer.zoom(5);
            });

            girderTest.waitForLoad();
            runs(function () {
                expect(viewer._annotations[annotationId]).toBeDefined();
                // geojs makes two features for a polygon
                expect(viewer._annotations[annotationId].features.length >= 1).toBe(true);

                featureSpy = sinon.spy(viewer._annotations[annotationId].features[0], '_exit');

                sinon.assert.called(annotation.setView);
                firstCount = setViewSpy.callCount;
                viewer.viewer.zoomRange({max: 12});
                viewer.viewer.zoom(12);
                viewer.viewer.zoom(1);
                expect(setViewSpy.callCount).toBe(firstCount + 2);
            });
        });

        it('draw overlay', function () {
            var projStringSpy;
            runs(function () {
                overlayAnnotation = new largeImageAnnotation.models.AnnotationModel({
                    _id: overlayAnnotationId
                });
                overlayAnnotation.fetch();
            });
            girderTest.waitForLoad();
            runs(function () {
                projStringSpy = sinon.spy(viewer, '_getOverlayTransformProjString');
                viewer.drawAnnotation(overlayAnnotation);
            });
            girderTest.waitForLoad();
            runs(function () {
                const annotationRecord = viewer._annotations[overlayAnnotationId] || undefined;
                expect(annotationRecord).toBeDefined();
                expect(projStringSpy.callCount).toBe(1);
            });
        });

        it('generates pixelmap layer parameters', function () {
            const overlayMetadata = {
                sizeX: 500,
                sizeY: 500,
                tileWidth: 256,
                tileHeight: 256,
                levels: viewer.levels
            };
            const overlayId = '012345678901234567890123';
            const pixelMapElement = {
                type: 'pixelmap',
                id: '00001111222233334444',
                opacity: 0.5,
                girderId: overlayId,
                boundaries: false,
                values: [0, 1, 0, 1, 0, 1],
                categories: [
                    {fillColor: '#000000'},
                    {fillColor: '#ffffff'}
                ]
            };
            const pixelmapLayerParams = viewer._generateOverlayLayerParams(overlayMetadata, overlayId, pixelMapElement);
            const expectedUrl = 'api/v1/item/' + overlayId + '/tiles/zxy/{z}/{x}/{y}?encoding=PNG';
            expect(pixelmapLayerParams.url).toBe(expectedUrl);
            expect(pixelmapLayerParams.data).toEqual(pixelMapElement.values);

            pixelMapElement.boundaries = true;
            const pixelmapLayerParamsWithBoundaries = viewer._generateOverlayLayerParams(overlayMetadata, overlayId, pixelMapElement);
            const expectedDataArray = [0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1];
            expect(pixelmapLayerParamsWithBoundaries.data).toEqual(expectedDataArray);
        });

        it('mouse over events', function () {
            var mouseon, mouseover, context = {};
            runs(function () {
                function onMouseOn(element, annotation) {
                    expect(annotation).toBe(annotationId);
                    mouseon = true;
                }
                function onMouseOver(element, annotation) {
                    expect(annotation).toBe(annotationId);
                    mouseover = true;
                }
                viewer.on('g:mouseOnAnnotation', onMouseOn, context);
                viewer.on('g:mouseOverAnnotation', onMouseOver, context);
                interactor.simulateEvent('mousemove', {
                    map: viewer.viewer.gcsToDisplay({x: 1000, y: 1000})
                });
                interactor.simulateEvent('mousemove', {
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });
            });

            waitsFor(function () {
                return mouseon && mouseover;
            }, 'events to be fired');

            runs(function () {
                viewer.off(null, null, context);
            });
        });

        it('mouse out events', function () {
            var mouseout, mouseoff, context = {};
            runs(function () {
                function onMouseOut(element, annotation) {
                    expect(annotation).toBe(annotationId);
                    mouseout = true;
                }
                function onMouseOff(element, annotation) {
                    expect(annotation).toBe(annotationId);
                    mouseoff = true;
                }
                viewer.on('g:mouseOutAnnotation', onMouseOut, context);
                viewer.on('g:mouseOffAnnotation', onMouseOff, context);
                interactor.simulateEvent('mousemove', {
                    map: viewer.viewer.gcsToDisplay({x: 1000, y: 1000})
                });
            });

            waitsFor(function () {
                return mouseoff && mouseout;
            }, 'events to be fired');

            runs(function () {
                viewer.off(null, null, context);
            });
        });

        it('mouse click events', function () {
            var mouseclick, context = {};
            runs(function () {
                function onMouseClick(element, annotation) {
                    expect(annotation).toBe(annotationId);
                    mouseclick = true;
                }
                viewer.on('g:mouseClickAnnotation', onMouseClick, context);
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });
            });

            waitsFor(function () {
                return mouseclick;
            }, 'event to be fired');

            runs(function () {
                viewer.off(null, null, context);
            });
        });

        it('fires overlay event', function () {
            const eventType = window.geo.event.feature.mouseclick;
            const mockEvent = {
                event: eventType,
                data: {}
            };
            const mockOverlay = overlayAnnotation.elements().models[0] || {};
            const mockLayer = viewer.viewer.createLayer('osm');
            var mouseclick = false;
            runs(function () {
                function handleOverlayEvent() {
                    mouseclick = true;
                }

                viewer.on('g:mouseClickAnnotationOverlay', handleOverlayEvent);
                viewer._onMouseFeature(mockEvent, mockOverlay, mockLayer);
            });

            waitsFor(function () {
                return mouseclick;
            }, 'event to be fired');

            runs(function () {
                viewer.viewer.deleteLayer(mockLayer);
            });
        });

        it('mouse reset events', function () {
            var mousereset, context = {};
            runs(function () {
                function onMouseReset(annotation) {
                    expect(annotation.id).toBe(annotationId);
                    mousereset = true;
                }
                viewer.on('g:mouseResetAnnotation', onMouseReset, context);
                annotation.trigger('g:fetched');
            });

            waitsFor(function () {
                return mousereset;
            }, 'event to be fired');

            runs(function () {
                viewer.off(null, null, context);
                viewer.viewer.zoom(1);
            });
        });

        it('removeAnnotation', function () {
            viewer.removeAnnotation(annotation);
            viewer.removeAnnotation(overlayAnnotation);
            expect(viewer._annotations).toEqual({});
            sinon.assert.calledOnce(featureSpy);
        });

        it('drawAnnotation without fetching', function () {
            var model;
            runs(function () {
                model = new largeImageAnnotation.models.AnnotationModel({
                    _id: 'invalid',
                    annotation: {
                        name: 'no fetch',
                        elements: [{
                            type: 'rectangle',
                            center: [100, 100, 0],
                            rotation: 0,
                            width: 10,
                            height: 10
                        }]
                    }
                });
                sinon.spy(model, 'setView');
                viewer.drawAnnotation(model, {fetch: false});
                viewer.viewer.zoom(5);
            });

            girderTest.waitForLoad();
            runs(function () {
                sinon.assert.notCalled(model.setView);
                viewer.viewer.zoom(1);
            });
        });

        it('drawRegion', function () {
            var model = new Backbone.Model();
            runs(function () {
                var pt = viewer.viewer.gcsToDisplay({x: 100, y: 100});
                viewer.drawRegion(model);
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: pt
                });
            });
            runs(function () {
                var pt = viewer.viewer.gcsToDisplay({x: 115, y: 115});
                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: pt
                });
            });
            runs(function () {
                var pt = viewer.viewer.gcsToDisplay({x: 115, y: 115});
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: pt
                });
            });
            waitsFor(function () {
                return !!model.get('value');
            });

            runs(function () {
                expect(model.get('value')).toEqual([100, 100, 15, 15]);
            });
        });

        it('draw point', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('point').then(function (elements) {
                    expect(elements.length).toBe(1);
                    expect(elements[0].type).toBe('point');
                    closeTo(elements[0].center, [100, 200, 0]);
                    created = true;
                    return null;
                });
                var pt = viewer.viewer.gcsToDisplay({x: 100, y: 200});
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: pt
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: pt
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        it('draw polygon', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('polygon').then(function (elements) {
                    expect(elements.length).toBe(1);
                    expect(elements[0].type).toBe('polyline');
                    expect(elements[0].closed).toBe(true);
                    expect(elements[0].points.length).toBe(3);
                    // these could be in any order, so sort them
                    var points = elements[0].points.sort(function (a, b) {
                        if (a[0] !== b[0]) {
                            return a[0] < b[0] ? -1 : 1;
                        }
                        return a[1] < b[1] ? -1 : 1;
                    });
                    closeTo(points[0], [100, 200, 0]);
                    closeTo(points[1], [200, 200, 0]);
                    closeTo(points[2], [200, 300, 0]);
                    created = true;
                    return null;
                });

                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });

                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        it('draw rectangle', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('rectangle').then(function (elements) {
                    expect(elements.length).toBe(1);
                    closeTo(elements[0].center, [150, 300, 0]);
                    expect(elements[0].width).toBe(100);
                    expect(elements[0].height).toBe(200);
                    created = true;
                    return null;
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        it('draw ellipse', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('ellipse').then(function (elements) {
                    expect(elements.length).toBe(1);
                    closeTo(elements[0].center, [150, 300, 0]);
                    expect(elements[0].width).toBe(100);
                    expect(elements[0].height).toBe(200);
                    created = true;
                    return null;
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 400})
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        it('draw circle', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('circle').then(function (elements) {
                    expect(elements.length).toBe(1);
                    closeTo(elements[0].center, [200, 200, 0]);
                    expect(elements[0].radius).toBe(100);
                    created = true;
                    return null;
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 100})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 500})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 500})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 500})
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        it('draw line', function () {
            var created;

            runs(function () {
                viewer.startDrawMode('line').then(function (elements) {
                    expect(elements.length).toBe(1);
                    expect(elements[0].type).toBe('polyline');
                    expect(elements[0].closed).toBe(false);
                    expect(elements[0].points.length).toBe(3);
                    closeTo(elements[0].points[0], [100, 200, 0]);
                    closeTo(elements[0].points[1], [200, 200, 0]);
                    closeTo(elements[0].points[2], [200, 300, 0]);
                    created = true;
                    return null;
                });

                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 100, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 200})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });

                interactor.simulateEvent('mousemove', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });

                interactor.simulateEvent('mousedown', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
                interactor.simulateEvent('mouseup', {
                    button: 'left',
                    map: viewer.viewer.gcsToDisplay({x: 200, y: 300})
                });
            });

            waitsFor(function () {
                return created;
            });
        });

        describe('global annotation opacity', function () {
            var opacity, opacityFunction;
            beforeEach(function () {
                opacity = null;
                opacityFunction = viewer.featureLayer.opacity;
                viewer.featureLayer.opacity = function (_opacity) {
                    opacity = _opacity;
                };
            });
            afterEach(function () {
                viewer.featureLayer.opacity = opacityFunction;
            });
            it('set global annotation opacity', function () {
                viewer.setGlobalAnnotationOpacity(0.5);
                expect(opacity).toBe(0.5);
            });
        });

        describe('global annotation fill opacity', function () {
            var annotation1;
            var element1 = '111111111111111111111111';

            it('generate test annotations', function () {
                girder.rest.restRequest({
                    url: 'annotation?itemId=' + itemId,
                    contentType: 'application/json',
                    processData: false,
                    type: 'POST',
                    data: JSON.stringify({
                        name: 'annotation1',
                        elements: [{
                            id: element1,
                            type: 'rectangle',
                            center: [200, 200, 0],
                            width: 400,
                            height: 400,
                            rotation: 0,
                            fillColor: '#000'
                        }]
                    })
                }).done(function (resp) {
                    annotation1 = new largeImageAnnotation.models.AnnotationModel({
                        _id: resp._id
                    });
                });
                waitsFor(function () {
                    return annotation1;
                }, 'annotations to be created');
                runs(function () {
                    viewer.drawAnnotation(annotation1);
                });
                girderTest.waitForLoad();
            });
            it('set global fill annotation opacity', function () {
                var polygonFeature = viewer.viewer.layers()[1].features()[2];
                expect(polygonFeature.style.get('fillOpacity')(null, 0, null, 0)).toBe(1);
                viewer.setGlobalAnnotationFillOpacity(0.5);
                expect(polygonFeature.style.get('fillOpacity')(null, 0, null, 0)).toBe(0.5);
                viewer.setGlobalAnnotationFillOpacity(1);
                expect(polygonFeature.style.get('fillOpacity')(null, 0, null, 0)).toBe(1);
            });
        });

        describe('highlight and hide annotations', function () {
            var annotation1, annotation2;
            var element11 = '111111111111111111111111';
            var element12 = '222222222222222222222222';
            var element21 = '333333333333333333333333';
            var element22 = '444444444444444444444444';

            it('generate test annotations', function () {
                girder.rest.restRequest({
                    url: 'annotation?itemId=' + itemId,
                    contentType: 'application/json',
                    processData: false,
                    type: 'POST',
                    data: JSON.stringify({
                        name: 'annotation1',
                        elements: [{
                            id: element11,
                            type: 'rectangle',
                            center: [200, 200, 0],
                            width: 400,
                            height: 400,
                            rotation: 0,
                            fillColor: 'rgba(0, 0, 0, 0.5)'
                        }, {
                            id: element12,
                            type: 'rectangle',
                            center: [300, 300, 0],
                            width: 100,
                            height: 100,
                            rotation: 0,
                            fillColor: 'rgba(0, 0, 0, 0.5)'
                        }]
                    })
                }).done(function (resp) {
                    annotation1 = new largeImageAnnotation.models.AnnotationModel({
                        _id: resp._id
                    });
                });
                girder.rest.restRequest({
                    url: 'annotation?itemId=' + itemId,
                    contentType: 'application/json',
                    processData: false,
                    type: 'POST',
                    data: JSON.stringify({
                        name: 'annotation2',
                        elements: [{
                            id: element21,
                            type: 'rectangle',
                            center: [200, 200, 0],
                            width: 400,
                            height: 400,
                            rotation: 0,
                            fillColor: 'rgba(0, 0, 0, 0.5)'
                        }, {
                            id: element22,
                            type: 'point',
                            center: [300, 300, 0],
                            fillColor: 'rgba(0, 0, 0, 0.5)'
                        }]
                    })
                }).done(function (resp) {
                    annotation2 = new largeImageAnnotation.models.AnnotationModel({
                        _id: resp._id
                    });
                });

                waitsFor(function () {
                    return annotation1 && annotation2;
                }, 'annotations to be created');
                runs(function () {
                    viewer.drawAnnotation(annotation1);
                    viewer.drawAnnotation(annotation2);
                });

                girderTest.waitForLoad();
            });

            function checkFeatureOpacity(annotationId, fillOpacity, strokeOpacity, filter) {
                filter = filter || _.constant(true);
                _.each(viewer._annotations[annotationId].features, function (feature, findex) {
                    var fillOpacityFunction = feature.style.get('fillOpacity');
                    var strokeOpacityFunction = feature.style.get('strokeOpacity');
                    var allData = feature.data();
                    _.each(_.filter(allData, filter), function (data, index) {
                        expect(fillOpacityFunction(allData, findex, data, index)).toBe(fillOpacity);
                        expect(strokeOpacityFunction(allData, findex, data, index)).toBe(strokeOpacity);
                    });
                });
            }

            it('highlight a full annotation', function () {
                viewer.highlightAnnotation(annotation1.id);

                checkFeatureOpacity(annotation1.id, 0.5, 1);
                checkFeatureOpacity(annotation2.id, 0.5 * 0.25, 0.25);
            });

            it('highlight a single element', function () {
                viewer.highlightAnnotation(annotation2.id, element21);

                checkFeatureOpacity(annotation1.id, 0.5 * 0.25, 0.25);
                checkFeatureOpacity(annotation2.id, 0.5 * 0.25, 0.25, function (data) {
                    return data.id !== element21;
                });
                checkFeatureOpacity(annotation2.id, 0.5, 1, function (data) {
                    return data.id === element21;
                });
            });

            it('reset opacities', function () {
                viewer.highlightAnnotation();

                checkFeatureOpacity(annotation1.id, 0.5, 1);
                checkFeatureOpacity(annotation2.id, 0.5, 1);
            });

            it('hide an element', function () {
                viewer.hideAnnotation(annotation2.id, element21);

                checkFeatureOpacity(annotation1.id, 0.5, 1);
                checkFeatureOpacity(annotation2.id, 0.5, 1, function (data) {
                    return data.id !== element21;
                });
                checkFeatureOpacity(annotation2.id, 0, 0, function (data) {
                    return data.id === element21;
                });
            });

            it('reset opacities', function () {
                viewer.hideAnnotation();

                checkFeatureOpacity(annotation1.id, 0.5, 1);
                checkFeatureOpacity(annotation2.id, 0.5, 1);
            });
        });
        describe('large annotations', function () {
            var annotations = [], count = 0;
            it('generate several sizes of annotations', function () {
                [0, 1, 2].forEach(function (i) {
                    var elements = new Array(Math.pow(10, i + 1)).fill(0).map(function (_elem, idx) {
                        return {
                            type: 'rectangle',
                            center: [0.2 + (idx % 100) * 0.1, 0.2 + (Math.floor(idx / 100)) * 0.1, 0],
                            width: 0.12 + (idx % 40) * 0.01,
                            height: 0.12 + (idx % 51) * 0.01,
                            rotation: 0,
                            fillColor: 'rgba(0, 0, 0, 0.5)'
                        };
                    });
                    girder.rest.restRequest({
                        url: 'annotation?itemId=' + itemId,
                        contentType: 'application/json',
                        processData: false,
                        type: 'POST',
                        data: JSON.stringify({
                            name: 'annotation' + i,
                            elements: elements
                        })
                    }).done(function (resp) {
                        annotations[i] = new largeImageAnnotation.models.AnnotationModel({
                            _id: resp._id,
                            maxDetails: 50,
                            minElements: 1,
                            maxCentroids: 500
                        });
                        count += 1;
                    });
                });
                waitsFor(function () {
                    return count === 3;
                }, 'annotations to be created');
                runs(function () {
                    annotations.forEach(function (annot) {
                        return viewer.drawAnnotation(annot);
                    });
                });
                girderTest.waitForLoad();
            });
            it('check that annotations are using centroids when appropriate', function () {
                runs(function () {
                    expect(annotations[0]._centroids).not.toBeDefined();
                    expect(annotations[1]._centroids).toBeDefined();
                    expect(annotations[1]._centroids.partial).not.toBeDefined();
                    expect(annotations[2]._centroids).toBeDefined();
                    expect(annotations[2]._centroids.partial).toBeDefined();
                    viewer.viewer.zoom(viewer.viewer.zoom() + 1);
                    expect(annotations[1]._lastZoom).toBeDefined();
                });
            });
        });
        it('destroy the viewer', function () {
            viewer.destroy();
            expect($('.geojs-layer').length).toBe(0);
        });

        it('scale', function () {
            viewer = new GeojsViewer({
                el: $el,
                itemId: itemId,
                parentView: null,
                scale: {position: {bottom: 20, right: 10}, scale: 0.0005}
            });
            viewer.once('g:beforeFirstRender', function () {
                try {
                    window.geo.util.mockWebglRenderer();
                } catch (err) {
                    // if this is already mocked, do nothing.
                }
            });
            waitsFor(function () {
                return $('.geojs-layer.active').length >= 1 && viewer.scaleWidget;
            }, 'viewer and scale to load');
            runs(function () {
                expect(viewer.scaleWidget instanceof window.geo.gui.scaleWidget).toBe(true);
                viewer.destroy();
            });
        });
    });
});
