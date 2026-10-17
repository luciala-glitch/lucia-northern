"""Image preparation helpers for the PBL Streamlit app."""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Optional integration with Ansh's enhancer when it is available.
try:
    from enhance_dataset import apply_clahe as ansh_clahe
except ImportError:
    ansh_clahe = None


def grayscale_8bit(image: Image.Image) -> Image.Image:
    """Convert an image to 8-bit grayscale without clipping 16-bit X-rays."""
    if image.mode == "L":
        return image.copy()

    if image.mode in {"I", "F"} or image.mode.startswith("I;16"):
        pixels = np.asarray(image, dtype=np.float64)
        finite = np.isfinite(pixels)
        if not finite.any():
            return Image.fromarray(np.zeros(pixels.shape, dtype=np.uint8))

        minimum = float(pixels[finite].min())
        maximum = float(pixels[finite].max())
        if maximum == minimum:
            scaled = np.zeros(pixels.shape, dtype=np.uint8)
        else:
            safe_pixels = np.where(finite, pixels, minimum)
            scaled = np.clip(
                (safe_pixels - minimum) * 255.0 / (maximum - minimum),
                0,
                255,
            ).astype(np.uint8)
        return Image.fromarray(scaled)

    return image.convert("L")


def fit_for_display(image: Image.Image, max_width: int = 1100) -> Image.Image:
    """Return a proportionally resized copy suitable for point placement."""
    image = grayscale_8bit(image)
    if image.width <= max_width:
        return image
    height = round(image.height * max_width / image.width)
    return image.resize((max_width, height), Image.Resampling.LANCZOS)


def enhance_contrast(
    image: Image.Image,
    clip_limit: float = 2.0,
    tile_grid_size: tuple[int, int] = (8, 8),
) -> Image.Image:
    """CLAHE. Uses Ansh's version when available, otherwise OpenCV directly."""
    grayscale = np.asarray(grayscale_8bit(image))
    if ansh_clahe is not None:
        return Image.fromarray(ansh_clahe(grayscale))
    clahe = cv2.createCLAHE(
        clipLimit=clip_limit, tileGridSize=tile_grid_size
    )
    return Image.fromarray(clahe.apply(grayscale))


def annotate_image(
    image: Image.Image,
    points: dict[str, tuple[int, int]],
    point_labels: dict[str, str],
) -> Image.Image:
    """Overlay selected points and measurement lines on an X-ray."""
    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default()
    colors = {
        "mesial": "#00e5ff",
        "distal": "#ffb000",
    }

    for side in ("mesial", "distal"):
        names = (
            f"{side}_cej", f"{side}_bone_crest", f"{side}_root_tip"
        )
        selected = [points[name] for name in names if name in points]
        if len(selected) >= 2:
            draw.line(selected, fill=colors[side], width=3)

    for name, (x, y) in points.items():
        color = colors["mesial" if name.startswith("mesial") else "distal"]
        radius = 6
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=color,
            outline="black",
            width=2,
        )
        label = point_labels.get(name, name)
        draw.text((x + 9, y - 13), label, fill=color, font=font, stroke_width=2,
                  stroke_fill="black")
    return annotated
