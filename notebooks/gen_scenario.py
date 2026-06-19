# ============================================================
# [v1] 터미널 시나리오 생성 확인 스크립트 (미션 타입별 다양화 검증)
# 실행: .venv/bin/python notebooks/gen_scenario.py
#   옵션(환경변수):
#     DIALOGUE=1   각 노드 NPC 대사도 LLM 생성(느림·토큰↑). 기본 0(고정대사)
#     JSON=1       원본 JSON 전체도 출력
#     X=126.9849 Y=37.5707  출발 좌표(경도/위도). 기본 종로
#     RADIUS=1500  반경(m)
# 구현일: 2026-06-19 | 작성: kys
# ============================================================
import asyncio
import json
import os
import sys
from pathlib import Path

# notebooks/ 에서 실행해도 app 패키지를 찾도록 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scenario.generator import generate_basic_scenario  # noqa: E402

# 미션 타입별 표시(아이콘 + 핵심 필드)
_LABEL = {
    "HUNT": ("👹 사냥", ["monster", "count", "boss", "weakness"]),
    "RESTORE_AR": ("🏛️ 복원", ["structure", "parts", "era"]),
    "PATH_TRACE": ("👣 추적", ["trail_clue", "steps", "find"]),
    "PHOTO_FIND": ("📸 사진", ["photo_targets", "find"]),
    "COLLECT": ("🧺 수집", ["items", "reactions"]),
    "DIALOGUE_FIND": ("💬 대화선택", ["question", "options", "answer", "find"]),
    "FIND": ("🔮 탐색", ["object", "count", "special"]),
    "QUIZ_FIND": ("❓ 퀴즈", ["q", "options", "answer", "wrong_hint", "find"]),
    "DIALOGUE_COLLECT": ("🏁 최종복원", ["villain_line", "guardian_line"]),
}


def _show_mission(m: dict, indent: str = "    "):
    mtype = m.get("type", "?")
    icon, fields = _LABEL.get(mtype, (mtype, []))
    print(f"{indent}미션: {icon}  [{mtype}]")
    print(f"{indent}지령: {m.get('order')}")
    for f in fields:
        if f in m:
            v = m[f]
            if isinstance(v, list):
                v = " · ".join(str(x) for x in v)
            print(f"{indent}  - {f}: {v}")
    hints = m.get("hints") or []
    for i, h in enumerate(hints, 1):
        print(f"{indent}  힌트{i}: {h}")


async def main():
    x = float(os.getenv("X", "126.9849"))
    y = float(os.getenv("Y", "37.5707"))
    radius = int(os.getenv("RADIUS", "1500"))
    with_dialogue = os.getenv("DIALOGUE", "0") == "1"

    print(f"▶ 시나리오 생성: 좌표=({x},{y}) 반경={radius}m 대사={'LLM' if with_dialogue else '고정'} 콘텐츠=ON\n")
    scn = await generate_basic_scenario(
        x, y, region="종로", radius_m=radius,
        with_dialogue=with_dialogue, with_content=True,
    )

    print(f"제목: {scn['title']}")
    print(f"ID:   {scn['scenario_id']}   (노드 {len(scn['node_sequence'])}개)\n")
    print("=" * 60)
    for n in scn["node_sequence"]:
        tag = " 🏁피날레" if n.get("is_finale") else ""
        print(f"\n[{n['order']}] {n.get('name')}{tag}   ({n.get('density_tier')})")
        if with_dialogue:
            print(f"    🧙 {n.get('npc_dialogue')}")
        m = n.get("mission")
        if m:
            _show_mission(m)
        else:
            print("    (미션 없음)")
    print("\n" + "=" * 60)
    # 미션 타입 분포 한눈에
    types = [n["mission"]["type"] for n in scn["node_sequence"] if n.get("mission")]
    print("미션 타입 시퀀스:", " → ".join(types))

    if os.getenv("JSON") == "1":
        print("\n----- RAW JSON -----")
        print(json.dumps(scn, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
