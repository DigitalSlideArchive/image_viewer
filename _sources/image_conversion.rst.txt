Image Conversion
================

The ``large_image`` library can read a variety of images with the various tile source modules.  Some image files that cannot be read directly can be converted into a format that can be read by the ``large_image`` library.  Additionally, some images that can be read are very slow to handle because they are stored inefficiently, and converting them will make a equivalent file that is more efficient.

Python Usage
~~~~~~~~~~~~
The ``large_image_converter`` module can be used as a Python package. See :doc:`_build/large_image_converter/modules` for details.

Command Line Usage
~~~~~~~~~~~~~~~~~~
Installing the ``large-image-converter`` module adds a ``large_image_converter`` command to the local environment.  Running ``large_image_converter --help`` displays the various options.

.. include:: ../build/docs-work/large_image_converter.txt
   :literal:
