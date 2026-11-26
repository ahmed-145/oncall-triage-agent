import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from triage.publish_issue import issue_payload, publish


class PublishIssueTests(unittest.TestCase):
    def test_summary_excludes_untrusted_report_content(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "0123456789abcdef0123.md"
            report.write_text('private log @someone\n'
                              '<!-- triage-eval {"hypotheses": [["oom", 0.9]]} -->\n')
            payload = issue_payload(report)
        self.assertIn("memory limit", payload["body"])
        self.assertNotIn("private log", payload["body"])
        self.assertNotIn("@someone", payload["body"])

    def test_posts_with_operator_credentials(self):
        with patch("triage.publish_issue.urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.read.return_value = '{"html_url": "https://github.com/org/repo/issues/1"}'
            self.assertEqual(publish("org/repo", "test-token", {"title": "Incident"}),
                             "https://github.com/org/repo/issues/1")
            request = open_url.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.github.com/repos/org/repo/issues")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data), {"title": "Incident"})
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
