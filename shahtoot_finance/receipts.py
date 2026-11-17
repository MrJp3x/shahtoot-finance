from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout

from .storage import MAX_RECEIPT_BYTES
from .widgets import button


def read_receipt(path: Path) -> bytes:
    with path.open("rb") as source:
        data = source.read(MAX_RECEIPT_BYTES + 1)
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError("حجم فایل رسید باید حداکثر ۱۰ مگابایت باشد.")
    decode_receipt(data)
    return data


def decode_receipt(data: bytes):
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    if bytes(reader.format()) not in {b"png", b"jpeg"}:
        raise ValueError("تصویر رسید باید در قالب PNG یا JPEG باشد.")
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 32_000_000:
        raise ValueError("اندازهٔ تصویر رسید بیش از حد بزرگ است یا فایل آسیب دیده است.")
    image = reader.read()
    if image.isNull():
        raise ValueError("تصویر رسید قابل خواندن نیست.")
    return image


def show_receipt(parent, data: bytes):
    original = QPixmap.fromImage(decode_receipt(data))
    dialog = QDialog(parent)
    dialog.setWindowTitle("تصویر رسید")
    available = dialog.screen().availableGeometry()
    width = min(800, available.width() - 48)
    height = min(720, available.height() - 96)
    dialog.resize(width, height)
    layout = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview = QLabel()
    preview.setAccessibleName("تصویر رسید پرداخت")
    scroll.setWidget(preview)
    layout.addWidget(scroll, 1)

    fitted = original
    bounds = QSize(width - 48, height - 84)
    if original.width() > bounds.width() or original.height() > bounds.height():
        fitted = original.scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def show_size(full_size):
        preview.setPixmap(original if full_size else fitted)
        preview.adjustSize()

    show_size(False)
    actions = QHBoxLayout()
    zoom = QCheckBox("نمایش در اندازهٔ اصلی")
    zoom.toggled.connect(show_size)
    actions.addWidget(zoom)
    actions.addStretch()
    close = button("بستن", "primary")
    close.clicked.connect(dialog.accept)
    actions.addWidget(close)
    layout.addLayout(actions)
    dialog.exec()
