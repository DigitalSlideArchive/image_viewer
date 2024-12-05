# Change Log

## 1.30.3

### Improvements

- Format dates in item lists ([#1707](../../pull/1707))
- Guard dtype types ([#1711](../../pull/1711), [#1714](../../pull/1714), [#1716](../../pull/1716))
- Better handle IndicaLabs tiff files ([#1717](../../pull/1717))
- Better detect files with geotransform data that aren't geospatial ([#1718](../../pull/1718))
- Better scale float-valued tiles ([#1725](../../pull/1725))

### Changes

- Openslide now requires the binary wheel on appropriate platforms ([#1709](../../pull/1709), [#1710](../../pull/1710))

### Bug Fixes

- Fix an issue searching for annotation metadata on items that a user doesn't have permissions to view ([#1723](../../pull/1723))
- Fix a typo in a column header ([#1727](../../pull/1727))

## 1.30.2

### Features

- Support setting axis actual values in the zarr sink.  Display these in the frame selector ([#1625](../../pull/1625))

### Improvements

- Speed up recursive item lists ([#1694](../../pull/1694))
- Better handle images with signed pixel data ([#1695](../../pull/1695))
- Reduce loading geojs when switching views in Girder ([#1699](../../pull/1699))

### Bug Fixes

- Don't compute channel window in zarr sinks ([#1705](../../pull/1705))

## 1.30.1

### Improvements

- Support generalized application buttons ([#1692](../../pull/1692))

### Bug Fixes

- Don't use a default for yaml config files except .large_image_config.yaml ([#1685](../../pull/1685))
- Some checks for repeated values in the item lists were wrong ([#1686](../../pull/1686))
- Better support creating zarr sinks from multiple processes ([#1687](../../pull/1687))

## 1.30.0

### Features

- Add support for Python 3.13 ([#1675](../../pull/1675))

### Improvements

- Better handle images without enough tile layers ([#1648](../../pull/1648))
- Add users option to config files; have a default config file ([#1649](../../pull/1649))
- Remove no longer used code; adjust item list slightly ([#1651](../../pull/1651), [#1668](../../pull/1668))
- Reduce updates when showing item lists; add a waiting spinner ([#1653](../../pull/1653))
- Update item lists check for large images when toggling recurse ([#1654](../../pull/1654))
- Support named item lists ([#1665](../../pull/1665))
- Add options to group within item lists ([#1666](../../pull/1666))
- Make the filter field in item lists wider ([#1669](../../pull/1669), [#1671](../../pull/1671))
- Add a navigate option to item lists ([#1659](../../pull/1659))

### Changes

- Handle a rasterio deprecation ([#1655](../../pull/1655))
- Handle a variation in a bioformats exception ([#1656](../../pull/1656))
- Increase logging slow histograms ([#1658](../../pull/1658))
- Use paginated item lists ([#1664](../../pull/1664))
- When in-line editing yaml and other files, the tab key now uses spaces ([#1667](../../pull/1667))
- Changed the parsing of the open parameter in the algorithm progression example ([#1677](../../pull/1677))

### Bug Fixes

- Fix styling images with empty tile layers ([#1650](../../pull/1650))
- Add a guard around sorting item lists ([#1663](../../pull/1663))
- Fix some issues with possible numpy 2.x overflows ([#1672](../../pull/1672))

## 1.29.11

### Changes

- Update zarr dependencies ([#1646](../../pull/1646))

### Bug Fixes

- Fixed an issue correlating bounding boxes across multiple annotations ([#1647](../../pull/1647))

## 1.29.10

### Improvements

- Only list computable plot columns if there are other numeric columns ([#1634](../../pull/1634))
- Allow canceling plottable data requests ([#1645](../../pull/1645))
- List official yaml mime type for the multi source ([#1636](../../pull/1636))
- Speed up correlating data files with annotations ([#1642](../../pull/1642))
- Support dict with MultiFileTileSource ([#1641](../../pull/1641))
- The PIL source reads more multi-frame images ([#1643](../../pull/1643))

### Changes

- Add an extension and mimetype to the listed openjpeg handlers ([#1644](../../pull/1644))

### Bug Fixes

- Fix an issue when asking not to resample a GDAL tile iterator ([#1640](../../pull/1640))

## 1.29.9

### Bug Fixes

- Fix scaling small images in the multi source ([#1633](../../pull/1633))

## 1.29.8

### Improvements

- Add the option to compute additional columns for plottable data ([#1626](../../pull/1626))

### Bug Fixes

- Fix scaling small images in the multi source with bicubic smoothing ([#1627](../../pull/1627))
- Fix correlating annotation bounding boxes on adjacent items for plottable data ([#1628](../../pull/1628), ([#1632](../../pull/1632))

## 1.29.7

### Improvements

- Speed up getting plottable data from adjacent items; plot more data ([#1613](../../pull/1613), [#1614](../../pull/1614))
- Better handle mixed dtype sources in the multi source ([#1616](../../pull/1616))
- Add a utility function to minimize caching ([#1617](../../pull/1617))
- Allow passing through converter options when writing a zarr sink to a non-zarr format ([#1618](../../pull/1618))
- Do less calculations when applying affine transforms in the multi-source ([#1619](../../pull/1619))
- Improve logging in the image converter ([#1621](../../pull/1621))

### Bug Fixes

- Harden converting sources that report varied tile bands ([#1615](../../pull/1615))
- Harden many of the sources from reading bad files ([#1623](../../pull/1623))
- Some projected bounds in the rasterio source could be off ([#1624](../../pull/1624))

## 1.29.6

### Bug Fixes

- Use math.prod in preference to np.prod ([#1606](../../pull/1606))

## 1.29.5

### Improvements

- Make the plottable data class threadsafe ([#1588](../../pull/1588))
- Speed up getting plottable data from items ([#1589](../../pull/1589))
- Add an index to speed up getting plottable data from annotation elements ([#1590](../../pull/1590))
- Speed up checks for old annotations ([#1591](../../pull/1591))
- Improve plottable data endpoint to better fetch folder data ([#1594](../../pull/1594))
- Show a frame slider when appropriate in jupyter widgets ([#1595](../../pull/1595))
- Improve options for creating or check large images for each item in a folder ([#1586](../../pull/1586))
- Add a lock to avoid mongo excessively computing random numbers ([#1601](../../pull/1601))
- Better merge source channel names in multi source ([#1605](../../pull/1605))

### Bug Fixes

- Don't redirect tile frame images via 303; they aren't rendered correctly ([#1596](../../pull/1596))

## 1.29.4

### Improvements

- Improve plottable data endpoint to better fetch varied data.  Refactors some columns names ([#1587](../../pull/1587))

## 1.29.3

### Improvements

- Improve plottable data endpoint to better fetch adjacent items and annotations ([#1573](../../pull/1573), [#1574](../../pull/1574), [#1575](../../pull/1575), [#1580](../../pull/1580), [#1583](../../pull/1583))
- Support Girder flat-mount paths ([#1576](../../pull/1576))
- Lazily import some modules to speed up large_image import speed ([#1577](../../pull/1577))
- Create or check large images for each item in a folder ([#1572](../../pull/1572))
- Support multiprocessing and pickling with a zarr sink ([#1551](../../pull/1551))
- Allow checking for geospatial sources to use a specific source list ([#1582](../../pull/1582))
- Read scales from some OME tiff files parsed with the tifffile source ([#1584](../../pull/1584))

### Changes
- Remove old code that handled old pyproj packages ([#1581](../../pull/1581))

### Bug Fixes
- Harden marking S3 uploads as large images ([#1579](../../pull/1579))

## 1.29.2

### Improvements
- Show a loading spinner on the image display in geojs in girder ([#1559](../../pull/1559))
- Better handle images that are composed of a folder and an item ([#1561](../../pull/1561))
- Allow specifying which sources are checked with canReadList ([#1562](../../pull/1562))
- Added endpoints to get plottable data related to annotations ([#1524](../../pull/1524))

### Bug Fixes
- Fix a compositing error in transformed multi source images ([#1560](../../pull/1560))
- Prevent using vips input in image conversion if vips parses the image as a different size than large_image ([#1569](../../pull/1569))

## 1.29.1

### Improvements
- Improved zarr sink metadata handling ([#1508](../../pull/1508))
- Speed up decoding jp2k tiff with an optional library ([#1555](../../pull/1555))

### Changes
- Work with newer python-mapnik ([#1550](../../pull/1550))
- Use the new official yaml mime-type of application/yaml ([#1558](../../pull/1558))

### Bug Fixes
- Fix an issue emitting rectangles in geojson ([#1552](../../pull/1552))
- Fix an issue writing zarr channel metadata ([#1557](../../pull/1557))

## 1.29.0

### Features
- Add redis as cache backend option ([#1469](../../pull/1469))

### Improvements
- Better detect available memory in containers ([#1532](../../pull/1532))
- Reject the promise from a canceled annotation ([#1535](../../pull/1535))
- Disallow certain names from being read by any but specific sources ([#1537](../../pull/1537))
- Add the ability to specify the dtype of a multi-source file ([#1542](../../pull/1542))
- Handle bounds on openslide sources to handle sparse sources ([#1543](../../pull/1543))

### Changes
- Log more when saving annotations ([#1525](../../pull/1525))
- Thumbnail generation jobs are less blocking ([#1528](../../pull/1528), [#1530](../../pull/1530))

### Bug Fixes
- Annotations are sometimes paged when they shouldn't be ([#1529](../../pull/1529))

## 1.28.2

### Improvements
- Improve uint16 image scaling ([#1511](../../pull/1511))
- Read some untiled tiffs using the tiff source ([#1512](../../pull/1512))
- Speed up multi source compositing in tiled cases ([#1513](../../pull/1513))
- Speed up some tifffile and multi source access cases ([#1515](../../pull/1515))
- Allow specifying a minimum number of annotations elements when maxDetails is used ([#1521](../../pull/1521))
- Improved import of GeoJSON annotations ([#1522](../../pull/1522))

### Changes
- Limit internal metadata on multi-source files with huge numbers of sources ([#1514](../../pull/1514))
- Make DICOMweb assetstore imports compatible with Girder generics ([#1504](../../pull/1504))

### Bug Fixes
- Fix touch actions in the image viewer in some instances ([#1516](../../pull/1516))
- Fix multisource dtype issues that resulted in float32 results ([#1520](../../pull/1520))

## 1.28.1

### Improvements
- When writing zarr sinks through the converter, use jpeg compression for lossy data ([#1501](../../pull/1501))

### Changes
- Improve algorithm sweep example options ([#1498](../../pull/1498))

### Bug Fixes
- Guard a race condition in vips new_from_file ([#1500](../../pull/1500))
- Fix cropping with the zarr sink ([#1505](../../pull/1505))

## 1.28.0

### Features
- Zarr tile sink ([#1446](../../pull/1446))

### Improvements
- Prioritize tile sinks ([#1478](../../pull/1478))
- Add a dependency to the zarr source to read more compression types ([#1480](../../pull/1480))
- Guard fetching internal metadata on zarr sources that have less data ([#1481](../../pull/1481))
- Add a method to list registered extensions and mimetypes ([#1488](../../pull/1488))
- Reduce bioformats keeping file handles open ([#1492](../../pull/1492))
- Use more tile-frame textures in high frame count images ([#1494](../../pull/1494))
- Zarr tile sink: generate downsampled levels ([#1490](../../pull/1490))

### Changes
- Prohibit bioformats from reading zip directly ([#1491](../../pull/1491))

### Bug Fixes
- Fix an issue with single band on multi source with non uniform sources ([#1474](../../pull/1474))
- Allow alternate name axes in the multi source schema ([#1476](../../pull/1476))
- Adjust default threading on tile-frame generation to match documentation ([#1495](../../pull/1495))
- Fix how zarr sink directory is cleaned up ([#1496](../../pull/1496))

## 1.27.4

### Improvements
- Add a guard when reading incorrect associated images ([#1472](../../pull/1472))

## 1.27.3

### Improvements
- Log and recover from occasional openslide failures ([#1461](../../pull/1461))
- Add support for Imaging Data Commons ([#1450](../../pull/1450))
- Speed up some retiling ([#1471](../../pull/1471))

### Changes
- Make GDAL an optional dependency for the converter ([#1464](../../pull/1464))

### Bug Fixes
- Fix an issue with uniform band depth on multi source with non uniform sources ([#1459](../../pull/1459))
- Fix histogram request bug in band compositing mode ([#1463](../../pull/1463))
- Prevent duplicating config files with multiple writes ([#1467](../../pull/1467))

## 1.27.2

### Improvements
- Support range requests when downloading DICOMweb files ([#1444](../../pull/1444))
- Bypass some scaling code when compositing multi sources ([#1447](../../pull/1447), [#1449](../../pull/1449))
- Do not create needless alpha bands in the multi source ([#1451](../../pull/1451))
- Infer DICOM file size, when possible ([#1448](../../pull/1448))
- Swap styles faster in the frame viewer ([#1452](../../pull/1452))
- Reduce color fringing in multi source compositing ([#1456](../../pull/1456))
- Retry read_region if openslide reports an error ([#1457](../../pull/1457))

### Bug Fixes
- Fix an issue with compositing sources in the multi source caused by alpha range ([#1453](../../pull/1453))

## 1.27.1

### Improvements
- Read config values from the environment variables ([#1422](../../pull/1422))
- Optimizing when reading arrays rather than images from tiff files ([#1423](../../pull/1423))
- Better filter DICOM adjacent files to ensure they share series instance IDs ([#1424](../../pull/1424), [#1436](../../pull/1436), [#1442](../../pull/1442))
- Optimizing small getRegion calls and some tiff tile fetches ([#1427](../../pull/1427))
- Started adding python types to the core library ([#1432](../../pull/1432), [#1433](../../pull/1433), [#1437](../../pull/1437), [#1438](../../pull/1438), [#1439](../../pull/1439))
- Use parallelism in computing tile frames ([#1434](../../pull/1434))
- Support downloading DICOMweb files ([#1429](../../pull/1429))

### Changes
- Cleanup some places where get was needlessly used ([#1428](../../pull/1428))
- Moved some internal code out of the base class ([#1429](../../pull/1429))
- Handle changes to wsidicom ([#1435](../../pull/1435))
- Refactored the tile iterator to its own class ([#1441](../../pull/1441))

## 1.27.0

### Features
- Support affine transforms in the multi-source ([#1415](../../pull/1415))

### Improvements
- Remove NaN values from band information ([#1414](../../pull/1414))
- Add a singleBand option to the multi-source specification ([#1416](../../pull/1416))
- Allow better detection of multiple file dicom ([#1417](../../pull/1417))
- Better missing data detection from tifffile ([#1421](../../pull/1421))

### Changes
- Remove an unused parameter in a private method ([#1419](../../pull/1419))

## 1.26.3

### Improvements
- Reduce stderr noise in PIL and rasterio sources ([#1397](../../pull/1397))
- Harden OME tiff reader ([#1398](../../pull/1398))
- Improve checks for formats we shouldn't read ([#1399](../../pull/1399))
- Support negative x, y in addTile ([#1401](../../pull/1401))
- Add a utility function for getting loggers ([#1403](../../pull/1403))
- Get bioformats jar version if bioformats was started ([#1405](../../pull/1405))
- Improve thread safety of concurrent first reads using bioformats ([#1406](../../pull/1406))
- Read more metadata from DICOMweb ([#1378](../../pull/1378))
- Remove logic for determining DICOMweb transfer syntax ([#1393](../../pull/1393))
- Speed up tile output ([#1407](../../pull/1407))
- Speed up import time ([#1408](../../pull/1408))
- Speed up some tile iteration by reducing the chance of multiple image decodes ([#1410](../../pull/1410))

### Changes
- Use an enum for priority constants ([#1400](../../pull/1400))
- Don't automatically flush memcached tile cache on exit ([#1409](../../pull/1409))
- Shift where netcdf information is reported ([#1413](../../pull/1413))

### Bug Fixes
- Fix an issue emitting geojson annotations ([#1395](../../pull/1395))
- Fix an issue when tifffile reports no key frame ([#1396](../../pull/1396))
- Frame Selector: Auto-Range format for saving presets ([#1404](../../pull/1404))

## 1.26.2

### Improvements
- Fix the DICOM limit to say "Series" instead of "Studies" ([#1379](../../pull/1379))
- Add token authentication option for DICOMweb ([#1349](../../pull/1349))
- Use vips resize rather than reduce to increase speed ([#1384](../../pull/1384))
- Added annotation to geojson endpoint and utility ([#1385](../../pull/1385))

### Changes
- Handle setup_requires deprecation ([#1390](../../pull/1390))

### Bug Fixes
- Fix an issue applying ICC profile adjustments to multiple image modes ([#1382](../../pull/1382))
- Guard against bad tifffile magnification values ([#1383](../../pull/1383))
- Frame Selector component: ensure that no color can be assigned twice ([#1387](../../pull/1387))
- Remove white space in frame selector internal fields ([#1389](../../pull/1389))
- Fix a comparison between integer enums in configured item lists ([#1391](../../pull/1391))

## 1.26.1

### Improvements
- Have zarr use read-only mode ([#1360](../../pull/1360))
- Use minified geojs ([#1362](../../pull/1362))
- Configurable item list grid view ([#1363](../../pull/1363))
- Allow labels in item list view ([#1366](../../pull/1366))
- Improve cache key guard ([#1368](../../pull/1368))
- Improve handling dicom files in the working directory ([#1370](../../pull/1370))
- General handling of skipped levels ([#1373](../../pull/1373))

### Changes
- Update WsiDicomWebClient init call ([#1371](../../pull/1371))
- Rename DICOMweb AssetstoreImportView ([#1372](../../pull/1372))
- Harden bioformats shutdown ([#1375](../../pull/1375))

### Bug Fixes
- Default to "None" for the DICOM assetstore limit ([#1359](../../pull/1359))
- Fix series detection for some bioformats files ([#1365](../../pull/1365), [#1367](../../pull/1367))
- Fix time comparison in annotation history check ([#1369](../../pull/1369))
- Fix an issue with apply a frame style to ome tiffs ([#1374](../../pull/1374))
- Guard against bad tifffile magnification values ([#1376](../../pull/1376))

## 1.26.0

### Features
- Add a Zarr tile source (including ome.zarr) ([#1350](../../pull/1350))

### Improvements
- Style can specify a dtype of 'source' to maintain the original dtype even when compositing frames ([#1326](../../pull/1326))
- Max Merge option in Frame Selector ([#1306](../../pull/1306), [#1330](../../pull/1330), [#1336](../../pull/1336))
- Improve tifffile associated image detection ([#1333](../../pull/1333))
- Guard against throwing a javascript warning ([#1337](../../pull/1337))
- Test on Python 3.12 ([#1335](../../pull/1335))
- Added filtering and limit options to the DICOMweb assetstore ([#1327](../../pull/1327))
- Support more formats through PIL ([#1351](../../pull/1351))

### Changes
- Prohibit bioformats and vips from reading mrxs directly ([#1328](../../pull/1328))
- Handle Python 3.12 deprecating utcnow ([#1331](../../pull/1331))
- Turn down logging about annotation ACLs ([#1332](../../pull/1332))
- Add scope to the dicomweb import endpoint access decorator ([#1347](../../pull/1347))
- Drop support for Python 3.6 and Python 3.7 ([#1352](../../pull/1352))
- Standardize DICOMweb assetstore parameter names/style ([#1338](../../pull/1338))

## 1.25.0

### Features
- DICOMweb support, including a Girder assetstore ([#1303](../../pull/1303))

### Improvements
- Frame selection presets have configurable defaults ([#1301](../../pull/1301))
- Improved DICOM metadata extraction ([#1305](../../pull/1305))
- Support more region shapes in the annotation widget ([#1323](../../pull/1323))

### Changes
- Remove a needless guard around getting an icc profile ([#1316](../../pull/1316))
- Refactor fetching extra associated images from openslide ([#1318](../../pull/1318))
- Minor refactor of some of the internals of the tiff source ([#1322](../../pull/1322))

### Bug Fixes
- Guard against potential bad event stream timestamp ([#1306](../../pull/1306))

## 1.24.0

### Features
- Added a noCache option to opening tile sources ([#1296](../../pull/1296))
- Added a display/visible value to the annotation schema ([#1299](../../pull/1299))

### Improvements
- Band compositing is shown for single band images ([#1300](../../pull/1300))

### Changes
- Changed the cdn used for the SlideAtlas viewer ([#1297](../../pull/1297))

### Bug Fixes
- Band compositing wasn't working ([#1300](../../pull/1300))

## 1.23.7

### Improvements
- Add [common] extra_requires ([#1288](../../pull/1288))
- Add more logic for determining associated images in tiff source ([#1291](../../pull/1291))

### Changes
- Internal metadata get endpoint is now public ([#1285](../../pull/1285))

### Bug Fixes
- Fix an issue with presets and single frame images ([#1289](../../pull/1289))

## 1.23.6

### Improvements
- Allow scheduling histogram computation in Girder ([#1282](../../pull/1282))

### Bug Fixes
- Closing some styled sources could lead to prematurely closing file handles ([#1283](../../pull/1283))
- Band order could matter in styles ([#1284](../../pull/1284))

## 1.23.5

### Improvements
- Better expose ipyleaflet maps from remote files ([#1280](../../pull/1280))

### Bug Fixes
- Fix modifying annotations anonymously ([#1279](../../pull/1279))

## 1.23.4

### Improvements
- Harden when the bioformats reader claims it has a zero sized image ([#1268](../../pull/1268))
- Harden internal retiling.  This sometimes affected histograms ([#1269](../../pull/1269))
- Set annotation update user in client so it appears faster ([#1270](../../pull/1270))
- Harden reading with tifffile on images with bad axes information ([#1273](../../pull/1273))
- Include projection in metadata ([#1277](../../pull/1277))
- Better expose ipyleaflet maps ([#1278](../../pull/1278))

### Changes
- Adjust tifffile log level ([#1265](../../pull/1265))
- Use a newer version of the hammerjs touch events library in Girder ([#1266](../../pull/1266))

### Bug Fixes
- Allow users with only annotation access to edit annotations ([#1267](../../pull/1267))
- Fix filtering item lists in Girder by multiple phrases ([#1272](../../pull/1272))
- Style functions after band compositing had a styleIndex value set ([#1274](../../pull/1274))

## 1.23.3

### Improvements
- Frame selection presets ([#1237](../../pull/1237))
- Adjust the bounds on non geospatial leaflet maps ([#1249](../../pull/1249))
- Allow hiding metadata on item pages ([#1250](../../pull/1250))
- Allow caching rounded histograms ([#1252](../../pull/1252))
- Add an endpoint to make it easier to replace thumbnails ([#1253](../../pull/1253))
- Presets from Large Image Configuration file ([#1248](../../pull/1248), [#1256](../../pull/1256))
- Reduce memory allocation during some region tiling operations ([#1261](../../pull/1261))
- Reduce memory allocation during some styling operations ([#1262](../../pull/1262), [#1263](../../pull/1263))
- Added a max_annotation_input_file_length setting ([#1264](../../pull/1264))

### Changes
- Minor code changes based on suggestions from ruff linting ([#1257](../../pull/1257))
- Reduce pyvips log level ([#1259](../../pull/1259))
- Don't use dask threads when using nd2 to fetch tiles ([#1260](../../pull/1260))

### Bug Fixes
- Guard against ICC profiles that won't parse ([#1245](../../pull/1245))
- Fix filter button on item lists ([#1251](../../pull/1251))

## 1.23.2

### Improvements
- Allow editing metadata in item lists ([#1235](../../pull/1235))
- Frame selector hotkeys for channel or bands ([#1233](../../pull/1233))
- More consistency in how local and remote image conversions are performed in Girder ([#1238](../../pull/1238))
- Support showing data from subkeys in annotation lists ([#1241](../../pull/1241))

### Bug Fixes
- The nd2 reader throws a different exception with JP2 files ([#1242](../../pull/1242))
- Better guards on ACL migration ([#1243](../../pull/1243))

## 1.23.1

### Improvements
- Harden reading some nc files ([#1218](../../pull/1218))
- Increase the cache used for opening directories in the pylibtiff source ([#1221](../../pull/1221))
- Refactor style locking to increase parallelism ([#1224](../../pull/1224), [#1234](../../pull/1234))
- Better isGeospatial consistency ([#1228](../../pull/1228))
- Better channel handling on frame selector ([#1222](../../pull/1222))

### Changes
- Clean up some old slideatlas url references ([#1223](../../pull/1223))
- Band compositing defaults to visible bands ([#1230](../../pull/1230))

### Bug Fixes
- Pass style to histogram endpoint as json ([#1220](../../pull/1220))
- Don't show frame controls outside of the geojs viewer ([#1226](../../pull/1226))
- Fix updating the hidden style field for the frame selector ([#1227](../../pull/1227))
- Fix a bug calculating some histograms ([#1231](../../pull/1231))
- Fix showing the frame selector when there is no axis information ([#1230](../../pull/1230))

## 1.23.0

### Features
- Add tile source bandCount attribute ([#1214](../../pull/1214))
- Histogram range editor ([#1175](../../pull/1175))

### Improvements
- Harden the nd2 source to allow it to read more files ([#1207](../../pull/1207))
- Add ipyleaflet representation for JupyterLab ([#1065](../../pull/1065))
- When restyling a source, share band range calculations ([#1215](../../pull/1215))

### Changes
- Change how extensions and fallback priorities in Girder interact ([#1208](../../pull/1208))
- Reduce the default max texture size for frame quads ([#1212](../../pull/1212))

### Bug Fixes
- Fix clearing the style threshold cache ([#1210](../../pull/1210))

## 1.22.4

### Bug Fixes
- Fix a scope issue when deleting metadata ([#1203](../../pull/1203))

## 1.22.3

### Improvements
- Better DICOM multi-level detection ([#1196](../../pull/1196))
- Added an internal field to report populated tile levels in some sources ([#1197](../../pull/1197), [#1199](../../pull/1199))
- Allow specifying an empty style dict ([#1200](../../pull/1200))
- Allow rounding histogram bin edges and reducing bin counts ([#1201](../../pull/1201))
- Allow configuring which metadata can be added to items ([#1202](../../pull/1202))

### Changes
- Change how extensions and fallback priorities interact ([#1192](../../pull/1192))
- Refactor reading the .large_image_config.yaml file on the girder client ([#1193](../../pull/1193))
- Refactor of the which-folders-have-annotations pipeline ([#1194](../../pull/1194))

### Bug Fixes
- Fix an issue converting multiframe files that vips reads as single frame ([#1195](../../pull/1195))

## 1.22.2

### Changes
- Alter jpeg priority with the PIL source ([#1191](../../pull/1191))

### Bug Fixes
- Fix NeededInitPrefix namespace errors ([#1190](../../pull/1190))

## 1.22.1

### Improvements
- Reduce memory use in a mongo aggregation pipeline ([#1183](../../pull/1183))
- Remove rasterio dep on pyproj ([#1182](../../pull/1182))
- Filter on specific metadata from item lists ([#1184](../../pull/1184))
- Add a button to clear the filter on item lists ([#1185](../../pull/1185))
- Improve JSONDict usage ([#1189](../../pull/1189))

### Changes
- Log more often when importing files or making large images ([#1187](../../pull/1187))

## 1.22.0

### Features
- Add tile source dtype attribute ([#1144](../../pull/1144))
- Added rasterio tile source ([#1115](../../pull/1115))

### Improvements
- Parse qptiff and imagej vendor information ([#1168](../../pull/1168))

### Changes
- Remove an unneeded warnings filter ([#1172](../../pull/1172))
- Fix gdal warning suppression ([#1176](../../pull/1176))

## 1.21.0

### Improvements
- getPixel method and endpoint now returns rawer values ([#1155](../../pull/1155))
- Allow more sophisticated filtering on item lists from the Girder client ([#1157](../../pull/1157), [#1159](../../pull/1159), [#1161](../../pull/1161))

### Changes
- Rename tiff exceptions to be better follow python standards ([#1162](../../pull/1162))
- Require a newer version of girder ([#1163](../../pull/1163))
- Add manual mongo index names where index names might get too long ([#1166](../../pull/1166))
- Avoid using $unionWith for annotation searches as it isn't supported everywhere ([#1167](../../pull/1167))

### Bug Fixes
- The deepzoom tile source misreported the format of its tile output ([#1158](../../pull/1158))
- Guard against errors in a log message ([#1164](../../pull/1164))
- Fix thumbnail query typo ([#1165](../../pull/1165))

## 1.20.6

### Improvements
- Store current frame and style in the DOM for easier access ([#1136](../../pull/1136))
- Convert long girder GET and PUT requests to POSTs ([#1137](../../pull/1137))
- Propagate more feature events from geojs on annotations ([#1147](../../pull/1147))
- Add another mime type to those considered to be yaml ([#1149](../../pull/1149))

### Changes
- Add a guard if PIL doesn't support ImageCms ([#1132](../../pull/1132))
- Allow putting a yaml config file from a Girder API endpoint ([#1133](../../pull/1133))

### Bug Fixes
- Allow clearing the min/max fields of the frame selector ([#1130](../../pull/1130))
- Fix a bug with caching tiles and styling ([#1131](../../pull/1131))
- Fix setting minimum values on bands from the frame selector ([#1138](../../pull/1138))
- Fix a version reference in the source extras_require ([#1150](../../pull/1150))

## 1.20.5

### Improvements
- Improve access and repr of metadata and style ([#1121](../../pull/1121))

### Changes
- Remove psutil hard dependency ([#1127](../../pull/1127))

## 1.20.4

### Improvements
- Better cache handling with Etags ([#1097](../../pull/1097))
- Reduce duplicate computation of slow cached values ([#1100](../../pull/1100))
- Reconnect to memcached if the connection fails ([#1104](../../pull/1104))
- Better frame selector on Girder item page ([#1086](../../pull/1086))

### Bug Fixes
- Tile serving can bypass loading a source if it is in memory ([#1102](../../pull/1102))
- Don't copy style lock when semi-duplicating a tile source ([#1114](../../pull/1114))

### Changes
- On the large image item page, guard against overflow ([#1096](../../pull/1096))
- Specify version of simplejpeg for older python ([#1098](../../pull/1098))
- Better expose the Girder yaml config files from python ([#1099](../../pull/1099))

## 1.20.3

### Changes
- Update dicom source for upstream changes ([#1092](../../pull/1092))

## 1.20.2

### Improvements
- Allow ICC correction to specify intent ([#1066](../../pull/1066))
- Make tile sources pickleable ([#1071](../../pull/1071))
- Extract scale information from more bioformats files ([#1074](../../pull/1074))
- Speed up validating annotations with user fields ([#1078](../../pull/1078))
- Speed up validating annotation colors ([#1080](../../pull/1080))
- Support more complex bands from the test source ([#1082](../../pull/1082))
- Improve error thrown for invalid schema with multi source ([#1083](../../pull/1083))
- Support multi-frame PIL sources ([#1088](../../pull/1088))

### Bug Fixes
- The cache could reuse a class inappropriately ([#1070](../../pull/1070))
- Increase size of annotation json that will be parsed ([#1075](../../pull/1075))
- Quote ETag tags ([#1084](../../pull/1084))

### Changes
- Stop packaging the slideatlas viewer directly ([#1085](../../pull/1085))

## 1.20.1

### Bug Fixes
- Fix packaging listing various source requirements ([#1064](../../pull/1064))

## 1.20.0

### Features
- ICC color profile support ([#1037](../../pull/1037), [#1043](../../pull/1043), [#1046](../../pull/1046), [#1048](../../pull/1048), [#1052](../../pull/1052))

  Note: ICC color profile adjustment to sRGB is the new default.  This can be disabled with a config setting or on a per tile source basis.

- Support arbitrary axes in the test and multi sources ([#1054](../../pull/1054))

### Improvements
- Speed up generating tiles for some multi source files ([#1035](../../pull/1035), [#1047](../../pull/1047))
- Render item lists faster ([#1036](../../pull/1036))
- Reduce bioformats source memory usage ([#1038](../../pull/1038))
- Better pick the largest image from bioformats ([#1039](../../pull/1039), [#1040](../../pull/1040))
- Speed up some images handled with bioformats ([#1063](../../pull/1063))
- Cache histogram thresholds ([#1042](../../pull/1042))
- Add `_repr_png_` for Jupyter ([#1058](../../pull/1058))
- Ignore bogus tifffile resolutions ([#1062](../../pull/1062))

## 1.19.3

### Improvements
- Speed up rendering Girder item page metadata in some instances ([#1031](../../pull/1031))
- Speed up opening some multi source files ([#1033](../../pull/1033))
- Test nd2 source on Python 3.11 ([#1034](../../pull/1034))

### Bug Fixes
- Fix an issue with non-square tiles in the multi source ([#1032](../../pull/1032))

## 1.19.2

### Improvements
- Better parse svs pixel size in tiff and tifffile sources ([#1021](../../pull/1021))
- Add geojson to known mime types ([#1022](../../pull/1022))
- Handle upcoming matplotlib deprecations ([#1025](../../pull/1025))
- Handle upcoming numpy deprecations ([#1026](../../pull/1026))

## 1.19.1

### Improvements
- Improve tifffile associated image detection ([#1019](../../pull/1019))

## 1.19.0

### Features
- Add a frames property to the tile source as a short hand for getting the number of frames from the metadata ([#1014](../../pull/1014))

### Improvements
- Better release file handles ([#1007](../../pull/1007))
- Support tiny images from the test source ([#1013](../../pull/1013))
- Speed up loading or parsing some multi sources ([#1015](../../pull/1015))
- Better scale uint32 images ([#1017](../../pull/1017))

### Changes
- Don't report filename in internal PIL metadata ([#1006](../../pull/1006))

### Bug Fixes
- Better output new vips images as float32 ([#1016](../../pull/1016))
- Pin tinycolor2 for annotations ([#1018](../../pull/1018))

## 1.18.0

### Features
- Add a DICOM tile source ([#1005](../../pull/1005))

### Improvements
- Better control dtype on multi sources ([#993](../../pull/993))
- Don't use dask threads when using nd2 to fetch tiles ([#994](../../pull/994))
- Set mime type for imported girder files ([#995](../../pull/995))
- Specify token scopes for girder endpoints ([#999](../../pull/999), [#1000](../../pull/1000))
- Set the qptiff extension to prefer the tiff reader ([#1003](../../pull/1003))

### Bug Fixes
- Use open.read rather than download to access files in Girder ([#989](../../pull/989))
- Fix nd2 source scale ([#990](../../pull/990))
- Do not raise a login request when checking if the user can write annotations ([#991](../../pull/991))

## 1.17.3

### Changes
- Test on Python 3.11 ([#986](../../pull/986))

## 1.17.2

### Bug Fixes
- Fixed overcaching annotations ([#983](../../pull/983))
- Depending on timing, annotations could be inappropriately paged ([#984](../../pull/984))

## 1.17.1

### Improvements
- Fallback when server notification streams are turned off ([#967](../../pull/967))
- Show and edit yaml and json files using codemirror ([#969](../../pull/969), [#971](../../pull/971))
- Show configured item lists even if there are no large images ([#972](../../pull/972))
- Add metadata and annotation metadata search modes to Girder ([#974](../../pull/974))
- Add the ability to show annotation metadata in item annotation lists ([#977](../../pull/977))
- Support ETAG in annotation rest responses for better browser caching ([#978](../../pull/978))
- Thumbnail maintenance endpoints ([#980](../../pull/980))
- Handle lif file extensions ([#981](../../pull/981))

### Bug Fixes
- Fixed an issue with compositing multiple frames ([#982](../../pull/982))

## 1.17.0

### Features
- Style functions ([#960](../../pull/960))
- Annotation metadata endpoints ([#963](../../pull/963))

### Improvements
- Reduce rest calls to get settings ([#953](../../pull/953))
- Add an endpoint to delete all annotations in a folder ([#954](../../pull/954))
- Support relabeling axes in the multi source ([#957](../../pull/957))
- Reduce a restriction on reading some tiff files ([#958](../../pull/958))

### Changes
- Improve internals for handling large annotation elements ([#961](../../pull/961))

### Bug Fixes
- Harden adding images to the item list ([#955](../../pull/955))
- Fix checking user annotation document length ([#956](../../pull/956))
- Improve scaled overlays ([#959](../../pull/959))

## 1.16.2

### Improvements
- Add a general filter control to item lists ([#938](../../pull/938), [#941](../../pull/941))
- Item list modal dialogs are wider ([#939](../../pull/939))
- Improve mimetypes on upload to Girder ([#944](../../pull/944))

### Bug Fixes
- Fix iterating tiles where the overlap larger than the tile size ([#940](../../pull/940))
- Better ignore tiff directories that aren't part of the pyramid ([#943](../../pull/943))
- Fix an issue with styling frames in ome tiffs ([#945](../../pull/945))
- Better handle large user records in annotation elements ([#949](../../pull/949))
- Harden which output formats are supported ([#950](../../pull/950))

### Changes
- Adjusted rest request logging rates for region endpoint ([#948](../../pull/948))

## 1.16.1

### Improvements
- Add annotation access controls at the folder level ([#905](../../pull/905))
- Reduce error messages and make canRead results more accurate ([#918](../../pull/918), [#919](../../pull/919), [#920](../../pull/920))
- Sort columns in item lists based ([#925](../../pull/925), [#928](../../pull/928))
- Better handle tiffs with orientation flags in pil source ([#924](../../pull/924))
- Support a bands parameter for the test source ([#935](../../pull/935))
- Add annotation creation access flag ([#937](../../pull/937))

### Changes
- Remove some extraneous values from metadata responses ([#932](../../pull/932))
- Reduce some messages to stderr from other libraries ([#919](../../pull/919))
- Avoid some warnings in Python 3.10 ([#913](../../pull/913))

## 1.16.0

### Features
- Add a tifffile tile source ([#885](../../pull/885), [#896](../../pull/896), [#903](../../pull/903))
- Added a canReadList method to large_image to show which source can be used ([#895](../../pull/895))
- Optionally show metadata in item lists ([#901](../../pull/901))
- Register the tile output formats from PIL ([#904](../../pull/904))
- Copy tilesource instances to add styles ([#894](../../pull/894))

### Improvements
- Pass options to the annotationLayer mode ([#881](../../pull/881))
- Support more style range options ([#883](../../pull/883))
- When converting girder images locally, prefer mount paths ([#886](../../pull/886))
- Store the id of job results for easier post-job work ([#887](../../pull/887))
- Harden style compositing of partial tiles ([#889](../../pull/889))
- Cache read_tiff calls to speed up restyling ([#891](../../pull/891))
- Speed up styling by doing less ([#892](../../pull/892))
- Add local color definitions ([#858](../../pull/858))
- Inheritable config files ([#897](../../pull/897))
- Add geospatial property ([#818](../../pull/818), [#908](../../pull/908))
- Improve repr of image bytes ([#902](../../pull/902))
- Handle nodata style when specified as a string ([#914](../../pull/914))

### Changes
- Be more consistent in source class name attribute assignment ([#884](../../pull/884))

### Bug Fixes
- Fix alpha on GDAL sources with a projection that have an explicit alpha channel ([#909](../../pull/909), [#915](../../pull/915))

## 1.15.1

### Improvements
- When scaling heatmap annotations, use an appropriate value ([#878](../../pull/878))
- Use the girder client build time for cache control ([#879](../../pull/879))

## 1.15.0

### Features
- Abstract caching and support entrypoints ([#876](../../pull/876))

### Bug Fixes
- Fix getPixel for single channel sources ([#875](../../pull/875))

## 1.14.5

### Improvements
- Speed up ingesting annotations ([#870](../../pull/870))
- Reduce the chance of blinking on annotation layers ([#871](../../pull/871))
- Reduce updates when modifying annotations ([#872](../../pull/872))

### Bug Fixes
- Improve annotation upload; support full annotation documents ([#869](../../pull/869))

## 1.14.4

### Improvements
- Better handle editing polygons with holes ([#857](../../pull/857))
- Support fetching yaml config files ([#860](../../pull/860))
- Optionally include bounding box information with annotation queries ([#851](../../pull/851))
- Reduce memory copying in the nd2 reader ([#853](../../pull/853))
- Add support for boolean annotation operations ([#865](../../pull/865))
- Speed up removing all annotations from an item ([#863](../../pull/863))

### Bug Fixes
- Fix issues with the nd2 reader ([#866](../../pull/866), [#867](../../pull/867))
- Honor the highlight size limit with centroid annotations ([#861](../../pull/861))

## 1.14.3

### Improvements
- Support polygon annotations with holes ([#844](../../pull/844))
- New annotations get a default name if they do not have one ([#843](../../pull/843))
- Explicitly mark vips output as tiled ([#848](../../pull/848))
- Change how annotations are uploaded from the UI ([#845](../../pull/845))

## 1.14.2

### Improvements
- Improve handling for vips pixel formats in addTile ([#838](../../pull/838))
- Add validateCOG method to GDALFileTileSource ([#835](../../pull/835))

### Changes
- The default logger now uses the null handler ([#840](../../pull/840))

## 1.14.1

### Changes
- The sources extra_installs didn't include all sources ([#833](../../pull/833))

## 1.14.0

### Features
- Vips tile source and tiled file writer ([#816](../../pull/816), [#827](../../pull/827), [#830](../../pull/830))

### Improvements
- Handle file URLs with GDAL ([#820](../../pull/820))
- Add a hasAlpha flag to image annotations ([#823](../../pull/823))
- Allow dict for style ([#817](../../pull/817))
- Support drawing multipolygon regions ([#832](../../pull/832))

### Bug Fixes
- Fix a range check for pixelmap annotations ([#815](../../pull/815))
- Harden checking if a PIL Image can be read directly from a file pointer ([#822](../../pull/822))

### Changes
- Handle PIL deprecations ([#824](../../pull/824))

## Version 1.13.0

### Features
- Add support for ellipse and circle annotations ([#811](../../pull/811))
- Support pickle output of numpy arrays for region, thumbnail, and tile_frames endpoints ([#812](../../pull/812))

### Improvements
- Improve parsing OME TIFF channel names ([#806](../../pull/806))
- Improve handling when a file vanishes ([#807](../../pull/807))
- Add TileSourceXYZRangeError ([#809](../../pull/809))

## Version 1.12.0

### Features
- Refactor the nd2 source to use the nd2 library ([#797](../../pull/797))

### Improvements
- Add options to threshold near min/max based on the histogram ([#798](../../pull/798))
- Mark vsi extensions as being preferred by the bioformats source ([#793](../../pull/793))
- Add mouse events to overlay annotations ([#794](../../pull/794))
- Use orjson instead of ujson for annotations ([#802](../../pull/802))
- Use simplejpeg for jpeg encoding rather than PIL ([#800](../../pull/800))
- Use pylibtiff instead of libtiff ([#799](../../pull/799))

### Bug Fixes
- Harden annotation ACL migration code ([#804](../../pull/804))

## Version 1.11.2

### Improvements
- Emit events when an overlay annotation layer is created ([#787](../../pull/787))
- Minor improvements to setFrameQuad to make it more flexible ([#790](../../pull/790))
- Support drawing polygon selection regions ([#791](../../pull/791))
- Add some automating options to getTileFramesQuadInfo ([#792](../../pull/792))

### Changes
- Change how we do a version check ([#785](../../pull/785))

## Version 1.11.1

### Improvements
- Add options to get frame quad info from python ([#783](../../pull/783))

## Version 1.11.0

### Improvements
- Release memory associated with a lazy tile if it has been loaded ([#780](../../pull/780))

### Bug Fixes
- Tile overlaps on subset regions could be wrong ([#781](../../pull/781))

## Version 1.11.0

### Features
- Initial implementation of multi-source tile source ([#764](../../pull/764))
- Added pixelmap annotation element ([#767](../../pull/767), [#776](../../pull/776))

### Improvements
- Add more opacity support for image overlays ([#761](../../pull/761))
- Make annotation schema more uniform ([#763](../../pull/763))
- Improve TileSource class repr ([#765](../../pull/765))
- Improve frame slider response with base quads ([#771](../../pull/771))
- Default to nearest-neighbor scaling in lossless image conversion ([#772](../../pull/772))
- Improve the import time ([#775](../../pull/775), [#777](../../pull/777))

### Bug Fixes
- The tile iterator could return excess tiles with overlap ([#773](../../pull/773))

## Version 1.10.0

### Features
- Added image annotation element ([#742](../../pull/742), [#750](../../pull/750))
- Allow the discrete scheme to be used on all tile sources ([#755](../../pull/755))

### Improvements
- Expand user paths ([#746](../../pull/746))
- Work with more matplotlib palettes ([#760](../../pull/760))

### Changes
- Use importlib rather than pkg_resources internally ([#747](../../pull/747), [#778](../../pull/778))

### Bug Fixes
- Fix expanding a style palette with a single named color ([#754](../../pull/754))

## Version 1.9.0

### Features
- Better palette support in styles ([#724](../../pull/724))
- Enumerate available palettes ([#741](../../pull/741))

### Improvements
- The openjpeg girder source handles uploaded files better ([#721](../../pull/721))
- Suppress some warnings on Girder and on bioformats ([#727](../../pull/727))

### Bug Fixes
- Harden detecting file-not-found ([#726](../../pull/726))
- Fix the pylibmc dependency for windows ([#725](../../pull/725))

## Version 1.8.11

### Changes
- Reduce extraneous files in large_image distribution ([#718](../../pull/718))

## Version 1.8.10

### Changes
- Improve library dependencies in setup.py ([#710](../../pull/710), [#715](../../pull/715))

## Version 1.8.9

### Changes
- Include the converter in the girder tasks dependency ([#707](../../pull/707))

## Version 1.8.8

### Changes
- Some log levels have been adjusted ([#689](../../pull/689), [#695](../../pull/695))

## Version 1.8.7

### Improvements
- Add the image converter to the extra requires ([#677](../../pull/677))
- All file tile sources can take either strings or pathlib.Path values ([#683](../../pull/683))
- On Girder with read-only assetstores, return results even if caching fails ([#684](../../pull/684))
- Handle geospatial files with no explicit projection ([#686](../../pull/686))

### Bug Fixes
- Fix default properties on annotations when emitted as centroids ([#687](../../pull/687))

## Version 1.8.6

### Bug Fixes
- A change in the Glymur library affected how missing files were handled ([#675](../../pull/675))

## Version 1.8.5

### Improvements
- Better Girder client exports ([#674](../../pull/674))

## Version 1.8.4

### Improvements
- Improve warnings on inefficient tiff files ([#668](../../pull/668))
- Add more options to setFrameQuad ([#669](../../pull/669), [#670](../../pull/670))
- Improved concurrency of opening multiple distinct tile sources ([#671](../../pull/671))

## Version 1.8.3

### Improvements
- Better handle item changes with tile caching ([#666](../../pull/666))

## Version 1.8.2

### Improvements
- Make the image viewer control css class more precise ([#665](../../pull/665))

## Version 1.8.1

### Improvements
- Allow GDAL source to read non-geospatial files ([#655](../../pull/655))
- Rename Exceptions to Errors, improve file-not-found errors ([#657](../../pull/657))
- More robust OME TIFF handling ([#660](../../pull/660))
- large-image-converter can exclude specified associated images ([#663](../../pull/663))
- Harden on some openslide errors ([#664](../../pull/664))

### Bug Fixes
- getBandInformation could fail on high bands in some cases ([#651](../../pull/651))
- Band information should always be 1-indexed ([#659](../../pull/659))
- Use GDAL to subset a non-geospatial image ([#662](../../pull/662))

## Version 1.8.0

### Features
- Deepzoom tile source ([#641](../../pull/641), [#647](../../pull/647))

### Bug Fixes
- Harden tile source detection ([#644](../../pull/644))

## Version 1.7.1

### Improvements
- More control over associated image caching ([#638](../../pull/638))
- Better handling some geospatial bounds ([#639](../../pull/639))

## Version 1.7.0

### Features
- Provide band information on all tile sources ([#622](../../pull/622), [#623](../../pull/623))
- Add a tileFrames method to tile sources and appropriate endpoints to composite regions from multiple frames to a single output image ([#629](../../pull/629))
- The test tile source now support frames ([#631](../../pull/631), [#632](../../pull/632), [#634](../../pull/634), [#634](../../pull/634))

### Improvements
- Better handle TIFFs with missing levels and tiles ([#624](../../pull/624), [#627](../../pull/627))
- Better report inefficient TIFFs ([#626](../../pull/626))
- Smoother cross-frame navigation ([#635](../../pull/635))

## Version 1.6.2

### Improvements
- Better reporting of memcached cache ([#613](../../pull/613))
- Better handle whether proj string need the +init prefix ([#620](../../pull/620))

### Changes
- Avoid a bad version of Pillow ([#619](../../pull/619))

## Version 1.6.1

### Improvements
- Allow specifying content disposition filenames in Girder REST endpoints ([#604](../../pull/604))
- Improve caching of unstyled tiles when compositing styled types ([#605](../../pull/605))
- Speed up compositing some styled tiles ([#606](../../pull/606), [#609](../../pull/609))
- Handle some nd2 files with missing metadata ([#608](../../pull/608))
- Allow setting default tile query parameters in the Girder client ([#611](../../pull/611))

### Changes
- Don't use underscore parameters in image caching keys ([#610](../../pull/610))

## Version 1.6.0

### Features
- Allow setting the cache memory portion and maximum for tilesources ([#601](../../pull/601))
- Add heatmap and griddata to the annotation schema ([#589](../../pull/589))
- Regions can be output as tiled tiffs with scale or geospatial metadata ([#594](../../pull/594))

### Improvements
- Cache histogram requests ([#598](../../pull/598))
- Allow configuring bioformats ignored extensions ([#603](../../pull/603))
- Tilesources always have self.logger for logging ([#602](../../pull/602))

### Changes
- Use float rather than numpy.float ([#600](../../pull/600))

### Bug Fixes
- The nd2reader module now requires files to have an nd2 extension ([#599](../../pull/599))
- Fix the progress bar when uploading annotations ([#589](../../pull/589))

## Version 1.5.0

### Features
- Allow converting a single frame of a multiframe image ([#579](../../pull/579))
- Add a convert endpoint to the Girder plugin ([#578](../../pull/578))
- Added support for creating Aperio svs files ([#580](../../pull/580))
- Added support for geospatial files with GCP ([#588](../../pull/588))

### Improvements
- More untiled tiff files are handles by the bioformats reader ([#569](../../pull/569))
- Expose a concurrent option on endpoints for converting images ([#583](../../pull/583))
- Better concurrency use in image conversion ([#587](../../pull/587))
- Handle more OME tiffs ([#585](../../pull/585), [#591](../../pull/591))
- Better memcached error logging ([#592](../../pull/592))

### Changes
- Exceptions on cached items are no longer within the KeyError context ([#584](../../pull/584))
- Simplified thumbnail generation by removing the level-0 option ([#593](../../pull/593))

### Bug Fixes
- Updated dependencies to work with changes to the nd2reader ([#596](../../pull/596))

## Version 1.4.3

### Improvements
- In Girder, prefer geospatial sources for geospatial data ([#564](../../pull/564))

### Bug Fixes
- The GDAL source failed when getting band ranges on non-integer data ([#565](../../pull/565))

## Version 1.4.2

### Features
- Added a Girder endpoint to get metadata on associated images ([#561](../../pull/561))
- Added an option to try all Girder items for use as large images ([#562](../../pull/562))

### Improvements
- Reduce gdal warning about projection strings ([#559](../../pull/559))
- Don't report needless frame information for some single frame files ([#558](../../pull/558))
- Send Backbone events on frame changes in the viewer ([#563](../../pull/563))

### Changes
- The PIL tilesource priority is slightly higher than other fallback sources ([#560](../../pull/560))

### Bug Fixes
- Fix compositing when using different frame numbers and partial tiles ([#557](../../pull/557))

## Version 1.4.1

### Features
- Multiple frames can be composited together with the style option ([#554](../../pull/554), [#556](../../pull/556))

### Improvements
- Warn when opening an inefficient tiff file ([#555](../../pull/555))

## Version 1.4.0

### Features
- Added a `canRead` method to the core module ([#512](../../pull/512))
- Image conversion supports JPEG 2000 (jp2k) compression ([#522](../../pull/522))
- Image conversion can now convert images readable by large_image sources but not by vips ([#529](../../pull/529))
- Added an `open` method to the core module as an alias to `getTileSource` ([#550](../../pull/550))
- Added an `open` method to each file source module ([#550](../../pull/550))
- Numerous improvement to image conversion ([#533](../../pull/533), [#535](../../pull/535), [#537](../../pull/537), [#541](../../pull/541), [#544](../../pull/544), [#545](../../pull/545), [#546](../../pull/546), [#549](../../pull/549))

### Improvements
- Better release bioformats resources ([#502](../../pull/502))
- Better handling of tiff files with JPEG compression and RGB colorspace ([#503](../../pull/503))
- The openjpeg tile source can decode with parallelism ([#511](../../pull/511))
- Geospatial tile sources are preferred for geospatial files ([#512](../../pull/512))
- Support decoding JP2k compressed tiles in the tiff tile source ([#514](../../pull/514))
- Hardened tests against transient timing issues ([#532](../../pull/532), [#536](../../pull/536))

### Changes
- The image conversion task has been split into two packages, large_image_converter and large_image_tasks.  The tasks module is used with Girder and Girder Worker for converting images and depends on the converter package.  The converter package can be used as a stand-alone command line tool ([#518](../../pull/518))

### Bug Fixes
- Harden updates of the item view after making a large image ([#508](../../pull/508), [#515](../../pull/515))
- Tiles in an unexpected color mode weren't consistently adjusted ([#510](../../pull/510))
- Harden trying to add an annotation before the viewer is ready ([#547](../../pull/547))
- Correctly report the tile size after resampling in the tileIterator ([#538](../../pull/538))

## Version 1.3.2

### Improvements
- Reduce caching associated images when the parent item changes ([#491](../../pull/491))
- Test with Python 3.9 ([#493](../../pull/493))
- Add a hideAnnotation function in the client ([#490](../../pull/490))
- Expose more resample options for region and histogram endpoints ([#496](../../pull/496))
- Improve OME tiff preferred level calculation for OME tiffs with subifds ([#496](../../pull/496))

### Changes
- Include the annotationType to the annotation conversion method in the client ([#490](../../pull/490))

### Notes
- This will be the last version to support Python 2.7 and 3.5.

## Version 1.3.1

### Improvements
- Include ETag support in some Girder rest requests to reduce data transfer ([#488](../../pull/488))

### Changes
- Don't let bioformats handle pngs ([#487](../../pull/487))

## Version 1.3.0

### Features
- Added bioformats tile source ([#463](../../pull/463))
- Handle OME Tiff files with sub-ifd images ([#469](../../pull/469))

### Improvements
- Expose more internal metadata ([#479](../../pull/479))
- Improve how Philips XML internal metadata is reported ([#475](../../pull/475))
- Show aperio version in internal metadata ([#474](../../pull/474))
- Add css classes to metadata on the item page ([#472](../../pull/472))
- The Girder web client exports the ItemViewWidget ([#483](../../pull/483))
- Read more associated images in openslide formats ([#486](../../pull/486))

### Bug Fixes
- Add a reference to updated time to avoid overcaching associated images ([#477](../../pull/477))
- Fix a typo in the settings page ([#473](../../pull/473))

## Version 1.2.0

### Features
- Added endpoints to remove old annotations ([#432](../../pull/432))
- Show auxiliary images and metadata on Girder item pages ([#457](../../pull/457))

### Improvements
- Migrate some database values on start to allow better annotation count reporting ([#431](../../pull/431))
- Speed up Girder item list annotation counts ([#454](../../pull/454))
- Read more OME Tiff files ([#450](../../pull/450))
- Handle subimages of different component depths ([#449](../../pull/449))
- When scaling, adjust reported mm_x/y ([#441](../../pull/441))

### Changes
- Standardize metadata for tile sources with multiple frames ([#433](../../pull/433))
- Unify code to check if a tile exists ([#462](../../pull/462))
- Switch to ElementTree, as cElementTree is deprecate ([#461](../../pull/461))
- Refactor how frame information is added to metadata ([#460](../../pull/460))
- Upgrade GeoJS to the latest version ([#451](../../pull/451))

### Bug Fixes
- Fix a threading issue with multiple styled tiles ([#444](../../pull/444))
- Guard against reading tiff tiles outside of the image ([#458](../../pull/458))
- Guard against a missing annotation value ([#456](../../pull/456)(
- Fix handling Girder filenames with multiple periods in a row ([#459](../../pull/459))
- Work around a file descriptor issue in cheroot ([#465](../../pull/465))

## Version 1.1.0

### Features
- Added nd2 tile source ([#419](../../pull/419))

### Bug Fixes
- Fixed an issue where, if users or groups were deleted outside of normal methods, checking an annotation's access would delete its elements ([#428](../../pull/428))
- Fix an issue where retiling some tile sources could fail ([#427](../../pull/427))

### Improvements
- Testing fully with Python 3.8 ([#429](../../pull/429))

## Version 1.0.4

### Bug Fixes
- Fixed an issue where retiling some tile sources could fail ([#427](../../pull/427))

## Version 1.0.3

### Features
- Added gdal tile source ([#418](../../pull/418))
- Added a GET large_image/sources endpoint to list versions of all installed sources ([#421](../../pull/421))

### Bug Fixes
- Fixed an issue where changing the annotation history setting when Girder's settings' cache was enable wouldn't take effect until after a restart ([#422](../../pull/422))
- Fixed an issue when used as a Girder plugin and served with a proxy with a prefix path ([#423](../../pull/423))

### Improvements
- Better handling of imported file formats with adjacent files ([#424](../../pull/424))

## Version 1.0.2

### Features
- Add style options for all tile sources to remap channels and colors ([#397](../../pull/397))
- Better support for high bit-depth images ([#397](../../pull/397))

### Improvements
- Make it easier to load the annotation-enable web viewers ([#402](../../pull/402))
- Improved support for z-loops in OMETiff files ([#397](../../pull/397))
- Support using Glymur 0.9.1 ([#411](../../pull/411))

### Bug Fixes
- Fixed an issue where a Girder image conversion task could raise an error about a missing file ([#409](../../pull/409))

## Version 1.0.1

### Features
- Get annotations elements by centroid ([#371](../../pull/371))
- Added an annotation badge to the image list ([#372](../../pull/372))
- Added openjpeg tile source ([#380](../../pull/380))
- Handle different tiff orientations in the tiff tile source ([#390](../../pull/390))

### Improvements
- Increased the annotation page limit ([#367](../../pull/367))
- Increased the annotations response time limit ([#389](../../pull/389))
- Improved handling of tiff files with multiple tiled images ([#373](../../pull/373))
- Don't reset backbone models on saving existing annotations ([#399](../../pull/399))

### Changes
- Use girder/large_image_wheels ([#384](../../pull/384))
- Changed the mapnik tile source style defaults ([#395](../../pull/395))

### Bug Fixes
- Fixed the pyproj minimum version ([#366](../../pull/366))
- Guard against GDAL open errors ([#375](../../pull/375))
- Better handle annotations with zero elements ([#398](../../pull/398))
- Sorting tile layers could use a dictionary comparison ([#396](../../pull/396))

## Version 1.0.0

This is a substantial refactor from preliminary versions.  Now that setuptools_scm is used for versioning, all merges to master are automatically published to pypi as development versions.

Tile sources are now fully modular and are installed via pip.  File extensions and mime type are now used as part of the order that tile sources are checked, giving more control over which tile source is used by default.

The Girder plugin has been divided into the parts requiring annotations and the parts that are only necessary for large images.

Python 3.4 support was dropped.
