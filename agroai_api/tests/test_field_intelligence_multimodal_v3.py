from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_field_intelligence_multimodal_v3_source_contract():
    extension = (ROOT / "app/services/field_intelligence_vision_extension.py").read_text()
    video = (ROOT / "app/services/field_video.py").read_text()
    vision = (ROOT / "app/services/field_vision.py").read_text()
    edge = (ROOT.parent / "cloudflare/edge-gateway/src/edge-main-v3.ts").read_text()

    assert "extract_video_audio" in extension
    assert "extract_video_frames" in extension
    assert "transcript_preview" in extension
    assert "_repair_text_inference" in extension
    assert "video_frame_count" in extension
    assert "subprocess.run" in video
    assert "shell=" not in video
    assert "visible_facts" in vision
    assert "hypotheses" in vision
    assert "pesticide concentration" in vision
    assert "@cf/meta/llama-3.2-11b-vision-instruct" in edge
    assert "degraded" in edge
