"""Streamlit interface for the periodontal bone loss calculator."""

import matplotlib.pyplot as plt
import streamlit as st

from pbl_calculator import calculate_pbl, classify_pbl, distance


SLIDER_MIN = -10.0
SLIDER_MAX = 10.0
SLIDER_STEP = 0.1
PLOT_LIMIT = 16.0
DEFAULT_POINTS = {
    "CEJ": (0.0, 4.0),
    "Bone Crest": (1.0, 1.0),
    "Root Tip": (2.0, -6.0),
}


st.set_page_config(page_title="PBL Calculator", page_icon="🦷")
st.title("Periodontal Bone Loss Calculator")
st.caption(
    "PBL (%) = distance(CEJ → bone crest) ÷ distance(CEJ → root tip) × 100. "
    "Stages follow the 2018 AAP/EFP classification: Mild < 15%, "
    "Moderate 15–33%, Severe ≥ 33%."
)


def point_sliders(label, default_x, default_y):
    """Create X and Y sliders for one point and return its coordinates."""
    st.sidebar.subheader(label)
    x = st.sidebar.slider(
        f"{label} X",
        SLIDER_MIN,
        SLIDER_MAX,
        default_x,
        SLIDER_STEP,
        key=f"{label}_x",
    )
    y = st.sidebar.slider(
        f"{label} Y",
        SLIDER_MIN,
        SLIDER_MAX,
        default_y,
        SLIDER_STEP,
        key=f"{label}_y",
    )
    return x, y


def reset_points():
    """Restore all point sliders to their default coordinates."""
    for label, (x, y) in DEFAULT_POINTS.items():
        st.session_state[f"{label}_x"] = x
        st.session_state[f"{label}_y"] = y


st.sidebar.header("Point positions")
st.sidebar.button("Reset Points", on_click=reset_points, use_container_width=True)
cej = point_sliders("CEJ", *DEFAULT_POINTS["CEJ"])
bone_crest = point_sliders("Bone Crest", *DEFAULT_POINTS["Bone Crest"])
root_tip = point_sliders("Root Tip", *DEFAULT_POINTS["Root Tip"])

try:
    pbl = calculate_pbl(cej, bone_crest, root_tip)
except ValueError as error:
    st.error(str(error))
else:
    stage = classify_pbl(pbl)
    bone_loss_distance = distance(cej, bone_crest)
    root_length = distance(cej, root_tip)

    percentage_column, stage_column, loss_column, root_column = st.columns(4)
    percentage_column.metric("PBL Percentage", f"{pbl:.1f}%")
    stage_column.metric("Classification", stage)
    loss_column.metric("CEJ to Bone Crest", f"{bone_loss_distance:.2f}")
    root_column.metric("CEJ to Root Tip", f"{root_length:.2f}")

    # Keep the canvas and coordinate range fixed. This prevents the plot from
    # zooming and jumping while a slider is being moved.
    fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")

    # Build the tooth around its long axis so the drawing rotates with it.
    axis_x = (root_tip[0] - cej[0]) / root_length
    axis_y = (root_tip[1] - cej[1]) / root_length
    normal_x, normal_y = -axis_y, axis_x
    crown_top = (cej[0] - 2.5 * axis_x, cej[1] - 2.5 * axis_y)

    tooth_x = [
        crown_top[0] - 1.8 * normal_x,
        cej[0] - 1.2 * normal_x,
        root_tip[0],
        cej[0] + 1.2 * normal_x,
        crown_top[0] + 1.8 * normal_x,
    ]
    tooth_y = [
        crown_top[1] - 1.8 * normal_y,
        cej[1] - 1.2 * normal_y,
        root_tip[1],
        cej[1] + 1.2 * normal_y,
        crown_top[1] + 1.8 * normal_y,
    ]
    ax.fill(tooth_x, tooth_y, color="#fff4d6", edgecolor="#9c7a3c", alpha=0.7)

    # Draw the bone surface perpendicular to the long axis of the tooth.
    ax.plot(
        [
            bone_crest[0] - 2.5 * normal_x,
            bone_crest[0] + 2.5 * normal_x,
        ],
        [
            bone_crest[1] - 2.5 * normal_y,
            bone_crest[1] + 2.5 * normal_y,
        ],
        color="#8c564b",
        linewidth=3,
        alpha=0.75,
        label="Bone level",
    )

    ax.plot(
        [cej[0], bone_crest[0]],
        [cej[1], bone_crest[1]],
        color="#d62728",
        linewidth=2,
        label="CEJ to Bone Crest",
    )
    ax.plot(
        [cej[0], root_tip[0]],
        [cej[1], root_tip[1]],
        color="#1f77b4",
        linewidth=2,
        linestyle="--",
        label="CEJ to Root Tip",
    )

    points = [cej, bone_crest, root_tip]
    labels = ["CEJ", "Bone Crest", "Root Tip"]
    colors = ["#2ca02c", "#d62728", "#1f77b4"]
    for point, label, color in zip(points, labels, colors):
        ax.scatter(*point, s=90, color=color, zorder=3)
        ax.annotate(label, point, xytext=(7, 7), textcoords="offset points", weight="bold")

    ax.set_xlim(-PLOT_LIMIT, PLOT_LIMIT)
    ax.set_ylim(-PLOT_LIMIT, PLOT_LIMIT)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X coordinate")
    ax.set_ylabel("Y coordinate")
    ax.set_title("Tooth Schematic")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right")
    st.pyplot(fig, width="stretch", clear_figure=True)
    plt.close(fig)
