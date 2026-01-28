from duckduckgo_search import DDGS
import unittest

class TestDDGSBackend(unittest.TestCase):
    def test_text_search_api_backend(self):
        # Verify that backend='api' does not raise KeyError
        try:
            with DDGS() as ddgs:
                # We limit results to 1 to be fast
                results = list(ddgs.text("test", backend="api", max_results=1))
                print(f"Results found: {len(results)}")
        except Exception as e:
            self.fail(f"DDGS text search with backend='api' failed: {e}")

if __name__ == '__main__':
    unittest.main()
