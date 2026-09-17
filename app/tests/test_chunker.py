from chunker import Chunk, Image, chunk_html

DOC_TITLE = "콘솔 사용 가이드"
DOC_DIR = "Network/VPC"

HTML = """
<section>
<h2 id="crumb">Network &gt; VPC &gt; 콘솔 사용 가이드</h2>
<h2>서브넷</h2>
<h3>서브넷 생성</h3>
<p>왼쪽 메뉴에서 Network &gt; Subnet을 클릭합니다.</p>
<p>서브넷 생성 버튼을 클릭합니다. <img src="./images/subnet_01.png" alt="subnet_01.png"></p>
<ul><li>이름을 입력합니다.</li><li>CIDR을 입력합니다.</li></ul>
<img src="./images/subnet_02.png" alt="">
<h3>서브넷 삭제</h3>
<p>삭제할 서브넷을 선택하고 삭제를 클릭합니다.</p>
<table><tr><th>이름</th><th>설명</th></tr><tr><td>CIDR</td><td>대역</td></tr></table>
<pre>curl -X DELETE /subnets</pre>
</section>
"""


def chunks():
    return chunk_html(HTML, DOC_TITLE, DOC_DIR)


def test_breadcrumb_h2_is_metadata_not_a_section():
    assert all("Network > VPC" not in c.section_path for c in chunks())


def test_sections_follow_heading_hierarchy():
    assert [c.section_path for c in chunks()] == ["서브넷 > 서브넷 생성", "서브넷 > 서브넷 삭제"]


def test_content_starts_with_title_and_section_path():
    first = chunks()[0]
    assert first.content.startswith("콘솔 사용 가이드 > 서브넷 > 서브넷 생성\n")
    assert "왼쪽 메뉴에서 Network > Subnet을 클릭합니다." in first.content


def test_image_inside_block_uses_block_text_as_caption():
    img = chunks()[0].images[0]
    assert img == Image(path="Network/VPC/images/subnet_01.png",
                        caption="서브넷 생성 버튼을 클릭합니다.", alt="subnet_01.png")
    assert "[스크린샷 1: 서브넷 생성 버튼을 클릭합니다.]" in chunks()[0].content


def test_standalone_image_uses_previous_block_as_caption():
    img = chunks()[0].images[1]
    assert img.path == "Network/VPC/images/subnet_02.png"
    assert img.caption == "CIDR을 입력합니다."
    assert "[스크린샷 2: CIDR을 입력합니다.]" in chunks()[0].content


def test_marker_follows_its_block():
    content = chunks()[0].content
    assert content.index("서브넷 생성 버튼을 클릭합니다.") < content.index("[스크린샷 1:")
    assert content.index("[스크린샷 1:") < content.index("이름을 입력합니다.")


def test_table_and_code_are_preserved():
    second = chunks()[1]
    assert "이름 | 설명" in second.content
    assert "이름: CIDR | 설명: 대역" in second.content
    assert "[코드]\ncurl -X DELETE /subnets" in second.content
    assert second.images == []


def test_absolute_image_url_is_kept_as_is():
    html = '<section><h3>A</h3><p>본문 <img src="https://x/y.png" alt="y"></p></section>'
    assert chunk_html(html, "t", "C/S")[0].images[0].path == "https://x/y.png"


def test_long_section_splits_at_block_boundary_with_header_on_each_piece():
    paragraphs = "".join(f"<p>{'가' * 400} {i}</p>" for i in range(5))
    paragraphs += '<p>마지막 문단 <img src="./images/last.png" alt=""></p>'
    html = f"<section><h3>긴 절</h3>{paragraphs}</section>"

    result = chunk_html(html, "문서", "C/S", max_chars=1000)

    assert len(result) == 3                      # 400자 문단 2개씩 + 마지막 조각
    assert all(c.content.startswith("문서 > 긴 절\n") for c in result)
    assert all(c.section_path == "긴 절" for c in result)
    assert result[-1].images == [Image(path="C/S/images/last.png", caption="마지막 문단", alt="")]
    assert "[스크린샷 1: 마지막 문단]" in result[-1].content
    assert result[0].images == []


def test_caption_marker_is_cut_at_60_chars():
    long_text = "가" * 100
    html = f'<section><h3>A</h3><p>{long_text} <img src="./images/a.png"></p></section>'
    c = chunk_html(html, "t", "C/S")[0]
    assert f"[스크린샷 1: {'가' * 60}]" in c.content
    assert c.images[0].caption == long_text


def test_content_before_any_heading_goes_to_title_only_section():
    html = "<section><p>개요 문단</p><h3>A</h3><p>본문</p></section>"
    result = chunk_html(html, "문서", "C/S")
    assert result[0].section_path == ""
    assert result[0].content == "문서\n개요 문단"
    assert result[1].section_path == "A"


def test_empty_html_gives_no_chunks():
    assert chunk_html("<section></section>", "t", "C/S") == []


def test_image_in_empty_paragraph_uses_previous_paragraph_as_caption():
    html = '<section><h3>A</h3><p>설명 문단입니다.</p><p><img src="./images/x.png" alt="x"/></p></section>'
    c = chunk_html(html, "t", "C/S")[0]
    assert c.images == [Image(path="C/S/images/x.png", caption="설명 문단입니다.", alt="x")]
    assert c.content == "t > A\n설명 문단입니다.\n[스크린샷 1: 설명 문단입니다.]"


