import os
import streamlit.components.v1 as components

_RELEASE = True

if _RELEASE:
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    _component_func = components.declare_component("vibe_ghost_component", path=parent_dir)
else:
    _component_func = components.declare_component("vibe_ghost_component", url="http://localhost:3001")

def vibe_ghost_component(locs, initial_id="", key=None):
    component_value = _component_func(locs=locs, initial_id=initial_id, key=key, default=None)
    return component_value
