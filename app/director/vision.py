"""Capture one clean live overview at planning time, without streaming rendered video."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from ..director_demo import DirectorDemo


def capture_planning_view(director: DirectorDemo) -> bytes:
    viewer = director.viewer
    camera = viewer.camera
    original_camera = (camera.pos, camera.pitch, camera.yaw, camera.pivot)
    debug_flags = (
        "show_context_poses",
        "show_target_poses",
        "show_blendspace_targets",
        "show_probe_box",
        "show_actual_velocity",
        "show_input_velocity",
        "show_desired_velocity",
        "show_foot_contacts",
        "show_scene_object_target_poses",
        "show_scene_object_interaction_boxes",
    )
    original_flags = {name: getattr(director, name) for name in debug_flags}
    try:
        for name in debug_flags:
            setattr(director, name, False)
        # Public camera operations preserve the runtime's Z-up convention.
        viewer.set_camera((-18.0, -24.0, 22.0), pitch=-35.0, yaw=58.0)
        camera.look_at(np.array((0.0, 4.0, 0.5)))
        director.render()
        image = Image.fromarray(viewer.get_frame(render_ui=False).numpy())
        image.thumbnail((960, 540))
        output = BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()
    finally:
        camera.pos, camera.pitch, camera.yaw, camera.pivot = original_camera
        for name, value in original_flags.items():
            setattr(director, name, value)
