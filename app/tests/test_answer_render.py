"""{{img:N}} 마커 분할. Streamlit 없이 순수 함수만 검사한다."""
import answer_render as ar
from rag import ImageRef

MAP = {1: ImageRef("p/1.png", "하나"), 2: ImageRef("p/2.png", "둘")}


def test_split_text_without_markers_is_single_text_part():
    assert ar.split_markers("그냥 글", MAP) == [("text", "그냥 글")]


def test_split_alternates_text_and_images_in_order():
    parts = ar.split_markers("1. 클릭 {{img:1}}\n2. 저장 {{img:2}}", MAP)
    assert parts == [
        ("text", "1. 클릭 "),
        ("image", MAP[1]),
        ("text", "\n2. 저장 "),
        ("image", MAP[2]),
    ]


def test_split_drops_out_of_range_marker_and_logs(capsys):
    parts = ar.split_markers("앞 {{img:9}} 뒤", MAP)
    assert parts == [("text", "앞 "), ("text", " 뒤")]
    assert "img:9" in capsys.readouterr().err


def test_split_handles_marker_at_edges_and_empty_map():
    assert ar.split_markers("{{img:1}}", MAP) == [("image", MAP[1])]
    assert ar.split_markers("{{img:1}} 끝", {}) == [("text", " 끝")]
    assert ar.split_markers("", MAP) == []


def test_valid_markers_keeps_order_and_repeats_but_not_out_of_range():
    assert ar.valid_markers("{{img:2}} a {{img:1}} b {{img:2}} c {{img:7}}", MAP) == [2, 1, 2]
    assert ar.valid_markers("마커 없음", MAP) == []


def test_not_grounded_message_is_fixed():
    assert ar.NOT_GROUNDED_MESSAGE == "제공된 문서에서 확인되지 않습니다."
