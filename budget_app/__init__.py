"""budget_app — 나만의 용돈 기입장 (Codyssey Mission B2-1).

파일 기반 콘솔 가계부. 계층은 cli → services → repository → models 한 방향이며,
errors와 decorators는 어느 계층에서나 사용한다 (AGENT.md 5장).
패키지를 가져오는 것만으로 프로그램을 실행하거나 저장 파일을 만들지는 않는다.
"""
from __future__ import annotations

# 패키지 버전은 한 곳에서 관리하여 다른 모듈에서도 같은 값을 참조할 수 있다.
__version__ = "0.1.0"
