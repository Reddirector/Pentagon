import base64
import io
from PIL import Image

from app.services.image_generator import (
    enhance_prompt,
    _generate_fallback_diagram,
    resolve_image_bytes,
)
from app.services.document_builder import build_document, parse_markdown


def test_enhance_prompt():
    prompt = "a cute red panda eating bamboo"
    enhanced = enhance_prompt(prompt, style="photorealistic")
    assert "a cute red panda eating bamboo" in enhanced
    assert len(enhanced) > len(prompt)


def test_fallback_diagram_generation():
    bytes_data, mime = _generate_fallback_diagram("System Architecture", width=800, height=450)
    assert len(bytes_data) > 1000
    assert mime == "image/jpeg"
    img = Image.open(io.BytesIO(bytes_data))
    assert img.size == (800, 450)



def test_resolve_image_bytes_data_uri():
    img = Image.new("RGB", (64, 64), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"

    result = resolve_image_bytes(data_uri)
    assert result is not None
    data, mime = result
    assert mime == "image/png"
    assert len(data) == len(buf.getvalue())


def test_parse_markdown_image():
    md = "# Overview\n\n![Architecture Diagram](generate:microservice flow)\n\nEnd note."
    blocks = parse_markdown(md)
    kinds = [b.kind for b in blocks]
    assert "image" in kinds
    img_block = next(b for b in blocks if b.kind == "image")
    assert img_block.text == "Architecture Diagram"
    assert img_block.lines == ["generate:microservice flow"]


def test_build_documents_with_embedded_image():
    # Create small test 1x1 png as data URI
    img = Image.new("RGB", (100, 80), color=(16, 185, 129))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"

    content = f"# System Report\n\nExecutive summary text.\n\n![Architecture Flow]({data_uri})\n\n| Component | Status |\n|---|---|\n| API | Operational |\n"

    # 1. DOCX
    docx_bytes = build_document("docx", "System Report", content)
    assert len(docx_bytes) > 2000

    # 2. PDF
    pdf_bytes = build_document("pdf", "System Report", content)
    assert len(pdf_bytes) > 2000
    assert pdf_bytes.startswith(b"%PDF")

    # 3. PPTX
    pptx_bytes = build_document("pptx", "System Report", content)
    assert len(pptx_bytes) > 2000

    # 4. HTML
    html_bytes = build_document("html", "System Report", content)
    html_str = html_bytes.decode("utf-8")
    assert "<figure" in html_str
    assert f"data:image/png;base64,{b64}" in html_str
    assert "Figure: Architecture Flow" in html_str
