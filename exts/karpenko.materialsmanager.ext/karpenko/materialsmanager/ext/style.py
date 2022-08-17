# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["materialsmanager_window_style"]

import omni.kit.app
import omni.ui as ui
import pathlib
from omni.ui import color as cl

EXTENSION_FOLDER_PATH = pathlib.Path(
    omni.kit.app.get_app().get_extension_manager().get_extension_path_by_module(__name__)
)

# The main style dict
materialsmanager_window_style = {
    "Image::material_preview": {
        "image_url": f"{EXTENSION_FOLDER_PATH}/data/icons/material@3x.png",
    },
    "Label::main_label": {
        "alignment": ui.Alignment.LEFT_CENTER,
        "color": cl("#a1a1a1"),
        "font_size": 24,
    },
    "Label::main_hint": {
        "alignment": ui.Alignment.CENTER,
        "margin_height": 1,
        "margin_width": 10,
        "font_size": 16,
    },
    "Label::main_hint_small": {
        "alignment": ui.Alignment.CENTER,
        "color": cl("#a1a1a1"),
    },
    "Label::material_name": {
        "alignment": ui.Alignment.LEFT_CENTER,
        "font_size": 14,
    },
    "Label::secondary_label": {
        "alignment": ui.Alignment.LEFT_CENTER,
        "color": cl("#a1a1a1"),
        "font_size": 18,
    },
    "Label::material_counter": {
        "alignment": ui.Alignment.CENTER,
        "margin_height": 1,
        "margin_width": 10,
        "font_size": 14,
    },
}

# The style dict for the viewport widget ui
viewport_widget_style = {
    "Button.Label": {
        "font_size": 30,
    },
    "Button.Label:disabled": {
        "color": cl("#a1a1a1")
    },
    "Button:disabled": {
        "background_color": cl("#4d4d4d"),
    },
    "Button": {
        "alignment": ui.Alignment.BOTTOM,
        "background_color": cl("#666666"),
    },
    "Label::name_label": {
        "alignment": ui.Alignment.CENTER_BOTTOM,
        "font_size": 34,
    }
}
