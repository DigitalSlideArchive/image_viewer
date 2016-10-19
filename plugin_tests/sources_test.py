#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#############################################################################

import numpy
import os
import PIL.Image
import six

from girder import config
from tests import base

from . import common


# boiler plate to start and stop the server

os.environ['GIRDER_PORT'] = os.environ.get('GIRDER_TEST_PORT', '20200')
config.loadConfig()  # Must reload config to pickup correct port


def setUpModule():
    base.enabledPlugins.append('large_image')
    base.startServer(False)


def tearDownModule():
    base.stopServer()


class LargeImageSourcesTest(common.LargeImageCommonTest):
    def testMagnification(self):
        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_jp2k_33003_TCGA-CV-7242-'
            '11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)
        mag = source.getNativeMagnification()
        self.assertEqual(mag['magnification'], 40.0)
        self.assertEqual(mag['mm_x'], 0.000252)
        self.assertEqual(mag['mm_y'], 0.000252)
        mag = source.getMagnificationForLevel()
        self.assertEqual(mag['magnification'], 40.0)
        self.assertEqual(mag['mm_x'], 0.000252)
        self.assertEqual(mag['mm_y'], 0.000252)
        self.assertEqual(mag['level'], 7)
        mag = source.getMagnificationForLevel(0)
        self.assertEqual(mag['magnification'], 0.3125)
        self.assertEqual(mag['mm_x'], 0.032256)
        self.assertEqual(mag['mm_y'], 0.032256)
        self.assertEqual(mag['level'], 0)
        self.assertEqual(source.getLevelForMagnification(), 7)
        self.assertEqual(source.getLevelForMagnification(exact=True), 7)
        self.assertEqual(source.getLevelForMagnification(40), 7)
        self.assertEqual(source.getLevelForMagnification(20), 6)
        self.assertEqual(source.getLevelForMagnification(0.3125), 0)
        self.assertEqual(source.getLevelForMagnification(15), 6)
        self.assertEqual(source.getLevelForMagnification(25), 6)
        self.assertEqual(source.getLevelForMagnification(
            15, rounding='ceil'), 6)
        self.assertEqual(source.getLevelForMagnification(
            25, rounding='ceil'), 7)
        self.assertEqual(source.getLevelForMagnification(
            15, rounding=False), 5.585)
        self.assertEqual(source.getLevelForMagnification(
            25, rounding=False), 6.3219)
        self.assertEqual(source.getLevelForMagnification(
            45, rounding=False), 7)
        self.assertEqual(source.getLevelForMagnification(
            15, rounding=None), 5.585)
        self.assertEqual(source.getLevelForMagnification(
            25, rounding=None), 6.3219)
        self.assertEqual(source.getLevelForMagnification(
            45, rounding=None), 7.1699)
        self.assertEqual(source.getLevelForMagnification(mm_x=0.0005), 6)
        self.assertEqual(source.getLevelForMagnification(
            mm_x=0.0005, mm_y=0.002), 5)
        self.assertEqual(source.getLevelForMagnification(
            mm_x=0.0005, exact=True), None)
        self.assertEqual(source.getLevelForMagnification(
            mm_x=0.000504, exact=True), 6)
        self.assertEqual(source.getLevelForMagnification(80), 7)
        self.assertEqual(source.getLevelForMagnification(80, exact=True), None)
        self.assertEqual(source.getLevelForMagnification(0.1), 0)

    def testTileIterator(self):
        from girder.plugins.large_image import tilesource

        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_jp2k_33003_TCGA-CV-7242-'
            '11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)
        tileCount = 0
        visited = {}
        for tile in source.tileIterator(scale={'magnification': 5}):
            visited.setdefault(tile['level_x'], {})[tile['level_y']] = True
            tileCount += 1
            self.assertEqual(tile['tile'].size, (tile['width'], tile['height']))
            self.assertEqual(tile['width'], 256 if tile['level_x'] < 11 else 61)
            self.assertEqual(tile['height'], 256 if tile['level_y'] < 11 else 79)
        self.assertEqual(tileCount, 144)
        self.assertEqual(len(visited), 12)
        self.assertEqual(len(visited[0]), 12)
        # Check with a non-native magnfication with exact=True
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 4, 'exact': True}):
            tileCount += 1
        self.assertEqual(tileCount, 0)
        # Check with a non-native (but factor of 2) magnfication with exact=True
        for tile in source.tileIterator(
                scale={'magnification': 2.5, 'exact': True}):
            tileCount += 1
        self.assertEqual(tileCount, 0)
        # Check with a native magnfication with exact=True
        for tile in source.tileIterator(
                scale={'magnification': 5, 'exact': True}):
            tileCount += 1
        self.assertEqual(tileCount, 144)
        # Check with a non-native magnfication without resampling
        tileCount = 0
        for tile in source.tileIterator(scale={'magnification': 2}):
            tileCount += 1
            self.assertEqual(tile['tile'].size, (tile['width'], tile['height']))
            self.assertEqual(tile['width'], 256 if tile['level_x'] < 11 else 61)
            self.assertEqual(tile['height'], 256 if tile['level_y'] < 11 else 79)
        self.assertEqual(tileCount, 144)
        # Check with a non-native magnfication with resampling
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 2}, resample=True):
            tileCount += 1
            self.assertEqual(tile['tile'].size, (tile['width'], tile['height']))
            self.assertEqual(tile['width'], 102 if tile['level_x'] < 11 else 24)
            self.assertEqual(tile['height'], 102 if tile['level_y'] < 11 else 31)
        self.assertEqual(tileCount, 144)

        # Ask for numpy array as results
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 5},
                format=tilesource.TILE_FORMAT_NUMPY):
            tileCount += 1
            self.assertTrue(isinstance(tile['tile'], numpy.ndarray))
            self.assertEqual(tile['tile'].shape, (
                256 if tile['level_y'] < 11 else 79,
                256 if tile['level_x'] < 11 else 61,
                4))
            self.assertEqual(tile['tile'].dtype, numpy.dtype('uint8'))
        self.assertEqual(tileCount, 144)
        # Ask for either PIL or IMAGE data, we should get PIL data
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 5},
                format=(tilesource.TILE_FORMAT_PIL,
                        tilesource.TILE_FORMAT_IMAGE),
                encoding='JPEG'):
            tileCount += 1
            self.assertTrue(isinstance(tile['tile'], PIL.Image.Image))
        self.assertEqual(tileCount, 144)
        # Ask for PNGs
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 5},
                format=tilesource.TILE_FORMAT_IMAGE,
                encoding='PNG'):
            tileCount += 1
            self.assertFalse(isinstance(tile['tile'], PIL.Image.Image))
            self.assertEqual(tile['tile'][:len(common.PNGHeader)],
                             common.PNGHeader)
        self.assertEqual(tileCount, 144)

        # Use a ptif to test getting tiles as images
        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_image.ptif'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)
        # Ask for either PIL or IMAGE data, we should get image data
        tileCount = 0
        jpegTileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 2.5},
                format=(tilesource.TILE_FORMAT_PIL,
                        tilesource.TILE_FORMAT_IMAGE),
                encoding='JPEG'):
            tileCount += 1
            if not isinstance(tile['tile'], PIL.Image.Image):
                self.assertEqual(tile['tile'][:len(common.JPEGHeader)],
                                 common.JPEGHeader)
                jpegTileCount += 1
        self.assertEqual(tileCount, 45)
        self.assertGreater(jpegTileCount, 0)
        # Ask for PNGs
        tileCount = 0
        for tile in source.tileIterator(
                scale={'magnification': 2.5},
                format=tilesource.TILE_FORMAT_IMAGE,
                encoding='PNG'):
            tileCount += 1
            self.assertEqual(tile['tile'][:len(common.PNGHeader)],
                             common.PNGHeader)
        self.assertEqual(tileCount, 45)

        # Test getting a single tile
        sourceRegion = {
            'width': 0.7, 'height': 0.6,
            'left': 0.15, 'top': 0.2,
            'units': 'fraction'}
        tileCount = 0
        for tile in source.tileIterator(
                region=sourceRegion,
                scale={'magnification': 5},
                tile_position=25):
            tileCount += 1
            self.assertEqual(tile['tile_position']['position'], 25)
            self.assertEqual(tile['tile_position']['level_x'], 8)
            self.assertEqual(tile['tile_position']['level_y'], 2)
            self.assertEqual(tile['tile_position']['region_x'], 4)
            self.assertEqual(tile['tile_position']['region_y'], 1)
            self.assertEqual(tile['iterator_range']['level_x_min'], 4)
            self.assertEqual(tile['iterator_range']['level_y_min'], 1)
            self.assertEqual(tile['iterator_range']['level_x_max'], 25)
            self.assertEqual(tile['iterator_range']['level_y_max'], 5)
            self.assertEqual(tile['iterator_range']['region_x_max'], 21)
            self.assertEqual(tile['iterator_range']['region_y_max'], 4)
            self.assertEqual(tile['iterator_range']['position'], 84)
        self.assertEqual(tileCount, 1)
        tiles = list(source.tileIterator(
            region=sourceRegion, scale={'magnification': 5},
            tile_position={'position': 25}))
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]['tile_position']['position'], 25)
        tiles = list(source.tileIterator(
            region=sourceRegion, scale={'magnification': 5},
            tile_position={'level_x': 8, 'level_y': 2}))
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]['tile_position']['position'], 25)
        tiles = list(source.tileIterator(
            region=sourceRegion, scale={'magnification': 5},
            tile_position={'region_x': 4, 'region_y': 1}))
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]['tile_position']['position'], 25)
        tiles = list(source.tileIterator(
            region=sourceRegion, scale={'magnification': 5},
            tile_position={'position': 90}))
        self.assertEqual(len(tiles), 0)

    def testGetRegion(self):
        from girder.plugins.large_image import tilesource

        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_jp2k_33003_TCGA-CV-7242-'
            '11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)

        # By default, getRegion gets an image
        image, mimeType = source.getRegion(scale={'magnification': 2.5})
        self.assertEqual(mimeType, 'image/jpeg')
        self.assertEqual(image[:len(common.JPEGHeader)], common.JPEGHeader)

        # Adding a tile position request should be ignored
        image2, imageFormat = source.getRegion(scale={'magnification': 2.5},
                                               tile_position=1)
        self.assertEqual(image, image2)

        # We should be able to get a NUMPY array instead
        image, imageFormat = source.getRegion(
            scale={'magnification': 2.5},
            format=tilesource.TILE_FORMAT_NUMPY)
        self.assertEqual(imageFormat, tilesource.TILE_FORMAT_NUMPY)
        self.assertTrue(isinstance(image, numpy.ndarray))
        self.assertEqual(image.shape, (1447, 1438, 4))

        # We should be able to get a PIL image
        image, imageFormat = source.getRegion(
            scale={'magnification': 2.5},
            format=(tilesource.TILE_FORMAT_PIL, tilesource.TILE_FORMAT_NUMPY))
        self.assertEqual(imageFormat, tilesource.TILE_FORMAT_PIL)
        self.assertEqual(image.width, 1438)
        self.assertEqual(image.height, 1447)

    def testConvertRegionScale(self):
        from girder.plugins.large_image import tilesource

        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_jp2k_33003_TCGA-CV-7242-'
            '11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)

        # If we aren't using pixels as our units and don't specify a target
        # unit, this should do nothing.  This source image is 23021 x 23162
        sourceRegion = {'width': 0.8, 'height': 0.7, 'units': 'fraction'}
        targetRegion = source.convertRegionScale(sourceRegion)
        self.assertEqual(sourceRegion, targetRegion)

        # Units must be valid
        with six.assertRaisesRegex(self, ValueError, 'Invalid units'):
            source.convertRegionScale({'units': 'unknown'})
        with six.assertRaisesRegex(self, ValueError, 'Invalid units'):
            source.convertRegionScale(sourceRegion, targetUnits='unknown')

        # We can convert to pixels
        targetRegion = source.convertRegionScale(
            sourceRegion, targetScale={'magnification': 2.5},
            targetUnits='pixels')
        self.assertEqual(int(targetRegion['width']), 1151)
        self.assertEqual(int(targetRegion['height']), 1013)
        self.assertEqual(targetRegion['units'], 'mag_pixels')

        # Now use that to convert to a different magnification
        sourceRegion = targetRegion
        sourceScale = {'magnification': 2.5}

        # Test other conversions
        targetScale = {'magnification': 1.25}
        targetRegion = source.convertRegionScale(
            sourceRegion, sourceScale, targetScale)
        self.assertEqual(int(targetRegion['width']), 18417)
        self.assertEqual(int(targetRegion['height']), 16213)
        self.assertEqual(targetRegion['units'], 'base_pixels')

        targetRegion = source.convertRegionScale(
            sourceRegion, sourceScale, targetScale, targetUnits='fraction')
        self.assertAlmostEqual(targetRegion['width'], 0.8, places=4)
        self.assertAlmostEqual(targetRegion['height'], 0.7, places=4)
        self.assertEqual(targetRegion['units'], 'fraction')

        targetRegion = source.convertRegionScale(
            sourceRegion, sourceScale, targetScale, targetUnits='mm')
        self.assertAlmostEqual(targetRegion['width'], 4.6411, places=3)
        self.assertAlmostEqual(targetRegion['height'], 4.0857, places=3)
        self.assertEqual(targetRegion['units'], 'mm')
        with six.assertRaisesRegex(self, ValueError, 'No mm_x'):
            source.convertRegionScale(
                sourceRegion, sourceScale, None, targetUnits='mm')

        targetRegion = source.convertRegionScale(
            sourceRegion, sourceScale, targetScale, targetUnits='pixels')
        self.assertEqual(int(targetRegion['width']), 575)
        self.assertEqual(int(targetRegion['height']), 506)
        self.assertEqual(targetRegion['units'], 'mag_pixels')
        with six.assertRaisesRegex(self, ValueError, 'No magnification'):
            source.convertRegionScale(
                sourceRegion, sourceScale, None, targetUnits='pixels')

        # test getRegionAtAnotherScale
        image, imageFormat = source.getRegionAtAnotherScale(
            sourceRegion, sourceScale, targetScale,
            format=tilesource.TILE_FORMAT_NUMPY)
        self.assertEqual(imageFormat, tilesource.TILE_FORMAT_NUMPY)
        self.assertTrue(isinstance(image, numpy.ndarray))
        self.assertEqual(image.shape, (506, 575, 4))
        with six.assertRaisesRegex(self, TypeError, 'unexpected keyword'):
            source.getRegionAtAnotherScale(
                sourceRegion, sourceScale, region=sourceRegion,
                format=tilesource.TILE_FORMAT_NUMPY)

        # test tileIteratorAtAnotherScale
        tileCount = 0
        for tile in source.tileIteratorAtAnotherScale(
                sourceRegion, sourceScale, targetScale,
                format=tilesource.TILE_FORMAT_NUMPY):
            tileCount += 1
        self.assertEqual(tileCount, 72)
        with six.assertRaisesRegex(self, TypeError, 'unexpected keyword'):
            for tile in source.tileIteratorAtAnotherScale(
                    sourceRegion, sourceScale, region=sourceRegion,
                    format=tilesource.TILE_FORMAT_NUMPY):
                tileCount += 1

    def testGetSingleTile(self):
        file = self._uploadFile(os.path.join(
            os.environ['LARGE_IMAGE_DATA'], 'sample_image.ptif'))
        itemId = str(file['itemId'])
        item = self.model('item').load(itemId, user=self.admin)
        source = self.model('image_item', 'large_image').tileSource(item)

        sourceRegion = {
            'width': 0.7, 'height': 0.6,
            'left': 0.15, 'top': 0.2,
            'units': 'fraction'}
        sourceScale = {'magnification': 5}
        targetScale = {'magnification': 2.5}
        tile = source.getSingleTile(
            region=sourceRegion, scale=sourceScale, tile_position=25)
        self.assertEqual(tile['tile_position']['position'], 25)
        self.assertEqual(tile['tile_position']['level_x'], 8)
        self.assertEqual(tile['tile_position']['level_y'], 2)
        self.assertEqual(tile['tile_position']['region_x'], 4)
        self.assertEqual(tile['tile_position']['region_y'], 1)
        self.assertEqual(tile['iterator_range']['level_x_min'], 4)
        self.assertEqual(tile['iterator_range']['level_y_min'], 1)
        self.assertEqual(tile['iterator_range']['level_x_max'], 25)
        self.assertEqual(tile['iterator_range']['level_y_max'], 5)
        self.assertEqual(tile['iterator_range']['region_x_max'], 21)
        self.assertEqual(tile['iterator_range']['region_y_max'], 4)
        self.assertEqual(tile['iterator_range']['position'], 84)

        tile = source.getSingleTileAtAnotherScale(
            sourceRegion, sourceScale, targetScale, tile_position=25)
        self.assertEqual(tile['tile_position']['position'], 25)
        self.assertEqual(tile['tile_position']['level_x'], 5)
        self.assertEqual(tile['tile_position']['level_y'], 2)
        self.assertEqual(tile['tile_position']['region_x'], 3)
        self.assertEqual(tile['tile_position']['region_y'], 2)
        self.assertEqual(tile['iterator_range']['level_x_min'], 2)
        self.assertEqual(tile['iterator_range']['level_y_min'], 0)
        self.assertEqual(tile['iterator_range']['level_x_max'], 13)
        self.assertEqual(tile['iterator_range']['level_y_max'], 3)
        self.assertEqual(tile['iterator_range']['region_x_max'], 11)
        self.assertEqual(tile['iterator_range']['region_y_max'], 3)
        self.assertEqual(tile['iterator_range']['position'], 33)
