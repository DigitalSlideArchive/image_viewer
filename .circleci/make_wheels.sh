#!/bin/bash

set -e

ROOTPATH=`pwd`

pip install --user -U setuptools_scm wheel
export SETUPTOOLS_SCM_PRETEND_VERSION=`python -m setuptools_scm | sed "s/.* //"`
if [ ${CIRCLE_BRANCH-:} = "master" ]; then export SETUPTOOLS_SCM_PRETEND_VERSION=`echo $SETUPTOOLS_SCM_PRETEND_VERSION | sed "s/\+.*$//"`; fi

mkdir ~/wheels

# If we need binary wheels, we would need to step through the various versions
# of python and also run auditwheel on each output
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/girder"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/girder_annotation"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/utilities/converter"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/utilities/tasks"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/bioformats"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/deepzoom"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/dicom"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/dummy"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/gdal"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/mapnik"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/multi"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/nd2"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/ometiff"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/openjpeg"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/openslide"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/pil"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/rasterio"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/test"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/tiff"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/tifffile"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/vips"
pip wheel . --no-deps -w ~/wheels && rm -rf build
cd "$ROOTPATH/sources/zarr"
pip wheel . --no-deps -w ~/wheels && rm -rf build
