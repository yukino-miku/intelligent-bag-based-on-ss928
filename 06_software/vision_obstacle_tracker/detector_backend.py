from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DetectorBackend(ABC):
    @property
    @abstractmethod
    def names(self) -> object:
        raise NotImplementedError

    @abstractmethod
    def track(self, frame: object, **kwargs: object) -> object:
        raise NotImplementedError


class UltralyticsBackend(DetectorBackend):
    def __init__(self, model: Any) -> None:
        self.model = model

    @property
    def names(self) -> object:
        return self.model.names

    def track(self, frame: object, **kwargs: object) -> object:
        return self.model.track(frame, **kwargs)


class Ss928OmBackend(DetectorBackend):
    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        raise RuntimeError(
            "SS928 .om inference is not implemented in this repository. "
            "Exporting an OpenVINO model does not create an SS928 NPU model; "
            "a verified ModelZoo/SVP runtime adapter is still required."
        )

    @property
    def names(self) -> object:
        return {}

    def track(self, frame: object, **kwargs: object) -> object:
        raise RuntimeError("SS928 .om backend is unavailable")
