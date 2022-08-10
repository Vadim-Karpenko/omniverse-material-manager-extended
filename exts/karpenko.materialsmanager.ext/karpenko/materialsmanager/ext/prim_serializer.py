# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["update_property_paths", "get_prim_as_text", "text_to_stage"]

from omni.kit.commands import execute
from pxr import Sdf
from pxr import Tf
from pxr import Usd
from typing import List
from typing import Optional


def _to_layer(text: str) -> Optional[Sdf.Layer]:
    """Create an sdf layer from the given text"""

    if not text.startswith("#usda 1.0\n"):
        text = "#usda 1.0\n" + text

    anonymous_layer = Sdf.Layer.CreateAnonymous("clipboard.usda")
    try:
        if not anonymous_layer.ImportFromString(text):
            return
    except Tf.ErrorException:
        return

    return anonymous_layer


def update_property_paths(prim_spec, old_path, new_path):
    if not prim_spec:
        return

    for rel in prim_spec.relationships:
        rel.targetPathList.explicitItems = [path.ReplacePrefix(old_path, new_path)
                                            for path in rel.targetPathList.explicitItems]

    for attr in prim_spec.attributes:
        attr.connectionPathList.explicitItems = [path.ReplacePrefix(old_path, new_path)
                                                 for path in attr.connectionPathList.explicitItems]

    for child in prim_spec.nameChildren:
        update_property_paths(child, old_path, new_path)


def get_prim_as_text(stage: Usd.Stage, prim_paths: List[Sdf.Path]) -> Optional[str]:
    """Generate a text from the stage and prim path"""

    if not prim_paths:
        return

    # TODO: It can be slow in large scenes. Ideally we need to flatten specific prims.
    flatten_layer = stage.Flatten()
    anonymous_layer = Sdf.Layer.CreateAnonymous(prim_paths[0].name + ".usda")
    paths_map = {}

    for i in range(0, len(prim_paths)):
        item_name = str.format("Item_{:02d}", i)
        Sdf.PrimSpec(anonymous_layer, item_name, Sdf.SpecifierDef)
        prim_path = prim_paths[i]
        anonymous_path = Sdf.Path.absoluteRootPath.AppendChild(item_name).AppendChild(prim_path.name)

        # Copy
        Sdf.CopySpec(flatten_layer, prim_path, anonymous_layer, anonymous_path)

        paths_map[prim_path] = anonymous_path

    for prim in anonymous_layer.rootPrims:
        for source_path, target_path in paths_map.items():
            update_property_paths(prim, source_path, target_path)

    return anonymous_layer.ExportToString()


def text_to_stage(stage: Usd.Stage, text: str, root: Sdf.Path = Sdf.Path.absoluteRootPath) -> bool:
    """
    Convert the given text to the prim and place it to the stage under the
    given root.
    """

    source_layer = _to_layer(text)
    if not source_layer:
        return False

    execute("ImportLayer", layer=source_layer, stage=stage, root=root)
    return True
