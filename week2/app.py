"""Streamlit interface for point-based PBL measurement on dental X-rays."""

from functools import partial
from io import BytesIO
from pathlib import Path

from PIL import Image
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

from image_processing import (
    annotate_image,
    ansh_clahe,
    enhance_contrast,
    fit_for_display,
)
from pbl_calculator import calculate_tooth_pbl
from repeatability import (
    POINT_NAMES,
    make_measurement_row,
    read_measurements,
    save_measurement,
    summarize_repeatability,
)


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = PROJECT_DIR / "sample_xrays"
MEASUREMENTS_PATH = PROJECT_DIR / "measurements.csv"
POINT_LABELS = {
    "mesial_cej": "M-CEJ",
    "mesial_bone_crest": "M-Crest",
    "mesial_root_tip": "M-Tip",
    "distal_cej": "D-CEJ",
    "distal_bone_crest": "D-Crest",
    "distal_root_tip": "D-Tip",
}
POINT_INSTRUCTIONS = {
    "mesial_cej": "Click the mesial CEJ",
    "mesial_bone_crest": "Click the mesial bone crest",
    "mesial_root_tip": "Click the mesial root tip",
    "distal_cej": "Click the distal CEJ",
    "distal_bone_crest": "Click the distal bone crest",
    "distal_root_tip": "Click the distal root tip",
}
READING_COLUMN_CONFIG = {
    "timestamp_utc": "Timestamp (UTC)",
    "observer": "Reader",
    "round": "Reading session",
    "image_id": "Image ID",
    "image_width": "Image width",
    "image_height": "Image height",
    "tooth_id": "Tooth ID",
    "mesial_pbl": "Mesial PBL",
    "distal_pbl": "Distal PBL",
    "worst_side": "Worse side",
    "worst_pbl": "Worst PBL",
    "stage": "Stage",
}


def reset_points() -> None:
    """Clear placed landmarks and recreate the click component."""
    st.session_state.measurement_points = {}
    st.session_state.click_epoch = st.session_state.get("click_epoch", 0) + 1


def undo_last_point() -> None:
    """Remove the most recently placed landmark without a second rerun."""
    points = st.session_state.get("measurement_points", {})
    if points:
        points.pop(POINT_NAMES[len(points) - 1], None)


def record_landmark(
    point_name: str, component_key: str, to_original: float
) -> None:
    """Save a component click before Streamlit redraws the page."""
    click = st.session_state.get(component_key)
    points = st.session_state.setdefault("measurement_points", {})
    if not click or point_name in points:
        return
    points[point_name] = (
        round(click["x"] / to_original),
        round(click["y"] / to_original),
    )


def change_zoom(amount: int | None = None) -> None:
    """Adjust image zoom without changing the stored landmark coordinates."""
    if amount is None:
        st.session_state.zoom_percent = 100
    else:
        current = st.session_state.get("zoom_percent", 100)
        st.session_state.zoom_percent = min(200, max(50, current + amount))


def complete_round_two() -> None:
    """Reveal the completed reading session and its agreement results."""
    if st.session_state.get("round2_done"):
        st.session_state.blind_reading = False


def load_selected_image() -> tuple[Image.Image, str] | tuple[None, None]:
    """Load either the bundled Kaggle image or a user-uploaded X-ray."""
    source = st.sidebar.radio(
        "X-ray source", ("Kaggle demo", "Upload my own"), horizontal=True
    )
    if source == "Kaggle demo":
        choices = sorted(
            path for path in SAMPLE_DIR.iterdir()
            if path.suffix.lower() in (".jpg", ".jpeg", ".png")
        )
        if not choices:
            st.error("No sample X-ray was found in sample_xrays/.")
            return None, None
        selected = st.sidebar.selectbox(
            "Demo image", choices, format_func=lambda path: path.name
        )
        return Image.open(selected), selected.name

    uploaded = st.sidebar.file_uploader(
        "Upload a dental X-ray", type=("png", "jpg", "jpeg", "tif", "tiff")
    )
    if uploaded is None:
        st.info("Upload a dental X-ray to begin.")
        return None, None
    data = uploaded.getvalue()
    return Image.open(BytesIO(data)), uploaded.name


