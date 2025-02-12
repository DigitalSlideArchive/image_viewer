#!/bin/bash

set -e

ROOTPATH=`pwd`

export SETUPTOOLS_SCM_PRETEND_VERSION=`python -m setuptools_scm | sed "s/.* //"`
if [ ${CIRCLE_BRANCH-:} = "master" ]; then export SETUPTOOLS_SCM_PRETEND_VERSION=`echo $SETUPTOOLS_SCM_PRETEND_VERSION | sed "s/\+.*$//"`; fi

mkdir ~/wheels

python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/girder"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
# Build the client plugin code
pushd "$ROOTPATH/girder/girder_large_image/web_client/"
npm ci
npm run build
popd
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/girder_annotation"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
# Build the client plugin code
pushd "$ROOTPATH/girder_annotation/girder_large_image_annotation/web_client/"
npm ci
npm run build
popd
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/utilities/converter"
# cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/utilities/tasks"
# cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/bioformats"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/deepzoom"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/dicom"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
# TODO build DICOMweb plugin client code when converted
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/dummy"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/gdal"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/mapnik"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/multi"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/nd2"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/ometiff"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/openjpeg"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/openslide"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/pil"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/rasterio"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/test"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/tiff"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/tifffile"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/vips"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels
cd "$ROOTPATH/sources/zarr"
cp "$ROOTPATH/README.rst" .
cp "$ROOTPATH/LICENSE" .
python setup.py sdist
pip wheel . --no-deps -w ~/wheels

if [[ ${1:-check} != "skip" ]]; then
  twine ${1:-check} $( [[ "${1:-check}" == "upload" ]] && printf %s '--verbose' ) ~/wheels/*
fi
