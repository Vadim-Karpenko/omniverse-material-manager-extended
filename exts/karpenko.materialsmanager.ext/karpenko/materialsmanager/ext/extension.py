import base64
import json

import carb
import omni.ext
import omni.kit.commands
import omni.ui as ui
import omni.usd
import asyncio
from omni.kit.viewport.utility import get_active_viewport_window
from pxr import Sdf
from .prim_serializer import get_prim_as_text, text_to_stage
from .style import materialsmanager_window_style as _style
from .viewport_ui.widget_info_scene import WidgetInfoScene


class MaterialManagerExtended(omni.ext.IExt):
    WINDOW_NAME = "Material Manager Extended"
    SCENE_SETTINGS_WINDOW_NAME = "Material Manager Settings"
    MENU_PATH = "Window/" + WINDOW_NAME

    def on_startup(self, ext_id):
        print("[karpenko.materialsmanager.ext] MaterialManagerExtended startup")
        self._usd_context = omni.usd.get_context()
        self._selection = self._usd_context.get_selection()
        self.latest_selected_prim = None
        self.variants_frame_original = None
        self.variants_frame = None
        self.active_objects_frame = None
        self._window = None
        self._window_scenemanager = None
        self.materials_frame = None
        self.main_frame = None
        self.ignore_change = False
        self.ignore_settings_update = False
        self.ext_id = ext_id
        self._widget_info_viewport = None
        self.current_ui = "default"
        self.is_settings_open = False
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
            "MovePrims",
            "MovePrim",
        ]
        self.is_settings_window_open = False
        self.render_default_layout()
        # show the window in the usual way if the stage is loaded
        if self.stage:
            self._window.deferred_dock_in("Property")
        else:
            # otherwise, show the window after the stage is loaded
            self._setup_window_task = asyncio.ensure_future(self._dock_window())
        omni.kit.commands.subscribe_on_change(self.on_change)

    def on_shutdown(self):
        """
        This function is called when the addon is disabled
        """
        omni.kit.commands.unsubscribe_on_change(self.on_change)
        # Deregister the function that shows the window from omni.ui
        ui.Workspace.set_show_window_fn(self.WINDOW_NAME, None)
        if self._window:
            self._window.destroy()
            self._window = None
        self._selection = None
        self._usd_context = None
        self.latest_selected_prim = None
        self.variants_frame_original = None
        self.variants_frame = None
        self.materials_frame = None
        self.main_frame = None
        if self._widget_info_viewport:
            self._widget_info_viewport.destroy()
            self._widget_info_viewport = None
        print("[karpenko.materialsmanager.ext] MaterialManagerExtended shutdown")

    async def _dock_window(self):
        """
        It waits for the property window to appear, then docks the window to it
        """
        property_win = None

        frames = 3
        while frames > 0:
            if not property_win:
                property_win = ui.Workspace.get_window("Property")
            if property_win:
                break  # early out

            frames = frames - 1
            await omni.kit.app.get_app().next_update_async()

        # Dock to property window after 5 frames. It's enough for window to appear.
        for _ in range(5):
            await omni.kit.app.get_app().next_update_async()

        if property_win:
            self._window.deferred_dock_in("Property")
        self._setup_window_task = None

    def get_latest_version(self, looks):
        """
        It takes a list of looks, and returns the next available version number

        :param looks: The parent folder of the looks
        :return: The latest version of the look.
        """
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
        It creates a new folder under the Looks folder, copies all materials attached to the meshes and re-binds them
        so the user can tweak copies instead of the original ones.

        :param looks: The looks folder
        :param parent_prim: The prim that contains the meshes that need to be assigned the new materials
        """
        looks = parent_prim.GetPrimAtPath("Looks")
        looks_path = looks.GetPath()

        self.ignore_change = True
        # group all commands so it can be undone at once
        with omni.kit.undo.group():
            all_meshes = self.get_meshes_from_prim(parent_prim)
            all_materials = self.get_data_from_meshes(all_meshes)
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

                is_active_attr_path = Sdf.Path(f"{looks_path}/MME.MMEisActive")

                omni.kit.commands.execute(
                    'CreateUsdAttributeOnPath',
                    attr_path=is_active_attr_path,
                    attr_type=Sdf.ValueTypeNames.Bool,
                    custom=True,
                    attr_value=False,
                    variability=Sdf.VariabilityVarying
                )
                self.set_mesh_data(all_materials, looks_path, None)

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

            if folder_name is None:
                new_looks_folder = looks
            else:
                new_looks_folder = looks.GetPrimAtPath(f"MME/{folder_name}")
            new_looks_folder_path = new_looks_folder.GetPath()
            # Copy material's prim as text
            usd_code = get_prim_as_text(self.stage, [mat_data["path"] for mat_data in all_materials])
            # put the clone material into the scene
            text_to_stage(self.stage, usd_code, new_looks_folder_path)

            self.bind_materials(all_materials, new_looks_folder_path)
            self.set_mesh_data(all_materials, looks_path, folder_name)
            self.deactivate_all_variants(looks)
            # Set current variant as active
            omni.kit.commands.execute(
                'ChangeProperty',
                prop_path=is_active_attr_path,
                value=True,
                prev="",
            )
        self.ignore_change = False
        if not self.ignore_settings_update:
            self.render_active_objects_frame()
            self.render_variants_frame(looks, parent_prim)

    def get_meshes_from_prim(self, parent_prim):
        """
        It takes a parent prim and returns a list of all the meshes that are children of that prim

        :param parent_prim: The parent prim of the mesh you want to get
        :return: A list of all meshes in the scene.
        """
        all_meshes = []
        for mesh in self.get_all_children_of_prim(parent_prim):
            if mesh.GetTypeName() == "Mesh":
                all_meshes.append(mesh)
        return all_meshes

    def get_data_from_meshes(self, all_meshes):
        """
        It loops through all passed meshes, gets the materials that are bound to them, and returns a list of
        dictionaries containing the material name, path, and the mesh it's bound to

        :param all_meshes: a list of all the meshes in the scene
        :return: A list of dictionaries.
        """
        processed_materials = []
        result = []
        # loop through all meshes
        for mesh_data in all_meshes:
            # Get currently binded materials for the current mesh
            current_material_prims = mesh_data.GetRelationship('material:binding').GetTargets()

            # Loop through all binded materials paths
            for original_material_prim_path in current_material_prims:
                original_material_prim = self.stage.GetPrimAtPath(original_material_prim_path)
                if not original_material_prim:
                    continue
                # Check if was not already processed to avoid duplicates
                if original_material_prim_path not in processed_materials:
                    result.append({
                        "name": original_material_prim.GetName(),
                        "path": original_material_prim_path,
                        "mesh": mesh_data.GetPath(),
                    })
                    processed_materials.append(original_material_prim_path)
        return result

    def bind_materials(self, all_materials, variant_folder_path):
        """
        Look through all the materials and bind them to the meshes.
        If variant_folder_path is empty, then just binds passed materials. If not, looks for the materials in the
        variant folder and binds them instead using all_materials as a reference.

        :param all_materials: A list of dictionaries containing the material path and the mesh path
        :param variant_folder_path: The path to the variant folder
        """
        # Check if there is a variant folder where new materials are stored
        if variant_folder_path:
            variant_materials_prim = self.stage.GetPrimAtPath(variant_folder_path)
        with omni.kit.undo.group():
            # loop through all passed materials
            for mat_data in all_materials:
                if variant_folder_path and variant_materials_prim:
                    # loop throug all materials in the variant folder
                    for var_mat in variant_materials_prim.GetChildren():
                        # If found material matches with the one in the all_materials list, bind it to the mesh
                        if var_mat.GetName() == str(mat_data["path"]).split("/")[-1]:
                            omni.kit.commands.execute(
                                "BindMaterial",
                                prim_path=mat_data["mesh"],
                                material_path=var_mat.GetPath(),
                                strength=['weakerThanDescendants']
                            )
                            break
                else:
                    # If there's no variant folder, then just bind passed material to the mesh
                    omni.kit.commands.execute(
                        'BindMaterial',
                        material_path=mat_data["path"],
                        prim_path=mat_data["mesh"],
                        strength=['weakerThanDescendants']
                    )

    def deactivate_all_variants(self, looks):
        """
        It deactivates all variants in a given looks prim

        :param looks: The looks prim
        """
        looks_path = looks.GetPath()
        mme_folder = looks.GetPrimAtPath("MME")
        # Check if mme folder exists
        if mme_folder:
            # MMEisActive also present in MME folder, so we need to set it to False as well.
            mme_folder_prop_path = Sdf.Path(f"{looks_path}/MME.MMEisActive")
            mme_is_active = self.stage.GetAttributeAtPath(mme_folder_prop_path).Get()
            if mme_is_active:
                omni.kit.commands.execute(
                    'ChangeProperty',
                    prop_path=mme_folder_prop_path,
                    value=False,
                    prev=True,
                )
            # Loop through all variants in the MME folder and deactivate them
            for look in mme_folder.GetChildren():
                p_type = look.GetTypeName()
                if p_type == "Scope":
                    look_is_active_path = Sdf.Path(f"{looks_path}/MME/{look.GetName()}.MMEisActive")
                    look_is_active = self.stage.GetAttributeAtPath(look_is_active_path).Get()
                    if look_is_active:
                        omni.kit.commands.execute(
                            'ChangeProperty',
                            prop_path=look_is_active_path,
                            value=False,
                            prev=True,
                        )

    def get_parent_from_mesh(self, mesh_prim):
        """
        It takes a mesh prim as an argument and returns the first Xform prim it finds in the prim's ancestry

        :param mesh_prim: The mesh prim you want to get the parent of
        :return: The parent of the mesh_prim.
        """
        parent_prim = mesh_prim.GetParent()
        default_prim = self.stage.GetDefaultPrim()
        if not default_prim:
            return
        default_prim_name = default_prim.GetName()
        rootname = f"/{default_prim_name}"
        while True:
            if parent_prim is None or parent_prim.IsPseudoRoot():
                return parent_prim
            if str(parent_prim.GetPath()) == "/" or str(parent_prim.GetPath()) == rootname:
                return None
            if parent_prim.GetPrimAtPath("Looks") and str(parent_prim.GetPath()) != rootname:
                return parent_prim
            parent_prim = parent_prim.GetParent()
        return parent_prim

    def get_looks_folder(self, parent_prim):
        """
        If the parent_prim has a child prim named "Looks", return that found prim. Otherwise, return None

        :param parent_prim: The parent prim of the looks folder
        :return: The looks folder if it exists, otherwise None.
        """
        looks_folder = parent_prim.GetPrimAtPath("Looks")
        return looks_folder if looks_folder else None

    def check_if_original_active(self, mme_folder):
        """
        If the folder has an attribute called "MMEisActive" and it's value is True, return the folder and True.
        Otherwise, return the folder and False

        :param mme_folder: The folder that contains the MME data
        :return: the mme_folder and a boolean value.
        """
        if mme_folder:
            mme_is_active_attr = mme_folder.GetAttribute("MMEisActive")
            if mme_is_active_attr and mme_is_active_attr.Get():
                return mme_folder, True
        return mme_folder, False

    def get_currently_active_folder(self, looks):
        """
        It looks for a folder called "MME" in the "Looks" folder, and if it finds it, it search for a folder inside
        with an attribute MMEisActive set to True and returns it if it finds one.
        If it doesn't find one, it returns None.

        :param looks: The looks node
        :return: The currently active folder.
        """
        mme_folder = looks.GetPrimAtPath("MME")
        if mme_folder:
            if mme_folder.GetTypeName() == "Scope":
                for look in mme_folder.GetChildren():
                    if look.GetTypeName() == "Scope":
                        is_active_attr = look.GetAttribute("MMEisActive")
                        if is_active_attr and is_active_attr.Get():
                            return look
        return None

    def update_material_data(self, latest_action):
        """
        It updates the material data in the looks folder when a material is changed using data from the latest action.
        All data is converted into string and encrypted into base64 to prevent it from being seen or modified
        by the user.

        :param latest_action: The latest action that was performed in the scene
        :return: The return value is a list of dictionaries.
        """
        if "prim_path" not in latest_action.kwargs or "material_path" not in latest_action.kwargs:
            return
        prim_path = latest_action.kwargs["prim_path"]
        if not prim_path:
            return
        if type(prim_path) == list:
            prim_path = prim_path[0]
        new_material_path = latest_action.kwargs["material_path"]
        if not new_material_path:
            return
        if type(new_material_path) == list:
            new_material_path = new_material_path[0]
        parent_mesh = self.get_parent_from_mesh(self.stage.GetPrimAtPath(prim_path))
        looks = self.get_looks_folder(parent_mesh)
        if looks:
            looks_path = looks.GetPath()
            mme_folder, is_original_active = self.check_if_original_active(looks.GetPrimAtPath("MME"))
            if is_original_active:
                folder_name = None
            else:
                active_folder = self.get_currently_active_folder(looks)
                if not active_folder:
                    return
                folder_name = active_folder.GetName()
            mesh_data = self.get_mesh_data(looks_path, folder_name)
            mesh_data_to_update = []
            previous_mats = []
            if mesh_data:
                for mat_data in mesh_data:
                    if mat_data["mesh"] == prim_path and mat_data["path"] != new_material_path:
                        carb.log_warn("Material changes detected. Updating material data...")
                        previous_mats.append(mat_data["path"])
                        mat_data["path"] = new_material_path
                        mesh_data_to_update.append(mat_data)
                        break
                else:
                    return

                if not is_original_active and folder_name:
                    active_folder_path = active_folder.GetPath()
                    # Copy material's prim as text
                    usd_code = get_prim_as_text(self.stage, [Sdf.Path(i["path"]) for i in mesh_data])
                    omni.kit.commands.execute(
                        'DeletePrims',
                        paths=[i.GetPath() for i in active_folder.GetChildren()]
                    )
                    # put the clone material into the scene
                    text_to_stage(self.stage, usd_code, active_folder_path)
                    self.ignore_change = True
                    self.bind_materials(mesh_data_to_update, active_folder_path)
                    self.ignore_change = False
                self.set_mesh_data(mesh_data, looks_path, folder_name)
                self.render_current_materials_frame(parent_mesh)

    def on_change(self):
        """
        Everytime the user changes the scene, this method is called.
        Method does the following:
        It checks if the user has changed the material, and if so, it updates the material data in the apropriate
        variant folder or save it into the MME folder if the variant is set to \"original\".
        It checks if the selected object has a material, and if it does, it renders a new window with the material's
        properties of the selected object.
        If the selected object doesn't have a material, it renders a new window with a prompt to select an object with
        a material.

        :return: None
        """
        if not self.stage:
            self._usd_context = omni.usd.get_context()
            self._selection = self._usd_context.get_selection()
            self.stage = self._usd_context.get_stage()
        # Get history of commands
        current_history = reversed(omni.kit.undo.get_history().values())
        # Get the latest one
        latest_action = next(current_history)

        if latest_action.name == "ChangePrimVarCommand" and latest_action.level == 1:
            latest_action = next(current_history)

        if latest_action.name not in self.allowed_commands:
            return
        # To skip the changes made by the addon
        if self.ignore_change:
            return
        show_default_layout = True

        if latest_action.name in ["BindMaterial", "BindMaterialCommand"]:
            self.update_material_data(latest_action)
            return

        # Get the top-level prim (World)
        default_prim = self.stage.GetDefaultPrim()
        if not default_prim:
            return
        default_prim_name = default_prim.GetName()
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
                    if p_type == "Mesh" or p_type == "Scope" or p_type == "Material":
                        prim = self.get_parent_from_mesh(prim)
                    elif p_type == "Xform":
                        # Current prim is already parental one, so we don't need to do anything.
                        pass
                    else:
                        # In case if something unexpected is selected, we just return None
                        carb.log_warn(f"Selected {prim} does not has any materials or has invalid type.")
                        return
                    if not prim:
                        self.render_scenelevel_frame()
                        return
                    if prim.GetPrimAtPath("Looks") and prim != self.latest_selected_prim:
                        # Save the type of the rendered window
                        self.current_ui = "object"
                        # Render new window for the selected prim
                        self.render_objectlevel_frame(prim)
                        if not self.ignore_settings_update:
                            self.render_active_objects_frame()
                    show_default_layout = False

        if show_default_layout and self.current_ui != "default":
            self.current_ui = "default"
            self.render_scenelevel_frame()
            if not self.ignore_settings_update:
                self.render_active_objects_frame()
            self.latest_selected_prim = None

    def _get_looks(self, path):
        """
        It gets the prim at the path, checks if it's a mesh, scope, or material, and if it is, it gets the parent prim.
        If it's an xform, it does nothing. If it's something else, it returns None

        :param path: The path to the prim you want to get the looks from
        :return: The prim and the looks.
        """
        prim = self.stage.GetPrimAtPath(path)
        p_type = prim.GetTypeName()
        # User could select not the prim directly but sub-items of it, so we need to make sure in any scenario
        # we will get the parent prim.
        if p_type == "Mesh" or p_type == "Scope" or p_type == "Material":
            prim = self.get_parent_from_mesh(prim)
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
        It returns a list of all the variants in the MME folder

        :param looks_prim: The prim that contains the MME folder
        :return: A list of all the variants in the MME folder.
        """
        variants = []
        mme_folder = looks_prim.GetPrimAtPath("MME")
        if mme_folder:
            for child in mme_folder.GetChildren():
                if child.GetTypeName() == "Scope":
                    variants.append(child)
        return variants

    def get_mesh_data(self, looks_path, folder_name):
        """
        It gets the mesh data from the folder you pass as a parameter.
        It does decode it back from base64 and returns it as a dictionary.

        :param looks_path: The path to the looks prim
        :param folder_name: The name of the folder that contains the mesh data
        :return: A list of dictionaries.
        """
        if folder_name:
            data_attr_path = Sdf.Path(f"{looks_path}/MME/{folder_name}.MMEMeshData")
        else:
            data_attr_path = Sdf.Path(f"{looks_path}/MME.MMEMeshData")
        data_attr = self.stage.GetAttributeAtPath(data_attr_path)
        if data_attr:
            attr_value = data_attr.Get()
            if attr_value:
                result = []
                # decode base64 string and load json
                for item in attr_value:
                    result.append(json.loads(base64.b64decode(item).decode("utf-8")))
                return result

    def set_mesh_data(self, mesh_materials, looks_path, folder_name):
        """
        It creates a custom attribute on a USD prim, and sets the value of that attribute to a list of base64
        encoded JSON strings

        :param mesh_materials: A list of dictionaries containing the following keys: path, mesh
        :param looks_path: The path to the looks prim
        :param folder_name: The name of the folder that contains the mesh data
        """
        # Convert every Path to string in mesh_materials to be able to pass it into JSON
        all_materials = [{
            "path": str(mat_data["path"]),
            "mesh": str(mat_data["mesh"]),
        } for mat_data in mesh_materials]

        if folder_name:
            data_attr_path = Sdf.Path(f"{looks_path}/MME/{folder_name}.MMEMeshData")
        else:
            data_attr_path = Sdf.Path(f"{looks_path}/MME.MMEMeshData")
        omni.kit.commands.execute(
            'CreateUsdAttributeOnPath',
            attr_path=data_attr_path,
            attr_type=Sdf.ValueTypeNames.StringArray,
            custom=True,
            variability=Sdf.VariabilityVarying,
            attr_value=[base64.b64encode(json.dumps(i).encode()) for i in all_materials],
        )

    def delete_variant(self, prim_path, looks, parent_prim):
        """
        It deletes the variant prim and then re-renders the variants frame

        :param prim_path: The path to the variant prim you want to delete
        :param looks: a list of all the looks in the current scene
        :param parent_prim: The prim path of the parent prim of the variant set
        """
        omni.kit.commands.execute('DeletePrims', paths=[prim_path, ])
        self.render_variants_frame(looks, parent_prim)

    def enable_variant(self, folder_name, looks, parent_prim, ignore_changes=True):
        """
        It takes a folder name, a looks prim, and a parent prim, and then it activates the variant in the folder,
        binds the materials in the variant, and renders the variant and current materials frames

        :param folder_name: The name of the folder that contains the materials you want to enable
        :param looks: the looks prim
        :param parent_prim: The prim that contains the variant sets
        """
        if ignore_changes:
            self.ignore_change = True
        if folder_name is None:
            new_looks_folder = looks.GetPrimAtPath("MME")
        else:
            new_looks_folder = looks.GetPrimAtPath(f"MME/{folder_name}")
        new_looks_folder_path = new_looks_folder.GetPath()
        all_materials = self.get_mesh_data(looks.GetPath(), folder_name)
        self.deactivate_all_variants(looks)
        is_active_attr_path = Sdf.Path(f"{new_looks_folder_path}.MMEisActive")
        omni.kit.commands.execute(
                'ChangeProperty',
                prop_path=is_active_attr_path,
                value=True,
                prev=False,
            )
        self.bind_materials(all_materials, None if folder_name is None else new_looks_folder_path)
        self.render_variants_frame(looks, parent_prim, ignore_widget=True)
        self.render_current_materials_frame(parent_prim)
        if ignore_changes:
            self.ignore_change = False

    def select_material(self, associated_mesh):
        """
        It selects the material of the mesh that is currently selected in the viewport

        :param associated_mesh: The path to the mesh you want to select the material for
        """
        if associated_mesh:
            mesh = self.stage.GetPrimAtPath(associated_mesh)
            if mesh:
                current_material_prims = mesh.GetRelationship('material:binding').GetTargets()
                if current_material_prims:
                    omni.usd.get_context().get_selection().set_prim_path_selected(
                        str(current_material_prims[0]), True, True, True, True)
                    ui.Workspace.show_window("Property", True)
                    property_window = ui.Workspace.get_window("Property")
                    ui.WindowHandle.focus(property_window)

    def render_variants_frame(self, looks, parent_prim, ignore_widget=False):
        """
        It renders the variants frame, it contains all the variants of the current prim

        :param parent_prim: The prim that contains the variants
        """
        # Checking if any of the variants are active.
        is_variants_active = False
        all_variants = self.get_all_materials_variants(looks)
        for variant_prim in all_variants:
            is_active_attr = variant_prim.GetAttribute("MMEisActive")
            if is_active_attr:
                if is_active_attr.Get():
                    is_variants_active = True
                    break
        # Checking if the is_variants_active variable is True or False. If it is True, then the active_status variable
        # is set to an empty string. If it is False, then the active_status variable is set to ' (Active)'.
        active_status = '' if is_variants_active else ' (Active)'

        # Creating a frame in the UI.
        if not self.variants_frame_original:
            self.variants_frame_original = ui.Frame(
                name="variants_frame_original",
                identifier="variants_frame_original"
            )
        with self.variants_frame_original:
            with ui.CollapsableFrame(f"Original{active_status}",
                                     height=ui.Pixel(10),
                                     collapsed=is_variants_active):
                with ui.VStack():
                    ui.Label("Your original, unmodified materials. Cannot be deleted.", name="variant_label", height=40)
                    if is_variants_active:
                        with ui.HStack():
                            ui.Button(
                                "Enable",
                                name="variant_button",
                                clicked_fn=lambda: self.enable_variant(None, looks, parent_prim))

        if not self.variants_frame:
            self.variants_frame = ui.Frame(name="variants_frame", identifier="variants_frame")
        with self.variants_frame:
            with ui.VStack(height=ui.Pixel(10)):
                for variant_prim in all_variants:
                    # Creating a functions that will be called later in this loop.
                    prim_name = variant_prim.GetName()
                    prim_path = variant_prim.GetPath()

                    is_active_attr = variant_prim.GetAttribute("MMEisActive")
                    if is_active_attr:
                        # Checking if the attribute is_active_attr is active.
                        is_active = is_active_attr.Get()
                        active_status = ' (Active)' if is_active else ''
                        with ui.CollapsableFrame(f"{variant_prim.GetName()}{active_status}",
                                                 height=ui.Pixel(10),
                                                 collapsed=not is_active):
                            with ui.VStack(height=ui.Pixel(10)):
                                with ui.HStack():
                                    if not active_status:
                                        ui.Button(
                                            "Enable",
                                            name="variant_button",
                                            clicked_fn=lambda p_name=prim_name: self.enable_variant(
                                                p_name,
                                                looks,
                                                parent_prim
                                            ))
                                        ui.Button(
                                            "Delete",
                                            name="variant_button",
                                            clicked_fn=lambda p_path=prim_path: self.delete_variant(
                                                p_path,
                                                looks,
                                                parent_prim
                                            ))
                                    else:
                                        label_text = "This variant is enabled.\nMake changes to the active materials" \
                                            "from above to edit this variant.\nAll changes will be saved automatically."
                                        ui.Label(label_text, name="variant_label", height=40)
        if not ignore_widget and self.get_enable_viewport_ui():
            if self._widget_info_viewport:
                self._widget_info_viewport.destroy()
                self._widget_info_viewport = None
            if len(all_variants) > 0:
                # Get the active (which at startup is the default Viewport)
                viewport_window = get_active_viewport_window()

                # Issue an error if there is no Viewport
                if not viewport_window:
                    carb.log_warn(f"No Viewport Window to add {self.ext_id} scene to")
                    self._widget_info_viewport = None
                    return

                # Build out the scene
                self._widget_info_viewport = WidgetInfoScene(
                    viewport_window,
                    self.ext_id,
                    all_variants=all_variants,
                    enable_variant=self.enable_variant,
                    looks=looks,
                    check_visibility=self.get_enable_viewport_ui,
                    parent_prim=parent_prim
                )

        return self.variants_frame_original, self.variants_frame

    def get_all_children_of_prim(self, prim):
        """
        It takes a prim as an argument and returns a list of all the prims that are children of that prim

        :param prim: The prim you want to get the children of
        :return: A list of all the children of the prim.
        """
        children = []
        for child in prim.GetChildren():
            children.append(child)
            children.extend(self.get_all_children_of_prim(child))
        return children

    def render_current_materials_frame(self, prim):
        """
        It loops through all meshes of the selected prim, gets all materials that are binded to the mesh, and then loops
        through all materials and renders a button for each material

        :param prim: The prim to get all children of
        :return: The return value is a ui.Frame object.
        """
        all_meshes = []
        all_mat_paths = []
        # Get all meshes
        for mesh in self.get_all_children_of_prim(prim):
            if mesh.GetTypeName() == "Mesh":
                material_paths = mesh.GetRelationship('material:binding').GetTargets()
                all_meshes.append({"mesh": mesh, "material_paths": material_paths})
                for original_material_prim_path in material_paths:
                    all_mat_paths.append(original_material_prim_path)
        materials_quantity = len(list(dict.fromkeys(all_mat_paths)))
        processed_materials = []
        scrolling_frame_height = ui.Percent(80)
        materials_column_count = 1
        if materials_quantity < 2:
            scrolling_frame_height = ui.Percent(50)
        elif materials_quantity < 4:
            scrolling_frame_height = ui.Percent(70)
        elif materials_quantity > 6:
            materials_column_count = 2
            scrolling_frame_height = ui.Percent(100)

        if not self.materials_frame:
            self.materials_frame = ui.Frame(name="materials_frame", identifier="materials_frame")

        with self.materials_frame:
            with ui.ScrollingFrame(height=scrolling_frame_height):
                with ui.VGrid(column_count=materials_column_count, height=ui.Pixel(10)):
                    material_counter = 1
                    # loop through all meshes
                    for mesh_data in all_meshes:
                        def sl_mat_fn(mesh_path=mesh_data["mesh"].GetPath()):
                            return self.select_material(mesh_path)
                        # Get currently binded materials for the current mesh
                        current_material_prims = mesh_data["material_paths"]
                        # Loop through all binded materials paths
                        for original_material_prim_path in current_material_prims:
                            if original_material_prim_path in processed_materials:
                                continue
                            # Get the material prim from path
                            original_material_prim = self.stage.GetPrimAtPath(original_material_prim_path)
                            if not original_material_prim:
                                continue
                            with ui.HStack():
                                if materials_column_count == 1:
                                    ui.Spacer(height=10, width=10)
                                ui.Label(
                                    f"{material_counter}.",
                                    name="material_counter",
                                    width=20 if materials_column_count == 1 else 50,
                                )
                                ui.Image(
                                    height=24,
                                    width=24,
                                    name="material_preview",
                                    fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT
                                )
                                if materials_column_count == 1:
                                    ui.Spacer(height=10, width=10)
                                ui.Label(
                                    original_material_prim.GetName(),
                                    elided_text=True,
                                    name="material_name"
                                )
                                ui.Button(
                                    "Select",
                                    name="variant_button",
                                    width=ui.Percent(30),
                                    clicked_fn=sl_mat_fn,
                                )
                            material_counter += 1
                            processed_materials.append(original_material_prim_path)
                    if len(all_mat_paths) == 0:
                        ui.Label(
                            "No materials were found. Please make sure that the selected model is valid.",
                            name="main_hint",
                            height=30
                        )
                    ui.Spacer(height=10)
        return self.materials_frame

    def render_objectlevel_frame(self, prim):
        """
        It renders a frame with a list of all the variants of a given object, and a list of all the materials of the
        currently active variant.

        :param prim: The prim that is currently selected in the viewport
        :return: The main_frame is being returned.
        """
        if not prim:
            return
        looks = prim.GetPrimAtPath("Looks")

        if self.variants_frame:
            self.variants_frame = None
        if self.variants_frame_original:
            self.variants_frame_original = None
        if self.materials_frame:
            self.materials_frame = None

        if not self.main_frame:
            self.main_frame = ui.Frame(name="main_frame", identifier="main_frame")
        with self.main_frame:
            with ui.VStack(style=_style):
                with ui.HStack(height=ui.Pixel(10), name="label_container"):
                    ui.Spacer(width=10)
                    ui.Label(prim.GetName(), name="main_label", height=ui.Pixel(10))
                ui.Spacer(height=6)
                ui.Separator(height=6)
                ui.Spacer(height=10)

                with ui.HStack(height=ui.Pixel(30)):
                    ui.Spacer(width=10)
                    ui.Label("Active materials", name="secondary_label")

                self.render_current_materials_frame(prim)
                with ui.HStack(height=ui.Pixel(30)):
                    ui.Spacer(width=10)
                    ui.Label("All variants", name="secondary_label")
                with ui.ScrollingFrame():
                    with ui.VStack():
                        self.render_variants_frame(looks, prim)
                ui.Spacer(height=10)
                ui.Button(
                    "Add new variant",
                    height=30,
                    clicked_fn=lambda: self.add_variant(looks, prim),
                    alignment=ui.Alignment.CENTER_BOTTOM,
                    tooltip="Create a new variant, based on the current look",
                )

    def open_scene_settings(self):
        """
        If the settings window is not open, render the settings layout, set the settings window to open, and then
        show the settings window. If the settings window is open, render the active objects frame, and then show
        the settings window
        """
        if not self.is_settings_open:
            self.render_scene_settings_layout(dock_in=True)
            self.is_settings_open = True

        else:
            self.render_active_objects_frame()
        ui.Workspace.show_window(self.SCENE_SETTINGS_WINDOW_NAME, True)
        scene_settings_window = ui.Workspace.get_window(self.SCENE_SETTINGS_WINDOW_NAME)
        ui.WindowHandle.focus(scene_settings_window)

    def render_scenelevel_frame(self):
        """
        It creates a frame with a hint and a button to open the settings window.
        :return: The main_frame is being returned.
        """
        if not self.main_frame:
            self.main_frame = ui.Frame(name="main_frame", identifier="main_frame")
        with self.main_frame:
            with ui.VStack(style=_style):
                ui.Spacer()
                with ui.VStack():
                    ui.Label("Please select any object to see its materials", name="main_hint", height=30)
                    ui.Label("or", name="main_hint_small", height=10)
                    ui.Spacer(height=5)
                    with ui.HStack(height=ui.Pixel(10)):
                        ui.Spacer()
                        ui.Button(
                            "Open settings",
                            height=20,
                            width=150,
                            name="open_mme_settings",
                            clicked_fn=self.open_scene_settings,
                        )
                        ui.Spacer()
                ui.Spacer()
        return self.main_frame

    def render_default_layout(self, prim=None):
        """
        It's a function that renders a default layout for the UI

        :param prim: The prim that is selected in the viewport
        """
        if self.main_frame:
            self.main_frame = None
        if self.variants_frame:
            self.variants_frame = None
        if self.variants_frame_original:
            self.variants_frame_original = None
        if self._window:
            self._window.destroy()
            self._window = None

        self._window = ui.Window(self.WINDOW_NAME, width=300, height=300)
        with self._window.frame:
            if not prim:
                self.render_scenelevel_frame()
            else:
                self.render_objectlevel_frame(prim)

    # SCENE SETTINGS
    def is_MME_exists(self, prim):
        """
        A recursive method that checks if the prim has a MME prim in its hierarchy

        :param prim: The prim to check
        :return: A boolean value.
        """
        for child in prim.GetChildren():
            if child.GetName() == "Looks":
                if child.GetPrimAtPath("MME"):
                    return True
                else:
                    return False
            if self.is_MME_exists(child):
                return True
        return False

    def get_mme_valid_objects_on_stage(self):
        """
        Returns a list of valid objects on the stage.
        """
        if not self.stage:
            return []
        valid_objects = []
        default_prim = self.stage.GetDefaultPrim()
        # Get all objects and check if it has Looks folder
        for obj in default_prim.GetAllChildren():
            if obj:
                if self.is_MME_exists(obj):
                    valid_objects.append(obj)
        return valid_objects

    def select_prim(self, prim_path):
        """
        It selects the prim at the given path, shows the property window, and focuses it

        :param prim_path: The path to the prim you want to select
        """
        self.ignore_settings_update = True
        omni.kit.commands.execute(
            'SelectPrimsCommand',
            old_selected_paths=[],
            new_selected_paths=[str(prim_path), ],
            expand_in_stage=True
        )
        ui.Workspace.show_window(self.WINDOW_NAME, True)
        property_window = ui.Workspace.get_window(self.WINDOW_NAME)
        ui.WindowHandle.focus(property_window)
        self.ignore_settings_update = False

    def check_stage(self):
        """
        It gets the current stage from the USD context
        """
        if not hasattr(self, "stage") or not self.stage:
            self._usd_context = omni.usd.get_context()
            self.stage = self._usd_context.get_stage()

    def set_enable_viewport_ui(self, value, create_only=False):
        """
        It checks if the attribute for showing viewport ui exists, under the DefaultPrim
        if it doesn't, it creates it, but if it does, it changes the value instead

        :param value: True or False
        :param create_only: If True, the attribute will only be created if it doesn't exist,
        defaults to False (optional)
        :return: The return value is the value of the attribute.
        """
        self.check_stage()
        if not self.stage:
            return
        # Get DefaultPrim from Stage
        default_prim = self.stage.GetDefaultPrim()
        # Get attribute from DefaultPrim called "MMEEnableViewportUI"
        attribute = default_prim.GetAttribute("MMEEnableViewportUI")
        attribute_path = attribute.GetPath()
        # check if attribute exists
        if not attribute:
            # if not, create it
            omni.kit.commands.execute(
                'CreateUsdAttributeOnPath',
                attr_path=attribute_path,
                attr_type=Sdf.ValueTypeNames.Bool,
                custom=True,
                attr_value=value,
                variability=Sdf.VariabilityVarying
            )
        else:
            if attribute.Get() == value or create_only:
                return
            omni.kit.commands.execute(
                'ChangeProperty',
                prop_path=attribute_path,
                value=value,
                prev=not value,
            )

    def get_enable_viewport_ui(self):
        """
        Get the value of the "MMEEnableViewportUI" attribute from the DefaultPrim of the Stage.
        :return: The value of the attribute.
        """
        self.check_stage()
        if not self.stage:
            return
        # Get DefaultPrim from Stage
        default_prim = self.stage.GetDefaultPrim()
        # Get attribute from DefaultPrim called "MMEEnableViewportUI"
        attribute = default_prim.GetAttribute("MMEEnableViewportUI")
        if attribute:
            return attribute.Get()
        else:
            return True  # Attribute was not created yet, so we return True as default

    def render_active_objects_frame(self, valid_objects=None):
        """
        It creates a UI frame with a list of buttons that select objects in the scene

        :param valid_objects: a list of objects that have variants
        :return: The active_objects_frame is being returned.
        """
        if not valid_objects:
            valid_objects = self.get_mme_valid_objects_on_stage()
        objects_quantity = len(valid_objects)
        objects_column_count = 1
        if objects_quantity > 6:
            objects_column_count = 2
        if not self.active_objects_frame:
            self.active_objects_frame = ui.Frame(name="active_objects_frame", identifier="active_objects_frame")
        with self.active_objects_frame:
            with ui.VGrid(column_count=objects_column_count):
                material_counter = 1
                # loop through all meshes
                for prim in valid_objects:
                    if not prim:
                        continue
                    with ui.HStack():
                        if objects_column_count == 1:
                            ui.Spacer(height=10, width=10)
                        ui.Label(
                            f"{material_counter}.",
                            name="material_counter",
                            width=20 if objects_column_count == 1 else 50,
                        )
                        if objects_column_count == 1:
                            ui.Spacer(height=10, width=10)
                        ui.Label(
                            prim.GetName(),
                            elided_text=True,
                            name="material_name"
                        )
                        ui.Button(
                            "Select",
                            name="variant_button",
                            width=ui.Percent(30),
                            clicked_fn=lambda mesh_path=prim.GetPath(): self.select_prim(mesh_path),
                        )
                        material_counter += 1
                if objects_quantity == 0:
                    ui.Label(
                        "No models with variants were found.",
                        name="main_hint",
                        height=30
                    )
                ui.Spacer(height=10)
        return self.active_objects_frame

    def render_scene_settings_layout(self, dock_in=False):
        """
        It renders a window with a list of objects in the scene that have variants and some settings.
        Called only once, all interactive elements are updated through the frames.
        """
        valid_objects = self.get_mme_valid_objects_on_stage()
        if self._window_scenemanager:
            self._window_scenemanager.destroy()
            self._window_scenemanager = None
        self._window_scenemanager = ui.Window(self.SCENE_SETTINGS_WINDOW_NAME, width=300, height=300)
        if dock_in:
            self._window_scenemanager.deferred_dock_in(self.WINDOW_NAME)
        if self.active_objects_frame:
            self.active_objects_frame = None
        with self._window_scenemanager.frame:
            with ui.VStack(style=_style):
                with ui.HStack(height=ui.Pixel(10), name="label_container"):
                    ui.Spacer(width=10)
                    ui.Label(self.SCENE_SETTINGS_WINDOW_NAME, name="main_label", height=ui.Pixel(10))
                ui.Spacer(height=6)
                ui.Separator(height=6)
                ui.Spacer(height=10)
                with ui.HStack(height=ui.Pixel(30)):
                    ui.Spacer(width=10)
                    ui.Label("Models with variants in your scene", name="secondary_label")
                    ui.Spacer(height=40)
                with ui.ScrollingFrame(height=ui.Pixel(100)):
                    self.render_active_objects_frame(valid_objects)
                ui.Spacer(height=10)
                with ui.HStack(height=ui.Pixel(30)):
                    ui.Spacer(width=10)
                    ui.Label("Settings", name="secondary_label")
                ui.Spacer(height=10)
                ui.Separator(height=6)
                with ui.ScrollingFrame():
                    with ui.VStack():
                        ui.Spacer(height=5)
                        with ui.HStack(height=20):
                            ui.Spacer(width=ui.Percent(5))
                            ui.Label("Enable viewport widget rendering:", width=ui.Percent(70))
                            ui.Spacer(width=ui.Percent(10))
                            # Creating a checkbox and setting the value to the value of the get_enable_viewport_ui()
                            # function.
                            self.enable_viewport_ui = ui.CheckBox(width=ui.Percent(15))
                            self.enable_viewport_ui.model.set_value(self.get_enable_viewport_ui())
                            self.enable_viewport_ui.model.add_value_changed_fn(
                                lambda value: self.set_enable_viewport_ui(value.get_value_as_bool())
                            )
                        ui.Spacer(height=10)
                        ui.Separator(height=6)
