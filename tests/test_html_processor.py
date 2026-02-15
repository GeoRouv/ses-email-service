"""Tests for HTML processing utilities."""

from app.utils.html_processor import (
    inject_tracking_pixel,
    inject_unsubscribe_link,
    process_email_html,
    rewrite_urls,
    sanitize_html,
)


class TestRewriteUrls:
    def test_rewrite_simple_link(self):
        html = '<a href="https://example.com">Click</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert "/api/track/click/msg-123?url=" in result
        assert "https%3A%2F%2Fexample.com" in result

    def test_skip_mailto(self):
        html = '<a href="mailto:user@example.com">Email</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert "mailto:user@example.com" in result
        assert "/api/track/click/" not in result

    def test_skip_tel(self):
        html = '<a href="tel:+1234567890">Call</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert "tel:+1234567890" in result

    def test_skip_anchor(self):
        html = '<a href="#section">Jump</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert '#section' in result

    def test_multiple_links(self):
        html = '<a href="https://a.com">A</a><a href="https://b.com">B</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert result.count("/api/track/click/") == 2

    def test_skip_already_tracked(self):
        html = '<a href="http://localhost:8000/api/track/click/msg-123?url=test">Link</a>'
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        # Should not double-rewrite
        assert result.count("/api/track/click/") == 1

    def test_no_links(self):
        html = "<p>No links here</p>"
        result = rewrite_urls(html, "msg-123", "http://localhost:8000")
        assert result == "<p>No links here</p>"


class TestInjectTrackingPixel:
    def test_inject_before_body_close(self):
        html = "<html><body><p>Content</p></body></html>"
        result = inject_tracking_pixel(html, "msg-123", "http://localhost:8000")
        assert "/api/track/open/msg-123" in result
        assert result.index("/api/track/open/") < result.index("</body>")

    def test_inject_without_body_tag(self):
        html = "<p>Content</p>"
        result = inject_tracking_pixel(html, "msg-123", "http://localhost:8000")
        assert "/api/track/open/msg-123" in result

    def test_pixel_attributes(self):
        html = "<body></body>"
        result = inject_tracking_pixel(html, "msg-123", "http://localhost:8000")
        assert 'width="1"' in result
        assert 'height="1"' in result
        assert 'style="display:none' in result


class TestInjectUnsubscribeLink:
    def test_inject_before_body(self):
        html = "<html><body><p>Content</p></body></html>"
        result = inject_unsubscribe_link(html, "http://localhost:8000/unsubscribe/token123")
        assert "Unsubscribe from these emails" in result
        assert "http://localhost:8000/unsubscribe/token123" in result

    def test_inject_without_body(self):
        html = "<p>Content</p>"
        result = inject_unsubscribe_link(html, "http://localhost:8000/unsubscribe/token123")
        assert "Unsubscribe" in result


class TestProcessEmailHtml:
    def test_full_processing(self):
        html = '<html><body><a href="https://example.com">Link</a></body></html>'
        result = process_email_html(
            html, "msg-123", "http://localhost:8000",
            unsubscribe_url="http://localhost:8000/unsubscribe/tok",
        )
        # URLs rewritten
        assert "/api/track/click/" in result
        # Unsubscribe link injected
        assert "Unsubscribe" in result
        # Tracking pixel injected
        assert "/api/track/open/" in result

    def test_processing_without_unsubscribe(self):
        html = '<html><body><p>Content</p></body></html>'
        result = process_email_html(html, "msg-123", "http://localhost:8000")
        assert "Unsubscribe" not in result
        assert "/api/track/open/" in result

    def test_unsubscribe_link_not_tracked(self):
        html = '<html><body><p>Content</p></body></html>'
        result = process_email_html(
            html, "msg-123", "http://localhost:8000",
            unsubscribe_url="http://localhost:8000/unsubscribe/tok",
        )
        # The unsubscribe URL should NOT be rewritten with tracking
        assert 'href="http://localhost:8000/unsubscribe/tok"' in result


class TestSanitizeHtml:
    def test_remove_script_tags(self):
        html = "<p>Safe</p><script>alert('xss')</script>"
        result = sanitize_html(html)
        assert "<script>" not in result
        assert "Safe" in result

    def test_remove_iframe(self):
        html = '<p>Safe</p><iframe src="evil.com"></iframe>'
        result = sanitize_html(html)
        assert "<iframe" not in result

    def test_keep_safe_tags(self):
        html = "<p>Safe <strong>content</strong></p>"
        result = sanitize_html(html)
        assert "<p>" in result
        assert "<strong>" in result
