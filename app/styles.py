"""NHN Cloud 디자인 토큰 기반 스타일.

색상·폰트·radius 값은 www.nhncloud.com 의 배포 스타일시트에서 추출한 실제 토큰이다.
"""

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

:root {
  /* --- NHN Cloud 색상 토큰 --- */
  --nhn-blue-100: #f4f8ff;
  --nhn-blue-150: #e9f1ff;
  --nhn-blue-200: #c8dcff;
  --nhn-blue-600: #377cf4;
  --nhn-blue-700: #125de6;
  --nhn-blue-800: #1446c8;
  --nhn-blue-900: #00338f;
  --nhn-dark:     #222734;
  --nhn-gray-100: #f8f9fa;
  --nhn-gray-150: #f3f4f6;
  --nhn-gray-200: #eceef2;
  --nhn-gray-250: #e2e5eb;
  --nhn-gray-300: #d9dde4;
  --nhn-gray-500: #a6aab4;
  --nhn-gray-700: #727781;
  --nhn-gray-800: #51565f;
  --nhn-light:    #eff4ff;
  --nhn-teal-700: #026d72;
  --nhn-coral-700:#e5482f;

  --nhn-radius-8:  0.5rem;
  --nhn-radius-12: 0.75rem;
  --nhn-radius-16: 1rem;
  --nhn-radius-30: 1.875rem;
  --nhn-shadow: 0px 4px 8px #0000000f;

  --nhn-font: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont,
              system-ui, 'Malgun Gothic', sans-serif;
}

html, body, [class*="st-"], .stMarkdown, .stChatInput textarea {
  font-family: var(--nhn-font) !important;
}

/* 기본 Streamlit 헤더 숨기고 여백 정리 */
header[data-testid="stHeader"] { background: transparent; height: 0; }
.block-container { padding-top: 1.5rem; padding-bottom: 7rem; max-width: 52rem; }

/* ---------- 브랜드 헤더 ---------- */
.nhn-header {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0 0 1rem 0; border-bottom: 1px solid var(--nhn-gray-200);
  margin-bottom: 1.5rem;
}
.nhn-logo {
  width: 34px; height: 34px; border-radius: var(--nhn-radius-8);
  background: linear-gradient(135deg, var(--nhn-blue-600), var(--nhn-blue-800));
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 15px; letter-spacing: -0.5px;
  flex-shrink: 0;
}
.nhn-title { font-size: 1.05rem; font-weight: 700; color: var(--nhn-dark); line-height: 1.3; }
.nhn-subtitle { font-size: 0.78rem; color: var(--nhn-gray-700); line-height: 1.3; }

/* ---------- 빈 화면 안내 ---------- */
.nhn-empty { text-align: center; padding: 3rem 0 2rem; }
.nhn-empty h2 {
  font-size: 1.5rem; font-weight: 700; color: var(--nhn-dark); margin: 0 0 0.5rem;
}
.nhn-empty p { color: var(--nhn-gray-700); font-size: 0.9rem; margin: 0; }
.nhn-hint { text-align:center; font-size:0.8rem; color: var(--nhn-gray-700); margin-bottom: 1rem; }

/* ---------- 채팅 버블 ---------- */
[data-testid="stChatMessage"] {
  background: transparent; padding: 0.35rem 0; gap: 0.7rem;
}
/* 역할 구분은 Streamlit 내부 testid 대신 직접 심은 마커로 한다.
   (이모지 아바타를 쓰면 testid 가 stChatMessageAvatarCustom 이 되어
    stChatMessageAvatarUser/Assistant 선택자가 매칭되지 않는다.) */
.nhn-user-marker { display: none; }

/* 사용자 메시지: 오른쪽 정렬 파란 버블 */
[data-testid="stChatMessage"]:has(.nhn-user-marker) {
  flex-direction: row-reverse;
}
[data-testid="stChatMessage"]:has(.nhn-user-marker)
  [data-testid="stChatMessageContent"] {
  background: var(--nhn-blue-700); color: #fff;
  border-radius: var(--nhn-radius-16) var(--nhn-radius-16) var(--nhn-radius-8) var(--nhn-radius-16);
  padding: 0.7rem 1rem; max-width: 80%; margin-left: auto;
}
[data-testid="stChatMessage"]:has(.nhn-user-marker)
  [data-testid="stChatMessageContent"] p,
