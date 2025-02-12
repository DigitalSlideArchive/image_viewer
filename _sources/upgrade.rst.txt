Upgrading from Previous Versions
================================

Migration from Girder 2 to Girder 3
-----------------------------------

If you are migrating a Girder 2 instance with Large Image to Girder 3, you need to do a one time database update.  Specifically, one of the tile sources' internal name changed.

Access the Girder Mongo database.  The command for this in a simple installation is::

    mongo girder

Update the tile source name by issuing the Mongo command::

    db.item.updateMany({"largeImage.sourceName": "svs"}, {$set: {"largeImage.sourceName": "openslide"}})

.. _Girder: https://github.com/girder/girder
