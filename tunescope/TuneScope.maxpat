{
    "patcher": {
        "fileversion": 1,
        "appversion": {
            "major": 9,
            "minor": 0,
            "revision": 0,
            "architecture": "x64",
            "modernui": 1
        },
        "classnamespace": "box",
        "rect": [100.0, 100.0, 1000.0, 900.0],
        "openinpresentation": 1,
        "default_fontsize": 10.0,
        "default_fontname": "Arial Bold",
        "gridsize": [8.0, 8.0],
        "devicewidth": 131.0,
        "boxes": [
            {
                "box": {
                    "id": "obj-1",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": ["signal", "signal"],
                    "patching_rect": [40.0, 40.0, 53.0, 20.0],
                    "text": "plugin~"
                }
            },
            {
                "box": {
                    "id": "obj-2",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": ["signal", "signal"],
                    "patching_rect": [40.0, 560.0, 53.0, 20.0],
                    "text": "plugout~"
                }
            },
            {
                "box": {
                    "id": "obj-3",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["signal"],
                    "patching_rect": [200.0, 110.0, 32.0, 20.0],
                    "text": "+~"
                }
            },
            {
                "box": {
                    "id": "obj-4",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["signal"],
                    "patching_rect": [200.0, 145.0, 42.0, 20.0],
                    "text": "*~ 0.5"
                }
            },
            {
                "box": {
                    "id": "obj-5",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["jit_matrix", ""],
                    "patching_rect": [200.0, 190.0, 130.0, 20.0],
                    "text": "jit.catch~ 1 @mode 0"
                }
            },
            {
                "box": {
                    "id": "obj-6",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["bang"],
                    "patching_rect": [360.0, 150.0, 68.0, 20.0],
                    "text": "qmetro 25"
                }
            },
            {
                "box": {
                    "id": "obj-7",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [360.0, 115.0, 69.0, 20.0],
                    "text": "loadmess 1"
                }
            },
            {
                "box": {
                    "id": "obj-8",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", ""],
                    "patching_rect": [200.0, 230.0, 190.0, 20.0],
                    "text": "jit.spill @plane 0 @listlength 4416"
                }
            },
            {
                "box": {
                    "id": "obj-9",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [200.0, 265.0, 86.0, 20.0],
                    "text": "prepend audio"
                }
            },
            {
                "box": {
                    "id": "obj-10",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", ""],
                    "patching_rect": [200.0, 310.0, 260.0, 20.0],
                    "saved_object_attributes": {
                        "autostart": 1,
                        "defer": 0,
                        "node_bin_path": "",
                        "npm_bin_path": "",
                        "watch": 1
                    },
                    "text": "node.script analyzer.js @autostart 1 @watch 1"
                }
            },
            {
                "box": {
                    "id": "obj-11",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": ["", "int"],
                    "patching_rect": [480.0, 190.0, 68.0, 20.0],
                    "text": "adstatus sr"
                }
            },
            {
                "box": {
                    "id": "obj-12",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [480.0, 225.0, 67.0, 20.0],
                    "text": "prepend sr"
                }
            },
            {
                "box": {
                    "border": 0,
                    "filename": "TuneScope_UI.js",
                    "id": "obj-13",
                    "maxclass": "jsui",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "parameter_enable": 0,
                    "patching_rect": [640.0, 310.0, 127.0, 164.0],
                    "presentation": 1,
                    "presentation_rect": [2.0, 4.0, 127.0, 163.75]
                }
            },
            {
                "box": {
                    "angle": 270.0,
                    "bgcolor": [0.125, 0.141, 0.18, 1.0],
                    "bordercolor": [0.0, 0.0, 0.0, 1.0],
                    "id": "obj-14",
                    "maxclass": "panel",
                    "mode": 0,
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [640.0, 520.0, 128.0, 128.0],
                    "presentation": 1,
                    "presentation_rect": [2.0, 5.0, 127.0, 164.0],
                    "proportion": 0.39,
                    "rounded": 6,
                    "saved_attribute_attributes": {
                        "bgfillcolor": {
                            "expression": "themecolor.live_lcd_bg"
                        }
                    }
                }
            },
            {
                "box": {
                    "id": "obj-15",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": ["bang"],
                    "patching_rect": [40.0, 640.0, 53.0, 20.0],
                    "text": "loadbang"
                }
            },
            {
                "box": {
                    "id": "obj-16",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["bang", "int", "int"],
                    "patching_rect": [40.0, 675.0, 78.0, 20.0],
                    "text": "live.thisdevice"
                }
            },
            {
                "box": {
                    "id": "obj-17",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [40.0, 710.0, 77.0, 20.0],
                    "text": "path live_set"
                }
            },
            {
                "box": {
                    "id": "obj-18",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["", "", ""],
                    "patching_rect": [40.0, 745.0, 54.0, 20.0],
                    "text": "live.path"
                }
            },
            {
                "box": {
                    "id": "obj-19",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [40.0, 780.0, 50.0, 20.0],
                    "text": "deferlow"
                }
            },
            {
                "box": {
                    "id": "obj-20",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 2,
                    "outlettype": ["", ""],
                    "patching_rect": [40.0, 815.0, 113.0, 20.0],
                    "saved_object_attributes": {
                        "_persistence": 0
                    },
                    "text": "live.observer tempo"
                }
            },
            {
                "box": {
                    "id": "obj-21",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [40.0, 850.0, 116.0, 20.0],
                    "text": "prepend live_tempo"
                }
            },
            {
                "box": {
                    "id": "obj-22",
                    "maxclass": "newobj",
                    "numinlets": 8,
                    "numoutlets": 8,
                    "outlettype": ["", "", "", "", "", "", "", ""],
                    "patching_rect": [640.0, 660.0, 320.0, 20.0],
                    "text": "route settempo freeze reset notation smoothing bpmswap tag"
                }
            },
            {
                "box": {
                    "id": "obj-23",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [640.0, 695.0, 99.0, 20.0],
                    "text": "prepend set tempo"
                }
            },
            {
                "box": {
                    "id": "obj-24",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [760.0, 695.0, 92.0, 20.0],
                    "text": "prepend freeze"
                }
            },
            {
                "box": {
                    "id": "obj-25",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [870.0, 695.0, 37.0, 20.0],
                    "text": "reset"
                }
            },
            {
                "box": {
                    "id": "obj-26",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [640.0, 740.0, 63.0, 20.0],
                    "saved_object_attributes": {
                        "_persistence": 0
                    },
                    "text": "live.object"
                }
            },
            {
                "box": {
                    "appearance": 4,
                    "id": "obj-27",
                    "maxclass": "live.numbox",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "parameter_mappable": 0,
                    "patching_rect": [940.0, 620.0, 48.0, 15.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [0.0],
                            "parameter_initial_enable": 1,
                            "parameter_invisible": 1,
                            "parameter_longname": "TuneScope Notation",
                            "parameter_mmax": 2.0,
                            "parameter_modmode": 0,
                            "parameter_shortname": "Notation",
                            "parameter_type": 1,
                            "parameter_unitstyle": 0
                        }
                    },
                    "varname": "notation_state"
                }
            },
            {
                "box": {
                    "id": "obj-28",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [940.0, 650.0, 106.0, 20.0],
                    "text": "prepend notation"
                }
            },
            {
                "box": {
                    "appearance": 4,
                    "id": "obj-29",
                    "maxclass": "live.numbox",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "parameter_mappable": 0,
                    "patching_rect": [940.0, 690.0, 48.0, 15.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [1.0],
                            "parameter_initial_enable": 1,
                            "parameter_invisible": 1,
                            "parameter_longname": "TuneScope Smoothing",
                            "parameter_mmax": 2.0,
                            "parameter_modmode": 0,
                            "parameter_shortname": "Smoothing",
                            "parameter_type": 1,
                            "parameter_unitstyle": 0
                        }
                    },
                    "varname": "smoothing_state"
                }
            },
            {
                "box": {
                    "id": "obj-32",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [1080.0, 780.0, 76.0, 20.0],
                    "text": "js tagger.js"
                }
            },
            {
                "box": {
                    "id": "obj-33",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [1080.0, 745.0, 76.0, 20.0],
                    "text": "prepend tag"
                }
            },
            {
                "box": {
                    "id": "obj-31",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [1080.0, 695.0, 60.0, 20.0],
                    "text": "bpmswap"
                }
            },
            {
                "box": {
                    "id": "obj-30",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [940.0, 720.0, 118.0, 20.0],
                    "text": "prepend smoothing"
                }
            }
        ],
        "lines": [
            { "patchline": { "destination": ["obj-6", 0], "source": ["obj-7", 0] } },
            { "patchline": { "destination": ["obj-5", 0], "source": ["obj-6", 0] } },
            { "patchline": { "destination": ["obj-2", 0], "source": ["obj-1", 0], "order": 0 } },
            { "patchline": { "destination": ["obj-2", 1], "source": ["obj-1", 1], "order": 0 } },
            { "patchline": { "destination": ["obj-3", 0], "source": ["obj-1", 0], "order": 1 } },
            { "patchline": { "destination": ["obj-3", 1], "source": ["obj-1", 1], "order": 1 } },
            { "patchline": { "destination": ["obj-4", 0], "source": ["obj-3", 0] } },
            { "patchline": { "destination": ["obj-5", 0], "source": ["obj-4", 0] } },
            { "patchline": { "destination": ["obj-11", 0], "source": ["obj-16", 0], "order": 1 } },
            { "patchline": { "destination": ["obj-8", 0], "source": ["obj-5", 0] } },
            { "patchline": { "destination": ["obj-9", 0], "source": ["obj-8", 0] } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-9", 0] } },
            { "patchline": { "destination": ["obj-12", 0], "source": ["obj-11", 0] } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-12", 0] } },
            { "patchline": { "destination": ["obj-13", 0], "source": ["obj-10", 0] } },
            { "patchline": { "destination": ["obj-16", 0], "source": ["obj-15", 0] } },
            { "patchline": { "destination": ["obj-17", 0], "source": ["obj-16", 0] } },
            { "patchline": { "destination": ["obj-18", 0], "source": ["obj-17", 0] } },
            { "patchline": { "destination": ["obj-19", 0], "source": ["obj-18", 1] } },
            { "patchline": { "destination": ["obj-20", 1], "source": ["obj-19", 0], "order": 1 } },
            { "patchline": { "destination": ["obj-26", 1], "source": ["obj-19", 0], "order": 0 } },
            { "patchline": { "destination": ["obj-21", 0], "source": ["obj-20", 0] } },
            { "patchline": { "destination": ["obj-13", 0], "source": ["obj-21", 0] } },
            { "patchline": { "destination": ["obj-22", 0], "source": ["obj-13", 0] } },
            { "patchline": { "destination": ["obj-23", 0], "source": ["obj-22", 0] } },
            { "patchline": { "destination": ["obj-26", 0], "source": ["obj-23", 0] } },
            { "patchline": { "destination": ["obj-24", 0], "source": ["obj-22", 1] } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-24", 0] } },
            { "patchline": { "destination": ["obj-25", 0], "source": ["obj-22", 2] } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-25", 0] } },
            { "patchline": { "destination": ["obj-27", 0], "source": ["obj-22", 3] } },
            { "patchline": { "destination": ["obj-29", 0], "source": ["obj-22", 4] } },
            { "patchline": { "destination": ["obj-28", 0], "source": ["obj-27", 0] } },
            { "patchline": { "destination": ["obj-13", 0], "source": ["obj-28", 0] } },
            { "patchline": { "destination": ["obj-30", 0], "source": ["obj-29", 0] } },
            { "patchline": { "destination": ["obj-13", 0], "source": ["obj-30", 0], "order": 1 } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-30", 0], "order": 0 } },
            { "patchline": { "destination": ["obj-31", 0], "source": ["obj-22", 5] } },
            { "patchline": { "destination": ["obj-10", 0], "source": ["obj-31", 0] } },
            { "patchline": { "destination": ["obj-33", 0], "source": ["obj-22", 6] } },
            { "patchline": { "destination": ["obj-32", 0], "source": ["obj-33", 0] } }
        ],
        "parameters": {
            "obj-27": ["TuneScope Notation", "Notation", 0],
            "obj-29": ["TuneScope Smoothing", "Smoothing", 0],
            "parameterbanks": {
                "0": {
                    "index": 0,
                    "name": "",
                    "parameters": ["-", "-", "-", "-", "-", "-", "-", "-"],
                    "buttons": ["-", "-", "-", "-", "-", "-", "-", "-"]
                }
            },
            "inherited_shortname": 1
        },
        "autosave": 0
    }
}
