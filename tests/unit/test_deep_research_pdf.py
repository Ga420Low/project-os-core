from __future__ import annotations

import tempfile
from pathlib import Path

from project_os_core.deep_research_pdf import render_operator_reply_pdf


def test_render_operator_reply_pdf_writes_pdf_with_reader_sections() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "operator_reply.pdf"
        render_operator_reply_pdf(
            destination,
            display_title="Reponse detaillee Project OS",
            metadata={
                "channel": "discord",
                "provider": "openai",
                "model": "gpt-5",
                "message_id": "msg_123",
            },
            overview="Resume court pour lecture mobile.",
            highlights=["Point cle 1", "Point cle 2"],
            questions=["Question 1"],
            full_response="Bloc detaille.\n\nDeuxieme bloc.",
        )

        assert destination.exists()
        assert destination.read_bytes().startswith(b"%PDF")
