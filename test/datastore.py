import os

import pooch

registry = {
    # netcdf file for testing mapnik source
    # Source: 04091217_ruc.nc
    '04091217_ruc.nc': 'sha512:3380c8de64afc46a5cfe764921e0fd5582380b1065754a6e6c4fa506625ee26edb1637aeda59c1d2a2dc245364b191563d8572488c32dcafe9e706e208fd9939',  # noqa
    # OME Tiff with non-tiled layout
    # Source: DDX58_AXL_EGFR_well2_XY01.ome.tif
    'DDX58_AXL_EGFR_well2_XY01.ome.tif': 'sha512:d9f7b733fd758f13540a7416d1e22469e8e28a434a1acb7a50a5da0398eaa93cb5b00cc1d0bd02216da8ab9b648e82cfcb4c4bc084bd08216f6cb3c5f485f1b6',  # noqa
    # Power of three tiles
    # Source: G10-3_pelvis_crop-powers-of-3.tif
    'G10-3_pelvis_crop-powers-of-3.tif': 'sha512:56ca89f25b0857960518c417393633029d5592376c8d94bc867662b7bff684fb2a4fe40f7dd3eeeb9abe9c8c3105b9bf89868a79a883b32e1207acd2ff59af21',  # noqa
    # Zeiss file
    # Source: HENormalN801.czi
    'HENormalN801.czi': 'sha512:ca0704401d7e1b75b5b3830bc4316e4f453a1428538d54415671d3048786c7d88d3b0774a67a5f8071c4e91213657ad6ee3f866f4a631cd3f2b477bdae4b17a7',  # noqa
    # Nikon file
    # Source: ITGA3Hi_export_crop2.nd2
    'ITGA3Hi_export_crop2.nd2': 'sha512:9c1f412468025e53c632c2d45a77ac73d6c100750304ad0db6311de22348a4052f97828fde78ca3ccd61ace17bd007c2d8a1bb1406ec19748029a308f60a1725',  # noqa
    # JPEG2000 File with associated images
    # Source: JK-kidney_B-gal_H3_4C_1-500sec.jp2
    'JK-kidney_B-gal_H3_4C_1-500sec.jp2': 'sha512:38912884b07a626d61a61dfede497abc31e407772bf300a553de737cb2289cb55aa94b059d4a304269900a5a267170912fa95d3b8260571bdffc14b311d5ec61',  # noqa
    # Multiple tiles; some not part of the main sequence
    # Source: JK-kidney_H3_4C_1-500sec.tif
    'JK-kidney_H3_4C_1-500sec.tif': 'sha512:9d94deb45acd1af86dedd26e261e788bad6364e0243712cd9ac37ad6862b3ec7db1554bf9392b88dc2748a1d2147baaf1a8b00d5ab39c04aa1dfbc4218362550',  # noqa
    # RGB JPEG compression
    # Source: TCGA-AA-A02O-11A-01-BS1.8b76f05c-4a8b-44ba-b581-6b8b4f437367.svs
    'TCGA-AA-A02O-11A-01-BS1.8b76f05c-4a8b-44ba-b581-6b8b4f437367.svs': 'sha512:1b75a4ec911017aef5c885760a3c6575dacf5f8efb59fb0e011108dce85b1f4e97b8d358f3363c1f5ea6f1c3698f037554aec1620bbdd4cac54e3d5c9c1da1fd',  # noqa
    # Tiff with floating point pixels
    # Source: d042-353.crop.small.float32.tif
    'd042-353.crop.small.float32.tif': 'sha512:ae05dbe6f3330c912893b203b55db27b0fdf3222a0e7f626d372c09668334494d07dc1d35533670cfac51b588d2292eeee7431317741fdb4cbb281c28a289115',  # noqa
    # JPEG with progressive compression and restart markers
    # Source: d042-353.crop.small.jpg
    'd042-353.crop.small.jpg': 'sha512:1353646637c1fae266b87312698aa39eca0311222c3a1399b60efdc13bfe55e2f3db59da005da945dd7e9e816f31ccd18846dd72744faac75215074c3d87414f',  # noqa
    # Tiff with JP2k compression
    # Source: huron.image2_jpeg2k.tif
    'huron.image2_jpeg2k.tif': 'sha512:eaba877079c86f0603b2a636a44d57832cdafe6d43a449121f575f0d43f69b8a17fa619301b066ece1c11050b41d687400b27407c404d827fd2c132d99e669ae',  # noqa
    # Thematic landcover sample
    # Source: landcover_sample_1000.tif
    'landcover_sample_1000.tif': 'sha512:0a1e8c4cf29174b19ddece9a2deb7230a31e819ee78b5ec264feda6356abf60d63763106f1ddad9dd04106d383fd0867bf2db55be0552c30f38ffb530bf72dec',  # noqa
    # Geospatial image defined by GCP
    # Source: extracted from a public landsat image
    'region_gcp.tiff': 'sha512:b49d753c0a04888882da60917a6578707ad2d6f5a8f1de3b21b2ae498ad6140ee8a1779a4690cc24fa7b1cbae46e86c3529d2fbd88f392a344fbe549b4447f23',  # noqa
    # Multiframe OME tif
    # Source: sample.ome.tif
    'sample.ome.tif': 'sha512:a65ad3d67bbc8f56eb3aa7c7d6a43326e50fdef7c0a0c7ace2b477c2dfda2e810c1acc148be2ee2da9a9aa7b0195032938f36da4117a7c3f46302d4fbb1e8173',  # noqa
    # Multiframe OME tif with lower resolutions in subifds
    # Source: sample.subifd.ome.tif
    'sample.subifd.ome.tif': 'sha512:35ec252c94b1ad0b9d5bd42c89c1d15c83065d6734100d6f596237ff36e8d4495bcfed2c9ea24ab0b4a35aef59871da429dbd48faf0232219dc4391215ba59ce',  # noqa
    # Used for testing tile redirects
    # Source: sample_Easy1.jpeg
    'sample_Easy1.jpeg': 'sha512:528a3625f6565450292da605264aefbdb29fd0ca7991f6e86dff85c2e7f3093715e7cc8b5664c2168b513c37c3b43ecd537404a2d3b7f902c2ad0a66b3f5d3c8',  # noqa
    # Small PNG
    # Source: sample_Easy1.png
    'sample_Easy1.png': 'sha512:feaf2b24c4ab3123caf1aa35f51acb1d8b83b34941b28d130f878702fd3be4ae9bf46176209f7511d1213da511d414c2b4b7738ad567b089224de9d6c189e664',  # noqa
    # Small JPEG2000 image
    # Source: sample_image.jp2
    'sample_image.jp2': 'sha512:82f1dc64435ab959532ea845c93c28a1e05ed85999300bccf0e7196c91652d014d2a571c324d83279da4cabcd42cf4ed6d732e304ffa71e8b9f7ae3a1390f4c5',  # noqa
    # Pyramidal tiff file (Phillips format)
    # Source: sample_image.ptif
    'sample_image.ptif': 'sha512:ec0ec688537080e4ec2abb3978c14577df87250a2c0af42beaadc8f00f0baba210997d5d2fe7cfeeceb841885b6adad0c9f607e35eddcc479eb487bd3c1e28ac',  # noqa
    # Aperio file with JPEG2000 compression requiring a newer openjpeg library
    # Source: sample_jp2k_33003_TCGA-CV-7242-11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs
    'sample_jp2k_33003_TCGA-CV-7242-11A-01-TS1.1838afb1-9eee-4a70-9ae3-50e3ab45e242.svs': 'sha512:9a4312bc720e81ef4496cc33c71c122b82226f72bc4944b0192cc83a93b9ed7f69612d3f4369279c2ec41183e3f684cca7e068208b7d0a42bdca26cbdc3b9aac',  # noqa
    # Leica file
    # Source: sample_leica.scn
    'sample_leica.scn': 'sha512:954953c1562d9b91445287cc2066d252e821e807d5b6f60a575892f6434ecf3db7fa40371c0d07cedc0c3e8a8eb8666f40b7e027e04051afc609f55ce596f588',  # noqa
    # Typical SVS file with 240x240 tiles
    # Source: sample_svs_image.TCGA-DU-6399-01A-01-TS1.e8eb65de-d63e-42db-af6f-14fefbbdf7bd.svs
    'sample_svs_image.TCGA-DU-6399-01A-01-TS1.e8eb65de-d63e-42db-af6f-14fefbbdf7bd.svs': 'sha512:5580c2b5a5360d279d102f1eb5b0e646a4943e362ec1d47f2db01f8e9e52b302e51692171198d0d35c7fa9ec9f5b8e445ef91fa7ea0bdb05ead31ab49e0118f9',  # noqa
    # One layer tiff with missing tiles
    # Source: one_layer_missing_tiles.tiff
    'one_layer_missing_tiles.tiff': 'sha512:53d52abbb82d312b114407d2974fa0a4116c3b50875c5b360798b5d529cbb67596b1dff7d8feceb319d0b4377d12d023b64e374ea3df37f795c5a940afaa4cd5',  # noqa
    # Geospatial file without a projection
    # Source: generated from geojs oahu sample and a script
    'oahu-dense.tiff': 'sha512:414b7807f14991d6f8229134ad6ccbc2cc2d4b05423ccebfd3ede7d7323dfcf04ef1a7b2c2b4c45c31f8a36bccd390782af3e7d3e99f01f1b95650c5da1f122b',  # noqa
    # Multi source file using different sources
    # Source: manually generated.
    'multi_source.yml': 'sha512:81d7768b06eca6903082daa5b91706beaac8557ba4cede7f826524303df69a33478d6bb205c56af7ee2b45cd7d75897cc4b5704f743ddbf71bb3537ed3b9e8a8',  # noqa
    # Geospatial tiff - not cloud optimized
    'TC_NG_SFBay_US_Geo.tif': 'sha512:da2e66528f77a5e10af5de9e496074b77277c3da81dafc69790189510e5a7e18dba9e966329d36c979f1b547f0d36a82fbc4cfccc65ae9ef9e2747b5a9ee77b0',  # noqa
    # Geospatial tiff - cloud optimized
    'TC_NG_SFBay_US_Geo_COG.tif': 'sha512:5e56cdb8fb1a02615698a153862c10d5292b1ad42836a6e8bce5627e93a387dc0d3c9b6cfbd539796500bc2d3e23eafd07550f8c214e9348880bbbc6b3b0ea0c',  # noqa
    # Tiff with extra overview that was originally misinterpreted as a layer
    # Source: generated from a tifftools dump with the image descriptions and
    #  topmost layer removed.
    'extraoverview.tiff': 'sha512:22793cc6285ad11fbb47927c3d546d35e531a73852b79a9248ba489b421792e3a55da61e00079372bcf72a7e11b12e1ee69d553620edf46ff8d86ad2a9da9fc5',  # noqa
    # DICOM WSI files generated from TCGA-02-0010-01Z-00-DX4...svs and only
    # keeping two levels
    'level-0-frames-0-320.dcm': 'sha512:c3c39e133988f29a99d87107f3b8fbef1c6f530350a9192671f237862731d6f44d18965773a499867d853cbf22aaed9ea1670ce0defda125efe6a8c0cc63c316',  # noqa
    'level-1-frames-0-20.dcm': 'sha512:cc414f0ec2f6ea0d41fa7677e5ce58d72b7541c21dd5c3a0106bf2d1814903daaeba61ae3c3cc3c46ed86210f04c7ed5cff0fc76c7305765f82642ad7ed4caa7',  # noqa
    # Composite XY frames using the multi source
    'multi-source-composite.yaml': 'sha512:61b79d43592d68509ec8a3e10b18689ac896c5753e8c1e5be349ff857ac981f8e980c4ad15bab84a3d67b08ada956d195557c64e2fd116dcdf9dc054f679573d',  # noqa
    # Blank qptiff file with multiple channels
    'synthetic_qptiff.qptiff': 'sha512:652e61c650bcc57beeb2f89b8fa9ac4ba44ce5c0b48c5d3c6fb40ca539b015e36fe831ea5abd95d5650ec342de6a4207a9c22d410f5e2d8bfafbf19e2a6d5d96',  # noqa
    # Blank imageJ file with multiple channels
    'synthetic_imagej.tiff': 'sha512:f4fcf9633b7fc8c819aace248352b3ef89364418d734aa8326096829d64956f11b961c24003bd5ca1f7e46462a8230b64177b37b1517a416d7c7123a0932d5dc',  # noqa
    # Blank untiled tiff with bad tifffile axes information
    'bad_axes_description.tif': 'sha512:cbe82614a83d315a2f22c32b14fd32560fadb3f263bfeffc75f42f88e535e8a11728f691499cb7f5714bbbc55938c472ee4a706d7281bdfefe6fdb965c0a2d6b',  # noqa
    # Converted from the blank qptiff file
    'synthetic_channels.zarr.db': 'sha512:84a1e5e55931ca17e914b97c3e90bba786ce0a53eec61956a0026a65eea759f45193052e70add531b9debd13597433fdc06fc0abfa5ebae628fa64d34e0d750d',  # noqa
    # Converted from a file called normmedia...nd2 and made mostly dull
    'synthetic_multiaxis.zarr.db': 'sha512:2ca118b67ca73bbc6fe9542c5b71ee6cb5f45f5049575a4682290cec4cfb4deef29aee5e19fb5d4005167322668a94191a86f98f1125c94f5eef3e14c6ec6e26',  # noqa
    # The same as above, but as a multi directory zip
    'synthetic_multiaxis.zarr.zip': 'sha512:95da53061bd09deaf4357e745404780d78a0949935f82c10ee75237e775345caace18fad3f05c3452ba36efca6b3ed58d815d041f33197497ab53d2c80b9e2ac',  # noqa
    # Single flat array zarr
    'flat2.zarr.zip': 'sha512:c49ff5fbfa73615da4c2a7c8602723297d604892b848860a068ab200245eec6c4f638f35d0b40cde0233c55faa6dc4e46351a841b481211f36dc5fb43765d818',  # noqa
    # OME tiff where tifffile reports no keyframe
    'test_nokeyframe.ome.tiff': 'sha512:e810420ece0688bf4e1c347ef7e172a303a9cb3f0d56efc3d0068ec40decf05d2588b01a3f5ac9857ccf8f3d088819e532148488f30ad693d6d79c1aa66115d7',  # noqa
    # From TCGA-AA-3697-01Z-00-DX1 (three levels), dual-character DCM/TIFF
    'd4db7ae6-1344-467e-8380-4ce13cc3f59e.dcm': 'sha512:48cb562b94d0daf4060abd9eef150c851d3509d9abbff4bea11d00832955720bf1941073a51e6fb68fb5cc23704dec2659fc0c02360a8ac753dc523dca2c8c36',  # noqa
    '18f6378f-433c-42bf-9373-1ff9c808c118.dcm': 'sha512:36432183380eb7d44417a2210a19d550527abd1181255e19ed5c1d17695d8bb8ca42f5b426a63fa73b84e0e17b770401a377ae0c705d0ed7fdf30d571ef60e2d',  # noqa
    'a131592c-a069-4aa7-8031-398654aa8a3d.dcm': 'sha512:99bd3da4b8e11ce7b4f7ed8a294ed0c37437320667a06c40c383f4b29be85fe8e6094043e0600bee0ba879f2401de4c57285800a4a23da2caf2eb94e5b847ee0',  # noqa
    # Synthetic newer ndpi with binary data and nonblank image labelled as RGB
    'synthetic_ndpi_2024.ndpi': 'sha512:192cdcf551a824277ef70358b8ed6225dca0c5b5d0817fe0d800b72638e0ad9416cd5bc40cb186219da60fd324b676d1b32cc05a276a33b71b485d665a31e42e',  # noqa
    # Synthetic uint16 untiled tiff that can be read with the tiff source
    'synthetic_untiled_16.tiff': 'sha512:f4773fcfa749ba9c2db25319c9e8ad8586dd148de4366dae0393a3703906dace9f11233eafdb24418b598170d6372ef1ca861bf8d7a8212cac21a0eb8636ee77',  # noqa
    # DICOM with int16 data
    # Source: TCIA/CMB-LCA_v07_20240828/CMB-LCA/MSB-01459/
    #   12-22-1959-XR Chest-59125/1002.000000-43033/1-1.dcm
    'tcia_msb_01459_19591222.dcm': 'sha512:9dea871c3816f149227ece40d35aa5cf655f23412cb7aee72f175f0a74435d8b21aaa2030e7e75b0affbc07c03c205028025a4d5022bfa797bff523fa98315e0',  # noqa
    # Synthetic Indica Labs tiff; subifds missing tile/strip data and unmarked
    # float32 pixels rather than uint32
    'synthetic_indica.tiff': 'sha512:fba7eb2fb5fd12ac242d8b0760440f170f48f9e2434a672cbf230bd8a9ff02fad8f9bdf7225edf2de244f412edfc5205e695031a1d43dd99fe31c3aca11909a1',  # noqa
}


class DKCPooch(pooch.Pooch):
    def get_url(self, fname):
        self._assert_file_in_registry(fname)
        algo, hashvalue = self.registry[fname].split(':')
        return self.base_url.format(algo=algo, hashvalue=hashvalue)


datastore = DKCPooch(
    path=pooch.utils.cache_location(
        os.path.join(os.environ.get('TOX_WORK_DIR', pooch.utils.os_cache('pooch')), 'externaldata'),
    ),
    base_url='https://data.kitware.com/api/v1/file/hashsum/{algo}/{hashvalue}/download',
    registry=registry,
    retry_if_failed=10,
)


def fetch_all():
    for key in registry:
        datastore.fetch(key)
