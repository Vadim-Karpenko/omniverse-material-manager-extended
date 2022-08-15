# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["WidgetInfoModel"]

from omni.ui import scene as sc
from pxr import UsdGeom
from pxr import Usd
from pxr import UsdShade
from pxr import Tf
from pxr import UsdLux

import omni.usd
import omni.kit.commands


class WidgetInfoModel(sc.AbstractManipulatorModel):
    """
    User part. The model tracks the position and info of the selected object.
    """

    class PositionItem(sc.AbstractManipulatorItem):
        """
        The Model Item represents the position. It doesn't contain anything
        because because we take the position directly from USD when requesting.
        """

        def __init__(self):
            super().__init__()
            self.value = [0, 0, 0]

    class ValueItem(sc.AbstractManipulatorItem):
        """The Model Item contains a single float value about some attibute"""

        def __init__(self, value=0):
            super().__init__()
            self.value = [value]

    def __init__(self, parent_prim):
        super().__init__()

        self.material_name = ""
        self.position = WidgetInfoModel.PositionItem()

        # The distance from the bounding box to the position the model returns
        self._offset = 0
        # Current selection
        self._prim = parent_prim
        self._current_path = ""
        self._stage_listener = None

        # Save the UsdContext name (we currently only work with single Context)
        self._usd_context_name = ''
        usd_context = self._get_context()

        # Track selection
        self._events = usd_context.get_stage_event_stream()
        self._stage_event_sub = self._events.create_subscription_to_pop(
            self._on_stage_event, name="Object Info Selection Update"
        )

    def _get_context(self) -> Usd.Stage:
        # Get the UsdContext we are attached to
        return omni.usd.get_context(self._usd_context_name)

    def _notice_changed(self, notice, stage):
        """Called by Tf.Notice"""
        for p in notice.GetChangedInfoOnlyPaths():
            if self._current_path in str(p.GetPrimPath()):
                self._item_changed(self.position)

    def get_item(self, identifier):
        if identifier == "position":
            return self.position
        if identifier == "name":
            return self._current_path
        if identifier == "material":
            return self.material_name

    def get_as_floats(self, item):
        if item == self.position:
            # Requesting position
            return self._get_position()

        if item:
            # Get the value directly from the item
            return item.value
        return []

    def set_floats(self, item, value):
        if not self._current_path:
            return

        if not value or not item or item.value == value:
            return

        # Set directly to the item
        item.value = value
        # This makes the manipulator updated
        self._item_changed(item)

    def _on_stage_event(self, event):
        """Called by stage_event_stream"""
        if event.type == int(omni.usd.StageEventType.SELECTION_CHANGED):
            self._on_kit_selection_changed()

    def _on_kit_selection_changed(self):
        # selection change, reset it for now
        self._current_path = ""
        usd_context = self._get_context()
        stage = usd_context.get_stage()
        if not stage:
            return

        prim_paths = usd_context.get_selection().get_selected_prim_paths()
        if not prim_paths or len(prim_paths) > 1 or len(prim_paths) == 0 or str(self._prim.GetPath()) not in prim_paths[0]:
            self._item_changed(self.position)
            # Revoke the Tf.Notice listener, we don't need to update anything
            if self._stage_listener:
                self._stage_listener.Revoke()
                self._stage_listener = None
            return

        prim = self._prim

        if prim.IsA(UsdLux.Light):
            self.material_name = "I am a Light"
        elif prim.IsA(UsdGeom.Imageable):
            material, relationship = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            if material:
                self.material_name = str(material.GetPath())
            else:
                self.material_name = "N/A"
        else:
            self._prim = None
            return

        self._current_path = str(self._prim.GetPath())

        # Add a Tf.Notice listener to update the position
        if not self._stage_listener:
            self._stage_listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._notice_changed, stage)

        (old_scale, old_rotation_euler, old_rotation_order, old_translation) = omni.usd.get_local_transform_SRT(prim)

        # Position is changed
        self._item_changed(self.position)

    def find_child_mesh_with_position(self, prim):
        """
        A recursive method to find a child with a valid position.
        """
        if prim.IsA(UsdGeom.Mesh):
            self._current_path = str(prim.GetPath())
            prim_position = self._get_position(non_recursive=True)
            if prim_position[0] == 0.0 or prim_position[1] == 0.0 or prim_position[2] == 0.0:
                pass
            else:
                return prim
        for child in prim.GetChildren():
            result = self.find_child_mesh_with_position(child)
            if result:
                return result
        return None

    def _get_position(self, non_recursive=False):
        """Returns position of currently selected object"""
        stage = self._get_context().get_stage()
        if not stage or not self._current_path:
            return [0, 0, 0]

        # Get position directly from USD
        if non_recursive:
            prim = stage.GetPrimAtPath(self._current_path)
        else:
            prim = self.find_child_mesh_with_position(stage.GetPrimAtPath(self._current_path))
        box_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), includedPurposes=[UsdGeom.Tokens.default_])
        bound = box_cache.ComputeWorldBound(prim)
        range = bound.ComputeAlignedBox()
        bboxMin = range.GetMin()
        bboxMax = range.GetMax()

        position = [(bboxMin[0] + bboxMax[0]) * 0.5, bboxMax[1] + self._offset, (bboxMin[2] + bboxMax[2]) * 0.5]
        return position