def test_image_in_table_cell_uses_cell_text_as_caption():
    html = ('<section><h3>A</h3><table><tr><th>항목</th><th>화면</th></tr>'
            '<tr><td>로그인 화면 <img src="./images/login.png"/></td><td>설명</td></tr></table></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert c.images[0].caption == "로그인 화면"


def test_caption_is_normalized_to_one_line():
    html = ('<section><h3>A</h3><table><tr><th>이름</th><th>값</th></tr>'
            '<tr><td>a</td><td>1</td></tr></table><img src="./images/t.png"></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert "\n" not in c.images[0].caption
    assert c.images[0].caption == "이름 | 값 이름: a | 값: 1"
    assert "[스크린샷 1: 이름 | 값 이름: a | 값: 1]" in c.content


def test_first_image_of_new_section_is_captioned_by_its_heading():
    html = ('<section><h3>이전 절</h3><p>이전 문장</p>'
            '<h3>새 절</h3><p><img src="./images/a.png"/></p><p>본문</p></section>')
    cs = chunk_html(html, "t", "C/S")
    assert cs[1].section_path == "새 절"
    assert cs[1].images[0].caption == "새 절"


def test_nested_table_in_list_item_is_serialized_separately():
    html = ('<section><h3>A</h3><ul><li>항목 설명'
            '<table><tr><th>이름</th><th>값</th></tr><tr><td>a</td><td>1</td></tr></table>'
            '</li></ul></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert "항목 설명\n이름 | 값\n이름: a | 값: 1" in c.content
    assert c.content.count("이름: a") == 1


def test_nested_pre_in_blockquote_keeps_code_marker():
    html = '<section><h3>A</h3><blockquote>참고 <pre>curl -X GET /x</pre></blockquote></section>'
    c = chunk_html(html, "t", "C/S")[0]
    assert "참고\n[코드]\ncurl -X GET /x" in c.content


def test_image_inside_nested_table_uses_cell_caption_and_list_text_is_not_duplicated():
    html = ('<section><h3>A</h3><li>설명<table><tr><td>로그인 화면 <img src="./images/l.png"/></td></tr></table></li></section>')
    c = chunk_html(html, "t", "C/S")[0]
    assert c.images[0].caption == "로그인 화면"
    assert c.content.count("로그인 화면") == 2      # 셀 텍스트 1회 + 마커 1회


def test_long_table_is_split_by_rows_with_header_repeated():
    rows = "".join(f"<tr><td>키{i}</td><td>{'값' * 60}</td></tr>" for i in range(30))
    html = f'<section><h3>표</h3><table><tr><th>이름</th><th>설명</th></tr>{rows}</table></section>'
    result = chunk_html(html, "t", "C/S", max_chars=800)
    assert len(result) >= 3
    for c in result:
        assert c.content.startswith("t > 표\n이름 | 설명\n")
        assert len(c.content) <= 800
    assert sum(c.content.count("이름: 키") for c in result) == 30


def test_header_and_marker_lines_count_toward_limit():
    body = "가" * 700
    html = f'<section><h3>절</h3><p>{body}</p><p>{body} <img src="./images/a.png"></p></section>'
    result = chunk_html(html, "t", "C/S", max_chars=1450)
    assert len(result) == 2          # 700+700 자체는 1,400 이지만 헤더·마커 줄을 더하면 넘는다


def test_missing_flag_from_crawler_attribute():
    html = '<section><h3>A</h3><p>본문 <img src="https://x/y.png" data-missing="true"></p></section>'
    img = chunk_html(html, "t", "C/S")[0].images[0]
    assert img.missing is True and img.path == "https://x/y.png"


def test_has_breadcrumb_false_keeps_heading_with_gt():
    html = '<section><h2>Network &gt; Subnet 메뉴 안내</h2><p>본문</p></section>'
    assert chunk_html(html, "t", "C/S", has_breadcrumb=False)[0].section_path == "Network > Subnet 메뉴 안내"


def test_has_breadcrumb_true_drops_first_h2_even_without_gt():
    html = '<section><h2>브레드크럼 없음</h2><h3>A</h3><p>본문</p></section>'
    result = chunk_html(html, "t", "C/S", has_breadcrumb=True)
    assert [c.section_path for c in result] == ["A"]


def test_split_table_pieces_respect_cap_including_header():
    rows = "".join(f"<tr><td>키{i}</td><td>{'값' * 60}</td></tr>" for i in range(30))
    html = f'<section><h3>표</h3><table><tr><th>이름</th><th>설명</th></tr>{rows}</table></section>'
    for c in chunk_html(html, "아주 긴 문서 제목입니다", "C/S", max_chars=800):
        assert len(c.content) <= 800, len(c.content)


def test_images_follow_their_table_rows_across_splits():
    rows = "".join(
        f"<tr><td>키{i}</td><td>{'값' * 60}{' <img src=\"./images/r%d.png\"/>' % i if i in (5, 25) else ''}</td></tr>"
        for i in range(30)
    )
    html = f'<section><h3>표</h3><table><tr><th>이름</th><th>설명</th></tr>{rows}</table></section>'
    result = chunk_html(html, "t", "C/S", max_chars=800)
    assert sum(len(c.images) for c in result) == 2
    for c in result:
        for im in c.images:
            row = im.path.rsplit("r", 1)[1].split(".")[0]          # "5" 또는 "25"
            assert f"이름: 키{row} |" in c.content, (im.path, c.section_path)
            assert f"[스크린샷 1: " in c.content