st.set_page_config(
    page_title="Two-sided PBL X-ray Calculator", page_icon="🦷", layout="wide"
)
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] div[data-testid="stButton"] button {
        white-space: nowrap;
        font-size: 0.76rem;
        padding-left: 0.2rem;
        padding-right: 0.2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Two-sided PBL measurement on dental X-rays")
st.caption(
    "Place six landmarks directly on the image. PBL is measured on mesial and "
    "distal surfaces, and the tooth is staged from the worse surface."
)

st.sidebar.header("Image and display")
image, image_id = load_selected_image()
use_enhancement = st.sidebar.toggle(
    "Contrast enhancement (CLAHE)",
    help=(
        "Using Ansh's enhance_dataset.py" if ansh_clahe
        else "OpenCV CLAHE: clip limit 2.0, 8 × 8 tile grid."
    ),
)
blind_reading = st.sidebar.toggle(
    "Blind reading mode",
    key="blind_reading",
    help=(
        "Hide the calculated PBL, stage, saved readings, and agreement while "
        "placing landmarks. Readings can still be saved. Completing Round 2 "
        "turns this mode off and reveals the results."
    ),
)

if "zoom_percent" not in st.session_state:
    st.session_state.zoom_percent = 100
st.sidebar.caption(f"X-ray zoom: {st.session_state.zoom_percent}%")
zoom_out, zoom_reset, zoom_in = st.sidebar.columns(3)
zoom_out.button(
    "−",
    on_click=change_zoom,
    args=(-25,),
    disabled=st.session_state.zoom_percent <= 50,
    help="Zoom out",
    width="stretch",
)
zoom_reset.button(
    "Reset",
    on_click=change_zoom,
    help="Reset to 100%",
    width="stretch",
)
zoom_in.button(
    "＋",
    on_click=change_zoom,
    args=(25,),
    disabled=st.session_state.zoom_percent >= 200,
    help="Zoom in",
    width="stretch",
)

if image is None:
    st.stop()

display_image = fit_for_display(image)
# Points are kept in original image pixels; the display copy is usually smaller.
display_scale = display_image.width / image.width
image_token = f"{image_id}:{display_image.width}x{display_image.height}"
if st.session_state.get("image_token") != image_token:
    st.session_state.image_token = image_token
    reset_points()

if "measurement_points" not in st.session_state:
    reset_points()
points: dict[str, tuple[int, int]] = st.session_state.measurement_points

if use_enhancement:
    display_image = enhance_contrast(display_image)
display_points = {
    name: (x * display_scale, y * display_scale)
    for name, (x, y) in points.items()
}
annotated_image = annotate_image(display_image, display_points, POINT_LABELS)
zoom_scale = st.session_state.zoom_percent / 100
zoomed_image = annotated_image.resize(
    (
        round(annotated_image.width * zoom_scale),
        round(annotated_image.height * zoom_scale),
    ),
    Image.Resampling.LANCZOS,
)

st.sidebar.header("Landmarks")
undo_column, reset_column = st.sidebar.columns(2)
undo_column.button(
    "Undo",
    disabled=not points,
    on_click=undo_last_point,
    width="stretch",
)
reset_column.button(
    "Reset",
    disabled=not points,
    on_click=reset_points,
    width="stretch",
)

for index, point_name in enumerate(POINT_NAMES, start=1):
    if point_name in points:
        marker = "✓"
    elif index == len(points) + 1:
        marker = "→"
    else:
        marker = "·"
    st.sidebar.write(f"{marker} {index}. {POINT_LABELS[point_name]}")

image_column, results_column = st.columns((3, 1), gap="large")
with image_column:
    if len(points) < len(POINT_NAMES):
        next_name = POINT_NAMES[len(points)]
        st.info(f"Step {len(points) + 1} of 6 — {POINT_INSTRUCTIONS[next_name]}")
        to_original = zoom_scale * display_scale
        component_key = (
            f"xray-click-{image_token}-{use_enhancement}-"
            f"{st.session_state.zoom_percent}-{st.session_state.click_epoch}"
        )
        streamlit_image_coordinates(
            zoomed_image,
            width=zoomed_image.width,
            key=component_key,
            image_format="JPEG",
            jpeg_quality=90,
            cursor="crosshair",
            on_click=partial(
                record_landmark, next_name, component_key, to_original
            ),
        )
    else:
        st.success("All six landmarks are placed. Use Undo to adjust the last one.")
        st.image(zoomed_image, width=zoomed_image.width)

result = None
with results_column:
    st.subheader("Result")
    if len(points) < len(POINT_NAMES):
        st.write("Complete all six landmarks to calculate PBL.")
    else:
        try:
            result = calculate_tooth_pbl(
                points["mesial_cej"],
                points["mesial_bone_crest"],
                points["mesial_root_tip"],
                points["distal_cej"],
                points["distal_bone_crest"],
                points["distal_root_tip"],
            )
        except ValueError as error:
            st.error(str(error))
        else:
            if blind_reading:
                st.info(
                    "Blind reading mode is active. PBL and stage are calculated "
                    "for saving but hidden until the mode is turned off."
                )
            else:
                st.metric("Mesial PBL", f"{result.mesial_pbl:.1f}%")
                st.metric("Distal PBL", f"{result.distal_pbl:.1f}%")
                st.metric(
                    "Tooth stage",
                    result.stage,
                    help=(
                        "Worst surface: "
                        f"{result.worst_side} ({result.worst_pbl:.1f}%)"
                    ),
                )
                st.write(
                    f"Worse surface: **{result.worst_side}** "
                    f"at **{result.worst_pbl:.1f}%**"
                )

st.divider()
st.subheader("Reading record")
st.write(
    "Save the current tooth assessment as a reading record. Use Round 1 for "
    "an initial reading; add a blinded Round 2 with the same image and tooth "
    "ID when assessing intra-reader repeatability."
)
form_column, saved_column = st.columns((1, 2), gap="large")
with form_column:
    observer = st.text_input("Reader", value="Lucia")
    round_name = st.selectbox("Reading session", ("Round 1", "Round 2"))
    tooth_id = st.text_input("Tooth ID", placeholder="e.g. img1-T1")
    if st.button(
        "Save reading", type="primary", disabled=result is None,
        width="stretch",
    ):
        try:
            row = make_measurement_row(
                observer=observer,
                round_name=round_name,
                image_id=image_id,
                tooth_id=tooth_id,
                image_size=image.size,
                points=points,
                mesial_pbl=result.mesial_pbl,
                distal_pbl=result.distal_pbl,
                worst_side=result.worst_side,
                worst_pbl=result.worst_pbl,
                stage=result.stage,
            )
            save_measurement(MEASUREMENTS_PATH, row)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Reading saved to measurements.csv")

rows = read_measurements(MEASUREMENTS_PATH)

with saved_column:
    # Keep this widget mounted for the whole of Round 2. If it is only drawn
    # while blind mode is active, Streamlit removes its state on the next
    # interaction and hides the revealed summary again.
    round2_done = False
    if round_name == "Round 2":
        round2_done = st.checkbox(
            "Complete Round 2 and reveal results",
            key="round2_done",
            on_change=complete_round_two,
        )
        if round2_done:
            st.success("Round 2 is complete. Results are now visible for review.")
    blind = blind_reading or (round_name == "Round 2" and not round2_done)

    if blind:
        done = sum(
            r["round"] == round_name and r["observer"] == observer.strip()
            for r in rows
        )
        if blind_reading:
            st.info(
                "Blind reading mode: calculated results, earlier readings, and "
                f"agreement are hidden. {done} assessments saved in {round_name}."
            )
        else:
            st.info(
                f"Blinded Round 2: earlier readings remain hidden. "
                f"{done} assessments saved in this session."
            )
    elif rows:
        st.dataframe(
            rows,
            column_config=READING_COLUMN_CONFIG,
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No measurements saved yet.")
    if not blind and MEASUREMENTS_PATH.exists():
        st.download_button(
            "Download measurements.csv",
            MEASUREMENTS_PATH.read_bytes(),
            file_name="measurements.csv",
            mime="text/csv",
            width="stretch",
        )

if not blind:
    st.subheader("Intra-reader agreement")
    summary = summarize_repeatability(rows)
    if summary["pair_count"] == 0:
        st.info(
            "Save matching Round 1 and Round 2 readings to compare agreement."
        )
    else:
        cols = st.columns(4)
        cols[0].metric("Paired teeth", summary["pair_count"])
        cols[1].metric(
            "Mean |Δ worst PBL|",
            f"{summary['mean_absolute_pbl_change']:.1f} pp",
        )
        cols[2].metric(
            "Max |Δ worst PBL|",
            f"{summary['max_absolute_pbl_change']:.1f} pp",
        )
        cols[3].metric(
            "Stage agreement", f"{summary['stage_agreement_percent']:.0f}%"
        )

        cols = st.columns(4)
        cols[0].metric(
            "Mean |Δ mesial|",
            f"{summary['mean_absolute_mesial_change']:.1f} pp",
        )
        cols[1].metric(
            "Mean |Δ distal|",
            f"{summary['mean_absolute_distal_change']:.1f} pp",
        )
        cols[2].metric("Stage changed", summary["stage_change_count"])
        cols[3].metric("Worse side flipped", summary["worst_side_change_count"])

        st.write("**Average landmark shift between rounds** (original pixels)")
        st.dataframe(
            [
                {"landmark": POINT_LABELS[name], "mean shift (px)": round(px, 1)}
                for name, px in summary["mean_landmark_shift_px"].items()
            ],
            hide_index=True,
        )
        st.dataframe(
            summary["pairs"],
            column_config={
                "observer": "Reader",
                "image_id": "Image ID",
                "tooth_id": "Tooth ID",
            },
            hide_index=True,
            width="stretch",
        )

with st.expander("Input rules and staging limits"):
    st.markdown(
        """
        - A CEJ and root tip at the same pixel produce a clear zero-root-length error.
        - A bone crest on the crown side of the CEJ is reported as 0% PBL.
        - A bone crest projected past the root tip is flagged as an invalid placement.
        - Stage I is <15%, Stage II is 15–<33%, and ≥33% is shown as Stage III/IV.
          PBL alone cannot distinguish Stage III from Stage IV; that requires
          complexity and tooth-loss information.
        """
    )
