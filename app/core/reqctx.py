# ============================================================
# [v1] 요청 컨텍스트 — 유저/요청ID를 요청 처리 전 구간에 흘린다
# pipeline: 공통 인프라 (로깅 상관관계)
# 구현(요약): contextvars에 user·req_id를 담아두면 logger가 모든 줄에 자동으로 붙인다.
#            운영 테스트에서 "이 에러가 누구 요청이었나"를 로그만 보고 답하려는 것.
#            asyncio 태스크 경계를 넘어 전파되므로(gather로 갈라진 LLM·TourAPI 호출 포함)
#            호출부마다 user를 인자로 넘기지 않아도 된다 — 기존 로그를 안 고쳐도 되는 이유.
#            ⚠️ ContextVar에 담는 건 '가변 객체 1개'다. 값을 직접 set 하면 그 변경이
#            자식 컨텍스트에만 남아, 미들웨어가 라우트에서 심은 user를 못 본다
#            (요청 완료 줄에 유저가 '-'로 찍히던 문제). 객체를 공유하고 필드를 바꾼다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
import contextvars
import uuid

_MAX_LABEL = 20        # 로그 열 정렬이 무너지지 않을 정도로만 자른다


class _Scope:
    """요청 1건의 식별자 묶음. 가변이라 어느 깊이에서 채워도 전체가 같이 본다."""

    __slots__ = ("user", "req")

    def __init__(self, user: str = "-", req: str = "-") -> None:
        self.user = user
        self.req = req


# 기본값 — 컨텍스트가 안 잡힌 경로(기동 로그·배치)에서도 포맷이 깨지지 않게.
_scope: contextvars.ContextVar[_Scope] = contextvars.ContextVar(
    "dokkaebi_scope", default=_Scope()
)


def new_request_id() -> str:
    """요청 1건을 식별할 짧은 id. 로그를 이걸로 묶어 한 요청의 전 구간을 따라간다."""
    return uuid.uuid4().hex[:8]


def bind_request(req_id: str | None = None) -> str:
    """요청 시작 시 호출. 새 Scope를 깔고 req_id를 심는다(유저는 나중에 채워진다)."""
    rid = req_id or new_request_id()
    _scope.set(_Scope(user="-", req=rid))
    return rid


def bind_user(user_id: str | None = None, user_name: str | None = None) -> str:
    """유저 식별자를 컨텍스트에 심는다. 이름이 있으면 이름을 우선 표시한다.

    서버(dokkaebi-server)는 현재 /v1/scenarios 에만 user_id를 실어 보낸다.
    대화 계열은 아직 안 보내므로(schemas의 user_id·user_name은 optional)
    그때는 "-"로 남는다 — 서버가 보내기 시작하면 자동으로 채워진다.
    """
    name, uid = (user_name or "").strip(), (user_id or "").strip()
    # 둘 다 있으면 "이름(id)"이 제일 좋지만, 길이에 걸려 잘리면 둘 다 못 읽게 된다
    # ("yeseul(guest_e6ea76f"). 그럴 땐 이름만 온전히 남긴다 — 사람이 찾는 건 이름이다.
    if name and uid:
        combined = f"{name}({uid})"
        label = combined if len(combined) <= _MAX_LABEL else name
    else:
        label = name or uid or "-"
    # set이 아니라 필드 변경 — 미들웨어(부모 컨텍스트)도 같은 객체를 보고 있어야 한다.
    _scope.get().user = label[:_MAX_LABEL]
    return _scope.get().user


def current_user() -> str:
    """지금 요청의 유저 라벨. 없으면 '-'."""
    return _scope.get().user


def current_request_id() -> str:
    """지금 요청의 id. 없으면 '-'."""
    return _scope.get().req


def reset() -> None:
    """컨텍스트 초기화 — 테스트에서 요청 간 값이 새는 것을 막는다."""
    _scope.set(_Scope())
