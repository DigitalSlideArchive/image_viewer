from pathlib import Path

import pooch

EXAMPLES_FOLDER = Path('format_examples')

format_examples = [
    dict(
        name='TIFF',
        extensions=['tiff', 'tif', 'ptif', 'ptiff', 'qptiff'],
        long_name='Tagged Image File Format',
        reference='https://www.itu.int/itudoc/itu-t/com16/tiff-fx/docs/tiff6.pdf',
        examples=[
            dict(
                filename='tcgaextract_ihergb_labeled.tiff',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/faf5c8da95a5e624c70300afb98318e3421cc86ac27755f207075fa2f68aa23d099bec802007a86533579c6aadc97b4ce710d272eb871172d4b2c7e9ff6e9cad/download',
                hash='8a03ae4370a35517e2ab2249177d903c1ea52869e30dc558750c626d9edbae6f',
            ),
        ],
    ),
    dict(
        name='SVS',
        extensions=['svs', 'svslide'],
        long_name='Aperio ScanScope Virtual Slide',
        reference='https://paulbourke.net/dataformats/svs/',
        examples=[
            dict(
                filename='CMU-1.svs',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/3c31fd959302b56cf62020ed01312ab964bd776fbf7139a283bdde7c351d9211cec008eaf7f3b1b54e8e14c8293c6e6f77a389406e72318cb954f4a1a65f9ae1/download',
                hash='00a3d54482cd707abf254fe69dccc8d06b8ff757a1663f1290c23418c480eb30',
            ),
        ],
    ),
    dict(
        name='OME-TIFF',
        extensions=['ome.tiff', 'ome.tif', 'ome'],
        long_name='Open Microscopy Environment Tagged Image File Format',
        reference='https://docs.openmicroscopy.org/ome-model/5.6.3/ome-tiff/',
        examples=[
            dict(
                filename='DDX58_AXL_EGFR_well2_XY04.ome.tif',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/d255bac7fdb3318ca015a688d396a2fc618a1383bc1751ec56100bf50b38f16d2d71a3837104fbe41bad524807123108e6fe0984f76bbf5e22656cea7541d44e/download',
                hash='5dabb19081db4893d58b6680e54b566fc6246ccbde10d41413201afd96499482',
            ),
        ],
    ),
    dict(
        name='NDPI',
        extensions=['ndpi', 'ndpis'],
        long_name='Hamamatsu NanoZoomer Digital Pathology Image',
        reference='https://openslide.org/formats/hamamatsu/',
        examples=[
            dict(
                filename='test3.ndpis',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/07fa23e39d1b79eb436aa282e340787e11ef32cd9547c246c0040f05bd0f0e6d283cf4107f31fdc0ef923d847d93941901e32885a163ba31da6c82f76d1b9744/download',
                hash='35542dff44d7844f1fac04c1703bdb1476f90f484457907ead132203e6de066e',
            ),
            dict(
                filename='test3-TRITC 2 (560).ndpi',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/6eae0f8bf57f42dee6a6f7f1da6d249fe06b11d7e3ac9c55721841c50961e4518b451bae9874d6aa767b1a53d4ac3bba3f72917b45cf21a8ddae8efb264a78a2/download',
                skip=True,
                hash='f02985d30aa38060e83c9477a4435cb81b2a0a234d3d664195dfc5a4e2657be8',
            ),
            dict(
                filename='test3-FITC 2 (485).ndpi',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/8f44a0a39a3a924ad831eb30ac5d906c601e9d16c79834edbe90affdf9c7ff54eea753075c117881ffb76d3ce542a18da3e4b262c87f4ec850e9fedd31b97385/download',
                skip=True,
                hash='455069a02a761ecfedb93492f103dec8c5b23b7c46fd47e9d8d22191ea803018',
            ),
            dict(
                filename='test3-DAPI 2 (387).ndpi',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/5ebdc2aed6ab277eb1644b9a7f489b70127b561ee8f9505677b1a3d3446d2d7a6ce10824d1e77ddd815a9a9214dc4423cb7de8539213265b5575e6ffc0d9e25f/download',
                skip=True,
                hash='9294d31f304f20ef1df1e08650d3f225b8ed44db8b2dc0d52f584449f85bdca2',
            ),
        ],
    ),
    dict(
        name='Zarr',
        extensions=['zarr', 'zarray', 'zattrs', 'zgroup', 'zip', 'db', 'sqlite'],
        reference='https://wiki.earthdata.nasa.gov/display/ESO/Zarr+Format',
        examples=[
            dict(
                filename='WD1.1_17-03_WT_MP.ome.zarr.zip',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/ebc026c279944e8d2829f3cfd12715cce73bd49f2d081688fd12bd758b26a2728a3f34f2c9c0c1b37f8bf822b5283908e84a41cb9b761000d5c8b43854572f32/download',
                hash='f7dfb6683107d1cb21a360e31752b02641a16e0d32a87698669838418f108831',
            ),
            dict(
                filename='normmedia_8well_col2_livecellgfp.db',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/aa2c27d981ce01e75c642a68bee49752822eafdd68ca4eab0dffd0e04844499f7d3db18c21c59514b0b079e80a62cfc39c483d76c2ea962c45a9697de9e6fd08/download',
                hash='7d6cfb6967f79eb5201eebbe93418e26445676d9ea95a3bf49ff4ffbf0993e39',
            ),
        ],
    ),
    dict(
        name='ND2',
        extensions=['nd2'],
        long_name='Nikon NIS Elements',
        reference='https://docs.openmicroscopy.org/bio-formats/5.9.2/formats/nikon-nis-elements-nd2.html',
        examples=[
            dict(
                filename='sample_image.nd2',
                # originally from 'https://downloads.openmicroscopy.org/images/ND2/aryeh/MeOh_high_fluo_003.nd2',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/4e76e490c915b10f646cb516f85a4d36d52aa7eff94715b90222644180e26fef6768493887c05adf182cf0351ba0bce659204041c4698a0f6b08423586788f4d/download',
                hash='8e23bb594cd18314f9c18e70d736088ae46f8bc696ab7dc047784be416d7a706',
            ),
        ],
    ),
    dict(
        name='CZI',
        extensions=['czi'],
        long_name='Carl Zeiss Image',
        reference='https://www.zeiss.com/microscopy/en/products/software/zeiss-zen/czi-image-file-format.html',
        examples=[
            dict(
                filename='Plate1-Blue-A-02-Scene-1-P2-E1-01.czi',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/a707e0a65bbb743adb90ea17dd4e2d1ad1fbf7a105a29e8b67bd90b41525786136ed20ecc4876ff68abdceba8eb5f5bbedb9a364f5b260fa357d37987082a355/download',
                hash='494936fa5a8c2e53b73672980986e2c44f3779e9b709ebfd406ffda723336376',
            ),
        ],
    ),
    dict(
        name='DICOM',
        extensions=['dcm', 'dic', 'dicom'],
        long_name='Digital Imaging and Communications in Medicine',
        reference='https://www.dicomstandard.org/about',
        examples=[
            dict(
                filename='US-MONO2-8-8x-execho.dcm',
                # originally from 'https://downloads.openmicroscopy.org/images/DICOM/samples/US-MONO2-8-8x-execho.dcm',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/5332044f887d82c7f3693c6ca180f07accf5f00c2b7b1a3a29ef9ae737d5f1975478b5e2d5846c391987b8051416068f57a7062e848323c700412236b35679db/download',
                hash='7d3f54806d0315c6cfc8b7371649a242b5ef8f31e0d20221971dd8087f2ff1ea',
            ),
        ],
    ),
    dict(
        name='LIF',
        extensions=['lif', 'liff'],
        long_name='Leica Image Format',
        reference='https://svi.nl/LeicaLif',
        examples=[
            dict(
                filename='20191025 Test FRET 585. 423, 426.lif',
                # originally from 'https://downloads.openmicroscopy.org/images/Leica-LIF/imagesc-30856/20191025%20Test%20FRET%20585.%20423,%20426.lif',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/d25de002d8a81dfcaf6b062b9f429ca85bb81423bc09d3aa33d9d51e9392cc4ace2b8521475e373ceecaf958effd0fade163e7173c467aab66c957da14482ed7/download',
                hash='8d4ee62868b9616b832c2eb28e7d62ec050fb032e0bc11ea0a392f5c84390c71',
            ),
        ],
    ),
    dict(
        name='PNG',
        extensions=['png'],
        long_name='Portable Network Graphics',
        reference='http://www.libpng.org/pub/png/spec/1.2/PNG-Structure.html',
        examples=[
            dict(
                filename='Animated_PNG_example_bouncing_beach_ball.png',
                # originally from 'https://upload.wikimedia.org/wikipedia/commons/1/14/Animated_PNG_example_bouncing_beach_ball.png',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/465ebdc2e81b2576dfc96b34e82db7f968e6d4f32f0fa80ef4bb0e44ed216230e6be1a2e4b11ae301a2905cc582dd24cbd2c360d9567ff7b1dac2c871f6d1e37/download',
                hash='3b28e2462f1b31d0d15d795e6e58baf397899c3f864be7034bf47939b5bbbc3b',
            ),
        ],
    ),
    dict(
        name='JPEG',
        extensions=['jpeg', 'jpe', 'jpg'],
        long_name='Joint Photographic Experts Group',
        reference='https://jpeg.org/jpeg/',
        examples=[
            dict(
                filename='albania.jpg',
                url='https://github.com/OSGeo/gdal/blob/master/autotest/gdrivers/data/jpeg/albania.jpg',
            ),
            dict(
                filename='clouds.jpeg',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/19796a50482aa834dca684129384c4bee87c43fb1636f0358211119b9274e05797db78cfa89192fc3395ad7cbb2d66e78e15ed8b8c9fed6361c0fc300d2fde93/download',
                hash='fb195bb9dae13aa85d9f46f86ab9441a3b436dabbf57c68149453cba691d4391',
            ),
        ],
    ),
    dict(
        name='JPEG 2000',
        extensions=['j2c', 'j2k', 'jp2', 'jpf', 'jpx'],
        long_name='Joint Photographic Experts Group 2000',
        reference='https://jpeg.org/jpeg2000/index.html',
        examples=[
            dict(
                filename='erdas_foo.jp2',
                url='https://github.com/OSGeo/gdal/raw/master/autotest/gdrivers/data/jpeg2000/erdas_foo.jp2',
                hash='d08653919c41a49cd31f9116278fe6a6d8c189dc6379a280810f65df11bde006',
            ),
        ],
    ),
    dict(
        name='GIF',
        extensions=['gif'],
        long_name='Graphics Interchange Format',
        reference='https://www.adobe.com/creativecloud/file-types/image/raster/gif-file.html',
        examples=[
            dict(
                filename='SampleGIFImage_40kbmb.gif',
                # originally from 'https://sample-videos.com/gif/3.gif',
                url='https://data.kitware.com/api/v1/file/hashsum/sha512/26d9a26b25a37f405b5c165b9ae338c873d27482e83881222df2af99e620b5f860a74ba92c0ca6caab2a45582ec5d82ba4c9a9c73870306c1eaa7d5fe69eafff/download',
                hash='0ff064ba36e4f493f6a1b3d9d29c8eee1b719e39fc6768c5a6129534869c380b',
            ),
        ],
    ),
    dict(
        name='Bitmap',
        extensions=['bmp'],
        reference='https://www.ece.ualberta.ca/~elliott/ee552/studentAppNotes/2003_w/misc/bmp_file_format/bmp_file_format.htm',
        examples=[
            dict(
                filename='1bit.bmp',
                url='https://github.com/OSGeo/gdal/raw/master/autotest/gcore/data/1bit.bmp',
                hash='b0c201bee1e5a36ee698ab098aa3480e20772869d8f5c788280e532fa3620667',
            ),
        ],
    ),
]


class ExamplesPooch(pooch.Pooch):
    def get_url(self, fname):
        self._assert_file_in_registry(fname)
        for format_info in format_examples:
            for example in format_info.get('examples', []):
                if example.get('filename') == fname:
                    return example.get('url')


def fetch_all():
    registry = {}
    for format_info in format_examples:
        for example in format_info.get('examples', []):
            filename = example.get('filename')
            hash_value = example.get('hash')
            if filename and hash_value:
                registry[filename] = hash_value
    datastore = ExamplesPooch(
        path=EXAMPLES_FOLDER,
        base_url='',
        registry=registry,
        retry_if_failed=10,
    )
    for key in registry:
        datastore.fetch(key)
