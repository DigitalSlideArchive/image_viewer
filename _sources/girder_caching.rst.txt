Caching Large Image in Girder
=============================

Tile sources are opened: when large image files uploaded or imported; when large image files are viewed; when thumbnails are generated; when an item page with a large image is viewd; and from some API calls.  All of these result in the source being placed in the cache _except_ import.

Since there are multiple users, the cache size should be large enough that no user has an image that they are actively viewing fall out of cache.

Example of cache use when the ``GET`` ``/item/{id}/tile/zxy/{z}/{x}/{y}?style=<style>&encoding=<encoding>&...`` endpoint is called:

.. mermaid::

  graph TD;
    apicall(["GET /item/{id}/tile/zxy/{z}/{x}/{y}?style=&lt;style&gt;&amp;encoding=&lt;encoding&gt;&amp;..."])
    checktile1{Is tile in\ntile cache?}
    apicall --> checktile1;
    getfile[("Get file-like object\nor url from Girder")]
    checktile1 -- No --> getfile;
    servetile(["Serve tile 🖼️"])
    checktile1 -- Yes --> servetile;
    checksource{"Is file-like object\nin source cache\nwith {style}\nand {encoding}?"}
    getfile --> checksource;
    checkunstyled{"Is unstyled file\nin source cache\nwith {encoding}?"}
    checksource -- No --> checkunstyled;
    openunstyle["Open unstyled file with {encoding}"]
    checkunstyled -- No --> openunstyle;
    putunstyledsource[/"Put unstyled source in cache"/]
    openunstyle --> putunstyledsource;
    alter["Copy unstyled source\nand alter for {style}"]
    putunstyledsource --> alter;
    checkunstyled -- Yes --> alter;
    putsource[/"Put styled source in cache"/]
    alter --> putsource;
    checktile2{"Is unstyled tile\n{x}, {y}, {z},\n{frame}, {encoding}\nin tile cache?"}
    putsource --> checktile2;
    checksource -- Yes --> checktile2;
    checktile3{"Does tile exist\nin the file?"}
    checktile2 -- No --> checktile3;
    maketile[["Synthesize tile\nfrom higher\nresolution tiles"]]
    checktile3 -- No --> maketile;
    readfile[("Read tile from file")]
    checktile3 -- Yes --> readfile;
    puttile1[/"Put unstyled\ntile in cache"/]
    maketile --> puttile1;
    readfile --> puttile1;
    gettile[\"Read unstyled tile\nfrom cache"\]
    checktile2 -- Yes --> gettile;
    needstyle{"Is {style}\nrequired?"}
    puttile1 --> needstyle;
    gettile --> needstyle;
    checkencoding{"Is tile\nin {encoding}?"}
    needstyle -- No --> checkencoding;
    isnumpy{"Is unstyled\ntile a\nnumpy array?"}
    needstyle -- Yes --> isnumpy;
    makenumpy["Convert tile to numpy"]
    isnumpy -- No --> makenumpy;
    makestyle["Generate styled tile in numpy format\n(Note that this could fetch other tiles)"]
    isnumpy -- Yes --> makestyle;
    makenumpy --> makestyle;
    makestyle --> checkencoding;
    encode["Encode tile to {encoding}"]
    checkencoding -- No --> encode;
    puttile2[/"Put encoded tile\nin cache"/]
    encode --> puttile2;
    checkencoding -- Yes --> puttile2;
    puttile2 --> servetile;
