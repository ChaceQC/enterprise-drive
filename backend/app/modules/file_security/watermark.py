from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from math import cos, radians, sin
from pathlib import PurePath
from uuid import UUID

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import DecodedStreamObject, DictionaryObject, FloatObject, NameObject

from app.api.errors import ApiError


@dataclass(frozen=True, slots=True)
class WatermarkedContent:
    content: bytes
    media_type: str
    file_name: str


class WatermarkRenderer:
    def render(
        self,
        *,
        content: bytes,
        mime_type: str,
        file_name: str,
        watermark_text: str,
    ) -> WatermarkedContent:
        normalized_mime = mime_type.split(";", 1)[0].strip().casefold()
        extension = PurePath(file_name).suffix.casefold()
        if normalized_mime.startswith("image/") or extension in {
            ".bmp",
            ".gif",
            ".jpeg",
            ".jpg",
            ".png",
            ".tif",
            ".tiff",
            ".webp",
        }:
            return WatermarkedContent(
                content=_watermark_image(content=content, text=watermark_text),
                media_type="image/png",
                file_name=_watermarked_name(file_name=file_name, extension=".png"),
            )
        if normalized_mime == "application/pdf" or extension == ".pdf":
            return WatermarkedContent(
                content=_watermark_pdf(content=content, text=watermark_text),
                media_type="application/pdf",
                file_name=_watermarked_name(file_name=file_name, extension=".pdf"),
            )
        raise ApiError(
            "WATERMARK_FORMAT_UNSUPPORTED",
            "当前文件格式不支持水印输出",
            status_code=422,
        )


def build_watermark_text(
    *,
    template: str | None,
    user_label: str,
    user_id: UUID | None,
    tenant_id: UUID,
    now: datetime,
) -> str:
    value = template or "CONFIDENTIAL | {user} | {timestamp}"
    replacements = {
        "{user}": user_label,
        "{user_id}": str(user_id) if user_id else "external",
        "{tenant_id}": str(tenant_id),
        "{timestamp}": now.isoformat(),
    }
    for placeholder, replacement in replacements.items():
        value = value.replace(placeholder, replacement)
    return value[:256]


def _watermark_image(*, content: bytes, text: str) -> bytes:
    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except Exception as exc:
        raise ApiError("WATERMARK_RENDER_FAILED", "图片水印生成失败", status_code=422) from exc

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = max(14, min(image.width, image.height) // 12)
    font = ImageFont.load_default(size=font_size)
    bounds = draw.textbbox((0, 0), text, font=font)
    text_width = max(int(bounds[2] - bounds[0]), 1)
    text_height = max(int(bounds[3] - bounds[1]), 1)
    step_x = int(text_width + max(80, image.width // 8))
    step_y = int(text_height + max(80, image.height // 8))
    for y in range(-image.height, image.height * 2, step_y):
        for x in range(-image.width, image.width * 2, step_x):
            draw.text((x, y), text, font=font, fill=(80, 80, 80, 72))
    rotated = overlay.rotate(30, resample=Image.Resampling.BICUBIC, expand=False)
    result = Image.alpha_composite(image, rotated).convert("RGB")
    output = BytesIO()
    result.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _watermark_pdf(*, content: bytes, text: str) -> bytes:
    ascii_text = text.encode("ascii", "replace").decode("ascii")
    try:
        writer = PdfWriter(clone_from=BytesIO(content))
        for page in writer.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            overlay = _pdf_watermark_page(
                width=width,
                height=height,
                text=ascii_text,
            )
            page.merge_page(overlay)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception as exc:
        raise ApiError("WATERMARK_RENDER_FAILED", "PDF 水印生成失败", status_code=422) from exc


def _pdf_watermark_page(*, width: float, height: float, text: str) -> PageObject:
    overlay = PageObject.create_blank_page(width=width, height=height)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        }
    )
    graphics_state = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/ExtGState"),
            NameObject("/ca"): FloatObject(0.18),
            NameObject("/CA"): FloatObject(0.18),
        }
    )
    overlay[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/FWM"): font}),
            NameObject("/ExtGState"): DictionaryObject({NameObject("/GSWM"): graphics_state}),
        }
    )
    escaped = _escape_pdf_text(text)
    angle = radians(30)
    matrix = (cos(angle), sin(angle), -sin(angle), cos(angle))
    font_size = max(18.0, min(width, height) / 12.0)
    positions = (
        (width * 0.08, height * 0.25),
        (width * 0.20, height * 0.55),
        (width * 0.32, height * 0.85),
    )
    operations = ["q /GSWM gs 0.5 g"]
    for x, y in positions:
        operations.append(
            "BT /FWM "
            f"{font_size:.2f} Tf {matrix[0]:.4f} {matrix[1]:.4f} "
            f"{matrix[2]:.4f} {matrix[3]:.4f} {x:.2f} {y:.2f} Tm "
            f"({escaped}) Tj ET"
        )
    operations.append("Q")
    stream = DecodedStreamObject()
    stream.set_data(" ".join(operations).encode("ascii"))
    overlay[NameObject("/Contents")] = stream
    return overlay


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _watermarked_name(*, file_name: str, extension: str) -> str:
    source = PurePath(file_name)
    stem = source.stem or "download"
    return f"{stem}_watermarked{extension}"
