import numpy as np
from typing import Optional

from .template_ocr import TemplateOCR


class OCRReader:
    def __init__(
        self,
        template_dir: Optional[str] = None,
        template_threshold: float = 0.7,
    ):
        self._template_ocr: Optional[TemplateOCR] = None
        if template_dir:
            self._template_ocr = TemplateOCR(template_dir, template_threshold)
        self.last_color = "unknown"
        self.last_raw_text = ""

    def read_time(self, image: np.ndarray) -> Optional[int]:
        if self._template_ocr is None:
            return None
        result = self._template_ocr.read_time(image)
        self.last_raw_text = self._template_ocr.last_raw_text
        self.last_color = self._template_ocr.last_color
        return result
