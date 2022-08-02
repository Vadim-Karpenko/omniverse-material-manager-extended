import base64
import json

import carb
import omni.ext
import omni.kit.commands
import omni.ui as ui
import omni.usd
# from omni.kit.property.material.scripts.material_utils import get_binding_from_prims
from omni.kit.stage.copypaste.prim_serializer import (get_prim_as_text,
                                                      text_to_stage)
from pxr import Sdf


# Any class derived from `omni.ext.IExt` in top level module (defined in `python.modules` of `extension.toml`) will be
# instantiated when extension gets enabled and `on_startup(ext_id)` will be called. Later when extension gets disabled
# on_shutdown() is called.
class MaterialManagerExtended(omni.ext.IExt):
    # ext_id is current extension id. It can be used with extension manager to query additional information, like where
    # this extension is located on filesystem.
    def on_startup(self, ext_id):
        print("[karpenko.materialsmanager.ext] MaterialManagerExtended startup")
        self._usd_context = omni.usd.get_context()
        self._selection = self._usd_context.get_selection()
        self.ext_id = ext_id
        self.latest_selected_prim = None
        self.materials_frame_original = None
        self.materials_frame = None
        self.main_frame = None
        self.ignore_change = False
        self.force_render = False
        self.current_ui = "default"
        self.stage = self._usd_context.get_stage()
        self.allowed_commands = [
            "SelectPrimsCommand",
            "SelectPrims",
            "CreatePrimCommand",
            "DeletePrims",
            "TransformPrimCommand",
            "Undo",
            "BindMaterial",
            "BindMaterialCommand",
        ]
        self.collapsed = False
        
        omni.kit.commands.subscribe_on_change(self.on_change)

        manager = omni.kit.app.get_app().get_extension_manager()
        extension_path = manager.get_extension_path(ext_id)
        self.material_icon = f"{extension_path}/data/icons/material@3x.png"
        self._style = {
            "Image::material": {
                "margin": 12,
                "image_url": self.material_icon,
            },
            "Button.Image::material_solo": {"image_url": self.material_icon},
            "Image::collapsable_opened": {"image_url": f"{extension_path}/data/icons/opened.svg"},
            "Image::collapsable_closed": {"image_url": f"{extension_path}/data/icons/closed.svg"},
            "Label::main_label": {
                "alignment": ui.Alignment.CENTER_TOP,
                "margin_height": 1,
                "margin_width": 10,
                "font_size": 32,
            },
            "Label::material_name": {
                "alignment": ui.Alignment.CENTER_TOP,
                "margin_height": 1,
                "margin_width": 10,
                "font_size": 14,
            },
            "Label::secondary_label": {
                "alignment": ui.Alignment.LEFT_CENTER,
                "margin_height": 1,
                "margin_width": 10,
                "font_size": 24,
            },
            "Label::material_counter": {
                "alignment": ui.Alignment.CENTER,
                "margin_height": 1,
                "margin_width": 10,
                "font_size": 14,
            },
        }
        self.render_default_layout()

    def on_shutdown(self):
        """
        This function is called when the addon is disabled
        """
        omni.kit.commands.unsubscribe_on_change(self.on_change)
        print("[karpenko.materialsmanager.ext] MaterialManagerExtended shutdown")

    def get_latest_version(self, looks):
        latest_version = 1
        versions = []
        for look in looks.GetChildren():
            look_path = look.GetPath()
            if look_path.name.startswith("Look_"):
                version = int(look_path.name.split("_")[-1])
                versions.append(version)
        versions.sort()
        for version in versions:
            if version != latest_version:
                return latest_version
            else:
                latest_version += 1
        return latest_version

    def add_variant(self, looks, parent_prim):
        """
        It creates a new folder under the Looks folder, copies all materials from the parent prim and binds them to the
        meshes

        :param looks: The looks folder
        :param parent_prim: The prim that contains the meshes that need to be assigned the new materials
        """
        looks = parent_prim.GetPrimAtPath("Looks")
        looks_path = looks.GetPath()

        self.ignore_change = True
        # group all commands so it can be undone at once
        with omni.kit.undo.group():
            # Check if folder (prim, Scope) MME already exist
            if not looks.GetPrimAtPath("MME"):
                # Create a folder called MME under the looks folder, it will contain all the materials for all variants
                omni.kit.commands.execute(
                    "CreatePrim",
                    prim_path=f"{looks_path}/MME",
                    prim_type="Scope",
                    attributes={},
                    select_new_prim=False
                )
            # Generate a new name for the variant based on the quantity of previous ones
            folder_name = f"Look_{self.get_latest_version(looks.GetPrimAtPath('MME'))}"
            # Create a folder for the new variant
            omni.kit.commands.execute(
                "CreatePrim",
                prim_path=f"{looks_path}/MME/{folder_name}",
                prim_type="Scope",
                attributes={},
                select_new_prim=False
            )
            
            is_active_attr_path = Sdf.Path(f"{looks_path}/MME/{folder_name}.MMEisActive")

            omni.kit.commands.execute(
                'CreateUsdAttributeOnPath',
                attr_path=is_active_attr_path,
                attr_type=Sdf.ValueTypeNames.Bool,
                custom=True,
                variability=Sdf.VariabilityVarying
            )

            all_meshes = []
            # Get all meshes
            for mesh in parent_prim.GetChildren():
                if mesh.GetTypeName() == "Mesh":
                    all_meshes.append(mesh)
            
            if folder_name is None:
                new_looks_folder = looks
            else:
                new_looks_folder = looks.GetPrimAtPath(f"MME/{folder_name}")
            new_looks_folder_path = new_looks_folder.GetPath()
            processed_materials = []
            all_materials = []
            # loop through all meshes
            for mesh_data in all_meshes:
                # Get currently binded materials for the current mesh
                current_material_prims = mesh_data.GetRelationship('material:binding').GetTargets()
                
                # Loop through all binded materials paths
                for original_material_prim_path in current_material_prims:
                    original_material_prim = self.stage.GetPrimAtPath(original_material_prim_path)
                    # Check if was not already processed to avoid duplicates
                    if original_material_prim_path not in processed_materials:
                        all_materials.append({
                            "name": original_material_prim.GetName(),
                            "path": original_material_prim_path,
                            "mesh": mesh_data.GetPath(),
                        })
                        processed_materials.append(original_material_prim_path)
                    
            # Copy material's prim as text
            usd_code = get_prim_as_text(self.stage, [mat_data["path"] for mat_data in all_materials])
            # put the clone material into the scene
            text_to_stage(self.stage, usd_code, new_looks_folder_path)

            for mat_data in all_materials:
                mat_name = mat_data["name"]
                
                # Bind the new material to the mesh
                omni.kit.commands.execute(
                    'BindMaterial',
                    material_path=f'{new_looks_folder_path}/{mat_name}',
                    prim_path=mat_data["mesh"],
                    strength=['weakerThanDescendants']
                )

            # Convert every Path to string in all_materials to be able to pass it into JSON
            all_materials = [{
                "name": mat_data["name"],
                "path": str(mat_data["path"]),
                "mesh": str(mat_data["mesh"]),
            } for mat_data in all_materials]

            data_attr_path = Sdf.Path(f"{looks_path}/MME/{folder_name}.MMEMeshData")
            omni.kit.commands.execute(
                'CreateUsdAttributeOnPath',
                attr_path=data_attr_path,
                attr_type=Sdf.ValueTypeNames.StringArray,
                custom=True,
                variability=Sdf.VariabilityVarying,
                attr_value=[base64.b64encode(json.dumps(i).encode()) for i in all_materials],
            )

            self.deactivate_all_variants(looks)
            omni.kit.commands.execute(
                'ChangeProperty',
                prop_path=is_active_attr_path,
                value=True,
                prev="",
            )
                        
        self.render_variants_frame(looks, parent_prim)

    def deactivate_all_variants(self, looks):
        """
        Deactivates all variants
        """
        looks_path = looks.GetPath()
        mme_folder = looks.GetPrimAtPath("MME")
        if mme_folder:
            for look in mme_folder.GetChildren():
                p_type = look.GetTypeName()
                if p_type == "Scope":
                    omni.kit.commands.execute(
                        'ChangeProperty',
                        prop_path=Sdf.Path(f"{looks_path}/MME/{look.GetName()}.MMEisActive"),
                        value=False,
                        prev="",
                    )

    def on_change(self):
        if not self.force_render:
            # Get history of commands
            current_history = omni.kit.undo.get_history().values()
            # Get the latest one
            latest_action = next(reversed(current_history))

            if latest_action.name not in self.allowed_commands:
                return
            # To skip the changes made by the addon
            if self.ignore_change:
                self.ignore_change = False
                return
        else:
            self.force_render = False
        show_default_layout = True

        # Get the top-level prim (World)
        settings = carb.settings.get_settings()
        default_prim_name = settings.get("/persistent/app/stage/defaultPrimName")
        rootname = f"/{default_prim_name}"
        # Get currently selected prim
        paths = self._selection.get_selected_prim_paths()
        if paths:
            # Get path of the first selected prim
            base_path = paths[0] if len(paths) > 0 else None
            base_path = Sdf.Path(base_path) if base_path else None
            if base_path:
                # Skip if the prim is the root of the stage to avoid unwanted errors
                if base_path == rootname:
                    return
                # Skip if this object was already selected previously. Protection from infinite loop.
                if base_path == self.latest_selected_prim:
                    return
                # Save the path of the currently selected prim for the next iteration
                self.latest_selected_prim = base_path
                # Get prim from path
                prim = self.stage.GetPrimAtPath(base_path)
                if prim:
                    p_type = prim.GetTypeName()
                    # This is needed to successfully get the prim even if it's child was selected
                    if p_type == "Mesh" or p_type == "Scope":
                        prim = prim.GetParent()
                    elif p_type == "Material":
                        prim = prim.GetParent().GetParent()
                    elif p_type == "Xform":
                        # Current prim is already parental one, so we don't need to do anything.
                        pass
                    else:
                        # In case if something unexpected is selected, we just return None
                        carb.log_warn(f"Selected {prim} does not has any materials")
                        return
                    if prim.GetPrimAtPath("Looks") and prim != self.latest_selected_prim:
                        # Save the type of the rendered window
                        self.current_ui = "object"
                        # Render new window for the selected prim
                        self.render_objectlevel_frame(prim)
                    show_default_layout = False

        if show_default_layout and self.current_ui != "default":
            self.current_ui = "default"
            self.render_scenelevel_frame()
            self.latest_selected_prim = None

    def _get_looks(self, path):
        """
        :param path: The path to the prim you want to get the looks from
        :return: The parent-prim and the looks (materials).
        """
        prim = self.stage.GetPrimAtPath(path)
        p_type = prim.GetTypeName()
        # User could select not the prim directly but sub-items of it, so we need to make sure in any scenario
        # we will get the parent prim.
        if p_type == "Mesh" or p_type == "Scope":
            prim = prim.GetParent()
        elif p_type == "Material":
            prim = prim.GetParent().GetParent()
        elif p_type == "Xform":
            # Current prim is already parental one, so we don't need to do anything.
            pass
        else:
            # In case if something unexpected is selected, we just return None
            carb.log_error("No selected prim")
            return None, None
        # Get all looks (a.k.a. materials)
        looks = prim.GetPrimAtPath("Looks").GetChildren()
        # return a parental prim object and its looks
        return prim, looks

    def get_all_materials_variants(self, looks_prim):
        """
        :param prim: The prim you want to get the variants from
        :return: A list of all variants of the prim
        """
        variants = []
        mme_folder = looks_prim.GetPrimAtPath("MME")
        if mme_folder:
            for child in mme_folder.GetChildren():
                if child.GetTypeName() == "Scope":
                    variants.append(child)
        return variants

    def delete_variant(self, prim_path, looks, parent_prim):
        omni.kit.commands.execute('DeletePrims', paths=[prim_path, ])
        self.render_variants_frame(looks, parent_prim)

    def enable_variant(self, folder_name, looks, parent_prim):
        all_meshes = []
        # Get all meshes
        for mesh in parent_prim.GetChildren():
            if mesh.GetTypeName() == "Mesh":
                all_meshes.append(mesh)
        
        if folder_name is None:
            new_looks_folder = looks
        else:
            new_looks_folder = looks.GetPrimAtPath(f"MME/{folder_name}")
        new_looks_folder_path = new_looks_folder.GetPath()
        processed_materials = []
        all_materials = []
        # loop through all meshes
        for mesh_data in all_meshes:
            # Get currently binded materials for the current mesh
            current_material_prims = mesh_data.GetRelationship('material:binding').GetTargets()
            
            # Loop through all binded materials paths
            for original_material_prim_path in current_material_prims:
                original_material_prim = self.stage.GetPrimAtPath(original_material_prim_path)
                # Check if was not already processed to avoid duplicates
                if original_material_prim_path not in processed_materials:
                    all_materials.append({
                        "name": original_material_prim.GetName(),
                    })
                    processed_materials.append(original_material_prim_path)
                
        for mat_data in all_materials:
            mat_name = mat_data["name"]
            
            # Bind the new material to the mesh
            omni.kit.commands.execute(
                'BindMaterial',
                material_path=f'{new_looks_folder_path}/{mat_name}',
                prim_path=mesh_data.GetPath(),
                strength=['weakerThanDescendants']
            )
                    
        self.render_variants_frame(looks, parent_prim)

    def select_material(self, associated_mesh):
        if associated_mesh:
            mesh = self.stage.GetPrimAtPath(associated_mesh)
            if mesh:
                current_material_prims = mesh.GetRelationship('material:binding').GetTargets()
                if current_material_prims:
                    print(current_material_prims)
                    omni.usd.get_context().get_selection().set_prim_path_selected(
                        str(current_material_prims[0]), True, True, True, True
                    )

    def render_variants_frame(self, looks, parent_prim):
        """
        It renders the variants frame, it contains all the variants of the current prim

        :param parent_prim: The prim that contains the variants
        """
        is_variants_active = False
        all_variants = self.get_all_materials_variants(looks)
        for variant_prim in all_variants:
            is_active_attr = variant_prim.GetAttribute("MMEisActive")
            if is_active_attr:
                if is_active_attr.Get():
                    is_variants_active = True
                    break
        active_status = '' if is_variants_active else ' (Active)'
        if not self.materials_frame_original:
            self.materials_frame_original = ui.Frame(name="materials_frame_original", identifier="materials_frame_original")
        with self.materials_frame_original:
            with ui.CollapsableFrame(f"Original{active_status}", height=ui.Pixel(10), collapsed=is_variants_active):
                with ui.VStack():
                    ui.Label("Your original, unmodified materials. Cannot be deleted.", name="variant_label", height=40)
                    if is_variants_active:
                        with ui.HStack():
                            ui.Button("Enable", name="variant_button", clicked_fn=lambda: self.enable_variant(None, looks, parent_prim))
        
        if not self.materials_frame:
            self.materials_frame = ui.Frame(name="materials_frame", identifier="materials_frame")
        with self.materials_frame:
            with ui.VStack():
                for variant_prim in all_variants:
                    is_active_attr = variant_prim.GetAttribute("MMEisActive")
                    if is_active_attr:
                        is_active = is_active_attr.Get()
                        active_status = ' (Active)' if is_active else ''
                        with ui.CollapsableFrame(f"{variant_prim.GetName()}{active_status}", height=ui.Pixel(10), collapsed=not is_active):
                            with ui.VStack():
                                with ui.HStack():
                                    if not active_status:
                                        prim_name = variant_prim.GetName()
                                        ui.Button("Enable", name="variant_button", clicked_fn=lambda p_name=prim_name: self.enable_variant(p_name, looks, parent_prim))
                                        prim_path = variant_prim.GetPath()
                                        ui.Button("Delete", name="variant_button", clicked_fn=lambda p_path=prim_path: self.delete_variant(p_path, looks, parent_prim))
                                    else:
                                        label_text = "This variant is enabled.\nMake changes to the active materials from above to edit this variant.\nAll changes will be saved automatically."
                                        ui.Label(label_text, name="variant_label", height=40)
                                    
        return self.materials_frame_original, self.materials_frame

    def render_objectlevel_frame(self, prim):
        looks = prim.GetPrimAtPath("Looks")

        all_meshes = []
        all_mat_paths = []
        # Get all meshes
        for mesh in prim.GetChildren():
            if mesh.GetTypeName() == "Mesh":
                material_paths = mesh.GetRelationship('material:binding').GetTargets()
                all_meshes.append({"mesh": mesh, "material_paths": material_paths})
                for original_material_prim_path in material_paths:
                    all_mat_paths.append(original_material_prim_path)
        materials_quantity = len(list(dict.fromkeys(all_mat_paths)))
        materials_column_count = 1
        if materials_quantity > 6:
            materials_column_count = 2
        if self.materials_frame:
            self.materials_frame = None
        if self.materials_frame_original:
            self.materials_frame_original = None

        processed_materials = []
        if not self.main_frame:
            self.main_frame = ui.Frame(name="materials_frame", identifier="materials_frame")
        with self.main_frame:
            with ui.VStack(style=self._style):
                ui.Label(prim.GetName(), name="main_label", height=40)
                ui.Spacer(height=10)
                with ui.VStack(height=250):
                    with ui.CollapsableFrame("Active materials", height=ui.Pixel(10), collapsed=True):
                        with ui.VGrid(column_count=materials_column_count):
                            material_counter = 1
                            # loop through all meshes
                            for mesh_data in all_meshes:
                                # Get currently binded materials for the current mesh
                                current_material_prims = mesh_data["material_paths"]
                                # Loop through all binded materials paths
                                for original_material_prim_path in current_material_prims:
                                    if original_material_prim_path in processed_materials:
                                        continue
                                    # Get the material prim from path
                                    original_material_prim = self.stage.GetPrimAtPath(original_material_prim_path)
                                    with ui.HStack():
                                        if materials_column_count == 1:
                                            ui.Label(
                                                f"{material_counter}",
                                                name="material_counter",
                                                width=40,
                                            )
                                            ui.Image(
                                                self.material_icon,
                                                height=24,
                                                width=24,
                                            )
                                            ui.Spacer(height=10, width=10)
                                            ui.Label(
                                                original_material_prim.GetName(),
                                                
                                                elided_text=True
                                            )
                                            
                                            ui.Button(
                                                "Select",
                                                name="variant_button",
                                                width=ui.Percent(30),
                                                clicked_fn=lambda mesh_path=mesh_data["mesh"].GetPath(): self.select_material(mesh_path),
                                            )
                                        else:
                                            ui.Label(
                                                f"{material_counter}",
                                                name="material_counter",
                                                width=50,
                                            )
                                            ui.Image(
                                                self.material_icon,
                                                height=24,
                                                width=24,
                                            )
                                            
                                            ui.Label(
                                                original_material_prim.GetName(),
                                                
                                                elided_text=True
                                            )
                                            
                                            ui.Button(
                                                "Select",
                                                name="variant_button",
                                                width=ui.Percent(30),
                                                clicked_fn=lambda: self.select_material(mesh_data["mesh"].GetPath()),
                                            )
                                    material_counter += 1
                                    processed_materials.append(original_material_prim_path)
                            ui.Spacer(height=20)
                ui.Spacer(height=20)
                ui.Label("All variants", name="secondary_label", height=40)
                self.render_variants_frame(looks, prim)
                ui.Spacer(height=20)
                ui.Button(
                    "Add new variant",
                    height=20,
                    clicked_fn=lambda: self.add_variant(looks, prim),
                    alignment=ui.Alignment.CENTER_BOTTOM,
                    tooltip="Create a new variant, based on the current look",
                )

    def render_scenelevel_frame(self):
        if not self.main_frame:
            self.main_frame = ui.Frame(name="materials_frame", identifier="materials_frame")
        with self.main_frame:
            with ui.VStack():
                ui.Label("Some Label")

                ui.Button("Click Me")

    def render_default_layout(self, prim=None):
        if self.main_frame:
            self.main_frame = None
        if self.materials_frame:
            self.materials_frame = None
        if self.materials_frame_original:
            self.materials_frame_original = None
        self._window = ui.Window("Material Manager", width=300, height=300)
        with self._window.frame:
            if not prim:
                self.render_scenelevel_frame()
            else:
                self.render_objectlevel_frame(prim)
            
