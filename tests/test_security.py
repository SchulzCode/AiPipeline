from aipipe.security import scan_added_diff


def test_secret_scan_only_added_lines():
    diff = '''diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
-password = "old-secret-value"
+name = "safe"
+api_key = "abcdefghijklmnop"
'''
    findings = scan_added_diff(diff)
    assert len(findings) == 1
    assert "generic-secret" in findings[0]


def test_private_key_detected():
    diff = "+++ b/key.pem\n+-----BEGIN PRIVATE KEY-----\n"
    assert scan_added_diff(diff)
