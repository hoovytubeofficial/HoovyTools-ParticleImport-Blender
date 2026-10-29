"""Logic modules. Kept free of bpy wherever possible so they can be tested
outside Blender:

    pcf.py           .pcf (DMX) parsing + the parent/child system tree   [no bpy]
    vtf.py           .vtf decode (DXT1/3/5 + 8-bit) and the sheet table  [no bpy]
    datamodel.py     vendored DMX reader (MIT, Tom Edwards)              [no bpy]
    gn_to_python.py  Geometry Nodes -> runnable rebuild script            [bpy]
"""
