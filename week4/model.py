"""Optional pretrained ResNet-18 heatmap regressor (PyTorch is lazily imported)."""

from __future__ import annotations

from typing import Any

from week4.errors import ModelNotReadyError


def build_heatmap_model(*, pretrained: bool = True, dropout: float = 0.15) -> Any:
    """Return a five-channel heatmap model with an ImageNet-pretrained encoder."""
    try:
        import torch.nn as nn
        from torchvision.models import ResNet18_Weights, resnet18
    except ImportError as exc:
        raise ModelNotReadyError(
            "Install week4/requirements-model.txt to build the learned detector"
        ) from exc

    class ResNet18Heatmap(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            backbone = resnet18(
                weights=ResNet18_Weights.DEFAULT if pretrained else None
            )
            self.encoder = nn.Sequential(*list(backbone.children())[:-2])
            channels = [512, 256, 128, 64, 32, 16]
            blocks = []
            for incoming, outgoing in zip(channels, channels[1:]):
                blocks.extend(
                    [
                        nn.ConvTranspose2d(incoming, outgoing, 4, stride=2, padding=1),
                        nn.BatchNorm2d(outgoing),
                        nn.ReLU(inplace=True),
                        nn.Dropout2d(dropout),
                    ]
                )
            self.decoder = nn.Sequential(*blocks)
            self.head = nn.Conv2d(16, 5, 1)

        def forward(self, image):
            return self.head(self.decoder(self.encoder(image)))

    return ResNet18Heatmap()


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def to_input_tensor(pixels: Any, torch: Any) -> Any:
    """(N, H, W) uint8 crops -> ImageNet-normalized (N, 3, H, W) float tensor."""
    x = torch.as_tensor(pixels, dtype=torch.float32) / 255.0
    x = x[:, None].repeat(1, 3, 1, 1)
    mean = torch.tensor(IMAGENET_MEAN, device=x.device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, device=x.device).view(1, 3, 1, 1)
    return (x - mean) / std


def decode_heatmaps(logits: Any, torch: Any) -> tuple[Any, Any]:
    """Spatial-softmax expectation and standard deviation in heatmap pixels.

    Returns ``(coords, spread)`` with shapes (N, 5, 2) and (N, 5, 2). The
    spread is the heatmap's per-axis standard deviation, used as uncertainty.
    """
    n, k, h, w = logits.shape
    probability = torch.softmax(logits.reshape(n, k, -1), dim=2).reshape(n, k, h, w)
    ys = torch.arange(h, device=logits.device, dtype=logits.dtype)
    xs = torch.arange(w, device=logits.device, dtype=logits.dtype)
    py, px = probability.sum(dim=3), probability.sum(dim=2)
    x = (px * xs).sum(dim=2)
    y = (py * ys).sum(dim=2)
    sx = ((px * (xs - x[..., None]) ** 2).sum(dim=2)).clamp_min(1e-6).sqrt()
    sy = ((py * (ys - y[..., None]) ** 2).sum(dim=2)).clamp_min(1e-6).sqrt()
    return torch.stack((x, y), dim=2), torch.stack((sx, sy), dim=2)
