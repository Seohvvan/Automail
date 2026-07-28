"""시트 저장 시 사람이 수동 입력한 값 보존을 위한 순수 병합 로직.

에이전트 메모리 상태를 시트에 덮어쓸 때, 메모리 이메일이 비어 있으면
시트의 기존 값을 지우지 않고 보존한다(승인 대기 중 수동 입력·재검색 실패 대비).
"""


def merge_email_column(mem_emails, sheet_emails):
    """인덱스별로 메모리 값 우선, 비어 있으면 시트 기존 값 채택."""
    n = max(len(mem_emails), len(sheet_emails))
    out = []
    for i in range(n):
        m = (mem_emails[i] if i < len(mem_emails) else "") or ""
        s = (sheet_emails[i] if i < len(sheet_emails) else "") or ""
        out.append(m.strip() or s.strip())
    return out