[data-testid="stChatMessage"]:has(.nhn-user-marker)
  [data-testid="stChatMessageContent"] { color: #fff; }

/* 어시스턴트 메시지: 왼쪽 카드 */
[data-testid="stChatMessage"]:not(:has(.nhn-user-marker))
  [data-testid="stChatMessageContent"] {
  background: var(--nhn-gray-100);
  border: 1px solid var(--nhn-gray-200);
  border-radius: var(--nhn-radius-16) var(--nhn-radius-16) var(--nhn-radius-16) var(--nhn-radius-8);
  padding: 0.85rem 1.1rem; color: var(--nhn-dark);
}
[data-testid="stChatMessageContent"] table {
  font-size: 0.83rem; border-collapse: collapse; width: 100%;
}
[data-testid="stChatMessageContent"] th {
  background: var(--nhn-blue-150); color: var(--nhn-blue-900);
  font-weight: 600; text-align: left;
}
[data-testid="stChatMessageContent"] th,
[data-testid="stChatMessageContent"] td {
  border: 1px solid var(--nhn-gray-250); padding: 0.35rem 0.55rem;
}
[data-testid="stChatMessageContent"] code {
  background: var(--nhn-blue-100); color: var(--nhn-blue-800);
  padding: 0.1rem 0.3rem; border-radius: var(--nhn-radius-8); font-size: 0.85em;
}

/* ---------- 출처 칩 ---------- */
.nhn-source-chip {
  display: inline-block; margin: 0.15rem 0.25rem 0.15rem 0;
  padding: 0.2rem 0.6rem; font-size: 0.72rem; font-weight: 500;
  background: var(--nhn-blue-100); color: var(--nhn-blue-800);
  border: 1px solid var(--nhn-blue-200); border-radius: var(--nhn-radius-30);
}
.nhn-service-tag {
  display: inline-block; padding: 0.1rem 0.45rem; margin-right: 0.35rem;
  font-size: 0.68rem; font-weight: 600;
  background: var(--nhn-blue-700); color: #fff; border-radius: var(--nhn-radius-8);
}
.nhn-answer-tag { margin: 0 0 0.5rem 0; }
.nhn-source-chip a { color: inherit; text-decoration: none; }
.nhn-source-chip a:hover { text-decoration: underline; }
.nhn-section { font-size: 0.72rem; color: var(--nhn-gray-700); margin-left: 0.3rem; }
.nhn-cite-card { font-size: 0.8rem; padding: 0.3rem 0.5rem; margin-top: 0.25rem; border-left: 3px solid var(--nhn-blue-200); background: var(--nhn-blue-100); border-radius: 0 var(--nhn-radius-8) var(--nhn-radius-8) 0; }
.nhn-cite-no { color: var(--nhn-blue-800); font-weight: 700; margin-right: 0.2rem; }
.nhn-cite-card a { color: var(--nhn-blue-800); text-decoration: none; margin-left: 0.3rem; }
.nhn-cite-card a:hover { text-decoration: underline; }
.nhn-progress-chip { font-size: 0.75rem; color: var(--nhn-gray-700); padding: 0.1rem 0; }

/* ---------- 입력창 ---------- */
[data-testid="stChatInput"] {
  border: 1px solid var(--nhn-gray-300); border-radius: var(--nhn-radius-30);
  box-shadow: var(--nhn-shadow); background: #fff;
}
[data-testid="stChatInput"]:focus-within {
  border-color: var(--nhn-blue-700);
  box-shadow: 0 0 0 3px var(--nhn-blue-150);
}

/* ---------- 사이드바 ---------- */
[data-testid="stSidebar"] {
  background: var(--nhn-gray-100); border-right: 1px solid var(--nhn-gray-200);
}
[data-testid="stSidebar"] h3 {
  font-size: 0.78rem; font-weight: 700; color: var(--nhn-gray-700);
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.4rem;
}
.nhn-kv {
  display: flex; justify-content: space-between; gap: 0.5rem;
  font-size: 0.78rem; padding: 0.28rem 0; border-bottom: 1px dashed var(--nhn-gray-250);
}
.nhn-kv span:first-child { color: var(--nhn-gray-700); }
.nhn-kv span:last-child  { color: var(--nhn-dark); font-weight: 600; text-align: right; }

/* 예시 질문 버튼 */
[data-testid="stSidebar"] .stButton button,
.stButton button {
  border-radius: var(--nhn-radius-12); border: 1px solid var(--nhn-gray-300);
  background: #fff; color: var(--nhn-dark); font-size: 0.8rem;
  text-align: left; font-weight: 500; transition: all 0.12s ease;
}
.stButton button:hover {
  border-color: var(--nhn-blue-700); color: var(--nhn-blue-700);
  background: var(--nhn-blue-100);
}

/* 상태 박스 */
[data-testid="stStatusWidget"], [data-testid="stExpander"] {
  border-radius: var(--nhn-radius-12);
}
</style>
"""
