# Copyright (c) 2018-2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#
__all__ = ["WidgetInfoManipulator"]

from omni.ui import color as cl
from omni.ui import scene as sc
import omni.ui as ui
from ..style import viewport_widget_style


class _ViewportLegacyDisableSelection:
    """Disables selection in the Viewport Legacy"""

    def __init__(self):
        self._focused_windows = None
        focused_windows = []
        try:
            # For some reason is_focused may return False, when a Window is definitely in fact is the focused window!
            # And there's no good solution to this when mutliple Viewport-1 instances are open; so we just have to
            # operate on all Viewports for a given usd_context.
            import omni.kit.viewport_legacy as vp

            vpi = vp.acquire_viewport_interface()
            for instance in vpi.get_instance_list():
                window = vpi.get_viewport_window(instance)
                if not window:
                    continue
                focused_windows.append(window)
            if focused_windows:
                self._focused_windows = focused_windows
                for window in self._focused_windows:
                    # Disable the selection_rect, but enable_picking for snapping
                    window.disable_selection_rect(True)
        except Exception:
            pass


class _DragPrioritize(sc.GestureManager):
    """Refuses preventing _DragGesture."""

    def can_be_prevented(self, gesture):
        # Never prevent in the middle of drag
        return gesture.state != sc.GestureState.CHANGED

    def should_prevent(self, gesture, preventer):
        if preventer.state == sc.GestureState.BEGAN or preventer.state == sc.GestureState.CHANGED:
            return True


class _DragGesture(sc.DragGesture):
    """"Gesture to disable rectangle selection in the viewport legacy"""

    def __init__(self):
        super().__init__(manager=_DragPrioritize())

    def on_began(self):
        # When the user drags the slider, we don't want to see the selection
        # rect. In Viewport Next, it works well automatically because the
        # selection rect is a manipulator with its gesture, and we add the
        # slider manipulator to the same SceneView.
        # In Viewport Legacy, the selection rect is not a manipulator. Thus it's
        # not disabled automatically, and we need to disable it with the code.
        self.__disable_selection = _ViewportLegacyDisableSelection()

    def on_ended(self):
        # This re-enables the selection in the Viewport Legacy
        self.__disable_selection = None


class WidgetInfoManipulator(sc.Manipulator):
    def __init__(self, all_variants, enable_variant, looks, parent_prim, check_visibility, **kwargs):
        super().__init__(**kwargs)

        self.destroy()

        self.all_variants = all_variants
        self.enable_variant = enable_variant
        self.looks = looks
        self.parent_prim = parent_prim
        self.check_visibility = check_visibility
        self._radius = 2
        self._distance_to_top = 5
        self._thickness = 2
        self._radius_hovered = 20
        self.prev_button = None
        self.next_button = None

    def destroy(self):
        self._root = None
        self._slider_subscription = None
        self._slider_model = None
        self._name_label = None
        self.prev_button = None
        self.next_button = None
        self.all_variants = None
        self.enable_variant = None
        self.looks = None
        self.parent_prim = None

    def _on_build_widgets(self):
        with ui.ZStack(height=70, style=viewport_widget_style):
            ui.Rectangle(
                style={
                    "background_color": cl(0.2),
                    "border_color": cl(0.7),
                    "border_width": 2,
                    "border_radius": 4,
                }
            )
            with ui.VStack():
                ui.Spacer(height=4)
                with ui.HStack():
                    ui.Spacer(width=10)
                    self.prev_button = ui.Button("Prev", width=100)
                    self._name_label = ui.Label(
                        "",
                        elided_text=True,
                        name="name_label",
                        height=0,
                        alignment=ui.Alignment.CENTER_BOTTOM
                    )
                    self.next_button = ui.Button("Next", width=100)
                    ui.Spacer(width=10)
                # setup some model, just for simple demonstration here
                self._slider_model = ui.SimpleIntModel()

                ui.Spacer(height=5)
                with ui.HStack(style={"font_size": 26}):
                    ui.Spacer(width=10)
                    ui.IntSlider(self._slider_model, min=0, max=len(self.all_variants))

                    ui.Spacer(width=10)
                ui.Spacer(height=8)
                ui.Spacer()

        self.on_model_updated(None)

        # Additional gesture that prevents Viewport Legacy selection
        self._widget.gestures += [_DragGesture()]

    def on_build(self):
        """Called when the model is chenged and rebuilds the whole slider"""
        self._root = sc.Transform(visible=False)
        with self._root:
            with sc.Transform(scale_to=sc.Space.SCREEN):
                with sc.Transform(transform=sc.Matrix44.get_translation_matrix(0, 100, 0)):
                    # Label
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        self._widget = sc.Widget(500, 130, update_policy=sc.Widget.UpdatePolicy.ON_MOUSE_HOVERED)
                        self._widget.frame.set_build_fn(self._on_build_widgets)

    # Update the slider
    def update_variant(self, value):
        if not self._root or not self._root.visible or not self.looks or not self.parent_prim:
            return
        if value == 0:
            self.enable_variant(None, self.looks, self.parent_prim, ignore_select=True)
        else:
            selected_variant = self.all_variants[value - 1]
            if not selected_variant:
                return
            prim_name = selected_variant.GetName()
            self.enable_variant(prim_name, self.looks, self.parent_prim, ignore_select=True)

    def on_model_updated(self, _):
        if not self._root:
            return
        # if we don't have selection then show nothing
        if not self.model or not self.model.get_item("name") or not self.check_visibility():
            self._root.visible = False
            return

        # Update the shapes
        position = self.model.get_as_floats(self.model.get_item("position"))
        self._root.transform = sc.Matrix44.get_translation_matrix(*position)
        self._root.visible = True

        active_index = 0
        for variant_prim in self.all_variants:
            is_active_attr = variant_prim.GetAttribute("MMEisActive")
            if is_active_attr:
                # Checking if the attribute is_active_attr is active.
                is_active = is_active_attr.Get()
                if is_active:
                    active_index = self.all_variants.index(variant_prim) + 1
                    break

        if self._slider_model:
            if self._slider_subscription:
                self._slider_subscription.unsubscribe()
            self._slider_subscription = None
            self._slider_model.as_int = active_index
            self._slider_subscription = self._slider_model.subscribe_value_changed_fn(
                lambda m: self.update_variant(m.as_int)
            )

        if self.prev_button and self.next_button:
            self.prev_button.enabled = active_index > 0
            self.next_button.enabled = active_index < len(self.all_variants)
            self.prev_button.set_clicked_fn(lambda: self.update_variant(active_index - 1))
            self.next_button.set_clicked_fn(lambda: self.update_variant(active_index + 1))

        # Update the shape name
        if self._name_label:
            if active_index == 0:
                self._name_label.text = "Orginal"
            else:
                self._name_label.text = f"{self.all_variants[active_index - 1].GetName()}"
