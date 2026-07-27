"""테스트 공통 설정: repo 루트를 import 경로에 추가하고 network 마커 등록."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: 인터넷 접속이 필요한 통합 테스트 (RUN_NETWORK_TESTS=1)")
