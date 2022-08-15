# Material Manager Extended

### About
This extension will let you quickly toggle between different materials for your static objects in your scene.

## Adding Extension

To add a this extension to your Omniverse app:
1. Go into: Extension Manager -> Gear Icon -> Extension Search Path
2. Add this as a search path: `git://github.com/Vadim-Karpenko/omniverse-material-manager-extended?branch=main&dir=exts`
3. A new window should appear alongside the Property tab:


    ![start window](readme_media/start_window.jpg)

## Restrictions
1. It may not work with vegetations and characters
2. Your object need to have the following structure:


    ![Structure example](readme_media/structure_example.svg)


    Most objects already has this structure, especially from **Nvidia Assets** tab, but in some custom cases you might need to change your object so it corresponds to the structure from above. Note: Looks folder might be even empty, it just tells the extension that this is a separate object.
    #### Example:


    ![Structure example 2](readme_media/structure_example2.jpg)


## How to use
- Navigate to your viewport and select any static object on your scene
- Once object is selected and is valid (see restrictions), the window will be changed into something simillar to this:


![step 1](readme_media/step1.jpg)
- Click **Add new variant** at the bottom of the window. A new variant called _Look_1_ will appear in the list. You can create as many as you need, and if you need to rename your variant you can do it by renaming appropiate folder in **Looks/MME/your_variant**


![step 2](readme_media/step2.jpg)
- And you will see a viewport window on top of your model. Change material or replace it completely while your variant is active


![step 3](readme_media/step3.jpg) ![step 4](readme_media/step4.jpg)


- Now you can toggle between those variants


![step 5](readme_media/step5.jpg) ![step 6](readme_media/step6.jpg)


- More complex Xform's are also supported. Which means that extension will toggle all the matterials for every mesh at once under this Xform.


![step 7](readme_media/step7.jpg)


## Linking with an Omniverse app

For a better developer experience, it is recommended to create a folder link named `app` to the *Omniverse Kit* app installed from *Omniverse Launcher*. A convenience script to use is included.

Run:

```bash
> link_app.bat
```

There is also an analogous `link_app.sh` for Linux. If successful you should see `app` folder link in the root of this repo.

If multiple Omniverse apps is installed script will select recommended one. Or you can explicitly pass an app:

```bash
> link_app.bat --app code
```

You can also just pass a path to create link to:

```bash
> link_app.bat --path "C:/Users/bob/AppData/Local/ov/pkg/create-2022.1.3"
```


## Contributing
Feel free to create a new issue if you run into any issues. Pull requests are welcomed.
