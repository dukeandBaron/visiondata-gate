"""Native-origin exception requires the real desktop capability and local peer."""
import pytest
from fastapi.testclient import TestClient
from visiondata_gate.api import create_app
from visiondata_gate.product_service import ProductService

CAPABILITY = 'synthetic-native-startup-capability-47'

@pytest.mark.parametrize('origin,token,peer,forwarded,expected', [
    ('http://tauri.localhost', CAPABILITY, '127.0.0.1', False, 201),
    ('https://tauri.localhost', CAPABILITY, '127.0.0.1', False, 201),
    ('http://tauri.localhost', '', '127.0.0.1', False, 403),
    ('http://tauri.localhost', 'incorrect', '127.0.0.1', False, 403),
    ('https://untrusted.example', CAPABILITY, '127.0.0.1', False, 403),
    ('http://tauri.localhost', CAPABILITY, '192.0.2.1', False, 403),
    ('http://tauri.localhost', CAPABILITY, '127.0.0.1', True, 403),
])
def test_native_setup(tmp_path, monkeypatch, origin, token, peer, forwarded, expected):
    monkeypatch.setenv('VISIONDATA_DESKTOP_SESSION_TOKEN', CAPABILITY)
    monkeypatch.setenv('VISIONDATA_WEB_ORIGINS', 'http://tauri.localhost,https://tauri.localhost')
    monkeypatch.setenv('VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS', 'false')
    product = ProductService(tmp_path / 'product', recover_interrupted=False)
    headers = {'Origin': origin, 'Sec-Fetch-Site': 'cross-site', 'X-VisionData-Desktop-Token': token}
    if forwarded:
        headers['X-Forwarded-For'] = '127.0.0.1'
    try:
        with TestClient(create_app(product), client=(peer, 49123)) as client:
            response = client.post('/v1/identity/setup', headers=headers,
                json={'login_name': 'native-admin', 'display_name': 'Synthetic administrator', 'password': 'synthetic-password-for-test-42'})
            assert response.status_code == expected
    finally:
        product.close(wait=True)
