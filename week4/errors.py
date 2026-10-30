"""Typed failures for image validation, models, datasets, and predictions."""


class PredictionError(RuntimeError):
    """Base class for Week 4 prediction failures."""


class ImageValidationError(PredictionError, ValueError):
    """An input is missing, unreadable, unsupported, or implausibly sized."""


class MissingImageError(ImageValidationError, FileNotFoundError):
    """The requested image file does not exist."""


class CorruptedImageError(ImageValidationError):
    """The input bytes cannot be decoded as an image."""


class UnsupportedImageError(ImageValidationError):
    """The decoded image has unsupported dimensions or bit depth."""


class EmptyPredictionError(PredictionError, ValueError):
    """A detector returned no complete five-landmark prediction."""


class ModelNotReadyError(PredictionError):
    """A requested learned model or checkpoint is unavailable."""


class DatasetValidationError(ValueError):
    """Annotations are incomplete, duplicated, or unsafe to evaluate."""


class LeakageError(DatasetValidationError):
    """The proposed split places the same image/patient in multiple folds."""
